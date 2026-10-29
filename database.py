"""SQLite 데이터 저장: 고객, 미션, 수행 결과, 사건 로그."""
import sqlite3
import json
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
        self.migrate_requests()
        self.migrate_operations()

    def migrate_operations(self):
        """기존 테이블의 CHECK와 기록을 유지하며 운영 스냅샷을 확장합니다."""
        with self.transaction():
            for sql in (
                """CREATE TABLE IF NOT EXISTS simulation_state (
                    id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS request_runtime (
                    request_id INTEGER PRIMARY KEY REFERENCES customer_requests(id),
                    playthrough_id INTEGER REFERENCES playthroughs(id), payload TEXT NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS request_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL REFERENCES customer_requests(id),
                    playthrough_id INTEGER REFERENCES playthroughs(id),
                    game_minute INTEGER NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS retry_links (
                    child_id INTEGER PRIMARY KEY REFERENCES playthroughs(id),
                    parent_id INTEGER NOT NULL REFERENCES playthroughs(id),
                    request_id INTEGER NOT NULL REFERENCES customer_requests(id),
                    retry_number INTEGER NOT NULL CHECK(retry_number BETWEEN 1 AND 2),
                    preparation_minutes INTEGER NOT NULL DEFAULT 20)""",
            ):
                self.conn.execute(sql)

    def get_simulation(self):
        row = self.conn.execute("SELECT payload FROM simulation_state WHERE id=1").fetchone()
        return json.loads(row["payload"]) if row else None

    def save_simulation(self, payload):
        with self.transaction():
            self.conn.execute("""INSERT INTO simulation_state VALUES (1,?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload""", (json.dumps(payload),))

    def get_runtime(self, request_id):
        row = self.conn.execute("SELECT payload FROM request_runtime WHERE request_id=?", (request_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_runtime(self, request_id, playthrough_id, payload):
        with self.transaction():
            self.conn.execute("""INSERT INTO request_runtime VALUES (?,?,?)
                ON CONFLICT(request_id) DO UPDATE SET playthrough_id=excluded.playthrough_id,
                payload=excluded.payload""", (request_id, playthrough_id, json.dumps(payload)))

    def add_request_event(self, request_id, run_id, minute, kind, message):
        with self.transaction():
            self.conn.execute("""INSERT INTO request_events
                (request_id,playthrough_id,game_minute,kind,message) VALUES (?,?,?,?,?)""",
                (request_id, run_id, minute, kind, message))

    def get_request_events(self, request_id):
        return self.conn.execute("SELECT * FROM request_events WHERE request_id=? ORDER BY id", (request_id,)).fetchall()

    def link_retry(self, request_id, child_id, parent_id, retry_number):
        with self.transaction():
            request, parent, child = self.get_request(request_id), self.get_playthrough(parent_id), self.get_playthrough(child_id)
            if (request["status"] != "completed" or request["playthrough_id"] != parent_id
                    or parent["status"] != "실패" or child["status"] != "진행중"
                    or child["mission_id"] != request["mission_id"] or parent["mission_id"] != request["mission_id"]):
                raise ValueError("재처리 요청과 이전 실패 기록이 일치하지 않습니다.")
            self.conn.execute("INSERT INTO retry_links VALUES (?,?,?,?,20)",
                              (child_id, parent_id, request_id, retry_number))
            self.conn.execute("""UPDATE customer_requests SET status='operating',playthrough_id=?,updated_at=?
                WHERE id=?""", (child_id, now_text(), request_id))

    def get_retry_links(self, request_id):
        return self.conn.execute("SELECT * FROM retry_links WHERE request_id=? ORDER BY retry_number", (request_id,)).fetchall()

    def migrate_requests(self) -> None:
        """기존 4개 테이블을 변경하지 않는 반복 실행 가능한 확장입니다."""
        with self.transaction():
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS customer_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mission_id INTEGER NOT NULL REFERENCES missions(id),
                    message TEXT NOT NULL,
                    source_key TEXT UNIQUE,
                    status TEXT NOT NULL DEFAULT 'new'
                        CHECK(status IN ('new','review','waiting','operating','rejected','completed')),
                    is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
                    rejection_reason TEXT,
                    playthrough_id INTEGER UNIQUE REFERENCES playthroughs(id),
                    received_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(status != 'rejected' OR
                        (rejection_reason IS NOT NULL AND length(trim(rejection_reason)) > 0)),
                    CHECK((status IN ('operating','completed') AND playthrough_id IS NOT NULL)
                        OR (status IN ('new','review','waiting','rejected') AND playthrough_id IS NULL))
                )
            """)
            self.conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS request_open_mission
                ON customer_requests(mission_id)
                WHERE status IN ('new','review','waiting','operating')""")

    def get_requests(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM customer_requests ORDER BY id").fetchall()

    def get_request(self, request_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM customer_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise ValueError(f"요청 {request_id}을 찾을 수 없습니다.")
        return row

    def find_request_by_source(self, source_key):
        return self.conn.execute('SELECT * FROM customer_requests WHERE source_key=?', (source_key,)).fetchone()

    def create_request(self, mission_id: int, message: str, source_key: str | None = None) -> int:
        with self.transaction():
            if source_key is not None:
                row = self.conn.execute("SELECT id FROM customer_requests WHERE source_key=?", (source_key,)).fetchone()
                if row is not None:
                    return row["id"]
            stamp = now_text()
            cursor = self.conn.execute("""INSERT INTO customer_requests
                (mission_id,message,source_key,received_at,updated_at) VALUES (?,?,?,?,?)""",
                (mission_id, message, source_key, stamp, stamp))
            return int(cursor.lastrowid)

    def mark_request_read(self, request_id: int) -> None:
        with self.transaction():
            cursor = self.conn.execute("""UPDATE customer_requests SET is_read=1,
                status=CASE WHEN status='new' THEN 'review' ELSE status END, updated_at=? WHERE id=?""",
                (now_text(), request_id))
            if cursor.rowcount != 1:
                raise ValueError("요청을 찾을 수 없습니다.")

    def mark_request_unread(self, request_id):
        with self.transaction():
            cursor = self.conn.execute("UPDATE customer_requests SET is_read=0 WHERE id=?", (request_id,))
            if cursor.rowcount != 1:
                raise ValueError("요청을 찾을 수 없습니다.")

    def change_request_status(self, request_id: int, status: str,
                              playthrough_id: int | None = None, reason: str | None = None) -> None:
        allowed = {"waiting": ("new", "review", "waiting"),
                   "rejected": ("new", "review", "waiting"),
                   "operating": ("new", "review", "waiting"), "completed": ("operating",)}
        if status not in allowed:
            raise ValueError("잘못된 요청 상태 변경입니다.")
        reason = reason.strip() if reason else None
        if status == "rejected" and not reason:
            raise ValueError("거절 사유를 입력해 주세요.")
        with self.transaction():
            row = self.get_request(request_id)
            if row["status"] not in allowed[status]:
                raise ValueError("이미 처리했거나 현재 변경할 수 없는 요청입니다.")
            run_id = playthrough_id if status == "operating" else row["playthrough_id"]
            if status in ("operating", "completed"):
                run = self.get_playthrough(run_id)
                if run["mission_id"] != row["mission_id"] or ((run["status"] == "진행중") != (status == "operating")):
                    raise ValueError("요청과 수행 기록의 상태 또는 미션이 일치하지 않습니다.")
            self.conn.execute("""UPDATE customer_requests SET status=?, is_read=1,
                rejection_reason=?, playthrough_id=?, updated_at=? WHERE id=?""",
                (status, reason, run_id, now_text(), request_id))

    def get_playthrough(self, playthrough_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM playthroughs WHERE id=?", (playthrough_id,)).fetchone()
        if row is None:
            raise ValueError("수행 기록을 찾을 수 없습니다.")
        return row

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
                   finished_at=? WHERE id=? AND status='진행중'""",
                (response, "성공" if succeeded else "실패", score,
                 result_text, now_text(), playthrough_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"진행 중인 수행 기록 {playthrough_id}을 찾을 수 없습니다.")

    def get_recent_records(self, limit: int = 30) -> list[sqlite3.Row]:
        """현재 작업 및 이전 실행의 미완료 기록까지 조회합니다."""
        return self.conn.execute(
            """SELECT p.id, p.mission_id, c.company_name, c.country, m.title, p.status, p.score,
                      p.started_at, p.plan, p.response
               FROM playthroughs p JOIN missions m ON p.mission_id = m.id
               JOIN clients c ON m.client_id = c.id ORDER BY p.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()

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
