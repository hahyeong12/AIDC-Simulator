"""v0.9-1b 사건 대화, 저장 호환, 독립 초상화와 실제 Tk 조작 검증."""
from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from main import SimulatorApp
from session import GameSession
from story import GUIDES, STEPS, StoryProgress
from story_dialog import StoryDialogueDialog
from tests.test_story import gameplay
from tests.test_story_patch import prepare, finish
from tests.support import dismiss_story_popups


class DialogueStateTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, mode='story', seed=9)

    def test_display_does_not_satisfy_actual_action(self):
        before = gameplay(self.s)
        self.s.mark_story_dialogue('arrival')
        self.assertEqual(gameplay(self.s), before)
        self.assertEqual(self.s.story.step, 'arrival')
        self.assertFalse(self.s.story.introduction_confirmed)

    def test_duplicate_display_is_idempotent_without_database_write(self):
        self.s.mark_story_dialogue('arrival')
        with patch.object(self.db, 'save_runtime') as save:
            self.s.mark_story_dialogue('arrival')
        save.assert_not_called()
        self.assertEqual(self.s.story.dialogue_seen, ['arrival'])

    def test_future_event_cannot_be_recorded(self):
        with self.assertRaises(ValueError):
            self.s.mark_story_dialogue('operations')
        self.assertEqual(self.s.story.dialogue_seen, [])

    def test_refresh_equivalent_queries_do_not_create_display_history(self):
        for _ in range(4):
            self.s.story.dialogue; self.s.story.objective
            self.s.allocation_options(self.s.current, 'performance')
        self.assertEqual(self.s.story.dialogue_seen, [])

    def test_display_save_failure_rolls_back_sql_game_and_history(self):
        before = deepcopy(self.s.story.payload()), gameplay(self.s), '\n'.join(self.db.conn.iterdump())
        with patch.object(self.db, 'save_runtime', side_effect=OSError('표시 저장 실패')):
            with self.assertRaises(OSError): self.s.mark_story_dialogue('arrival')
        self.assertEqual((self.s.story.payload(), gameplay(self.s), '\n'.join(self.db.conn.iterdump())), before)

    def test_v091a_in_progress_missing_display_field_preserves_every_game_fact(self):
        prepare(self.s); self.s.choose_plan('performance'); self.s.advance_time(10)
        payload = self.db.get_simulation(); payload['story'].pop('dialogue_seen')
        self.db.save_simulation(payload)
        before = gameplay(self.s), '\n'.join(self.db.conn.iterdump())
        restored = GameSession(self.db, mode='story')
        self.assertEqual((gameplay(restored), '\n'.join(self.db.conn.iterdump())), before)
        self.assertEqual(restored.story.step, 'operations')
        self.assertEqual(restored.story.dialogue_seen, list(STEPS[:7]))

    def test_v091a_completed_record_is_not_restarted_or_rescored(self):
        prepare(self.s); finish(self.s)
        payload = self.db.get_simulation(); payload['story'].pop('dialogue_seen')
        self.db.save_simulation(payload)
        before = gameplay(self.s), '\n'.join(self.db.conn.iterdump())
        restored = GameSession(self.db, mode='story')
        self.assertTrue(restored.story.chapter_completed)
        self.assertTrue(restored.story.tutorial_completed)
        self.assertEqual((gameplay(restored), '\n'.join(self.db.conn.iterdump())), before)
        self.assertEqual(len(restored.db.get_recent_records()), 1)

    def test_invalid_display_history_is_rejected(self):
        for seen in ('arrival', ['arrival', 'arrival'], ['chapter2'], [None], [4]):
            with self.subTest(seen=seen), self.assertRaises(ValueError):
                StoryProgress(dialogue_seen=seen)

    def test_scene_lengths_are_bounded(self):
        self.assertLessEqual(len(GUIDES['arrival'][1]), 6)
        for key in STEPS[1:]: self.assertLessEqual(len(GUIDES[key][1]), 3)

    def test_closed_request_has_failure_specific_mentor_response(self):
        self.s.reject_request('조건 불가')
        self.assertEqual(self.s.story.dialogue_event, 'closed')
        self.assertEqual(self.s.story.dialogue[0].role, 'mentor')
        self.assertIn('정상 완료하지 못', self.s.story.dialogue[0].text)
        self.assertFalse(self.s.story.chapter_completed)

    def test_free_mode_rejects_story_history_without_writing(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db)
        before = '\n'.join(db.conn.iterdump())
        with self.assertRaises(ValueError): s.mark_story_dialogue('arrival')
        self.assertIsNone(s.story)
        self.assertEqual('\n'.join(db.conn.iterdump()), before)

    def test_disk_resume_preserves_seen_events_and_real_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'story.db'
            db = Database(path); s = GameSession(db, mode='story')
            for action in (lambda:s.mark_story_dialogue('arrival'), lambda:s.confirm_story_arrival(),
                           lambda:s.mark_story_dialogue('server'), lambda:s.select_story_server('A'),
                           lambda:s.mark_story_dialogue('resources')):
                action()
                expected = deepcopy(s.story.payload()), gameplay(s)
                s.close(); db = Database(path); s = GameSession(db, mode='story')
                self.assertEqual((s.story.payload(), gameplay(s)), expected)
            s.close()


class DialogueGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.db = Database(':memory:'); self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, mode='story', seed=9)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args:self.errors.append(args)
        self.root.update()

    def arrival(self):
        d = self.app.story_window; d.skip_button.invoke(); d.next_button.invoke()
        self.root.update()

    def resources(self):
        self.arrival(); self.app.select_server('A'); self.root.update()

    def request(self):
        self.resources(); dismiss_story_popups(self.app, self.root)
        self.app.resource_confirm_button.invoke(); self.root.update()

    def test_two_original_portraits_and_active_speaker_change(self):
        d = self.app.story_window
        self.assertEqual(d.active_role, 'player')
        for role, canvas in d.portraits.items():
            self.assertGreater(len(canvas.find_withtag(role)), 10)
        self.assertFalse(d.portraits['player'].find_withtag('inactive'))
        self.assertTrue(d.portraits['mentor'].find_withtag('inactive'))
        d.next_button.invoke()
        self.assertEqual(d.active_role, 'mentor')
        self.assertTrue(d.portraits['player'].find_withtag('inactive'))
        self.assertTrue(d.portraits['mentor'].find_withtag('headset'))

    def test_portrait_renderer_is_independent_and_replaceable(self):
        renderer = unittest.mock.Mock()
        d = StoryDialogueDialog(self.root, [v.page() for v in GUIDES['arrival'][1]],
                                portrait_renderer=renderer)
        renderer.reset_mock(); d.next_button.invoke()
        self.assertEqual(renderer.call_count, 2)
        self.assertEqual(renderer.call_args_list[1].args[1:], ('mentor', True))

    def test_close_and_last_page_do_not_select_server(self):
        self.arrival(); d = self.app.show_story_help()
        d.skip_button.invoke(); d.next_button.invoke()
        self.assertFalse(d.winfo_exists())
        self.assertEqual(self.app.session.story.step, 'server')
        self.app.select_server('B'); self.root.update()
        self.assertEqual(self.app.session.story.step, 'server')
        self.app.select_server('A'); self.root.update()
        self.assertEqual(self.app.session.story.step, 'resources')
        self.assertIn('resources', self.app.session.story.dialogue_seen)

    def test_inspector_confirmation_is_real_and_not_dialogue_next(self):
        self.resources()
        dismiss_story_popups(self.app, self.root)
        self.assertFalse(self.app.session.story.resources_confirmed)
        self.app.resource_confirm_button.invoke()
        self.assertTrue(self.app.session.story.resources_confirmed)
        self.assertEqual(self.app.session.story.step, 'request')

    def test_resource_confirmation_cannot_use_hidden_inspector(self):
        self.resources(); self.app.resources.show_preview(); self.root.update()
        with patch('main.messagebox.showerror'):
            self.assertFalse(self.app.confirm_story_resources())
        self.assertFalse(self.app.session.story.resources_confirmed)

    def test_refresh_and_repeat_server_click_do_not_reopen_seen_scene(self):
        self.resources(); d = self.app.story_window; d.destroy()
        before = deepcopy(self.app.session.story.payload())
        for _ in range(3): self.app.refresh(); self.app.select_server('A')
        self.root.update()
        self.assertFalse(d.winfo_exists())
        self.assertEqual(self.app.session.story.payload(), before)

    def test_seen_scene_can_be_manually_reopened_without_progress_or_write(self):
        d = self.app.story_window; d.destroy()
        before = deepcopy(self.app.session.story.payload()), gameplay(self.app.session)
        with patch.object(self.db, 'save_runtime') as save: self.app.show_story_help()
        save.assert_not_called()
        self.assertEqual((self.app.session.story.payload(), gameplay(self.app.session)), before)

    def test_customer_read_defers_short_mentor_scene_until_customer_closes(self):
        self.request(); self.app.open_message(1); self.root.update()
        self.assertFalse(self.app.story_window.winfo_exists())
        self.assertNotIn('preview', self.app.session.story.dialogue_seen)
        self.app.message_window.destroy(); self.root.update()
        self.assertEqual(self.app.feedback_window.event, 'request')
        self.assertIn('preview', self.app.session.story.dialogue_seen)
        self.assertEqual(self.app.center.gpu_used, 0)

    def test_comparison_close_triggers_actual_preview_event_without_start(self):
        self.request(); self.app.open_message(1); self.app.message_window.destroy(); self.root.update()
        d = self.app.open_allocation_plans(); self.root.update()
        self.assertIs(self.root.grab_current(), d)
        self.assertFalse(self.app.story_window.winfo_exists())
        d.close_button.invoke(); self.root.update()
        # 아무 계획도 확인하지 않고 닫으면 검토 완료 사건이 생기지 않습니다.
        self.assertNotIn('allocation', self.app.session.story.dialogue_seen)
        self.assertEqual(self.app.session.story.step, 'preview')
        d = self.app.open_allocation_plans(); d.plan_buttons[0].invoke(); d.close_button.invoke(); self.root.update()
        self.assertIn('allocation', self.app.session.story.dialogue_seen)
        self.assertEqual(self.app.session.story.step, 'allocation')
        self.assertEqual(self.app.center.gpu_used, 0)
        self.assertIsNone(self.root.grab_current())

    def test_selected_plan_start_progress_and_completion_use_actual_rules(self):
        self.request(); self.app.open_message(1); self.app.message_window.destroy(); self.root.update()
        d = self.app.open_allocation_plans(); d.plan_buttons[1].invoke()
        parts = d.options[1]; d.start_button.invoke(); self.root.update()
        self.assertEqual(self.app.session.current.server_allocations[-1].slices, parts)
        self.assertIn('time', self.app.session.story.dialogue_seen)
        self.assertEqual(len(self.app.network.find_withtag('gpu-owner-sg')), 7)
        self.app.advance_time(10)
        self.assertIn('operations', self.app.session.story.dialogue_seen)
        self.assertGreater(self.app.state.work_done, 0)
        self.app.show_story_help()
        self.app.story_window.skip_button.invoke(); self.app.story_window.next_button.invoke()
        self.app.advance_time(60); self.app.advance_time(60); self.root.update()
        self.assertTrue(self.app.session.story.chapter_completed)
        self.assertEqual(self.app.center.gpu_used, 0)
        self.assertEqual(self.app.chapter_window.result['score'], self.app.state.score)
        self.assertEqual(len(self.db.get_recent_records()), 1)
        self.assertEqual(self.errors, [])

    def test_review_selects_single_topic_and_does_not_change_sql_or_progress(self):
        before = deepcopy(self.app.session.story.payload()), '\n'.join(self.db.conn.iterdump())
        d = self.app.show_story_review()
        for i, key in enumerate(STEPS):
            d.scene.current(i); d.scene.event_generate('<<ComboboxSelected>>'); self.root.update()
            self.assertEqual(d.steps, [line.page() for line in GUIDES[key][1]])
            self.assertIsNone(d.confirm)
            d.skip_button.invoke(); d.next_button.invoke()
            if i < len(STEPS)-1: d = self.app.show_story_review()
        self.assertEqual((self.app.session.story.payload(), '\n'.join(self.db.conn.iterdump())), before)

    def test_portraits_text_and_controls_fit_three_resolutions(self):
        d = self.app.story_window
        review = self.app.show_story_review()
        for width, height in ((1000,650), (1280,680), (1366,768)):
            self.root.geometry(f'{width}x{height}')
            for dialog in (d, review):
                dialog.geometry('740x430'); self.root.update()
                for widget in (*dialog.portraits.values(), dialog.speaker, dialog.bubble,
                               dialog.next_button, dialog.previous_button, dialog.close_button,
                               dialog.skip_button, dialog.page):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreaterEqual(widget.winfo_rootx(), dialog.winfo_rootx())
                    self.assertGreaterEqual(widget.winfo_rooty(), dialog.winfo_rooty())
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), dialog.winfo_rootx()+dialog.winfo_width())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), dialog.winfo_rooty()+dialog.winfo_height())
        self.assertEqual(self.errors, [])

    def test_display_failure_destroys_dialog_and_leaves_event_retryable(self):
        self.app.session.confirm_story_arrival()
        self.app.story_window.destroy()
        with patch.object(self.db, 'save_runtime', side_effect=OSError('실패')):
            with patch('main.messagebox.showerror') as error:
                self.assertIsNone(self.app.show_story_help())
        error.assert_called_once()
        self.assertNotIn('server', self.app.session.story.dialogue_seen)
        self.assertFalse(self.app.story_window.winfo_exists())
        self.assertTrue(self.app.show_story_help().winfo_exists())

    def test_free_mode_has_no_story_dialog_or_portraits(self):
        root = tk.Toplevel(self.root); db = Database(':memory:'); self.addCleanup(db.close)
        app = SimulatorApp(root, db); self.addCleanup(app.network.stop)
        self.assertIsNone(app.story_window)
        self.assertIsNone(app.show_story_event())

    def test_pending_dialog_callback_is_cancelled_on_mode_transition(self):
        self.request(); self.app.open_message(1); self.app.message_window.destroy()
        timer = self.app.story_event_timer
        self.assertIsNotNone(timer)
        self.app.return_to_modes()
        self.root.update()
        self.assertIsNone(self.app.story_event_timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
