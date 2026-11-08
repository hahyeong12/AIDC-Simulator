"""Chapter 1 교육 흐름. 실제 업무 규칙과 점수는 기존 세션을 사용합니다."""
from dataclasses import dataclass, field, asdict

from chapter2 import Chapter2Progress, EVENTS2


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
    'preview': ('[배정 계획 비교·선택]을 열어 배정안 하나를 직접 선택해 검토하세요.', [
        Dialogue('mentor', '고객은 GPU 7개를 요청했지만 한 서버에는 최대 4개만 있습니다. 여러 서버의 GPU와 전력을 조합해야 합니다.'),
        Dialogue('mentor', '오른쪽 [배정 미리보기] 탭에서 [배정 계획 비교·선택]을 눌러 비교 창을 열고, 배정안 1(추천)을 포함한 계획 중 하나를 직접 선택해 확인해 보세요. 탭을 여는 것만으로는 검토가 아닙니다. 여기서는 아직 실제로 배정하지 않고 사용량과 잔여량을 비교합니다.')]),
    'allocation': ('검토한 배정 계획으로 실제 고객 작업을 시작하세요.', [
        Dialogue('mentor', '[배정하고 작업 시작] 또는 비교 창의 시작 버튼을 눌러 주세요. 자동 추천을 사용해도 됩니다. 원래 요청 조건이나 고객이 동의한 조건을 지켜야 합니다.'),
        Dialogue('system', '미리보기나 계획 선택만으로는 자원을 점유하지 않습니다. 실제 작업을 시작한 뒤 랙의 SG 코드와 점유 색상, 전력 사용량을 확인하세요.')]),
    'time': ('시간 버튼(+10/+30/+60분) 중 하나로 실제 작업 진행률을 높이세요.', [
        Dialogue('mentor', '좋아요. 서버에 GPU가 배정됐네요. SG 코드와 밝은 청록색 모듈이 보이시죠? 지금은 싱가포르 고객이 해당 장비를 사용하고 있다는 뜻입니다.'),
        Dialogue('mentor', '배정 직후 진행률 0%는 정상입니다. 가상 시간을 진행해 볼까요? +10분은 상황을 자세히 확인할 때, +30분과 +60분은 작업 시간을 빠르게 진행할 때 사용합니다. 어느 버튼을 눌러도 괜찮습니다. 먼저 작업 진행률이 어떻게 변하는지 확인해 보세요.')]),
    'operations': ('예상 완료 시각·고객 기한·서버별 잔여 자원을 확인하세요.', [
        Dialogue('mentor', '작업량이 늘었네요. 진행률과 예상 완료 시각, 고객 기한을 함께 확인해 보세요. 서버별 남은 GPU와 전력도 중요합니다.'),
        Dialogue('mentor', '나중에는 여러 고객의 요청이나 네트워크 장애에도 대응하게 됩니다. 지금은 첫 업무에 집중하겠습니다. 아래 현재 운영 정보를 읽고 [운영 상태 확인]을 눌러 주세요.')]),
    'work_complete': ('가상 시간 버튼으로 첫 고객 업무를 정상 완료하세요.', [
        Dialogue('mentor', '이제 시간 버튼으로 첫 업무를 끝까지 진행해 보세요. 실제 작업이 정상 완료되었을 때만 첫 업무 완료로 기록합니다.'),
        Dialogue('system', '완료 상태와 고객 완료 안내, GPU·전력 반환, 서버의 IDLE 상태, 실제 운영 점수를 확인하게 됩니다.')]),
    'complete': ('Chapter 1 완료 · 완료 화면에서 다음 행동을 선택하세요.', [
        Dialogue('mentor', '첫 업무를 성공적으로 마쳤네요. 처음에는 GPU와 전력 배정만으로도 복잡해 보이지만, 조금씩 익숙해질 겁니다.'),
        Dialogue('mentor', '다음에는 여러 고객의 요청이 동시에 들어오거나 네트워크에 장애가 발생하는 상황도 경험하게 될 거예요.'),
        Dialogue('system', '완료 화면에서 [Chapter 2 시작]으로 여러 고객의 요청을 다루는 다음 미션을 시작하거나, 모드 선택이나 자유 운영으로 이동할 수 있습니다.')]),
}


# Chapter 2: 선배는 개념만 설명하고 판단은 플레이어에게 맡깁니다. 정답 배정안은 알려 주지 않습니다.
GUIDES2 = {
    'briefing': ('선배의 Chapter 2 브리핑을 읽고 확인하세요.', [
        Dialogue('mentor', '오늘은 고객 요청이 한꺼번에 들어왔습니다. 일본 고객은 로봇 추론 작업의 완료 기한이 촉박하고, 미국 고객은 데이터 분석을 위해 많은 GPU를 요구하고 있어요.'),
        Dialogue('mentor', '이번에는 고객이 두 곳입니다. 작업을 시작하기 전에 두 고객의 GPU·전력 요구량과 기한을 모두 확인해 보세요.'),
        Dialogue('mentor', '두 작업을 모두 원래 조건대로 동시에 실행하기는 어려울 수 있습니다. 서버 자원은 한정되어 있고, 먼저 배정한 작업이 남는 자원을 줄이니까요.'),
        Dialogue('mentor', '어떤 작업을 먼저 처리할지, 서버 자원을 어떻게 남겨둘지 판단해 보세요. 정답은 알려 드리지 않을게요. 고객 동의 없이 원래 조건을 바꿀 수는 없습니다. 준비가 되면 브리핑을 확인하고 AIDC LINK에서 두 요청을 열어 보세요.')]),
    'requests': ('AIDC LINK에서 일본·미국 두 요청의 GPU·전력·완료 기한·모드별 처리 시간을 모두 읽으세요.', [
        Dialogue('mentor', '두 요청서의 GPU와 전력 요구량, 완료 기한, 고객이 허용한 운영 모드, 모드별 처리 시간을 읽고 비교해 보세요. 절약형이 허용되는 고객이라도 처리 시간은 길어집니다.')]),
    'review': ('[배정 계획 비교·선택]에서 두 요청의 배정안을 각각 비교하고 선택해 보세요.', [
        Dialogue('mentor', '배정 계획 비교창에서 서버별 잔여량을 살펴보세요. 한 서버에 모으는 안과 여러 서버에 나누는 안은 남는 자원이 다릅니다.'),
        Dialogue('system', '비교창에는 모드별 완료 예상, 두 고객의 원래 요청을 동시에 실행할 수 있는지, 선택한 안이 다른 요청의 배정 가능 여부를 어떻게 바꾸는지가 현재 자원 기준으로 표시됩니다. 선택만으로는 자원을 점유하지 않습니다.')]),
    'allocate': ('두 요청을 직접 판단해 처리하세요. 배정·대기·협의·거절 모두 선택할 수 있습니다.', [
        Dialogue('mentor', '이제 결정할 차례입니다. 어느 요청을 먼저, 어떤 모드와 배정안으로 시작할지는 여러분의 판단이에요. 기다리는 동안에도 시간은 흐르고, 최종 배정 기한까지 시작하지 못한 요청은 철회될 수 있습니다.')]),
    'progress': ('시간 버튼으로 작업 진행률과 남은 자원, 고객 기한을 확인하세요.', [
        Dialogue('mentor', '시간을 진행해서 작업이 실제로 늘어나는지 확인해 보세요. 서버 랙의 고객 색상으로 누가 어떤 GPU를 쓰는지 볼 수 있습니다. 작업이 끝나면 자원이 반환되어 대기 중인 요청을 시작할 수 있어요.')]),
    'finish': ('두 요청이 모두 끝날 때까지 시간을 진행하세요.', [
        Dialogue('mentor', '완료된 작업의 GPU와 전력은 반환됩니다. 두 작업이 끝날 때까지 기한과 남은 자원을 보면서 진행해 주세요.')]),
    'done': ('Chapter 2 종료 · 결과 화면에서 미션 평가를 확인하세요.', [
        Dialogue('system', '두 고객의 요청이 모두 끝났습니다. 결과 화면에서 미션 성공 여부와 고객별 점수, 종합 평가, 배정 위치, 반환된 자원을 확인할 수 있습니다.')]),
}

GUIDES2_FAILED_DONE = ('Chapter 2 종료 · 미션 실패 · 결과 화면에서 원인과 평가를 확인하세요.', [
    Dialogue('mentor', '두 요청은 모두 끝났지만, 이번 미션의 목표인 두 고객의 기한 내 정상 처리는 달성하지 못했습니다.'),
    Dialogue('system', '결과 화면에서 고객별 점수와 종합 평가, 실패 원인을 확인하고 [Chapter 2 다시 도전]으로 새로 시작할 수 있습니다.')])


def chapter2_failure_pages(failure):
    """저장된 실패 기록의 사실만으로 선배 피드백을 만듭니다. 원인을 알 수 없으면 원인 문장을 쓰지 않습니다."""
    who = failure['country']
    reason = failure['reason']
    first = {
        'expired': f'{who} 고객의 요청이 결국 철회됐습니다. 최종 배정 기한({failure.get("expiry")})까지 작업을 시작하지 못했습니다.',
        'rejected': f'{who} 고객의 요청을 거절하셨네요. 이 요청은 더 이상 처리되지 않습니다.',
        'failed': f'{who} 고객의 작업이 중단되어 더 이상 정상 완료할 수 없습니다.',
        'late': f'{who} 고객의 작업이 완료 기한({failure.get("due")})을 {failure.get("late_minutes")}분 넘겨 끝났습니다.',
        'late_certain': f'{who} 고객의 작업은 이제 어떤 방법으로도 완료 기한({failure.get("due")}) 안에 끝낼 수 없게 됐습니다.'
                        + (f' 가장 빨리 끝나도 {failure["earliest_finish"]}입니다.' if failure.get('earliest_finish') else ''),
    }[reason]
    pages = [Dialogue('mentor', first)]
    blocker = failure.get('blocker')
    if blocker and reason in ('expired', 'late_certain', 'late'):
        pages.append(Dialogue('mentor', f'{blocker["country"]} 고객의 {blocker["mode"]} 작업(GPU {blocker["gpu"]}/전력 {blocker["power"]})이 '
                              f'{blocker["until"]}까지 자원을 사용하는 동안 {who} 고객의 요청을 시작할 수 없었습니다.'))
    elif reason in ('late', 'late_certain') and failure.get('mode') and failure.get('waited') is not None:
        pages.append(Dialogue('mentor', f'{who} 고객의 작업은 {failure["mode"]}로 접수 후 {failure["waited"]}분 뒤에 시작했고 처리에 {failure["minutes"]}분이 필요합니다.'))
    elif reason in ('expired', 'late_certain') and failure.get('waited') is None:
        pages.append(Dialogue('mentor', '자원을 쓸 수 있는 상황에서도 요청을 처리하지 않고 기다리는 동안 시간이 흘러 기한 안에 끝낼 수 없게 됐습니다.'))
    tried = failure.get('tried') or {}
    attempts = []
    if tried.get('proposal'):
        attempts.append(f'{who} 고객과 절약형 대안을 협의했지만 '
                        + {'rejected': '고객이 거절했습니다.', 'accepted': '동의를 받고도 끝내 처리하지 못했습니다.',
                           'pending': '고객의 답변을 확인하지 못했습니다.'}[tried['proposal']])
    if tried.get('wait_choices'):
        attempts.append(f'요청 대기를 {tried["wait_choices"]}회 선택했습니다.')
    if attempts:
        pages.append(Dialogue('mentor', ' '.join(attempts)+' 다른 방법도 검토했지만 이번에는 해결하지 못했습니다.'))
    other = failure.get('other')
    follow = ''
    if other and other.get('state') == 'running':
        follow = f'{other["country"]} 고객의 작업은 정상적으로 진행되고 있지만, '
    elif other and other.get('state') == 'pending':
        follow = f'{other["country"]} 고객의 요청은 아직 남아 있지만, '
    pages.append(Dialogue('mentor', follow+'이번 미션의 목표는 두 고객의 요청을 모두 기한 내에 처리하는 것이었습니다. 이미 확정된 실패 판정은 바뀌지 않습니다.'))
    pages.append(Dialogue('mentor', '다시 도전하면서 두 고객의 요구 조건과 완료 기한을 비교해 보세요. [Chapter 2 다시 도전]으로 바로 새로 시작할 수 있고, 지금 진행 중인 작업은 [기존 진행 계속 보기]로 이어서 확인할 수 있습니다.'))
    return pages


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
    chapter2: Chapter2Progress | None = None
    practice: bool = False  # Chapter 2만 독립 슬롯에서 시작한 연습. Chapter 1을 플레이한 기록으로 취급하지 않습니다.

    def __post_init__(self):
        if isinstance(self.chapter2, dict):
            self.chapter2 = Chapter2Progress(**self.chapter2)
        if type(self.practice) is not bool:
            raise ValueError('저장된 Chapter 2 연습 표시가 올바르지 않습니다.')
        if self.chapter2 is not None and (not isinstance(self.chapter2, Chapter2Progress)
                                          or not (self.chapter_completed or self.practice)):
            raise ValueError('저장된 Chapter 2 진행 상태가 올바르지 않습니다.')
        if self.practice and (self.chapter_completed or self.completed_steps or self.tutorial_completed
                              or self.skipped or self.first_work_completed or self.mission_status != 'pending'
                              or self.request_id is not None or self.legacy_progress):
            raise ValueError('Chapter 2 연습 저장에 Chapter 1 진행 기록이 포함되어 있습니다.')
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
                or any(not isinstance(key, str) or key not in (*STEPS, 'closed', 'skipped', *EVENTS2) for key in self.dialogue_seen)
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
        if payload.get('practice') is True:
            # 연습 슬롯에는 Chapter 1 고객 요청이 없습니다. 실제 Chapter 1 완료 여부와 비교하지 않습니다.
            data = dict(payload)
            data.setdefault('dialogue_seen', [])
            return cls(**data)
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
        data = asdict(self)
        if data['chapter2'] is None:
            data.pop('chapter2')  # Chapter 1 저장 형식을 그대로 유지합니다.
        if not data['practice']:
            data.pop('practice')
        return data

    @property
    def chapter2_active(self):
        return self.chapter2 is not None and not self.chapter2.completed

    @property
    def ui_done(self):
        """화면이 보는 '현재 Chapter 완료' 여부. Chapter 2가 시작되면 Chapter 2 기준입니다."""
        return self.chapter2.completed if self.chapter2 is not None else self.chapter_completed

    @property
    def ui_step(self):
        if self.chapter2 is None:
            return self.step
        return 'c2_done' if self.chapter2.completed else 'c2_'+self.chapter2.step

    @property
    def ui_completed_steps(self):
        if self.chapter2 is None:
            return self.completed_steps
        return ['c2_'+key for key in self.chapter2.completed_steps]

    @property
    def chapter_label(self):
        return 'Chapter 2' if self.chapter2 is not None else f'Chapter {self.chapter}'

    @property
    def dialogue_event(self):
        if self.chapter2 is not None:
            return self.ui_step
        if self.chapter_completed:
            return 'complete'
        if self.mission_status == 'closed':
            return 'closed'
        return 'skipped' if self.skipped else self.step

    @property
    def objective(self):
        if self.chapter2 is not None:
            if self.chapter2.completed and self.chapter2.failure is not None:
                return GUIDES2_FAILED_DONE[0]
            return GUIDES2[self.ui_step[3:]][0]
        if self.chapter_completed:
            return GUIDES['complete'][0]
        if self.mission_status == 'closed':
            return '첫 요청이 종료되었습니다. 교육 복습 또는 모드 선택을 이용하세요.'
        if self.skipped:
            return 'Merlion AI 업무를 직접 진행하세요. · Chapter 1'
        return GUIDES[self.step][0]

    @property
    def dialogue(self):
        if self.chapter2 is not None:
            if self.chapter2.completed and self.chapter2.failure is not None:
                return GUIDES2_FAILED_DONE[1]
            return GUIDES2[self.ui_step[3:]][1]
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
                 self.operations_confirmed or self.legacy_tutorial_completed or succeeded, succeeded, succeeded)
        # 시간을 크게 진행해 운영 확인 전에 정상 완료되면 완료 화면의 실제 결과가 운영 확인을 대신합니다.
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
