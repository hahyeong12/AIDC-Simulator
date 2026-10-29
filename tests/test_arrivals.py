"""시간 기반 반복 접수, 고객 다양성, 대기 상한과 저장·복구를 검증합니다."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import Database
from game import ACTIVE_PHASES
from session import GameSession, MAX_PENDING_REQUESTS, CUSTOMER_COOLDOWN


class ArrivalTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=9, incident_chance=0)

    def assert_saved_usage(self, session, db):
        states = [db.get_runtime(rid)['state'] for rid in session.runs]
        gpu = sum(s['gpu_used'] for s in states if s['phase'] in ACTIVE_PHASES)
        power = sum(s['power_used'] for s in states if s['phase'] in ACTIVE_PHASES)
        self.assertEqual((gpu,power), (session.center.gpu_used,session.center.power_used))
        self.assertEqual(db.get_simulation()['minute'], session.minute)

    def test_japan_allocation_and_progress_for_both_modes(self):
        for mode,usage,percent in (('performance',(3,4),100/6), ('economy',(2,2),100*7/60)):
            db=Database(':memory:')
            try:
                s=GameSession(db,seed=9,incident_chance=0)
                s.deliver_next_request(); s.select(2); s.choose_plan(mode)
                self.assertEqual(s.current.state.progress,0)
                self.assertEqual((s.center.gpu_used,s.center.power_used),usage)
                s.advance_time(10)
                self.assertAlmostEqual(s.current.state.progress,percent)
                self.assertEqual(s.minute,550)
                self.assert_saved_usage(s,db)
            finally:
                db.close()

    def test_two_simultaneous_arrivals_preserve_running_job_and_selection(self):
        s=self.s; s.choose_plan('economy')
        state,run_id=s.current.state,s.current.playthrough_id
        s.advance_time(30)
        self.assertEqual(len(s.runs),3)
        self.assertEqual(s.selected_id,1)
        self.assertIs(s.current.state,state)
        self.assertEqual(s.current.playthrough_id,run_id)
        self.assertEqual((state.phase,state.work_done),('running',21))
        self.assertEqual(s.center.gpu_used,4)
        for rid in (2,3):
            self.assertEqual(s.runs[rid].request['status'],'new')
            self.assertEqual(s.runs[rid].state.gpu_used,0)
            events=self.db.get_request_events(rid)
            self.assertEqual(events[0]['game_minute'],570)
        self.assertEqual({r.mission['country'] for r in s.runs.values()},{'싱가포르','일본','미국'})
        self.assert_saved_usage(s,self.db)

    def test_arrival_order_varies_with_seed_and_is_reproducible(self):
        orders=[]
        for seed in (0,2,0):
            db=Database(':memory:')
            try:
                s=GameSession(db,seed=seed,incident_chance=0)
                s.choose_plan('economy'); s.advance_time(30)
                orders.append([r.mission['country'] for rid,r in s.runs.items() if rid!=1])
            finally: db.close()
        self.assertEqual(orders[0],orders[2])
        self.assertNotEqual(orders[0],orders[1])

    def test_unhandled_queue_is_bounded_and_blocked_slots_do_not_accumulate(self):
        s=self.s
        # 미처리 종료 전에는 보류 슬롯을 누적하지 않습니다. 만료 후 재접수는 별도 검증합니다.
        for _ in range(3): s.advance_time(60)
        self.assertEqual(s.pending_request_count,MAX_PENDING_REQUESTS)
        self.assertEqual(len(s.runs),MAX_PENDING_REQUESTS)
        self.assertGreater(s.next_arrival_minute,s.minute)
        count=len(s.runs)
        s.select(1); s.reject_request('현재 처리 불가')
        s.advance_time(10)
        self.assertEqual(len(s.runs),count)  # 과거에 보류했던 요청을 한꺼번에 밀어 넣지 않습니다.
        s.advance_time(30)
        self.assertLessEqual(s.pending_request_count,MAX_PENDING_REQUESTS)
        self.assertLessEqual(len(s.runs),count+1)

    def test_repeat_arrivals_continue_after_all_initial_customers_are_processed(self):
        s=self.s
        s.deliver_next_request(); s.deliver_next_request()
        for rid in (1,2,3):
            s.select(rid); s.reject_request('운영 조건 미충족')
        s.advance_time(60)
        self.assertGreater(len(s.runs),3)
        self.assertTrue(any(r.request['source_key'].startswith('auto:') for rid,r in s.runs.items() if rid>3))
        self.assertTrue(all(s.runs[rid].request['status']=='rejected' for rid in (1,2,3)))

    def test_cooldown_and_least_received_priority_prevent_customer_spam(self):
        s=self.s
        for _ in range(12):
            for rid,run in list(s.runs.items()):
                if run.request['status']=='new': s.select(rid); s.reject_request('수용 불가')
            s.advance_time(30)
        times={mid:[] for mid in s.missions}
        for rid,run in s.runs.items():
            times[run.mission['id']].extend(e['game_minute'] for e in self.db.get_request_events(rid) if e['kind']=='arrival')
        for moments in times.values():
            self.assertGreaterEqual(len(moments),2)
            self.assertTrue(all(b-a>=CUSTOMER_COOLDOWN for a,b in zip(moments,moments[1:])))
        counts=[len(v) for v in times.values()]
        self.assertLessEqual(max(counts)-min(counts),2)

    def test_shared_jobs_progress_before_and_after_automatic_arrivals(self):
        s=self.s; s.choose_plan('economy')
        first=s.current
        s.advance_time(30)
        japan=next(rid for rid,r in s.runs.items() if r.mission['country']=='일본')
        s.select(japan); s.choose_plan('performance')
        s.advance_time(30)
        self.assertEqual(first.state.work_done,42)
        self.assertEqual(s.current.state.work_done,30)
        self.assertEqual((s.center.gpu_used,s.center.power_used),(7,8))
        self.assert_saved_usage(s,self.db)

    def test_insufficient_resources_reject_automatic_request_without_allocating(self):
        s=self.s; s.choose_plan('economy')
        s.deliver_next_request(); s.select(2); s.choose_plan('performance')
        s.advance_time(30)
        usa=next(rid for rid,r in s.runs.items() if r.mission['country']=='미국')
        s.select(usa)
        with self.assertRaisesRegex(ValueError,'GPU 3개 / 전력 4단위'):
            s.choose_plan('performance')
        self.assertEqual(s.current.request['status'],'review')
        self.assertIsNone(s.current.playthrough_id)
        self.assertEqual((s.center.gpu_used,s.center.power_used),(7,8))
        self.assert_saved_usage(s,self.db)

    def test_other_job_runs_during_incident_and_arrival_events(self):
        s=self.s; s.choose_plan('economy'); first=s.current
        first.state.incident_at=7
        s.advance_time(30)
        japan=next(rid for rid,r in s.runs.items() if r.mission['country']=='일본')
        s.select(japan); s.choose_plan('performance')
        s.advance_time(10)
        self.assertEqual(first.state.phase,'incident')
        self.assertEqual(first.state.work_done,7)
        self.assertEqual(s.current.state.work_done,10)
        self.assert_saved_usage(s,self.db)

    def test_followup_failure_does_not_receive_duplicate_customer_request(self):
        s=self.s; s.choose_plan('economy'); s.current.state.trigger_incident()
        s.advance_time(60)
        self.assertFalse(s.current.state.succeeded)
        self.assertFalse(s.current.followup_closed)
        s.advance_time(60)
        self.assertEqual(sum(r.mission['id']==1 for r in s.runs.values()),1)

    def test_failed_save_restores_schedule_and_retry_delivers_exactly_once(self):
        s=self.s; s.choose_plan('economy')
        before=self.db.get_simulation()
        events=len(self.db.get_request_events(1))
        with patch.object(self.db,'save_runtime',side_effect=sqlite3.OperationalError('저장 실패')):
            with self.assertRaises(sqlite3.OperationalError): s.advance_time(30)
        self.assertEqual(s.minute,540)
        self.assertEqual((s.next_arrival_minute,s.arrival_index),(570,0))
        self.assertEqual(self.db.get_simulation(),before)
        self.assertEqual(len(s.runs),1)
        self.assertEqual(len(self.db.get_requests()),1)
        self.assertEqual(len(self.db.get_request_events(1)),events)
        self.assertEqual(s.current.state.work_done,0)
        s.advance_time(30)
        self.assertEqual(len(s.runs),3)
        keys=[r['source_key'] for r in self.db.get_requests()]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertEqual(s.arrival_index,1)

    def test_resume_preserves_schedule_and_does_not_replay_delivered_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'arrivals.db'
            db=Database(path); s=GameSession(db,seed=9,incident_chance=0)
            s.choose_plan('economy'); s.advance_time(30)
            keys=[r['source_key'] for r in db.get_requests()]
            s.close(); db=Database(path)
            try:
                s=GameSession(db,seed=0)
                self.assertEqual((s.minute,s.next_arrival_minute,s.arrival_index),(570,600,1))
                self.assertEqual(s.current.state.work_done,21)
                s.advance_time(30)
                self.assertEqual([r['source_key'] for r in db.get_requests()],keys)
                self.assertEqual(s.current.state.work_done,42)
                self.assert_saved_usage(s,db)
            finally: db.close()

    def test_old_save_adds_future_schedule_without_resetting_clock_or_history(self):
        s=self.s; s.choose_plan('economy'); s.advance_time(10)
        saved=self.db.get_simulation(); saved.pop('arrivals')
        self.db.save_simulation(saved)
        before=[dict(row) for row in self.db.get_recent_records()]
        restored=GameSession(self.db)
        self.assertEqual((restored.minute,restored.next_arrival_minute),(550,580))
        self.assertEqual(restored.current.state.work_done,7)
        self.assertEqual([dict(row) for row in self.db.get_recent_records()],before)
        self.assertEqual(len(restored.runs),1)
        restored.advance_time(30)
        self.assertGreater(len(restored.runs),1)

    def test_large_and_small_time_buttons_share_arrival_schedule(self):
        outcomes=[]
        for steps in ((60,), (10,10,10,10,10,10)):
            db=Database(':memory:')
            try:
                s=GameSession(db,seed=9,incident_chance=0); s.choose_plan('economy')
                for step in steps: s.advance_time(step)
                outcomes.append((s.minute,s.current.state.work_done,s.arrival_index,
                                 [(r.request['source_key'],r.mission['id']) for r in s.runs.values()]))
            finally: db.close()
        self.assertEqual(outcomes[0],outcomes[1])
