"""Canvas HUD의 가용량·장비 상태·전력 경고·점등 타이머 검증."""
import tkinter as tk
from tkinter import font as tkfont
import unittest

from database import Database
from main import SimulatorApp
from ui import CYAN, AMBER, RED, CUSTOMER_COLORS


class ResourceHudTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, seed=9, incident_chance=0)
        self.app.network.stop()
        self.panel = self.app.resources
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()

    def finish_pulse(self):
        self.root.after(350, self.root.quit)
        self.root.mainloop()

    def test_all_available_counts_have_exactly_ten_equipment_slots(self):
        panel, center = self.panel, self.app.center
        for available in range(11):
            with self.subTest(available=available):
                center.gpu_used = 10-available
                panel.refresh()
                self.assertEqual(panel.gpu_numbers['available'].cget('text'), f'{available:02d}')
                self.assertEqual(len(panel.rack.find_withtag('slot')), 10)
                self.assertEqual(len(panel.rack.find_withtag('gpu-block')), 10)
                self.assertEqual(len(panel.rack.find_withtag('available')), available)
                self.assertEqual(len(panel.rack.find_withtag('used')), 10-available)
                for item in panel.rack.find_withtag('available'):
                    self.assertEqual(panel.rack.itemcget(item, 'fill'), CYAN)
                self.assertTrue(all(panel.rack.itemcget(item, 'text') == 'A'
                                    for item in panel.rack.find_withtag('available-state')))
        self.assertEqual(self.errors, [])

    def test_available_is_largest_number_and_zero_is_a_warning(self):
        sizes = {key:tkfont.Font(font=w.cget('font')).actual('size') for key,w in self.panel.gpu_numbers.items()}
        self.assertGreater(sizes['available'], sizes['total'])
        self.assertGreater(sizes['available'], sizes['used'])
        self.app.center.gpu_used = 10
        self.panel.refresh()
        self.assertEqual(self.panel.gpu_numbers['available'].cget('fg'), RED)
        title = self.panel.gpu_label
        number = self.panel.gpu_numbers['available']
        self.root.update()
        self.assertLessEqual(title.winfo_y()+title.winfo_height(), number.winfo_y())

    def test_actual_allocation_and_return_dim_and_relight_equipment(self):
        app, panel = self.app, self.panel
        app.choose_plan('economy')
        self.assertEqual(panel.gpu_numbers['available'].cget('text'), '06')
        self.assertEqual(len(panel.rack.find_withtag('available')), 6)
        self.assertEqual(len(panel.rack.find_withtag('used')), 4)
        self.assertEqual([panel.rack.itemcget(item, 'text') for item in panel.rack.find_withtag('used-state')], ['S']*4)
        self.assertIsNotNone(panel.pulse_timer)
        self.finish_pulse()
        self.assertIsNone(panel.pulse_timer)
        app.state.work_done = app.state.work_total-1
        app.advance_time(10)
        self.assertEqual(panel.gpu_numbers['available'].cget('text'), '10')
        self.assertEqual(len(panel.rack.find_withtag('available')), 10)
        self.assertTrue(panel.changed_slots)
        self.finish_pulse()
        self.assertFalse(panel.changed_slots)
        self.assertEqual(self.errors, [])

    def test_customer_leds_and_selected_owner_are_distinct_from_available(self):
        app, panel = self.app, self.panel
        app.next_request()
        app.next_request()
        for rid in (1, 2, 3):
            app.select_request(rid)
            app.choose_plan('economy')
        app.select_request(2)
        self.assertEqual(len(panel.rack.find_withtag('selected-owner')), 2)
        self.assertEqual([panel.rack.itemcget(item, 'text') for item in panel.rack.find_withtag('used-state')],
                         ['S']*4+['J']*2+['U']*4)
        for color, count in zip(CUSTOMER_COLORS, (4, 2, 4)):
            self.assertEqual(sum(panel.rack.itemcget(item, 'fill') == color for item in panel.rack.find_withtag('used')), count)
        self.assertEqual(panel.preview_title.cget('text'), '현재 작업 점유 자원')
        self.assertFalse(panel.rack.find_withtag('request-marker'))
        positions = list(panel.slot_owners)
        app.select_request(1)
        app.state.work_done = app.state.work_total-1
        app.advance_time(10)
        self.assertEqual(panel.slot_owners[:4], [None]*4)
        self.assertEqual(panel.slot_owners[4:], positions[4:])
        app.select_request(1)
        self.assertEqual(panel.gpu_numbers['available'].cget('text'), '04')

    def test_power_changes_colour_at_high_load_and_supply_limit(self):
        for used in range(11):
            with self.subTest(used=used):
                self.app.center.power_used = used
                self.panel.refresh()
                item = self.panel.power.find_withtag('power-used')[0]
                self.assertEqual(self.panel.power.itemcget(item, 'fill'), RED if used == 10 else AMBER if used >= 7 else CYAN)
                self.assertIn(f'사용 {used} / 가용 {10-used} / 총 10', self.panel.power_label.cget('text'))
                total = self.panel.power.coords(self.panel.power.find_withtag('power-total')[0])[2]
                self.assertAlmostEqual(self.panel.power.coords(item)[2]/total, used/10)

    def test_request_markers_and_warning_never_allocate_resources(self):
        app, panel = self.app, self.panel
        app.next_request()
        app.next_request()
        app.select_request(3)
        app.choose_plan('economy')
        app.select_request(1)
        before = (app.center.gpu_used, app.center.power_used, len(self.db.get_recent_records()))
        self.assertEqual(len(panel.rack.find_withtag('request-marker')), 6)
        self.assertEqual(panel.preview_frame.cget('highlightbackground'), RED)
        self.assertIn('GPU 7 필요 / 가용 6 → 부족 1', panel.preview.cget('text'))
        self.assertIn('고성능 모드 배정 불가', panel.preview.cget('text'))
        app.plan_var.set('economy')
        app.preview_plan()
        self.assertEqual(len(panel.rack.find_withtag('request-marker')), 4)
        self.assertIn('→ 잔여 2', panel.preview.cget('text'))
        self.assertEqual((app.center.gpu_used, app.center.power_used, len(self.db.get_recent_records())), before)

    def test_repeated_refresh_and_mode_switch_do_not_add_animation_timers(self):
        panel = self.panel
        self.app.choose_plan('economy')
        timer = panel.pulse_timer
        items, children = len(panel.rack.find_all()), len(panel.rack.winfo_children())
        for _ in range(250):
            panel.refresh('economy')
            panel.refresh('performance')
        self.assertEqual(panel.pulse_timer, timer)
        self.assertEqual(len(panel.rack.find_all()), items)
        self.assertEqual(len(panel.rack.winfo_children()), children)
        self.finish_pulse()
        self.assertIsNone(panel.pulse_timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(self.errors, [])

    def test_new_usage_cancels_previous_pulse_and_destroy_cancels_last_timer(self):
        panel = self.panel
        self.app.choose_plan('economy')
        previous = panel.pulse_timer
        self.app.next_request()
        self.app.select_request(2)
        self.app.choose_plan('economy')
        self.assertNotEqual(panel.pulse_timer, previous)
        self.assertNotIn(previous, self.root.tk.call('after', 'info'))
        timer = panel.pulse_timer
        panel.destroy()
        self.root.update()
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(self.errors, [])

    def test_hud_fits_laptop_and_minimum_window_without_small_numeric_labels(self):
        app, panel = self.app, self.panel
        for width, height in ((1366,768), (1280,680), (1000,650)):
            self.root.geometry(f'{width}x{height}')
            self.root.update()
            self.assertEqual(len(panel.rack.find_withtag('slot')), 10)
            for widget in (panel.rack, panel.power, panel.preview, panel.preview_frame,
                           *panel.gpu_numbers.values(), *app.action_buttons.values()):
                with self.subTest(size=(width,height), widget=str(widget)):
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+width)
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+height)
            self.assertGreaterEqual(panel.preview.winfo_height(), panel.preview.winfo_reqheight())
            for canvas in (panel.rack, panel.power):
                for item in canvas.find_all():
                    if canvas.type(item) == 'text':
                        self.assertGreaterEqual(tkfont.Font(font=canvas.itemcget(item,'font')).actual('size'), 10)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
