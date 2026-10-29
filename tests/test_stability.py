"""v0.2 자원 공유, 상태 전환, 저장 실패 회귀 테스트."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from database import Database
from game import DataCenter, GameState
from main import SimulatorApp


class ResourceTests(unittest.TestCase):
    def test_default_centers_are_independent(self):
        first, second = GameState(), GameState(center=None)
        first.choose_plan("performance")
        self.assertIsNot(first.center, second.center)
        self.assertEqual(second.center.gpu_used, 0)

    def test_all_mission_outcomes_and_resource_return(self):
        outcomes = {
            ("performance", "reroute"): (True, 90),
            ("performance", "compress"): (False, 20),
            ("performance", "ignore"): (False, 5),
            ("economy", "reroute"): (True, 80),
            ("economy", "compress"): (True, 85),
            ("economy", "ignore"): (False, 0),
        }
        for (plan, response), expected in outcomes.items():
            with self.subTest(plan=plan, response=response):
                state = GameState()
                state.choose_plan(plan)
                state.resolve(response)
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
                state.resolve(response)
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
        self.assertEqual(state.phase, "incident")
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
    """실제 세션과 임시 SQLite로 GUI 버튼 처리 흐름을 검증합니다."""
    def setUp(self):
        from session import GameSession
        self.app = SimulatorApp.__new__(SimulatorApp)
        self.app.root = Mock()
        self.app.db = Database(":memory:")
        self.addCleanup(self.app.db.close)
        self.app.session = GameSession(self.app.db)
        self.app.center = self.app.session.center
        self.app.refresh = Mock()
        self.dialogs = patch("main.messagebox")
        self.messages = self.dialogs.start()
        self.addCleanup(self.dialogs.stop)

    def test_other_mission_start_finish_and_new_mission(self):
        app = self.app
        app.select_mission(2)
        app.choose_plan("economy")
        app.select_mission(1)
        app.choose_plan("economy")
        app.respond("compress")
        app.new_mission()
        self.assertIs(app.state.center, app.center)
        self.assertEqual((app.center.gpu_used, app.center.power_used), (2, 2))
        app.select_mission(2)
        app.respond("compress")
        self.assertEqual((app.center.gpu_used, app.center.power_used), (0, 0))
        self.assertEqual([row["status"] for row in app.db.get_recent_results()], ["성공", "성공"])
        self.assertEqual(len(app.db.get_logs(app.playthrough_id)), 4)

    def test_other_customer_can_finish_during_mission(self):
        app = self.app
        app.choose_plan("economy")
        app.select_mission(2)
        app.choose_plan("economy")
        app.respond("compress")
        self.assertEqual((app.center.gpu_used, app.center.power_used), (4, 4))
        app.select_mission(1)
        app.respond("ignore")
        self.assertEqual((app.center.gpu_used, app.center.power_used), (0, 0))

    def test_new_mission_cannot_discard_active_allocation(self):
        app = self.app
        app.choose_plan("economy")
        state, run_id = app.state, app.playthrough_id
        app.new_mission()
        self.assertIs(app.state, state)
        self.assertEqual(app.playthrough_id, run_id)
        self.assertEqual(app.center.gpu_used, 4)
        self.messages.showwarning.assert_called_once()

    def test_start_save_failure_restores_state_and_allows_retry(self):
        app = self.app
        app.select_mission(2)
        app.choose_plan("economy")
        app.select_mission(1)
        for method in ("create_playthrough", "add_log"):
            with self.subTest(method=method):
                with patch.object(app.db, method, side_effect=sqlite3.OperationalError("저장 실패")):
                    app.choose_plan("economy")
                self.assertEqual(app.state.phase, "ready")
                self.assertIsNone(app.playthrough_id)
                self.assertEqual((app.center.gpu_used, app.center.power_used), (2, 2))
                self.assertEqual(len(app.db.get_recent_records()), 1)
        app.choose_plan("economy")
        self.assertEqual(app.state.phase, "incident")

    def test_result_save_failure_restores_allocation_and_allows_retry(self):
        app = self.app
        app.select_mission(2)
        app.choose_plan("economy")
        app.select_mission(1)
        app.choose_plan("economy")
        for method in ("add_log", "save_result"):
            with self.subTest(method=method):
                with patch.object(app.db, method, side_effect=sqlite3.OperationalError("저장 실패")):
                    app.respond("compress")
                self.assertEqual(app.state.phase, "incident")
                self.assertIsNone(app.state.score)
                self.assertIsNone(app.state.response)
                self.assertEqual((app.center.gpu_used, app.center.power_used), (6, 6))
                self.assertEqual(len(app.db.get_logs(app.playthrough_id)), 2)
                self.assertEqual(app.db.get_recent_results(), [])
        app.respond("compress")
        self.assertEqual(app.state.phase, "finished")
        self.assertEqual((app.center.gpu_used, app.center.power_used), (2, 2))
        self.assertEqual(len(app.db.get_logs(app.playthrough_id)), 4)
        self.assertEqual(len(app.db.get_recent_results()), 1)

    def test_second_log_failure_does_not_leave_partial_records(self):
        app = self.app
        add_log = app.db.add_log

        def fail_second_log():
            calls = 0

            def save(run_id, message):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise sqlite3.OperationalError("두 번째 로그 저장 실패")
                add_log(run_id, message)

            return save

        with patch.object(app.db, "add_log", side_effect=fail_second_log()):
            app.choose_plan("economy")
        self.assertEqual(app.db.conn.execute("SELECT COUNT(*) FROM event_logs").fetchone()[0], 0)
        self.assertEqual(app.state.phase, "ready")
        app.choose_plan("economy")
        app.refresh.reset_mock()
        with patch.object(app.db, "add_log", side_effect=fail_second_log()):
            app.respond("compress")
        self.assertEqual(len(app.db.get_logs(app.playthrough_id)), 2)
        self.assertEqual(app.state.phase, "incident")
        app.refresh.assert_not_called()
        app.respond("compress")
        self.assertEqual(len(app.db.get_logs(app.playthrough_id)), 4)
        self.assertEqual(app.center.gpu_used, 0)


if __name__ == "__main__":
    unittest.main()
