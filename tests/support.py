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


def dismiss_story_popups(app, root):
    """안내/결과 창만 닫습니다. 실제 교육 확인이나 게임 행동을 대신하지 않습니다."""
    for _ in range(4):
        root.update()
        feedback = getattr(app, 'feedback_window', None)
        guide = app.story_window
        if feedback is not None and feedback.winfo_exists():
            feedback.close_button.invoke()
        elif guide is not None and guide.winfo_exists():
            guide.close_button.invoke()
        else:
            break
    root.update()


def start_via_dialog(app, index=None):
    """v0.9-2b-1: 메인 [배정 설정·선택]은 설정창을 열기만 합니다. 창에서 계획(없으면 자동 추천)을 직접 고르고 시작합니다."""
    app.action_buttons['start'].invoke()
    dialog = app.allocation_window
    app.root.update()
    (dialog.auto_button if index is None else dialog.plan_buttons[index]).invoke()
    dialog.start_button.invoke()
    app.root.update()
    return dialog
