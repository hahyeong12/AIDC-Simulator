"""v0.9-1: 두 모드의 독립성, 실제 상태 기반 교육, 원자성, 실제 Tk 조작."""
from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from tests.support import start_via_dialog
from unittest.mock import patch

from database import Database, DB_PATH, STORY_DB_PATH
from main import ModeSelection, SimulatorApp
from session import GameSession
from story import STEPS
from tests.support import dismiss_story_popups


def gameplay(s):
    runs = {rid:{**vars(r), 'mission':dict(r.mission),
                 'state':{k:v for k,v in vars(r.state).items() if k != 'center'}}
            for rid, r in s.runs.items()}
    return deepcopy((s.minute, vars(s.center), runs, s.servers.allocations,
                     s.roll_index, s.next_arrival_minute, s.servers.hardware))


class StoryTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, mode='story', seed=9, incident_chance=1)
        self.s.confirm_story_arrival()

    def prepare(self):
        self.s.select_story_server('A')
        self.s.confirm_story_resources()
        self.s.read_conversation(self.s.story.request_id)
        self.s.inspect_story_preview(self.s.story.request_id)

    def snapshot(self):
        s = self.s
        return deepcopy(s.story.payload()), gameplay(s), '\n'.join(self.db.conn.iterdump())

    def test_first_request_reuses_singapore_mission_and_conditions(self):
        s = self.s
        self.assertEqual(len(s.runs), 1)
        self.assertEqual(s.current.mission['company_name'], 'Merlion AI')
        self.assertEqual(s.current.mission['country'], '싱가포르')
        self.assertEqual(s.current.request['source_key'], 'initial:1')
        self.assertEqual(s.current.conditions['allowed_modes'], ['performance'])
        self.assertEqual((s.current.state.plans['performance']['gpu'], s.current.state.plans['performance']['power']), (7, 7))
        self.assertIn('due', s.current.terms)
        self.assertIsNone(s.deliver_next_request())
        self.assertEqual(len(self.db.get_requests()), 1)

    def test_only_actual_a_selection_advances_first_step(self):
        self.s.select_story_server('B')
        self.assertEqual(self.s.story.step, 'server')
        self.s.select_story_server('A')
        self.assertEqual(self.s.story.step, 'resources')
        self.assertEqual(self.s.story.completed_steps, ['arrival', 'server'])

    def test_resource_confirmation_requires_a_observation(self):
        with self.assertRaises(ValueError):
            self.s.confirm_story_resources()
        self.s.select_story_server('A')
        self.s.confirm_story_resources()
        self.assertEqual(self.s.story.step, 'request')

    def test_selecting_request_alone_is_not_reading_customer_dialogue(self):
        self.s.select_story_server('A'); self.s.confirm_story_resources()
        self.s.select(1)
        self.assertEqual(self.s.story.step, 'request')
        self.s.read_conversation(1)
        self.assertEqual(self.s.story.step, 'preview')
        self.assertTrue(self.s.story.request_read)

    def test_preview_and_choice_without_start_do_not_complete_allocation(self):
        self.prepare()
        self.s.allocation_preview(self.s.current, 'performance')
        self.s.allocation_options(self.s.current, 'performance')
        self.assertEqual(self.s.story.step, 'allocation')
        self.assertFalse(self.s.servers.allocations)

    def test_failed_condition_does_not_complete_assignment(self):
        self.prepare()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.s.choose_plan('economy')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.s.story.step, 'allocation')

    def test_failed_server_allocation_does_not_complete_assignment(self):
        self.prepare()
        self.s.inject_server_fault('A')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.s.choose_plan('performance')
        self.assertEqual(self.snapshot(), before)

    def test_automatic_assignment_then_progress_and_normal_finish_complete_tutorial(self):
        self.prepare()
        self.s.choose_plan('performance')
        self.assertEqual(self.s.story.step, 'time')
        self.assertEqual(self.s.current.state.progress, 0)
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (7, 7))
        self.s.advance_time(10)
        self.assertGreater(self.s.current.state.progress, 0)
        self.assertFalse(self.s.story.tutorial_completed)
        self.assertEqual(self.s.story.step, 'operations')
        self.assertFalse(self.s.story.first_work_completed)
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (7, 7))
        self.assertEqual(self.s.story.mission_status, 'running')
        self.s.confirm_story_operations()
        self.s.advance_time(60); self.s.advance_time(60)
        self.assertTrue(self.s.story.tutorial_completed)
        self.assertEqual(self.s.story.completed_steps, list(STEPS))

    def test_explicit_allocation_uses_existing_options_exactly(self):
        self.prepare()
        selected = self.s.allocation_options(self.s.current, 'performance')['options'][2]
        self.s.choose_plan('performance', selected)
        self.assertEqual(self.s.current.server_allocations[-1].slices, selected)
        self.assertEqual(self.s.story.step, 'time')

    def test_accepted_alternative_preserves_existing_customer_consent(self):
        self.prepare()
        self.s.propose_alternative()
        self.s.advance_time(10)
        self.s.review_alternative()
        if self.s.current.proposals[-1]['status'] == 'accepted':
            self.s.choose_plan('economy')
            self.assertEqual(self.s.story.step, 'time')
        else:
            with self.assertRaises(ValueError):
                self.s.choose_plan('economy')
            self.s.choose_plan('performance')
        self.assertEqual(self.s.story.mission_status, 'running')

    def test_time_button_without_progress_does_not_complete_tutorial(self):
        self.prepare()
        self.s.advance_time(10)
        self.assertEqual(self.s.story.step, 'allocation')
        self.s.choose_plan('performance')
        self.s.inject_server_fault('A')
        self.s.advance_time(10)
        self.assertEqual(self.s.current.state.work_done, 0)
        self.assertEqual(self.s.story.step, 'time')

    def test_first_work_finishes_normally_and_no_future_mission_appears(self):
        self.prepare(); self.s.choose_plan('performance')
        self.s.advance_time(60); self.s.advance_time(60)
        self.assertTrue(self.s.current.state.succeeded)
        self.assertTrue(self.s.story.first_work_completed)
        self.assertEqual(self.s.story.mission_status, 'completed')
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (0, 0))
        self.assertEqual(self.s.servers.allocations, {})
        self.assertIn('Chapter 1', self.s.story.objective)
        self.s.advance_time(60)
        self.assertEqual(len(self.s.runs), 1)
        with self.assertRaises(ValueError):
            self.s.restart()

    def test_story_blocks_random_network_incident_even_at_probability_one(self):
        self.s.skip_tutorial(); self.s.choose_plan('performance')
        self.assertIsNone(self.s.current.state.incident_at)
        self.s.advance_time(60)
        self.assertFalse(self.s.current.state.incident_occurred)
        self.assertEqual(self.s.current.state.phase, 'running')

    def test_story_disables_automatic_arrivals_before_and_after_skip(self):
        self.s.advance_time(30)
        self.assertEqual(len(self.s.runs), 1)
        self.s.skip_tutorial(); self.s.advance_time(60)
        self.assertEqual(len(self.s.runs), 1)
        self.assertFalse(self.s.has_next_request)

    def test_free_mode_keeps_arrivals_and_random_network_incidents(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, incident_chance=1, seed=9)
        s.choose_plan('performance'); s.advance_time(60)
        self.assertGreater(len(s.runs), 1)
        self.assertIsNotNone(s.current.state.incident_at)
        self.assertTrue(s.current.state.incident_occurred)
        self.assertIsNone(s.story)
        self.assertNotIn('story', db.get_simulation())

    def test_manual_hardware_repair_and_network_response_remain_available(self):
        self.prepare(); self.s.choose_plan('performance')
        self.s.inject_server_fault('A'); self.s.begin_server_repair('A')
        self.s.advance_time(10)
        self.assertEqual(self.s.servers.hardware['A'].repair_left, 10)
        self.assertEqual(self.s.story.step, 'time')
        self.s.advance_time(10)
        self.assertEqual(self.s.servers.hardware['A'].state, 'HEALTHY')
        self.s.advance_time(10)
        self.assertEqual(self.s.story.step, 'operations')
        self.s.current.state.trigger_incident()
        self.s.respond('reroute')
        self.assertIn(self.s.current.state.phase, ('recovering', 'running'))

    def test_skip_changes_only_guidance_at_each_active_stage(self):
        for stage in ('server', 'resources', 'request', 'allocation', 'time'):
            with self.subTest(stage=stage):
                db = Database(':memory:')
                try:
                    s = GameSession(db, mode='story', seed=9)
                    s.confirm_story_arrival()
                    if stage != 'server': s.select_story_server('A')
                    if stage in ('request', 'allocation', 'time'): s.confirm_story_resources()
                    if stage in ('allocation', 'time'): s.read_conversation(1)
                    if stage == 'time': s.choose_plan('performance')
                    before = gameplay(s)
                    rows = {name:[tuple(r) for r in db.conn.execute(f'SELECT * FROM {name}')]
                            for name in ('customer_requests', 'playthroughs', 'event_logs', 'request_events', 'request_runtime')}
                    s.skip_tutorial()
                    self.assertEqual(gameplay(s), before)
                    for name, expected in rows.items():
                        self.assertEqual([tuple(r) for r in db.conn.execute(f'SELECT * FROM {name}')], expected)
                    self.assertTrue(s.story.skipped)
                    self.assertFalse(s.story.first_work_completed)
                    self.assertEqual(s.mode, 'story')
                finally:
                    db.close()

    def test_out_of_order_real_actions_do_not_leave_tutorial_stuck(self):
        self.s.read_conversation(1); self.s.choose_plan('performance'); self.s.advance_time(10)
        self.assertEqual(self.s.story.step, 'server')
        self.s.select_story_server('A'); self.s.confirm_story_resources()
        self.s.inspect_story_preview(1); self.s.confirm_story_operations()
        self.assertEqual(self.s.story.step, 'work_complete')
        self.s.advance_time(60); self.s.advance_time(60)
        self.assertTrue(self.s.story.tutorial_completed)

    def test_rejected_or_expired_request_is_not_recorded_as_success(self):
        self.s.reject_request('교육 중 요청 종료')
        self.assertFalse(self.s.story.first_work_completed)
        self.assertFalse(self.s.story.tutorial_completed)
        self.assertEqual(self.s.story.mission_status, 'closed')
        self.assertIn('종료', self.s.story.objective)

    def test_db_failure_rolls_back_each_guidance_action(self):
        for action in (lambda:self.s.select_story_server('A'), self.s.skip_tutorial):
            before = self.snapshot()
            with patch.object(self.db, 'save_simulation', side_effect=OSError('저장 실패')):
                with self.assertRaises(OSError): action()
            self.assertEqual(self.snapshot(), before)
        self.s.select_story_server('A')
        before = self.snapshot()
        with patch.object(self.db, 'save_runtime', side_effect=OSError('저장 실패')):
            with self.assertRaises(OSError): self.s.confirm_story_resources()
        self.assertEqual(self.snapshot(), before)

    def test_db_failure_read_start_progress_and_finish_restore_story_and_game(self):
        self.s.select_story_server('A'); self.s.confirm_story_resources()
        for action in (lambda:self.s.read_conversation(1), lambda:self.s.choose_plan('performance'),
                       lambda:self.s.advance_time(10), lambda:self.s.advance_time(60)):
            before = self.snapshot()
            with patch.object(self.db, 'save_runtime', side_effect=OSError('저장 실패')):
                with self.assertRaises(OSError): action()
            self.assertEqual(self.snapshot(), before)
            action()
        before = self.snapshot()
        with patch.object(self.db, 'save_runtime', side_effect=OSError('완료 저장 실패')):
            with self.assertRaises(OSError): self.s.advance_time(60)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.s.story.first_work_completed)

    def test_disk_resume_at_every_stage_and_completed_mission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'story.db'
            actions = (lambda s:None, lambda s:s.confirm_story_arrival(), lambda s:s.select_story_server('A'),
                       lambda s:s.confirm_story_resources(), lambda s:s.read_conversation(1),
                       lambda s:s.inspect_story_preview(1), lambda s:s.choose_plan('performance'),
                       lambda s:s.advance_time(10), lambda s:s.confirm_story_operations(),
                       lambda s:s.advance_time(60), lambda s:s.advance_time(60))
            for action in actions:
                db = Database(path); s = GameSession(db, mode='story', seed=9)
                action(s)
                expected = deepcopy((s.story.payload(), s.minute, vars(s.current.state), s.servers.allocations))
                s.close()
                db = Database(path); restored = GameSession(db, mode='story')
                self.assertEqual((restored.story.payload(), restored.minute, vars(restored.current.state), restored.servers.allocations), expected)
                self.assertEqual(db.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
                restored.close()

    def test_skipped_guidance_resumes_without_changing_request(self):
        self.s.skip_tutorial()
        restored = GameSession(self.db, mode='story')
        self.assertTrue(restored.story.skipped)
        self.assertEqual(restored.current.state.phase, 'ready')
        self.assertEqual(restored.minute, 540)

    def test_modes_have_independent_disk_files_and_unchanged_sql_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            free_path, story_path = (Path(directory)/name for name in ('aidc_game.db', 'aidc_story.db'))
            free = Database(free_path); s = GameSession(free, seed=9, incident_chance=0)
            s.choose_plan('performance'); s.advance_time(30); s.close()
            before = free_path.read_bytes()
            story = Database(story_path); t = GameSession(story, mode='story')
            t.skip_tutorial(); t.advance_time(10); t.close()
            self.assertEqual(free_path.read_bytes(), before)
            free = Database(free_path); s = GameSession(free)
            story = Database(story_path); t = GameSession(story, mode='story')
            try:
                self.assertEqual(s.minute, 570); self.assertEqual(t.minute, 550)
                self.assertEqual(s.center.gpu_used, 7); self.assertEqual(t.center.gpu_used, 0)
                self.assertIsNone(s.story); self.assertTrue(t.story.skipped)
                sql = lambda db:[tuple(r) for r in db.conn.execute('SELECT name,sql FROM sqlite_master ORDER BY name')]
                self.assertEqual(sql(free), sql(story))
            finally:
                free.close(); story.close()

    def test_wrong_mode_rejects_existing_save_without_modifying_it(self):
        before = self.snapshot()
        with self.assertRaises(ValueError): GameSession(self.db)
        self.assertEqual(self.snapshot(), before)
        db = Database(':memory:'); self.addCleanup(db.close)
        GameSession(db)
        before = '\n'.join(db.conn.iterdump())
        with self.assertRaises(ValueError): GameSession(db, mode='story')
        self.assertEqual('\n'.join(db.conn.iterdump()), before)

    def test_invalid_story_save_is_reported_without_repair(self):
        payload = self.db.get_simulation(); payload['story']['step'] = 'chapter_2'
        self.db.save_simulation(payload)
        before = '\n'.join(self.db.conn.iterdump())
        with self.assertRaises(ValueError): GameSession(self.db, mode='story')
        self.assertEqual('\n'.join(self.db.conn.iterdump()), before)

    def test_missing_story_request_is_reported_without_creating_a_replacement(self):
        payload = self.db.get_simulation(); payload['story']['request_id'] = 999
        self.db.save_simulation(payload)
        before = '\n'.join(self.db.conn.iterdump())
        with self.assertRaises(ValueError): GameSession(self.db, mode='story')
        self.assertEqual('\n'.join(self.db.conn.iterdump()), before)


class StoryGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.db = Database(':memory:'); self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, mode='story', seed=9, incident_chance=1)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args:self.errors.append(args)
        self.root.update()

    def select_a(self):
        a = self.app
        if a.session.story.step == 'arrival':
            a.story_window.skip_button.invoke(); a.story_window.next_button.invoke()
        a.story_window.destroy()
        bounds = a.network.rack_bounds['A']
        a.network.event_generate('<Button-1>', x=int((bounds[0]+bounds[2])/2), y=int((bounds[1]+bounds[3])/2))
        self.root.update()

    def prepare(self):
        self.select_a()
        dismiss_story_popups(self.app, self.root)
        self.app.resource_confirm_button.invoke()
        self.root.update()
        dismiss_story_popups(self.app, self.root)
        self.app.arrival_open_button.invoke(); self.root.update()
        self.app.message_window.destroy()
        plans = self.app.open_allocation_plans(); plans.plan_buttons[0].invoke()
        plans.close_button.invoke(); self.root.update()
        self.app.resources.show_preview(); self.root.update()

    def test_first_day_dialogue_identifies_teacher_and_can_be_reopened(self):
        a = self.app; d = a.story_window
        self.assertIn('교육 담당자', d.title())
        self.assertTrue(any('환영' in text for _, text in d.steps))
        self.assertIn('신입 엔지니어', d.steps[0][0])
        self.assertNotIn('Merlion AI', d.title())
        self.assertIn('교육 도움말', d.page.cget('text'))
        self.assertNotIn('대화 기록', d.page.cget('text'))
        d.destroy(); a.story_help_button.invoke(); self.root.update()
        self.assertTrue(a.story_window.winfo_exists())
        self.assertEqual(a.session.story.step, 'arrival')
        self.assertIn('첫 출근', a.story_objective.cget('text'))

    def test_rack_click_displays_resources_and_confirmation_advances(self):
        self.select_a(); a = self.app
        self.assertEqual(a.resources.selected, 'A')
        self.assertEqual(a.resources.book.select(), str(a.resources.inspector_frame))
        self.assertEqual(a.session.story.step, 'resources')
        dismiss_story_popups(a, self.root)
        a.resource_confirm_button.invoke(); dismiss_story_popups(a, self.root)
        a.show_story_help(); self.root.update()
        self.assertEqual(a.session.story.step, 'request')
        self.assertIn('AIDC LINK', a.story_window.full_text)

    def test_real_customer_dialogue_advances_and_stays_distinct_from_teacher(self):
        self.prepare(); a = self.app
        self.assertEqual(a.session.story.step, 'allocation')
        self.assertIn('배정', a.story_objective.cget('text'))
        d = a.open_message(1)
        self.assertIn('Merlion AI', d.title())
        self.assertEqual(a.session.story.step, 'allocation')

    def test_comparison_preview_then_actual_selected_plan_and_time(self):
        self.prepare(); a = self.app
        d = a.open_allocation_plans(); self.root.update()
        d.plan_buttons[1].invoke()
        self.assertEqual(a.session.story.step, 'allocation')
        selected = d.options[1]
        d.start_button.invoke(); self.root.update()
        self.assertEqual(a.session.story.step, 'time')
        self.assertEqual(a.session.current.server_allocations[-1].slices, selected)
        a.time_buttons[10].invoke(); self.root.update()
        self.assertFalse(a.session.story.tutorial_completed)
        self.assertEqual(a.session.story.step, 'operations')
        self.assertEqual(a.center.gpu_used, 7)
        a.show_story_help()
        self.assertIn('예상 완료', a.story_window.full_text)
        self.assertEqual(self.errors, [])

    def test_skip_requires_confirmation_and_does_not_advance_time_or_allocate(self):
        a = self.app
        with patch('main.messagebox.askyesno', return_value=False): a.story_skip_button.invoke()
        self.assertFalse(a.session.story.skipped)
        with patch('main.messagebox.askyesno', return_value=True): a.story_skip_button.invoke()
        self.root.update()
        self.assertTrue(a.session.story.skipped)
        self.assertEqual(a.session.minute, 540)
        self.assertEqual(a.center.gpu_used, 0)
        self.assertEqual(a.session.current.proposals, [])
        self.assertEqual(a.session.mode, 'story')

    def test_failed_gui_start_does_not_advance_stage(self):
        self.prepare(); a = self.app
        with patch.object(self.db, 'save_runtime', side_effect=OSError('저장 실패')):
            with patch('main.messagebox.showerror') as error:
                start_via_dialog(a); self.root.update()
        error.assert_called_once()
        self.assertEqual(a.session.story.step, 'allocation')
        self.assertEqual(a.center.gpu_used, 0)

    def test_reopening_resources_help_after_close_preserves_progress(self):
        self.select_a(); a = self.app
        a.story_window.destroy(); self.root.update()
        self.assertEqual(a.session.story.step, 'resources')
        a.story_help_button.invoke(); self.root.update()
        self.assertEqual(a.story_window.confirm[0], '자원 정보 확인')
        a.story_window.skip_button.invoke(); a.story_window.next_button.invoke()
        self.assertEqual(a.session.story.step, 'request')

    def test_failed_gui_server_observation_restores_selection(self):
        a = self.app
        a.story_window.skip_button.invoke(); a.story_window.next_button.invoke()
        a.network.select('B')
        with patch.object(self.db, 'save_simulation', side_effect=OSError('저장 실패')):
            with patch('main.messagebox.showerror') as error: a.network.select('A')
        error.assert_called_once()
        self.assertEqual(a.session.story.step, 'server')
        self.assertEqual(a.resources.selected, 'B')
        self.assertEqual(a.network.selected, 'B')

    def assert_fits(self, widgets):
        self.root.update()
        for widget in widgets:
            host = widget.winfo_toplevel()
            with self.subTest(widget=str(widget)):
                self.assertGreaterEqual(widget.winfo_rootx(), host.winfo_rootx())
                self.assertGreaterEqual(widget.winfo_rooty(), host.winfo_rooty())
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), host.winfo_rootx()+host.winfo_width())
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), host.winfo_rooty()+host.winfo_height())
                self.assertTrue(widget.winfo_ismapped())
                if widget.winfo_class() == 'Treeview':
                    # 목록은 자체 스크롤합니다. 헤더와 한 행 이상은 보여야 합니다.
                    self.assertGreaterEqual(widget.winfo_height(), 56)
                else:
                    self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())

    def test_actual_tk_three_resolutions_through_all_tutorial_stages(self):
        a = self.app
        for width, height in ((1000, 650), (1280, 680), (1366, 768)):
            self.root.geometry(f'{width}x{height}'); self.root.update()
            self.assert_fits((a.story_bar, a.story_objective, a.story_help_button, a.story_skip_button,
                              a.resources.inspector, a.inbox, a.active_list, a.controls,
                              a.arrival_notice, *a.time_buttons.values(), *a.action_buttons.values()))
            self.assert_fits((a.story_window.bubble, a.story_window.next_button, a.story_window.skip_button))
        self.prepare()
        start_via_dialog(a); self.root.update()
        for width, height in ((1000, 650), (1280, 680), (1366, 768)):
            self.root.geometry(f'{width}x{height}'); self.root.update()
            self.assert_fits((a.story_bar, a.story_objective, a.controls, a.resources.preview,
                              *a.time_buttons.values()))
        a.time_buttons[10].invoke(); self.root.update()
        a.time_buttons[60].invoke(); a.time_buttons[60].invoke(); self.root.update()
        self.assertTrue(a.session.story.first_work_completed)
        self.assertIn('첫 번째 고객 업무', a.chapter_window.full_text)
        self.assertNotIn('restart', a.action_buttons)
        self.assertEqual(self.errors, [])

    def test_story_close_saves_and_stops_server_timer(self):
        self.select_a()
        with patch.object(self.db, 'close'), patch.object(self.root, 'destroy') as destroy:
            self.app.on_close()
        destroy.assert_called_once()
        self.assertIsNone(self.app.network.timer)
        restored = GameSession(self.db, mode='story')
        self.assertEqual(restored.story.step, 'resources')


class ModeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.databases = []
        self.paths = []
        def factory(path):
            self.paths.append(path)
            db = Database(':memory:'); self.databases.append(db)
            self.addCleanup(db.close)
            return db
        from story_slots import StorySlots
        self.slots_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.slots_directory.cleanup)
        self.selector = ModeSelection(self.root, db_factory=factory,
                                      story_slots=StorySlots(self.slots_directory.name))
        self.root.update()

    def test_selection_screen_does_not_open_any_save(self):
        self.assertEqual(self.paths, [])
        self.assertEqual(set(self.selector.buttons), {'story', 'free'})
        self.assertIsNone(self.selector.app)

    def test_mode_selection_cards_fit_three_resolutions(self):
        for width, height in ((1000, 650), (1280, 680), (1366, 768)):
            self.root.geometry(f'{width}x{height}'); self.root.update()
            for card in self.selector.frame.winfo_children():
                self.assertTrue(card.winfo_ismapped())
                self.assertGreaterEqual(card.winfo_rootx(), self.root.winfo_rootx())
                self.assertGreaterEqual(card.winfo_rooty(), self.root.winfo_rooty())
                self.assertLessEqual(card.winfo_rootx()+card.winfo_width(), self.root.winfo_rootx()+width)
                self.assertLessEqual(card.winfo_rooty()+card.winfo_height(), self.root.winfo_rooty()+height)
                self.assertGreaterEqual(card.winfo_height(), card.winfo_reqheight())

    def test_story_button_uses_story_file_and_story_session(self):
        self.selector.buttons['story'].invoke(); self.root.update()
        self.assertEqual(self.paths, [])
        self.assertTrue(self.selector.story_panel.winfo_ismapped())
        self.selector.story_buttons['new'].invoke(); self.root.update()
        self.addCleanup(self.selector.app.network.stop)
        self.assertEqual(self.paths, [Path(self.slots_directory.name)/'aidc_story_slot_001.db'])
        self.assertEqual(self.selector.app.session.mode, 'story')
        self.assertIsNotNone(self.selector.app.session.story)

    def test_free_button_loads_existing_progress(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, incident_chance=0, seed=9)
        s.choose_plan('performance'); s.advance_time(10); s.save()
        self.selector.db_factory = lambda path:self.paths.append(path) or db
        self.selector.buttons['free'].invoke(); self.root.update()
        self.addCleanup(self.selector.app.network.stop)
        self.assertEqual(self.paths, [DB_PATH])
        self.assertEqual(self.selector.app.session.minute, 550)
        self.assertEqual(self.selector.app.center.gpu_used, 7)
        self.assertIsNone(self.selector.app.session.story)

    def test_load_failure_preserves_selection_screen_for_retry(self):
        self.selector.db_factory = lambda path:(_ for _ in ()).throw(OSError('저장 파일 열기 실패'))
        with patch('main.messagebox.showerror') as error:
            self.selector.buttons['story'].invoke(); self.root.update()
            self.selector.story_buttons['new'].invoke(); self.root.update()
        error.assert_called_once()
        self.assertTrue(self.selector.frame.winfo_ismapped())
        self.assertIsNone(self.selector.app)


if __name__ == '__main__':
    unittest.main()
