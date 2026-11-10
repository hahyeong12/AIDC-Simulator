"""Chapter 1 교육 흐름. 실제 업무 규칙과 점수는 기존 세션을 사용합니다."""
from dataclasses import dataclass, field, asdict

from chapter2 import Chapter2Progress, EVENTS2
from chapter3 import Chapter3Progress, EVENTS3
from chapter3b import Chapter3bProgress, EVENTS3B


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
    'allocation': ('[배정 설정·선택]에서 검토한 계획으로 실제 고객 작업을 시작하세요.', [
        Dialogue('mentor', '[배정 설정·선택]에서 운영 모드와 배정안을 직접 확인한 뒤, 창 아래의 [선택한 계획으로 작업 시작]을 눌러 주세요. 자동 추천을 선택해도 되지만 직접 선택해야 시작할 수 있습니다. 원래 요청 조건이나 고객이 동의한 조건을 지켜야 합니다.'),
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
        Dialogue('mentor', '이번에는 고객이 두 곳입니다. 작업을 시작하기 전에 두 고객의 요청을 나란히 비교해 보세요. '
                           '확인할 것은 고객별 GPU 요구량, 전력 요구량, 운영 모드별 예상 처리 시간, 완료 기한, '
                           '고객이 허용하는 운영 모드, 그리고 지금 서버별로 남은 자원입니다. 마지막 장의 비교표는 현재 운영 시스템의 실제 값입니다.'),
        Dialogue('mentor', '두 작업을 모두 원래 조건대로 동시에 실행하기는 어려울 수 있습니다. 서버 자원은 한정되어 있고, 먼저 배정한 작업이 남는 자원을 줄이니까요.'),
        Dialogue('mentor', '어떤 작업을 먼저 처리할지, 서버 자원을 어떻게 남겨둘지 판단해 보세요. 정답은 알려 드리지 않을게요. 고객 동의 없이 원래 조건을 바꿀 수는 없습니다. 준비가 되면 브리핑을 확인하고 AIDC LINK에서 두 요청을 열어 보세요.')]),
    'requests': ('AIDC LINK에서 일본·미국 두 요청의 GPU·전력·완료 기한·모드별 처리 시간을 모두 읽으세요.', [
        Dialogue('mentor', '두 요청서의 GPU와 전력 요구량, 완료 기한, 고객이 허용한 운영 모드, 모드별 처리 시간을 읽고 비교해 보세요. 절약형이 허용되는 고객이라도 처리 시간은 길어집니다.'),
        Dialogue('mentor', '시간 버튼도 판단의 일부입니다. 결정을 미루는 동안에도 고객의 완료 기한은 다가옵니다.')]),
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
    after = failure.get('after')
    if blocker and reason in ('expired', 'late_certain', 'late'):
        text = (f'{blocker["country"]} 고객의 {blocker["mode"]} 작업(GPU {blocker["gpu"]}/전력 {blocker["power"]})을 배정하면서 '
                f'{who} 고객의 작업에 필요한 자원이 부족해졌습니다.')
        if blocker.get('placement'):
            text += (f' 전체 남은 GPU·전력 숫자로는 충분했지만, 먼저 배정한 위치({blocker.get("servers")}) 때문에 '
                     '서버별 GPU와 전력을 함께 묶을 수 없었습니다.')
        text += f' 그 작업이 {blocker["until"]}까지 자원을 사용하는 동안 {who} 고객의 요청을 기한에 맞춰 시작할 수 없었습니다.'
        pages.append(Dialogue('mentor', text))
    elif after and reason == 'late' and failure.get('mode') and failure.get('waited') is not None:
        pages.append(Dialogue('mentor', f'{after["country"]} 고객을 먼저 처리했지만({after["completed"]} 완료) {who} 고객도 '
                              f'{failure["mode"]}로 실행하면서 완료 기한을 넘겼습니다. 접수 후 {failure["waited"]}분 뒤에 시작했고 '
                              f'처리에 {failure["minutes"]}분이 걸렸습니다.'))
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
    elif other and other.get('state') == 'success':
        follow = f'{other["country"]} 고객의 작업은 기한 내에 정상 완료했지만, '
    pages.append(Dialogue('mentor', follow+'이번 미션의 목표는 두 고객의 요청을 모두 기한 내에 처리하는 것이었습니다. 이미 확정된 실패 판정은 바뀌지 않습니다.'))
    pages.append(Dialogue('mentor', '다시 도전하면서 두 고객의 요구 조건과 완료 기한을 비교해 보세요. [Chapter 2 다시 도전]으로 바로 새로 시작할 수 있고, 지금 진행 중인 작업은 [기존 진행 계속 보기]로 이어서 확인할 수 있습니다.'))
    return pages


# Chapter 3: 선배는 확인할 정보만 안내하고 정답 대응은 진단 뒤에도 알려 주지 않습니다. 결과 설명은 실제 기록에서만 만듭니다.
# 항목은 각각 별도 행으로 나누어 한 화면에서 읽히게 합니다(v0.9-3a-1). 정답 대응은 공개하지 않습니다.
_DIAGNOSE_HELP = ('[네트워크 진단]에서 살펴볼 항목\n\n'
                  '① 【주 통신 경로】 — 연결되어 있는가?\n'
                  '② 【필요 대역폭】 — 작업에 얼마나 필요한가?\n'
                  '③ 【백업 경로】 — 이용 가능한 대체 경로가 있는가?\n'
                  '④ 【GPU·서버 상태】 — 네트워크 외 장비에는 문제가 없는가?\n\n'
                  '확인한 정보를 바탕으로 대응 방법을 선택해 보세요.')
GUIDES3 = {
    'briefing': ('선배의 Chapter 3 브리핑을 읽고 확인하세요.', [
        Dialogue('mentor', '오늘은 운영 중에 생기는 네트워크 장애를 다룹니다. 작업이 갑자기 멈췄을 때 가장 위험한 것은 버튼부터 눌러 보는 습관이에요.'),
        Dialogue('mentor', '장애가 나면 먼저 무엇이 멈췄는지 확인하고, 원인에 맞는 대응을 골라야 합니다. 같은 "네트워크 장애"여도 원인이 다르면 효과가 있는 대응이 다를 수 있어요.'),
        Dialogue('mentor', '오늘은 서로 다른 장애를 두 번 겪게 됩니다. 정답은 알려 드리지 않을 테니 진단 화면의 수치를 보고 직접 판단해 보세요. 준비되면 브리핑을 확인하고 첫 고객 요청을 열어 보세요.'),
        Dialogue('system', '대응은 최대 3회, 장애 중단은 60분까지입니다. 시도한 대응은 비용과 점수에 실제로 반영됩니다. 이 장의 네트워크 구성은 교육용이며 실제 네트워크의 모든 경우를 대표하지 않습니다.')]),
    'a_start': ('AIDC LINK에서 싱가포르 요청을 확인하고 [배정 설정·선택]에서 작업을 시작하세요.', [
        Dialogue('mentor', '첫 고객 요청이 도착했습니다. 요청서를 읽고 [배정 설정·선택]에서 배정안을 직접 확인해 작업을 시작해 보세요.')]),
    'a_incident': ('시간 버튼으로 작업을 진행하세요. 작업 중 장애가 발생하면 시간이 멈춥니다.', [
        Dialogue('mentor', '작업이 시작됐습니다. 시간을 진행하면서 상태를 지켜보세요. 이상 신호가 나타나면 진행이 멈추니 그때 바로 대응하지 말고 상태부터 확인하면 됩니다.')]),
    'a_diagnose': ('[네트워크 진단]을 열어 장애 원인을 확인하세요.', [
        Dialogue('mentor', '작업이 중단됐습니다. 먼저 【장애 원인】을 확인하세요.\n\n'+_DIAGNOSE_HELP)]),
    'a_respond': ('진단 정보를 근거로 직접 판단해 대응을 선택하세요.', [
        Dialogue('mentor', '진단 정보를 확인했네요. 이제 수치를 근거로 어떤 대응이 맞을지 스스로 판단해 보세요. 대응은 3회까지이고 시도마다 비용이 들며, 중단 시간은 계속 쌓입니다. 결과가 기대와 다르면 진단 정보를 다시 열어 비교하면 됩니다.')]),
    'a_finish': ('시간을 진행해 작업을 마무리하세요. 실패했다면 후속 조치를 선택합니다.', [
        Dialogue('mentor', '대응을 선택했습니다. 복구되었다면 복구 준비가 끝난 뒤 작업이 다시 진행됩니다. 관제실로 돌아가 작업 상태를 확인해 보세요. 복구되지 않았다면 진단 정보를 다시 확인하세요.')]),
    'b_start': ('두 번째 장애 미션: 미국 요청을 확인하고 작업을 시작하세요.', [
        Dialogue('mentor', '첫 장애를 처리했네요. 이번에는 다른 고객 작업에서 장애가 발생할 수 있습니다. 앞서 효과가 있었던 대응이 이번에도 통할지는 진단 수치로 판단해야 합니다.'),
        Dialogue('mentor', '미국 고객의 요청을 확인하고 [배정 설정·선택]에서 작업을 시작해 보세요.')]),
    'b_incident': ('시간 버튼으로 작업을 진행하세요. 작업 중 장애가 발생하면 시간이 멈춥니다.', [
        Dialogue('mentor', '작업이 시작됐습니다. 시간을 진행하면서 상태를 지켜보세요.')]),
    'b_diagnose': ('[네트워크 진단]을 열어 장애 원인을 확인하세요.', [
        Dialogue('mentor', '이번에도 작업이 중단됐습니다. 지난번과 같은 원인이라고 단정하지 마세요.\n\n'+_DIAGNOSE_HELP)]),
    'b_respond': ('진단 정보를 근거로 직접 판단해 대응을 선택하세요.', [
        Dialogue('mentor', '이번 장애의 수치를 지난번과 비교해 보세요. 어떤 대응이 필요한지는 이번 진단 정보가 알려 줍니다.')]),
    'b_finish': ('시간을 진행해 작업을 마무리하세요. 실패했다면 후속 조치를 선택합니다.', [
        Dialogue('mentor', '대응을 선택했습니다. 복구되었다면 복구 준비가 끝난 뒤 작업이 다시 진행됩니다. 관제실로 돌아가 작업 상태를 확인해 보세요.')]),
    'done': ('Chapter 3 종료 · 결과 화면에서 두 장애의 진단과 대응 결과를 확인하세요.', [
        Dialogue('system', '두 장애 미션이 끝났습니다. 결과 화면에서 장애별 진단, 선택한 대응, 복구 결과, 중단 시간과 운영 점수를 확인할 수 있습니다.')]),
}

_CAUSES = {
    'path_down': ('통신 경로 단절', '주 통신 경로가 DOWN이라 데이터가 지나갈 길이 없었고, 백업 경로는 정상이었습니다.',
                  '진단에서 주 경로 DOWN과 백업 경로 UP을 확인하고 백업 경로로 우회하는 것이 맞는 조치였습니다.'),
    'bandwidth': ('가용 대역폭 부족', '주 통신 경로는 연결되어 있었지만 가용 대역폭이 필요 대역폭보다 작았고, 백업 경로는 같은 병목 구간을 공유했습니다.',
                  '진단에서 경로는 UP인데 필요 대역폭이 가용 대역폭보다 크다는 점을 확인하고 필요량을 줄이는 압축을 선택하는 것이 맞는 조치였습니다.'),
}
_NOTE = '이 설명은 이번 교육용 구성에서의 결과이며, 실제 네트워크에서는 구성에 따라 효과가 다를 수 있습니다.'


def chapter3_feedback_pages(key, record):
    """저장된 장애 기록의 사실만으로 선배 피드백을 만듭니다. 시도하지 않은 대응은 시도했다고 말하지 않습니다."""
    names = {'reroute': '백업 경로 우회', 'compress': '전송 데이터 압축', 'ignore': '기존 설정 유지'}
    tried = ' → '.join(names[r] for r in record.get('responses', []))
    cause, cause_text, improve = _CAUSES[record['kind']]
    if key == 'fail':
        last = names[record['responses'][-1]]
        left = max(0, 3-record['attempts'])
        link = '주 통신 경로 UP' if record['primary_up'] else ('백업 경로로 전환됨' if record['rerouted'] else '주 통신 경로 DOWN')
        return [Dialogue('mentor', f'{last}을(를) 적용했지만 작업은 재개되지 않았습니다. 관찰된 결과: {link}, 필요 대역폭 {record["needed"]} / '
                                   f'가용 대역폭 {record["available"]}. 중단 시간은 {record["downtime"]}분째입니다.'),
                Dialogue('mentor', f'남은 대응은 {left}회입니다. [네트워크 진단]을 다시 열어 지금의 수치를 처음 진단과 비교해 보세요. '
                                   '무엇이 바뀌었고 무엇이 그대로인지가 다음 판단의 근거입니다.')]
    if key == 'recovered':
        winner = names[record['recovered_by']]
        pages = [Dialogue('mentor', f'복구에 성공했습니다. 이번 장애의 원인은 "{cause}"였습니다. {cause_text}')]
        wasted = [r for r in record['responses'] if r != record['recovered_by']]
        if record['kind'] == 'path_down':
            why = (f'{winner}으로 막힌 주 경로 대신 백업 경로(용량 {record.get("backup", 0)})를 쓰게 되어 데이터가 다시 지나갈 수 있었습니다.')
            if 'compress' in wasted:
                why += ' 앞서 시도한 압축은 필요 대역폭을 줄였지만 끊어진 경로를 되살리지는 못했습니다.'
        else:
            why = f'{winner}으로 필요 대역폭을 가용 대역폭({record["available"]}) 이하로 낮춰 같은 경로로도 전송할 수 있게 되었습니다.'
            if 'reroute' in wasted:
                why += ' 앞서 시도한 백업 경로 우회는 같은 병목 구간을 지나 가용 대역폭을 늘리지 못했습니다.'
        pages.append(Dialogue('mentor', why+f' 시도한 대응: {tried}. 그동안 {record["downtime"]}분이 중단되었습니다. '+_NOTE))
        return pages
    if key == 'failed':
        reason = ('대응을 선택하지 못한 채 중단 시간이 60분을 넘겼습니다.' if not record.get('responses')
                  else f'대응 {record["attempts"]}회({tried})로 복구하지 못했거나 중단 시간이 60분을 넘겼습니다.')
        return [Dialogue('mentor', f'이번 작업은 정상 완료하지 못했습니다. {reason}'),
                Dialogue('mentor', f'실제 원인은 "{cause}"였습니다. {cause_text}'),
                Dialogue('mentor', f'개선점: {improve} 장애가 나면 먼저 진단 정보를 읽고, 시도한 조치가 효과가 없으면 같은 조치를 반복하지 말고 수치를 다시 비교하세요. '+_NOTE)]
    raise ValueError('알 수 없는 Chapter 3 피드백입니다.')



# Chapter 3b: 서버 장비 장애. 선배는 살펴볼 항목만 안내하고 복구/이전 중 무엇이 맞는지는 알려 주지 않습니다.
_HW_HELP = ('[장비 진단]에서 살펴볼 항목\n\n'
            '① 【장애 서버】 — 어느 서버이고 어떤 상태인가?\n'
            '② 【점유 자원】 — 영향받은 작업이 쓰는 GPU·전력은?\n'
            '③ 【정상 서버】 — 작업을 옮길 만한 여유 자원이 있는가?\n'
            '④ 【예상 시간】 — 복구와 이전을 하면 언제 끝나는가?\n\n'
            '비교한 뒤 대응 방법을 직접 선택해 보세요.')
GUIDES3B = {
    'briefing': ('선배의 Chapter 3b 브리핑을 읽고 확인하세요.', [
        Dialogue('mentor', '이번에는 서버 장비 자체의 장애를 다룹니다. 네트워크 장애와 달리 GPU와 서버가 멈추고, 장애가 난 서버는 새 작업을 받을 수 없어요.'),
        Dialogue('mentor', '대응은 크게 두 가지입니다. 장비를 복구하거나, 작업을 정상 서버로 옮기거나. 어느 쪽이 나은지는 정상 서버의 여유 자원과 고객 완료 기한을 비교해서 직접 판단해 보세요.'),
        Dialogue('system', '장비 복구는 가상 시간 20분, 작업 이전 준비는 10분입니다. 대응을 선택하는 것만으로는 시간이 흐르지 않고 시간 버튼을 눌러야 진행됩니다. 이 장의 구성은 교육용입니다.')]),
    'a_start': ('AIDC LINK에서 일본 요청을 확인하고 [배정 설정·선택]에서 작업을 시작하세요.', [
        Dialogue('mentor', '첫 고객 요청이 도착했습니다. 완료 기한이 빠듯한 긴급 작업이니 요청서를 읽고 작업을 시작해 보세요.')]),
    'a_fault': ('시간 버튼으로 작업을 진행하세요. 장비 장애가 발생하면 시간이 멈춥니다.', [
        Dialogue('mentor', '작업이 시작됐습니다. 시간을 진행하면서 지켜보세요. 이상이 생기면 진행이 멈춥니다.')]),
    'a_diagnose': ('[장비 진단]을 열어 복구와 이전을 비교하세요.', [
        Dialogue('mentor', '서버 장비에 장애가 발생했습니다. 고객 작업이 중단됐어요.\n\n'+_HW_HELP)]),
    'a_respond': ('비교한 내용을 근거로 장비 복구 또는 작업 이전을 직접 선택하세요.', [
        Dialogue('mentor', '진단 정보를 확인했네요. 이제 시간과 자원을 비교해 직접 선택하세요. 선택하는 순간에는 시간이 흐르지 않습니다.')]),
    'a_finish': ('시간 버튼으로 작업을 끝까지 진행하세요.', [
        Dialogue('mentor', '선택한 대응은 가상 시간으로 진행됩니다. 관제실로 돌아가 시간을 진행하며 작업이 재개되는지 확인해 보세요.')]),
    'b_start': ('두 번째 장애 미션: 싱가포르 요청을 확인하고 작업을 시작하세요.', [
        Dialogue('mentor', '첫 장애를 처리했네요. 이번에는 다른 고객의 큰 작업입니다. 앞서의 선택이 이번에도 통할지는 진단으로 확인하세요.')]),
    'b_fault': ('시간 버튼으로 작업을 진행하세요. 장비 장애가 발생하면 시간이 멈춥니다.', [
        Dialogue('mentor', '작업이 시작됐습니다. 시간을 진행하면서 지켜보세요.')]),
    'b_diagnose': ('[장비 진단]을 열어 복구와 이전을 비교하세요.', [
        Dialogue('mentor', '또 서버 장비에 장애가 발생했습니다. 지난번과 같은 상황이라고 단정하지 마세요.\n\n'+_HW_HELP)]),
    'b_respond': ('비교한 내용을 근거로 장비 복구 또는 작업 이전을 직접 선택하세요.', [
        Dialogue('mentor', '이번 진단 값을 지난번과 비교해 보세요. 선택하는 순간에는 시간이 흐르지 않습니다.')]),
    'b_finish': ('시간 버튼으로 작업을 끝까지 진행하세요.', [
        Dialogue('mentor', '선택한 대응은 가상 시간으로 진행됩니다. 관제실로 돌아가 시간을 진행해 주세요.')]),
    'done': ('Chapter 3b 종료 · 결과 화면에서 두 장애의 선택과 결과를 확인하세요.', [
        Dialogue('system', '두 장애 미션이 끝났습니다. 결과 화면에서 장애별 선택 대응, 기한 준수, 중단 시간과 운영 점수를 확인할 수 있습니다.')]),
}

_SHORT = {'reroute': '우회', 'compress': '압축', 'ignore': '유지'}
_CAUSE_TITLE = {'path_down': '주 통신 경로 단절', 'bandwidth': '가용 대역폭 부족'}


def chapter3_response_text(record):
    """실제 시도 기록을 '압축 실패 → 우회 성공'처럼 요약합니다. 마지막 대응만 보여 주어 오해하지 않게 합니다."""
    responses = record.get('responses', [])
    if not responses:
        return '대응 없음'
    return ' → '.join(f'{_SHORT[r]} '+('성공' if record.get('recovered_by') and i == len(responses)-1 else '실패')
                      for i, r in enumerate(responses))


def chapter3_card(kind, record, closed=False):
    """장애 결과 카드(제목·행·선배 한마디). 성공/실패 모두 같은 구조이며 저장된 장애 기록의 사실만 씁니다.
    kind: 'recovered' | 'fail'(대응이 실패했지만 기회가 남음) | 'failed'(작업 최종 실패)."""
    cause = _CAUSE_TITLE[record['kind']]
    tried = chapter3_response_text(record)
    if kind == 'recovered':
        if record['kind'] == 'path_down':
            result = '통신 경로 복구'
            mentor = '끊어진 경로는 압축만으로 복구할 수 없습니다. 정상적인 백업 경로로 우회한 판단이 적절했습니다.'
        else:
            result = f'필요 {record["needed"]} ≤ 가용 {record["available"]}로 복구'
            mentor = '경로는 연결되어 있었고 용량이 문제였습니다. 백업 경로는 같은 병목을 지나 용량이 늘지 않으므로 필요량을 줄인 압축이 적절했습니다.'
        return {'kind': kind, 'title': '네트워크 복구 성공', 'tone': 'success',
                'rows': [('원인', cause), ('선택 대응', tried), ('실제 결과', result)],
                'mentor': mentor+' (교육용 구성 기준)'}
    if kind == 'fail':
        link = '주 경로 UP' if record['primary_up'] else ('백업 경로 사용' if record['rerouted'] else '주 경로 DOWN')
        left = max(0, 3-record['attempts'])
        return {'kind': kind, 'title': f'복구되지 않음 · 대응 {record["attempts"]}/3회', 'tone': 'warn',
                'rows': [('선택 대응', tried),
                         ('실제 결과', f'작업 재개 안 됨 · {link} · 필요 {record["needed"]} / 가용 {record["available"]}')],
                'mentor': f'바뀐 수치를 처음 진단과 비교해 보세요. 남은 대응은 {left}회입니다.'}
    if kind == 'failed':
        return {'kind': kind, 'title': 'NETWORK RECOVERY FAILED', 'tone': 'fail',
                'rows': [('원인', cause), ('시도한 대응', tried), ('복구 결과', '실패'),
                         ('작업 상태', '실패 · 최종 보고 완료' if closed else '실패 · 후속 처리 필요')],
                'mentor': '이번에는 적절한 대응을 찾지 못했습니다. 어떤 조건 때문에 복구되지 않았는지 다시 살펴보세요.'}
    raise ValueError('알 수 없는 Chapter 3 결과 카드입니다.')


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
    practice: bool = False  # Chapter 2/3만 독립 슬롯에서 시작한 연습. Chapter 1을 플레이한 기록으로 취급하지 않습니다.
    chapter3: Chapter3Progress | None = None
    practice_chapter: int | str = 2  # 연습 슬롯이 시작한 Chapter(2, 3 또는 '3b'). 연습이 아니면 기본값 2
    chapter3b: Chapter3bProgress | None = None

    def __post_init__(self):
        if isinstance(self.chapter2, dict):
            self.chapter2 = Chapter2Progress(**self.chapter2)
        if isinstance(self.chapter3, dict):
            self.chapter3 = Chapter3Progress(**self.chapter3)
        if isinstance(self.chapter3b, dict):
            self.chapter3b = Chapter3bProgress(**self.chapter3b)
        if type(self.practice) is not bool or self.practice_chapter not in (2, 3, '3b') or type(self.practice_chapter) not in (int, str):
            raise ValueError('저장된 Chapter 2 연습 표시가 올바르지 않습니다.')
        if not self.practice and self.practice_chapter != 2:
            raise ValueError('저장된 연습 Chapter 표시가 올바르지 않습니다.')
        if self.chapter2 is not None and (not isinstance(self.chapter2, Chapter2Progress)
                                          or not (self.chapter_completed or (self.practice and self.practice_chapter == 2))):
            raise ValueError('저장된 Chapter 2 진행 상태가 올바르지 않습니다.')
        # Chapter 3은 Chapter 2를 끝낸 슬롯 또는 Chapter 3 독립 연습 슬롯에만 있습니다. 독립 연습에는 Chapter 1/2 기록이 없습니다.
        if self.chapter3 is not None and (
                not isinstance(self.chapter3, Chapter3Progress)
                or (self.practice_chapter == 3 and (not self.practice or self.chapter2 is not None))
                or self.practice_chapter == '3b'
                or (self.practice_chapter != 3 and (self.chapter2 is None or not self.chapter2.completed))):
            raise ValueError('저장된 Chapter 3 진행 상태가 올바르지 않습니다.')
        # Chapter 3b는 Chapter 3a를 끝낸 슬롯 또는 독립 연습 슬롯에만 있습니다. 독립 연습에는 이전 Chapter 기록이 없습니다.
        if self.chapter3b is not None and (
                not isinstance(self.chapter3b, Chapter3bProgress)
                or (self.practice_chapter == '3b' and (not self.practice or self.chapter2 is not None or self.chapter3 is not None))
                or (self.practice_chapter != '3b' and (self.chapter3 is None or not self.chapter3.completed))):
            raise ValueError('저장된 Chapter 3b 진행 상태가 올바르지 않습니다.')
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
                or any(not isinstance(key, str) or key not in (*STEPS, 'closed', 'skipped', *EVENTS2, *EVENTS3, *EVENTS3B) for key in self.dialogue_seen)
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
        if data['chapter3'] is None:
            data.pop('chapter3')
        if data['chapter3b'] is None:
            data.pop('chapter3b')
        if data['practice_chapter'] == 2:
            data.pop('practice_chapter')  # Chapter 2 연습/이전 저장 형식을 그대로 유지합니다.
        return data

    @property
    def chapter2_active(self):
        return self.chapter2 is not None and not self.chapter2.completed

    @property
    def chapter3_active(self):
        return self.chapter3 is not None and not self.chapter3.completed

    @property
    def chapter3b_active(self):
        return self.chapter3b is not None and not self.chapter3b.completed

    @property
    def ui_done(self):
        """화면이 보는 '현재 Chapter 완료' 여부. 가장 나중에 시작한 Chapter 기준입니다."""
        if self.chapter3b is not None:
            return self.chapter3b.completed
        if self.chapter3 is not None:
            return self.chapter3.completed
        return self.chapter2.completed if self.chapter2 is not None else self.chapter_completed

    @property
    def ui_step(self):
        if self.chapter3b is not None:
            return 'c3b_done' if self.chapter3b.completed else 'c3b_'+self.chapter3b.step
        if self.chapter3 is not None:
            return 'c3_done' if self.chapter3.completed else 'c3_'+self.chapter3.step
        if self.chapter2 is None:
            return self.step
        return 'c2_done' if self.chapter2.completed else 'c2_'+self.chapter2.step

    @property
    def ui_completed_steps(self):
        if self.chapter3b is not None:
            return ['c3b_'+key for key in self.chapter3b.completed_steps]
        if self.chapter3 is not None:
            return ['c3_'+key for key in self.chapter3.completed_steps]
        if self.chapter2 is None:
            return self.completed_steps
        return ['c2_'+key for key in self.chapter2.completed_steps]

    @property
    def chapter_label(self):
        if self.chapter3b is not None:
            return 'Chapter 3b'
        if self.chapter3 is not None:
            return 'Chapter 3'
        return 'Chapter 2' if self.chapter2 is not None else f'Chapter {self.chapter}'

    @property
    def dialogue_event(self):
        if self.chapter2 is not None or self.chapter3 is not None or self.chapter3b is not None:
            return self.ui_step
        if self.chapter_completed:
            return 'complete'
        if self.mission_status == 'closed':
            return 'closed'
        return 'skipped' if self.skipped else self.step

    @property
    def objective(self):
        if self.chapter3b is not None:
            return GUIDES3B[self.ui_step[4:]][0]
        if self.chapter3 is not None:
            return GUIDES3[self.ui_step[3:]][0]
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
        if self.chapter3b is not None:
            return GUIDES3B[self.ui_step[4:]][1]
        if self.chapter3 is not None:
            return GUIDES3[self.ui_step[3:]][1]
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
