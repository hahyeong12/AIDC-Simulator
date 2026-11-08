"""v0.9-1c: 실제 Tk 배치, 행동별 강조, 디스크 복원과 예약 정리."""
from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from main import SimulatorApp
from server_widgets import RED, animate_hardware
from session import GameSession
from story_dialog import StoryDialogueDialog, StoryReviewDialog
from tests.test_story import gameplay
from tests.support import dismiss_story_popups
from window_placement import centered_bounds, work_area


class PlacementTests(unittest.TestCase):
    def test_center_on_offset_parent(self):
        self.assertEqual(centered_bounds((300, 100, 1000, 650), (0, 0, 1920, 1040), (820, 470)),
                         (820, 470, 390, 190))

    def test_center_on_secondary_monitor(self):
        self.assertEqual(centered_bounds((2100, 100, 1000, 650), (1920, 0, 3840, 1040), (820, 470)),
                         (820, 470, 2190, 190))

    def test_negative_monitor_coordinates(self):
        self.assertEqual(centered_bounds((-1800, 100, 1000, 650), (-1920, 0, 0, 1040), (820, 470)),
                         (820, 470, -1710, 190))

    def test_partially_offscreen_parent_clamps_entire_frame(self):
        w, h, x, y = centered_bounds((900, 600, 1000, 650), (0, 0, 1366, 728), (820, 470))
        self.assertGreaterEqual(x, 12); self.assertGreaterEqual(y, 12)
        self.assertLessEqual(x+w+16, 1366-12)
        self.assertLessEqual(y+h+40, 728-12)

    def test_smaller_work_area_reduces_size(self):
        w, h, x, y = centered_bounds((0, 0, 640, 400), (0, 0, 640, 400), (820, 470))
        self.assertLess(w, 640); self.assertLess(h, 400)
        self.assertGreaterEqual(x, 0); self.assertGreaterEqual(y, 0)


class TutorialGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, mode='story', seed=9)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()
        self.h = self.app.tutorial_highlight

    def close_guide(self):
        dismiss_story_popups(self.app, self.root)

    def arrival(self):
        self.app.story_window.skip_button.invoke()
        self.app.story_window.next_button.invoke()
        self.close_guide()

    def resources(self):
        self.arrival(); self.app.network.select('A'); self.close_guide()

    def request(self):
        self.resources(); self.app.resource_confirm_button.invoke(); self.close_guide()

    def preview(self):
        self.request(); self.app.arrival_open_button.invoke()
        self.app.message_window.destroy(); self.root.update(); self.close_guide()

    def compare(self):
        self.preview()
        self.app.resources.book.select(self.app.resources.review_frame)
        self.root.update(); self.close_guide()
        self.app.resources.compare_button.invoke(); self.root.update()
        return self.app.allocation_window

    def allocation(self):
        d = self.compare()
        d.plan_buttons[0].invoke(); self.root.update()
        d.close_button.invoke(); self.root.update(); self.close_guide()

    def running(self):
        self.allocation(); self.app.action_buttons['start'].invoke(); self.close_guide()

    def assert_target(self, key, widget):
        self.assertEqual(self.h.key, key)
        self.assertIs(self.h.target, widget)
        self.assertTrue(widget.winfo_ismapped())
        self.assertIsNotNone(self.h.timer)
        self.assertEqual(self.errors, [])

    def test_guide_close_alone_cannot_complete_arrival(self):
        before = deepcopy(self.app.session.story.payload()), gameplay(self.app.session)
        self.close_guide()
        self.assertEqual((self.app.session.story.payload(), gameplay(self.app.session)), before)
        self.assertIsNone(self.h.target)

    def test_only_server_a_outer_border_pulses_and_wrong_server_does_not_complete(self):
        self.arrival()
        self.assert_target('server', self.app.network)
        self.assertEqual(len(self.app.network.find_withtag('tutorial-highlight')), 1)
        self.assertIn('server-A', self.app.network.gettags(self.app.network.find_withtag('tutorial-highlight')[0]))
        self.app.network.select('B'); self.root.update()
        self.assertEqual(self.app.session.story.step, 'server')
        self.assert_target('server', self.app.network)

    def test_real_server_a_click_removes_rack_highlight_before_resource_guide(self):
        self.arrival()
        x, y, right, bottom = self.app.network.rack_bounds['A']
        self.app.network.event_generate('<Button-1>', x=int((x+right)/2), y=int((y+bottom)/2))
        self.root.update()
        self.assertEqual(self.app.session.story.step, 'resources')
        self.assertFalse(self.app.network.find_withtag('tutorial-highlight'))
        self.assertIsNone(self.h.timer)
        self.assertTrue(self.app.feedback_window.winfo_exists())

    def test_resource_confirmation_button_and_actual_fact(self):
        self.resources()
        self.assert_target('resources', self.app.resource_confirm_button)
        self.assertFalse(self.app.session.story.resources_confirmed)
        self.app.resource_confirm_button.invoke(); self.root.update()
        self.assertTrue(self.app.session.story.resources_confirmed)
        self.assertIsNone(self.h.target)

    def test_request_button_and_customer_dialogue_suspend(self):
        self.request()
        self.assert_target('request', self.app.arrival_open_button)
        self.assertFalse(self.app.session.story.request_read)
        self.app.arrival_open_button.invoke(); self.root.update()
        self.assertTrue(self.app.session.story.request_read)
        self.assertIsNone(self.h.timer)
        self.app.message_window.destroy(); self.root.update(); self.close_guide()
        self.assert_target('preview', self.app.resources)

    def test_preview_tab_is_highlighted_from_inspector_without_completing_preview(self):
        self.preview()
        self.assertEqual(self.app.resources.book.select(), str(self.app.resources.inspector_frame))
        self.assert_target('preview', self.app.resources)
        self.assertEqual(len(self.app.resources.tutorial_tab_edges), 4)
        self.assertTrue(all(e.winfo_ismapped() for e in self.app.resources.tutorial_tab_edges))
        self.assertFalse(self.app.session.story.preview_confirmed)
        self.assertEqual(self.app.center.gpu_used, 0)

    def test_compare_dialog_start_is_single_target_and_does_not_allocate_on_view(self):
        self.preview()
        self.assert_target('preview', self.app.resources)
        self.app.resources.book.select(self.app.resources.review_frame); self.root.update(); self.close_guide()
        # 탭을 연 뒤에는 탭이 아니라 실제 비교 버튼을 가리킵니다.
        self.assert_target('compare', self.app.resources.compare_button)
        self.assertFalse(self.app.session.story.preview_confirmed)
        self.app.resources.compare_button.invoke(); self.root.update()
        d = self.app.allocation_window
        # 비교 창을 열기만 했을 때는 창 안의 계획 선택 버튼 하나만 가리킵니다.
        self.assert_target('plan', d.plan_buttons[0])
        self.assertIs(d.plan_buttons[0].winfo_toplevel(), d)
        self.assertFalse(self.app.session.story.preview_confirmed)
        self.assertEqual(self.app.center.gpu_used, 0)
        d.close_button.invoke(); self.root.update(); self.close_guide()
        self.assertEqual(self.app.session.story.step, 'preview')
        self.assert_target('compare', self.app.resources.compare_button)
        self.app.resources.compare_button.invoke(); self.root.update()
        d = self.app.allocation_window
        d.plan_buttons[0].invoke(); self.root.update()
        self.assertTrue(self.app.session.story.preview_confirmed)
        self.assert_target('allocation', d.start_button)
        self.assertEqual(self.app.center.gpu_used, 0)
        d.close_button.invoke(); self.root.update()
        self.assertIsNone(self.h.target)
        self.close_guide()
        self.assert_target('allocation', self.app.action_buttons['start'])

    def test_auto_recommendation_needs_explicit_click_to_count_as_review(self):
        d = self.compare()
        self.assertEqual(d.selection.get(), -1)
        self.assertFalse(self.app.session.story.preview_confirmed)
        d.auto_button.invoke(); self.root.update()
        self.assertTrue(self.app.session.story.preview_confirmed)

    def test_inspector_tab_is_pointed_at_when_resources_step_is_on_preview_tab(self):
        self.arrival(); self.app.network.select('A'); self.close_guide()
        self.app.resources.show_preview(); self.root.update()
        self.assert_target('inspector', self.app.resources)
        self.assertEqual(len(self.app.resources.tutorial_tab_edges), 4)
        self.app.resources.book.select(self.app.resources.inspector_frame); self.root.update()
        self.assert_target('resources', self.app.resource_confirm_button)

    def test_start_button_recreated_by_refresh_rebinds_without_extra_timers(self):
        self.allocation()
        old, timer = self.h.target, self.h.timer
        for _ in range(5): self.app.refresh()
        self.root.update()
        self.assertFalse(old.winfo_exists())
        self.assert_target('allocation', self.app.action_buttons['start'])
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        callbacks = [self.root.tk.call('after', 'info', t)[0] for t in self.root.tk.call('after', 'info')]
        self.assertEqual(sum('_paint' in c for c in callbacks), 1)

    def test_disallowed_mode_points_to_allowed_mode_then_start(self):
        self.allocation()
        self.app.plan_var.set('economy'); self.app.preview_plan(show_preview=True); self.root.update()
        self.assert_target('allocation', self.app.mode_buttons['performance'])
        self.assertEqual(self.app.action_buttons['start'].cget('state'), 'disabled')
        self.app.mode_buttons['performance'].invoke(); self.root.update()
        self.assert_target('allocation', self.app.action_buttons['start'])

    def test_time_requires_work_and_operations_reopens_real_information(self):
        self.running()
        self.assert_target('time', self.app.time_group)
        self.assertEqual(self.app.state.work_done, 0)
        self.app.time_buttons[10].invoke(); self.root.update()
        self.assertGreater(self.app.state.work_done, 0)
        self.assertIsNone(self.h.timer)
        self.close_guide()
        self.assert_target('operations', self.app.action_buttons['operations'])
        self.app.action_buttons['operations'].invoke(); self.root.update()
        self.assertFalse(self.app.session.story.operations_confirmed)
        self.assertIsNone(self.h.timer)
        self.app.story_window.skip_button.invoke()
        self.assertIn('서버별 잔여 자원', self.app.story_window.full_text)
        self.app.story_window.next_button.invoke(); self.root.update(); self.close_guide()
        self.assertTrue(self.app.session.story.operations_confirmed)
        self.assert_target('work_complete', self.app.time_group)
        self.app.time_buttons[60].invoke(); self.app.time_buttons[60].invoke(); self.root.update()
        self.assertTrue(self.app.session.story.chapter_completed)
        self.assertIsNone(self.h.timer); self.assertIsNone(self.h.target)

    def _time_button_advances_step(self, minutes):
        self.running()
        self.assert_target('time', self.app.time_group)
        self.assertEqual({b.master for b in self.app.time_buttons.values()}, {self.app.time_group})
        self.assertEqual(self.app.state.work_done, 0)
        self.app.time_buttons[minutes].invoke(); self.root.update(); self.close_guide()
        story = self.app.session.story
        self.assertGreater(self.app.state.work_done, 0)
        self.assertIn('time', story.completed_steps)
        self.assertEqual(self.errors, [])
        return story

    def test_plus_10_is_valid_time_action(self):
        self.assertEqual(self._time_button_advances_step(10).step, 'operations')

    def test_plus_30_is_valid_time_action(self):
        self.assertEqual(self._time_button_advances_step(30).step, 'operations')

    def test_plus_60_is_valid_time_action_even_if_job_finishes_at_once(self):
        story = self._time_button_advances_step(60)
        # 한 번에 끝나도 단계가 꼬이지 않고 실제 결과로 Chapter 완료까지 이어집니다.
        self.assertEqual(story.step, 'operations')
        for _ in range(4):
            if self.app.state.phase == 'finished':
                break
            self.app.time_buttons[60].invoke(); self.root.update(); self.close_guide()
        self.assertTrue(story.chapter_completed)
        self.assertEqual(story.step, 'complete')
        self.assertTrue(story.tutorial_completed)
        self.assertIsNone(self.h.target)
        self.assertEqual(self.errors, [])

    def test_time_group_pointer_text_and_pointer_click_uses_real_button(self):
        self.running()
        self.assertIn('시간 버튼', self.h.pointer.cget('text'))
        self.h.activate(); self.root.update()
        self.assertGreater(self.app.state.work_done, 0)

    def test_manual_help_and_review_suspend_then_restore_same_target(self):
        self.arrival()
        self.app.show_story_help(); self.close_guide()
        before = deepcopy(self.app.session.story.payload()), gameplay(self.app.session)
        old_timer = self.h.timer
        self.app.show_story_help(); self.root.update()
        self.assertIsNone(self.h.timer)
        self.assertNotIn(old_timer, self.root.tk.call('after', 'info'))
        self.close_guide(); self.assert_target('server', self.app.network)
        review = self.app.show_story_review(); self.root.update()
        self.assertIsNone(self.h.timer)
        review.destroy(); self.root.update()
        self.assert_target('server', self.app.network)
        self.assertEqual((self.app.session.story.payload(), gameplay(self.app.session)), before)

    def test_static_highlight_has_no_animation_timer(self):
        self.h.animate = False
        self.arrival()
        self.assertEqual(self.h.key, 'server')
        self.assertIsNone(self.h.timer)
        self.assertTrue(self.app.network.find_withtag('tutorial-highlight'))

    def test_destroyed_target_cancels_callback(self):
        self.allocation()
        timer = self.h.timer
        self.app.action_buttons['start'].destroy()
        self.assertIsNone(self.h.timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.root.tk.call('after', 510); self.root.update()
        self.assertEqual(self.errors, [])

    def test_animation_does_not_change_fault_or_gpu_colors(self):
        self.arrival()
        self.app.session.inject_server_fault('A'); self.app.refresh()
        canvas = self.app.network
        border = next(i for i in canvas.find_withtag('server-A') if 'rack-border' in canvas.gettags(i))
        self.assertEqual(canvas.itemcget(border, 'outline'), RED)
        slots = [(i, canvas.itemcget(i, 'fill'), canvas.itemcget(i, 'outline')) for i in canvas.find_withtag('gpu-slot')]
        self.root.tk.call('after', 510); self.root.update()
        self.assertEqual(slots, [(i, canvas.itemcget(i, 'fill'), canvas.itemcget(i, 'outline')) for i, _, _ in slots])
        self.assertEqual(canvas.itemcget(border, 'outline'), RED)
        self.assertEqual(self.errors, [])

    def test_busy_gpu_and_existing_led_animation_remain_unchanged(self):
        self.running()
        c = self.app.network
        before = [(i, c.itemcget(i, 'fill'), c.itemcget(i, 'outline')) for i in c.find_withtag('gpu-slot')]
        for phase in range(4): animate_hardware(c, phase)
        self.assertEqual(before, [(i, c.itemcget(i, 'fill'), c.itemcget(i, 'outline')) for i, _, _ in before])
        self.assertEqual(len(c.find_withtag('gpu-owner-sg')), 7)

    def test_skip_stops_highlight_without_advancing_time(self):
        self.arrival()
        self.app._perform(self.app.session.skip_tutorial); self.close_guide()
        self.assertIsNone(self.h.timer)
        self.assertEqual(self.app.session.minute, 540)

    def test_closed_request_has_no_remaining_target(self):
        self.request()
        self.app._perform(lambda: self.app.session.reject_request('교육 종료 검증'))
        self.close_guide()
        self.assertEqual(self.app.session.story.mission_status, 'closed')
        self.assertIsNone(self.h.target)
        self.assertIsNone(self.h.timer)

    def test_each_target_fits_three_resolutions_and_maximized_game(self):
        def check_sizes():
            for size in ('1000x650', '1280x680', '1366x768', 'zoomed'):
                with self.subTest(step=self.app.session.story.step, size=size):
                    if size == 'zoomed':
                        self.root.state('zoomed')
                    else:
                        self.root.state('normal'); self.root.geometry(size)
                    self.root.update()
                    target = self.h.target
                    self.assertIsNotNone(target)
                    self.assertTrue(target.winfo_ismapped())
                    self.assertGreaterEqual(target.winfo_rootx(), self.root.winfo_rootx())
                    self.assertGreaterEqual(target.winfo_rooty(), self.root.winfo_rooty())
                    self.assertLessEqual(target.winfo_rootx()+target.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
                    self.assertLessEqual(target.winfo_rooty()+target.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
            self.root.state('normal'); self.root.update()
        self.arrival(); check_sizes()
        self.app.network.select('A'); self.close_guide(); check_sizes()
        self.app.resource_confirm_button.invoke(); self.close_guide(); check_sizes()
        self.app.arrival_open_button.invoke(); self.app.message_window.destroy()
        self.root.update(); self.close_guide(); check_sizes()
        check_sizes()
        self.app.resources.book.select(self.app.resources.review_frame)
        self.root.update(); self.close_guide(); check_sizes()
        self.app.resources.compare_button.invoke(); self.root.update(); check_sizes()
        d = self.app.allocation_window; d.plan_buttons[0].invoke(); d.close_button.invoke()
        self.root.update(); self.close_guide(); check_sizes()
        self.app.action_buttons['start'].invoke(); self.close_guide(); check_sizes()
        self.app.time_buttons[10].invoke(); self.close_guide(); check_sizes()
        self.app.action_buttons['operations'].invoke()
        self.app.story_window.skip_button.invoke(); self.app.story_window.next_button.invoke()
        self.close_guide(); check_sizes()
        self.assertEqual(self.errors, [])

    def test_mode_transition_cancels_highlight_and_free_mode_has_none(self):
        self.arrival(); timer = self.h.timer
        self.app.db_factory = lambda _: Database(':memory:')
        self.assertTrue(self.app.return_to_modes('free'))
        free = self.app.mode_selector.app
        self.addCleanup(free.db.close); self.addCleanup(free.network.stop)
        self.root.update()
        self.assertIsNone(self.h.timer)
        self.assertIsNone(free.tutorial_highlight.target)
        self.assertIsNone(free.tutorial_highlight.timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(self.errors, [])

    def test_failed_transition_preserves_current_target_and_single_timer(self):
        self.arrival(); timer = self.h.timer
        with patch.object(self.app.session, 'close', side_effect=OSError('저장 실패')), patch('main.messagebox.showerror'):
            self.assertFalse(self.app.return_to_modes())
        self.assert_target('server', self.app.network)
        self.assertEqual(timer, self.h.timer)
        self.assertFalse(self.app.closed)

    def test_root_destruction_cancels_all_animation(self):
        root = tk.Toplevel(self.root)
        db = Database(':memory:'); self.addCleanup(db.close)
        app = SimulatorApp(root, db, mode='story')
        app.session.confirm_story_arrival(); app.refresh()
        app.story_window.destroy(); self.root.update()
        timer = app.tutorial_highlight.timer
        self.assertIsNotNone(timer)
        root.destroy(); self.root.update()
        self.assertIsNone(app.tutorial_highlight.timer)
        self.assertIsNone(app.network.timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(self.errors, [])

    def test_dialogues_center_on_game_at_three_resolutions_and_offsets(self):
        self.close_guide()
        for size, offset in (('1000x650', '+40+40'), ('1280x680', '+170+70'), ('1366x768', '+0+0')):
            with self.subTest(size=size):
                self.root.geometry(size+offset); self.root.update()
                for cls in (StoryDialogueDialog, StoryReviewDialog):
                    d = cls(self.root, [('교육 담당자', '중앙 배치 확인')]) if cls is StoryDialogueDialog else cls(self.root)
                    self.root.update()
                    self.assert_centered_and_visible(d)
                    d.destroy()

    def assert_centered_and_visible(self, d):
        left, top, right, bottom = work_area(self.root)
        for widget in (*d.portraits.values(), d.bubble, d.next_button, d.close_button, d.skip_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreaterEqual(widget.winfo_rootx(), d.winfo_rootx())
            self.assertGreaterEqual(widget.winfo_rooty(), d.winfo_rooty())
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), d.winfo_rootx()+d.winfo_width())
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), d.winfo_rooty()+d.winfo_height())
        self.assertGreaterEqual(d.winfo_rootx(), left)
        self.assertGreaterEqual(d.winfo_rooty(), top)
        self.assertLessEqual(d.winfo_rootx()+d.winfo_width(), right)
        self.assertLessEqual(d.winfo_rooty()+d.winfo_height(), bottom)
        self.assertAlmostEqual(d.winfo_rootx()+d.winfo_width()/2, self.root.winfo_rootx()+self.root.winfo_width()/2, delta=2)
        self.assertAlmostEqual(d.winfo_rooty()+d.winfo_height()/2, self.root.winfo_rooty()+self.root.winfo_height()/2, delta=2)

    def test_dialog_centered_on_actual_maximized_parent(self):
        self.root.state('zoomed'); self.root.update()
        self.assertEqual(self.root.state(), 'zoomed')
        d = self.app.show_story_help(); self.root.update()
        self.assert_centered_and_visible(d)
        review = self.app.show_story_review(); self.root.update()
        self.assert_centered_and_visible(review)


class ResumeHighlightTests(unittest.TestCase):
    def test_every_saved_action_resumes_only_current_target_without_changing_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'resume.db'
            db = Database(path)
            self.addCleanup(db.close)
            session = GameSession(db, mode='story', seed=9)
            actions = [session.confirm_story_arrival, lambda: session.select_story_server('A'),
                       session.confirm_story_resources, lambda: session.read_conversation(1),
                       lambda: session.inspect_story_preview(1), lambda: session.choose_plan('performance'),
                       lambda: session.advance_time(10), session.confirm_story_operations,
                       lambda: session.advance_time(60), lambda: session.advance_time(60)]
            for action in actions:
                action()
                session.mark_story_dialogue(session.story.dialogue_event)
                session.save()
                expected = deepcopy(session.story.payload()), gameplay(session)
                root = tk.Tk()
                reopened = Database(path)
                try:
                    app = SimulatorApp(root, reopened, mode='story')
                    root.update()
                    self.assertEqual((app.session.story.payload(), gameplay(app.session)), expected)
                    self.assertEqual(app.tutorial_highlight.key,
                                     None if session.story.chapter_completed else session.story.step)
                    if app.tutorial_highlight.key:
                        self.assertNotIn(app.tutorial_highlight.key, session.story.completed_steps)
                finally:
                    root.destroy(); reopened.close()
            db.close()

    def test_initial_screen_failure_cleans_started_highlight_and_gpu_timers(self):
        root = tk.Tk(); self.addCleanup(root.destroy)
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, mode='story'); s.confirm_story_arrival()
        s.select_story_server('A'); s.confirm_story_resources()
        before = deepcopy(s.story.payload()), gameplay(s)
        with patch('main.StoryDialogueDialog', side_effect=RuntimeError('화면 생성 실패')):
            with self.assertRaises(RuntimeError): SimulatorApp(root, db, mode='story')
        root.update()
        self.assertEqual(root.winfo_children(), [])
        self.assertFalse(root.tk.call('after', 'info'))
        restored = GameSession(db, mode='story')
        self.assertEqual((restored.story.payload(), gameplay(restored)), before)


if __name__ == '__main__':
    unittest.main()
