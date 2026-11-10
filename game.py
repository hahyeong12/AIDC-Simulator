"""AIDC Simulator: GUI나 DB에 의존하지 않는 게임 규칙."""
from dataclasses import dataclass, field

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
# Chapter 2 교육 시나리오 전용 요청 조건. scenario가 없는 요청(자유 운영/Chapter 1)은 위의 국가별 규칙을 그대로 씁니다.
# 저장된 요청은 GameState.scenario 이름으로 이 표를 다시 읽으므로, 이미 쓰인 이름의 수치는 바꾸지 않습니다.
# 새 조건은 새 이름으로 추가하고 chapter2.CHAPTER2_SCENARIOS에서 새 시작에만 연결합니다.
SCENARIOS = {
    "ch2_jp": {"plans": {"performance": {"label": "고성능 모드", "gpu": 4, "power": 5, "network": 3, "bonus": 15},
                         "economy": {"label": "절약형 모드", "gpu": 2, "power": 3, "network": 2, "bonus": 5}},
               "work": 40, "window": ("긴급 · 로봇 추론", 10, 50, 80)},
    # v0.9-2a-2~3 저장 호환용(작업 100·기한 150분). 일본 고성능 → 미국 고성능 순차 실행도 기한 안에 끝납니다.
    "ch2_us": {"plans": {"performance": {"label": "고성능 모드", "gpu": 6, "power": 6, "network": 6, "bonus": 15},
                         "economy": {"label": "절약형 모드", "gpu": 4, "power": 3, "network": 5, "bonus": 5}},
               "work": 100, "window": ("우선 · 데이터 분석", 40, 150, 240)},
    # v0.9-2a-4: 작업 70 → 고성능 70분 / 절약형 100분, 완료 기한 100분, 최종 배정 기한 120분.
    # 두 고객의 고성능 합계(전력 11)는 동시에 실행할 수 없고, 일본(40분) 뒤 미국 고성능은 110분에 끝나 기한을 넘깁니다.
    # 일본 고성능(GPU 4/전력 5)과 미국 절약형(GPU 4/전력 3)을 바로 함께 배정할 때만 두 기한을 모두 지킬 수 있습니다.
    "ch2_us_v2": {"plans": {"performance": {"label": "고성능 모드", "gpu": 6, "power": 6, "network": 6, "bonus": 15},
                            "economy": {"label": "절약형 모드", "gpu": 4, "power": 3, "network": 5, "bonus": 5}},
                  "work": 70, "window": ("우선 · 데이터 분석", 10, 100, 120)},
    # v0.9-3a Chapter 3: 네트워크 장애 진단 교육용 구성(실제 네트워크의 일반 규칙이 아닙니다). 장애는 작업량 40%에서 결정적으로 발생합니다.
    # path_down: 주 통신 경로 단절(가용 0). 백업 경로(용량 6)로 우회해야 복구되고 압축만으로는 복구되지 않습니다.
    # bandwidth: 경로는 연결됐지만 가용 대역폭(4)이 필요량(고성능 6/절약형 5)보다 작습니다. 백업 경로는 같은 병목 구간을 공유해
    #            용량이 늘지 않으므로 압축으로 필요량을 줄여야 복구됩니다.
    "ch3_path": {"plans": {"performance": {"label": "고성능 모드", "gpu": 4, "power": 4, "network": 5, "bonus": 15},
                           "economy": {"label": "절약형 모드", "gpu": 3, "power": 2, "network": 3, "bonus": 5}},
                 "work": 60, "window": ("일반 · 모델 학습", 10, 150, 240),
                 "incident": {"kind": "path_down", "at": .4, "available": 0, "backup": 6}},
    "ch3_bw": {"plans": {"performance": {"label": "고성능 모드", "gpu": 4, "power": 3, "network": 6, "bonus": 15},
                         "economy": {"label": "절약형 모드", "gpu": 3, "power": 2, "network": 5, "bonus": 5}},
               "work": 50, "window": ("우선 · 데이터 분석", 10, 140, 220),
               "incident": {"kind": "bandwidth", "at": .4, "available": 4, "backup": 4}},
    # v0.9-3b Chapter 3b: 서버 장비 장애 교육용 구성. 장애는 작업량 40%에서 결정적으로 발생합니다(hardware_fault).
    # 일본: GPU 3/전력 4(기존 요청 규칙). 장애 시점에서 이전 10분이면 시작 후 70분, 복구 20분이면 80분에 끝나므로 기한 75분이 둘을 가릅니다.
    # 싱가포르: GPU 7/전력 7. 정상 서버(B·C·D)의 GPU 합계가 6이라 전체 작업 이전이 불가능하고 장비 복구만 가능합니다.
    "ch3b_jp": {"plans": {"performance": {"label": "고성능 모드", "gpu": 3, "power": 4, "network": 3, "bonus": 15},
                          "economy": {"label": "절약형 모드", "gpu": 2, "power": 2, "network": 2, "bonus": 5}},
                "work": 60, "window": ("긴급 · 로봇 추론", 10, 75, 120),
                "hardware_fault": {"server": "A", "at": .4}},
    "ch3b_sg": {"plans": {"performance": {"label": "고성능 모드", "gpu": 7, "power": 7, "network": 5, "bonus": 15},
                          "economy": {"label": "절약형 모드", "gpu": 4, "power": 4, "network": 3, "bonus": 5}},
                "work": 60, "window": ("일반 · 모델 학습", 10, 150, 240),
                "hardware_fault": {"server": "A", "at": .4}},
}


def game_time(minute):
    return f'D{minute//1440+1} {minute//60%24:02d}:{minute%60:02d}'


def request_terms(country, minute, scenario=None):
    window = SCENARIOS[scenario]["window"] if scenario else REQUEST_WINDOWS.get(country, REQUEST_WINDOWS["싱가포르"])
    priority, start, due, expiry = window
    return {'priority': priority, 'received': minute, 'start_due': minute+start,
            'due': minute+due, 'expires': minute+expiry, 'alerts': []}


def request_conditions(mission, due, scenario=None):
    """신규 접수 때만 고객 의사와 자원 조건을 고정합니다. 과거 요청에는 적용하지 않습니다."""
    # 긴급 추론과 지정 환경의 학습은 고성능 요청, 배치 분석은 두 환경을 허용합니다.
    flexible = mission['country'] == '미국'
    return {'type': 'flexible' if flexible else 'fixed', 'task': mission['title'],
            'requested_mode': 'performance',
            'allowed_modes': ['performance', 'economy'] if flexible else ['performance'],
            'plans': {key: dict(plan, mode=key) for key, plan in
                      (SCENARIOS[scenario]["plans"] if scenario else plans_for(mission['country'])).items()},
            'due': due}


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
    scenario: str | None = None  # Chapter 2/3 전용 요청 조건 이름. 없으면 국가별 기본 규칙
    # v0.9-3a: 장애 원인 구분(Chapter 3 시나리오 전용). 없는 이전 저장과 자유 운영은 기본값 그대로 기존 규칙을 사용합니다.
    incident_kind: str | None = None   # 'path_down' | 'bandwidth'
    primary_up: bool = True            # 주 통신 경로 상태
    rerouted: bool = False             # 백업 경로로 우회했는지
    backup_capacity: int = 0           # 백업 경로 용량
    response_log: list = field(default_factory=list)  # 시도한 대응 순서(항상 새 리스트로 교체해 롤백과 충돌하지 않게 합니다)
    recovered_by: str | None = None    # 복구에 성공한 대응

    def __post_init__(self):
        if self.center is None:
            self.center = DataCenter()

    @property
    def plans(self):
        return SCENARIOS[self.scenario]["plans"] if self.scenario else plans_for(self.country)

    @property
    def allocated(self):
        return self.phase in ACTIVE_PHASES

    @property
    def work_total(self):
        return SCENARIOS[self.scenario]["work"] if self.scenario else WORK_TOTAL.get(self.country, 120)

    @property
    def progress(self):
        return min(100, self.work_done / self.work_total * 100)

    @property
    def remaining_minutes(self):
        return self.estimate_minutes(self.plan or "performance")

    def estimate_minutes(self, plan_key):
        import math
        speed = MODE_SPEEDS[plan_key]
        # 42/0.7 = 60.00000000000001 같은 부동소수점 오차가 10분 구간 하나를 더 세지 않도록 반올림 후 올림합니다.
        # 실제 진행(advance)은 10분마다 같은 속도를 더하므로 예상과 실제 완료 시각이 일치합니다.
        return max(0, math.ceil(round((self.work_total-self.work_done)/speed, 6)/10)*10) + self.recovery_left

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
        config = SCENARIOS[self.scenario].get("incident") if self.scenario in SCENARIOS else None
        if config:
            self.incident_kind = config["kind"]
            self.primary_up = config["kind"] != "path_down"
            self.backup_capacity = config["backup"]
            self.network_available = config["available"]
        else:
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
        self.response_log = [*self.response_log, response_key]
        if self.incident_kind:
            recovered = self._apply_diagnosed_response(response_key)
        else:
            if response_key == "reroute":
                self.network_available = min(NETWORK_NORMAL, self.network_available + 4)
            elif response_key == "compress":
                self.network_needed = max(1, self.network_needed - 2)
            recovered = self.network_needed <= self.network_available
        if recovered:
            self.recovered_by = response_key
            self.phase = "recovering"
            self.recovery_left = 10
            self.result_text = "네트워크 복구에 성공했습니다. 10분 복구 후 작업을 재개합니다."
        elif self.response_attempts >= 3:
            self.finish(False, "장애 대응 3회가 실패하여 이번 수행을 중단했습니다. 후속 조치를 선택해 주세요.")
        else:
            self.phase = "paused"
            self.result_text = ("복구 자원이 부족하여 일시 중단되었습니다. 다른 대응을 재시도할 수 있습니다."
                                if not self.incident_kind else self.observed_result(response_key))

    @property
    def link_ok(self):
        """작업 데이터가 지나갈 통신 경로가 살아 있는지(주 경로 또는 우회한 백업 경로)."""
        return self.primary_up or self.rerouted

    def observed_result(self, response_key):
        """실패한 대응 직후 관찰되는 사실만 서술합니다(정답 대응은 알려 주지 않습니다)."""
        link = "주 통신 경로 UP" if self.primary_up else ("백업 경로 사용 중" if self.rerouted else "주 통신 경로 DOWN")
        applied = {"reroute": "백업 경로로 전환했습니다.", "compress": "전송 데이터를 압축했습니다.",
                   "ignore": "기존 설정을 유지했습니다."}[response_key]
        return (f"{applied} 그러나 작업은 재개되지 않았습니다. ({link} · 필요 대역폭 {self.network_needed} / "
                f"가용 {self.network_available}) 남은 대응 {max(0, 3-self.response_attempts)}회. 상태를 다시 확인해 판단해 주세요.")

    def _apply_diagnosed_response(self, response_key):
        """Chapter 3 교육 구성의 원인별 효과. 대응 효과는 모두 기록된 수치로 계산하며 복구 여부만 반환합니다."""
        if response_key == "reroute":
            self.rerouted = True
            if self.incident_kind == "path_down":
                self.network_available = min(NETWORK_NORMAL, self.backup_capacity)
            # bandwidth: 백업 경로가 같은 병목 구간을 공유하므로 가용 대역폭은 늘지 않습니다.
        elif response_key == "compress":
            self.network_needed = max(1, self.network_needed - 2)
        return self.link_ok and self.network_needed <= self.network_available

    def finish(self, succeeded, text):
        if not self.allocated:
            raise ValueError("운영 중인 수행만 종료할 수 있습니다.")
        self.center.release(self.gpu_used, self.power_used)
        self.phase, self.succeeded = "finished", succeeded
        base = 80+self.plans[self.plan]["bonus"]
        self.score = max(0, min(100, base-self.cost_penalty-10*self.retry_count
                               -min(20,self.downtime//10)+(10 if succeeded else -65)))
        self.result_text = f"{text} 운영 점수: {self.score}점."
