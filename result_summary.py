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


def chapter3_diagnosis_text(job):
    """저장된 장애 기록에서 만든 진단 요약. 장애 전에 끝난 요청에는 진단을 만들지 않습니다."""
    record = job['record']
    if not record:
        return '장애 발생 전에 요청이 종료되어 진단 정보 없음'
    if record['kind'] == 'path_down':
        text = f'주 경로 DOWN / 백업 경로 정상(용량 {record["backup"]}) / GPU·서버 정상'
    else:
        text = (f'주 경로 UP / 필요 대역폭 {record["initial_needed"]} > 가용 {record["available"]}'
                f' / 백업 경로는 같은 병목 공유 / GPU·서버 정상')
    return text + ('' if record.get('diagnosed') else ' (진단창을 열지 않음)')


def chapter3_job_rows(job):
    """미션 하나의 요약표 행. 모든 값은 기록된 장애·대응·작업 결과에서 읽습니다."""
    summary = job['job']
    if summary['key'] in ('on_time', 'late'):
        work = f'정상 완료 · 기한 {summary["deadline"]}'
    else:
        work = summary['label']
    return [('장애', job['kind_label']), ('진단', chapter3_diagnosis_text(job)),
            ('선택 대응', ' → '.join(job['responses']) if job['responses'] else '대응 없음'),
            ('복구 결과', '성공' if job['recovered'] else '실패'),
            ('중단 시간', f'{job["downtime"]}분 (대응 {job["attempts"]}회)'),
            ('작업 결과', work),
            ('운영 점수', f'{summary["score"]}점' if summary['score'] is not None else '확정 점수 없음(정상 완료 못함)')]


CH3_CAUSE_SHORT = {'path_down': '경로 단절', 'bandwidth': '대역폭 부족', None: '발생 전 종료'}


def chapter3_table(jobs):
    """결과 요약표: 미션 · 장애 원인 · 선택 대응(시도 횟수 포함) · 복구 결과 · 점수."""
    from story import chapter3_response_text
    rows = []
    for index, job in enumerate(jobs):
        record = job['record']
        score = job['job']['score']
        rows.append(("AB"[index], CH3_CAUSE_SHORT[job['kind']],
                     chapter3_response_text(record) + (f' · {job["attempts"]}회' if job['attempts'] else ''),
                     '성공' if job['recovered'] else '실패', f'{score}점' if score is not None else '확정 점수 없음'))
    return rows


def chapter3_mentor(jobs, ok):
    """선배 평가 3문장 이내: 원인과 적절했던(또는 필요했던) 조치, 최종 결과."""
    lines = []
    for index, job in enumerate(jobs):
        if not job['record']:
            continue
        name = "AB"[index]
        if job['kind'] == 'path_down':
            lines.append(f'{name}: 끊어진 경로에는 정상 백업 경로로 우회한 조치가 적절했습니다.' if job['recovered'] else
                         f'{name}: 끊어진 경로는 압축으로 복구되지 않습니다. 정상 백업 경로로 우회해야 했습니다.')
        else:
            lines.append(f'{name}: 경로는 연결되어 있었고 용량이 문제여서 필요량을 줄이는 압축이 적절했습니다.' if job['recovered'] else
                         f'{name}: 백업 경로는 같은 병목을 지나 용량이 늘지 않습니다. 필요량을 줄이는 압축이 필요했습니다.')
    lines.append(f'최종 결과: {len(jobs)}개 장애 중 {ok}개를 복구하고 정상 완료했습니다.')
    return lines[:3]


def chapter3_summary(result):
    jobs = result['jobs']
    ok = sum(1 for j in jobs if j['success'])
    return {'mission': result['mission'], 'ok': ok, 'total': len(jobs),
            'table': chapter3_table(jobs), 'mentor': chapter3_mentor(jobs, ok),
            'rows': [chapter3_job_rows(job) for job in jobs],
            'verdict': ('두 장애 모두 원인에 맞게 복구하고 정상 완료' if ok == len(jobs)
                        else f'{len(jobs)}개 장애 미션 중 {ok}개만 복구 후 정상 완료')}


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


def chapter3b_summary(result):
    """Chapter 3b 결과 요약표(미션 · 장애 · 선택 대응 · 결과 · 중단 · 점수)와 선배 분석. 저장된 기록에서만 계산합니다."""
    from chapter3b import result_outcome, mentor_lines
    jobs = result['jobs']
    ok = sum(1 for j in jobs if j['success'])
    table, rows = [], []
    for index, job in enumerate(jobs):
        record, summary = job['record'], job['job']
        table.append(("AB"[index], f'Server {record["server"]} 장애' if record else '장애 발생 전 종료',
                      ' → '.join(job['choices']) or '대응 없음', result_outcome(job), f'{job["downtime"]}분',
                      f'{summary["score"]}점' if summary['score'] is not None else '확정 점수 없음'))
        rows.append([('장애 서버', f'Server {record["server"]}' if record else '-'),
                     ('선택 대응', ' → '.join(job['choices']) or '대응 없음'),
                     ('선택 시 예상', (f'복구 완료 {game_time(record["repair_finish"])}' if record.get('repair_finish') is not None else '-')
                      + (f' / 이전 완료 {game_time(record["migrate_finish"])}' if record.get('migrate_finish') is not None else ' / 이전 불가')
                      + (f' / 기한 {game_time(record["due"])}' if record.get('due') is not None else '')),
                     ('서버 배정(마지막)', job['last_placement'] or '-'), ('배정 기록 수', str(job['allocations'])),
                     ('중단 시간', f'{job["downtime"]}분 (하드웨어 중단 + 이전 준비)')])
    detail = []
    for index, job in enumerate(jobs):
        detail.append(f'미션 {"AB"[index]} · {job["country"]} {job["company"]} — {job["job"]["task"]}')
        detail += [f'  {name}: {value}' for name, value in rows[index]]
        detail.append(f'  운영 모드 {job["job"]["mode"]} · GPU {job["job"]["gpu"]} / 전력 {job["job"]["power"]} 사용 후 '
                      + ('반환' if result.get('released') else '(반환 확인 필요)'))
    detail.append('서버 상태: '+' / '.join(f'{key} {value}' for key, value in result['servers'].items()))
    if result.get('practice'):
        detail.append('이 기록은 Chapter 3b 독립 연습 슬롯의 것이며 이전 Chapter 진행·점수와 별개입니다.')
    detail.append('이 장의 서버 구성과 시간은 교육용 설정입니다.')
    return {'mission': result['mission'], 'ok': ok, 'total': len(jobs), 'table': table, 'rows': rows,
            'columns': ('미션', '장애', '선택 대응', '결과', '중단', '점수'), 'name': 'Chapter 3b',
            'subtitle': '서버 장비 장애 · 복구와 이전', 'detail_text': '\n'.join(detail),
            'verdict': ('두 장애 모두 기한 내 정상 완료' if ok == len(jobs) else f'{len(jobs)}개 장애 미션 중 {ok}개만 기한 내 정상 완료'),
            'mentor': mentor_lines(jobs, ok)}
