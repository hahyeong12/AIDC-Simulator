"""v0.2 자원 공유, 상태 전환, 저장 실패 회귀 테스트."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from database import Database
from game import DataCenter, GameState
from main import SimulatorApp
from test_game import finish_state
from test_operations import finish_current


class ResourceTests(unittest.TestCase):
    def test_default_centers_are_independent(self):
        first, second = GameState(), GameState(center=None)
        first.choose_plan("performance")
        self.assertIsNot(first.center, second.center)
        self.assertEqual(second.center.gpu_used, 0)

    def test_all_mission_outcomes_and_resource_return(self):
        outcomes = {
            ("performance", "reroute"): (True, 90),
            ("performance", "compress"): (False, 14),
            ("performance", "ignore"): (False, 0),
            ("economy", "reroute"): (True, 80),
            ("economy", "compress"): (True, 85),
            ("economy", "ignore"): (False, 0),
        }
        for (plan, response), expected in outcomes.items():
            with self.subTest(plan=plan, response=response):
                state = GameState()
                state.choose_plan(plan)
                state.trigger_incident(); state.resolve(response); finish_state(state)
                self.assertEqual((state.succeeded, state.score), expected)
                self.assertEqual(state.phase, "finished")
                self.assertEqual((state.center.gpu_used, state.center.power_used), (0, 0))
                with self.assertRaises(ValueError):
                    state.resolve(response)

    def test_insufficient_resources_do_not_partially_allocate(self):
        for center in (DataCenter(gpu_total=3), DataCenter(power_total=3)):
            with self.subTest(center=center):
                state = GameState(center=center)
                with self.assertRaises(ValueError):
                    state.choose_plan("economy")
                self.assertEqual((center.gpu_used, center.power_used), (0, 0))
                self.assertEqual(state.phase, "ready")
                self.assertIsNone(state.plan)

    def test_connected_center_capacity_is_used(self):
        center = DataCenter(gpu_total=6, power_total=6)
        state = GameState(center=center)
        with self.assertRaises(ValueError):
            state.choose_plan("performance")
        state.choose_plan("economy")
        self.assertIs(state.center, center)
        self.assertEqual((center.available_gpu(), center.available_power()), (2, 2))

    def test_external_resources_survive_mission_completion(self):
        for response in ("compress", "ignore"):
            with self.subTest(response=response):
                center = DataCenter()
                center.allocate(4, 4)
                state = GameState(center=center)
                with self.assertRaises(ValueError):
                    state.choose_plan("performance")
                state.choose_plan("economy")
                self.assertEqual((center.gpu_used, center.power_used), (8, 8))
                state.trigger_incident(); state.resolve(response); finish_state(state)
                self.assertEqual((center.gpu_used, center.power_used), (4, 4))
                center.release(4, 4)
                self.assertEqual((center.gpu_used, center.power_used), (0, 0))

    def test_invalid_operations_preserve_resources(self):
        center = DataCenter()
        center.allocate(4, 4)
        for gpu, power in ((0, 1), (1, 0), (-1, 1), (1, -1)):
            with self.subTest(allocate=(gpu, power)), self.assertRaises(ValueError):
                center.allocate(gpu, power)
        for gpu, power in ((-1, 0), (0, -1), (5, 1), (1, 5)):
            with self.subTest(release=(gpu, power)), self.assertRaises(ValueError):
                center.release(gpu, power)
        self.assertFalse(center.allocate(7, 1))
        self.assertFalse(center.allocate(1, 7))
        center.release(0, 0)
        self.assertEqual((center.gpu_used, center.power_used), (4, 4))

    def test_invalid_choices_and_repeated_allocation(self):
        state = GameState()
        with self.assertRaises(ValueError):
            state.choose_plan("unknown")
        state.choose_plan("economy")
        for action in (lambda: state.choose_plan("economy"), lambda: state.resolve("unknown")):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(state.phase, "running")
        self.assertEqual((state.center.gpu_used, state.center.power_used), (4, 4))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def test_missing_result_is_reported(self):
        for run_id in (None, 999):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                self.db.save_result(run_id, "ignore", False, 0, "실패")

    def test_foreign_key_failure_rolls_back(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.create_playthrough(999, "economy")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.add_log(999, "잘못된 기록")
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM playthroughs").fetchone()[0], 0)

    def test_nested_transaction_rolls_back_all_writes(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                run_id = self.db.create_playthrough(1, "economy")
                self.db.add_log(run_id, "기록")
                self.db.save_result(run_id, "compress", True, 85, "성공")
                raise RuntimeError("저장 도중 오류")
        for table in ("playthroughs", "event_logs"):
            self.assertEqual(self.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertGreater(self.db.create_playthrough(1, "economy"), 0)

    def test_file_persistence_and_log_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.db"
            db = Database(path)
            try:
                pending = db.create_playthrough(1, "performance")
                for success in (True, False):
                    run_id = db.create_playthrough(1, "economy")
                    db.add_log(run_id, "첫 번째 기록")
                    db.add_log(run_id, "두 번째 기록")
                    db.save_result(run_id, "compress" if success else "ignore", success,
                                   85 if success else 0, "성공" if success else "실패")
            finally:
                db.close()
            db = Database(path)
            try:
                rows = db.get_recent_results()
                self.assertEqual([row["status"] for row in rows], ["실패", "성공"])
                self.assertNotIn(pending, [row["id"] for row in rows])
                self.assertEqual(len(db.get_recent_results(limit=1)), 1)
                self.assertEqual([row["message"] for row in db.get_logs(run_id)],
                                 ["첫 번째 기록", "두 번째 기록"])
                result = db.conn.execute("SELECT * FROM playthroughs WHERE id=?", (run_id,)).fetchone()
                self.assertEqual(result["result_text"], "실패")
                self.assertIsNotNone(result["finished_at"])
            finally:
                db.close()


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        from session import GameSession
        self.app = SimulatorApp.__new__(SimulatorApp)
        self.app.root = Mock()
        self.app.db = Database(":memory:")
        self.addCleanup(self.app.db.close)
        self.app.session = GameSession(self.app.db, incident_chance=0)
        self.app.session.deliver_next_request(); self.app.session.deliver_next_request()
        self.app.center = self.app.session.center
        self.app.refresh = Mock()
        patcher = patch("main.messagebox")
        self.messages = patcher.start()
        self.addCleanup(patcher.stop)

    def test_other_mission_start_finish_and_new_mission(self):
        a=self.app
        a.select_request(2); a.choose_plan("economy")
        a.select_request(1); a.choose_plan("economy")
        a.state.work_done=a.state.work_total-1
        a.advance_time(10); a.new_mission()
        self.assertEqual(a.center.gpu_used,2)
        self.assertEqual(a.state.phase,"ready")
        a.select_request(2); finish_current(a.session)
        self.assertEqual(a.center.gpu_used,0)
        self.assertEqual(len(a.db.get_recent_results()),2)

    def test_other_customer_can_finish_during_mission(self):
        a=self.app
        a.choose_plan("economy"); a.select_request(2); a.choose_plan("performance")
        a.advance_time(60)
        self.assertEqual(a.center.gpu_used,4)
        a.select_request(1); finish_current(a.session)
        self.assertEqual(a.center.gpu_used,0)

    def test_new_mission_cannot_discard_active_allocation(self):
        a=self.app; a.choose_plan("economy")
        state,run_id=a.state,a.playthrough_id
        a.new_mission()
        self.assertIs(a.state,state)
        self.assertEqual(a.playthrough_id,run_id)
        self.assertEqual(a.center.gpu_used,4)
        self.messages.showerror.assert_called_once()

    def test_start_save_failure_restores_state_and_allows_retry(self):
        a=self.app; a.select_request(2); a.choose_plan("economy"); a.select_request(1)
        for method in ("create_playthrough","add_log"):
            with patch.object(a.db,method,side_effect=sqlite3.OperationalError("실패")):
                a.choose_plan("economy")
            self.assertEqual(a.state.phase,"ready")
            self.assertIsNone(a.playthrough_id)
            self.assertEqual(a.center.gpu_used,2)
            self.assertEqual(len(a.db.get_recent_records()),1)
        a.choose_plan("economy")
        self.assertEqual(a.state.phase,"running")

    def test_result_save_failure_restores_allocation_and_allows_retry(self):
        a=self.app; a.select_request(2); a.choose_plan("economy"); a.select_request(1); a.choose_plan("economy")
        a.state.work_done=a.state.work_total-1
        for method in ("add_log","save_result"):
            with patch.object(a.db,method,side_effect=sqlite3.OperationalError("실패")):
                a.advance_time(10)
            self.assertEqual(a.state.phase,"running")
            self.assertIsNone(a.state.score)
            self.assertEqual(a.center.gpu_used,6)
            self.assertEqual(a.db.get_recent_results(),[])
        a.advance_time(10)
        self.assertEqual(a.state.phase,"finished")
        self.assertEqual(a.center.gpu_used,2)

    def test_second_log_failure_does_not_leave_partial_records(self):
        a=self.app; original=a.db.add_log
        def failing():
            calls=0
            def write(*args):
                nonlocal calls
                calls+=1
                if calls==2: raise sqlite3.OperationalError("두 번째 로그 실패")
                original(*args)
            return write
        with patch.object(a.db,"add_log",side_effect=failing()): a.choose_plan("economy")
        self.assertEqual(len(a.db.get_recent_records()),0)
        self.assertEqual(a.state.phase,"ready")
        a.choose_plan("economy"); a.state.work_done=a.state.work_total-1
        a.refresh.reset_mock()
        with patch.object(a.db,"add_log",side_effect=failing()): a.advance_time(10)
        self.assertEqual(a.state.phase,"running")
        self.assertEqual(len(a.db.get_logs(a.playthrough_id)),3)
        a.refresh.assert_not_called()
        a.advance_time(10)
        self.assertEqual(a.center.gpu_used,0)
