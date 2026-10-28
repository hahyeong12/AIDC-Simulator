"""SQLite 데이터 저장: 고객, 미션, 수행 결과, 사건 로그."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("aidc_game.db")


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path = DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    @contextmanager
    def transaction(self):
        """여러 저장 작업도 실패 시 함께 취소합니다. 중첩 호출도 지원합니다."""
        self.conn.execute("SAVEPOINT game_save")
        try:
            yield
            self.conn.execute("RELEASE SAVEPOINT game_save")
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT game_save")
            self.conn.execute("RELEASE SAVEPOINT game_save")
            raise

    def init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY,
                company_name TEXT NOT NULL,
                country TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS missions (
                id INTEGER PRIMARY KEY,
                client_id INTEGER NOT NULL REFERENCES clients(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS playthroughs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id INTEGER NOT NULL REFERENCES missions(id),
                plan TEXT NOT NULL,
                response TEXT,
                status TEXT NOT NULL CHECK(status IN ('진행중', '성공', '실패')),
                score INTEGER,
                result_text TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playthrough_id INTEGER NOT NULL REFERENCES playthroughs(id),
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        self.conn.execute("INSERT OR IGNORE INTO clients VALUES (?, ?, ?)",
                          (1, "Merlion AI", "싱가포르"))
        self.conn.execute(
            "INSERT OR IGNORE INTO missions VALUES (?, ?, ?, ?)",
            (1, 1, "생성형 AI 모델 학습 요청",
             "생성형 AI 모델 학습을 위해 GPU 서버와 안정적인 통신 회선이 필요합니다."),
        )
        # 기존 미션 ID를 유지하여 수행 기록과 로그의 연결을 보존합니다.
        self.conn.execute(
            "UPDATE missions SET title=? WHERE id=1 AND client_id=1 AND title=?",
            ("생성형 AI 모델 학습 요청", "싱가포르 AI 모델 학습 요청"),
        )
        for company, country, title, description in (
            ("Sakura Robotics", "일본", "로봇 AI 모델 추론 작업",
             "로봇이 주변 환경을 인식하고 판단하는 AI 모델을 실행하기 위해 GPU 서버 자원이 필요합니다."),
            ("Northstar AI", "미국", "대규모 데이터 분석 작업",
             "대량의 데이터를 분석하고 AI 기반 예측 모델을 실행하기 위해 데이터센터 자원이 필요합니다."),
        ):
            client = self.conn.execute(
                "SELECT id FROM clients WHERE company_name=? AND country=? ORDER BY id LIMIT 1",
                (company, country),
            ).fetchone()
            if client is None:
                cursor = self.conn.execute(
                    "INSERT INTO clients (company_name, country) VALUES (?, ?)",
                    (company, country),
                )
                client_id = cursor.lastrowid
            else:
                client_id = client["id"]
            self.conn.execute(
                """INSERT INTO missions (client_id, title, description)
                   SELECT ?, ?, ? WHERE NOT EXISTS (
                       SELECT 1 FROM missions WHERE client_id=? AND title=?
                   )""",
                (client_id, title, description, client_id, title),
            )
        self.conn.commit()

    def get_missions(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT m.id, m.title, m.description, c.company_name, c.country
               FROM missions m JOIN clients c ON m.client_id = c.id ORDER BY m.id"""
        ).fetchall()

    def get_mission(self, mission_id: int = 1) -> sqlite3.Row:
        row = self.conn.execute(
            """SELECT m.id, m.title, m.description, c.company_name, c.country
               FROM missions m JOIN clients c ON m.client_id = c.id WHERE m.id = ?""",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"미션 {mission_id}을 찾을 수 없습니다.")
        return row

    def create_playthrough(self, mission_id: int, plan: str) -> int:
        with self.transaction():
            cursor = self.conn.execute(
                "INSERT INTO playthroughs (mission_id,plan,status,started_at) VALUES (?,?,'진행중',?)",
                (mission_id, plan, now_text()),
            )
        return int(cursor.lastrowid)

    def add_log(self, playthrough_id: int, message: str) -> None:
        with self.transaction():
            self.conn.execute(
                "INSERT INTO event_logs (playthrough_id,message,created_at) VALUES (?,?,?)",
                (playthrough_id, message, now_text()),
            )

    def save_result(self, playthrough_id: int, response: str,
                    succeeded: bool, score: int, result_text: str) -> None:
        with self.transaction():
            cursor = self.conn.execute(
                """UPDATE playthroughs SET response=?, status=?, score=?, result_text=?,
                   finished_at=? WHERE id=?""",
                (response, "성공" if succeeded else "실패", score,
                 result_text, now_text(), playthrough_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"수행 기록 {playthrough_id}을 찾을 수 없습니다.")

    def get_recent_results(self, limit: int = 12) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT p.id, p.mission_id, c.company_name, c.country, m.title, p.status, p.score,
                      p.started_at, p.plan, p.response
               FROM playthroughs p JOIN missions m ON p.mission_id = m.id
               JOIN clients c ON m.client_id = c.id
               WHERE p.status IN ('성공','실패') ORDER BY p.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    def get_logs(self, playthrough_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT message,created_at FROM event_logs WHERE playthrough_id=? ORDER BY id",
            (playthrough_id,),
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
