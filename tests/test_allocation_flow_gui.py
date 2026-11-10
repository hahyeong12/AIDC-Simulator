"""v0.9-2b-1: 결과창 버튼 고정 배치와 배정 설정창의 실제 Tk 동작. 작성만 했으며 사용자 데스크톱 보호를 위해 아직 실행하지 않았습니다."""
import tempfile
import tkinter as tk
import unittest

from database import Database
from main import SimulatorApp, ModeSelection
from story_slots import StorySlots
from tests.support import dismiss_story_popups
from tests.test_chapter2 import start

SIZES = ((1000, 650), (1280, 680), (1366, 768))


class ResultButtonsGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.selector = ModeSelection(self.root, db_factory=lambda path: Database(':memory:'),
                                      story_slots=StorySlots(self.directory.name))
        self.app = self.selector.new_story(2); self.root.update()
        self.addCleanup(self.app.network.stop)
        dismiss_story_popups(self.app, self.root)
        self.app.session.confirm_chapter2_briefing()
        self.jp, self.us = self.app.session.story.chapter2.request_ids

    def finish(self, economy):
        s = self.app.session
        start(s, self.jp, 'performance')
        start(s, self.us, 'economy' if economy else 'performance')
        for _ in range(40):
            if s.story.chapter2.completed:
                break
            s.advance_time(10)

    def assert_buttons_visible(self):
        for width, height in SIZES:
            self.root.geometry(f'{width}x{height}'); self.root.update()
            self.app.chapter_window = None
            dialog = self.app.show_chapter_complete(); self.root.update()
            self.assertIn('retry', dialog.buttons)
            bottom = dialog.winfo_height()
            for key, button in dialog.buttons.items():
                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), dialog.winfo_rooty()+bottom, (width, key))
                self.assertTrue(button.winfo_ismapped(), key)
            dialog.destroy(); self.root.update()

    def test_success_result_keeps_retry_button_visible(self):
        self.finish(economy=True)
        self.assertEqual(self.app.session.chapter2_result()['mission'], 'success')
        self.assert_buttons_visible()

    def test_failed_result_keeps_retry_button_visible(self):
        self.finish(economy=False)
        self.assertEqual(self.app.session.chapter2_result()['mission'], 'failed')
        self.assert_buttons_visible()


class AllocationSettingsGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, seed=9, incident_chance=0)
        self.addCleanup(self.app.network.stop)
        self.app.session.deliver_next_request(); self.app.session.select(2); self.app.refresh(); self.root.update()

    def test_main_button_opens_settings_without_starting(self):
        self.app.action_buttons['start'].invoke(); self.root.update()
        self.assertTrue(self.app.allocation_window.winfo_exists())
        self.assertEqual((self.app.center.gpu_used, self.app.center.power_used), (0, 0))
        self.assertIn('배정 설정', self.app.action_buttons['start'].cget('text'))

    def test_start_is_disabled_until_a_plan_or_auto_is_chosen(self):
        d = self.app.open_allocation_plans(); self.root.update()
        self.assertEqual(d.start_button.cget('state'), 'disabled')
        d.start_button.invoke(); self.root.update()
        self.assertEqual(self.app.center.gpu_used, 0)
        d.auto_button.invoke(); self.root.update()
        self.assertEqual(d.start_button.cget('state'), 'normal')
        self.assertIn('시작 요약', d.summary_label.cget('text'))
        self.assertEqual(self.app.center.gpu_used, 0)

    def test_changing_mode_recomputes_plans_and_requires_a_new_choice(self):
        d = self.app.open_allocation_plans(); self.root.update()
        d.plan_buttons[0].invoke(); self.root.update()
        before = (self.app.session.minute, self.app.center.gpu_used, dict(self.app.session.servers.allocations))
        other = 'economy' if d.mode == 'performance' else 'performance'
        d.mode_buttons[other].invoke(); self.root.update()
        self.assertEqual(d.mode, other)
        self.assertEqual(self.app.plan_var.get(), other)
        self.assertEqual(before, (self.app.session.minute, self.app.center.gpu_used, dict(self.app.session.servers.allocations)))
        self.assertEqual(d.start_button.cget('state'), 'disabled')

    def test_final_start_applies_the_chosen_plan_once(self):
        d = self.app.open_allocation_plans(); self.root.update()
        parts = d.options[-1]
        d.plan_buttons[len(d.options)-1].invoke(); self.root.update()
        d.start_button.invoke(); self.root.update()
        self.assertEqual(self.app.session.current.server_allocations[-1].slices, parts)
        self.assertGreater(self.app.center.gpu_used, 0)

    def test_footer_buttons_stay_visible_on_small_windows(self):
        for width, height in SIZES:
            self.root.geometry(f'{width}x{height}'); self.root.update()
            d = self.app.open_allocation_plans(); self.root.update()
            for button in (d.start_button, d.close_button):
                self.assertTrue(button.winfo_ismapped())
                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), d.winfo_rooty()+d.winfo_height())
            d.destroy(); self.root.update()
            self.app.allocation_window = None


if __name__ == '__main__':
    unittest.main()
