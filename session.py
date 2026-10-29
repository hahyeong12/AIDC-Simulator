"""여러 미션의 자원 공유와 SQLite 저장을 한 작업 단위로 관리합니다."""
from dataclasses import dataclass, field

from database import Database
from game import DataCenter, GameState, RESPONSES


@dataclass
class MissionRun:
    mission: object
    state: GameState
    playthrough_id: int | None = None
    messages: list[str] = field(default_factory=list)


class GameSession:
    def __init__(self, db: Database):
        self.db = db
        self.center = DataCenter()
        self.runs = {
            mission["id"]: MissionRun(
                mission, GameState(center=self.center, country=mission["country"])
            ) for mission in db.get_missions()
        }
        self.selected_id = next(iter(self.runs))

    @property
    def current(self) -> MissionRun:
        return self.runs[self.selected_id]

    def select(self, mission_id: int) -> None:
        if mission_id not in self.runs:
            raise ValueError(f"미션 {mission_id}을 찾을 수 없습니다.")
        self.selected_id = mission_id

    def restart(self) -> None:
        run = self.current
        if run.state.phase == "incident":
            raise ValueError("진행 중인 작업은 장애 대응을 완료한 뒤 다시 시작할 수 있습니다.")
        run.state = GameState(center=self.center, country=run.mission["country"])
        run.playthrough_id = None
        run.messages.clear()

    def _commit_action(self, action) -> list[str]:
        """DB 오류 시 다른 고객과 참조를 유지한 채 메모리 상태도 되돌립니다."""
        run = self.current
        snapshot = vars(run.state).copy()
        previous_id = run.playthrough_id
        usage = self.center.gpu_used, self.center.power_used
        try:
            with self.db.transaction():
                messages = action(run)
                for message in messages:
                    self.db.add_log(run.playthrough_id, message)
        except Exception:
            vars(run.state).update(snapshot)
            run.playthrough_id = previous_id
            self.center.gpu_used, self.center.power_used = usage
            raise
        run.messages.extend(messages)
        return messages

    def choose_plan(self, key: str) -> list[str]:
        def start(run):
            state, mission = run.state, run.mission
            state.choose_plan(key)
            run.playthrough_id = self.db.create_playthrough(mission["id"], key)
            return [
                f"[고객 요청] {mission['company_name']} ({mission['country']}) · {mission['title']}\n"
                f"{mission['description']}\n[자원 배정] {state.plans[key]['label']} · "
                f"GPU {state.gpu_used}개 / 전력 {state.power_used}단위 / 필요 네트워크 {state.network_needed}단위.",
                "[긴급 알림] 국제 네트워크 회선 장애! 이 고객의 가용량이 8 → 2단위로 감소했습니다. "
                "다른 고객으로 이동해도 배정 자원과 장애 상태는 유지됩니다.",
            ]
        return self._commit_action(start)

    def respond(self, key: str) -> list[str]:
        def finish(run):
            state = run.state
            state.resolve(key)
            self.db.save_result(run.playthrough_id, key, state.succeeded, state.score, state.result_text)
            return [f"[운영 조치] {RESPONSES[key]['label']} 선택.",
                    f"[처리 결과] {state.result_text} GPU {state.gpu_used}개 / 전력 {state.power_used}단위 반환."]
        return self._commit_action(finish)

    def abandon_active(self) -> None:
        """정상 종료 정책. 전체 저장 성공 후에만 메모리 자원을 반환합니다."""
        active = [run for run in self.runs.values() if run.state.phase == "incident"]
        text = "프로그램 종료로 미완료 작업이 중단되었습니다. 운영 점수: 0점."
        with self.db.transaction():
            for run in active:
                self.db.add_log(run.playthrough_id, f"[근무 종료] {text}")
                self.db.save_result(run.playthrough_id, "abandon", False, 0, text)
        for run in active:
            state = run.state
            self.center.release(state.gpu_used, state.power_used)
            state.phase, state.response = "finished", "abandon"
            state.succeeded, state.score, state.result_text = False, 0, text
            run.messages.append(f"[근무 종료] {text}")
