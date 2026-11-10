"""Chapter 3 진행 상태와 네트워크 진단 값. 네트워크 장애의 원인을 확인하고 원인에 맞는 대응을 고르는 교육 미션.

GUI/SQLite와 독립입니다. 단계는 실제 요청/배정/장애/진단/대응 사실에서 계산하며 안내를 읽은 것만으로 업무 단계를
완료하지 않습니다. 저장은 스토리 JSON의 선택 필드 `chapter3`로만 합니다.
미션 A(통신 경로 단절)와 미션 B(가용 대역폭 부족)는 이 교육 구성에서만 성립하는 규칙입니다.
"""
from dataclasses import dataclass, field


STEPS3 = ('briefing', 'a_start', 'a_incident', 'a_diagnose', 'a_respond', 'a_finish',
          'b_start', 'b_incident', 'b_diagnose', 'b_respond', 'b_finish')
EVENTS3 = tuple('c3_'+step for step in STEPS3) + ('c3_done',)
CHAPTER3_COUNTRIES = ('싱가포르', '미국')
CHAPTER3_SCENARIOS = ('ch3_path', 'ch3_bw')
KIND_LABELS = {'path_down': '통신 경로 단절', 'bandwidth': '가용 대역폭 부족'}
RESPONSE_LABELS = {'reroute': '백업 경로 우회', 'compress': '전송 데이터 압축', 'ignore': '기존 설정 유지'}


def mission_over(run):
    """장애 미션이 더 진행되지 않는 상태: 정상 완료, 최종 보고로 닫은 실패, 거절, 기한 만료.
    실패했지만 재처리/최종 보고가 남은 작업은 아직 끝나지 않은 것으로 봅니다."""
    s = run.state
    if run.request['status'] == 'rejected' or run.terms.get('expired'):
        return True
    return s.phase == 'finished' and ((run.request['status'] == 'completed' and bool(s.succeeded)) or run.followup_closed)


@dataclass
class Chapter3Progress:
    request_ids: list[int]
    completed_steps: list[str] = field(default_factory=list)
    briefing_confirmed: bool = False
    diagnosed: list[int] = field(default_factory=list)       # 진단창을 실제로 연 요청
    feedback_seen: list[str] = field(default_factory=list)   # 이미 보여 준 선배 피드백 키(같은 사건은 한 번만)
    records: dict = field(default_factory=dict)              # 요청 id(문자열) -> 마지막 장애 기록(재처리로 상태가 바뀌어도 유지)
    progress_version: int = 1

    def __post_init__(self):
        if (not isinstance(self.request_ids, list) or not 1 <= len(self.request_ids) <= 2
                or any(type(v) is not int or v < 1 for v in self.request_ids)
                or len(set(self.request_ids)) != len(self.request_ids)
                or type(self.progress_version) is not int or self.progress_version != 1
                or type(self.briefing_confirmed) is not bool
                or not isinstance(self.completed_steps, list)
                or self.completed_steps != list(STEPS3[:len(self.completed_steps)])):
            raise ValueError('저장된 Chapter 3 진행 상태가 올바르지 않습니다.')
        if (len(self.request_ids) == 1 and len(self.completed_steps) > STEPS3.index('b_start')
                or not isinstance(self.diagnosed, list) or any(v not in self.request_ids for v in self.diagnosed)
                or len(set(self.diagnosed)) != len(self.diagnosed)
                or not isinstance(self.feedback_seen, list) or any(not isinstance(v, str) for v in self.feedback_seen)
                or len(set(self.feedback_seen)) != len(self.feedback_seen)
                or not isinstance(self.records, dict)
                or any(k not in {str(v) for v in self.request_ids} or not isinstance(v, dict) for k, v in self.records.items())):
            raise ValueError('저장된 Chapter 3 확인 기록이 올바르지 않습니다.')

    @property
    def completed(self):
        return len(self.completed_steps) == len(STEPS3)

    @property
    def step(self):
        return STEPS3[min(len(self.completed_steps), len(STEPS3)-1)]

    def mark_diagnosed(self, request_id):
        if request_id in self.request_ids and request_id not in self.diagnosed:
            self.diagnosed.append(request_id)

    def update(self, runs):
        """실제 사실에서 완료 단계를 늘립니다. 단계는 줄어들지 않습니다.
        작업이 이미 끝난(시간 초과 실패 등) 요청의 진단/대응 단계는 더 이상 할 수 없으므로 통과시키되 기록(diagnosed)에는 남기지 않습니다."""
        facts = [self.briefing_confirmed]
        for index in range(2):
            run = runs[self.request_ids[index]] if index < len(self.request_ids) else None
            if run is None:
                facts += [False]*5
                continue
            rid, s = run.request['id'], run.state
            record = self.records.get(str(rid), {})
            # 작업이 끝났거나 요청이 거절/만료된 뒤에는 더 할 수 있는 행동이 없으므로 단계를 통과시킵니다(기록에는 남기지 않음).
            over = s.phase == 'finished' or mission_over(run)
            facts += [run.playthrough_id is not None or over,
                      s.incident_occurred or bool(record) or over,
                      rid in self.diagnosed or over,
                      s.response_attempts > 0 or bool(record.get('attempts')) or over,
                      mission_over(run)]
        for index, key in enumerate(STEPS3):
            if key in self.completed_steps:
                continue
            if not facts[index]:
                break
            self.completed_steps.append(key)


def network_diagnosis(state, hardware_issue='', downtime_note=''):
    """진단창에 표시할 관측 값. 모든 값은 GameState의 실제 필드에서 읽으며 정답 대응은 포함하지 않습니다."""
    if not state.incident_kind:
        raise ValueError('진단할 네트워크 장애가 없습니다.')
    primary = 'UP' if state.primary_up else 'DOWN'
    if state.incident_kind == 'path_down':
        observations = ['주 통신 경로: 링크 신호 없음 · 현재 경로로 데이터를 전송할 수 없음', '전송률: 0']
        backup_note = f'백업 경로: UP · 용량 {state.backup_capacity}'
        summary = '통신 경로 이상 · 전송률 0'
    else:
        observations = ['주 통신 경로: 링크 연결됨 · 대역폭 사용률 한계 · 전송 지연 증가',
                        f'전송률: 가용 대역폭 {state.network_available}에 제한']
        backup_note = f'백업 경로: UP · 용량 {state.backup_capacity} · 같은 병목 공유'
        summary = '대역폭 한계 · 전송 지연'
    # 우회/압축 뒤의 현재 상태도 그대로 반영합니다.
    if state.rerouted:
        backup_note += ' · 현재 우회 중'
    equipment = hardware_issue or 'GPU·서버 장비 정상 (네트워크만 문제)'
    return {'kind': state.incident_kind, 'summary': summary, 'observations': observations, 'primary': primary,
            'needed': state.network_needed, 'available': state.network_available, 'link_ok': state.link_ok,
            'backup': backup_note, 'equipment': equipment, 'equipment_ok': not hardware_issue,
            'downtime': state.downtime, 'limit': 60, 'progress': round(state.progress), 'phase': state.phase,
            'attempts': state.response_attempts, 'responses': list(state.response_log)}


def diagnosis_lines(d):
    lines = ['네트워크 진단 정보'] + ['· '+text for text in d['observations']]
    lines += [f'주 통신 경로 상태: {d["primary"]}',
              f'작업 필요 대역폭: {d["needed"]}',
              f'현재 가용 대역폭: {d["available"]}' + ('' if d['link_ok'] else ' (사용 가능한 경로 없음)'),
              d['backup'], f'장비 상태: {d["equipment"]}',
              f'네트워크 장애로 중단된 시간: {d["downtime"]}/{d["limit"]}분',
              f'현재 작업 진행률: {d["progress"]}%',
              f'대응 {d["attempts"]}/3회' + (' · 시도: '+' → '.join(RESPONSE_LABELS[r] for r in d['responses']) if d['responses'] else '')]
    return lines
