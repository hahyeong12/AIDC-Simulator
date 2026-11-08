"""저장된 요청 조건을 읽기 전용 표시 모델로 변환합니다."""
from game import game_time


def request_summary(run):
    c = run.conditions
    proposal = run.proposals[-1] if run.proposals else None
    mode = c.get('requested_mode')
    original = c.get('plans', {}).get(mode, {})
    if not original and proposal:
        original = proposal['original']
    missing = '기록 없음 · 이전 요청'
    def time_value(key):
        value = run.terms.get(key)
        if key == 'due' and value is None:
            value = c.get('due')
        return game_time(value) if value is not None else missing
    consent = ({'pending': '변경 제안 답변 대기 · 시작 불가', 'accepted': '변경 조건 동의 완료',
                'rejected': '변경 제안 거절 · 원래 조건 유지'}[proposal['status']] if proposal else
               '최초 허용 모드 내 실행 가능' if c else '이전 요청 · 동의 기록 없음')
    result = {'고객명': run.mission['company_name'], '국가': run.mission['country'],
              '작업 종류': c.get('task', run.mission['title']),
              '요청 운영 모드': original.get('label', missing),
              'GPU 요구량': str(original.get('gpu', missing)), '전력 요구량': str(original.get('power', missing)),
              '접수 시각': time_value('received'), '완료 기한': time_value('due'), '고객 동의': consent}
    if c:
        result['허용 운영 모드'] = ' / '.join(c['plans'][key]['label'] for key in c['allowed_modes'])
    if proposal:
        p = proposal['proposed']
        heading = '동의한 변경 조건' if proposal['status'] == 'accepted' else '변경 제안 · '+('답변 대기' if proposal['status'] == 'pending' else '거절됨')
        result[heading] = f'{p["label"]} · GPU {p["gpu"]} / 전력 {p["power"]} · 원래 완료 기한 유지'
    return result
