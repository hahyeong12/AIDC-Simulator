"""v0.9-4a Engineering Lab(Prototype)의 공통 관찰 모델. GUI/SQLite와 독립된 읽기 전용 계산입니다.

같은 GameSession 상태(같은 가상 시각·서버·네트워크 장애)를 운영 상태·구조도·서버 내부·명령어 학습·가상 터미널이
함께 사용하도록 `observe()` 하나에서 `LabObservation`을 만듭니다. 이 모듈은 세션·요청·원장·DB를 변경하지 않습니다.

게임에는 IP 주소·라우터·인터페이스가 없으므로 `LAB_NETWORK`에 **교육용 가상 네트워크 설정**을 따로 정의합니다.
이 값은 실제 AIDC·고객사 장비의 주소나 구성이 아니며 화면에도 그렇게 표시합니다.
"""
from dataclasses import dataclass, field

from server_resources import SERVERS

# 첫 프로토타입은 Chapter 3a 미션 A(통신 경로 단절) 하나만 지원합니다.
SUPPORTED_SCENARIOS = ('ch3_path',)

LAB_NOTICE = '교육용 가상 네트워크 설정입니다. 실제 AIDC·고객사 장비의 주소나 구성이 아닙니다.'
LAB_NETWORK = {
    'notice': LAB_NOTICE,
    # 가상 터미널이 접속한 관찰 지점: 싱가포르 고객 측 연동 단말(AIDC가 원격 관리한다고 가정한 교육용 장비)
    'host': 'sg-edge',
    'host_label': '고객 연동 단말',
    'user': 'engineer',
    'interfaces': (
        {'name': 'lo', 'address': '127.0.0.1', 'prefix': 8, 'mac': '00:00:00:00:00:00', 'path': None},
        {'name': 'eth0', 'address': '192.168.10.5', 'prefix': 24, 'mac': '02:00:c0:a8:0a:05', 'path': 'primary'},
        {'name': 'eth1', 'address': '192.168.20.5', 'prefix': 24, 'mac': '02:00:c0:a8:14:05', 'path': 'backup'},
    ),
    'routers': {
        'primary': {'name': 'rt-primary', 'label': '주 경로 라우터', 'address': '192.168.10.1', 'dev': 'eth0'},
        'backup': {'name': 'rt-backup', 'label': '백업 경로 라우터', 'address': '192.168.20.1', 'dev': 'eth1'},
    },
    'aidc_gateway': {'name': 'aidc-gw', 'label': 'AIDC 게이트웨이', 'address': '10.0.0.1'},
    'aidc_subnet': '10.0.0.0/24',
    'servers': {'A': '10.0.0.20', 'B': '10.0.0.21', 'C': '10.0.0.22', 'D': '10.0.0.23'},
}

PHASE_LABELS = {
    'ready': ('미배정', 'idle'), 'accepted': ('배정 대기', 'idle'), 'running': ('실행 중', 'ok'),
    'incident': ('중단 · 네트워크 장애', 'fault'), 'paused': ('중단 · 추가 대응 필요', 'fault'),
    'recovering': ('복구 준비 중', 'recover'),
}
# 아직 시뮬레이션하지 않는 서버 내부 정보. 화면에 '미구현'으로만 표시하고 값을 만들어 내지 않습니다.
UNSUPPORTED_INTERNALS = (
    ('OS 프로세스', 'ps · top'), ('서비스 상태', 'systemctl status'), ('소켓 · 포트', 'ss -lnt'),
    ('GPU 드라이버 · 사용률', 'nvidia-smi'), ('시스템 로그', 'journalctl'),
)


@dataclass(frozen=True)
class SlotView:
    index: int
    owner: str | None          # 고객 코드(sg/jp/us) 또는 None(빈 슬롯)
    this_job: bool             # 관찰 중인 작업의 슬롯인지


@dataclass(frozen=True)
class ServerView:
    key: str
    name: str
    address: str
    health: str                # HEALTHY / FAULT / REPAIRING
    repair_left: int
    gpu_total: int
    power_total: int
    gpu_used: int              # 모든 고객의 점유 합계(원장)
    power_used: int
    job_gpu: int               # 관찰 중인 작업의 점유
    job_power: int
    slots: tuple
    owners: tuple              # 이 서버를 쓰는 고객 코드

    @property
    def has_job(self):
        return self.job_gpu > 0 or self.job_power > 0


@dataclass(frozen=True)
class NetworkView:
    primary_up: bool
    backup_up: bool
    rerouted: bool
    link_ok: bool
    active_path: str           # 'primary' | 'backup'
    needed: int
    available: int
    backup_capacity: int
    incident_kind: str | None
    incident_occurred: bool
    recovered_by: str | None
    recovery_left: int
    downtime: int
    attempts: int
    responses: tuple
    segments: dict = field(default_factory=dict)   # 구간 id -> 'up' | 'down' | 'standby' | 'active'

    @property
    def congested(self):
        return self.link_ok and self.needed > self.available


@dataclass(frozen=True)
class LabObservation:
    minute: int
    time_label: str
    request_id: int
    playthrough_id: int | None
    customer: str
    country: str
    code: str
    task: str
    scenario: str | None
    phase: str
    phase_label: str
    tone: str                  # ok / fault / recover / idle / done / failed
    progress: float
    plan_label: str
    gpu_used: int
    power_used: int
    job_servers: tuple
    servers: tuple
    network: NetworkView
    incident_label: str
    recovery_label: str

    def server(self, key):
        return next(s for s in self.servers if s.key == key)

    @property
    def target_address(self):
        """'현재 서버'의 교육용 주소: 작업이 배정된 첫 서버, 아직 없으면 Server A."""
        return LAB_NETWORK['servers'][self.job_servers[0] if self.job_servers else 'A']

    @property
    def transferring(self):
        """작업 데이터가 오가는 중인지(교육용 흐름 애니메이션 표시 여부)."""
        return self.phase in ('running', 'incident', 'paused', 'recovering')


def customer_code(country):
    return {'싱가포르': 'sg', '일본': 'jp', '미국': 'us'}.get(country, 'x')


def lab_mode(session, rid=None):
    """(모드, 이유). 모드: 'training'(정규 심화 연수, Stage 잠금) · 'practice'(Engineering Lab 연습, 자유 선택)
    · 'preview'(Chapter 3a 미션 A의 관찰 탭만, 학습·명령 잠금) · None(미지원, 이유 안내). 조회 전용입니다."""
    story = session.story
    rid = session.selected_id if rid is None else rid
    run = session.runs.get(rid)
    unsupported = ('Engineering Lab(Prototype)은 Chapter 3a 미션 A(통신 경로 단절), 심화 연수, '
                   '[Engineering Lab 연습]에서 열 수 있습니다.\n')
    if story is None:
        return None, unsupported + '자유 운영에서는 아직 지원하지 않습니다. 기존 관제실 기능은 그대로 사용할 수 있습니다.'
    training = story.training
    if training is not None:
        if rid in training.request_ids:
            return ('practice' if training.practice else 'training'), ''
        return None, (f'심화 연수의 Engineering Lab은 연수 요청에서 엽니다. 고객 요청함에서 요청 #{training.rid}'
                      '(싱가포르 · 연수 사건)를 선택하세요.')
    if story.chapter3 is None or story.chapter3b is not None:
        return None, unsupported + '이 Chapter에서는 아직 지원하지 않습니다. 기존 관제실 기능은 그대로 사용할 수 있습니다.'
    if run is None or rid not in story.chapter3.request_ids or run.state.scenario not in SUPPORTED_SCENARIOS:
        hint = ''
        first = story.chapter3.request_ids[0]
        if session.runs[first].state.scenario in SUPPORTED_SCENARIOS and rid != first:
            hint = f'\n고객 요청함에서 요청 #{first}(싱가포르 · 미션 A)를 선택하면 열 수 있습니다.'
        return None, ('선택한 요청은 아직 Engineering Lab(Prototype)을 지원하지 않습니다. '
                      '첫 프로토타입은 미션 A(통신 경로 단절) 하나만 지원합니다.' + hint)
    return 'preview', ''


LAB_NETWORK_TAB = '네트워크 구조'


def diagnosis_lab_target(session, rid):
    """v0.9-4a-2: [네트워크 진단] 결과창에서 Lab의 네트워크 구조로 바로 갈 수 있는지(조회 전용).
    가능하면 (Lab 모드, 탭 이름), 아니면 None. 모드 판정은 lab_mode() 그대로라 미리보기 잠금·Stage 권한을 바꾸지 않습니다.
    심화 연수 중이면 Lab이 여는 요청(연수 요청)과 진단한 요청이 같을 때만 안내합니다."""
    mode, reason = lab_mode(session, rid)
    if mode is None or reason:
        return None
    training = session.story.training if session.story else None
    if training is not None and training.rid != rid:
        return None
    return mode, LAB_NETWORK_TAB


def job_symptom(observation):
    """v0.9-4a-2: 관찰 중인 고객 작업의 현재 상황 한 문장(조회 전용). 고정 문구 대신 실제 GameSession 상태에서 계산합니다.
    원인(경로 단절 등)은 말하지 않고 작업 상태만 말하므로 Stage 5의 장애 표시 숨김과 충돌하지 않습니다."""
    o = observation
    n = o.network
    if o.phase == 'finished':
        if o.tone == 'done':
            return ('고객 작업은 이미 정상 완료되었습니다. 지금 보이는 결과는 작업이 끝난 뒤의 네트워크 상태'
                    + (' (주 경로 단절 · 백업 경로 우회 중)' if n.rerouted else '') + '입니다.')
        return '고객 작업은 실패로 종료되었습니다. 지금 보이는 결과는 사건이 끝난 뒤의 네트워크 상태입니다.'
    if o.phase in ('incident', 'paused'):
        return '고객 작업이 멈췄습니다. 고객 연동 단말(sg-edge)에서 AIDC 서버까지의 통신 상태를 직접 조사하세요.'
    if o.phase == 'recovering':
        return '장애 조치 뒤 복구 준비 중입니다. 조치 전과 무엇이 달라졌는지 직접 관측해 보세요.'
    if o.phase == 'running':
        if n.recovered_by:
            return '장애 조치가 끝나 고객 작업이 정상 실행 중입니다. 조치 전과 무엇이 달라졌는지 직접 관측해 보세요.'
        return '고객 작업이 정상 실행 중이고 아직 장애가 없습니다. 정상 상태의 결과를 기준으로 관측해 둘 수 있습니다.'
    return '고객 작업이 아직 배정되지 않았습니다. 관제실에서 배정하면 작업 데이터가 오가기 시작합니다.'


def lab_support(session, rid=None):
    """Lab을 열 수 있으면 빈 문자열, 아니면 이유. 조회 전용이며 상태를 바꾸지 않습니다."""
    return lab_mode(session, rid)[1]


def _segments(primary_up, rerouted):
    """구조도와 터미널이 함께 쓰는 구간 상태. 고객 단말~라우터와 AIDC 내부 구간은 이 미션에서 항상 정상입니다."""
    return {'edge-primary': 'up', 'primary-wan': 'up' if primary_up else 'down',
            'edge-backup': 'up', 'backup-wan': 'active' if rerouted else 'standby',
            'gateway-servers': 'up'}


def observe(session, rid=None):
    """현재 세션 상태에서 관찰 결과를 만듭니다. 세션·원장·DB를 변경하지 않습니다."""
    rid = session.selected_id if rid is None else rid
    run = session.runs[rid]
    s = run.state
    allocation = session.servers.allocations.get(run.playthrough_id) if s.allocated else None
    job_parts = {part.server_id: part for part in allocation.slices} if allocation else {}
    owners_by_pid = {r.playthrough_id: customer_code(r.mission['country'])
                     for r in session.runs.values() if r.state.allocated}
    servers = []
    for spec in SERVERS:
        slots, owners, gpu_used, power_used = [None]*spec.gpu, [], 0, 0
        for pid, alloc in session.servers.allocations.items():
            for part in alloc.slices:
                if part.server_id != spec.key:
                    continue
                code = owners_by_pid.get(pid, 'x')
                owners.append(code)
                gpu_used, power_used = gpu_used+part.gpu, power_used+part.power
                for slot in part.gpu_slots:
                    slots[slot] = (code, pid == run.playthrough_id and allocation is not None)
        part = job_parts.get(spec.key)
        health = session.servers.hardware[spec.key]
        servers.append(ServerView(
            spec.key, spec.name, LAB_NETWORK['servers'][spec.key], health.state, health.repair_left,
            spec.gpu, spec.power, gpu_used, power_used, part.gpu if part else 0, part.power if part else 0,
            tuple(SlotView(i, v[0] if v else None, bool(v and v[1])) for i, v in enumerate(slots)),
            tuple(dict.fromkeys(owners))))
    network = NetworkView(
        primary_up=s.primary_up, backup_up=True, rerouted=s.rerouted, link_ok=s.link_ok,
        active_path='backup' if s.rerouted else 'primary', needed=s.network_needed, available=s.network_available,
        backup_capacity=s.backup_capacity, incident_kind=s.incident_kind, incident_occurred=s.incident_occurred,
        recovered_by=s.recovered_by, recovery_left=s.recovery_left if s.phase == 'recovering' else 0,
        downtime=s.downtime, attempts=s.response_attempts, responses=tuple(s.response_log),
        segments=_segments(s.primary_up, s.rerouted))
    if s.phase == 'finished':
        phase_label, tone = ('완료', 'done') if s.succeeded else ('실패', 'failed')
    else:
        phase_label, tone = PHASE_LABELS.get(s.phase, (s.phase, 'idle'))
    if s.incident_kind and not s.link_ok:
        incident = '주 통신 경로 DOWN · 데이터 전송 불가'
    elif s.incident_kind and s.recovered_by:
        incident = '장애 조치 완료 · 백업 경로 사용 중' if s.rerouted else '장애 조치 완료'
    elif s.incident_kind:
        incident = '네트워크 장애 · 원인 확인 필요'
    else:
        incident = '장애 없음'
    if s.phase == 'recovering' and s.recovery_left:
        recovery = f'복구 준비 {s.recovery_left}분 남음'
    elif s.recovered_by and s.phase == 'running':
        recovery = '정상 실행 재개'
    elif s.phase in ('incident', 'paused'):
        recovery = f'중단 {s.downtime}/60분 · 대응 {s.response_attempts}/3회'
    else:
        recovery = '-'
    plan = s.plans[s.plan]['label'] if s.plan else '미선택'
    return LabObservation(
        minute=session.minute, time_label=session.time_label, request_id=rid, playthrough_id=run.playthrough_id,
        customer=run.mission['company_name'], country=run.mission['country'], code=customer_code(run.mission['country']),
        task=run.mission['title'], scenario=s.scenario, phase=s.phase, phase_label=phase_label, tone=tone,
        progress=round(s.progress, 1), plan_label=plan, gpu_used=s.gpu_used if s.allocated else 0,
        power_used=s.power_used if s.allocated else 0, job_servers=tuple(job_parts), servers=tuple(servers),
        network=network, incident_label=incident, recovery_label=recovery)


@dataclass
class LabLearningTrace:
    """Lab 안에서만 쓰는 학습 기록(메모리 전용, 저장하지 않음). 게임 운영 점수와 분리합니다.
    향후 독립 진단·숙련 평가를 연결할 때 '어떤 도움 수준에서 무엇을 관찰했는가'를 담는 자리입니다."""
    level: str = 'beginner'
    entries: list = field(default_factory=list)

    def record(self, via, line, ok, time_label):
        self.entries.append({'level': self.level, 'via': via, 'line': line, 'ok': ok, 'time': time_label})
