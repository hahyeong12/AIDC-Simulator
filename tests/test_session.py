"""동시 미션, 저장 실패의 원자성, 종료 정책 검증. 실제 DB는 사용하지 않습니다."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import Database
from session import GameSession


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.session = GameSession(self.db)

    def test_concurrent_allocation_block_release_and_retry(self):
        s = self.session
        s.select(2)
        s.choose_plan("performance")  # GPU 3 / 전력 4
        japan = s.current
        s.select(3)
        s.choose_plan("performance")  # GPU 6 / 전력 6
        usa = s.current
        self.assertEqual((s.center.gpu_used, s.center.power_used), (9, 10))
        s.select(1)
        with self.assertRaises(ValueError):
            s.choose_plan("economy")
        self.assertEqual(s.current.state.phase, "ready")
        self.assertIsNone(s.current.playthrough_id)
        self.assertEqual(len(self.db.get_recent_records()), 2)
        s.select(2)
        s.respond("compress")
        self.assertEqual((s.center.gpu_used, s.center.power_used), (6, 6))
        self.assertEqual(usa.state.network_available, 2)
        self.assertEqual(usa.state.phase, "incident")
        self.assertTrue(japan.state.succeeded)
        s.select(1)
        s.choose_plan("economy")  # 10 GPU / 10 전력
        self.assertEqual((s.center.gpu_used, s.center.power_used), (10, 10))

    def test_switch_preserves_identity_and_independent_network(self):
        s = self.session
        s.select(2)
        s.choose_plan("economy")
        state, run_id = s.current.state, s.current.playthrough_id
        s.select(3)
        s.choose_plan("economy")
        s.respond("reroute")
        s.select(2)
        self.assertIs(s.current.state, state)
        self.assertEqual(s.current.playthrough_id, run_id)
        self.assertEqual((state.network_needed, state.network_available), (2, 2))
        s.respond("ignore")
        self.assertTrue(state.succeeded)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))

    def test_duplicate_start_finish_and_active_restart_are_blocked(self):
        s = self.session
        s.choose_plan("economy")
        for action in (lambda: s.choose_plan("economy"), s.restart):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(s.center.gpu_used, 4)
        self.assertEqual(len(self.db.get_recent_records()), 1)
        s.respond("compress")
        with self.assertRaises(ValueError):
            s.respond("compress")
        self.assertEqual(len(self.db.get_logs(s.current.playthrough_id)), 4)

    def test_start_failure_does_not_change_other_mission(self):
        s = self.session
        s.select(2)
        s.choose_plan("economy")
        other = s.current
        s.select(1)
        for method in ("create_playthrough", "add_log"):
            with self.subTest(method=method), patch.object(
                    self.db, method, side_effect=sqlite3.OperationalError("실패")):
                with self.assertRaises(sqlite3.OperationalError):
                    s.choose_plan("economy")
            self.assertEqual(s.current.state.phase, "ready")
            self.assertIsNone(s.current.playthrough_id)
            self.assertEqual((s.center.gpu_used, s.center.power_used), (2, 2))
            self.assertEqual(other.state.phase, "incident")
            self.assertEqual(len(self.db.get_recent_records()), 1)
        s.choose_plan("economy")

    def test_completion_failure_restores_shared_resources_and_db(self):
        s = self.session
        s.select(2)
        s.choose_plan("economy")
        s.select(1)
        s.choose_plan("economy")
        state = s.current.state
        for method in ("save_result", "add_log"):
            with self.subTest(method=method), patch.object(
                    self.db, method, side_effect=sqlite3.OperationalError("실패")):
                with self.assertRaises(sqlite3.OperationalError):
                    s.respond("compress")
            self.assertIs(s.current.state, state)
            self.assertEqual(state.phase, "incident")
            self.assertIsNone(state.response)
            self.assertEqual((s.center.gpu_used, s.center.power_used), (6, 6))
            self.assertEqual(len(self.db.get_logs(s.current.playthrough_id)), 2)
            self.assertEqual(self.db.get_recent_results(), [])
        s.respond("compress")
        self.assertEqual(s.center.gpu_used, 2)

    def test_close_abandons_only_current_active_runs(self):
        legacy = self.db.create_playthrough(1, "performance")
        s = self.session
        for mission_id in (1, 2):
            s.select(mission_id)
            s.choose_plan("economy")
        s.abandon_active()
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))
        self.assertEqual([r["score"] for r in self.db.get_recent_results()], [0, 0])
        self.assertEqual(self.db.conn.execute(
            "SELECT status FROM playthroughs WHERE id=?", (legacy,)).fetchone()[0], "진행중")
        s.abandon_active()  # 반복 종료는 자원을 이중 반환하지 않습니다.
        self.assertEqual(len(self.db.get_recent_results()), 2)

    def test_close_failure_rolls_back_all_runs(self):
        s = self.session
        for mission_id in (1, 2):
            s.select(mission_id)
            s.choose_plan("economy")
        original = self.db.save_result
        calls = 0

        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise sqlite3.OperationalError("두 번째 저장 실패")
            return original(*args)

        with patch.object(self.db, "save_result", side_effect=fail_second):
            with self.assertRaises(sqlite3.OperationalError):
                s.abandon_active()
        self.assertEqual((s.center.gpu_used, s.center.power_used), (6, 6))
        self.assertEqual(self.db.get_recent_results(), [])
        for run in s.runs.values():
            if run.playthrough_id:
                self.assertEqual(run.state.phase, "incident")
                self.assertEqual(len(self.db.get_logs(run.playthrough_id)), 2)

    def test_completed_results_cannot_be_overwritten(self):
        s = self.session
        s.choose_plan("economy")
        s.respond("compress")
        with self.assertRaises(ValueError):
            self.db.save_result(s.current.playthrough_id, "ignore", False, 0, "덮어쓰기")
        self.assertEqual(self.db.get_recent_results()[0]["score"], 85)

    def test_restart_resets_only_selected_finished_mission(self):
        s = self.session
        s.choose_plan("economy")
        s.respond("compress")
        s.select(2)
        s.choose_plan("economy")
        other = s.current
        s.select(1)
        s.restart()
        self.assertEqual(s.current.state.phase, "ready")
        self.assertEqual(s.current.messages, [])
        self.assertEqual(other.state.phase, "incident")
        self.assertEqual((s.center.gpu_used, s.center.power_used), (2, 2))
        self.assertEqual(len(self.db.get_recent_results()), 1)

    def test_three_customers_share_capacity_and_release_in_different_order(self):
        s = self.session
        for mid in (1, 2, 3):
            s.select(mid)
            s.choose_plan("economy")
        self.assertEqual((s.center.gpu_used, s.center.power_used), (10, 9))
        for mid, usage in ((2, (8, 7)), (1, (4, 3)), (3, (0, 0))):
            s.select(mid)
            s.respond("reroute")
            self.assertEqual((s.center.gpu_used, s.center.power_used), usage)
            for run in s.runs.values():
                record = self.db.conn.execute(
                    "SELECT status FROM playthroughs WHERE id=?", (run.playthrough_id,)).fetchone()
                self.assertEqual(record["status"], "진행중" if run.state.phase == "incident" else "성공")

    def test_shutdown_persists_results_and_reopening_starts_with_free_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.db"
            db = Database(path)
            try:
                s = GameSession(db)
                s.choose_plan("economy")
                s.respond("compress")
                s.select(2)
                s.choose_plan("performance")
                s.abandon_active()
                before = [tuple(r) for r in db.conn.execute("SELECT * FROM playthroughs ORDER BY id")]
                logs = [tuple(r) for r in db.conn.execute("SELECT * FROM event_logs ORDER BY id")]
            finally:
                db.close()
            db = Database(path)
            try:
                fresh = GameSession(db)
                self.assertEqual((fresh.center.gpu_used, fresh.center.power_used), (0, 0))
                self.assertTrue(all(run.state.phase == "ready" for run in fresh.runs.values()))
                self.assertEqual([tuple(r) for r in db.conn.execute("SELECT * FROM playthroughs ORDER BY id")], before)
                self.assertEqual([tuple(r) for r in db.conn.execute("SELECT * FROM event_logs ORDER BY id")], logs)
                self.assertEqual([r["response"] for r in db.get_recent_results()], ["abandon", "compress"])
            finally:
                db.close()
