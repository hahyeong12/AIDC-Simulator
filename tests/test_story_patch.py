"""v0.9-1a: 교육 확장, 이전 저장, 완료 결과, 안전한 화면 전환과 점유 색상."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database, DB_PATH, STORY_DB_PATH
from main import SimulatorApp
from session import GameSession
from server_console import server_views
from server_widgets import OWNER_COLORS, OWNER_BOARDS, CYAN, RED, animate_hardware
from story import LEGACY_STEPS, STEPS, GUIDES
from tests.test_story import gameplay


def prepare(s):
    s.confirm_story_arrival(); s.select_story_server('A'); s.confirm_story_resources()
    s.read_conversation(s.story.request_id); s.inspect_story_preview(s.story.request_id)


def finish(s):
    if s.current.state.phase in ('ready', 'accepted'):
        s.choose_plan('performance')
    s.advance_time(10)
    if s.story.step == 'operations':
        s.confirm_story_operations()
    s.advance_time(60); s.advance_time(60)


def legacy(s, step, tutorial=False, skipped=False):
    count = len(LEGACY_STEPS) if tutorial else LEGACY_STEPS.index(step)
    return {'chapter':1, 'step':step, 'completed_steps':list(LEGACY_STEPS[:count]),
            'tutorial_completed':tutorial, 'skipped':skipped,
            'mission_status':s.story.mission_status, 'first_work_completed':s.story.first_work_completed,
            'request_id':s.story.request_id, 'selected_server':s.story.selected_server,
            'resources_confirmed':s.story.resources_confirmed, 'request_read':s.story.request_read}


class ExtendedStoryTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:'); self.addCleanup(self.db.close)
        self.s = GameSession(self.db, mode='story', seed=9, incident_chance=1)

    def test_first_day_has_player_mentor_and_system_roles(self):
        self.assertEqual(self.s.story.step, 'arrival')
        self.assertFalse(self.s.story.introduction_confirmed)
        self.assertEqual(GUIDES['arrival'][1][0].role, 'player')
        self.assertTrue(any(line.role == 'mentor' for line in GUIDES['arrival'][1]))
        self.assertTrue(any(line.role == 'system' for line in GUIDES['resources'][1]))
        before = gameplay(self.s)
        self.s.confirm_story_arrival()
        self.assertEqual(self.s.story.step, 'server')
        self.assertEqual(gameplay(self.s), before)

    def test_real_ten_stage_flow_keeps_tutorial_open_until_completion(self):
        s = self.s
        s.confirm_story_arrival(); s.select_story_server('A'); s.confirm_story_resources()
        s.read_conversation(1)
        self.assertEqual(s.story.step, 'preview')
        before = gameplay(s)
        s.allocation_options(s.current, 'performance')
        self.assertEqual(s.story.step, 'preview')  # 모델 조회는 GUI 열람 이력이 아닙니다.
        s.inspect_story_preview(1)
        self.assertEqual(s.story.step, 'allocation')
        self.assertEqual(gameplay(s), before)
        s.choose_plan('performance')
        self.assertEqual(s.story.step, 'time')
        s.advance_time(10)
        self.assertEqual(s.story.step, 'operations')
        self.assertFalse(s.story.tutorial_completed)
        before = gameplay(s)
        s.confirm_story_operations()
        self.assertEqual(gameplay(s), before)
        self.assertEqual(s.story.step, 'work_complete')
        s.advance_time(60); self.assertFalse(s.story.chapter_completed)
        s.advance_time(60)
        self.assertTrue(s.story.chapter_completed)
        self.assertTrue(s.story.tutorial_completed)
        self.assertEqual(s.story.completed_steps, list(STEPS))

    def test_preview_of_wrong_or_unread_request_does_not_advance(self):
        self.s.inspect_story_preview(1)
        self.assertFalse(self.s.story.preview_confirmed)
        self.s.read_conversation(1); self.s.inspect_story_preview(999)
        self.assertFalse(self.s.story.preview_confirmed)

    def test_operations_requires_actual_progress_and_correct_stage(self):
        prepare(self.s); self.s.choose_plan('performance')
        with self.assertRaises(ValueError): self.s.confirm_story_operations()
        self.s.inject_server_fault('A'); self.s.advance_time(10)
        self.assertEqual(self.s.story.step, 'time')
        self.assertFalse(self.s.story.operations_confirmed)

    def test_chapter_result_requires_normal_completion_and_resource_release(self):
        prepare(self.s); self.s.choose_plan('performance')
        self.s.advance_time(10)
        with self.assertRaises(ValueError): self.s.chapter_result()
        self.s.confirm_story_operations(); finish(self.s)
        result = self.s.chapter_result()
        self.assertEqual(result['score'], self.db.get_playthrough(result['playthrough_id'])['score'])
        self.assertEqual((result['gpu'], result['power']), (7, 7))
        self.assertTrue(result['on_time'])
        self.assertEqual(set(result['servers'].values()), {'IDLE'})
        self.assertEqual(self.s.center.gpu_used, 0)
        self.assertEqual(self.s.center.power_used, 0)
        self.assertIn('완료', result['feedback'])

    def test_late_completion_reports_real_reduced_score_and_deadline(self):
        prepare(self.s); self.s.choose_plan('performance')
        self.s.inject_server_fault('A')
        for _ in range(4): self.s.advance_time(60)
        self.s.begin_server_repair('A'); self.s.advance_time(30)
        self.s.confirm_story_operations(); finish(self.s)
        result = self.s.chapter_result()
        self.assertFalse(result['on_time'])
        self.assertLess(result['score'], 100)
        self.assertEqual(result['score'], self.s.current.state.score)

    def test_early_normal_completion_does_not_fabricate_missing_education_checks(self):
        self.s.read_conversation(1); self.s.choose_plan('performance')
        self.s.advance_time(60); self.s.advance_time(60)
        self.assertTrue(self.s.story.chapter_completed)
        self.assertFalse(self.s.story.tutorial_completed)
        self.assertFalse(self.s.story.preview_confirmed)
        self.assertEqual(self.s.chapter_result()['score'], self.s.current.state.score)

    def test_skipping_never_completes_customer_work_or_chapter(self):
        prepare(self.s); self.s.choose_plan('performance'); self.s.advance_time(10)
        before = gameplay(self.s)
        self.s.skip_tutorial()
        self.assertEqual(gameplay(self.s), before)
        self.assertTrue(self.s.story.tutorial_completed)
        self.assertFalse(self.s.story.chapter_completed)
        finish(self.s)
        self.assertTrue(self.s.story.chapter_completed)

    def test_new_observation_save_failures_restore_full_state(self):
        actions = [self.s.confirm_story_arrival]
        for action in actions:
            before = (deepcopy(self.s.story.payload()), gameplay(self.s), '\n'.join(self.db.conn.iterdump()))
            with patch.object(self.db, 'save_runtime', side_effect=OSError('실패')):
                with self.assertRaises(OSError): action()
            self.assertEqual((self.s.story.payload(), gameplay(self.s), '\n'.join(self.db.conn.iterdump())), before)
        self.s.confirm_story_arrival(); self.s.select_story_server('A'); self.s.confirm_story_resources()
        self.s.read_conversation(1)
        for action in (lambda:self.s.inspect_story_preview(1),):
            before = deepcopy(self.s.story.payload())
            with patch.object(self.db, 'save_simulation', side_effect=OSError('실패')):
                with self.assertRaises(OSError): action()
            self.assertEqual(self.s.story.payload(), before)
        self.s.inspect_story_preview(1); self.s.choose_plan('performance'); self.s.advance_time(10)
        before = deepcopy(self.s.story.payload())
        with patch.object(self.db, 'save_runtime', side_effect=OSError('실패')):
            with self.assertRaises(OSError): self.s.confirm_story_operations()
        self.assertEqual(self.s.story.payload(), before)

    def test_customer_rejection_never_marks_chapter_complete(self):
        self.s.reject_request('처리 조건 불가')
        self.assertFalse(self.s.story.chapter_completed)
        with self.assertRaises(ValueError): self.s.chapter_result()

    def test_inconsistent_chapter_save_is_rejected_without_modification(self):
        payload = self.db.get_simulation()
        payload['story'].update(chapter_completed=True, first_work_completed=True, mission_status='completed')
        self.db.save_simulation(payload)
        before = '\n'.join(self.db.conn.iterdump())
        with self.assertRaises(ValueError): GameSession(self.db, mode='story')
        self.assertEqual('\n'.join(self.db.conn.iterdump()), before)


class LegacyStoryTests(unittest.TestCase):
    def test_all_v091_steps_resume_without_writing_or_restarting_customer(self):
        for step in LEGACY_STEPS:
            with self.subTest(step=step):
                db = Database(':memory:')
                try:
                    s = GameSession(db, mode='story', seed=9)
                    s.confirm_story_arrival()
                    index = LEGACY_STEPS.index(step)
                    if index >= 1: s.select_story_server('A')
                    if index >= 2: s.confirm_story_resources()
                    if index >= 3: s.read_conversation(1)
                    if index >= 4: s.choose_plan('performance')
                    if index >= 5: s.advance_time(10)
                    payload = db.get_simulation()
                    payload['story'] = legacy(s, step, tutorial=step == 'complete')
                    db.save_simulation(payload)
                    before = gameplay(s), '\n'.join(db.conn.iterdump())
                    restored = GameSession(db, mode='story')
                    self.assertEqual((gameplay(restored), '\n'.join(db.conn.iterdump())), before)
                    self.assertTrue(restored.story.legacy_progress)
                    self.assertEqual(restored.story.tutorial_completed, step == 'complete')
                    self.assertFalse(restored.story.chapter_completed)
                    if step == 'complete': self.assertEqual(restored.story.step, 'work_complete')
                finally:
                    db.close()

    def test_v091_completed_work_migrates_to_chapter_complete_without_new_score(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'story.db'
            db = Database(path)
            s = GameSession(db, mode='story'); prepare(s); finish(s)
            payload = db.get_simulation(); payload['story'] = legacy(s, 'complete', tutorial=True)
            db.save_simulation(payload)
            expected = gameplay(s)
            records = [tuple(r) for r in db.get_recent_records()]
            db.close()
            for _ in range(3):
                db = Database(path); restored = GameSession(db, mode='story')
                self.assertEqual(gameplay(restored), expected)
                self.assertTrue(restored.story.chapter_completed)
                self.assertTrue(restored.story.tutorial_completed)
                self.assertEqual([tuple(r) for r in db.get_recent_records()], records)
                restored.close()

    def test_v091_skipped_guidance_keeps_customer_unstarted(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, mode='story'); s.skip_tutorial()
        payload = db.get_simulation(); payload['story'] = legacy(s, 'complete', tutorial=True, skipped=True)
        db.save_simulation(payload)
        before = gameplay(s)
        restored = GameSession(db, mode='story')
        self.assertEqual(gameplay(restored), before)
        self.assertTrue(restored.story.skipped)
        self.assertFalse(restored.story.chapter_completed)

    def test_migrated_tutorial_completion_is_preserved_when_customer_finishes(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, mode='story'); prepare(s); s.choose_plan('performance'); s.advance_time(10)
        payload = db.get_simulation(); payload['story'] = legacy(s, 'complete', tutorial=True)
        db.save_simulation(payload)
        s = GameSession(db, mode='story')
        self.assertTrue(s.story.tutorial_completed)
        self.assertFalse(s.story.chapter_completed)
        s.advance_time(60); s.advance_time(60)
        self.assertTrue(s.story.chapter_completed)
        self.assertEqual(len(db.get_recent_records()), 1)

    def test_save_failure_after_migration_keeps_original_disk_payload(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, mode='story'); prepare(s); s.choose_plan('performance'); s.advance_time(10)
        payload = db.get_simulation(); payload['story'] = legacy(s, 'complete', tutorial=True)
        db.save_simulation(payload)
        restored = GameSession(db, mode='story')
        before = deepcopy(restored.story.payload()), gameplay(restored), '\n'.join(db.conn.iterdump())
        with patch.object(db, 'save_runtime', side_effect=OSError('실패')):
            with self.assertRaises(OSError): restored.advance_time(60)
        self.assertEqual((restored.story.payload(), gameplay(restored), '\n'.join(db.conn.iterdump())), before)


class PatchGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.databases = []
        def factory(path):
            db = Database(Path(self.directory.name)/Path(path).name)
            self.databases.append(db)
            return db
        self.factory = factory
        self.addCleanup(lambda:[db.close() for db in self.databases])
        self.app = SimulatorApp(self.root, db=factory(STORY_DB_PATH), db_factory=factory, mode='story', seed=9)
        self.errors = []
        self.root.report_callback_exception = lambda *args:self.errors.append(args)
        self.root.update()

    def complete(self):
        prepare(self.app.session)
        self.app.session.choose_plan('performance')
        self.app.advance_time(10)
        self.app.session.confirm_story_operations()
        self.app.advance_time(60); self.app.advance_time(60)
        self.root.update()
        return self.app.chapter_window

    def test_preview_tab_records_real_observation_without_reservation(self):
        s = self.app.session
        s.confirm_story_arrival(); s.select_story_server('A'); s.confirm_story_resources()
        self.app.open_message(1); self.root.update()
        self.assertEqual(s.story.step, 'preview')
        self.app.resources.book.select(self.app.resources.review_frame); self.root.update()
        self.assertTrue(s.story.preview_confirmed)
        self.assertEqual(s.story.step, 'allocation')
        self.assertEqual(s.servers.allocations, {})

    def test_comparison_open_records_preview_without_starting(self):
        s = self.app.session
        s.confirm_story_arrival(); s.select_story_server('A'); s.confirm_story_resources(); s.read_conversation(1)
        dialog = self.app.open_allocation_plans(); self.root.update()
        self.assertEqual(s.story.step, 'allocation')
        self.assertEqual(s.center.gpu_used, 0)
        dialog.close_button.invoke()
        self.assertEqual(s.story.step, 'allocation')

    def test_preview_save_failure_destroys_comparison_without_advancing(self):
        s = self.app.session
        s.confirm_story_arrival(); s.select_story_server('A'); s.confirm_story_resources(); s.read_conversation(1)
        with patch.object(self.app.db, 'save_runtime', side_effect=OSError('실패')):
            with patch('main.messagebox.showerror') as error:
                self.assertIsNone(self.app.open_allocation_plans())
        error.assert_called_once()
        self.assertFalse(s.story.preview_confirmed)
        self.assertEqual(s.story.step, 'preview')
        self.assertIsNone(self.root.grab_current())

    def test_operations_help_shows_live_estimate_deadline_and_server_residuals(self):
        prepare(self.app.session); self.app.session.choose_plan('performance')
        self.app.advance_time(10)
        win = self.app.story_window
        win.skip_button.invoke()
        text = win.full_text
        self.assertIn('예상 완료:', text)
        self.assertIn('완료 기한', text)
        self.assertIn('Server A: GPU 0 · 전력 0', text)
        before = gameplay(self.app.session)
        win.next_button.invoke()
        self.assertEqual(gameplay(self.app.session), before)
        self.assertEqual(self.app.session.story.step, 'work_complete')

    def test_completion_screen_uses_actual_results_and_four_actions(self):
        window = self.complete()
        self.assertEqual(set(window.buttons), {'modes', 'free', 'status', 'review'})
        self.assertIn(f'{self.app.state.score}점', window.full_text)
        self.assertIn('반환 GPU: 7개', window.full_text)
        self.assertIn('반환 전력: 7단위', window.full_text)
        self.assertIn('A IDLE', window.full_text)
        self.assertEqual(window.result, self.app.session.chapter_result())

    def test_completion_can_be_closed_and_reopened_from_control_room(self):
        window = self.complete(); window.destroy(); self.root.update()
        self.app.story_complete_button.invoke(); self.root.update()
        self.assertTrue(self.app.chapter_window.winfo_exists())
        self.assertEqual(len(self.app.db.get_recent_records()), 1)

    def test_review_dialog_is_read_only_and_speakers_are_separate(self):
        self.complete()
        before = gameplay(self.app.session), deepcopy(self.app.session.story.payload()), '\n'.join(self.app.db.conn.iterdump())
        review = self.app.show_story_review()
        self.assertTrue(any('신입 엔지니어' in speaker for speaker, _ in review.steps))
        self.assertTrue(any('선배 엔지니어' in speaker for speaker, _ in review.steps))
        review.next_button.invoke(); review.previous_button.invoke(); review.skip_button.invoke(); review.destroy()
        self.assertEqual((gameplay(self.app.session), self.app.session.story.payload(), '\n'.join(self.app.db.conn.iterdump())), before)

    def test_status_displays_unavailable_chapter_without_an_active_chapter_two_button(self):
        self.complete()
        status = self.app.show_story_status()
        text = status.text.get('1.0', 'end')
        self.assertIn('Chapter 1 · 완료', text)
        self.assertIn('Chapter 2 · 이후 개발 예정', text)
        self.assertEqual(set(self.app.chapter_window.buttons), {'modes', 'free', 'status', 'review'})

    def test_completion_return_to_selection_closes_database_and_timer(self):
        win = self.complete(); old = self.app
        timer = old.network.timer
        win.buttons['modes'].invoke(); self.root.update()
        self.assertTrue(old.closed)
        self.assertIsNone(old.network.timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertTrue(old.mode_selector.frame.winfo_ismapped())
        with self.assertRaises(sqlite3.ProgrammingError): old.db.get_simulation()
        self.assertEqual(len(self.root.winfo_children()), 1)
        self.assertEqual(self.errors, [])

    def test_direct_free_transition_resumes_its_own_existing_game(self):
        db = self.factory(DB_PATH)
        free = GameSession(db, seed=9, incident_chance=0)
        free.choose_plan('performance'); free.advance_time(30); free.close()
        before_story = Path(self.directory.name)/STORY_DB_PATH.name
        win = self.complete(); win.buttons['free'].invoke(); self.root.update()
        app = self.app.mode_selector.app
        self.assertIs(app.root, self.root)
        self.assertIsNone(app.session.story)
        self.assertEqual(app.session.minute, 570)
        self.assertEqual(app.center.gpu_used, 7)
        story = Database(before_story)
        try:
            restored = GameSession(story, mode='story')
            self.assertTrue(restored.story.chapter_completed)
            self.assertEqual(restored.center.gpu_used, 0)
            self.assertEqual(len(story.get_recent_records()), 1)
        finally:
            story.close()
        self.assertEqual(self.errors, [])

    def test_transition_save_failure_keeps_window_timer_and_database_open(self):
        win = self.complete(); timer = self.app.network.timer
        with patch.object(self.app.db, 'save_runtime', side_effect=OSError('실패')):
            with patch('main.messagebox.showerror') as error: win.buttons['free'].invoke()
        error.assert_called_once()
        self.assertFalse(self.app.closed)
        self.assertFalse(self.app.transitioning)
        self.assertTrue(win.winfo_exists())
        self.assertEqual(self.app.network.timer, timer)
        self.assertTrue(self.app.db.get_simulation()['story']['chapter_completed'])

    def test_target_load_failure_leaves_usable_selection_after_safe_save(self):
        self.complete()
        self.app.db_factory = lambda path:(_ for _ in ()).throw(OSError('대상 DB 열기 실패'))
        with patch('main.messagebox.showerror') as error:
            self.app.return_to_modes('free'); self.root.update()
        error.assert_called_once()
        self.assertTrue(self.app.mode_selector.frame.winfo_ismapped())
        self.assertIsNone(self.app.mode_selector.app)
        self.assertEqual(self.errors, [])

    def test_partial_target_ui_failure_cancels_timer_and_restores_selection(self):
        self.complete(); self.app.return_to_modes()
        selector = self.app.mode_selector
        with patch('main.SimulatorApp.show_chapter_complete', side_effect=ValueError('완료 화면 오류')):
            with patch('main.messagebox.showerror') as error:
                selector.start('story'); self.root.update()
        error.assert_called_once()
        self.assertTrue(selector.frame.winfo_ismapped())
        self.assertFalse(self.root.tk.call('after', 'info'))
        self.assertEqual(self.errors, [])

    def test_v091_completed_save_opens_completion_without_replaying_customer(self):
        self.complete(); self.app.return_to_modes()
        db = self.factory(STORY_DB_PATH)
        s = GameSession(db, mode='story')
        payload = db.get_simulation(); payload['story'] = legacy(s, 'complete', tutorial=True)
        db.save_simulation(payload); db.close()
        self.app.mode_selector.start('story'); self.root.update()
        resumed = self.app.mode_selector.app
        self.assertTrue(resumed.chapter_window.winfo_exists())
        self.assertTrue(resumed.session.story.chapter_completed)
        self.assertEqual(len(resumed.db.get_recent_records()), 1)
        self.assertEqual(resumed.center.gpu_used, 0)
        self.assertEqual(self.errors, [])

    def test_in_progress_transition_saves_and_cancels_customer_typewriter(self):
        prepare(self.app.session); self.app.session.choose_plan('performance'); self.app.advance_time(10)
        message = self.app.open_message(1)
        old_timer = message.timer
        self.app.mode_select_button.invoke(); self.root.update()
        self.assertIsNone(message.timer)
        self.assertNotIn(old_timer, self.root.tk.call('after', 'info'))
        self.app.mode_selector.buttons['story'].invoke(); self.root.update()
        resumed = self.app.mode_selector.app
        self.assertEqual(resumed.session.story.step, 'operations')
        self.assertEqual(resumed.center.gpu_used, 7)
        self.assertEqual(resumed.session.minute, 550)
        self.assertEqual(len(resumed.db.get_recent_records()), 1)

    def test_repeated_mode_round_trips_use_one_root_and_one_server_timer(self):
        self.complete()
        current = self.app
        for mode in ('free', 'story', 'free', 'story'):
            previous_timer = current.network.timer
            self.assertTrue(current.return_to_modes(mode)); self.root.update()
            self.assertIsNone(current.network.timer)
            self.assertNotIn(previous_timer, self.root.tk.call('after', 'info'))
            current = current.mode_selector.app
            self.assertIs(current.root, self.root)
            self.assertIsNotNone(current.network.timer)
        self.assertTrue(current.session.story.chapter_completed)
        self.assertEqual(len(current.db.get_recent_records()), 1)
        self.assertEqual(self.errors, [])

    def test_completion_all_controls_fit_three_resolutions_and_minimum_dialog(self):
        win = self.complete()
        for width, height in ((1000, 650), (1280, 680), (1366, 768)):
            self.root.geometry(f'{width}x{height}'); win.geometry('700x510'); self.root.update()
            for widget in (win.summary, win.next_notice, *win.buttons.values(), self.app.story_complete_button,
                           self.app.story_objective, self.app.mode_select_button, *self.app.time_buttons.values()):
                host = widget.winfo_toplevel()
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreaterEqual(widget.winfo_rootx(), host.winfo_rootx())
                self.assertGreaterEqual(widget.winfo_rooty(), host.winfo_rooty())
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), host.winfo_rootx()+host.winfo_width())
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), host.winfo_rooty()+host.winfo_height())
                self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
        self.assertEqual(self.errors, [])

    def test_gpu_owner_colors_match_between_story_and_free_and_differ_from_available(self):
        canvases = []
        for mode in ('story', 'free'):
            if mode == 'story':
                app = self.app
            else:
                self.app.return_to_modes('free'); self.root.update()
                app = self.app.mode_selector.app
            app.session.choose_plan('performance'); app.refresh(); self.root.update()
            bodies = [item for item in app.network.find_withtag('gpu-busy')]
            self.assertEqual(len(bodies), 7)
            self.assertEqual({app.network.itemcget(item, 'outline') for item in bodies}, {OWNER_COLORS['sg']})
            self.assertEqual({app.network.itemcget(item, 'fill') for item in bodies}, {OWNER_BOARDS['sg']})
            self.assertTrue(all('gpu-owner-sg' in app.network.gettags(item) for item in bodies))
            self.assertTrue(all(float(app.network.itemcget(item, 'width')) == 2 for item in bodies))
            self.assertIn('SG', [app.network.itemcget(i, 'text') for i in app.network.find_withtag('gpu-owner-code')])
            available = app.network.find_withtag('gpu-available')[0]
            self.assertNotEqual(app.network.itemcget(available, 'fill'), app.network.itemcget(bodies[0], 'fill'))
            self.assertNotEqual(OWNER_COLORS['sg'], CYAN)
            canvases.append({app.network.itemcget(i, 'fill') for i in bodies})
        self.assertEqual(canvases[0], canvases[1])

    def test_all_three_customer_colors_use_actual_allocated_slots(self):
        self.app.return_to_modes('free'); self.root.update()
        app = self.app.mode_selector.app; s = app.session
        s.deliver_next_request(); s.deliver_next_request()
        s.select(2); s.choose_plan('performance')
        s.select(3); s.choose_plan('economy'); app.refresh(); self.root.update()
        self.assertEqual(len(app.network.find_withtag('gpu-busy')), 7)
        for code, expected in (('jp', 3), ('us', 4)):
            items = [i for i in app.network.find_withtag('gpu-busy') if f'gpu-owner-{code}' in app.network.gettags(i)]
            self.assertEqual(len(items), expected)
            self.assertEqual({app.network.itemcget(i, 'outline') for i in items}, {OWNER_COLORS[code]})
        self.assertEqual(len(set(OWNER_COLORS.values())), 3)

    def test_completed_slots_and_power_return_to_on_and_idle(self):
        self.complete(); a = self.app
        self.assertEqual(len(a.network.find_withtag('gpu-busy')), 0)
        self.assertEqual(len(a.network.find_withtag('gpu-available')), 10)
        self.assertEqual(a.overview.values['power_available'], 10)
        self.assertEqual({v['status'] for v in server_views(a.session)}, {'IDLE'})
        codes = [a.network.itemcget(i, 'text') for i in a.network.find_withtag('gpu-owner-code')]
        self.assertEqual(set(codes), {'ON'})

    def test_fault_red_migration_and_animation_preserve_owner_marking(self):
        prepare(self.app.session); self.app.session.choose_plan('performance')
        s = self.app.session
        s.inject_server_fault('C'); self.app.refresh(); self.root.update()
        fault = self.app.network.find_withtag('gpu-fault')
        self.assertEqual(len(fault), 2)
        self.assertTrue(any(self.app.network.itemcget(i, 'fill') == RED for i in self.app.network.find_withtag('gpu-state-label')))
        preview = s.migration_preview(s.current)
        s.migrate(preview['options'][0], preview['source']); self.app.refresh(); self.root.update()
        items = self.app.network.find_withtag('gpu-busy')
        self.assertEqual(len(items), 7)
        self.assertTrue(all('gpu-owner-sg' in self.app.network.gettags(i) for i in items))
        for phase in (0, 1, 2):
            animate_hardware(self.app.network, phase)
            self.assertTrue(all(self.app.network.itemcget(i, 'outline') == OWNER_COLORS['sg'] for i in items))
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
