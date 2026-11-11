"""v0.9-4a-1 심화 연수(Stage 1~5) 진행 모델. GUI/SQLite와 독립입니다.

Chapter = 고객 업무·장애 사건·운영 미션, Stage = 같은 시스템을 얼마나 깊이 이해하고 어떤 방식으로 해결하는가.
Stage 통과는 탭 열기·버튼 클릭이 아니라 기록된 학습 행동(구간 선택·명령 실행 결과·답변)과 실제 게임 상태(복구 여부)로만
판정합니다. 저장은 스토리 JSON의 선택 필드 `training`으로만 합니다(SQL 변경 없음).

- 정규 연수(practice=False): Stage를 순서대로 엽니다. 현재 Stage를 통과해야 [다음 Stage 시작]이 가능하고, 완료한 Stage는 복습만 합니다.
- 연습(practice=True, [Engineering Lab 연습] 슬롯): 모든 Stage를 자유롭게 고를 수 있지만 정규 통과로 기록하지 않습니다.
- Stage 5는 이미 경험한 경로 단절 사건을 재사용한 **독립 진단 흐름의 시연용 골격**이며 숙련도 인증이 아닙니다.
"""
from dataclasses import dataclass, field

from lab_model import LAB_NETWORK

STAGES = ('structure', 'tool', 'assemble', 'terminal', 'independent')
EVENTS_T = tuple('t_'+key for key in STAGES) + ('t_done',)
TRAINING_SCENARIO = 'ch3_path'
TRAINING_COUNTRY = '싱가포르'
RECORD_LIMIT = 40
ROUTER_ADDRESSES = tuple(r['address'] for r in LAB_NETWORK['routers'].values())
REMOTE_ADDRESSES = tuple(LAB_NETWORK['servers'].values()) + (LAB_NETWORK['aidc_gateway']['address'],)
SERVER_ADDRESSES = tuple(LAB_NETWORK['servers'].values())
# Stage별로 학습 행동을 받는 입력 방식. 구조 관찰(Stage 1)은 구조도 구간 선택과 답변만 받습니다.
SOURCES = {'tool': 'choice', 'assemble': 'blocks', 'terminal': 'terminal', 'independent': 'terminal'}

STAGE_INFO = {
    'structure': {
        'no': 1, 'title': '시스템 구조를 관찰하다', 'short': '시스템 구조 관찰', 'tab': '네트워크 구조',
        'goal': '네트워크 구조도에서 끊어진 구간을 직접 클릭하고, 그 구간이 고객 통신에 주는 영향을 고르세요.',
        'intro': (('mentor', '지금까지는 관제실에서 장애를 처리했죠. 이제 장비가 실제로 어떻게 연결되어 있는지 살펴볼 차례예요.'),
                  ('player', '고객 단말, 라우터, 게이트웨이, 서버… 선으로 이어진 길을 따라가 보면 되겠네요.')),
        'done': '구조를 읽을 줄 알게 됐네요. 끊어진 구간 하나가 고객 작업 전체를 멈출 수 있다는 걸 확인했어요.'},
    'tool': {
        'no': 2, 'title': '진단 도구를 선택하다', 'short': '진단 도구 선택', 'tab': '명령어 학습',
        'goal': '"서버까지 통신할 수 있는지" 확인할 도구를 고르고, 그 결과만으로 확정할 수 있는 것을 답하세요.',
        'intro': (('mentor', '문제가 어디서 생겼는지 짐작할 수 있게 됐어요. 이번에는 그 판단을 확인할 도구를 배워 봅시다.'),),
        'done': '도구마다 답할 수 있는 질문이 다르다는 걸 알았네요. ping은 응답 여부를 알려 주지만 원인까지 말해 주지는 않아요.'},
    'assemble': {
        'no': 3, 'title': '명령어를 조립하다', 'short': '명령어 조립', 'tab': '명령어 학습',
        'goal': 'ping에 보낼 횟수 옵션(-c)과 서버 주소를 붙여 실제 명령 한 줄을 조립·실행하고, 결과의 응답 수를 확인하세요.',
        'intro': (('mentor', '이제 명령어 이름을 알았어요. 실제로 쓰려면 옵션과 대상도 알아야 해요.'),),
        'done': '명령 · 옵션 · 대상의 순서가 실제 문법이에요. 출력에서 숫자를 읽어 낸 것도 잘했어요.'},
    'terminal': {
        'no': 4, 'title': '직접 명령어를 입력하다', 'short': '터미널 직접 입력', 'tab': '가상 터미널',
        'goal': '가상 터미널에 직접 입력해 가까운 네트워크 장비, 원격 서버, 라우팅 정보를 관측하고, 알 수 있는 사실과 아직 확정할 수 없는 사실을 구별하세요.',
        'intro': (('mentor', '이제 제가 명령어를 골라 주지 않아요. 무엇을 확인할지 스스로 생각하고 직접 입력해 보세요.'),
                  ('player', '틀려도 다시 입력하면 되는 거죠? 출력부터 차분히 읽어 볼게요.')),
        'done': '증거를 모으는 것과 결론을 내리는 것은 달라요. 확인된 사실과 추측을 나눈 게 오늘의 핵심이에요.'},
    'independent': {
        'no': 5, 'title': '독립 진단 시연', 'short': '독립 진단', 'tab': '가상 터미널',
        'goal': '장애 증상만 주어집니다. 직접 관측해 원인을 판단하고, 관제실에서 조치한 뒤, 같은 관측으로 정상화를 재확인하세요.',
        'intro': (('mentor', '이제 장애 상황만 알려 드릴게요. 필요한 정보는 직접 확인하고, 대응한 다음 정상화 여부까지 검증해 보세요.'),
                  ('system', '이 Stage는 이미 경험한 경로 단절 사건을 재사용한 독립 진단 흐름의 시연입니다. 처음 보는 장애에 대한 숙련도 인증이 아닙니다.')),
        'done': '관찰 → 판단 → 조치 → 검증을 혼자 끝까지 해냈어요. 다음에는 원인을 미리 모르는 새 장애로 연습하게 될 거예요.'},
}
START_INTRO = (('mentor', '기초 교육을 마쳤네요. 관제실 운영에는 이제 익숙해졌을 거예요.'),
               ('mentor', '오늘부터는 심화 연수예요. 버튼 너머 시스템 내부를 다섯 단계로 깊이 들여다볼 거예요.'),
               ('system', '연수용 고객 요청이 접수됩니다. 배정하고 시간을 진행해 장애가 발생하면 [Engineering Lab]에서 Stage 1을 시작하세요.'))
RESULT_OUTRO = ('구조 관찰 · 도구 선택 · 명령 조립 · 직접 입력 · 독립 진단까지 같은 사건으로 단계별로 연습했어요. '
                '다음 전문 과정에서는 원인을 미리 알 수 없는 새 장애와 더 많은 관측 도구를 다룰 예정이에요(아직 미구현).')

QUESTIONS = {
    ('structure', 'impact'): {
        'prompt': '선택한 구간이 끊기면 고객 통신에는 어떤 일이 생길까요?',
        'options': (('blocked', '고객 단말이 보낸 작업 데이터가 AIDC 서버에 도달하지 못해 작업이 멈춘다'),
                    ('gpu', '서버의 GPU가 고장 나 연산이 멈춘다'),
                    ('local', '고객 단말의 네트워크 인터페이스가 꺼진다')),
        'correct': 'blocked'},
    ('tool', 'limit'): {
        'prompt': 'ping 결과만으로 확정할 수 있는 것은 무엇일까요?',
        'options': (('icmp', '대상까지 ICMP 응답이 오가는지 여부'),
                    ('cause', '응답이 없을 때 그 정확한 원인(회선 단절인지 장비 정지인지)'),
                    ('app', '고객 작업(애플리케이션)이 정상인지')),
        'correct': 'icmp'},
    ('independent', 'cause'): {
        'prompt': '관측한 증거로 볼 때 가장 타당한 원인은 무엇인가요?',
        'options': (('path_down', '주 통신 경로 단절 (가까운 라우터 너머 구간)'),
                    ('bandwidth', '가용 대역폭 부족 (경로는 연결됨)'),
                    ('server', '서버 장비 장애'),
                    ('local', '고객 단말의 인터페이스 장애'))},
}


def evidence_kind(result):
    """명령 결과의 관측 종류: near(가까운 라우터 ping) · remote(AIDC 쪽 ping) · route · addr · None."""
    if not result.ok or result.kind != 'output':
        return None
    if result.command == 'ping':
        target = result.facts.get('target')
        if target in ROUTER_ADDRESSES:
            return 'near'
        if target in REMOTE_ADDRESSES:
            return 'remote'
        return None
    return {'ip route': 'route', 'ip addr': 'addr'}.get(result.command)


def make_record(rid, source, result, observation):
    """저장할 학습 행동 한 건. 출력 전체가 아니라 판정에 필요한 사실만 남깁니다."""
    facts = result.facts
    return {'rid': rid, 'source': source, 'line': result.line[:120], 'ok': result.ok, 'command': result.command,
            'kind': evidence_kind(result), 'target': facts.get('target'), 'count': facts.get('transmitted'),
            'received': facts.get('received'), 'via': facts.get('aidc_via'),
            'link_ok': observation.network.link_ok, 'minute': observation.minute,
            'explicit_count': not facts.get('default_count', True) if result.command == 'ping' else None}


@dataclass
class TrainingProgress:
    request_ids: list[int]
    practice: bool = False
    current: str = 'structure'
    completed: list[str] = field(default_factory=list)
    actions: dict = field(default_factory=dict)    # stage -> [기록]
    answers: dict = field(default_factory=dict)    # stage -> {질문: {'answer', 'correct', 'attempts', 'rid'}}
    progress_version: int = 1

    def __post_init__(self):
        if (not isinstance(self.request_ids, list) or not self.request_ids
                or any(type(v) is not int or v < 1 for v in self.request_ids)
                or len(set(self.request_ids)) != len(self.request_ids)
                or type(self.practice) is not bool or self.current not in STAGES
                or type(self.progress_version) is not int or self.progress_version != 1
                or not isinstance(self.completed, list) or any(k not in STAGES for k in self.completed)
                or len(set(self.completed)) != len(self.completed)
                or not isinstance(self.actions, dict) or any(k not in STAGES or not isinstance(v, list) for k, v in self.actions.items())
                or not isinstance(self.answers, dict) or any(k not in STAGES or not isinstance(v, dict) for k, v in self.answers.items())):
            raise ValueError('저장된 심화 연수 진행 상태가 올바르지 않습니다.')
        if not self.practice:
            # 정규 연수는 앞 Stage부터 순서대로만 완료되고, 현재 Stage는 완료한 Stage 바로 다음(또는 마지막 완료 Stage)입니다.
            index = STAGES.index(self.current)
            if (self.completed != list(STAGES[:len(self.completed)])
                    or not len(self.completed)-1 <= index <= len(self.completed)
                    or index > len(STAGES)-1):
                raise ValueError('저장된 정규 심화 연수의 Stage 순서가 올바르지 않습니다.')

    # ── 조회 ─────────────────────────────────────────
    @property
    def rid(self):
        return self.request_ids[-1]

    @property
    def done(self):
        return set(self.completed) == set(STAGES)

    @property
    def completed_count(self):
        return len(self.completed)

    def stage_state(self, key):
        """completed / current / open(연습에서 자유 선택 가능) / locked."""
        if key in self.completed and key != self.current:
            return 'completed'
        if key == self.current:
            return 'current'
        return 'open' if self.practice else 'locked'

    def is_locked(self, key):
        return self.stage_state(key) == 'locked'

    def current_passed(self):
        return self.current in self.completed

    @property
    def next_stage(self):
        index = STAGES.index(self.current)
        return STAGES[index+1] if index+1 < len(STAGES) else None

    def can_advance(self):
        """정규: 현재 Stage를 통과했고 다음 Stage가 있을 때만 [다음 Stage 시작]."""
        return not self.practice and self.current_passed() and self.next_stage is not None

    def records(self, stage, rid=None):
        items = self.actions.get(stage, [])
        return [r for r in items if rid is None or r['rid'] == rid]

    def answer(self, stage, question, rid=None):
        item = self.answers.get(stage, {}).get(question)
        if item is None or (rid is not None and item.get('rid') != rid):
            return None
        return item

    def answered(self, stage, question, rid=None):
        item = self.answer(stage, question, rid)
        return bool(item and item['correct'])

    # ── 기록 ─────────────────────────────────────────
    def record(self, stage, record):
        items = [*self.actions.get(stage, []), record]
        self.actions = {**self.actions, stage: items[-RECORD_LIMIT:]}

    def record_answer(self, stage, question, answer, correct, rid):
        old = self.answers.get(stage, {}).get(question) or {}
        attempts = (old.get('attempts', 0) if old.get('rid') == rid or stage != 'independent' else 0) + 1
        # 한 번 맞힌 답은 이후 오답 시도로 지워지지 않습니다(통과는 되돌아가지 않음).
        keep = bool(old.get('correct')) and (old.get('rid') == rid or stage != 'independent')
        entry = {'answer': answer, 'correct': bool(correct) or keep, 'attempts': attempts, 'rid': rid}
        self.answers = {**self.answers, stage: {**self.answers.get(stage, {}), question: entry}}

    # ── 통과 판정(실제 기록과 게임 상태만 사용) ──────────
    def stage5_evidence(self, rid):
        """복구 전(경로가 끊긴 상태)에 직접 입력해 얻은 관측: 원격 대상 ping 1개 + 다른 관측 1개 이상."""
        before = [r for r in self.records('independent', rid) if r['ok'] and not r['link_ok'] and r['kind']]
        remote = [r for r in before if r['kind'] == 'remote']
        others = [r for r in before if r['kind'] in ('near', 'route', 'addr')]
        return bool(remote and others), before

    def stage5_verified(self, rid):
        """조치 뒤(경로가 살아난 상태) 같은 관측 도구로 원격 대상 응답을 다시 확인했는지."""
        return any(r['ok'] and r['link_ok'] and r['kind'] == 'remote' and r['received'] for r in self.records('independent', rid))

    def terminal_evidence(self):
        kinds = {r['kind'] for r in self.records('terminal') if r['source'] == 'terminal' and r['ok']}
        return {key: key in kinds for key in ('near', 'remote', 'route')}

    def last_record(self, stage, kind):
        return next((r for r in reversed(self.records(stage)) if r['ok'] and r['kind'] == kind), None)

    def valid_assembly(self):
        """Stage 3: 블록으로 조립해 실행한 ping 중 횟수 옵션과 서버(AIDC 쪽) 주소가 있는 마지막 실행."""
        return next((r for r in reversed(self.records('assemble')) if r['ok'] and r['source'] == 'blocks'
                     and r['command'] == 'ping' and r['explicit_count'] and r['kind'] == 'remote'), None)

    def passed(self, stage, state):
        if stage == 'structure':
            return self.answered('structure', 'segment') and self.answered('structure', 'impact')
        if stage == 'tool':
            return self.answered('tool', 'choice') and self.answered('tool', 'limit')
        if stage == 'assemble':
            return self.valid_assembly() is not None and self.answered('assemble', 'received')
        if stage == 'terminal':
            return all(self.terminal_evidence().values()) and self.answered('terminal', 'facts')
        rid = self.rid
        return bool(self.stage5_evidence(rid)[0] and self.answered('independent', 'cause', rid)
                    and state is not None and state.recovered_by and self.stage5_verified(rid))

    def update(self, state):
        """현재 Stage(연습은 모든 Stage)의 통과를 기록합니다. 완료 기록은 줄어들지 않습니다."""
        targets = [key for key in STAGES if key not in self.completed and (self.practice or key == self.current)]
        for key in targets:
            if self.passed(key, state):
                self.completed.append(key)
        if self.practice:
            self.completed.sort(key=STAGES.index)


def fact_statements(progress):
    """Stage 4 관측 정리: 직접 입력해 얻은 관측에서 '확인된 사실'을 만들고, 터미널만으로 확정할 수 없는 문장을 섞습니다."""
    near = progress.last_record('terminal', 'near')
    remote = progress.last_record('terminal', 'remote')
    route = progress.last_record('terminal', 'route')
    if not (near and remote and route):
        return []
    return [
        ('near', f'가까운 라우터({near["target"]})는 ping에 ' + ('응답했다' if near['received'] else '응답하지 않았다'), 'confirmed'),
        ('line_cut', '주 경로의 라우터 너머 회선이 물리적으로 끊어졌다', 'unknown'),
        ('remote', f'AIDC 쪽 대상({remote["target"]})에서 ping ' + ('응답이 왔다' if remote['received'] else '응답이 오지 않았다'), 'confirmed'),
        ('server_down', '서버 장비가 고장 나서 응답하지 않는다', 'unknown'),
        ('route', f'AIDC 네트워크로 가는 경로는 {route["via"]}로 설정되어 있다', 'confirmed'),
    ]


def received_options(record):
    """Stage 3 결과 확인 질문의 선택지: 실제 응답 수와 다른 후보."""
    return sorted({0, 1, record['count'], record['received']})
