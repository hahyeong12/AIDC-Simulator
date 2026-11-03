"""v0.7-2 최초 고객 조건, 실행 경계, 저장 호환과 실제 Tk 선택 표시 검증."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from game import CUSTOMER_PLANS
from main import SimulatorApp
from session import GameSession


class ConditionTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=9, incident_chance=0)

    def snapshot(self):
        return (deepcopy(self.db.get_runtime(self.s.selected_id)),
                list(map(tuple, self.db.get_request_events(self.s.selected_id))),
                list(map(tuple, self.db.get_recent_records())),
                self.s.center.gpu_used, self.s.center.power_used)

    def agree(self):
        self.s.propose_alternative()
        self.assertTrue(self.s.review_alternative())

    def test_initial_conditions_separate_task_mode_resources_deadline_and_permission(self):
        c = self.s.current.conditions
        self.assertEqual(c['type'], 'fixed')
        self.assertEqual(c['task'], self.s.current.mission['title'])
        self.assertEqual(c['requested_mode'], 'performance')
        self.assertEqual(c['allowed_modes'], ['performance'])
        self.assertEqual((c['plans']['performance']['gpu'], c['plans']['performance']['power']), (7, 7))
        self.assertEqual(c['due'], self.s.current.terms['due'])
        self.assertEqual(self.db.get_runtime(1)['conditions'], c)
        for text in ('원래 요청 모드: 고성능', '명시적인 동의', '고객 동의 필요', '완료 기한: D1 12:30'):
            self.assertIn(text, self.s.current.request['message'])

    def test_requested_plan_starts_without_proposal(self):
        self.s.choose_plan('performance')
        run = self.s.current
        self.assertEqual(run.proposals, [])
        self.assertEqual((run.state.plan, self.s.center.gpu_used, self.s.center.power_used), ('performance', 7, 7))
        self.assertEqual(self.db.get_playthrough(run.playthrough_id)['plan'], 'performance')

    def test_direct_economy_is_blocked_without_any_proposal_or_side_effect(self):
        before = self.snapshot()
        self.assertFalse(self.s.plan_agreed(self.s.current, 'economy'))
        with self.assertRaisesRegex(ValueError, '고객'):
            self.s.choose_plan('economy')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.s.current.state.phase, 'ready')
        self.assertIsNone(self.s.current.playthrough_id)

    def test_accepting_waiting_or_selecting_request_does_not_grant_mode_consent(self):
        for operation in (self.s.accept_request, self.s.wait_request, lambda: self.s.select(1)):
            operation()
            before = self.snapshot()
            with self.assertRaises(ValueError):
                self.s.choose_plan('economy')
            self.assertEqual(self.snapshot(), before)

    def test_unknown_mode_is_never_agreed(self):
        self.assertFalse(self.s.plan_agreed(self.s.current, 'unknown'))
        with self.assertRaises(ValueError):
            self.s.choose_plan('unknown')

    def test_pending_negotiation_blocks_both_modes_and_duplicate_submission(self):
        self.s.propose_alternative()
        before = self.snapshot()
        for mode in ('performance', 'economy'):
            with self.assertRaises(ValueError):
                self.s.choose_plan(mode)
        with self.assertRaises(ValueError):
            self.s.propose_alternative()
        self.assertEqual(self.snapshot(), before)

    def test_original_contract_and_message_survive_agreement_and_completion(self):
        run = self.s.current
        original, message, due = deepcopy(run.conditions), run.request['message'], run.terms['due']
        self.agree()
        self.s.choose_plan('economy')
        for _ in range(3):
            self.s.advance_time(60)
        self.assertTrue(run.state.succeeded)
        self.assertEqual(run.conditions, original)
        self.assertEqual(run.request['message'], message)
        self.assertEqual(run.terms['due'], due)
        self.assertEqual(run.proposals[-1]['original']['gpu'], 7)
        self.assertEqual(run.proposals[-1]['proposed']['gpu'], run.state.gpu_used)
        self.assertEqual(self.db.get_runtime(1)['conditions'], original)

    def test_requested_mode_is_still_available_after_alternative_agreement(self):
        self.agree()
        self.s.choose_plan('performance')
        self.assertEqual(self.s.current.state.gpu_used, 7)
        self.assertEqual(self.s.current.proposals[-1]['status'], 'accepted')

    def test_japan_is_fixed_and_rejected_economy_never_starts(self):
        self.s.deliver_next_request()
        self.s.select(2)
        run = self.s.current
        original = deepcopy(run.conditions)
        self.s.propose_alternative()
        self.assertFalse(self.s.review_alternative())
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.s.choose_plan('economy')
        with self.assertRaises(ValueError):
            self.s.propose_alternative()
        self.assertEqual(self.snapshot(), before)
        self.s.choose_plan('performance')
        self.assertEqual(run.conditions, original)
        self.assertEqual((run.state.gpu_used, run.state.power_used), (3, 4))

    def test_flexible_request_allows_each_mode_without_negotiation(self):
        for mode, resources in (('performance', (6, 6)), ('economy', (4, 3))):
            with self.subTest(mode=mode), DatabaseForTest() as db:
                s = GameSession(db, seed=9, incident_chance=0)
                s.deliver_next_request(); s.deliver_next_request(); s.select(3)
                run = s.current
                self.assertEqual(run.conditions['type'], 'flexible')
                self.assertEqual(run.conditions['allowed_modes'], ['performance', 'economy'])
                self.assertIn('고성능·절약형 모두 허용', run.request['message'])
                with self.assertRaisesRegex(ValueError, '이미 허용'):
                    s.propose_alternative()
                s.choose_plan(mode)
                self.assertEqual((s.center.gpu_used, s.center.power_used), resources)
                self.assertEqual(run.proposals, [])

    def test_flexible_request_rechecks_power_shortage_without_changing_permission(self):
        self.s.deliver_next_request(); self.s.deliver_next_request(); self.s.select(3)
        original = deepcopy(self.s.current.conditions)
        self.s.center.allocate(1, 8)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '전력 1단위'):
            self.s.choose_plan('economy')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.s.current.conditions, original)

    def test_requested_mode_rechecks_shortage(self):
        self.s.center.allocate(4, 4)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'GPU 1개 / 전력 1단위'):
            self.s.choose_plan('performance')
        self.assertEqual(self.snapshot(), before)

    def test_agreed_alternative_cannot_execute_different_resource_conditions(self):
        self.agree()
        before = self.snapshot()
        for field in ('gpu', 'power', 'network'):
            with self.subTest(field=field), patch.dict(CUSTOMER_PLANS['싱가포르']['economy'], {field: 5}):
                self.assertFalse(self.s.plan_agreed(self.s.current, 'economy'))
                with self.assertRaises(ValueError):
                    self.s.choose_plan('economy')
                self.assertEqual(self.snapshot(), before)

    def test_initial_permission_also_requires_matching_resource_conditions(self):
        for country, mode, rid in (('싱가포르', 'performance', 1), ('미국', 'economy', 3)):
            while len(self.s.runs) < rid:
                self.s.deliver_next_request()
            self.s.select(rid)
            before = self.snapshot()
            with self.subTest(country=country), patch.dict(CUSTOMER_PLANS[country][mode], {'gpu': 8}):
                with self.assertRaises(ValueError):
                    self.s.choose_plan(mode)
                self.assertEqual(self.snapshot(), before)

    def test_retry_cannot_bypass_original_conditions_and_rolls_back_replacement_state(self):
        self.s.choose_plan('performance')
        self.s.current.state.trigger_incident()
        for _ in range(3):
            self.s.respond('ignore')
        run = self.s.current
        state, parent, before = run.state, run.playthrough_id, self.snapshot()
        with self.assertRaises(ValueError):
            self.s.retry('economy')
        self.assertIs(run.state, state)
        self.assertEqual(run.playthrough_id, parent)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.db.conn.execute('SELECT count(*) FROM retry_links').fetchone()[0], 0)
        self.s.retry('performance')
        self.assertEqual(run.state.plan, 'performance')

    def test_new_request_does_not_inherit_preceding_consent(self):
        old = self.s.current
        self.agree()
        self.s.reject_request('새 일정으로 재접수')
        self.s.restart()
        self.assertEqual(old.proposals[-1]['status'], 'accepted')
        self.assertEqual(self.s.current.proposals, [])
        self.assertFalse(self.s.plan_agreed(self.s.current, 'economy'))
        self.assertTrue(self.s.current.conditions)

    def test_initial_contract_save_failure_rolls_back_intake_and_all_rows(self):
        before = (self.snapshot(), list(self.s.runs), self.s.selected_id, dict(self.s.arrival_last))
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('저장 실패')):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.deliver_next_request()
        self.assertEqual((self.snapshot(), list(self.s.runs), self.s.selected_id, dict(self.s.arrival_last)), before)
        self.assertEqual(len(self.db.get_requests()), 1)
        self.assertEqual(self.db.get_request_events(2), [])
        self.assertEqual(self.s.deliver_next_request(), 2)
        self.assertEqual(self.s.runs[2].conditions['type'], 'fixed')

    def test_original_allocation_save_failure_preserves_contract_and_database(self):
        original, before = deepcopy(self.s.current.conditions), self.snapshot()
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('저장 실패')):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.choose_plan('performance')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.s.current.conditions, original)
        self.assertIsNone(self.s.current.playthrough_id)
        self.s.choose_plan('performance')

    def test_negotiation_dialog_does_not_replay_read_original_request(self):
        self.s.read_conversation(1)
        self.s.propose_alternative()
        text = '\n'.join(text for _, text in self.s.read_conversation(1))
        for expected in ('원래 요청:', '제안 조건:', 'GPU 4개', '예상 완료 기한은 충족'):
            self.assertIn(expected, text)
        self.assertNotIn('[신규 작업 요청]', text)
        self.s.review_alternative()
        text = '\n'.join(text for _, text in self.s.read_conversation(1))
        self.assertIn('동의합니다', text)
        self.assertNotIn('[신규 작업 요청]', text)


class DatabaseForTest(Database):
    """짧은 하위 시나리오에서도 테스트 실패 시 연결을 닫습니다."""
    def __init__(self):
        super().__init__(':memory:')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ConditionPersistenceTests(unittest.TestCase):
    def test_conditions_and_answers_survive_repeated_resume_without_replayed_events(self):
        for stage in ('original', 'pending', 'accepted', 'rejected', 'running', 'completed', 'flexible'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'conditions.db'
                db = Database(path)
                try:
                    s = GameSession(db, seed=9, incident_chance=0)
                    if stage == 'rejected':
                        s.deliver_next_request(); s.select(2)
                    elif stage == 'flexible':
                        s.deliver_next_request(); s.deliver_next_request(); s.select(3)
                    if stage not in ('original', 'flexible'):
                        s.propose_alternative()
                        if stage != 'pending':
                            s.review_alternative()
                        if stage in ('running', 'completed'):
                            s.choose_plan('economy')
                        if stage == 'completed':
                            for _ in range(3):
                                s.advance_time(60)
                    rid = s.selected_id
                    expected = deepcopy(s.current.conditions), deepcopy(s.current.proposals), s.current.request['message']
                    events = list(map(tuple, db.get_request_events(rid)))
                    records = list(map(tuple, db.conn.execute('SELECT * FROM playthroughs ORDER BY id')))
                finally:
                    db.close()  # 정상 종료 시 저장하지 않고 마지막 동작의 저장만으로 복원합니다.
                for _ in range(2):
                    db = Database(path)
                    try:
                        s = GameSession(db)
                        s.select(rid)
                        self.assertEqual((s.current.conditions, s.current.proposals, s.current.request['message']), expected)
                        self.assertEqual(list(map(tuple, db.get_request_events(rid))), events)
                        self.assertEqual(list(map(tuple, db.conn.execute('SELECT * FROM playthroughs ORDER BY id'))), records)
                        self.assertEqual(s.plan_agreed(s.current, 'economy'), stage in ('accepted', 'running', 'completed', 'flexible'))
                        s.save()
                    finally:
                        db.close()

    def test_missing_conditions_never_retrofits_customer_intent_but_new_intake_gets_it(self):
        with DatabaseForTest() as db:
            s = GameSession(db, seed=9, incident_chance=0)
            payload = db.get_runtime(1)
            payload.pop('conditions')
            db.save_runtime(1, None, payload)
            message, events = s.current.request['message'], list(map(tuple, db.get_request_events(1)))
            old = db.create_playthrough(3, 'economy')
            db.save_result(old, 'normal', True, 73, '과거 결과')
            record = tuple(db.get_playthrough(old))
            restored = GameSession(db)
            self.assertEqual(restored.current.conditions, {})
            self.assertTrue(restored.plan_agreed(restored.current, 'economy'))
            restored.save()
            self.assertEqual(db.get_runtime(1)['conditions'], {})
            self.assertEqual(restored.current.request['message'], message)
            self.assertEqual(list(map(tuple, db.get_request_events(1))), events)
            self.assertEqual(tuple(db.get_playthrough(old)), record)
            restored.choose_plan('economy')
            restored.deliver_next_request()
            self.assertEqual(restored.runs[2].conditions['allowed_modes'], ['performance'])
            self.assertEqual(tuple(db.get_playthrough(old)), record)

    def test_legacy_proposal_restrictions_remain_even_without_initial_conditions(self):
        for stage in ('pending', 'accepted', 'rejected'):
            with self.subTest(stage=stage), DatabaseForTest() as db:
                s = GameSession(db, seed=9, incident_chance=0)
                s.propose_alternative()
                if stage == 'rejected':
                    s.advance_time(60)
                if stage != 'pending':
                    s.review_alternative()
                payload = db.get_runtime(1)
                payload.pop('conditions')
                db.save_runtime(1, None, payload)
                restored = GameSession(db)
                self.assertEqual(restored.current.conditions, {})
                self.assertEqual(restored.plan_agreed(restored.current, 'economy'), stage == 'accepted')
                self.assertEqual(restored.plan_agreed(restored.current, 'performance'), stage != 'pending')

    def test_request_without_any_runtime_keeps_original_message_and_completed_score(self):
        with DatabaseForTest() as db:
            rid = db.create_request(1, '과거 고객 요청 · 원래 의사 알 수 없음')
            old = db.create_playthrough(1, 'economy')
            db.change_request_status(rid, 'operating', old)
            db.save_result(old, 'compress', True, 85, '기존 완료 점수')
            db.change_request_status(rid, 'completed', old)
            record = tuple(db.get_playthrough(old))
            s = GameSession(db, seed=9, incident_chance=0)
            self.assertEqual(s.current.conditions, {})
            self.assertEqual(s.current.terms, {})
            self.assertEqual(s.current.state.score, 85)
            self.assertEqual(s.current.request['message'], '과거 고객 요청 · 원래 의사 알 수 없음')
            s.save(); s.advance_time(60)
            self.assertEqual(tuple(db.get_playthrough(old)), record)
            self.assertEqual(db.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.conn.execute('PRAGMA foreign_key_check').fetchall(), [])


class ConditionGuiTests(unittest.TestCase):
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
        messages = patch('main.messagebox')
        self.messages = messages.start()
        self.addCleanup(messages.stop)

    def economy(self):
        self.app.plan_var.set('economy')
        self.app.preview_plan()

    def test_original_and_unapproved_modes_are_distinguished_and_direct_call_is_blocked(self):
        a = self.app
        self.assertIn('고객 원래 요청', a.mode_buttons['performance'].cget('text'))
        self.assertIn('고객 동의 필요', a.mode_buttons['economy'].cget('text'))
        self.economy()
        self.assertEqual(a.action_buttons['start'].cget('state'), 'disabled')
        a.choose_plan('economy')
        self.messages.showerror.assert_called_once()
        self.assertEqual(a.center.gpu_used, 0)
        self.assertEqual(self.errors, [])

    def test_agreement_and_subsequent_shortage_are_both_visible(self):
        a = self.app
        a.session.propose_alternative(); a.refresh(); self.economy()
        self.assertIn('협의 중', a.mode_buttons['economy'].cget('text'))
        self.assertEqual(a.action_buttons['start'].cget('state'), 'disabled')
        self.assertTrue(a.session.review_alternative())
        a.refresh()
        self.assertIn('고객 동의 완료', a.mode_buttons['economy'].cget('text'))
        self.assertEqual(a.action_buttons['start'].cget('state'), 'normal')
        a.center.allocate(7, 7)
        a.preview_plan()
        text = a.mode_buttons['economy'].cget('text')
        self.assertIn('고객 동의 완료', text)
        self.assertIn('자원 부족', text)
        self.assertEqual(a.action_buttons['start'].cget('state'), 'disabled')
        self.assertEqual(self.errors, [])

    def test_flexible_modes_need_no_proposal_button_or_conversation(self):
        a = self.app
        a.next_request(); a.next_request(); a.select_request(3)
        self.assertIn('고객 원래 요청', a.mode_buttons['performance'].cget('text'))
        self.assertIn('고객 허용 모드', a.mode_buttons['economy'].cget('text'))
        self.assertNotIn('propose', a.action_buttons)
        self.economy()
        a.action_buttons['start'].invoke()
        self.assertEqual((a.state.plan, a.center.gpu_used, a.center.power_used), ('economy', 4, 3))
        self.assertEqual(a.session.current.proposals, [])
        self.assertEqual(self.errors, [])

    def test_rejection_is_visible_and_cannot_be_resubmitted(self):
        a = self.app
        a.next_request(); a.select_request(2)
        a.session.propose_alternative(); self.assertFalse(a.session.review_alternative()); a.refresh()
        self.assertIn('고객 거절', a.mode_buttons['economy'].cget('text'))
        self.assertNotIn('propose', a.action_buttons)
        self.economy()
        self.assertEqual(a.action_buttons['start'].cget('state'), 'disabled')
        a.plan_var.set('performance'); a.preview_plan()
        self.assertEqual(a.action_buttons['start'].cget('state'), 'normal')

    def test_mode_labels_fit_minimum_window_during_negotiation_and_shortage(self):
        a = self.app
        self.root.geometry('1000x650')
        for stage in ('original', 'pending', 'accepted', 'shortage', 'flexible', 'rejected', 'legacy'):
            if stage == 'pending':
                a.session.propose_alternative()
            elif stage == 'accepted':
                a.session.review_alternative()
            elif stage == 'shortage':
                a.center.allocate(7, 7)
            elif stage == 'flexible':
                a.center.release(7, 7)
                a.next_request(); a.next_request(); a.select_request(3)
            elif stage == 'rejected':
                a.select_request(2); a.session.propose_alternative(); a.session.review_alternative()
            elif stage == 'legacy':
                a.session.current.conditions = {}; a.session.current.proposals = []
            a.refresh()
            self.root.update()
            for widget in (*a.mode_buttons.values(), a.action_hint, a.resources.preview, *a.action_buttons.values()):
                with self.subTest(stage=stage, widget=str(widget)):
                    self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
                    self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
