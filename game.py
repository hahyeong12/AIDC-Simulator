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
# 국가로 규칙을 연결하므로 기존 DB의 고객/미션 ID를 바꿀 필요가 없습니다.
CUSTOMER_PLANS = {
    "싱가포르": PLANS,
    "일본": {
        "performance": {"label": "고성능 모드", "gpu": 3, "power": 4, "network": 3, "bonus": 15},
        "economy": {"label": "절약형 모드", "gpu": 2, "power": 2, "network": 2, "bonus": 5},
    },
    "미국": {
        "performance": {"label": "고성능 모드", "gpu": 6, "power": 6, "network": 6, "bonus": 15},
        "economy": {"label": "절약형 모드", "gpu": 4, "power": 3, "network": 5, "bonus": 5},
    },
}


def plans_for(country: str) -> dict:
    """이전 버전의 사용자 추가 고객은 기본 학습 작업 규칙을 사용합니다."""
    return CUSTOMER_PLANS.get(country, PLANS)


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

ACTIVE_PHASES = ("running", "incident", "paused", "recovering")
WORK_TOTAL = {"싱가포르": 120, "일본": 60, "미국": 100}
# 접수부터 배정 권장/완료/최종 접수 종료까지의 분. 교육용 가상 SLA입니다.
REQUEST_WINDOWS = {
    "싱가포르": ("일반 · 모델 학습", 60, 210, 330),
    "일본": ("긴급 · 로봇 추론", 20, 70, 190),
    "미국": ("우선 · 데이터 분석", 40, 120, 240),
}
MODE_SPEEDS = {"performance": 1, "economy": .7}


def game_time(minute):
    return f'D{minute//1440+1} {minute//60%24:02d}:{minute%60:02d}'


def request_terms(country, minute):
    priority, start, due, expiry = REQUEST_WINDOWS.get(country, REQUEST_WINDOWS["싱가포르"])
    return {'priority': priority, 'received': minute, 'start_due': minute+start,
            'due': minute+due, 'expires': minute+expiry, 'alerts': []}


@dataclass
class GameState:
    """요청과 독립적인 작업 상태. 모든 시간/속도/비용 수치는 교육용 가상 설정입니다."""
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
    country: str = "싱가포르"
    work_done: float = 0
    elapsed: int = 0
    downtime: int = 0
    recovery_left: int = 0
    incident_at: float | None = None
    incident_occurred: bool = False
    response_attempts: int = 0
    cost_penalty: int = 0
    retry_count: int = 0

    def __post_init__(self):
        if self.center is None:
            self.center = DataCenter()

    @property
    def plans(self):
        return plans_for(self.country)

    @property
    def allocated(self):
        return self.phase in ACTIVE_PHASES

    @property
    def work_total(self):
        return WORK_TOTAL.get(self.country, 120)

    @property
    def progress(self):
        return min(100, self.work_done / self.work_total * 100)

    @property
    def remaining_minutes(self):
        return self.estimate_minutes(self.plan or "performance")

    def estimate_minutes(self, plan_key):
        import math
        speed = MODE_SPEEDS[plan_key]
        return max(0, math.ceil((self.work_total-self.work_done)/speed/10)*10) + self.recovery_left

    def choose_plan(self, plan_key):
        if self.phase not in ("ready", "accepted"):
            raise ValueError("이미 시작한 작업은 중복 배정할 수 없습니다.")
        if plan_key not in self.plans:
            raise ValueError("존재하지 않는 운영 모드입니다.")
        plan = self.plans[plan_key]
        if not self.center.allocate(plan["gpu"], plan["power"]):
            raise ValueError("현재 사용 가능한 자원이 부족합니다.")
        self.plan, self.gpu_used, self.power_used = plan_key, plan["gpu"], plan["power"]
        self.network_needed, self.network_available = plan["network"], NETWORK_NORMAL
        self.phase = "recovering" if self.retry_count else "running"
        self.recovery_left = 20 if self.retry_count else 0

    def trigger_incident(self):
        if self.phase != "running":
            raise ValueError("정상 실행 중인 작업에서만 장애가 발생합니다.")
        self.incident_occurred = True
        self.network_available = NETWORK_DURING_INCIDENT
        self.phase = "incident"

    def advance(self, minutes):
        if minutes <= 0:
            raise ValueError("진행 시간은 양수여야 합니다.")
        if not self.allocated:
            return
        self.elapsed += minutes
        if self.phase in ("incident", "paused"):
            self.downtime += minutes
            if self.downtime >= 60:
                self.response = self.response or "timeout"
                self.finish(False, "장애 중단 60분을 초과하여 이번 수행에 실패했습니다.")
            return
        if self.phase == "recovering":
            consumed = min(minutes, self.recovery_left)
            self.recovery_left -= consumed
            minutes -= consumed
            if self.recovery_left:
                return
            self.phase = "running"
        self.work_done = min(self.work_total, self.work_done + minutes*MODE_SPEEDS[self.plan])
        if self.incident_at is not None and not self.incident_occurred and self.work_done >= self.incident_at:
            self.trigger_incident()
        elif self.work_done >= self.work_total:
            self.finish(True, "고객의 AI 작업이 정상 완료되었습니다.")

    def resolve(self, response_key):
        if self.phase not in ("incident", "paused") or self.plan is None:
            raise ValueError("장애 또는 중단 상태에서만 대응할 수 있습니다.")
        if response_key not in RESPONSES:
            raise ValueError("존재하지 않는 장애 대응 방법입니다.")
        self.response = response_key
        self.response_attempts += 1
        self.cost_penalty += RESPONSES[response_key]["penalty"]
        if response_key == "reroute":
            self.network_available = min(NETWORK_NORMAL, self.network_available + 4)
        elif response_key == "compress":
            self.network_needed = max(1, self.network_needed - 2)
        if self.network_needed <= self.network_available:
            self.phase = "recovering"
            self.recovery_left = 10
            self.result_text = "네트워크 복구에 성공했습니다. 10분 복구 후 작업을 재개합니다."
        elif self.response_attempts >= 3:
            self.finish(False, "장애 대응 3회가 실패하여 이번 수행을 중단했습니다. 후속 조치를 선택해 주세요.")
        else:
            self.phase = "paused"
            self.result_text = "복구 자원이 부족하여 일시 중단되었습니다. 다른 대응을 재시도할 수 있습니다."

    def finish(self, succeeded, text):
        if not self.allocated:
            raise ValueError("운영 중인 수행만 종료할 수 있습니다.")
        self.center.release(self.gpu_used, self.power_used)
        self.phase, self.succeeded = "finished", succeeded
        base = 80+self.plans[self.plan]["bonus"]
        self.score = max(0, min(100, base-self.cost_penalty-10*self.retry_count
                               -min(20,self.downtime//10)+(10 if succeeded else -65)))
        self.result_text = f"{text} 운영 점수: {self.score}점."
