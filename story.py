"""Chapter 1 교육 흐름. 실제 업무 규칙과 점수는 기존 세션을 사용합니다."""
from dataclasses import dataclass, field, asdict


LEGACY_STEPS = ('server', 'resources', 'request', 'allocation', 'time', 'complete')
STEPS = ('arrival', 'server', 'resources', 'request', 'preview', 'allocation',
         'time', 'operations', 'work_complete', 'complete')
SPEAKERS = {'player': '나 · 신입 엔지니어', 'mentor': '교육 담당자 · 선배 엔지니어',
            'customer': '고객', 'system': '시스템 · AIDC 운영 알림'}


@dataclass(frozen=True)
class Dialogue:
    role: str
    text: str

    def page(self):
        return SPEAKERS[self.role], self.text


GUIDES = {
    'arrival': ('첫 출근 안내를 읽고 업무를 시작하세요.', [
        Dialogue('player', '여기가 오늘부터 일하게 된 울산 AIDC구나. 생각했던 것보다 규모가 훨씬 크네.'),
        Dialogue('mentor', '안녕하세요. 오늘부터 함께 근무하실 신입분 맞으시죠? 운영팀에 오신 것을 환영합니다. 저는 선임 엔지니어입니다.'),
        Dialogue('player', '안녕하세요. 잘 부탁드립니다! 데이터센터 운영은 처음이라 조금 긴장되네요.'),
        Dialogue('mentor', '하나씩 함께 해 보면 됩니다. [첫 업무 시작]을 누르고 서버실부터 둘러볼까요?')]),
    'server': ('Server A를 클릭하여 장비 정보를 확인하세요.', [
        Dialogue('mentor', '먼저 중앙 서버실에서 Server A를 선택해 보세요. 오른쪽 서버 Inspector에서 장비 정보를 확인할 수 있습니다.')]),
    'resources': ('Inspector의 [GPU·전력 정보 확인]을 눌러 두 자원을 확인하세요.', [
        Dialogue('mentor', 'Server A의 장비 정보가 오른쪽 Inspector에 표시되었습니다. GPU는 AI 연산을 수행하는 장비이고, 전력은 서버 운영에 필요한 공급 용량입니다.'),
        Dialogue('mentor', 'GPU는 개별 반도체 모듈로, 전력은 가용량 게이지로 표시합니다. GPU가 남아 있어도 전력이 부족하면 작업을 시작할 수 없으니 둘 다 확인해야 합니다.'),
        Dialogue('system', 'Server A: GPU 4개 · 전력 4단위. Inspector에서 두 자원을 확인한 뒤 [자원 정보 확인]을 눌러 주세요.')]),
    'request': ('AIDC LINK에서 Merlion AI의 작업 조건·완료 기한을 확인하세요.', [
        Dialogue('system', '새로운 고객 요청이 AIDC LINK에 도착했습니다.'),
        Dialogue('mentor', '마침 좋은 타이밍이네요. 싱가포르 Merlion AI에서 AI 학습 작업을 요청했어요. AIDC LINK의 [요청 확인]을 눌러 작업 조건과 기한을 직접 읽어 보시겠어요?')]),
    'preview': ('배정 미리보기 또는 배정 계획 비교 창에서 계획을 검토하세요.', [
        Dialogue('mentor', '고객은 GPU 7개를 요청했지만 한 서버에는 최대 4개만 있습니다. 여러 서버의 GPU와 전력을 조합해야 합니다.'),
        Dialogue('mentor', '오른쪽 [배정 미리보기] 탭을 열거나 [배정 계획 비교·선택]을 눌러 추천안과 대안을 확인해 보세요. 여기서는 아직 실제로 배정하지 않고 사용량과 잔여량을 비교합니다.')]),
    'allocation': ('검토한 배정 계획으로 실제 고객 작업을 시작하세요.', [
        Dialogue('mentor', '[배정하고 작업 시작] 또는 비교 창의 시작 버튼을 눌러 주세요. 자동 추천을 사용해도 됩니다. 원래 요청 조건이나 고객이 동의한 조건을 지켜야 합니다.'),
        Dialogue('system', '미리보기나 계획 선택만으로는 자원을 점유하지 않습니다. 실제 작업을 시작한 뒤 랙의 SG 코드와 점유 색상, 전력 사용량을 확인하세요.')]),
    'time': ('+10분 버튼으로 실제 작업 진행률을 높이세요.', [
        Dialogue('mentor', '좋아요. 서버에 GPU가 배정됐네요. SG 코드와 밝은 청록색 모듈이 보이시죠? 지금은 싱가포르 고객이 해당 장비를 사용하고 있다는 뜻입니다.'),
        Dialogue('mentor', '배정 직후 진행률 0%는 정상입니다. 아래 [+10분]을 눌러 실제 작업이 진행되는지 확인해 보세요.')]),
    'operations': ('예상 완료 시각·고객 기한·서버별 잔여 자원을 확인하세요.', [
        Dialogue('mentor', '작업량이 늘었네요. 진행률과 예상 완료 시각, 고객 기한을 함께 확인해 보세요. 서버별 남은 GPU와 전력도 중요합니다.'),
        Dialogue('mentor', '나중에는 여러 고객의 요청이나 네트워크 장애에도 대응하게 됩니다. 지금은 첫 업무에 집중하겠습니다. 아래 현재 운영 정보를 읽고 [운영 상태 확인]을 눌러 주세요.')]),
    'work_complete': ('가상 시간 버튼으로 첫 고객 업무를 정상 완료하세요.', [
        Dialogue('mentor', '이제 시간 버튼으로 첫 업무를 끝까지 진행해 보세요. 실제 작업이 정상 완료되었을 때만 첫 업무 완료로 기록합니다.'),
        Dialogue('system', '완료 상태와 고객 완료 안내, GPU·전력 반환, 서버의 IDLE 상태, 실제 운영 점수를 확인하게 됩니다.')]),
    'complete': ('Chapter 1 완료 · 완료 화면에서 다음 행동을 선택하세요.', [
        Dialogue('mentor', '첫 업무를 성공적으로 마쳤네요. 처음에는 GPU와 전력 배정만으로도 복잡해 보이지만, 조금씩 익숙해질 겁니다.'),
        Dialogue('mentor', '다음에는 여러 고객의 요청이 동시에 들어오거나 네트워크에 장애가 발생하는 상황도 경험하게 될 거예요.'),
        Dialogue('system', '현재 제공되는 스토리는 Chapter 1까지입니다. Chapter 2는 이후 개발 예정입니다. 완료 화면에서 모드 선택이나 자유 운영으로 이동할 수 있습니다.')]),
}


@dataclass
class StoryProgress:
    chapter: int = 1
    step: str = 'arrival'
    completed_steps: list[str] = field(default_factory=list)
    tutorial_completed: bool = False
    skipped: bool = False
    mission_status: str = 'pending'
    first_work_completed: bool = False
    request_id: int | None = None
    selected_server: str | None = None
    resources_confirmed: bool = False
    request_read: bool = False
    progress_version: int = 2
    introduction_confirmed: bool = False
    preview_confirmed: bool = False
    operations_confirmed: bool = False
    chapter_completed: bool = False
    legacy_progress: bool = False
    legacy_tutorial_completed: bool = False
    dialogue_seen: list[str] = field(default_factory=list)

    def __post_init__(self):
        flags = (self.tutorial_completed, self.skipped, self.first_work_completed, self.resources_confirmed,
                 self.request_read, self.introduction_confirmed, self.preview_confirmed,
                 self.operations_confirmed, self.chapter_completed, self.legacy_progress,
                 self.legacy_tutorial_completed)
        if (type(self.chapter) is not int or self.chapter != 1 or type(self.progress_version) is not int or self.progress_version != 2
                or self.step not in STEPS or not isinstance(self.completed_steps, list)
                or self.completed_steps != list(STEPS[:len(self.completed_steps)])
                or any(type(v) is not bool for v in flags)
                or self.mission_status not in ('pending', 'running', 'completed', 'closed')
                or (self.request_id is not None and (type(self.request_id) is not int or self.request_id < 1))
                or self.selected_server not in (None, 'A', 'B', 'C', 'D')):
            raise ValueError('저장된 스토리 진행 상태가 올바르지 않습니다.')
        if (not isinstance(self.dialogue_seen, list)
                or any(not isinstance(key, str) or key not in (*STEPS, 'closed', 'skipped') for key in self.dialogue_seen)
                or len(set(self.dialogue_seen)) != len(self.dialogue_seen)):
            raise ValueError('저장된 대화 표시 이력이 올바르지 않습니다.')
        expected = STEPS[min(len(self.completed_steps), len(STEPS)-1)]
        if (self.step != expected
                or self.tutorial_completed != (len(self.completed_steps) == len(STEPS) or self.legacy_tutorial_completed)
                or (self.skipped and not self.tutorial_completed)
                or (self.legacy_tutorial_completed and not self.legacy_progress)
                or self.first_work_completed != (self.mission_status == 'completed')
                or self.chapter_completed != self.first_work_completed):
            raise ValueError('저장된 스토리 단계와 완료 기록이 일치하지 않습니다.')

    @classmethod
    def from_payload(cls, payload, run, plan_agreed):
        if 'progress_version' in payload:
            data = dict(payload)
            # v0.9-1a에는 표시 이력이 없습니다. 지난 장면은 다시 자동 재생하지 않습니다.
            data.setdefault('dialogue_seen', list(data.get('completed_steps', [])))
            result = cls(**data)
            succeeded = bool(run.state.phase == 'finished' and run.state.succeeded and run.request['status'] == 'completed')
            if result.chapter_completed != succeeded:
                raise ValueError('스토리 완료 기록과 실제 고객 업무 상태가 일치하지 않습니다.')
            return result
        old = dict(payload)
        completed = old.get('completed_steps', [])
        if (not isinstance(completed, list) or completed != list(LEGACY_STEPS[:len(completed)])
                or old.get('step') != LEGACY_STEPS[min(len(completed), len(LEGACY_STEPS)-1)]
                or type(old.get('tutorial_completed')) is not bool
                or old['tutorial_completed'] != (len(completed) == len(LEGACY_STEPS))
                or any(type(old.get(key, False)) is not bool for key in
                       ('skipped', 'first_work_completed', 'resources_confirmed', 'request_read'))
                or (old.get('skipped') and not old['tutorial_completed'])
                or old.get('first_work_completed', False) != (old.get('mission_status') == 'completed')):
            raise ValueError('이전 스토리 진행 기록이 올바르지 않습니다.')
        old.pop('step'); old.pop('completed_steps')
        result = cls(**{**old, 'tutorial_completed':False, 'skipped':False,
                       'first_work_completed':False, 'mission_status':'pending'},
                     introduction_confirmed=True, legacy_progress=True)
        result.legacy_tutorial_completed = bool(old['tutorial_completed'] and not old.get('skipped'))
        if old.get('skipped'):
            result.skip()
        result.update(run, plan_agreed)
        result.dialogue_seen = list(result.completed_steps)
        return result

    def payload(self):
        return asdict(self)

    @property
    def dialogue_event(self):
        if self.chapter_completed:
            return 'complete'
        if self.mission_status == 'closed':
            return 'closed'
        return 'skipped' if self.skipped else self.step

    @property
    def objective(self):
        if self.chapter_completed:
            return GUIDES['complete'][0]
        if self.mission_status == 'closed':
            return '첫 요청이 종료되었습니다. 교육 복습 또는 모드 선택을 이용하세요.'
        if self.skipped:
            return 'Merlion AI 업무를 직접 진행하세요. · Chapter 1'
        return GUIDES[self.step][0]

    @property
    def dialogue(self):
        if self.chapter_completed:
            return GUIDES['complete'][1]
        if self.mission_status == 'closed':
            return [Dialogue('mentor', '이번 요청은 정상 완료하지 못했네요. 고객 조건과 운영 상태를 복습하면서 무엇이 달랐는지 함께 확인해 봅시다.'),
                    Dialogue('system', '첫 고객 요청이 종료되었습니다. 정상 완료한 업무로 기록하지 않습니다. 교육을 복습하거나 모드 선택으로 이동할 수 있습니다.')]
        if self.skipped:
            return [Dialogue('system', '튜토리얼 안내를 건너뛰었습니다. 스토리 모드는 유지됩니다. 고객 요청 확인 → 조건에 맞는 배정 → 시간 진행으로 직접 업무를 완료하세요.')]
        return GUIDES[self.step][1]

    @property
    def guide(self):
        return [line.text for line in self.dialogue]

    def update(self, run, plan_agreed):
        s = run.state
        started = bool(run.playthrough_id and run.server_allocations and plan_agreed)
        succeeded = bool(s.phase == 'finished' and s.succeeded and run.request['status'] == 'completed')
        if succeeded:
            self.mission_status, self.first_work_completed, self.chapter_completed = 'completed', True, True
        elif run.request['status'] == 'rejected' or (s.phase == 'finished' and run.followup_closed):
            self.mission_status = 'closed'
        elif started:
            self.mission_status = 'running'
        if self.skipped:
            return
        facts = (self.introduction_confirmed, self.selected_server == 'A', self.resources_confirmed,
                 self.request_read, self.preview_confirmed or (self.legacy_progress and started),
                 started, started and s.work_done > 0,
                 self.operations_confirmed or self.legacy_tutorial_completed, succeeded, succeeded)
        for index, key in enumerate(STEPS):
            if key in self.completed_steps:
                continue
            if not facts[index]:
                break
            self.completed_steps.append(key)
        self.tutorial_completed = len(self.completed_steps) == len(STEPS) or self.legacy_tutorial_completed
        self.step = STEPS[min(len(self.completed_steps), len(STEPS)-1)]

    def skip(self):
        self.completed_steps = list(STEPS)
        self.step, self.tutorial_completed, self.skipped = 'complete', True, True
