"""기존 공유 자원·중복 차단·원자적 저장 보장을 시간 기반 구조에서 검증합니다."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from database import Database
from session import GameSession
from test_operations import finish_current


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.db=Database(':memory:'); self.addCleanup(self.db.close)
        self.session=GameSession(self.db,incident_chance=0)
        self.session.deliver_next_request(); self.session.deliver_next_request()

    def test_concurrent_allocation_block_release_and_retry(self):
        s=self.session
        s.select(2); s.choose_plan('performance'); japan=s.current
        s.select(3); s.choose_plan('performance'); usa=s.current
        self.assertEqual((s.center.gpu_used,s.center.power_used),(9,10))
        s.select(1)
        with self.assertRaises(ValueError): s.choose_plan('economy')
        self.assertEqual(s.current.state.phase,'ready')
        self.assertEqual(len(self.db.get_recent_records()),2)
        s.select(2); s.advance_time(60)
        self.assertTrue(japan.state.succeeded)
        self.assertEqual(usa.state.phase,'running')
        self.assertEqual((s.center.gpu_used,s.center.power_used),(6,6))
        s.select(1); s.choose_plan('economy')
        self.assertEqual((s.center.gpu_used,s.center.power_used),(10,10))

    def test_switch_preserves_identity_and_independent_network(self):
        s=self.session; s.select(2); s.choose_plan('economy'); state,run_id=s.current.state,s.current.playthrough_id
        s.select(3); s.choose_plan('economy'); s.current.state.trigger_incident(); s.respond('reroute')
        s.select(2)
        self.assertIs(s.current.state,state)
        self.assertEqual(s.current.playthrough_id,run_id)
        self.assertEqual((state.network_needed,state.network_available),(2,8))
        self.assertEqual(state.phase,'running')
        finish_current(s)
        self.assertTrue(state.succeeded)
        self.assertEqual(s.center.gpu_used,4)

    def test_duplicate_start_finish_and_active_restart_are_blocked(self):
        s=self.session; s.choose_plan('economy')
        for operation in (lambda:s.choose_plan('economy'),s.restart):
            with self.assertRaises(ValueError): operation()
        self.assertEqual(s.center.gpu_used,4)
        finish_current(s)
        with self.assertRaises(ValueError): s.respond('compress')
        self.assertEqual(len(self.db.get_recent_records()),1)
        self.assertGreaterEqual(len(self.db.get_logs(s.current.playthrough_id)),3)

    def test_start_failure_does_not_change_other_mission(self):
        s=self.session; s.select(2); s.choose_plan('economy'); other=s.current; s.select(1)
        for method in ('create_playthrough','add_log'):
            with patch.object(self.db,method,side_effect=sqlite3.OperationalError('실패')):
                with self.assertRaises(sqlite3.OperationalError): s.choose_plan('economy')
            self.assertEqual(s.current.state.phase,'ready')
            self.assertIsNone(s.current.playthrough_id)
            self.assertEqual(s.center.gpu_used,2)
            self.assertEqual(other.state.phase,'running')
            self.assertEqual(len(self.db.get_recent_records()),1)
        s.choose_plan('economy')

    def test_completion_failure_restores_shared_resources_and_db(self):
        s=self.session; s.select(2); s.choose_plan('economy'); s.select(1); s.choose_plan('economy')
        state=s.current.state; state.work_done=state.work_total-1
        for method in ('save_result','add_log'):
            with patch.object(self.db,method,side_effect=sqlite3.OperationalError('실패')):
                with self.assertRaises(sqlite3.OperationalError): s.advance_time(10)
            self.assertIs(s.current.state,state)
            self.assertEqual(state.phase,'running')
            self.assertEqual(s.center.gpu_used,6)
            self.assertEqual(self.db.get_recent_results(),[])
            self.assertEqual(len(self.db.get_logs(s.current.playthrough_id)),3)
        s.advance_time(10)
        self.assertEqual(s.center.gpu_used,2)

    def test_save_preserves_active_and_legacy_records(self):
        legacy=self.db.create_playthrough(1,'performance')
        s=self.session
        for rid in (1,2): s.select(rid); s.choose_plan('economy')
        s.save(); s.save()
        self.assertEqual((s.center.gpu_used,s.center.power_used),(6,6))
        self.assertEqual(self.db.get_recent_results(),[])
        self.assertEqual(self.db.get_playthrough(legacy)['status'],'진행중')
        self.assertEqual(len(self.db.get_recent_records()),3)

    def test_save_failure_rolls_back_all_runs(self):
        s=self.session
        for rid in (1,2): s.select(rid); s.choose_plan('economy')
        old=self.db.get_simulation()
        with patch.object(self.db,'save_runtime',side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError): s.save()
        self.assertEqual(self.db.get_simulation(),old)
        self.assertEqual(s.center.gpu_used,6)
        self.assertTrue(all(r.state.phase=='running' for r in s.runs.values() if r.playthrough_id))

    def test_completed_results_cannot_be_overwritten(self):
        s=self.session; s.choose_plan('economy'); finish_current(s)
        before=tuple(self.db.get_playthrough(s.current.playthrough_id))
        with self.assertRaises(ValueError): self.db.save_result(s.current.playthrough_id,'ignore',False,0,'덮어쓰기')
        self.assertEqual(tuple(self.db.get_playthrough(s.current.playthrough_id)),before)

    def test_restart_resets_only_selected_finished_mission(self):
        s=self.session; s.choose_plan('economy'); finish_current(s)
        s.select(2); s.choose_plan('economy'); other=s.current
        s.select(1); s.restart()
        self.assertEqual(s.current.state.phase,'ready')
        self.assertIsNone(s.current.playthrough_id)
        self.assertEqual(other.state.phase,'running')
        self.assertEqual(s.center.gpu_used,2)
        self.assertEqual(len(self.db.get_recent_results()),1)

    def test_three_customers_share_capacity_and_release_in_different_order(self):
        s=self.session
        for rid in (1,2,3): s.select(rid); s.choose_plan('economy')
        self.assertEqual((s.center.gpu_used,s.center.power_used),(10,9))
        for rid,usage in ((2,(8,7)),(1,(4,3)),(3,(0,0))):
            s.select(rid); s.current.state.work_done=s.current.state.work_total-1; s.advance_time(10)
            self.assertEqual((s.center.gpu_used,s.center.power_used),usage)
            for run in s.runs.values():
                self.assertEqual(self.db.get_playthrough(run.playthrough_id)['status'],
                                 '진행중' if run.state.allocated else '성공')

    def test_shutdown_persists_results_and_reopening_preserves_active_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'session.db'; db=Database(path)
            s=GameSession(db,incident_chance=0); s.deliver_next_request()
            s.choose_plan('economy'); finish_current(s)
            s.select(2); s.choose_plan('performance'); s.advance_time(10)
            before=[tuple(r) for r in db.conn.execute('SELECT * FROM playthroughs ORDER BY id')]
            logs=[tuple(r) for r in db.conn.execute('SELECT * FROM event_logs ORDER BY id')]
            s.close(); db=Database(path)
            try:
                fresh=GameSession(db)
                self.assertEqual(fresh.center.gpu_used,3)
                self.assertEqual(fresh.runs[2].state.work_done,10)
                self.assertEqual([tuple(r) for r in db.conn.execute('SELECT * FROM playthroughs ORDER BY id')],before)
                self.assertEqual([tuple(r) for r in db.conn.execute('SELECT * FROM event_logs ORDER BY id')],logs)
            finally: db.close()
