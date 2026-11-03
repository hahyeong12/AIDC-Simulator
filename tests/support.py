"""기존 운영 회귀 시나리오에 신규 요청의 실제 동의 절차를 준비합니다."""


def start_with_consent(owner, mode):
    """GUI 또는 세션을 통해 시작하되, 고객 조건을 바꾸지 않고 필요한 동의를 받습니다."""
    session = getattr(owner, 'session', owner)
    run = session.current
    if (run.request['status'] in ('new', 'review', 'waiting') and run.conditions
            and mode not in run.conditions['allowed_modes'] and not run.proposals):
        session.propose_alternative()
        if not session.review_alternative():
            raise AssertionError('이 시나리오는 고객이 거절한 모드로 시작할 수 없습니다.')
    return owner.choose_plan(mode)


def start_legacy_plan(owner, mode):
    """최초 조건이 없던 이전 저장의 운영 시나리오를 명시적으로 구성합니다."""
    session = getattr(owner, 'session', owner)
    session.current.conditions = {}
    return owner.choose_plan(mode)
