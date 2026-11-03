"""게임/DB와 분리된 서버실 시안의 샘플 일관성과 실제 Tk 상호작용 검증."""
import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import tkinter as tk
import unittest

from server_ui_preview import (CUSTOMERS, EMPTY, RED, SCENARIOS, SERVERS,
                               SampleUsage, Scenario, ServerPreviewApp, animate_hardware, server_status)


class PreviewSampleTests(unittest.TestCase):
    def test_sample_server_capacities_are_exactly_ten_each(self):
        self.assertEqual([(s.key, s.gpu, s.power) for s in SERVERS],
                         [('A', 4, 4), ('B', 3, 2), ('C', 2, 3), ('D', 1, 1)])
        self.assertEqual(sum(s.gpu for s in SERVERS), 10)
        self.assertEqual(sum(s.power for s in SERVERS), 10)

    def test_every_snapshot_stays_within_each_capacity_and_matches_summary(self):
        for scene in SCENARIOS:
            with self.subTest(scene=scene.key):
                for spec, used in zip(SERVERS, scene.usage):
                    self.assertTrue(0 <= used.gpu <= spec.gpu)
                    self.assertTrue(0 <= used.power <= spec.power)
                    self.assertEqual(used.owner is not None, bool(used.gpu or used.power))
                summary = scene.summary()
                self.assertEqual(summary['gpu_available'], sum(s.gpu-u.gpu for s, u in zip(SERVERS, scene.usage)))
                self.assertEqual(summary['power_available'], sum(s.power-u.power for s, u in zip(SERVERS, scene.usage)))
                self.assertEqual(summary['gpu_used']+summary['gpu_available'], 10)
                self.assertEqual(summary['power_used']+summary['power_available'], 10)
                self.assertEqual(summary['jobs'], len({u.owner for u in scene.usage if u.owner}))

    def test_initial_assignment_parallel_and_return_are_consistent(self):
        scenes = {scene.key: scene for scene in SCENARIOS}
        for key, gpu, power, servers, jobs in (('initial', 10, 10, 0, 0), ('assigned', 7, 7, 1, 1),
                                               ('parallel', 5, 6, 2, 2), ('returned', 8, 9, 1, 1)):
            summary = scenes[key].summary()
            self.assertEqual((summary['gpu_available'], summary['power_available'], summary['active_servers'], summary['jobs']),
                             (gpu, power, servers, jobs))
        self.assertEqual(scenes['returned'].usage[0], EMPTY)
        self.assertEqual(scenes['returned'].usage[1], scenes['parallel'].usage[1])
        self.assertEqual(scenes['returned'].completed, ('sg',))
        self.assertTrue(all(server_status(u) == 'IDLE' for u in scenes['initial'].usage))

    def test_distributed_example_is_one_job_with_seven_gpu_and_power(self):
        scene = next(s for s in SCENARIOS if s.key == 'distributed')
        summary = scene.summary()
        self.assertEqual((summary['gpu_used'], summary['power_used']), (7, 7))
        self.assertEqual((summary['active_servers'], summary['jobs']), (3, 1))
        self.assertEqual([(u.gpu, u.power) for u in scene.usage], [(4, 4), (1, 1), (2, 2), (0, 0)])

    def test_fault_sample_keeps_occupancy_and_counts_one_fault(self):
        scene = next(s for s in SCENARIOS if s.key == 'fault')
        self.assertEqual(scene.summary()['fault_servers'], 1)
        self.assertEqual(scene.summary()['jobs'], 3)
        self.assertEqual(server_status(scene.usage[2]), 'FAULT')
        self.assertEqual(scene.usage[2].owner, 'us')

    def test_invalid_sample_usage_is_rejected(self):
        for usage in (SampleUsage('sg', 5, 1), SampleUsage('sg', 1, 5), SampleUsage('sg', -1, 1),
                      SampleUsage(None, 1, 1), SampleUsage('unknown', 1, 1), SampleUsage('sg'),
                      SampleUsage('sg', True, 1), SampleUsage('sg', 1.5, 1)):
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                Scenario('bad', 'bad', '', (usage, EMPTY, EMPTY, EMPTY))
        with self.assertRaises(ValueError):
            Scenario('bad', 'bad', '', (EMPTY,))
        with self.assertRaises(ValueError):
            Scenario('bad', 'bad', '', (SampleUsage('sg', 1, 1), EMPTY, EMPTY, EMPTY), ('sg',))

    def test_samples_are_immutable_and_import_only_standard_library(self):
        with self.assertRaises(FrozenInstanceError):
            SCENARIOS[0].usage = ()
        with self.assertRaises(FrozenInstanceError):
            SERVERS[0].gpu = 20
        source = Path(__file__).resolve().parents[1]/'server_ui_preview.py'
        imports = [node for node in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
                   if isinstance(node, (ast.Import, ast.ImportFrom))]
        modules = {node.module if isinstance(node, ast.ImportFrom) else alias.name
                   for node in imports for alias in node.names}
        self.assertEqual(modules, {'tkinter', 'dataclasses', 'server_widgets'})


class PreviewGuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.app = ServerPreviewApp(self.root)
        self.addCleanup(self.app.close)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()

    def test_scenario_buttons_apply_fixed_snapshots_and_return_customer_resources(self):
        a = self.app
        for key in ('assigned', 'parallel', 'returned'):
            a.scenario_buttons[key].invoke()
            self.root.update()
            self.assertEqual(a.scenario.key, key)
        self.assertEqual(a.overview.scenario.summary()['gpu_available'], 8)
        self.assertEqual(a.details.values['owner'], '없음')
        self.assertEqual(a.details.values['gpu_available'], 4)
        self.assertEqual(a.details.values['power_available'], 4)
        labels = [a.room.itemcget(item, 'text') for item in a.room.find_withtag('owner-label')]
        self.assertFalse(any('Merlion AI' in label for label in labels))
        self.assertTrue(any('Sakura Robotics' in label for label in labels))
        self.assertEqual(self.errors, [])

    def test_clicking_each_rack_selects_matching_server_details(self):
        a = self.app
        a.set_scenario('fault')
        self.root.update()
        for spec, used in zip(SERVERS, a.scenario.usage):
            x1, y1, x2, y2 = a.room.rack_bounds[spec.key]
            x, y = int((x1+x2)/2), int((y1+y2)/2)
            a.room.event_generate('<Motion>', x=x, y=y)
            a.room.event_generate('<Button-1>', x=x, y=y)
            self.root.update()
            self.assertEqual(a.selected, spec.key)
            self.assertEqual(a.details.values['name'], spec.name)
            self.assertEqual(a.details.values['gpu_available'], spec.gpu-used.gpu)
            self.assertEqual(a.details.values['power_available'], spec.power-used.power)
            self.assertEqual(a.details.values['status'], server_status(used))
        self.assertEqual(self.errors, [])

    def test_details_show_actual_sample_owner_and_all_resource_values(self):
        a = self.app
        for scene in SCENARIOS:
            a.set_scenario(scene.key)
            for spec, used in zip(SERVERS, scene.usage):
                a.select_server(spec.key)
                values = a.details.values
                self.assertEqual((values['gpu_total'], values['gpu_used'], values['gpu_available']),
                                 (spec.gpu, used.gpu, spec.gpu-used.gpu))
                self.assertEqual((values['power_total'], values['power_used'], values['power_available']),
                                 (spec.power, used.power, spec.power-used.power))
                expected = CUSTOMERS[used.owner].company if used.owner else '없음'
                self.assertEqual(a.details.itemcget(a.details.find_withtag('detail-owner')[0], 'text'), expected)
                self.assertEqual(len(a.details.find_withtag('detail-gpu-slot')), spec.gpu)
        a.set_scenario('initial')
        labels = [a.room.itemcget(item, 'text') for item in a.room.find_withtag('owner-label')]
        self.assertFalse(any(c.company in label for c in CUSTOMERS.values() for label in labels))

    def test_three_window_sizes_keep_text_gauges_and_controls_inside_panels(self):
        a = self.app
        for size, columns in (('1280x680', 4), ('1366x768', 4), ('1000x650', 2)):
            self.root.geometry(size)
            self.root.update()
            for scene in SCENARIOS:
                a.set_scenario(scene.key)
                self.root.update()
                self.assertEqual(a.room.columns, columns)
                for canvas in (a.overview, a.inbox, a.room, a.details):
                    for item in canvas.find_all():
                        if canvas.type(item) != 'text':
                            continue
                        with self.subTest(size=size, scene=scene.key, text=canvas.itemcget(item, 'text')):
                            x1, y1, x2, y2 = canvas.bbox(item)
                            self.assertGreaterEqual(x1, 0)
                            self.assertGreaterEqual(y1, 0)
                            self.assertLessEqual(x2, canvas.winfo_width())
                            self.assertLessEqual(y2, canvas.winfo_height())
                for widget in (a.overview, a.inbox, a.room, a.details, a.scenario_note, *a.scenario_buttons.values()):
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
                    self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
                self.assertEqual(len(a.room.find_withtag('gpu-slot')), 10)
                self.assertEqual(len(a.room.find_withtag('available-gpu')), scene.summary()['gpu_available'])
        self.assertEqual(self.errors, [])

    def test_full_allocation_is_normal_and_selection_survives_scenario_changes(self):
        a = self.app
        a.select_server('C')
        a.set_scenario('distributed')
        self.assertEqual(a.selected, 'C')
        self.assertEqual(a.details.values['gpu_available'], 0)
        hint = a.details.find_withtag('gpu-availability-hint')[0]
        self.assertEqual(a.details.itemcget(hint, 'text'), '전체 배정')
        self.assertNotEqual(a.details.itemcget(hint, 'fill'), RED)
        self.assertFalse(a.details.find_withtag('gpu-fault'))
        a.set_scenario('initial')
        self.assertEqual(a.details.values['gpu_available'], 2)
        self.assertEqual(a.details.values['owner'], '없음')

    def test_refresh_and_scenario_changes_do_not_accumulate_animation_timers(self):
        a = self.app
        timer = a.animation_id
        for _ in range(80):
            for scene in SCENARIOS:
                a.set_scenario(scene.key)
        self.assertEqual(a.animation_id, timer)
        self.assertEqual(self.root.tk.call('after', 'info').count(timer), 1)
        self.assertEqual(a.scenario.summary()['gpu_used'], 7)
        a.room.animate()
        self.assertEqual(a.scenario.summary()['gpu_used'], 7)
        self.assertEqual(self.errors, [])

    def test_destroying_window_cancels_its_animation(self):
        window = tk.Toplevel(self.root)
        preview = ServerPreviewApp(window)
        timer = preview.animation_id
        window.destroy()
        self.assertTrue(preview.closed)
        self.assertIsNone(preview.animation_id)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))

    def test_unknown_scenario_or_server_does_not_change_selection(self):
        a = self.app
        before = a.scenario, a.selected
        with self.assertRaises(ValueError):
            a.set_scenario('missing')
        with self.assertRaises(ValueError):
            a.select_server('missing')
        self.assertEqual((a.scenario, a.selected), before)

    def test_each_gpu_state_matches_in_summary_racks_and_details(self):
        a = self.app
        for scene in SCENARIOS:
            a.set_scenario(scene.key)
            expected = {'available': 0, 'busy': 0, 'fault': 0}
            for spec, used in zip(SERVERS, scene.usage):
                if used.fault:
                    expected['fault'] += spec.gpu
                else:
                    expected['busy'] += used.gpu
                    expected['available'] += spec.gpu-used.gpu
                a.select_server(spec.key)
                self.assertEqual(len(a.details.find_withtag('gpu-fault')), spec.gpu if used.fault else 0)
                labels = [a.details.itemcget(i, 'text') for i in a.details.find_withtag('gpu-owner-code')]
                self.assertEqual(sum(used.owner.upper() in value for value in labels) if used.owner else 0,
                                 0 if used.fault else used.gpu)
            for state, count in expected.items():
                with self.subTest(scene=scene.key, state=state):
                    self.assertEqual(len(a.overview.find_withtag('gpu-'+state)), count)
                    self.assertEqual(len(a.room.find_withtag('gpu-'+state)), count)
            self.assertEqual(len(a.room.find_withtag('gpu-empty')), 6)
            self.assertEqual(len(a.overview.find_withtag('summary-gpu')), 10)
            self.assertFalse(a.overview.find_withtag('gpu-fan'))

    def test_leds_and_circuits_animate_without_fans_or_fault_activity(self):
        a = self.app
        a.set_scenario('fault')
        room = a.room
        self.assertFalse(room.find_withtag('gpu-rotor'))
        self.assertFalse(room.find_withtag('gpu-fan'))
        traces = {i:(state, room.itemcget(i, 'fill')) for i, state, _ in room.gpu_traces}
        leds = {i:(state, room.itemcget(i, 'fill')) for i, state in room.gpu_leds}
        items = room.find_all()
        animate_hardware(room, 2)
        for trace, (state, old_color) in traces.items():
            if state in ('available', 'busy'):
                self.assertNotEqual(room.itemcget(trace, 'fill'), old_color)
            else:
                self.assertEqual(room.itemcget(trace, 'fill'), old_color)
        for led, (state, old_color) in leds.items():
            if state == 'available':
                self.assertNotEqual(room.itemcget(led, 'fill'), old_color)
            else:
                self.assertEqual(room.itemcget(led, 'fill'), old_color)
            if state == 'fault':
                self.assertEqual(room.itemcget(led, 'fill'), RED)
            if state == 'empty':
                self.assertEqual(room.itemcget(led, 'fill'), '#263342')
        self.assertEqual(room.find_all(), items)

    def test_hardware_shapes_stay_inside_each_rack_at_all_window_sizes(self):
        a = self.app
        a.set_scenario('fault')
        for size in ('1280x680', '1366x768', '1000x650'):
            self.root.geometry(size)
            self.root.update()
            for key, (left, top, right, bottom) in a.room.rack_bounds.items():
                for item in a.room.find_withtag('server-'+key):
                    tags = a.room.gettags(item)
                    if not any(tag.startswith('gpu-') or tag == 'stopped-fan' for tag in tags):
                        continue
                    with self.subTest(size=size, server=key, item=item):
                        x1, y1, x2, y2 = a.room.bbox(item)
                        self.assertGreaterEqual(x1, left)
                        self.assertGreaterEqual(y1, top)
                        self.assertLessEqual(x2, right)
                        self.assertLessEqual(y2, bottom)

    def test_live_animation_keeps_one_timer_and_does_not_change_sample_resources(self):
        a = self.app
        a.set_scenario('parallel')
        snapshot = a.scenario.summary()
        old_timer = a.animation_id
        self.root.after(1000, self.root.quit)
        self.root.mainloop()
        timers = self.root.tk.call('after', 'info')
        self.assertNotEqual(a.animation_id, old_timer)
        self.assertNotIn(old_timer, timers)
        self.assertEqual(timers.count(a.animation_id), 1)
        self.assertEqual(a.scenario.summary(), snapshot)
        self.assertEqual(self.errors, [])

    def test_chip_geometry_is_small_and_fanless_at_every_resolution(self):
        a = self.app
        a.set_scenario('fault')
        chip_sizes = []
        for size in ('1000x650', '1280x680', '1366x768'):
            self.root.geometry(size)
            self.root.update()
            for canvas in (a.overview, a.room, a.details):
                self.assertFalse(canvas.find_withtag('gpu-fan'))
                self.assertFalse(canvas.find_withtag('gpu-rotor'))
                self.assertFalse(any(canvas.type(i) == 'arc' for i in canvas.find_all()))
                for body in canvas.find_withtag('gpu-body'):
                    x1, y1, x2, y2 = canvas.bbox(body)
                    self.assertLessEqual(x2-x1, 66)
                    self.assertLessEqual(y2-y1, 29)
            chip = a.room.find_withtag('gpu-die')[0]
            x1, y1, x2, y2 = a.room.bbox(chip)
            chip_sizes.append((x2-x1, y2-y1))
        self.assertEqual(len(set(chip_sizes)), 1)

    def test_fault_label_is_separate_from_normal_customer_allocation(self):
        a = self.app
        a.set_scenario('fault')
        a.select_server('C')
        labels = [a.details.itemcget(i, 'text') for i in a.details.find_withtag('gpu-state-label')]
        self.assertEqual(labels, ['FAULT', 'FAULT'])
        self.assertEqual(a.details.values['owner'], 'Northstar AI')
        a.select_server('A')
        labels = [a.details.itemcget(i, 'text') for i in a.details.find_withtag('gpu-state-label')]
        self.assertEqual(labels, ['SG', 'SG', 'SG', 'ON'])
        self.assertEqual(a.details.values['status'], 'ACTIVE')
        self.assertFalse(a.details.find_withtag('gpu-fault'))

    def test_request_comparison_reports_one_missing_gpu_without_allocating(self):
        a = self.app
        a.select_server('C')
        before = a.scenario.summary()
        a.compare_toggle.invoke()
        hint = a.details.find_withtag('gpu-availability-hint')[0]
        self.assertEqual(a.details.itemcget(hint, 'text'), '요청3 · 1개 부족')
        self.assertEqual(a.details.itemcget(hint, 'fill'), RED)
        self.assertEqual(a.details.values['gpu_shortage'], 1)
        self.assertEqual(a.details.values['power_shortage'], 0)
        self.assertEqual(a.details.values['status'], 'IDLE')
        self.assertEqual(a.scenario.summary(), before)
        a.compare_toggle.invoke()
        self.assertEqual(a.details.itemcget(a.details.find_withtag('gpu-availability-hint')[0], 'text'), '모두 가용')
        self.assertEqual(a.details.values['gpu_shortage'], 0)

    def test_zero_power_is_neutral_until_compared_with_a_new_request(self):
        a = self.app
        a.set_scenario('distributed')
        self.assertEqual(a.details.values['power_available'], 0)
        frame = a.details.find_withtag('battery-frame')[0]
        self.assertNotEqual(a.details.itemcget(frame, 'outline'), RED)
        self.assertEqual(a.details.values['status'], 'ACTIVE')
        self.assertEqual(a.details.values['power_shortage'], 0)
        a.set_comparison(True)
        self.assertEqual(a.details.values['power_shortage'], 2)
        self.assertEqual(a.details.itemcget(a.details.find_withtag('battery-frame')[0], 'outline'), RED)
        self.assertEqual(a.details.values['status'], 'ACTIVE')
        a.set_comparison(False)
        self.assertNotEqual(a.details.itemcget(a.details.find_withtag('battery-frame')[0], 'outline'), RED)

    def test_battery_percentage_explicitly_means_available_power(self):
        a = self.app
        for scene in SCENARIOS:
            a.set_scenario(scene.key)
            for spec, used in zip(SERVERS, scene.usage):
                a.select_server(spec.key)
                percentage = a.details.find_withtag('battery-percent')[0]
                self.assertEqual(a.details.itemcget(percentage, 'text'),
                                 f'가용 {(spec.power-used.power)/spec.power:.0%}')
                self.assertEqual(a.details.values['power_available']+a.details.values['power_used'], spec.power)

    def test_request_comparison_and_header_fit_all_three_sizes(self):
        a = self.app
        a.set_comparison(True)
        for size in ('1000x650', '1280x680', '1366x768'):
            self.root.geometry(size)
            for scene in ('initial', 'distributed', 'fault'):
                a.set_scenario(scene)
                for spec in SERVERS:
                    a.select_server(spec.key)
                    self.root.update()
                    for canvas in (a.details, a.room):
                        for item in canvas.find_all():
                            if canvas.type(item) == 'text':
                                with self.subTest(size=size, scene=scene, server=spec.key, text=canvas.itemcget(item, 'text')):
                                    x1, y1, x2, y2 = canvas.bbox(item)
                                    self.assertGreaterEqual(x1, 0)
                                    self.assertGreaterEqual(y1, 0)
                                    self.assertLessEqual(x2, canvas.winfo_width())
                                    self.assertLessEqual(y2, canvas.winfo_height())
                    self.assertGreaterEqual(a.compare_toggle.winfo_width(), a.compare_toggle.winfo_reqwidth())
                    self.assertLessEqual(a.compare_toggle.winfo_rootx()+a.compare_toggle.winfo_width(),
                                         self.root.winfo_rootx()+self.root.winfo_width())
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
