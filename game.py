"""AIDC Simulator: GUI나 DB에 의존하지 않는 게임 규칙."""
from dataclasses import dataclass

GPU_TOTAL = 10
POWER_TOTAL = 10
NETWORK_NORMAL = 8
NETWORK_DURING_INCIDENT = 2

PLANS = {
    "performance": {"label": "고성능 모드", "gpu": 7, "power": 7, "network": 5, "bonus": 15},
    "economy": {"label": "절약형 모드", "gpu": 4, "power": 4, "network": 3, "bonus": 5},
}
RESPONSES = {
    "reroute": {"label": "백업 경로로 우회", "penalty": 15},
    "compress": {"label": "전송 데이터 압축", "penalty": 10},
    "ignore": {"label": "기존 설정 유지", "penalty": 25},
}

@dataclass
class DataCenter:
    gpu_total: int = GPU_TOTAL
    power_total: int = POWER_TOTAL

    gpu_used: int = 0
    power_used: int = 0

    # 현재 사용할 수 있는 GPU 계산
    def available_gpu(self):
        return self.gpu_total - self.gpu_used

    # 현재 사용할 수 있는 전력 계산
    def available_power(self):
        return self.power_total - self.power_used

    # 자원 배정
    def allocate(self, gpu, power):

        if gpu <= 0 or power <= 0:
            raise ValueError("요청 자원은 양수여야 합니다.")

        if gpu > self.available_gpu():
            return False

        if power > self.available_power():
            return False

        self.gpu_used += gpu
        self.power_used += power

        return True

    # 사용이 끝난 자원 반환
    def release(self, gpu, power):

        if gpu < 0 or power < 0:
            raise ValueError("반환 자원은 음수일 수 없습니다.")

        if gpu > self.gpu_used or power > self.power_used:
            raise ValueError("사용량보다 많은 자원을 반환할 수 없습니다.")

        self.gpu_used -= gpu
        self.power_used -= power

@dataclass
class GameState:
    """한 번의 미션 진행 상태: ready -> incident -> finished."""
    center: DataCenter | None = None
    phase: str = "ready"
    plan: str | None = None
    response: str | None = None
    gpu_used: int = 0
    power_used: int = 0
    network_needed: int = 0
    network_available: int = NETWORK_NORMAL
    score: int | None = None
    succeeded: bool | None = None
    result_text: str = ""

    def choose_plan(self, plan_key: str) -> None:
        if self.phase != "ready":
            raise ValueError("자원 배분은 미션 시작 전에만 선택할 수 있습니다.")
        if plan_key not in PLANS:
            raise ValueError("존재하지 않는 운영 모드입니다.")
        plan = PLANS[plan_key]
        if plan["gpu"] > GPU_TOTAL or plan["power"] > POWER_TOTAL:
            raise ValueError("데이터센터의 자원이 부족합니다.")
        else:
            if not self.center.allocate(plan["gpu"], plan["power"]):
                raise ValueError("현재 사용 가능한 자원이 부족합니다.")

        self.plan = plan_key
        self.gpu_used = plan["gpu"]
        self.power_used = plan["power"]
        self.network_needed = plan["network"]
        self.network_available = NETWORK_DURING_INCIDENT
        self.phase = "incident"

    def resolve(self, response_key: str) -> None:
        if self.phase != "incident" or self.plan is None:
            raise ValueError("장애가 발생한 뒤에만 대응할 수 있습니다.")
        if response_key not in RESPONSES:
            raise ValueError("존재하지 않는 장애 대응 방법입니다.")
        self.response = response_key
        available = self.network_available
        required = self.network_needed
        if response_key == "reroute":
            available = min(NETWORK_NORMAL, available + 4)
        elif response_key == "compress":
            required = max(1, required - 2)
        self.network_available = available
        self.network_needed = required
        self.succeeded = required <= available
        base_score = 80 + PLANS[self.plan]["bonus"]
        penalty = RESPONSES[response_key]["penalty"]
        self.score = max(0, min(100, base_score - penalty + (10 if self.succeeded else -65)))
        if self.succeeded:
            self.result_text = (
                f"요청 처리 성공! 필요 네트워크 {required} / 가용 {available}단위. "
                f"고객의 학습 요청이 정상 완료되었습니다. 운영 점수: {self.score}점."
            )
        else:
            self.result_text = (
                f"요청 처리 실패. 필요 네트워크 {required} / 가용 {available}단위. "
                f"통신 자원이 부족하여 작업이 중단되었습니다. 운영 점수: {self.score}점."
            )
        self.phase = "finished"
        if self.center is not None:
            self.center.release(self.gpu_used, self.power_used)