"""가상 시간, 독립적인 장애, 후속 대응, 이어하기와 원자적 저장 검증."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import Database
from session import GameSession


def finish_current(session):
    for _ in range(80):
        if session.current.state.phase == 'finished':
            return
        if session.current.state.phase in ('incident','paused'):
            session.respond('reroute')
        session.advance_time(10)
    raise AssertionError('작업이 완료되지 않았습니다.')


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db,seed=12,incident_chance=0)

    def test_accept_without_allocation_then_start_is_normal(self):
        self.s.accept_request()
        self.assertEqual(self.s.current.state.phase,'accepted')
        self.assertEqual(self.s.center.gpu_used,0)
        self.assertEqual(self.db.get_recent_records(),[])
        self.s.choose_plan('economy')
        self.assertEqual(self.s.current.state.phase,'running')
        self.assertEqual(self.s.current.state.network_available,8)
        self.assertEqual(self.s.current.state.progress,0)

    def test_time_and_progress_then_success_releases_only_own_resources(self):
        s=self.s
        s.choose_plan('economy')
        first=s.current
        s.deliver_next_request(); s.select(2); s.choose_plan('performance')
        s.advance_time(30)
        self.assertEqual(s.time_label,'D1 09:30')
        self.assertEqual(first.state.work_done,21)
        self.assertEqual(s.current.state.work_done,30)
        s.advance_time(30)
        self.assertTrue(s.current.state.succeeded)
        self.assertEqual((s.center.gpu_used,s.center.power_used),(4,4))
        s.select(1); finish_current(s)
        self.assertEqual((s.center.gpu_used,s.center.power_used),(0,0))

    def test_scheduled_arrivals_and_invalid_steps(self):
        self.s.advance_time(60)
        self.assertEqual(len(self.s.runs),2)
        self.s.advance_time(60)
        self.assertEqual(len(self.s.runs),2)  # 미처리 요청 2건이면 추가 접수를 보류합니다.
        self.assertEqual(self.s.pending_request_count,2)
        for value in (0,-10,5,True,1.5,120):
            with self.assertRaises(ValueError): self.s.advance_time(value)

    def test_fault_pauses_only_one_job_and_backup_resumes_after_delay(self):
        s=self.s
        s.choose_plan('economy')
        first=s.current
        first.state.incident_at=7
        s.deliver_next_request(); s.select(2); s.choose_plan('performance')
        s.advance_time(10)
        self.assertEqual(first.state.phase,'incident')
        work=first.state.work_done
        s.advance_time(10)
        self.assertEqual(first.state.work_done,work)
        self.assertEqual(s.current.state.work_done,20)
        s.select(1); s.respond('reroute')
        self.assertEqual(first.state.phase,'recovering')
        self.assertEqual(s.center.gpu_used,7)
        s.advance_time(10)
        self.assertEqual(first.state.phase,'running')
        self.assertEqual(first.state.work_done,work)
        s.advance_time(10)
        self.assertGreater(first.state.work_done,work)
        self.assertTrue(any('네트워크 장애' in r['message'] for r in self.db.get_request_events(1)))

    def test_failed_response_can_be_followed_by_another_response(self):
        s=self.s; s.choose_plan('performance'); s.current.state.trigger_incident()
        s.respond('ignore')
        self.assertEqual(s.current.state.phase,'paused')
        self.assertEqual(s.center.gpu_used,7)
        s.respond('reroute')
        self.assertEqual(s.current.state.phase,'recovering')
        self.assertEqual(self.db.get_recent_results(),[])
        finish_current(s)
        self.assertTrue(s.current.state.succeeded)

    def test_timeout_records_failure_and_customer_followup(self):
        self.s.choose_plan('economy'); self.s.current.state.trigger_incident()
        self.s.advance_time(60)
        self.assertFalse(self.s.current.state.succeeded)
        self.assertEqual(self.s.center.gpu_used,0)
        self.assertEqual(self.db.get_recent_results()[0]['status'],'실패')
        self.assertIn('복구',self.s.current.last_feedback)

    def test_retry_preserves_failure_and_links_new_attempt_with_cost(self):
        s=self.s; s.choose_plan('performance'); s.current.state.trigger_incident()
        s.respond('ignore')
        s.notify_delay()
        for _ in range(2): s.respond('ignore')
        parent=s.current.playthrough_id
        old=tuple(self.db.get_playthrough(parent))
        with self.assertRaises(ValueError): s.notify_delay()  # 종료 후에는 안내 대신 재처리·최종 보고
        s.retry('economy')
        child=s.current.playthrough_id
        self.assertNotEqual(parent,child)
        self.assertEqual(s.current.state.recovery_left,20)
        self.assertEqual(s.current.state.retry_count,1)
        self.assertEqual(s.center.gpu_used,4)
        self.assertEqual(self.db.get_retry_links(1)[0]['parent_id'],parent)
        s.advance_time(10)
        self.assertEqual(s.current.state.progress,0)
        finish_current(s)
        self.assertEqual(tuple(self.db.get_playthrough(parent)),old)
        self.assertEqual(self.db.get_playthrough(child)['status'],'성공')
        self.assertLess(s.current.state.score,95)

    def test_retry_limit_and_final_report_never_overwrite_failed_result(self):
        s=self.s; s.choose_plan('economy'); s.report_failure()
        # 보고로 닫힌 요청은 재처리하지 않습니다.
        with self.assertRaises(ValueError): s.retry('economy')
        s.restart(); s.choose_plan('economy')
        for attempt in range(3):
            s.current.state.trigger_incident() if s.current.state.phase=='running' else None
            if s.current.state.phase=='recovering': s.advance_time(30); s.current.state.trigger_incident()
            s.advance_time(60)
            if attempt<2: s.retry('economy')
        with self.assertRaises(ValueError): s.retry('performance')
        run_id=s.current.playthrough_id
        before=tuple(self.db.get_playthrough(run_id))
        s.report_failure()
        self.assertTrue(s.current.followup_closed)
        self.assertEqual(tuple(self.db.get_playthrough(run_id)),before)

    def test_time_save_failure_rolls_back_every_job_clock_arrivals_and_events(self):
        s=self.s; s.choose_plan('economy')
        state=s.current.state
        with patch.object(self.db,'save_runtime',side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError): s.advance_time(60)
        self.assertEqual(s.minute,540)
        self.assertIs(s.current.state,state)
        self.assertEqual(state.work_done,0)
        self.assertEqual(len(s.runs),1)
        self.assertEqual(len(self.db.get_requests()),1)
        self.assertEqual(self.db.get_simulation()['minute'],540)
        self.assertEqual(s.center.gpu_used,4)

    def test_completion_save_failure_restores_allocation_and_allows_retry(self):
        s=self.s; s.deliver_next_request(); s.select(2); s.choose_plan('performance'); s.advance_time(30)
        with patch.object(self.db,'save_result',side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError): s.advance_time(30)
        self.assertEqual(s.current.state.work_done,30)
        self.assertEqual(s.current.state.phase,'running')
        self.assertEqual(s.center.gpu_used,3)
        self.assertEqual(self.db.get_recent_results(),[])
        s.advance_time(30)
        self.assertEqual(s.current.state.phase,'finished')

    def test_retry_link_failure_restores_original_failed_job(self):
        s=self.s; s.choose_plan('economy'); s.current.state.trigger_incident(); s.advance_time(60)
        state,run_id=s.current.state,s.current.playthrough_id
        with patch.object(self.db,'link_retry',side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError): s.retry('performance')
        self.assertIs(s.current.state,state)
        self.assertEqual(s.current.playthrough_id,run_id)
        self.assertEqual(s.center.gpu_used,0)
        self.assertEqual(len(self.db.get_recent_records()),1)

    def test_seed_is_reproducible_and_resume_keeps_future_rolls(self):
        sequences=[]
        for _ in range(2):
            db=Database(':memory:')
            try:
                s=GameSession(db,seed=3,incident_chance=.5)
                for _ in range(2): s.deliver_next_request()
                values=[]
                for rid in (1,2,3):
                    s.select(rid); s.choose_plan('economy'); values.append(s.current.state.incident_at)
                sequences.append(values)
            finally: db.close()
        self.assertEqual(sequences[0],sequences[1])
        self.assertTrue(any(v is None for v in sequences[0]))
        self.assertTrue(any(v is not None for v in sequences[0]))

    def test_normal_close_and_resume_preserve_clock_progress_and_active_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'resume.db'
            db=Database(path); s=GameSession(db,seed=10,incident_chance=0)
            s.choose_plan('economy'); s.advance_time(30)
            run_id=s.current.playthrough_id; s.close()
            db=Database(path)
            try:
                s=GameSession(db)
                self.assertEqual(s.minute,570)
                self.assertEqual(s.current.state.work_done,21)
                self.assertEqual(s.current.state.phase,'running')
                self.assertEqual(s.current.playthrough_id,run_id)
                self.assertEqual(s.center.gpu_used,4)
                self.assertEqual(db.get_recent_results(),[])
            finally: db.close()

    def test_delay_notice_and_operational_phase_are_saved(self):
        s=self.s; s.choose_plan('economy'); s.current.state.trigger_incident(); s.respond('ignore'); s.notify_delay()
        copy=Database(':memory:'); self.addCleanup(copy.close); self.db.conn.backup(copy.conn)
        restored=GameSession(copy)
        self.assertEqual(restored.current.state.phase,'paused')
        self.assertTrue(restored.current.delay_notified)
        self.assertIn('기다리겠습니다',restored.current.last_feedback)
        with self.assertRaises(ValueError): restored.notify_delay()

    def test_large_time_step_matches_six_small_steps(self):
        outcomes=[]
        for steps in ((60,), (10,10,10,10,10,10)):
            db=Database(':memory:')
            try:
                s=GameSession(db,seed=1,incident_chance=1)
                s.choose_plan('economy')
                for minutes in steps: s.advance_time(minutes)
                outcomes.append((s.minute,s.current.state.work_done,s.current.state.phase,
                                 s.current.state.downtime,len(s.runs),s.center.gpu_used))
            finally: db.close()
        self.assertEqual(outcomes[0],outcomes[1])

    def test_legacy_active_request_preserves_existing_incident_and_record(self):
        db=Database(':memory:'); self.addCleanup(db.close)
        rid=db.create_request(1,'이전 요청','initial:1')
        run_id=db.create_playthrough(1,'economy')
        db.change_request_status(rid,'operating',run_id)
        db.add_log(run_id,'v0.5 네트워크 장애')
        before=tuple(db.get_playthrough(run_id))
        s=GameSession(db,incident_chance=0)
        self.assertEqual(s.current.state.phase,'incident')
        self.assertEqual(s.current.state.network_available,2)
        self.assertEqual(s.center.gpu_used,4)
        self.assertEqual(tuple(db.get_playthrough(run_id)),before)
        self.assertIn('v0.5',s.current.messages[0])

    def test_resume_retains_seed_and_next_incident_draw(self):
        self.s.choose_plan('economy')
        copy=Database(':memory:'); self.addCleanup(copy.close)
        self.db.conn.backup(copy.conn)
        restored=GameSession(copy,seed=999,incident_chance=1)
        for session in (self.s,restored):
            session.deliver_next_request(); session.select(2); session.choose_plan('economy')
        self.assertEqual(restored.seed,self.s.seed)
        self.assertEqual(restored.roll_index,self.s.roll_index)
        self.assertEqual(restored.current.state.incident_at,self.s.current.state.incident_at)
