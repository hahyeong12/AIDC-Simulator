"""요청 접수·결정·저장·기존 운영 연결 검증. 실제 DB를 사용하지 않습니다."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import Database
from session import GameSession
from test_operations import finish_current


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, incident_chance=0)

    def test_first_request_only_and_deterministic_arrival(self):
        self.assertEqual(len(self.s.runs), 1)
        self.assertEqual(self.s.current.request["status"], "new")
        self.assertEqual(self.s.current.request["is_read"], 0)
        self.assertEqual(self.s.current.mission["country"], "싱가포르")
        self.assertEqual([self.s.deliver_next_request(), self.s.deliver_next_request()], [2, 3])
        self.assertIsNone(self.s.deliver_next_request())
        self.assertFalse(self.s.has_next_request)
        self.assertEqual([r["mission_id"] for r in self.db.get_requests()], [1, 2, 3])

    def test_message_and_request_list(self):
        request = self.db.get_requests()[0]
        for part in ("안녕하세요", "발신: Merlion AI", "요청 GPU: 7개", "전력: 7단위", "감사합니다"):
            self.assertIn(part, request["message"])
        self.assertIsNone(request["playthrough_id"])
        self.assertTrue(request["received_at"])

    def test_select_marks_read_and_review_only_selected_request(self):
        self.s.deliver_next_request()
        self.s.select(1)
        self.assertEqual((self.s.current.request["status"], self.s.current.request["is_read"]), ("review", 1))
        self.assertEqual(self.db.get_request(2)["is_read"], 0)

    def test_wait_then_accept_and_complete(self):
        s = self.s
        s.wait_request()
        self.assertEqual(s.current.request["status"], "waiting")
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))
        s.select(1)
        self.assertEqual(s.current.request["status"], "waiting")
        s.choose_plan("economy")
        self.assertEqual(s.current.request["status"], "operating")
        self.assertEqual(s.current.request["playthrough_id"], s.current.playthrough_id)
        s.current.state.trigger_incident(); s.respond("compress"); finish_current(s)
        self.assertEqual(s.current.request["status"], "completed")
        self.assertTrue(s.current.state.succeeded)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))

    def test_rejection_requires_reason_and_is_not_mission_failure(self):
        for reason in ("", "   ", "기타 사유"):
            with self.assertRaises(ValueError):
                self.s.reject_request(reason)
        self.s.reject_request("  현재 GPU 자원 부족  ")
        request = self.db.get_request(1)
        self.assertEqual(request["status"], "rejected")
        self.assertEqual(request["rejection_reason"], "현재 GPU 자원 부족")
        self.assertIsNone(request["playthrough_id"])
        self.assertEqual(self.db.get_recent_records(), [])
        self.assertEqual(self.s.center.gpu_used, 0)
        with self.assertRaises(ValueError):
            self.s.choose_plan("economy")

    def test_wait_then_reject_custom_reason(self):
        self.s.wait_request()
        self.s.reject_request("기타 사유: 작업 범위 확인 필요")
        self.assertEqual(self.s.current.request["status"], "rejected")
        self.assertIn("범위 확인", self.db.get_request(1)["rejection_reason"])

    def test_duplicate_acceptance_does_not_double_allocate(self):
        self.s.choose_plan("economy")
        run_id = self.s.current.playthrough_id
        with self.assertRaises(ValueError):
            self.s.choose_plan("performance")
        self.assertEqual(self.s.current.playthrough_id, run_id)
        self.assertEqual(self.s.center.gpu_used, 4)
        self.assertEqual(len(self.db.get_recent_records()), 1)
        for operation in (self.s.wait_request, lambda: self.s.reject_request("자원 부족")):
            with self.assertRaises(ValueError):
                operation()

    def test_resource_shortage_keeps_waiting_and_reports_both_shortages(self):
        self.s.wait_request()
        self.s.center.allocate(8, 9)
        with self.assertRaisesRegex(ValueError, "GPU 5개 / 전력 6단위"):
            self.s.choose_plan("performance")
        self.assertEqual(self.s.current.request["status"], "waiting")
        self.assertEqual(self.s.current.state.phase, "ready")
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (8, 9))
        self.assertEqual(self.db.get_recent_records(), [])

    def test_acceptance_save_failure_restores_request_resources_and_logs(self):
        self.s.wait_request()
        for method in ("create_playthrough", "change_request_status", "add_log", "get_request"):
            with self.subTest(method=method), patch.object(self.db, method, side_effect=sqlite3.OperationalError("실패")):
                with self.assertRaises(sqlite3.OperationalError):
                    self.s.choose_plan("economy")
            self.assertEqual(self.s.current.request["status"], "waiting")
            self.assertEqual(self.db.get_request(1)["status"], "waiting")
            self.assertEqual(self.s.current.state.phase, "ready")
            self.assertIsNone(self.s.current.playthrough_id)
            self.assertEqual(self.s.center.gpu_used, 0)
            self.assertEqual(self.db.get_recent_records(), [])
        self.s.choose_plan("economy")

    def test_completion_request_save_failure_restores_operating_job(self):
        self.s.choose_plan("economy")
        self.s.current.state.work_done=self.s.current.state.work_total-1
        with patch.object(self.db, "change_request_status", side_effect=sqlite3.OperationalError("실패")):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.advance_time(10)
        self.assertEqual(self.s.current.request["status"], "operating")
        self.assertEqual(self.db.get_request(1)["status"], "operating")
        self.assertEqual(self.s.current.state.phase, "running")
        self.assertEqual(self.s.center.gpu_used, 4)
        self.assertEqual(self.db.get_recent_results(), [])
        self.assertEqual(len(self.db.get_logs(self.s.current.playthrough_id)), 3)  # 시작·배정·고객 확인

    def test_decision_read_and_arrival_failures_do_not_update_memory(self):
        for action in (self.s.wait_request, lambda: self.s.reject_request("자원 부족")):
            with patch.object(self.db, "change_request_status", side_effect=sqlite3.OperationalError("실패")):
                with self.assertRaises(sqlite3.OperationalError):
                    action()
            self.assertEqual(self.s.current.request["status"], "new")
        with patch.object(self.db, "mark_request_read", side_effect=sqlite3.OperationalError("실패")):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.select(1)
        self.assertEqual(self.s.current.request["is_read"], 0)
        with patch.object(self.db, "get_request", side_effect=sqlite3.OperationalError("실패")):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.deliver_next_request()
        self.assertEqual(len(self.db.get_requests()), 1)
        self.assertEqual(len(self.s.runs), 1)

    def test_no_new_request_for_customer_with_unresolved_request(self):
        with self.assertRaises(ValueError):
            self.s.restart()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.create_request(1, "중복 요청")

    def test_explicit_repeat_gets_new_request_id_and_preserves_decision(self):
        self.s.reject_request("자원 부족")
        self.s.restart()
        self.assertNotEqual(self.s.current.request["id"], 1)
        self.assertEqual(self.s.current.mission["id"], 1)
        self.assertEqual(self.db.get_request(1)["status"], "rejected")
        self.assertEqual(self.s.current.request["status"], "new")

    def test_db_rejects_invalid_status_reason_and_mismatched_run(self):
        for status in ("new", "review", "typo"):
            with self.assertRaises(ValueError):
                self.db.change_request_status(1, status)
        with self.assertRaises(ValueError):
            self.db.change_request_status(1, "rejected", reason=" ")
        run_id = self.db.create_playthrough(2, "economy")
        with self.assertRaises(ValueError):
            self.db.change_request_status(1, "operating", run_id)
        self.assertEqual(self.db.get_request(1)["status"], "new")

    def test_save_preserves_waiting_and_operating_requests(self):
        self.s.wait_request()
        self.s.deliver_next_request()
        self.s.select(2)
        self.s.choose_plan("economy")
        self.s.save()
        self.assertEqual(self.db.get_request(1)["status"], "waiting")
        self.assertEqual(self.db.get_request(2)["status"], "operating")
        self.assertEqual(self.db.get_recent_results(), [])

    def test_requests_persist_no_auto_arrival_and_crash_job_restores(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "requests.db"
            db = Database(path)
            try:
                s = GameSession(db, incident_chance=0)
                s.wait_request()
                s.deliver_next_request()
                s.select(2)
                s.choose_plan("performance")
                run_id = s.current.playthrough_id
            finally:
                db.close()  # 강제 종료를 모의하여 세션 종료 처리를 실행하지 않습니다.
            for _ in range(2):
                db = Database(path)
                try:
                    s = GameSession(db, incident_chance=0)
                    self.assertEqual(len(s.runs), 2)
                    self.assertEqual(s.runs[1].request["status"], "waiting")
                    self.assertEqual(s.runs[2].playthrough_id, run_id)
                    self.assertEqual(s.runs[2].state.phase, "running")
                    self.assertEqual((s.center.gpu_used, s.center.power_used), (3, 4))
                    self.assertEqual(len(db.get_recent_records()), 1)
                finally:
                    db.close()

    def test_rejected_waiting_and_completed_requests_restore_without_new_rows(self):
        self.s.reject_request("전력 공급 여유 부족")
        self.s.deliver_next_request()
        self.s.select(2)
        self.s.wait_request()
        self.s.deliver_next_request()
        self.s.select(3)
        self.s.choose_plan("economy")
        self.s.current.state.trigger_incident(); self.s.respond("reroute"); finish_current(self.s)
        restored_db = Database(":memory:")
        self.addCleanup(restored_db.close)
        self.db.conn.backup(restored_db.conn)
        restored = GameSession(restored_db, incident_chance=0)
        self.assertEqual([restored.runs[rid].request["status"] for rid in (1,2,3)], ["rejected", "waiting", "completed"])
        self.assertEqual(restored.runs[1].request["rejection_reason"], "전력 공급 여유 부족")
        self.assertEqual(restored.runs[3].state.score, 60)  # 40분 지연 감점 20점도 그대로 복원
        self.assertTrue(restored.runs[3].state.succeeded)
        self.assertGreaterEqual(len(restored.runs[3].messages), 4)
        self.assertEqual(restored.center.gpu_used, 0)
        self.assertEqual([dict(r) for r in restored_db.get_requests()], [dict(r) for r in self.db.get_requests()])
        self.assertFalse(restored.has_next_request)

    def test_three_active_jobs_restore_shared_capacity_and_complete_independently(self):
        self.s.deliver_next_request()
        self.s.deliver_next_request()
        for rid in (1, 2, 3):
            self.s.select(rid)
            self.s.choose_plan("economy")
        restored_db = Database(":memory:")
        self.addCleanup(restored_db.close)
        self.db.conn.backup(restored_db.conn)
        restored = GameSession(restored_db, incident_chance=0)
        self.assertEqual((restored.center.gpu_used, restored.center.power_used), (10, 9))
        self.assertTrue(all(run.state.center is restored.center for run in restored.runs.values()))
        restored.select(3)
        restored.current.state.work_done=restored.current.state.work_total-1
        restored.advance_time(10)
        self.assertEqual((restored.center.gpu_used, restored.center.power_used), (6, 6))
        self.assertEqual(restored.runs[1].state.phase, "running")
        self.assertEqual(restored.runs[2].state.phase, "running")
        self.assertEqual(len(restored_db.get_recent_records()), 3)
