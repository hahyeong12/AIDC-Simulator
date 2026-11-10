"""v0.9-2b 결과 요약과 고객 반응. Tk와 DB 쓰기가 없는 순수 함수 모음입니다.

모든 값은 이미 저장된 요청 상태·terms·MissionRun에서 읽습니다. 새 점수나 저장 필드는 만들지 않습니다.
원칙: 결과는 요약표로 먼저, 설명은 아래에, 고객 반응은 실제 결과에 맞게.
"""
from game import game_time

OUTCOME_NAMES = {'in_progress': '진행 중', 'on_time': '정상 완료 · 기한 준수', 'late': '정상 완료 · 기한 초과',
                 'failed': '작업 실패', 'rejected': '요청 거절', 'expired': '기한 만료 · 미처리'}


def outcome_key(run):
    """실제 요청/작업 상태만으로 결과 종류를 구분합니다. 끝나지 않았으면 'in_progress'입니다."""
    s, t = run.state, run.terms
    if t.get('expired'):
        return 'expired'
    if run.request['status'] == 'rejected':
        return 'rejected'
    if s.phase == 'finished':
        if run.request['status'] == 'completed' and s.succeeded:
            due, done = t.get('due'), t.get('completed')
            return 'late' if due is not None and done is not None and done > due else 'on_time'
        return 'failed'
    return 'in_progress'


def job_summary(run):
    """고객 작업 하나의 결과 요약. 수행하지 않은 작업(거절·미처리)에는 점수와 자원을 만들지 않습니다."""
    key = outcome_key(run)
    s, t = run.state, run.terms
    ran = key in ('on_time', 'late', 'failed') or (key == 'in_progress' and s.allocated)
    if key in ('on_time', 'late'):
        deadline = '준수' if key == 'on_time' else f'초과 {t.get("late_minutes") or 0}분'
    elif key == 'in_progress':
        deadline = '판정 전'
    else:
        deadline = '해당 없음'
    return {'request_id': run.request['id'], 'company': run.mission['company_name'], 'country': run.mission['country'],
            'task': run.mission['title'], 'key': key, 'label': OUTCOME_NAMES[key],
            'mode': s.plans[s.plan]['label'] if (ran and s.plan) else '배정 없음',
            'gpu': s.gpu_used if ran else 0, 'power': s.power_used if ran else 0,
            'deadline': deadline, 'due': game_time(t['due']) if t.get('due') is not None else None,
            'completed': game_time(t['completed']) if key in ('on_time', 'late') and t.get('completed') is not None else None,
            'score': s.score if key in ('on_time', 'late') else None}


def _agreed_economy(run):
    p = run.proposals[-1] if run.proposals else None
    state = getattr(run, 'state', None)
    # 동의한 대안은 실제로 그 모드로 운영했을 때만 반응에 반영합니다.
    return bool(p and p['status'] == 'accepted' and (state is None or state.plan == p.get('proposed', {}).get('mode', state.plan)))


def customer_reaction(run, key):
    """결과에 맞는 고객 반응. 동의했던 대안과 국가별 말투를 반영하고 과장된 감정은 쓰지 않습니다."""
    country = run.mission['country']
    if key == 'on_time':
        base = {'일본': '요청드린 작업이 예정대로 완료되었음을 확인했습니다. 성실히 처리해 주셔서 감사드립니다.',
                '미국': '작업이 일정에 맞춰 끝났네요. 안정적으로 처리해 주셔서 고맙습니다.'}.get(
            country, '요청드린 작업이 예정대로 완료됐네요. 안정적으로 처리해 주셔서 감사합니다.')
        if _agreed_economy(run):
            base += ' 협의한 운영 조건대로 진행된 점도 확인했습니다.'
        return base
    if key == 'late':
        return {'일본': '작업을 마무리해 주셔서 감사합니다. 다만 약속된 일정이 지연되어 아쉬움이 남습니다. 다음에는 일정을 지켜 주시길 부탁드립니다.',
                '미국': '작업 완료는 확인했습니다. 다만 약속한 기한보다 일정이 지연되어 아쉽습니다. 다음에는 일정에 맞춰 주세요.'}.get(
            country, '작업을 마무리해 주셔서 감사합니다. 다만 약속된 일정이 지연되어 아쉬움이 있었습니다. 다음에는 일정을 준수해 주시길 부탁드립니다.')
    if key == 'failed':
        return {'일본': '작업이 정상적으로 완료되지 못했다니 유감입니다. 원인과 복구 계획을 안내해 주시기 바랍니다.',
                '미국': '작업이 끝내 완료되지 못해 유감입니다. 원인과 이후 복구 계획을 알려 주세요.'}.get(
            country, '작업이 정상적으로 완료되지 못했다니 유감입니다. 원인과 복구 계획을 안내해 주시기 바랍니다.')
    if key == 'rejected':
        extra = ' 앞서 협의했던 조건도 이번 요청에는 적용되지 않는 것으로 알겠습니다.' if run.proposals else ''
        return '회신과 거절 사유를 확인했습니다. 아쉽지만 이번 요청은 종료하겠습니다.' + extra
    if key == 'expired':
        extra = ' 협의했던 대안 조건도 시작되지 못한 점이 아쉽습니다.' if run.proposals else ''
        return '최종 배정 기한까지 작업이 시작되지 않아 요청을 철회합니다. 아쉽지만 미처리로 기록해 주세요.' + extra
    raise ValueError('끝나지 않은 요청에는 결과 반응을 만들 수 없습니다.')


def free_result_lines(run):
    """자유 운영 패널에 붙이는 간단한 결과 요약. 끝나지 않은 요청은 빈 목록입니다."""
    job = job_summary(run)
    if job['key'] == 'in_progress':
        return []
    lines = [f'작업 결과: {job["label"]}', f'고객: {job["company"]}']
    if job['key'] in ('on_time', 'late', 'failed'):
        lines.append(f'운영 모드: {job["mode"]}')
        lines.append(f'사용 자원: GPU {job["gpu"]} / 전력 {job["power"]}')
    if job['key'] in ('on_time', 'late'):
        lines.append(f'기한: {job["deadline"]}' + (f' (완료 {job["completed"]} / 기한 {job["due"]})' if job['due'] else ''))
        lines.append(f'점수: {job["score"]}점')
    elif job['key'] == 'failed':
        lines.append('점수: 정상 완료하지 못해 확정 점수 없음')
    else:
        lines.append('점수: 수행하지 않아 부여하지 않음')
    return lines


def chapter1_summary(result, run):
    """Chapter 1 완료창용 요약 행. result는 chapter_result() 값입니다."""
    job = job_summary(run)
    return [('고객', job['company']), ('운영 모드', job['mode']),
            ('사용 자원', f'GPU {job["gpu"]} / 전력 {job["power"]}'),
            ('완료 / 기한', f'{job["completed"]} / {job["due"]} · {job["deadline"]}' if job['due'] else '기한 평가 제외'),
            ('운영 점수', f'{result["score"]}점'),
            ('반환 자원', f'GPU {result["gpu"]}개 · 전력 {result["power"]}단위 반환')]


def chapter2_strategy(jobs, concurrent):
    """'일본 고성능 + 미국 절약형' 같은 실제 운영 전략 한 줄."""
    parts = [f'{j["country"]} {j["mode"].replace(" 모드", "")}' for j in jobs if j['started'] is not None]
    if not parts:
        return '배정한 작업 없음'
    return ' + '.join(parts) if concurrent or len(parts) == 1 else ' → '.join(parts)


def chapter2_summary(result):
    """Chapter 2 결과의 상단 요약. 개별 고객 성공과 미션 성공은 별도로 셉니다."""
    jobs = result['jobs']
    ok = sum(1 for j in jobs if j['state'] == 'success')
    ran = [j for j in jobs if j['started'] is not None]
    concurrent = result['concurrent']
    return {'mission': result['mission'], 'overall': result['overall'], 'ok': ok, 'total': len(jobs),
            'strategy': chapter2_strategy(jobs, concurrent),
            'arrangement': ('두 작업 동시 실행' if concurrent else '순차 실행 · 먼저 끝난 자원 반환 후 시작' if len(ran) == 2
                            else f'실행한 작업 {len(ran)}건'),
            'resources': (f'GPU {sum(j["gpu"] for j in ran)}개 / 전력 {sum(j["power"] for j in ran)}단위 사용 후 반환'
                          if ran else '사용한 자원 없음'),
            'verdict': ('두 고객 모두 기한 내 완료' if ok == len(jobs) else f'{len(jobs)}명 중 {ok}명만 기한 내 정상 완료')}
