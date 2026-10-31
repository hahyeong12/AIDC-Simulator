"""대안 협의, 동의에 따른 배정, 원본 보존 및 이전 저장 호환성 검증."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from main import SimulatorApp
from session import GameSession


class AlternativeTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=12, incident_chance=0)

    def gpu_shortage(self):
        self.s.deliver_next_request()
        self.s.deliver_next_request()
        self.s.select(3)
        self.s.choose_plan('economy')
        self.s.select(1)
        return self.s.current

    def test_shortage_proposal_compares_resources_duration_and_original_deadline(self):
        run = self.gpu_shortage()
        with self.assertRaisesRegex(ValueError, 'GPU 1개'):
            self.s.choose_plan('performance')
        original = dict(run.request)
        terms = deepcopy(run.terms)
        proposal = self.s.propose_alternative()
        text = self.s.proposal_summary(proposal)
        for expected in ('원래 요청: 고성능', '제안 조건: 절약형', 'GPU -3개', '전력 -3단위',
                         '120분 → 180분 (+60분)', '기한 내 완료 예상', '원래 완료 기한: D1 12:30'):
            self.assertIn(expected, text)
        self.assertTrue(any('자원이 부족' in message for message in run.messages))
        for key in ('message', 'mission_id', 'received_at', 'status'):
            self.assertEqual(run.request[key], original[key])
        self.assertEqual(run.terms, terms)
        self.assertEqual(run.state.phase, 'ready')
        self.assertIsNone(run.state.plan)

    def test_proposal_and_customer_acceptance_do_not_allocate_or_create_execution(self):
        self.gpu_shortage()
        before = (self.s.center.gpu_used, self.s.center.power_used, len(self.db.get_recent_records()))
        self.s.propose_alternative()
        for key in ('performance', 'economy'):
            with self.assertRaisesRegex(ValueError, '고객'):
                self.s.choose_plan(key)
        self.assertEqual(self.s.current.proposals[-1]['status'], 'pending')
        self.assertTrue(self.s.review_alternative())
        self.assertEqual(self.s.current.proposals[-1]['status'], 'accepted')
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used, len(self.db.get_recent_records())), before)
        self.assertIsNone(self.s.current.playthrough_id)

    def test_agreed_plan_starts_and_releases_only_its_resources(self):
        run = self.gpu_shortage()
        self.s.propose_alternative()
        self.s.review_alternative()
        self.s.choose_plan('economy')
        self.assertEqual((run.state.plan, run.state.gpu_used, run.state.power_used), ('economy', 4, 4))
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (8, 7))
        self.assertEqual(self.db.get_playthrough(run.playthrough_id)['plan'], 'economy')
        self.assertTrue(any('고객 동의 대안 적용' in row['message'] for row in self.s.logs(run.playthrough_id)))
        for _ in range(3):
            self.s.advance_time(60)
        self.assertTrue(run.state.succeeded)
        self.assertEqual(run.terms['late_minutes'], 0)
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (0, 0))

    def test_customer_rejects_late_economy_plan_and_original_can_still_start(self):
        self.s.choose_plan('performance')
        self.s.deliver_next_request()
        self.s.select(2)
        run = self.s.current
        message, due = run.request['message'], run.terms['due']
        self.s.propose_alternative()
        self.assertFalse(self.s.review_alternative())
        self.assertEqual(run.proposals[-1]['status'], 'rejected')
        self.assertIn('완료 기한을 넘길', run.proposals[-1]['reason'])
        with self.assertRaisesRegex(ValueError, '고객'):
            self.s.choose_plan('economy')
        # 기존 작업을 완료한 뒤 원래 고성능 요청으로 시작할 수 있습니다.
        self.s.runs[1].state.work_done = 119
        self.s.advance_time(10)
        self.s.choose_plan('performance')
        self.assertEqual(run.state.plan, 'performance')
        self.assertEqual(run.request['message'], message)
        self.assertEqual(run.terms['due'], due)

    def test_start_rechecks_resources_consumed_after_customer_agreement(self):
        run = self.gpu_shortage()
        self.s.propose_alternative()
        self.s.review_alternative()
        self.s.select(2)
        self.s.choose_plan('performance')
        self.s.select(1)
        records, usage = len(self.db.get_recent_records()), (self.s.center.gpu_used, self.s.center.power_used)
        with self.assertRaisesRegex(ValueError, '자원 부족'):
            self.s.choose_plan('economy')
        self.assertEqual(run.proposals[-1]['status'], 'accepted')
        self.assertIsNone(run.playthrough_id)
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), usage)
        self.assertEqual(len(self.db.get_recent_records()), records)

    def test_customer_uses_decision_time_and_exact_deadline_is_accepted(self):
        self.s.propose_alternative()
        self.s.advance_time(30)
        self.assertTrue(self.s.review_alternative())
        proposal = self.s.current.proposals[-1]
        self.assertEqual(proposal['decision_finish'], self.s.current.terms['due'])

    def test_delayed_customer_review_rejects_previously_on_time_proposal(self):
        self.s.propose_alternative()
        self.s.advance_time(60)
        self.assertTrue(self.s.current.proposals[-1]['on_time'])
        self.assertFalse(self.s.review_alternative())
        self.assertEqual(self.s.center.gpu_used, 0)

    def test_waiting_after_agreement_keeps_original_deadline_and_late_penalty(self):
        run = self.s.current
        due = run.terms['due']
        self.s.propose_alternative()
        self.s.review_alternative()
        self.s.wait_request()
        self.s.advance_time(60)
        self.s.choose_plan('economy')
        for _ in range(3):
            self.s.advance_time(60)
        self.assertEqual(run.terms['due'], due)
        self.assertEqual(run.terms['late_minutes'], 30)
        self.assertGreater(run.terms['penalty'], 0)

    def test_economy_also_unavailable_blocks_proposal_without_partial_writes(self):
        self.s.deliver_next_request()
        self.s.deliver_next_request()
        self.s.select(2)
        self.s.choose_plan('performance')
        self.s.select(3)
        self.s.choose_plan('performance')
        self.s.select(1)
        events = list(map(tuple, self.db.get_request_events(1)))
        with self.assertRaisesRegex(ValueError, '절약형'):
            self.s.propose_alternative()
        self.assertEqual(self.s.current.proposals, [])
        self.assertEqual(list(map(tuple, self.db.get_request_events(1))), events)
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (9, 10))

    def test_duplicate_proposals_and_answers_are_blocked(self):
        self.s.propose_alternative()
        with self.assertRaises(ValueError):
            self.s.propose_alternative()
        self.s.review_alternative()
        for action in (self.s.propose_alternative, self.s.review_alternative):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(len(self.s.current.proposals), 1)

    def test_rejected_proposals_keep_separate_history(self):
        self.s.deliver_next_request()
        self.s.select(2)
        self.s.propose_alternative()
        self.s.review_alternative()
        first = deepcopy(self.s.current.proposals[0])
        self.s.advance_time(10)
        self.s.propose_alternative()
        self.assertEqual(self.s.current.proposals[0], first)
        self.assertEqual(self.s.current.proposals[1]['status'], 'pending')

    def test_only_pending_requests_can_negotiate_and_expiry_is_preserved(self):
        self.s.propose_alternative()
        for _ in range(6):
            self.s.advance_time(60)
        self.assertTrue(self.s.runs[1].terms['expired'])
        self.s.select(1)
        with self.assertRaises(ValueError):
            self.s.review_alternative()
        self.assertEqual(self.s.current.proposals[-1]['status'], 'pending')
    def test_running_request_cannot_negotiate(self):
        self.s.choose_plan('performance')
        with self.assertRaises(ValueError):
            self.s.propose_alternative()

    def test_legacy_request_without_deadline_cannot_get_speculative_consent(self):
        self.s.current.terms = {}
        self.s.propose_alternative()
        self.assertFalse(self.s.review_alternative())
        self.assertIn('완료 기한 정보가 없어', self.s.current.proposals[-1]['reason'])
        self.assertEqual(self.s.current.terms, {})

    def test_current_and_historical_link_conversations_include_proposal_and_answer(self):
        self.s.read_conversation(1)
        self.s.propose_alternative()
        steps = self.s.read_conversation(1)
        self.assertEqual(steps[0][0], '운영 담당자')
        self.assertIn('원래 요청:', steps[0][1])
        self.assertIn('검토하겠습니다', steps[-1][1])
        self.s.accept_request()
        self.assertEqual(self.s.current.proposals[-1]['status'], 'pending')
        with self.assertRaises(ValueError):
            self.s.choose_plan('economy')
        self.s.read_conversation(1)
        reopened = self.s.conversation(1)
        self.assertIn('제안 조건:', reopened[0][1])
        self.s.review_alternative()
        steps = self.s.read_conversation(1)
        self.assertIn('동의합니다', steps[-1][1])
        history = '\n'.join(text for _, text in self.s.conversation(1, history=True))
        self.assertIn('[신규 작업 요청]', history)
        self.assertIn('제안 조건:', history)
        self.assertIn('동의합니다', history)

    def test_proposal_save_failure_rolls_back_history_and_messages(self):
        before = (deepcopy(self.s.current.proposals), list(self.s.current.messages), dict(self.s.current.request))
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.propose_alternative()
        self.assertEqual((self.s.current.proposals, self.s.current.messages, self.s.current.request), before)
        self.assertFalse(any(e['kind'] == 'proposal' for e in self.db.get_request_events(1)))

    def test_customer_answer_save_failure_restores_pending_consent(self):
        self.s.propose_alternative()
        before = deepcopy(self.s.current.proposals)
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.review_alternative()
        self.assertEqual(self.s.current.proposals, before)
        self.assertFalse(any(e['kind'] == 'customer_proposal_decision' for e in self.db.get_request_events(1)))
        with self.assertRaises(ValueError):
            self.s.choose_plan('economy')
        self.assertTrue(self.s.review_alternative())

    def test_allocation_save_failure_preserves_customer_consent_and_resources(self):
        self.s.propose_alternative()
        self.s.review_alternative()
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.choose_plan('economy')
        self.assertEqual(self.s.current.proposals[-1]['status'], 'accepted')
        self.assertEqual(self.s.center.gpu_used, 0)
        self.assertIsNone(self.s.current.playthrough_id)
        self.assertEqual(self.db.get_recent_records(), [])
        self.s.choose_plan('economy')
        self.assertEqual(self.s.center.gpu_used, 4)

    def test_restart_gets_new_request_without_inheriting_agreement(self):
        old = self.s.current
        self.s.propose_alternative()
        self.s.review_alternative()
        self.s.reject_request('다른 일정으로 재접수')
        self.s.restart()
        self.assertEqual(self.s.current.proposals, [])
        self.assertEqual(old.proposals[-1]['status'], 'accepted')


class AlternativePersistenceTests(unittest.TestCase):
    def test_resume_pending_accepted_rejected_and_running_without_replaying_events(self):
        for stage in ('pending', 'accepted', 'rejected', 'running'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'test.db'
                db = Database(path)
                s = GameSession(db, seed=9, incident_chance=0)
                if stage == 'rejected':
                    s.deliver_next_request()
                    s.select(2)
                rid = s.selected_id
                s.propose_alternative()
                if stage != 'pending':
                    s.review_alternative()
                if stage == 'running':
                    s.choose_plan('economy')
                    s.advance_time(30)
                expected = deepcopy(s.current.proposals)
                message = s.current.request['message']
                terms = deepcopy(s.current.terms)
                events = list(map(tuple, db.get_request_events(rid)))
                s.close()
                db = Database(path)
                try:
                    s = GameSession(db)
                    s.select(rid)
                    self.assertEqual(s.current.proposals, expected)
                    self.assertEqual(s.current.request['message'], message)
                    self.assertEqual(s.current.terms, terms)
                    self.assertEqual(list(map(tuple, db.get_request_events(rid))), events)
                    self.assertEqual(s.center.gpu_used, 4 if stage == 'running' else 0)
                    if stage in ('pending', 'rejected'):
                        with self.assertRaises(ValueError):
                            s.choose_plan('economy')
                    elif stage == 'accepted':
                        s.choose_plan('economy')
                        self.assertEqual(s.center.gpu_used, 4)
                    else:
                        self.assertEqual(s.current.state.work_done, 21)
                finally:
                    db.close()

    def test_v06_payload_extension_preserves_tables_old_rows_and_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.db'
            db = Database(path)
            s = GameSession(db, seed=9, incident_chance=0)
            s.choose_plan('economy')
            for _ in range(3):
                s.advance_time(60)
            for rid in s.runs:
                payload = db.get_runtime(rid)
                payload.pop('proposals')
                db.save_runtime(rid, s.runs[rid].playthrough_id, payload)
            schema = list(map(tuple, db.conn.execute('SELECT name,sql FROM sqlite_master ORDER BY name')))
            tables = ('clients', 'missions', 'playthroughs', 'event_logs', 'customer_requests', 'request_events', 'retry_links')
            old = {table:list(map(tuple, db.conn.execute(f'SELECT * FROM {table} ORDER BY 1'))) for table in tables}
            db.close()
            for _ in range(2):
                db = Database(path)
                try:
                    s = GameSession(db)
                    self.assertTrue(all(not r.proposals for r in s.runs.values()))
                    s.save()
                    self.assertEqual(list(map(tuple, db.conn.execute('SELECT name,sql FROM sqlite_master ORDER BY name'))), schema)
                    for table in tables:
                        self.assertEqual(list(map(tuple, db.conn.execute(f'SELECT * FROM {table} ORDER BY 1'))), old[table])
                    self.assertEqual(db.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(db.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
                finally:
                    db.close()


class AlternativeGuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, seed=9, incident_chance=0)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        p = patch('main.messagebox')
        self.messages = p.start()
        self.addCleanup(p.stop)
        self.root.update()

    def test_actual_link_buttons_negotiate_then_start_agreed_economy(self):
        app = self.app
        app.next_request()
        app.next_request()
        app.select_request(3)
        app.choose_plan('economy')
        app.select_request(1)
        app.action_buttons['propose'].invoke()
        dialog = app.message_window
        dialog.reveal()
        self.assertIn('GPU -3개', dialog.bubble.get('1.0', 'end'))
        self.assertEqual(app.center.gpu_used, 4)
        self.assertEqual(app.action_buttons['start'].cget('state'), 'disabled')
        dialog.skip_button.invoke()
        self.assertEqual(dialog.next_button.cget('text'), '고객 답변 확인')
        dialog.next_button.invoke()
        app.message_window.reveal()
        self.assertIn('동의합니다', app.message_window.bubble.get('1.0', 'end'))
        self.assertEqual(app.plan_var.get(), 'economy')
        self.assertEqual(app.center.gpu_used, 4)
        app.action_buttons['start'].invoke()
        self.assertEqual(app.state.plan, 'economy')
        self.assertEqual(app.center.gpu_used, 8)
        self.assertEqual(self.errors, [])

    def test_rejected_plan_disables_economy_but_keeps_original_available(self):
        app = self.app
        app.next_request()
        app.select_request(2)
        app.action_buttons['propose'].invoke()
        app.message_window.skip()
        app.message_window.next_button.invoke()
        app.message_window.reveal()
        self.assertIn('거절', app.message_window.bubble.get('1.0', 'end'))
        self.assertEqual(app.center.gpu_used, 0)
        app.plan_var.set('economy')
        app.preview_plan()
        self.assertEqual(app.action_buttons['start'].cget('state'), 'disabled')
        app.plan_var.set('performance')
        app.preview_plan()
        self.assertEqual(app.action_buttons['start'].cget('state'), 'normal')
        self.assertEqual(self.errors, [])

    def test_stale_link_dialog_cannot_answer_for_another_customer(self):
        app = self.app
        app.propose_alternative()
        dialog = app.message_window
        dialog.skip()
        app.next_request()
        app.select_request(2)
        dialog.next_button.invoke()
        self.assertEqual(app.session.runs[1].proposals[-1]['status'], 'pending')
        self.assertEqual(app.session.current.proposals, [])
        self.messages.showerror.assert_called_once()
        self.assertEqual(self.errors, [])

    def test_proposal_controls_fit_minimum_window_and_reopen_without_resubmitting(self):
        app = self.app
        app.action_buttons['propose'].invoke()
        count = len(app.session.current.proposals)
        app.message_window.destroy()
        app.action_buttons['propose'].invoke()
        self.assertEqual(len(app.session.current.proposals), count)
        self.assertIn('원래 요청:', app.message_window.steps[0][1])
        self.root.geometry('1000x650')
        self.root.update()
        for widget in (*app.action_buttons.values(), app.action_hint, app.resources.preview, app.time_buttons[60]):
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
