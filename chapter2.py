"""Chapter 2 진행 상태. 여러 고객의 요청을 비교하고 같은 서버 원장을 나누어 쓰는 교육 미션.

GUI/SQLite와 독립입니다. 단계는 실제 요청/배정/작업 사실에서 계산하며 안내를 읽은 것만으로
업무 단계를 완료하지 않습니다. 저장은 스토리 JSON의 선택 필드 `chapter2`로만 합니다.
"""
from dataclasses import dataclass, field

STEPS2 = ('briefing', 'requests', 'review', 'allocate', 'progress', 'finish')
EVENTS2 = tuple('c2_'+step for step in STEPS2) + ('c2_done',)
# 교육용으로 고정한 두 고객. 요구량·기한·허용 모드는 기존 국가별 규칙을 그대로 사용합니다.
CHAPTER2_COUNTRIES = ('일본', '미국')
# 최종 실패로 확정된 이유: 기한 만료 미처리, 거절, 재처리 종료, 기한 초과 완료, 기한 내 완료가 불가능함이 확정됨
FAILURE_REASONS = ('expired', 'rejected', 'failed', 'late', 'late_certain')
# 요청 조건(GPU·전력·작업량·기한)은 game.SCENARIOS의 같은 이름을 사용합니다.
CHAPTER2_SCENARIOS = {'일본': 'ch2_jp', '미국': 'ch2_us'}


def is_resolved(run):
    """고객 요청에 대해 플레이어가 실제 결정을 내린 상태: 배정 시작, 거절, 기한 만료."""
    return (run.playthrough_id is not None or run.request['status'] == 'rejected'
            or bool(run.terms.get('expired')))


def is_finished(run):
    """더 이상 처리할 일이 없는 상태: 정상 완료, 재처리 종료한 실패, 거절, 기한 만료."""
    s = run.state
    return (run.request['status'] == 'rejected' or bool(run.terms.get('expired'))
            or (s.phase == 'finished' and (run.request['status'] == 'completed' or run.followup_closed)))


@dataclass
class Chapter2Progress:
    jp_request_id: int
    us_request_id: int
    completed_steps: list[str] = field(default_factory=list)
    briefing_confirmed: bool = False
    requests_read: list[int] = field(default_factory=list)
    reviewed: list[int] = field(default_factory=list)
    progress_version: int = 1
    # 처음 확정된 미션 실패의 기록(저장 시각의 사실만 담은 문자열/숫자 사전). 한 번 기록되면 지우거나 성공으로 바꾸지 않습니다.
    failure: dict | None = None
    failure_seen: bool = False  # 선배의 실패 피드백을 이미 보여 주었는지(같은 실패 이벤트는 한 번만)

    def __post_init__(self):
        ids = (self.jp_request_id, self.us_request_id)
        if (any(type(v) is not int or v < 1 for v in ids) or ids[0] == ids[1]
                or type(self.progress_version) is not int or self.progress_version != 1
                or type(self.briefing_confirmed) is not bool
                or not isinstance(self.completed_steps, list)
                or self.completed_steps != list(STEPS2[:len(self.completed_steps)])):
            raise ValueError('저장된 Chapter 2 진행 상태가 올바르지 않습니다.')
        if (type(self.failure_seen) is not bool
                or (self.failure is not None and (not isinstance(self.failure, dict)
                                                  or self.failure.get('request_id') not in ids
                                                  or self.failure.get('reason') not in FAILURE_REASONS))
                or (self.failure is None and self.failure_seen)):
            raise ValueError('저장된 Chapter 2 실패 기록이 올바르지 않습니다.')
        for values in (self.requests_read, self.reviewed):
            if (not isinstance(values, list) or any(type(v) is not int or v not in ids for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError('저장된 Chapter 2 확인 기록이 올바르지 않습니다.')

    @property
    def request_ids(self):
        return (self.jp_request_id, self.us_request_id)

    @property
    def completed(self):
        return len(self.completed_steps) == len(STEPS2)

    @property
    def step(self):
        return STEPS2[min(len(self.completed_steps), len(STEPS2)-1)]

    def mark_read(self, request_id):
        if request_id in self.request_ids and request_id not in self.requests_read:
            self.requests_read.append(request_id)

    def mark_reviewed(self, request_id):
        if request_id in self.request_ids and request_id not in self.reviewed:
            self.reviewed.append(request_id)

    def update(self, runs):
        """실제 요청/배정/작업 사실에서 완료 단계를 늘립니다. 단계는 줄어들지 않습니다."""
        both = [runs[rid] for rid in self.request_ids]
        facts = (
            self.briefing_confirmed,
            # 읽지 않고 바로 배정한 요청도 조건을 확인할 기회를 막지 않도록 결정 완료를 허용합니다.
            all(r.request['id'] in self.requests_read or is_resolved(r) for r in both),
            all(r.request['id'] in self.reviewed or is_resolved(r) for r in both),
            all(is_resolved(r) for r in both),
            any(r.state.work_done > 0 for r in both) or all(is_finished(r) for r in both),
            all(is_finished(r) for r in both),
        )
        for index, key in enumerate(STEPS2):
            if key in self.completed_steps:
                continue
            if not facts[index]:
                break
            self.completed_steps.append(key)
