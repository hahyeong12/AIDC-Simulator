"""Chapter 3b 진행 상태와 표시 값. 서버 장비 장애에서 장비 복구와 작업 이전을 자원·시간으로 비교하는 심화 교육.

GUI/SQLite와 독립입니다. 기존 하드웨어 엔진(ServerHealth·migration_preview·migrate)을 그대로 쓰며, 단계는 실제 요청/배정/장애/진단/
선택 사실에서 계산합니다. 안내를 읽은 것만으로 업무 단계를 완료하지 않습니다. 저장은 스토리 JSON의 선택 필드 `chapter3b`로만 합니다.
이 장의 서버 구성과 시간은 교육용 설정입니다.
"""
from dataclasses import dataclass, field

from chapter3 import mission_over
from game import game_time

STEPS3B = ('briefing', 'a_start', 'a_fault', 'a_diagnose', 'a_respond', 'a_finish',
           'b_start', 'b_fault', 'b_diagnose', 'b_respond', 'b_finish')
EVENTS3B = tuple('c3b_'+step for step in STEPS3B) + ('c3b_done',)
CHAPTER3B_COUNTRIES = ('일본', '싱가포르')
CHAPTER3B_SCENARIOS = ('ch3b_jp', 'ch3b_sg')
CHOICE_LABELS = {'repair': '장비 복구', 'migrate': '작업 이전'}


@dataclass
class Chapter3bProgress:
    request_ids: list[int]
    completed_steps: list[str] = field(default_factory=list)
    briefing_confirmed: bool = False
    diagnosed: list[int] = field(default_factory=list)      # 장비 진단창(이전 가능 여부 포함)을 실제로 연 요청
    feedback_seen: list[str] = field(default_factory=list)  # 이미 보여 준 결과 카드 키
    records: dict = field(default_factory=dict)             # 요청 id(문자열) -> 장애·선택 기록
    progress_version: int = 1

    def __post_init__(self):
        if (not isinstance(self.request_ids, list) or not 1 <= len(self.request_ids) <= 2
                or any(type(v) is not int or v < 1 for v in self.request_ids)
                or len(set(self.request_ids)) != len(self.request_ids)
                or self.progress_version != 1 or type(self.briefing_confirmed) is not bool
                or not isinstance(self.completed_steps, list)
                or self.completed_steps != list(STEPS3B[:len(self.completed_steps)])
                or (len(self.request_ids) == 1 and len(self.completed_steps) > STEPS3B.index('b_start'))):
            raise ValueError('저장된 Chapter 3b 진행 상태가 올바르지 않습니다.')
        if (not isinstance(self.diagnosed, list) or any(v not in self.request_ids for v in self.diagnosed)
                or len(set(self.diagnosed)) != len(self.diagnosed)
                or not isinstance(self.feedback_seen, list) or any(not isinstance(v, str) for v in self.feedback_seen)
                or len(set(self.feedback_seen)) != len(self.feedback_seen)
                or not isinstance(self.records, dict)
                or any(k not in {str(v) for v in self.request_ids} or not isinstance(v, dict) for k, v in self.records.items())):
            raise ValueError('저장된 Chapter 3b 확인 기록이 올바르지 않습니다.')

    @property
    def completed(self):
        return len(self.completed_steps) == len(STEPS3B)

    @property
    def step(self):
        return STEPS3B[min(len(self.completed_steps), len(STEPS3B)-1)]

    def mark_diagnosed(self, request_id):
        if request_id in self.request_ids and request_id not in self.diagnosed:
            self.diagnosed.append(request_id)

    def update(self, runs):
        """실제 사실에서 완료 단계를 늘립니다. 작업이 이미 끝나 더 할 수 없는 단계만 통과시킵니다."""
        facts = [self.briefing_confirmed]
        for index in range(2):
            run = runs[self.request_ids[index]] if index < len(self.request_ids) else None
            if run is None:
                facts += [False]*5
                continue
            rid = run.request['id']
            record = self.records.get(str(rid), {})
            over = run.state.phase == 'finished' or mission_over(run)
            facts += [run.playthrough_id is not None or over,
                      bool(record) or over,
                      rid in self.diagnosed or over,
                      bool(record.get('choices')) or over,
                      mission_over(run)]
        for index, key in enumerate(STEPS3B):
            if key in self.completed_steps:
                continue
            if not facts[index]:
                break
            self.completed_steps.append(key)


def fault_server_for(config_server, allocation):
    """교육용 장애 서버. 설정한 서버가 작업에 쓰이면 그 서버, 아니면 GPU를 가장 많이 쓰는 서버."""
    ids = [part.server_id for part in allocation.slices]
    if config_server in ids:
        return config_server
    return max(allocation.slices, key=lambda part: part.gpu).server_id


def impossible_reason(normal_gpu, normal_power, need_gpu, need_power):
    if normal_gpu < need_gpu:
        return (f'정상 서버의 가용 GPU는 {normal_gpu}개입니다. 현재 작업은 GPU {need_gpu}개가 필요하므로 전체 작업 이전이 불가능합니다.')
    if normal_power < need_power:
        return (f'정상 서버의 가용 전력은 {normal_power}단위입니다. 현재 작업은 전력 {need_power}단위가 필요하므로 전체 작업 이전이 불가능합니다.')
    return '정상 서버의 GPU와 전력을 한 번에 묶을 수 없어 전체 작업 이전이 불가능합니다.'


def diagnosis_rows(d):
    """진단창 표(이름, 값, 강조) 목록. 값은 모두 세션이 계산한 현재 상태입니다."""
    normal = ' · '.join(f'{n["key"]} {n["gpu"]}/{n["power"]}' for n in d['normal']) or '없음'
    return [
        ('장애 서버', f'Server {d["server"]} · {d["health"]}' + (f' · 복구 {d["repair_left"]}분' if d['repair_left'] else ''), 'bad'),
        ('영향 작업', f'{d["company"]} · {d["mode"]}', None),
        ('서버 점유', f'GPU {d["slice_gpu"]} / 전력 {d["slice_power"]}', None),
        ('정상 서버 가용', f'GPU {d["normal_gpu"]} / 전력 {d["normal_power"]}  ({normal})', None),
        ('필요 자원', f'GPU {d["need_gpu"]} / 전력 {d["need_power"]}', None),
        ('작업 이전', '가능' if d['migrate_possible'] else '불가능', 'good' if d['migrate_possible'] else 'bad'),
        ('장비 복구 예상', f'{d["repair_minutes"]}분 → {d["repair_finish_label"]}' + _flag(d['repair_on_time']), None),
        ('작업 이전 예상', (f'{d["migrate_minutes"]}분 → {d["migrate_finish_label"]}' + _flag(d['migrate_on_time']))
         if d['migrate_possible'] else '해당 없음', None),
        ('고객 완료 기한', d['due_label'] or '없음', None),
        ('중단 시간', f'{d["downtime"]}분', None),
    ]


def _flag(on_time):
    return '' if on_time is None else (' · 기한 내' if on_time else ' · 기한 초과')


def card(kind, record, closed=False):
    """결과 카드. kind: 'repair'|'migrate'(선택 직후)|'failed'(작업 최종 실패). 저장된 기록의 사실만 씁니다."""
    server = f'Server {record["server"]}'
    if kind == 'repair':
        rows = [('장애 서버', server), ('선택 대응', '장비 복구'),
                ('실제 결과', f'복구 시작 · {record["repair_minutes"]}분 후 기존 배정으로 재개')]
        if record.get('migrate_finish') is None:
            rows.insert(2, ('작업 이전', '불가능 · 정상 서버 자원 부족'))
            mentor = (f'{record["need_gpu"]}개 GPU가 필요하지만 정상 서버에는 {record["normal_gpu"]}개만 남아 있어 작업을 옮길 수 없습니다. '
                      '시간 버튼을 눌러 복구를 진행하세요.')
        else:
            rows.append(('예상 완료', f'{game_time(record["repair_finish"])} · 기한 {game_time(record["due"])}'))
            mentor = '장비 복구를 시작했습니다. 시간 버튼으로 20분이 지나면 기존 배정 그대로 작업이 재개됩니다.'
        return {'kind': kind, 'title': '장비 복구 시작', 'tone': 'success', 'rows': rows, 'mentor': mentor}
    if kind == 'migrate':
        rows = [('장애 서버', server), ('선택 대응', '작업 이전'),
                ('실제 결과', f'새 배정 {record.get("parts", "")} · 준비 10분'),
                ('예상 완료', f'{game_time(record["migrate_finish"])} · 기한 {game_time(record["due"])}')]
        return {'kind': kind, 'title': '작업 이전 확정', 'tone': 'success', 'rows': rows,
                'mentor': '다른 서버에서 10분 준비 후 작업을 재개합니다. 진행률과 운영 모드, 완료 기한은 그대로 유지됩니다.'}
    if kind == 'failed':
        tried = ' → '.join(CHOICE_LABELS[c] for c in record['choices']) or '대응 없음'
        return {'kind': kind, 'title': 'SERVER RECOVERY FAILED', 'tone': 'fail',
                'rows': [('장애 서버', server), ('시도한 대응', tried), ('복구 결과', '작업 실패'),
                         ('작업 상태', '실패 · 최종 보고 완료' if closed else '실패 · 후속 처리 필요')],
                'mentor': '이번에는 작업을 끝내지 못했습니다. 복구와 이전 중 무엇이 가능했고 기한에 어떤 영향을 줬는지 다시 살펴보세요.'}
    raise ValueError('알 수 없는 Chapter 3b 결과 카드입니다.')


def result_outcome(job):
    summary = job['job']
    if summary['key'] == 'on_time':
        return '기한 내 완료'
    if summary['key'] == 'late':
        return f'기한 초과 완료 ({summary["deadline"]})'
    return summary['label']


def mentor_lines(jobs, ok):
    """선배 분석 3문장 이내. 저장된 선택 시점의 예상 시각과 실제 결과에서만 만듭니다."""
    lines = []
    for index, job in enumerate(jobs):
        record = job['record']
        if not record.get('choices'):
            continue
        name = 'AB'[index]
        choice = record['choices'][-1]
        if choice == 'migrate':
            gap = ''
            if record.get('repair_finish') is not None and record['repair_finish'] > record['due'] >= record['migrate_finish']:
                gap = ' 복구를 기다렸다면 기한을 넘겼을 것입니다.'
            lines.append(f'{name}: 정상 서버에 자원이 있어 작업을 이전했고{"" if job["on_time"] else " 그래도"} '
                         f'{"기한 내에 끝냈습니다." if job["on_time"] else "기한을 지키지 못했습니다."}{gap}')
        elif record.get('migrate_finish') is None:
            lines.append(f'{name}: 정상 서버 GPU {record["normal_gpu"]}개로는 GPU {record["need_gpu"]}개 작업을 옮길 수 없어 장비 복구가 맞는 선택이었습니다.')
        else:
            note = (f' 이전했다면 {game_time(record["migrate_finish"])}에 끝낼 수 있었습니다.'
                    if record['migrate_finish'] <= record['due'] < record['repair_finish'] else '')
            lines.append(f'{name}: 이전이 가능했지만 장비 복구를 선택했습니다.'
                         f'{" 기한 내에 끝냈습니다." if job["on_time"] else " 기한을 넘겼습니다."}{note}')
    lines.append(f'최종 결과: 두 장애 중 {ok}개를 기한 내 정상 완료했습니다.')
    return lines[:3]
