"""고객 기한, 사건별 대화, 호환 저장과 원자적 복구 검증."""
from copy import deepcopy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import Database
from session import GameSession


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=9, incident_chance=0)

    def japan(self):
        self.s.deliver_next_request()
        self.s.select(2)
        return self.s.current

    def test_customer_windows_and_mode_estimates_differ(self):
        s = self.s
        s.deliver_next_request(); s.deliver_next_request()
        values = []
        for run in s.runs.values():
            t = run.terms
            values.append((t['start_due']-540, t['due']-540, t['expires']-540))
            self.assertLess(run.state.estimate_minutes('performance'), run.state.estimate_minutes('economy'))
        self.assertEqual(values, [(60,210,330),(20,70,190),(40,120,240)])

    def test_waiting_time_and_reminders_occur_once(self):
        run = self.japan()
        self.s.wait_request()
        self.s.advance_time(30)
        self.assertIn('대기 30분', self.s.deadline_summary(run))
        self.assertEqual(run.terms['alerts'], ['allocation_due'])
        self.s.advance_time(60)
        self.assertEqual(run.terms['alerts'], ['allocation_due','deadline_near','deadline_passed'])
        self.s.advance_time(30)
        kinds = [e['kind'] for e in self.db.get_request_events(2)]
        for key in run.terms['alerts']:
            self.assertEqual(kinds.count('customer_'+key), 1)
        self.assertEqual(run.state.gpu_used, 0)

    def test_ignored_request_expires_as_unprocessed_not_execution_failure(self):
        run = self.japan()
        for _ in range(3): self.s.advance_time(60)
        self.assertEqual(run.request['status'], 'review')
        self.s.advance_time(10)
        self.assertTrue(run.terms['expired'])
        self.assertEqual(run.terms['evaluation'], 0)
        self.assertEqual(run.request['status'], 'rejected')
        self.assertIn('미처리', run.request['rejection_reason'])
        self.assertIsNone(run.playthrough_id)
        self.assertEqual(self.db.get_recent_records(), [])
        self.assertEqual(self.s.center.gpu_used, 0)
        with self.assertRaises(ValueError): self.s.choose_plan('performance')
        count = len(self.db.get_request_events(2))
        self.s.advance_time(60)
        self.assertEqual(len(self.db.get_request_events(2)), count)

    def test_urgent_performance_meets_deadline_economy_finishes_late(self):
        outcomes = []
        for mode in ('performance','economy'):
            db = Database(':memory:')
            try:
                s = GameSession(db, seed=9, incident_chance=0)
                s.deliver_next_request(); s.select(2); s.choose_plan(mode)
                while s.current.state.phase != 'finished': s.advance_time(10)
                r = s.current
                outcomes.append((s.minute-540, r.terms['late_minutes'], r.state.score))
                self.assertEqual(s.center.gpu_used, 0)
                self.assertEqual(db.get_playthrough(r.playthrough_id)['score'], r.state.score)
            finally: db.close()
        self.assertEqual(outcomes, [(60,0,100),(90,20,85)])

    def test_late_start_and_completion_are_penalized_separately(self):
        run = self.japan()
        self.s.advance_time(30)
        self.s.choose_plan('performance')
        self.s.advance_time(60)
        self.assertTrue(run.state.succeeded)
        self.assertEqual(run.terms['penalty'], 12)  # 배정 10분=2점, 완료 20분=10점
        self.assertEqual(run.state.score, 88)
        self.assertIn('일정보다 지연', run.last_feedback)

    def test_notice_does_not_extend_due_or_erase_deadline_penalty(self):
        run = self.japan()
        self.s.choose_plan('economy')
        due = run.terms['due']
        self.s.notify_delay()
        self.s.advance_time(60); self.s.advance_time(30)
        self.assertEqual(run.terms['due'], due)
        self.assertEqual(run.terms['penalty'], 10)
        self.assertEqual(run.state.score, 80)  # 소통 비용 5점과 기한 감점은 독립
        with self.assertRaises(ValueError): self.s.notify_delay()

    def test_notify_is_blocked_for_normal_on_time_and_all_finished_jobs(self):
        s = self.s
        s.choose_plan('performance')
        with self.assertRaises(ValueError): s.notify_delay()
        s.current.state.trigger_incident()
        for _ in range(3): s.respond('ignore')
        self.assertFalse(s.current.state.succeeded)
        before = len(self.db.get_request_events(1))
        with self.assertRaises(ValueError): s.notify_delay()
        self.assertEqual(len(self.db.get_request_events(1)), before)

    def test_current_dialog_never_returns_to_original_request_after_start(self):
        s = self.s
        first = s.read_conversation(1)
        self.assertIn('[신규 작업 요청]', first[0][1])
        s.accept_request()
        self.assertIn('배정 일정을 확인', s.read_conversation(1)[0][1])
        s.choose_plan('economy')
        for _ in range(3):
            text = '\n'.join(t for _,t in s.read_conversation(1))
            self.assertIn('작업이 진행 중', text)
            self.assertNotIn('[신규 작업 요청]', text)
        count = len(self.db.get_request_events(1))
        s.read_conversation(1)
        self.assertEqual(len(self.db.get_request_events(1)), count)

    def test_incident_notice_recovery_and_completion_messages_follow_state(self):
        s = self.s; s.choose_plan('economy')
        s.current.state.incident_at = 7
        s.advance_time(10)
        self.assertIn('복구 상황', s.read_conversation(1)[0][1])
        s.notify_delay()
        steps = s.read_conversation(1)
        self.assertIn('지연을 안내', steps[0][1])
        self.assertIn('안내 감사합니다', steps[1][1])
        s.respond('reroute'); s.advance_time(10)
        self.assertIn('작업이 재개', s.read_conversation(1)[0][1])
        while s.current.state.phase != 'finished': s.advance_time(10)
        text = '\n'.join(t for _,t in s.read_conversation(1))
        self.assertIn('작업 완료', text)
        self.assertNotIn('복구 상황', text)
        history = s.conversation(1, history=True)
        self.assertIn('[신규 작업 요청]', history[0][1])
        minutes = [e['game_minute'] for e in self.db.get_request_events(1)]
        self.assertEqual(minutes, sorted(minutes))

    def test_reading_history_preserves_unread_and_clock(self):
        s = self.s; s.choose_plan('performance')
        before = (s.current.message_read_id, s.current.request['is_read'], s.minute)
        s.conversation(1, history=True)
        self.assertEqual((s.current.message_read_id, s.current.request['is_read'], s.minute), before)

    def test_resume_preserves_deadline_alerts_and_read_position(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'resume.db'
            db = Database(path)
            s = GameSession(db, seed=9, incident_chance=0)
            s.deliver_next_request(); s.select(2); s.wait_request(); s.advance_time(60)
            s.read_conversation(2)
            terms, cursor = deepcopy(s.current.terms), s.current.message_read_id
            s.close()
            db = Database(path)
            try:
                restored = GameSession(db)
                r = restored.runs[2]
                self.assertEqual((r.terms, r.message_read_id), (terms, cursor))
                restored.advance_time(30)
                kinds = [e['kind'] for e in db.get_request_events(2)]
                self.assertEqual(kinds.count('customer_deadline_near'), 1)
                self.assertEqual(kinds.count('customer_deadline_passed'), 1)
            finally: db.close()

    def test_legacy_payload_without_terms_is_exempt_and_records_unchanged(self):
        s = self.s; s.choose_plan('economy'); s.advance_time(30)
        payload = self.db.get_runtime(1)
        for key in ('terms','message_read_id','version'): payload.pop(key)
        self.db.save_runtime(1, s.current.playthrough_id, payload)
        old = self.db.create_playthrough(2, 'economy')
        self.db.save_result(old, 'normal', True, 77, '과거 결과')
        record = tuple(self.db.get_playthrough(old))
        restored = GameSession(self.db)
        self.assertEqual(restored.runs[1].terms, {})
        self.assertEqual(restored.runs[1].state.work_done, 21)
        for _ in range(3): restored.advance_time(60)
        self.assertEqual(restored.runs[1].state.score, 95)
        self.assertEqual(tuple(self.db.get_playthrough(old)), record)
        self.assertIn('기한 평가 제외', restored.deadline_summary(restored.runs[1]))

    def test_save_failure_restores_alerts_deadlines_new_requests_and_messages(self):
        run = self.japan()
        terms, messages = deepcopy(run.terms), list(run.messages)
        events = [tuple(e) for e in self.db.get_request_events(2)]
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError): self.s.advance_time(60)
        self.assertEqual(run.terms, terms)
        self.assertEqual(run.messages, messages)
        self.assertEqual(self.s.minute, 540)
        self.assertEqual([tuple(e) for e in self.db.get_request_events(2)], events)
        self.s.advance_time(60)
        self.assertEqual(run.terms['alerts'], ['allocation_due','deadline_near'])

    def test_failed_completion_save_restores_penalty_and_allocation(self):
        run = self.japan(); self.s.choose_plan('economy'); self.s.advance_time(60)
        terms = deepcopy(run.terms)
        with patch.object(self.db, 'save_result', side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError): self.s.advance_time(30)
        self.assertEqual(run.terms, terms)
        self.assertIsNone(run.state.score)
        self.assertEqual((run.state.phase, self.s.center.gpu_used, self.s.minute), ('running',2,600))
        self.s.advance_time(30)
        self.assertEqual(run.state.score, 85)

    def test_failed_read_does_not_consume_new_message(self):
        before = (self.s.current.message_read_id, self.s.current.request['is_read'])
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError): self.s.read_conversation(1)
        self.assertEqual((self.s.current.message_read_id, self.s.current.request['is_read']), before)

    def test_expiry_save_failure_restores_request_and_zero_evaluation(self):
        run = self.japan()
        for _ in range(3): self.s.advance_time(60)
        with patch.object(self.db, 'save_simulation', side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError): self.s.advance_time(10)
        self.assertNotIn('expired', run.terms)
        self.assertEqual(run.request['status'], 'review')
        self.assertEqual(self.db.get_request(2)['status'], 'review')
        self.s.advance_time(10)
        self.assertEqual(run.terms['evaluation'], 0)

    def test_replayed_arrival_key_does_not_reset_terms_or_duplicate_messages(self):
        run = self.s.current
        self.s.choose_plan('economy'); self.s.advance_time(30)
        before = (deepcopy(run.terms), list(run.messages), run.state.work_done)
        with self.s._atomic():
            rid = self.s._receive(1, 'initial:1')
        self.assertEqual(rid, 1)
        self.assertIs(self.s.runs[1], run)
        self.assertEqual((run.terms,run.messages,run.state.work_done), before)
