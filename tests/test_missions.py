"""고객별 미션 전환과 기존 데이터 보존 테스트."""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from database import Database
from main import SimulatorApp


class MissionDatabaseTests(unittest.TestCase):
    def test_three_customers_and_missions(self):
        db = Database(":memory:")
        self.addCleanup(db.close)
        missions = db.get_missions()
        self.assertEqual(
            [(m["company_name"], m["country"], m["title"]) for m in missions],
            [("Merlion AI", "싱가포르", "생성형 AI 모델 학습 요청"),
             ("Sakura Robotics", "일본", "로봇 AI 모델 추론 작업"),
             ("Northstar AI", "미국", "대규모 데이터 분석 작업")],
        )
        self.assertTrue(all(m["description"] for m in missions))
        self.assertEqual(db.get_mission()["id"], missions[0]["id"])

    def test_reopening_does_not_duplicate_seed_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missions.db"
            original = None
            for _ in range(3):
                db = Database(path)
                try:
                    rows = [tuple(row) for row in db.get_missions()]
                    if original is None:
                        original = rows
                    self.assertEqual(rows, original)
                    self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0], 3)
                    self.assertEqual(len(rows), 3)
                finally:
                    db.close()

    def test_v02_upgrade_preserves_history_and_existing_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.db"
            # v0.2와 동일한 테이블에 기존 고객, 완료/진행 기록과 로그를 구성합니다.
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript("""
                    CREATE TABLE clients (id INTEGER PRIMARY KEY, company_name TEXT NOT NULL, country TEXT NOT NULL);
                    CREATE TABLE missions (id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
                        title TEXT NOT NULL, description TEXT NOT NULL);
                    CREATE TABLE playthroughs (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        mission_id INTEGER NOT NULL REFERENCES missions(id), plan TEXT NOT NULL, response TEXT,
                        status TEXT NOT NULL CHECK(status IN ('진행중', '성공', '실패')), score INTEGER,
                        result_text TEXT, started_at TEXT NOT NULL, finished_at TEXT);
                    CREATE TABLE event_logs (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        playthrough_id INTEGER NOT NULL REFERENCES playthroughs(id), message TEXT NOT NULL,
                        created_at TEXT NOT NULL);
                    INSERT INTO clients VALUES (1, 'Merlion AI', '싱가포르');
                    INSERT INTO missions VALUES (1, 1, '싱가포르 AI 모델 학습 요청', '기존 설명');
                    INSERT INTO clients VALUES (2, '기존 추가 고객', '한국');
                    INSERT INTO missions VALUES (2, 2, '기존 추가 미션', '보존할 설명');
                    INSERT INTO playthroughs VALUES (7, 1, 'economy', 'compress', '성공', 85,
                        '기존 결과', '2026-10-27', '2026-10-27');
                    INSERT INTO playthroughs VALUES (8, 1, 'performance', NULL, '진행중', NULL,
                        NULL, '2026-10-27', NULL);
                    INSERT INTO event_logs VALUES (9, 7, '기존 로그', '2026-10-27');
                    INSERT INTO event_logs VALUES (10, 8, '진행 중 로그', '2026-10-27');
                """)
                before = {
                    table: conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                    for table in ("playthroughs", "event_logs")
                }
                schema = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            for _ in range(2):
                db = Database(path)
                try:
                    for table, rows in before.items():
                        self.assertEqual([tuple(r) for r in db.conn.execute(f"SELECT * FROM {table} ORDER BY id")], rows)
                    self.assertEqual(db.get_mission(1)["title"], "생성형 AI 모델 학습 요청")
                    self.assertEqual(db.get_mission(2)["company_name"], "기존 추가 고객")
                    self.assertEqual(len(db.get_missions()), 4)
                    self.assertEqual([tuple(r) for r in db.conn.execute(
                        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")], schema)
                    self.assertEqual(db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                finally:
                    db.close()


class MissionSelectionTests(unittest.TestCase):
    def setUp(self):
        from session import GameSession
        self.app = SimulatorApp.__new__(SimulatorApp)
        app = self.app
        app.root = Mock()
        app.db = Database(":memory:")
        self.addCleanup(app.db.close)
        app.session = GameSession(app.db)
        app.center = app.session.center
        app.refresh = Mock()
        dialogs = patch("main.messagebox")
        self.dialogs = dialogs.start()
        self.addCleanup(dialogs.stop)

    def test_default_mission_on_startup(self):
        self.assertEqual((self.app.mission["company_name"], self.app.mission["country"]),
                         ("Merlion AI", "싱가포르"))
        self.assertEqual(self.app.state.country, "싱가포르")

    def test_selection_updates_current_customer_and_starts_ready(self):
        app = self.app
        for mission in app.db.get_missions()[1:]:
            app.select_mission(mission["id"])
            self.assertEqual(app.mission["id"], mission["id"])
            self.assertEqual(app.state.country, mission["country"])
            self.assertEqual(app.state.phase, "ready")
            self.assertIsNone(app.playthrough_id)
            app.refresh.assert_called()

    def test_in_progress_switch_preserves_original_mission(self):
        app = self.app
        app.choose_plan("economy")
        state, run_id = app.state, app.playthrough_id
        app.select_mission(2)
        self.assertEqual(app.state.phase, "ready")
        app.select_mission(3)
        app.select_mission(1)
        self.assertIs(app.state, state)
        self.assertEqual(app.playthrough_id, run_id)
        self.assertEqual((app.center.gpu_used, app.center.power_used), (4, 4))
        app.respond("compress")
        self.assertEqual(app.db.get_recent_results()[0]["mission_id"], 1)

    def test_all_customers_can_run_in_sequence_with_correct_results(self):
        app = self.app
        outcomes = [("economy", "compress", "성공", 85),
                    ("performance", "compress", "성공", 95),
                    ("performance", "reroute", "성공", 90)]
        app.center.allocate(1, 1)
        for mission, (plan, response, status, score) in zip(app.db.get_missions(), outcomes):
            app.select_mission(mission["id"])
            app.choose_plan(plan)
            app.respond(response)
            self.assertEqual(app.state.phase, "finished")
            self.assertEqual((app.center.gpu_used, app.center.power_used), (1, 1))
            result = app.db.get_recent_results()[0]
            for key in ("company_name", "country", "title"):
                self.assertEqual(result[key], mission[key])
            self.assertEqual((result["mission_id"], result["status"], result["score"]),
                             (mission["id"], status, score))
            logs = app.db.get_logs(app.playthrough_id)
            self.assertIn(mission["company_name"], logs[0]["message"])
            self.assertIn("국제 네트워크", logs[1]["message"])
            self.assertEqual(len(logs), 4)
        self.assertEqual(len(app.db.get_recent_results()), 3)

    def test_invalid_selection_keeps_current_mission(self):
        app = self.app
        app.select_mission(999)
        self.assertEqual(app.mission["id"], 1)
        self.assertEqual(app.state.phase, "ready")
        self.dialogs.showerror.assert_called_once()


if __name__ == "__main__":
    unittest.main()
