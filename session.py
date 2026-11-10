"""요청 접수, 가상 시간, 동시 운영과 SQLite 저장의 일관성을 관리합니다."""
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from copy import deepcopy
import random

from database import Database
from game import DataCenter, GameState, RESPONSES, request_terms, request_conditions, game_time
from server_resources import ServerPool, Allocation, SERVERS, ServerHealth
from story import StoryProgress
from result_summary import customer_reaction, outcome_key, job_summary, chapter1_summary, chapter2_summary
from chapter2 import Chapter2Progress, CHAPTER2_COUNTRIES, CHAPTER2_SCENARIOS, is_finished

REQUEST_LABELS = {'new':'신규 요청','review':'검토 중','waiting':'대기',
                  'operating':'수락','rejected':'거절','completed':'처리 완료'}
REJECTION_REASONS = ('현재 GPU 자원 부족','전력 공급 여유 부족','요청한 운영 조건을 충족하기 어려움','기타 사유')
ARRIVAL_INTERVAL = 30
CUSTOMER_COOLDOWN = 60
MAX_PENDING_REQUESTS = 2


@dataclass
class MissionRun:
    mission: object
    state: GameState
    request: dict = field(default_factory=dict)
    playthrough_id: int | None = None
    messages: list[str] = field(default_factory=list)
    followup_closed: bool = False
    last_feedback: str = ''
    delay_notified: bool = False
    delay_notice_key: list | None = None
    terms: dict = field(default_factory=dict)
    message_read_id: int = 0
    proposals: list[dict] = field(default_factory=list)
    conditions: dict = field(default_factory=dict)
    server_allocations: list = field(default_factory=list)
    hardware_downtime: int = 0
    migration_left: int = 0
    migration_downtime: int = 0


class GameSession:
    def __init__(self, db: Database, seed=None, incident_chance=None, mode='free', start_chapter=1):
        self.db, self.center = db, DataCenter()
        self.servers = ServerPool()
        self.missions = {m['id']:m for m in db.get_missions()}
        saved = db.get_simulation()
        if mode not in ('free', 'story'):
            raise ValueError('존재하지 않는 게임 모드입니다.')
        if start_chapter not in (1, 2) or (start_chapter == 2 and (mode != 'story' or saved)):
            raise ValueError('Chapter 2 연습은 비어 있는 새 스토리 슬롯에서만 시작할 수 있습니다.')
        if saved and saved.get('mode', 'free') != mode:
            raise ValueError('선택한 모드와 저장 파일이 다릅니다. 모드별 저장 파일을 사용해 주세요.')
        if mode == 'story' and not saved and db.get_requests():
            raise ValueError('기존 자유 운영 요청을 스토리로 변경할 수 없습니다.')
        self.mode = mode
        if saved and mode == 'story' and not isinstance(saved.get('story'), dict):
            raise ValueError('저장된 스토리 진행 기록을 찾을 수 없습니다.')
        self.story = None
        if mode == 'story' and not saved:
            self.story = StoryProgress(practice=start_chapter == 2)
        self.minute = saved['minute'] if saved else 540
        self.seed = saved['seed'] if saved else (seed if seed is not None else random.SystemRandom().randrange(2**31))
        self.roll_index = saved['roll_index'] if saved else 0
        self.incident_chance = saved['incident_chance'] if saved else (.45 if incident_chance is None else incident_chance)
        if not 0 <= self.incident_chance <= 1:
            raise ValueError('장애 확률은 0~1이어야 합니다.')
        self.runs = {}
        self.selected_id = None
        for request in db.get_requests():
            self.runs[request['id']] = self._load_run(request)
        if mode == 'story' and saved and saved['story'].get('practice') is True:
            self.story = StoryProgress.from_payload(saved['story'], None, False)
        elif mode == 'story' and saved:
            rid = saved['story'].get('request_id')
            if type(rid) is not int or rid not in self.runs:
                raise ValueError('스토리의 첫 고객 요청을 찾을 수 없습니다.')
            run = self.runs[rid]
            self.story = StoryProgress.from_payload(saved['story'], run, self.plan_agreed(run, run.state.plan))
        if saved and self.story and not self.story.practice and (self.story.request_id not in self.runs
                or self.runs[self.story.request_id].mission['country'] != '싱가포르'):
            raise ValueError('스토리의 첫 고객 요청을 찾을 수 없습니다.')
        if saved:
            self._validate_chapter2()
        self._restore_servers()
        hardware = saved.get('server_health', {}) if saved else {}
        if not isinstance(hardware, dict) or set(hardware)-{s.key for s in SERVERS}:
            raise ValueError('저장된 서버 상태의 식별자가 올바르지 않습니다.')
        # 기존 배정은 장애 상태여도 그대로 복원한 다음 신규 배정을 차단합니다.
        self.servers.hardware = {s.key:ServerHealth(**hardware.get(s.key, {})) for s in SERVERS}
        arrivals = saved.get('arrivals', {}) if saved else {}
        # 이전 저장 파일은 현재 시각 이후부터 새 일정을 시작하며 과거 요청을 재생성하지 않습니다.
        self.next_arrival_minute = arrivals.get('next_minute', self.minute + ARRIVAL_INTERVAL)
        self.arrival_index = arrivals.get('slot', 0)
        self.arrival_last = {int(mid):minute for mid,minute in arrivals.get('last_by_mission', {}).items()}
        if not arrivals:
            for rid, run in self.runs.items():
                times = [e['game_minute'] for e in db.get_request_events(rid) if e['kind']=='arrival']
                mid = run.mission['id']
                self.arrival_last[mid] = max(self.arrival_last.get(mid, self.minute-CUSTOMER_COOLDOWN),
                                             max(times, default=self.minute-CUSTOMER_COOLDOWN))
        if not self.runs:
            self.deliver_next_request()
        if self.story and not self.story.practice and self.story.request_id not in self.runs:
            raise ValueError('스토리의 첫 고객 요청을 찾을 수 없습니다.')
        self.selected_id = next((rid for rid,r in self.runs.items() if r.request['status'] not in ('completed','rejected')),
                                next(reversed(self.runs)))
        if saved and self.story and self.story.chapter2 is not None:
            self._detect_chapter2_failure(on_load=True)

    @property
    def current(self):
        return self.runs[self.selected_id]
    @property
    def time_label(self):
        return f'D{self.minute//1440+1} {self.minute//60%24:02d}:{self.minute%60:02d}'
    @property
    def has_next_request(self):
        if self.story:
            return False
        received = {r.mission['id'] for r in self.runs.values()}
        return any(mid not in received for mid in self.missions)

    @property
    def pending_request_count(self):
        return sum(r.request['status'] in ('new','review','waiting') for r in self.runs.values())

    @property
    def next_arrival_label(self):
        minute = self.next_arrival_minute
        return f'D{minute//1440+1} {minute//60%24:02d}:{minute%60:02d}'

    def _load_run(self, request):
        mission = self.missions[request['mission_id']]
        snapshot = self.db.get_runtime(request['id'])
        if snapshot:
            s = GameState(center=self.center, **snapshot['state'])
            if s.allocated and not self.center.allocate(s.gpu_used, s.power_used):
                raise ValueError('저장된 자원 배정이 데이터센터 용량을 초과합니다.')
            run = MissionRun(mission,s,dict(request),request['playthrough_id'],
                             followup_closed=snapshot['followup_closed'], last_feedback=snapshot['last_feedback'],
                             delay_notified=snapshot['delay_notified'], terms=snapshot.get('terms', {}),
                             message_read_id=snapshot.get('message_read_id', 0),
                             proposals=snapshot.get('proposals', []),
                             conditions=snapshot.get('conditions', {}),
                             server_allocations=[Allocation.from_payload(a) for a in snapshot.get('server_allocations', [])],
                             hardware_downtime=snapshot.get('hardware_downtime', 0),
                             migration_left=snapshot.get('migration_left', 0),
                             migration_downtime=snapshot.get('migration_downtime', 0),
                             delay_notice_key=snapshot.get('delay_notice_key'))
            if (any(type(v) is not int or v < 0 for v in (run.hardware_downtime, run.migration_left, run.migration_downtime))
                    or run.migration_left not in (0, 10) or (run.migration_left and not s.allocated)):
                raise ValueError('저장된 하드웨어 중단/이전 시간이 올바르지 않습니다.')
        else:
            s = GameState(center=self.center,country=mission['country'])
            run = MissionRun(mission,s,dict(request),request['playthrough_id'])
            if run.playthrough_id is not None:
                record = self.db.get_playthrough(run.playthrough_id)
                if record['mission_id'] != mission['id']:
                    raise ValueError('요청과 수행의 미션이 일치하지 않습니다.')
                if request['status'] == 'operating':
                    if record['status'] != '진행중':
                        raise ValueError('요청과 수행의 상태가 일치하지 않습니다.')
                    s.choose_plan(record['plan'])
                    s.trigger_incident()  # v0.5의 이미 발생한 장애 상태를 보존합니다.
                else:
                    p = s.plans[record['plan']]
                    s.phase, s.plan = 'finished', record['plan']
                    s.gpu_used, s.power_used = p['gpu'], p['power']
                    s.network_needed, s.network_available = p['network'], 2
                    s.response, s.score = record['response'], record['score']
                    s.succeeded, s.result_text = record['status']=='성공', record['result_text']
                    s.work_done = s.work_total if s.succeeded else 0
                    run.followup_closed = True  # 이전 버전 완료 기록은 재판정하지 않습니다.
        events = self.db.get_request_events(request['id'])
        run.messages = [row['message'] for row in events] if events else (
            [row['message'] for row in self.db.get_logs(run.playthrough_id)] if run.playthrough_id else [])
        if snapshot and run.delay_notified and 'delay_notice_key' not in snapshot:
            # 이전 저장의 전송 여부를 현재 상황에 연결하여 같은 안내의 재전송을 막습니다.
            run.delay_notice_key = self._delay_notice_key(run)
        return run

    def _restore_servers(self):
        legacy = []
        for run in self.runs.values():
            if not run.state.allocated:
                continue
            current = next((a for a in reversed(run.server_allocations) if a.playthrough_id == run.playthrough_id), None)
            if current is not None:
                if (current.gpu, current.power) != (run.state.gpu_used, run.state.power_used):
                    raise ValueError('저장된 서버 배정과 작업 자원 조건이 일치하지 않습니다.')
                self.servers.reserve(current)
            else:
                legacy.append((run.playthrough_id, run.state.gpu_used, run.state.power_used))
        self.servers.restore_legacy(legacy)
        for run in self.runs.values():
            if run.state.allocated and not any(a.playthrough_id == run.playthrough_id for a in run.server_allocations):
                run.server_allocations.append(self.servers.allocations[run.playthrough_id])

    def _persist(self):
        payload = {'minute':self.minute,'seed':self.seed,'roll_index':self.roll_index,
                                 'server_health':{key:asdict(value) for key,value in self.servers.hardware.items()},
                                 'incident_chance':self.incident_chance,
                                 'arrivals':{'next_minute':self.next_arrival_minute, 'slot':self.arrival_index,
                                             'last_by_mission':self.arrival_last}}
        if self.story:
            payload.update(mode=self.mode, story=self.story.payload())
        self.db.save_simulation(payload)
        for rid,run in self.runs.items():
            state = {k:v for k,v in vars(run.state).items() if k != 'center'}
            self.db.save_runtime(rid,run.playthrough_id,{'state':state,'followup_closed':run.followup_closed,
                                  'last_feedback':run.last_feedback,'delay_notified':run.delay_notified,
                                  'delay_notice_key':run.delay_notice_key,
                                  'terms':run.terms, 'message_read_id':run.message_read_id,
                                  'proposals':run.proposals, 'conditions':run.conditions,
                                  'hardware_downtime':run.hardware_downtime, 'migration_left':run.migration_left,
                                  'migration_downtime':run.migration_downtime,
                                  'server_allocations':[a.payload() for a in run.server_allocations], 'version':2})

    @contextmanager
    def _atomic(self):
        before = {rid:(run, {**vars(run), 'terms':deepcopy(run.terms), 'proposals':deepcopy(run.proposals),
                            'conditions':deepcopy(run.conditions)}, vars(run.state).copy(),list(run.messages),dict(run.request))
                  for rid,run in self.runs.items()}
        usage = self.center.gpu_used,self.center.power_used
        clock = self.minute,self.roll_index,self.selected_id
        arrivals = self.next_arrival_minute,self.arrival_index,dict(self.arrival_last)
        allocations = dict(self.servers.allocations)
        hardware = dict(self.servers.hardware)
        story = deepcopy(self.story)
        histories = {rid:list(run.server_allocations) for rid, run in self.runs.items()}
        try:
            with self.db.transaction():
                yield
                if self.story and self.story.request_id in self.runs:
                    run = self.runs[self.story.request_id]
                    self.story.update(run, self.plan_agreed(run, run.state.plan))
                if self.story and self.story.chapter2 is not None:
                    self.story.chapter2.update(self.runs)
                    self._detect_chapter2_failure()
                self._persist()
        except Exception:
            self.runs.clear()
            for rid,(run,fields,state,messages,request) in before.items():
                vars(run).update(fields)
                vars(run.state).update(state)
                run.messages, run.request = messages,request
                run.server_allocations = histories[rid]
                self.runs[rid] = run
            self.center.gpu_used,self.center.power_used = usage
            self.minute,self.roll_index,self.selected_id = clock
            self.next_arrival_minute,self.arrival_index,self.arrival_last = arrivals
            self.servers.allocations = allocations
            self.servers.hardware = hardware
            self.story = story
            raise

    def mark_story_dialogue(self, event):
        """표시 사실만 저장합니다. 대화는 업무 확인/완료를 대신하지 않습니다."""
        if not self.story or event != self.story.dialogue_event:
            raise ValueError('현재 사건의 대화가 아닙니다.')
        if event not in self.story.dialogue_seen:
            with self._atomic():
                self.story.dialogue_seen.append(event)

    def select_story_server(self, server_id):
        if not self.story or self.story.tutorial_completed or self.story.chapter2 is not None:
            return
        if server_id not in {s.key for s in SERVERS}:
            raise ValueError('존재하지 않는 서버입니다.')
        with self._atomic():
            # A 선택의 실제 관찰을 보존하며 이후 다른 서버를 봐도 교육 이력을 지우지 않습니다.
            if server_id == 'A':
                self.story.selected_server = server_id

    def confirm_story_resources(self):
        if not self.story or self.story.step != 'resources':
            raise ValueError('먼저 Server A를 선택하고 Inspector를 확인해 주세요.')
        with self._atomic():
            self.story.resources_confirmed = True

    def confirm_story_arrival(self):
        if not self.story or self.story.step != 'arrival':
            raise ValueError('현재는 첫 출근 안내 단계가 아닙니다.')
        with self._atomic():
            self.story.introduction_confirmed = True

    def inspect_story_preview(self, request_id):
        if self.story and self.story.chapter2_active:
            # Chapter 2: 비교 창에서 계획을 직접 고른 요청만 검토로 기록합니다.
            if request_id in self.story.chapter2.request_ids and request_id not in self.story.chapter2.reviewed:
                with self._atomic():
                    self.story.chapter2.mark_reviewed(request_id)
            return
        if not self.story or self.story.tutorial_completed or self.story.preview_confirmed:
            return
        if request_id != self.story.request_id or not self.story.request_read:
            return
        with self._atomic():
            self.story.preview_confirmed = True

    def confirm_story_operations(self):
        if not self.story or self.story.step != 'operations':
            raise ValueError('현재는 운영 상태 확인 단계가 아닙니다.')
        if self.runs[self.story.request_id].state.work_done <= 0:
            raise ValueError('실제 작업이 진행된 뒤 운영 상태를 확인해 주세요.')
        with self._atomic():
            self.story.operations_confirmed = True

    def chapter_result(self):
        if not self.story or not self.story.chapter_completed:
            raise ValueError('첫 업무를 정상 완료한 뒤 결과를 확인할 수 있습니다.')
        run = self.runs[self.story.request_id]
        s = run.state
        if not (s.phase == 'finished' and s.succeeded and run.request['status'] == 'completed'
                and run.playthrough_id not in self.servers.allocations):
            raise ValueError('고객 작업 완료와 자원 반환을 확인할 수 없습니다.')
        statuses = {spec.key:(self.servers.hardware[spec.key].state if self.servers.hardware[spec.key].state != 'HEALTHY'
                             else 'ACTIVE' if any(part.server_id == spec.key for a in self.servers.allocations.values()
                                                  for part in a.slices) else 'IDLE') for spec in SERVERS}
        return {'company':run.mission['company_name'], 'task':run.mission['title'], 'score':s.score,
                'on_time':run.terms['completed'] <= run.terms['due'] if run.terms else None,
                'gpu':s.gpu_used, 'power':s.power_used, 'servers':statuses,
                'feedback':run.last_feedback, 'request_id':run.request['id'], 'playthrough_id':run.playthrough_id,
                'summary':chapter1_summary({'score':s.score,'gpu':s.gpu_used,'power':s.power_used}, run)}

    # ---- Chapter 2 -------------------------------------------------------------------------
    def _validate_chapter2(self):
        chapter2 = self.story.chapter2 if self.story else None
        if chapter2 is None:
            if self.story and self.story.practice:
                raise ValueError('Chapter 2 연습 슬롯의 고객 요청 기록이 없습니다.')
            return
        countries = []
        for rid in chapter2.request_ids:
            run = self.runs.get(rid)
            if run is None:
                raise ValueError('Chapter 2의 고객 요청을 찾을 수 없습니다.')
            countries.append(run.mission['country'])
        if tuple(countries) != CHAPTER2_COUNTRIES:
            raise ValueError('Chapter 2의 고객 요청이 저장된 미션과 일치하지 않습니다.')

    def start_chapter2(self):
        """Chapter 1을 정상 완료한 스토리에서만 일본·미국 요청을 접수합니다. 기존 기록은 변경하지 않습니다."""
        if not self.story or not self.story.chapter_completed:
            raise ValueError('Chapter 1을 정상 완료한 뒤 Chapter 2를 시작할 수 있습니다.')
        if self.story.chapter2 is not None:
            raise ValueError('이미 Chapter 2를 시작했습니다.')
        return self._open_chapter2()

    def _open_chapter2(self):
        """일본·미국의 고정 교육 요청을 새로 접수합니다. 다른 슬롯의 기록은 읽거나 가져오지 않습니다."""
        mission_ids = []
        for country in CHAPTER2_COUNTRIES:
            mid = next((mid for mid, m in self.missions.items() if m['country'] == country), None)
            if mid is None:
                raise ValueError(f'{country} 고객 미션을 찾을 수 없습니다.')
            mission_ids.append((mid, CHAPTER2_SCENARIOS[country]))
        with self._atomic():
            ids = [self._receive(mid, f'chapter2:{mid}', scenario) for mid, scenario in mission_ids]
            self.story.chapter2 = Chapter2Progress(*ids)
            self.selected_id = ids[0]
        return tuple(ids)

    def confirm_chapter2_briefing(self):
        if not self.story or not self.story.chapter2_active or self.story.chapter2.step != 'briefing':
            raise ValueError('현재는 Chapter 2 브리핑 단계가 아닙니다.')
        with self._atomic():
            self.story.chapter2.briefing_confirmed = True

    def allocation_impacts(self, run, parts):
        """선택한 배정안을 가정했을 때 다른 Chapter 2 요청의 고객 허용 모드가 배정 가능한지 현재 원장으로 계산합니다.
        조회 전용 복사본만 사용하며 원장/DB를 변경하지 않습니다."""
        story = self.story
        if (not story or not story.chapter2_active or not parts
                or run.request['id'] not in story.chapter2.request_ids):
            return []
        pool = self.servers.excluding(None)
        try:
            pool.reserve(Allocation(10**9, tuple(parts)))
        except (ValueError, TypeError):
            return []
        lines = []
        for rid in story.chapter2.request_ids:
            other = self.runs[rid]
            if other is run or other.state.allocated or other.request['status'] not in ('new', 'review', 'waiting'):
                continue
            results = []
            for key, plan in other.state.plans.items():
                if self.plan_agreed(other, key):
                    ok = pool.plan(plan['gpu'], plan['power']) is not None
                    results.append(f'{plan["label"]} GPU {plan["gpu"]}/전력 {plan["power"]} '+('배정 가능' if ok else '배정 불가'))
            if results:
                lines.append(f'{other.mission["country"]} {other.mission["company_name"]}: '+' · '.join(results))
        return lines

    def chapter2_briefing_lines(self, run):
        """판단에 필요한 실제 수치: 모드별 처리 시간·예상 완료·기한 준수 여부, 현재 자원으로 두 요청의 원래 조건을 함께 실행할 수 있는지.
        조회 전용이며 값은 모두 현재 엔진 상태에서 계산합니다."""
        story = self.story
        if (not story or not story.chapter2_active or run.request['id'] not in story.chapter2.request_ids
                or run.state.allocated or run.request['status'] not in ('new', 'review', 'waiting')):
            return []
        lines = []
        due = run.terms.get('due')
        for key, plan in run.state.plans.items():
            if not self.plan_agreed(run, key):
                continue
            minutes = run.state.estimate_minutes(key)
            finish = self.minute + minutes
            status = '' if due is None else (' · 기한 내' if finish <= due else f' · 기한 {finish-due}분 초과')
            lines.append(f'{plan["label"]} GPU {plan["gpu"]}/전력 {plan["power"]}: 처리 {minutes}분 → 지금 시작하면 {game_time(finish)} 완료{status}')
        pending = [self.runs[rid] for rid in story.chapter2.request_ids
                   if self.runs[rid].request['status'] in ('new', 'review', 'waiting') and not self.runs[rid].state.allocated]
        if len(pending) == 2:
            mode = lambda r: r.conditions['requested_mode'] if r.conditions else 'performance'
            need_gpu = sum(r.state.plans[mode(r)]['gpu'] for r in pending)
            need_power = sum(r.state.plans[mode(r)]['power'] for r in pending)
            gpu, power = self.servers.available()
            gpu, power = min(gpu, self.center.available_gpu()), min(power, self.center.available_power())
            ok = need_gpu <= gpu and need_power <= power
            lines.append(f'두 고객의 원래 요청 동시 실행: 필요 GPU {need_gpu}/전력 {need_power} · 현재 가용 GPU {gpu}/전력 {power} → '
                         + ('가능' if ok else '불가'))
        return lines

    def chapter2_comparison_lines(self):
        """두 고객의 요청 조건을 같은 기준으로 나란히 보여 주는 판단 자료(조회 전용).
        GPU·전력·모드별 처리 시간·완료 기한·고객 허용 모드·서버별 남은 자원만 현재 엔진 값으로 계산하며,
        처리 순서나 운영 모드의 정답·권장은 쓰지 않습니다."""
        story = self.story
        if not story or not story.chapter2_active:
            return []
        lines = [f'두 고객 요청 비교 · 현재 {self.time_label} 기준']
        for rid in story.chapter2.request_ids:
            run = self.runs[rid]
            t, s = run.terms, run.state
            lines.append(f'■ {run.mission["country"]} {run.mission["company_name"]}'
                         + (f' · {t["priority"]}' if t.get('priority') else ''))
            if s.allocated:
                lines.append(f'  실행 중 · {s.plans[s.plan]["label"]} GPU {s.gpu_used}/전력 {s.power_used} · '
                             f'남은 처리 {s.remaining_minutes}분 → 예상 완료 {game_time(self.minute+s.remaining_minutes)}')
            elif run.request['status'] in ('new', 'review', 'waiting'):
                for key, plan in s.plans.items():
                    minutes = s.estimate_minutes(key)
                    lines.append(f'  {plan["label"]}: GPU {plan["gpu"]}/전력 {plan["power"]} · 처리 {minutes}분'
                                 f' · {self.mode_status(run, key)}')
            else:
                lines.append('  '+self._chapter2_outcome_label(run))
            if t.get('due') is not None:
                left = t['due'] - self.minute
                lines.append(f'  완료 기한 {game_time(t["due"])} ('+(f'남은 {left}분' if left >= 0 else f'{-left}분 초과')+')'
                             + (f' · 최종 배정 기한 {game_time(t["expires"])}'
                                if not s.allocated and run.request['status'] in ('new', 'review', 'waiting') else ''))
        parts = []
        for spec in SERVERS:
            if self.servers.hardware[spec.key].state != 'HEALTHY':
                parts.append(f'{spec.key} 사용 불가')
            else:
                parts.append(f'{spec.key} {len(self.servers.free_slots(spec))}/{spec.power-self.servers.usage(spec.key)[1]}')
        lines.append('서버별 남은 GPU/전력: '+' · '.join(parts))
        return lines

    def _chapter2_outcome_label(self, run):
        state, reason = self.chapter2_job_state(run)
        if state == 'success':
            return '정상 완료 · 기한 내'
        names = {'expired': '기한 만료 · 미처리', 'rejected': '거절', 'failed': '실패', 'late': '기한 초과 완료'}
        return names.get(reason, '후속 조치 대기' if run.state.phase == 'finished' else '종료')

    # ---- Chapter 2 성공/실패 판정 ---------------------------------------------------------------
    def _chapter2_start_bound(self, run):
        """아직 시작하지 않은 요청이 가장 빨리 끝낼 수 있는 시각의 하한. 값은 현재 자원·진행 중 작업의 남은 시간에서 계산합니다."""
        best = None
        running = [r for r in self.runs.values() if r.state.allocated]
        release = min((self.minute + r.state.remaining_minutes for r in running), default=self.minute)
        for key in run.state.plans:
            if not self.plan_agreed(run, key):
                continue
            allowed = self.allocation_preview(run, key)['allowed']
            start = self.minute if allowed or not running else release
            finish = start + run.state.estimate_minutes(key)
            if best is None or finish < best[0]:
                best = (finish, start, key, allowed)
        return best

    def chapter2_job_state(self, run):
        """('success'|'failed'|'running'|'pending', 이유). 실제 요청/작업 상태와 시간에서만 판정합니다."""
        s, t = run.state, run.terms
        due = t.get('due')
        if t.get('expired'):
            return 'failed', 'expired'
        if run.request['status'] == 'rejected':
            return 'failed', 'rejected'
        if s.phase == 'finished':
            if run.request['status'] == 'completed' and s.succeeded:
                return ('success', None) if due is None or t.get('completed', self.minute) <= due else ('failed', 'late')
            return ('failed', 'failed') if run.followup_closed else ('pending', None)
        if s.allocated:
            return ('failed', 'late_certain') if due is not None and self.minute + s.remaining_minutes > due else ('running', None)
        bound = self._chapter2_start_bound(run)
        if bound is not None and due is not None and bound[0] > due:
            return 'failed', 'late_certain'
        return 'pending', None

    def _chapter2_failure_record(self, run, reason):
        s, t = run.state, run.terms
        record = {'request_id': run.request['id'], 'reason': reason, 'minute': self.minute, 'time': game_time(self.minute),
                  'company': run.mission['company_name'], 'country': run.mission['country'],
                  'due': game_time(t['due']) if t.get('due') is not None else None,
                  'expiry': game_time(t['expires']) if t.get('expires') is not None else None,
                  'late_minutes': t.get('late_minutes'),
                  'waited': (t['started']-t['received']) if t.get('started') is not None else None,
                  'mode': s.plans[s.plan]['label'] if s.plan else None,
                  'minutes': ((t.get('completed', self.minute + (s.remaining_minutes if s.allocated else 0)) - t['started'])
                              if t.get('started') is not None else None),
                  'blocker': None, 'earliest_finish': None,
                  # 실제로 시도한 대응만 기록합니다(대안 협의 결과, 요청 대기 선택 횟수).
                  'tried': {'proposal': run.proposals[-1]['status'] if run.proposals else None,
                            'wait_choices': sum(1 for e in self.db.get_request_events(run.request['id'])
                                                if e['kind'] == 'decision' and '대기 · 자원 미점유' in e['message'])}}
        if reason == 'late_certain' and not s.allocated and run.playthrough_id is None:
            bound = self._chapter2_start_bound(run)
            if bound is not None:
                record['earliest_finish'] = game_time(bound[0])
        if reason in ('late_certain', 'expired', 'late'):
            record['blocker'] = self._chapter2_blocker(run)
            started = t.get('started')
            if started is not None and record['blocker'] is None:
                # 다른 고객의 작업이 끝난 뒤에 시작한 경우만 '먼저 처리한 고객'으로 기록합니다.
                prior = [o for o in self._chapter2_others(run)
                         if o.terms.get('started') is not None and o.terms.get('completed') is not None
                         and not o.terms.get('expired') and o.terms['completed'] <= started]
                if prior:
                    first = max(prior, key=lambda o: o.terms['completed'])
                    record['after'] = {'country': first.mission['country'], 'company': first.mission['company_name'],
                                       'mode': first.state.plans[first.state.plan]['label'] if first.state.plan else None,
                                       'completed': game_time(first.terms['completed'])}
        other = next((self.runs[rid] for rid in self.story.chapter2.request_ids if rid != run.request['id']), None)
        if other is not None:
            record['other'] = {'country': other.mission['country'], 'state': self.chapter2_job_state(other)[0]}
        return record

    def _chapter2_others(self, run):
        return [self.runs[rid] for rid in self.story.chapter2.request_ids if rid != run.request['id']]

    def _chapter2_blocker(self, run):
        """이 요청이 기한 안에 끝날 수 있는 마지막 시작 시각에 자원을 점유해 함께 배정할 수 없게 만든 다른 고객 작업.
        저장된 시작/완료 시각과 실제 서버 배정 위치로만 판정하며(조회용 새 원장 사용), 그런 작업이 없으면 None입니다."""
        t = run.terms
        agreed = [key for key in run.state.plans if self.plan_agreed(run, key)]
        if t.get('due') is None or t.get('received') is None or not agreed:
            return None
        fresh = GameState(center=DataCenter(), country=run.mission['country'], scenario=run.state.scenario)
        latest = max(t['received'], t['due'] - min(fresh.estimate_minutes(key) for key in agreed))
        for other in self._chapter2_others(run):
            ot = other.terms
            if ot.get('started') is None or ot['started'] > latest:
                continue
            end = ot.get('completed') if not ot.get('expired') else None
            if end is not None and end <= latest:
                continue
            if not other.server_allocations:
                continue
            allocation = other.server_allocations[0]   # 처음 시작할 때 실제로 점유한 서버 위치
            pool = ServerPool()
            try:
                pool.reserve(Allocation(allocation.playthrough_id, allocation.slices))
            except ValueError:
                continue
            plans = [run.state.plans[key] for key in agreed]
            if any(pool.plan(p['gpu'], p['power']) is not None for p in plans):
                continue   # 함께 배정할 수 있는 허용 모드가 있었으므로 자원을 막은 작업이 아닙니다.
            # 전체 GPU·전력 숫자로는 들어가지만 서버별 위치 때문에 결합할 수 없었던 경우를 구분합니다.
            placement = any(allocation.gpu + p['gpu'] <= self.center.gpu_total and allocation.power + p['power'] <= self.center.power_total
                            for p in plans)
            plan = other.state.plans[other.state.plan] if other.state.plan else {'label': '배정'}
            until = end if end is not None else (self.minute + other.state.remaining_minutes if other.state.allocated else self.minute)
            return {'country': other.mission['country'], 'company': other.mission['company_name'],
                    'mode': plan['label'], 'gpu': allocation.gpu, 'power': allocation.power,
                    'until': game_time(until), 'placement': placement,
                    'servers': ', '.join(f'{p.server_id} {p.gpu}/{p.power}' for p in allocation.slices)}
        return None

    def _chapter2_hint(self, run):
        """Chapter 2 요청의 배정 실패에는 원인만 짧게 알리고 다음에 확인할 일을 안내합니다. 실패를 선언하지 않습니다."""
        story = self.story
        if story and story.chapter2_active and run.request['id'] in story.chapter2.request_ids:
            return ' 현재 가용 GPU 또는 전력이 부족해 이 요청을 배정할 수 없습니다. 다른 배정 계획이나 고객과의 조건 협의 가능성을 확인해 보세요.'
        return ''

    @property
    def chapter2_retry_available(self):
        """플레이어가 대응(대안 협의·요청 대기)을 시도했고 기한 내 완료가 불가능하다고 예측될 때, 또는 이미 실패가 확정됐을 때만
        [이번 시도 종료·재도전]을 제공합니다. 이 선택지는 현재 슬롯과 요청을 변경하지 않습니다."""
        chapter2 = self.story.chapter2 if self.story else None
        if chapter2 is None or chapter2.completed:
            return False
        if chapter2.failure is not None:
            return True
        for rid in chapter2.request_ids:
            run = self.runs[rid]
            if (self.chapter2_job_state(run) == ('failed', 'late_certain') and not run.state.allocated
                    and (run.proposals or run.request['status'] == 'waiting')):
                return True
        return False

    def _detect_chapter2_failure(self, on_load=False):
        """실제로 확정된 실패(만료·거절·재처리 종료·기한 초과 완료)만 한 번 기록합니다. 기한 내 완료 불가 예측은 내부 판단일 뿐
        기록하지 않으며 선배 안내를 만들지 않습니다. 기록은 이후 성공으로 바뀌지 않습니다."""
        chapter2 = self.story.chapter2 if self.story else None
        if chapter2 is None:
            return
        if chapter2.failure is not None and chapter2.failure.get('reason') == 'late_certain':
            # v0.9-2a-2가 예측만으로 기록한 실패는 확정 실패가 아니므로 현재 상태로 다시 판정합니다.
            chapter2.failure, chapter2.failure_seen = None, False
        if chapter2.failure is not None:
            return
        for rid in chapter2.request_ids:
            run = self.runs[rid]
            state, reason = self.chapter2_job_state(run)
            if state == 'failed' and reason != 'late_certain':
                chapter2.failure = self._chapter2_failure_record(run, reason)
                # 이전 버전에서 이미 끝난 저장은 새로 안내하지 않습니다(결과 화면에 실패가 표시됩니다).
                chapter2.failure_seen = bool(on_load and chapter2.completed)
                return

    def mark_chapter2_failure_seen(self):
        chapter2 = self.story.chapter2 if self.story else None
        if chapter2 is None or chapter2.failure is None:
            raise ValueError('확정된 Chapter 2 실패가 없습니다.')
        if not chapter2.failure_seen:
            with self._atomic():
                chapter2.failure_seen = True

    @property
    def chapter2_failure_pending(self):
        chapter2 = self.story.chapter2 if self.story else None
        return bool(chapter2 is not None and chapter2.failure is not None and not chapter2.failure_seen)

    def chapter2_evaluation(self):
        """고객별 미션 평가와 종합 점수. 미처리·실패 고객은 0점, 끝나지 않은 작업은 확정 전으로 표시합니다.
        기존 고객별 점수와 기한 감점은 그대로 사용하며 실패 패널티를 따로 더하지 않습니다."""
        story = self.story
        if not story or story.chapter2 is None:
            raise ValueError('Chapter 2 진행 기록이 없습니다.')
        jobs = []
        for rid in story.chapter2.request_ids:
            run = self.runs[rid]
            state, reason = self.chapter2_job_state(run)
            final = is_finished(run)
            score = None
            if final:
                score = run.state.score if (run.state.succeeded and run.request['status'] == 'completed') else 0
            jobs.append({'request_id': rid, 'company': run.mission['company_name'], 'country': run.mission['country'],
                         'state': state, 'reason': reason, 'final': final, 'score': score,
                         'raw_score': run.state.score})
        overall = (sum(j['score'] for j in jobs)/2) if all(j['final'] for j in jobs) else None
        failed = story.chapter2.failure is not None or any(j['state'] == 'failed' for j in jobs)
        mission = 'failed' if failed else 'success' if all(j['state'] == 'success' for j in jobs) else 'in_progress'
        return {'jobs': jobs, 'overall': overall, 'mission': mission}

    def chapter2_evaluation_lines(self):
        names = {'expired': '기한 만료 · 미처리', 'rejected': '거절', 'failed': '실패', 'late': '기한 초과 완료',
                 'late_certain': '기한 내 완료 불가'}
        lines = []
        evaluation = self.chapter2_evaluation()
        for job in evaluation['jobs']:
            if job['final']:
                note = '정상 완료 · 기한 내' if job['state'] == 'success' else names[job['reason']]
                lines.append(f'{job["country"]} {job["company"]}: {job["score"]}점 ({note})')
            else:
                note = f' · {names[job["reason"]]}' if job['state'] == 'failed' else ''
                lines.append(f'{job["country"]} {job["company"]}: 진행 중 · 점수 확정 전{note}')
        lines.append('Chapter 2 종합 평가: '+(f'{evaluation["overall"]:g}/100' if evaluation['overall'] is not None
                                          else '미확정(두 작업이 끝나면 확정)'))
        return lines

    def chapter2_result(self):
        story = self.story
        if not story or story.chapter2 is None or not story.chapter2.completed:
            raise ValueError('두 고객 요청을 모두 마무리한 뒤 결과를 확인할 수 있습니다.')
        jobs = []
        for rid in story.chapter2.request_ids:
            run = self.runs[rid]
            s = run.state
            if not is_finished(run):
                raise ValueError('고객 요청의 종료 상태를 확인할 수 없습니다.')
            if run.terms.get('expired'):
                outcome = '기한 만료 · 미처리'
            elif run.request['status'] == 'rejected':
                outcome = '거절'
            elif s.succeeded:
                outcome = '정상 완료'
            else:
                outcome = '실패 · 재처리 종료'
            last = next((a for a in reversed(run.server_allocations) if a.playthrough_id == run.playthrough_id), None)
            terms = run.terms
            jobs.append({'request_id': rid, 'company': run.mission['company_name'], 'country': run.mission['country'],
                         'task': run.mission['title'], 'outcome': outcome, 'succeeded': bool(s.succeeded),
                         'score': s.score, 'on_time': (terms['completed'] <= terms['due'] if 'completed' in terms and not terms.get('expired') else None),
                         'mode': s.plans[s.plan]['label'] if s.plan else '미배정',
                         'gpu': s.gpu_used if run.playthrough_id else 0, 'power': s.power_used if run.playthrough_id else 0,
                         'placement': ', '.join(f'{p.server_id} GPU {p.gpu}/전력 {p.power}' for p in last.slices) if last else '배정 없음',
                         'started': terms.get('started'), 'completed': terms.get('completed')})
        for job in jobs:
            run = self.runs[job['request_id']]
            terms = run.terms
            job.update(waited=(terms['started']-terms['received']) if terms.get('started') is not None else None,
                       late_minutes=terms.get('late_minutes'), penalty=terms.get('penalty'),
                       expired=bool(terms.get('expired')), expiry=terms.get('expires'),
                       wait_choices=sum(1 for e in self.db.get_request_events(job['request_id'])
                                        if e['kind'] == 'decision' and '대기 · 자원 미점유' in e['message']),
                       proposals=[p['status'] for p in run.proposals])
        windows = [(j['started'], j['completed']) for j in jobs if j['started'] is not None and j['completed'] is not None]
        concurrent = len(windows) == 2 and max(w[0] for w in windows) < min(w[1] for w in windows)
        # 아래 문장은 저장된 시작/종료 시각과 결과에서만 만듭니다. 기록이 없는 행동은 쓰지 않습니다.
        decisions = []
        started = sorted((j for j in jobs if j['started'] is not None), key=lambda j: (j['started'], j['request_id']))
        if len(started) == 2 and started[0]['started'] == started[1]['started']:
            decisions.append(f'두 작업을 같은 시각({game_time(started[0]["started"])})에 시작했습니다.')
        elif started:
            decisions.append(f'먼저 배정한 고객: {started[0]["country"]} {started[0]["company"]} ({game_time(started[0]["started"])})')
        for job in jobs:
            line = f'{job["country"]}: {job["mode"] if job["started"] is not None else "배정 없음"}'
            if job['waited'] is not None:
                line += f' · 접수 후 {job["waited"]}분 뒤 시작'
            if job['wait_choices']:
                line += f' · 요청 대기 {job["wait_choices"]}회'
            if job['proposals']:
                line += ' · 대안 협의 '+'/'.join({'accepted': '동의', 'rejected': '거절', 'pending': '답변 대기'}[p] for p in job['proposals'])
            if job['on_time'] is True:
                line += ' · 기한 내 완료'
            elif job['on_time'] is False:
                line += f' · 기한 {job["late_minutes"]}분 초과'
            if job['penalty']:
                line += f' · 기한 감점 {job["penalty"]}점'
            line += f' · {job["outcome"]}'
            decisions.append(line)
            if job['expired']:
                holder = next((o for o in jobs if o is not job and o['started'] is not None and o['completed'] is not None
                               and o['started'] <= job['completed'] < o['completed']), None)
                if holder is not None:
                    decisions.append(f'{holder["country"]} {holder["company"]} 작업은 {game_time(holder["completed"])}에야 자원을 반환했습니다. '
                                     f'{job["country"]} 요청은 최종 배정 기한({game_time(job["expiry"])})까지 시작하지 못했습니다.')
                released = next((o for o in jobs if o is not job and o['started'] is not None and o['completed'] is not None
                                 and o['started'] <= job['completed'] and o['completed'] <= job['completed']), None)
                if holder is None and released is not None:
                    decisions.append(f'{released["country"]} {released["company"]} 작업은 {game_time(released["completed"])}에 자원을 반환했지만, '
                                     f'{job["country"]} 요청은 최종 배정 기한({game_time(job["expiry"])})까지 시작하지 않았습니다.')
        statuses = {spec.key: (self.servers.hardware[spec.key].state if self.servers.hardware[spec.key].state != 'HEALTHY'
                               else 'ACTIVE' if any(part.server_id == spec.key for a in self.servers.allocations.values()
                                                    for part in a.slices) else 'IDLE') for spec in SERVERS}
        evaluation = self.chapter2_evaluation()
        for job, scored in zip(jobs, evaluation['jobs']):
            job.update(eval_score=scored['score'], state=scored['state'], reason=scored['reason'])
        result = {'jobs': jobs, 'concurrent': concurrent, 'servers': statuses, 'decisions': decisions,
                  'practice': bool(story.practice), 'mission': evaluation['mission'], 'overall': evaluation['overall'],
                  'failure': deepcopy(story.chapter2.failure),
                  'highlights': self._chapter2_success_lines(jobs, concurrent) if evaluation['mission'] == 'success' else []}
        # v0.9-2b: 요약표용 값. 모두 위 기록에서 계산하며 저장하지 않습니다.
        for job in jobs:
            job['deadline'] = job_summary(self.runs[job['request_id']])['deadline']
        result['summary'] = chapter2_summary(result)
        return result

    def _chapter2_success_lines(self, jobs, concurrent):
        """성공했을 때 어떤 운영 모드·배정 위치·시간으로 기한을 지켰는지 저장된 기록만으로 설명합니다."""
        lines = []
        for job in jobs:
            run = self.runs[job['request_id']]
            t, s = run.terms, run.state
            proposal = run.proposals[-1] if run.proposals else None
            how = ('고객 동의를 받은 ' if proposal and proposal['status'] == 'accepted' and s.plan == proposal['proposed']['mode'] else
                   '고객이 원래 요청한 ' if run.conditions and s.plan == run.conditions['requested_mode'] else
                   '고객이 허용한 ' if run.conditions and s.plan in run.conditions['allowed_modes'] else '')
            margin = t['due'] - t['completed']
            lines.append(f'{job["country"]} {job["company"]}: {how}{job["mode"]}(GPU {job["gpu"]}/전력 {job["power"]} · '
                         f'배정 {job["placement"]})로 {game_time(t["started"])}에 시작해 {game_time(t["completed"])}에 완료했습니다. '
                         + (f'완료 기한 {game_time(t["due"])}보다 {margin}분 먼저 끝냈습니다.' if margin else
                            f'완료 기한 {game_time(t["due"])}에 맞춰 끝냈습니다.'))
        if concurrent:
            lines.append(f'두 작업을 동시에 실행하며 GPU {sum(j["gpu"] for j in jobs)}개와 전력 {sum(j["power"] for j in jobs)}단위를 '
                         f'나누어 썼습니다(데이터센터 총 GPU {self.center.gpu_total}/전력 {self.center.power_total}).')
        else:
            lines.append('먼저 끝난 작업의 GPU와 전력이 반환된 뒤 다음 작업을 시작해 두 기한을 모두 지켰습니다.')
        return lines

    def skip_tutorial(self):
        if self.story and not self.story.tutorial_completed:
            with self._atomic():
                self.story.skip()

    def hardware_servers(self, run):
        allocation = self.servers.allocations.get(run.playthrough_id)
        return tuple(s.server_id for s in allocation.slices
                     if self.servers.hardware[s.server_id].state != 'HEALTHY') if allocation else ()

    def hardware_status(self, run):
        servers = self.hardware_servers(run)
        issues = []
        if servers:
            issues.append('서버 장애 '+', '.join(servers)+f' · 하드웨어 중단 {run.hardware_downtime}분')
        if run.state.allocated and run.migration_left:
            issues.append(f'작업 이전 준비 {run.migration_left}분')
        return ' / '.join(issues)

    def inject_server_fault(self, server_id):
        if server_id not in self.servers.hardware:
            raise ValueError('존재하지 않는 서버입니다.')
        if self.servers.hardware[server_id].state != 'HEALTHY':
            raise ValueError('정상 서버에만 교육용 장애를 발생시킬 수 있습니다.')
        with self._atomic():
            self.servers.hardware[server_id] = ServerHealth('FAULT', reason='교육용 서버 장애 시뮬레이션 · 서버 사용 불가')
            for run in self.runs.values():
                if server_id in self.hardware_servers(run):
                    self._emit(run, 'hardware_fault', f'Server {server_id} 하드웨어 장애. 배정 유지 · 작업 전체 중단.')
                    self._feedback(run, f'Server {server_id} 장애로 작업이 멈췄습니다. 장비 복구 또는 작업 이전 계획을 알려주세요.',
                                   'customer_hardware_fault')

    def begin_server_repair(self, server_id):
        if server_id not in self.servers.hardware or self.servers.hardware[server_id].state != 'FAULT':
            raise ValueError('FAULT 상태인 서버만 복구를 시작할 수 있습니다.')
        with self._atomic():
            self.servers.hardware[server_id] = ServerHealth('REPAIRING', 20, self.servers.hardware[server_id].reason)
            for run in self.runs.values():
                if server_id in self.hardware_servers(run):
                    self._emit(run, 'hardware_repair', f'Server {server_id} 복구 시작. 가상 시간 20분 필요 · 기존 배정 유지.')
                    self._feedback(run, f'Server {server_id} 장비 복구 20분 일정을 확인했습니다. 기존 작업과 완료 기한은 유지됩니다.',
                                   'customer_hardware_repair')

    def migration_preview(self, run):
        source = self.servers.allocations.get(run.playthrough_id)
        result = {'allowed':False, 'reason':'서버 장애 영향을 받는 실행 작업만 이전할 수 있습니다.',
                  'options':(), 'source':source, 'slices':None}
        if not run.state.allocated or not self.hardware_servers(run) or run.migration_left:
            return result
        if not self.plan_agreed(run, run.state.plan):
            return {**result, 'reason':'현재 운영 모드의 고객 조건/동의를 확인해 주세요.'}
        options = self.servers.migration_options(run.playthrough_id)
        return {**result, 'allowed':bool(options), 'options':options, 'slices':options[0] if options else None,
                'reason':'이전 가능' if options else '정상 서버의 GPU·전력으로 전체 작업을 이전할 수 없습니다.'}

    def migrate(self, server_plan, source):
        run = self.current
        with self._atomic():
            current = self.servers.allocations.get(run.playthrough_id)
            if current is None or current != source or not self.hardware_servers(run) or run.migration_left:
                raise ValueError('기존 배정이나 장애 상황이 변경되었습니다. 이전 계획을 다시 확인해 주세요.')
            if not self.plan_agreed(run, run.state.plan):
                raise ValueError('고객이 동의한 운영 모드로만 이전할 수 있습니다.')
            pool = self.servers.excluding(run.playthrough_id)
            try:
                pool.validate_plan(server_plan, run.state.gpu_used, run.state.power_used)
            except (ValueError, TypeError) as exc:
                raise ValueError(f'선택한 이전 계획을 사용할 수 없습니다: {exc} 이전 계획을 다시 확인해 주세요.') from exc
            allocation = Allocation(run.playthrough_id, server_plan)
            # 전체 DataCenter는 점유/반환하지 않습니다. 현재 수행의 위치만 한 번 교체합니다.
            self.servers.allocations[run.playthrough_id] = allocation
            run.server_allocations.append(allocation)
            run.migration_left = 10
            self._emit(run, 'migration', '작업 이전 확정 · 기존 수행/진행률/운영 모드/완료 기한 유지 · 준비 10분.\n'
                       +'서버 배정: '+', '.join(f'{s.server_id} GPU{s.gpu}/전력{s.power}' for s in server_plan))
            self._feedback(run, '이전 계획을 확인했습니다. 10분 준비 후 기존 작업을 계속해 주세요.', 'customer_migration')

    def _advance_repairs(self):
        for server_id, health in tuple(self.servers.hardware.items()):
            if health.state != 'REPAIRING':
                continue
            left = health.repair_left-10
            self.servers.hardware[server_id] = ServerHealth('REPAIRING', left, health.reason) if left else ServerHealth()
            if not left:
                for run in self.runs.values():
                    allocation = self.servers.allocations.get(run.playthrough_id)
                    if allocation and any(s.server_id == server_id for s in allocation.slices):
                        self._emit(run, 'hardware_recovered', f'Server {server_id} 장비 복구 완료. 남은 다른 장애/준비가 없으면 다음 시간 구간부터 실행합니다.')
                        pending = self.hardware_status(run)
                        if run.state.phase in ('incident', 'paused', 'recovering'):
                            pending += ' · 기존 네트워크 상태/준비는 별도 확인해 주세요.'
                        self._feedback(run, f'Server {server_id} 장비 복구 완료를 확인했습니다. '
                                       +(pending or '다음 시간 구간부터 작업을 계속해 주세요.'), 'customer_hardware_recovered')

    def _emit(self, run, kind, text):
        message = f'[{self.time_label}] {text}'
        self.db.add_request_event(run.request['id'],run.playthrough_id,self.minute,kind,message)
        if run.playthrough_id is not None:
            self.db.add_log(run.playthrough_id,message)
        run.messages.append(message)

    def _feedback(self, run, text, kind='feedback'):
        run.last_feedback = text
        self.db.mark_request_unread(run.request['id'])
        self._refresh_request(run)
        self._emit(run,kind,f'{run.mission["company_name"]}: {text}')

    def _refresh_request(self, run):
        run.request = dict(self.db.get_request(run.request['id']))

    def _message(self, mission, conditions):
        p,e = (conditions['plans'][k] for k in ('performance','economy'))
        permission = ('고성능·절약형 모두 허용합니다. 운영자가 자원과 처리 시간을 고려하여 직접 선택해 주세요.'
                      if conditions['type'] == 'flexible' else
                      '고성능 운영을 요청드립니다. 절약형으로 변경하려면 대안 제시 후 저희의 명시적인 동의가 필요합니다.')
        return (f'[신규 작업 요청]\n발신: {mission["company_name"]}\n국가: {mission["country"]}\n\n안녕하세요.\n'
                f'{mission["description"]}\n요청 작업: {mission["title"]}\n\n'
                f'원래 요청 모드: {p["label"]}\n{permission}\n'
                f'요청 GPU: {p["gpu"]}개 / 전력: {p["power"]}단위 / 네트워크: {p["network"]}단위\n'
                f'절약형: GPU {e["gpu"]}개 / 전력 {e["power"]}단위 · '
                + ('고객 허용 모드' if conditions['type'] == 'flexible' else '고객 동의 필요')
                + f'\n완료 기한: {game_time(conditions["due"])} · 기한까지 처리해 주세요.\n\n'
                + '가능한 자원과 운영 일정을 확인해 회신 부탁드립니다. 감사합니다.')

    def _receive(self, mid, key=None, scenario=None):
        existing = self.db.find_request_by_source(key) if key is not None else None
        if existing is not None:
            if existing['id'] not in self.runs:
                self.runs[existing['id']] = self._load_run(existing)
            return existing['id']
        terms = request_terms(self.missions[mid]['country'], self.minute, scenario)
        conditions = request_conditions(self.missions[mid], terms['due'], scenario)
        message = self._message(self.missions[mid], conditions)
        if scenario:
            probe = GameState(center=DataCenter(), country=self.missions[mid]['country'], scenario=scenario)
            message += ('\n\n예상 처리 시간(시작 후, 장애·대기 제외): '
                        + ' / '.join(f'{p["label"]} {probe.estimate_minutes(k)}분' for k, p in probe.plans.items()))
        rid = self.db.create_request(mid,message,key)
        run = self._load_run(self.db.get_request(rid))
        self.runs[rid] = run
        run.state.scenario = scenario
        run.terms, run.conditions = terms, conditions
        self.arrival_last[mid] = self.minute
        self._emit(run,'arrival',f'새 업무 메시지: {run.mission["company_name"]} · {run.mission["country"]}')
        self._feedback(run, message+'\n\n'+self.deadline_summary(run)
                       +f'\n미배정 요청의 최종 접수 종료: {game_time(run.terms["expires"])}', 'customer_request')
        return rid

    def deliver_next_request(self):
        """최초 요청 접수 보조 함수. GUI는 시간 기반 자동 접수를 사용합니다."""
        if self.story:
            if self.runs:
                return None
            if self.story.practice:
                return self._open_chapter2()[0]
            mid = next(mid for mid, m in self.missions.items() if m['country'] == '싱가포르')
            with self._atomic():
                rid = self._receive(mid, f'initial:{mid}')
                self.story.request_id = rid
            return rid
        received = {r.mission['id'] for r in self.runs.values()}
        for mid in self.missions:
            if mid not in received:
                with self._atomic():
                    rid = self._receive(mid,f'initial:{mid}')
                return rid
        return None

    def _deliver_scheduled_requests(self):
        if self.story:
            return  # Chapter별 접수는 스토리 조건에서 명시적으로 실행합니다.
        while self.minute >= self.next_arrival_minute:
            due = self.next_arrival_minute
            slots = max(0, MAX_PENDING_REQUESTS-self.pending_request_count)
            busy = {r.mission['id'] for r in self.runs.values()
                    if r.request['status'] in ('new','review','waiting','operating')
                    or (r.state.phase=='finished' and not r.state.succeeded and not r.followup_closed)}
            eligible = [mid for mid in self.missions if mid not in busy
                        and due-self.arrival_last.get(mid, due-CUSTOMER_COOLDOWN) >= CUSTOMER_COOLDOWN]
            # 요청 추첨과 장애 추첨은 서로 영향을 주지 않는 독립된 순서를 사용합니다.
            rng = random.Random(f'{self.seed}:arrivals:{self.arrival_index}')
            rng.shuffle(eligible)
            counts = {mid:0 for mid in self.missions}
            for run in self.runs.values():
                counts[run.mission['id']] += 1
            eligible.sort(key=lambda mid:counts[mid])
            amount = min(slots, len(eligible), rng.randint(1,2))
            for mid in eligible[:amount]:
                self._receive(mid, f'auto:{due}:{mid}')
            # 가득 찼거나 모든 고객이 운영 중인 구간은 건너뛰고 과거 요청을 누적하지 않습니다.
            self.next_arrival_minute += ARRIVAL_INTERVAL
            self.arrival_index += 1

    def select(self, rid):
        if rid not in self.runs:
            raise ValueError('접수된 요청을 찾을 수 없습니다.')
        with self._atomic():
            self.db.mark_request_read(rid)
            self._refresh_request(self.runs[rid])
            self.selected_id = rid

    def accept_request(self):
        run = self.current
        if run.request['status'] not in ('new','review','waiting') or run.state.phase != 'ready':
            raise ValueError('이 요청은 수락 대기 상태로 바꿀 수 없습니다.')
        with self._atomic():
            self.db.mark_request_read(run.request['id'])
            self._refresh_request(run)
            run.state.phase = 'accepted'
            self._emit(run,'decision','요청을 수락했습니다. GPU와 전력은 아직 배정하지 않았습니다.')
            self._feedback(run,'자원 배정 일정을 확인했습니다. 완료 기한에 맞춰 진행 부탁드립니다.', 'customer_accept')

    def _start(self, run, key, retry=False, server_plan=None):
        s = run.state
        if run.terms and self.minute >= run.terms['expires'] and not retry:
            raise ValueError('최종 배정 기한을 초과한 요청입니다.')
        if key not in s.plans:
            raise ValueError('존재하지 않는 운영 모드입니다.')
        if not self.plan_agreed(run, key):
            raise ValueError('대안에 대한 고객 답변을 확인하거나 고객이 동의한 운영 모드를 선택해 주세요.')
        p = s.plans[key]
        shortage = []
        available_gpu, available_power = self.servers.available()
        for name,needed,available in (('GPU',p['gpu'],min(self.center.available_gpu(), available_gpu)),
                                      ('전력',p['power'],min(self.center.available_power(), available_power))):
            if needed > available:
                shortage.append(f'{name} {needed-available}{"개" if name=="GPU" else "단위"}')
        if shortage:
            raise ValueError('자원 부족: '+' / '.join(shortage)+'. 대기하거나 다른 작업 완료를 기다리세요.'+self._chapter2_hint(run))
        if server_plan is None:
            parts = self.servers.plan(p['gpu'], p['power'])
        else:
            try:
                self.servers.validate_plan(server_plan, p['gpu'], p['power'])
            except (ValueError, TypeError) as exc:
                raise ValueError(f'선택한 배정안을 사용할 수 없습니다: {exc} 현재 자원으로 배정 계획을 다시 확인해 주세요.') from exc
            parts = server_plan
        if parts is None:
            raise ValueError('서버별 GPU·전력의 동시 배정 조합이 성립하지 않습니다. 다른 작업 완료를 기다리세요.'+self._chapter2_hint(run))
        s.choose_plan(key)
        rng = random.Random(self.seed+self.roll_index)
        self.roll_index += 1
        s.incident_at = (None if self.story else
                         s.work_total*rng.uniform(.35,.65) if rng.random() < self.incident_chance else None)
        run.playthrough_id = self.db.create_playthrough(run.mission['id'],key)
        allocation = Allocation(run.playthrough_id, parts)
        self.servers.reserve(allocation)
        run.server_allocations.append(allocation)
        if not retry:
            self.db.change_request_status(run.request['id'],'operating',run.playthrough_id)
        self._emit(run,'start',f'[고객 요청 #{run.request["id"]}] {run.mission["company_name"]} · {run.mission["title"]}')
        self._emit(run,'allocation',f'{s.plans[key]["label"]}: GPU {s.gpu_used} / 전력 {s.power_used} 배정. 정상 실행을 시작합니다.\n'
                   +'서버 배정: '+', '.join(f'{part.server_id} GPU {part.gpu}/전력 {part.power}' for part in parts))
        if run.proposals or run.conditions:
            self._emit(run,'agreed_plan',f'최종 운영 계획: {s.plans[key]["label"]} · '
                       + ('고객 동의 대안 적용' if run.proposals and key == run.proposals[-1]['proposed']['mode']
                          else '고객 허용 모드 적용' if run.conditions and key != run.conditions['requested_mode']
                          else '원래 요청 조건 적용'))
        if run.terms and not retry:
            run.terms['started'] = self.minute
        self._feedback(run,'현재 작업이 진행 중인 것으로 확인했습니다. 완료 결과를 기다리겠습니다.', 'customer_start')

    def choose_plan(self, key, server_plan=None):
        run = self.current
        if run.request['status'] not in ('new','review','waiting'):
            raise ValueError('이미 처리한 요청은 중복 수락할 수 없습니다.')
        with self._atomic():
            self._start(run,key,server_plan=server_plan)
            self._refresh_request(run)
        return run.messages[-2:]

    def plan_agreed(self, run, key):
        """최초 허용 조건 또는 명시적으로 동의한 조건과 실제 배정 조건을 검사합니다."""
        if key not in run.state.plans:
            return False
        proposal = run.proposals[-1] if run.proposals else None
        if proposal and proposal['status'] == 'pending':
            return False
        if proposal and proposal['status'] == 'accepted' and key == proposal['proposed']['mode']:
            return self._plan_matches(run, key, proposal['proposed'])
        if run.conditions:
            return key in run.conditions['allowed_modes'] and self._plan_matches(run, key, run.conditions['plans'].get(key, {}))
        # 최초 조건이 없던 저장에는 고객 의사를 소급 추정하지 않습니다.
        return proposal is None or (key == proposal['original']['mode']
                                    and self._plan_matches(run, key, proposal['original']))

    def allocation_preview(self, run, key):
        """조회만 수행하며 실제 시작도 같은 탐색/동의 검증을 다시 적용합니다."""
        if (run.state.allocated or run.request['status'] in ('completed','rejected')) and not (
                run.state.phase == 'finished' and not run.state.succeeded and not run.followup_closed):
            return {'allowed':False, 'reason':'이미 배정했거나 종료된 요청', 'slices':None}
        if run.terms and self.minute >= run.terms['expires'] and run.state.phase != 'finished':
            return {'allowed':False, 'reason':'최종 배정 기한 초과', 'slices':None}
        if not self.plan_agreed(run, key):
            return {'allowed':False, 'reason':'고객 동의 확인 필요', 'slices':None}
        p = run.state.plans[key]
        gpu, power = self.servers.available()
        if p['gpu'] > min(gpu, self.center.available_gpu()) or p['power'] > min(power, self.center.available_power()):
            return {'allowed':False, 'reason':'정상 가용 GPU 또는 전력 부족', 'slices':None}
        parts = self.servers.plan(p['gpu'], p['power'])
        return {'allowed':parts is not None, 'reason':'배정 가능' if parts else '서버별 GPU·전력 조합 불가', 'slices':parts}

    def allocation_options(self, run, key):
        """고객 조건을 먼저 검사한 뒤 비교 가능한 최대 3개 안을 조회합니다."""
        preview = self.allocation_preview(run, key)
        p = run.state.plans.get(key)
        return {**preview, 'options':self.servers.distinct_options(p['gpu'], p['power']) if preview['allowed'] else ()}

    def allocation_summary(self, parts):
        return '\n'.join(f'Server {s.server_id}: GPU {s.gpu} / 전력 {s.power} → '
                         f'잔여 {next(x.gpu for x in SERVERS if x.key==s.server_id)-self.servers.usage(s.server_id)[0]-s.gpu} / '
                         f'{next(x.power for x in SERVERS if x.key==s.server_id)-self.servers.usage(s.server_id)[1]-s.power}'
                         for s in parts)

    @staticmethod
    def _plan_matches(run, key, agreed):
        return agreed.get('mode') == key and all(
            agreed.get(field) == run.state.plans[key][field] for field in ('gpu', 'power', 'network'))

    def mode_status(self, run, key):
        """운영 모드 선택 영역에 최초 허용 범위와 협의 결과를 표시합니다."""
        proposal = run.proposals[-1] if run.proposals else None
        if run.conditions:
            status = ('고객 원래 요청' if key == run.conditions['requested_mode'] else
                      '고객 허용 모드' if key in run.conditions['allowed_modes'] else '고객 동의 필요')
        else:
            status = '이전 요청 · 기존 선택 허용'
        if proposal:
            if proposal['status'] == 'pending':
                return status + ' · 협의 중'
            if key == proposal['proposed']['mode']:
                status = '고객 동의 완료' if proposal['status'] == 'accepted' else '고객 거절 · 실행 불가'
        if status not in ('고객 동의 필요', '고객 거절 · 실행 불가') and not self.plan_agreed(run, key):
            return '동의 조건 불일치 · 실행 불가'
        return status

    def _require_proposable(self, run):
        if run.request['status'] not in ('new','review','waiting') or run.state.phase not in ('ready','accepted'):
            raise ValueError('작업 시작 전 요청을 검토할 때만 대안을 제시할 수 있습니다.')
        if run.terms and self.minute >= run.terms['expires']:
            raise ValueError('최종 배정 기한을 초과한 요청입니다.')

    def alternative_preview(self, run):
        """원본 요청서나 실제 자원을 바꾸지 않고 두 기존 모드를 비교합니다."""
        original_mode = run.conditions['requested_mode'] if run.conditions else 'performance'
        original_plan = run.conditions['plans'][original_mode] if run.conditions else run.state.plans[original_mode]
        original = dict(original_plan, mode=original_mode)
        proposed = dict(run.state.plans['economy'], mode='economy')
        original['minutes'] = run.state.estimate_minutes(original_mode)
        proposed['minutes'] = run.state.estimate_minutes('economy')
        due = run.terms.get('due')
        return {'original':original, 'proposed':proposed, 'created':self.minute, 'due':due,
                'estimated_finish':self.minute+proposed['minutes'],
                'on_time':self.minute+proposed['minutes'] <= due if due is not None else None,
                'resources_available':proposed['gpu'] <= self.center.available_gpu()
                    and proposed['power'] <= self.center.available_power()}

    def proposal_summary(self, proposal):
        o, p = proposal['original'], proposal['proposed']
        deadline = ('기한 내 완료 예상' if proposal['on_time'] else '기한 초과 예상') if proposal['due'] is not None else '기존 요청 · 완료 기한 정보 없음'
        return (f'원래 요청: {o["label"]} · GPU {o["gpu"]} / 전력 {o["power"]} / 네트워크 {o["network"]}\n'
                f'제안 조건: {p["label"]} · GPU {p["gpu"]} / 전력 {p["power"]} / 네트워크 {p["network"]}\n'
                f'사용량 차이: GPU {p["gpu"]-o["gpu"]:+d}개 / 전력 {p["power"]-o["power"]:+d}단위\n'
                f'예상 처리 시간: {o["minutes"]}분 → {p["minutes"]}분 ({p["minutes"]-o["minutes"]:+d}분)\n'
                f'제안 시 예상 완료: {game_time(proposal["estimated_finish"])} · {deadline}\n'
                + (f'원래 완료 기한: {game_time(proposal["due"])} · 기한 유지\n' if proposal['due'] is not None else '')
                + '장애·추가 대기 지연 제외. 제안과 동의만으로 자원을 배정하지 않습니다.')

    def propose_alternative(self):
        run = self.current
        self._require_proposable(run)
        if run.conditions and 'economy' in run.conditions['allowed_modes']:
            raise ValueError('절약형은 고객이 이미 허용한 모드입니다. 별도 협의 없이 선택할 수 있습니다.')
        if run.conditions and run.proposals:
            raise ValueError('이 요청의 대안 협의는 이미 진행했습니다. 기존 조건 또는 동의한 대안을 선택해 주세요.')
        if run.proposals and run.proposals[-1]['status'] in ('pending','accepted'):
            raise ValueError('이미 제시한 대안과 고객 답변을 확인해 주세요.')
        proposal = self.alternative_preview(run)
        if not proposal['resources_available']:
            raise ValueError('절약형 운영에 필요한 GPU 또는 전력도 부족합니다. 다른 작업 완료를 기다려 주세요.')
        with self._atomic():
            proposal.update(status='pending', decided=None, reason='')
            run.proposals.append(proposal)
            original = proposal['original']
            shortage = original['gpu'] > self.center.available_gpu() or original['power'] > self.center.available_power()
            intro = ('현재 요청하신 고성능 운영에 필요한 자원이 부족합니다.' if shortage else
                     '자원 사용량을 줄이는 절약형 운영을 대안으로 제안드립니다.')
            schedule = ('예상 완료 기한은 충족할 수 있습니다.' if proposal['on_time'] else
                        '예상 완료 기한을 초과합니다.' if proposal['on_time'] is False else
                        '완료 기한 정보가 없어 일정 준수를 확인할 수 없습니다.')
            self._emit(run,'proposal',intro+f'\nGPU {proposal["proposed"]["gpu"]}개를 사용하는 절약형 운영을 제안드립니다. '
                       + '작업 시간이 증가하지만 자원 사용량이 줄어듭니다.\n'+schedule+'\n\n'
                       + self.proposal_summary(proposal))
            self._feedback(run,'제안하신 운영 조건을 검토하겠습니다.', 'customer_proposal_review')
        return deepcopy(proposal)

    def review_alternative(self):
        """현재 시각의 예상 완료가 기존 기한 이내일 때만 고객이 수락합니다."""
        run = self.current
        self._require_proposable(run)
        if not run.proposals or run.proposals[-1]['status'] != 'pending':
            raise ValueError('고객 답변을 기다리는 대안이 없습니다.')
        with self._atomic():
            proposal = run.proposals[-1]
            finish = self.minute + run.state.estimate_minutes(proposal['proposed']['mode'])
            due = run.terms.get('due')
            accepted = due is not None and finish <= due
            reason = ('원래 완료 기한 내 처리가 예상되어 대안을 수락합니다.' if accepted else
                      '완료 기한 정보가 없어 일정 준수를 확인할 수 없습니다. 대안을 거절합니다.' if due is None else
                      '원래 완료 기한을 넘길 것으로 예상되어 대안을 거절합니다.')
            proposal.update(status='accepted' if accepted else 'rejected', decided=self.minute,
                            decision_finish=finish, reason=reason)
            self._feedback(run,reason+('\n제안하신 절약형 운영에 동의합니다. 자원 배정 후 시작해 주세요.' if accepted else
                           '\n기존 요청 조건은 유지해 주세요.'), 'customer_proposal_decision')
        return accepted

    def wait_request(self):
        self._decide('waiting')
    def reject_request(self, reason):
        reason = reason.strip()
        if not reason or reason == '기타 사유':
            raise ValueError('구체적인 거절 사유를 입력해 주세요.')
        self._decide('rejected',reason)
    def _decide(self, status, reason=None):
        run = self.current
        with self._atomic():
            self.db.change_request_status(run.request['id'],status,reason=reason)
            run.state.phase = 'ready'
            self._refresh_request(run)
            self._emit(run,'decision',f'{REQUEST_LABELS[status]}'+(f': {reason}' if reason else ' · 자원 미점유'))
            if status == 'rejected':
                if run.terms:
                    run.terms['closed'] = self.minute
                self._feedback(run, customer_reaction(run, 'rejected'), 'customer_reject')

    def _finish_if_needed(self, run):
        s = run.state
        if s.phase == 'finished' and run.request['status'] == 'operating':
            if run.playthrough_id in self.servers.allocations:
                self.servers.release(run.playthrough_id)
            run.migration_left = 0
            late = 0
            if run.terms:
                t = run.terms
                late = max(0, self.minute-t['due'])
                start_late = max(0, t.get('started', self.minute)-t['start_due'])
                penalty = min(15, (start_late+9)//10*2) + min(50, (late+9)//10*5)
                t.update(completed=self.minute, late_minutes=late, penalty=penalty)
                s.score = max(0, s.score-penalty)
                t['evaluation'] = s.score
                s.result_text = s.result_text.rsplit(' 운영 점수:', 1)[0] + f' 운영 점수: {s.score}점. 배정 지연 {start_late}분 / 완료 기한 초과 {late}분 · 기한 감점 {penalty}점.'
            self.db.save_result(run.playthrough_id,s.response or 'normal',s.succeeded,s.score,s.result_text)
            self.db.change_request_status(run.request['id'],'completed')
            self._refresh_request(run)
            self._emit(run,'result',s.result_text+f' GPU {s.gpu_used} / 전력 {s.power_used} 반환.')
            # v0.9-2b: 실제 결과(기한 준수/초과/실패)에 맞는 고객 반응. 종료 시점에 한 번만 기록합니다.
            self._feedback(run, customer_reaction(run, outcome_key(run)),
                           'customer_complete' if s.succeeded else 'customer_failure')

    def deadline_summary(self, run):
        t = run.terms
        if not t:
            return '기존 요청 · 기한 평가 제외'
        end = t.get('completed', t.get('closed', self.minute))
        waiting = max(0, t.get('started', end)-t['received'])
        remaining = t['due']-end
        return (f'{t["priority"]} · 접수 {game_time(t["received"])} · 대기 {waiting}분\n'
                f'배정 권장 {game_time(t["start_due"])} · 완료 기한 {game_time(t["due"])} · '
                + (f'남은 {remaining}분' if remaining >= 0 else f'기한 초과 {-remaining}분'))

    def deadline_level(self, run):
        if not run.terms or run.request['status'] in ('completed','rejected'):
            return ''
        left = run.terms['due']-self.minute
        return 'overdue' if left < 0 else 'urgent' if left <= 30 else ''

    def _check_deadlines(self, run):
        t = run.terms
        if not t or run.request['status'] in ('completed','rejected'):
            return
        pending = run.request['status'] in ('new','review','waiting')
        checks = [('allocation_due', pending and self.minute >= t['start_due'],
                   '요청한 자원의 배정 일정이 지연되고 있습니다. 처리 가능 시간을 알려주세요.'),
                  ('deadline_near', self.minute >= t['due']-30,
                   '완료 기한이 얼마 남지 않았습니다. 현재 일정으로 완료 가능한지 확인 부탁드립니다.'),
                  ('deadline_passed', self.minute > t['due'],
                   '약속된 완료 기한을 초과했습니다. 일정 지연이 운영 평가에 반영됩니다. 신속한 처리를 부탁드립니다.')]
        if pending and self.minute >= t['expires']:
            reason = '최종 배정 기한 초과 · 미처리 종료'
            self.db.change_request_status(run.request['id'], 'rejected', reason=reason)
            self._refresh_request(run)
            run.state.phase = 'ready'
            t.update(expired=True, completed=self.minute, evaluation=0)
            self._emit(run, 'unprocessed', reason+' · 요청 평가 0점. 실행 실패와 별도로 기록합니다.')
            self._feedback(run, customer_reaction(run, 'expired'), 'customer_expired')
            return
        for key, applies, text in checks:
            if applies and key not in t['alerts']:
                t['alerts'].append(key)
                self._feedback(run, text, 'customer_'+key)

    def advance_time(self, minutes):
        if isinstance(minutes,bool) or not isinstance(minutes,int) or minutes not in (10,30,60):
            raise ValueError('시간은 10분, 30분 또는 60분 단위로 진행해 주세요.')
        with self._atomic():
            for _ in range(minutes//10):
                self.minute += 10
                for run in list(self.runs.values()):
                    before = run.state.phase
                    if run.state.allocated and self.hardware_servers(run):
                        run.state.elapsed += 10
                        run.hardware_downtime += 10
                    elif run.state.allocated and run.migration_left:
                        run.state.elapsed += 10
                        run.migration_downtime += 10
                        run.migration_left -= 10
                        if not run.migration_left:
                            self._emit(run, 'migration_ready', '작업 이전 준비 완료. 남아 있는 네트워크 상태를 유지하며 다음 구간부터 실행합니다.')
                            self._feedback(run, '작업 이전 준비가 끝났습니다. '
                                           +('기존 네트워크 장애/준비는 별도로 확인해 주세요.' if run.state.phase != 'running' else
                                             '다음 시간 구간부터 기존 작업을 계속해 주세요.'), 'customer_migration_ready')
                    else:
                        run.state.advance(10)
                    if before == 'running' and run.state.phase == 'incident':
                        self._emit(run,'incident',f'긴급 경고! {run.mission["country"]} 네트워크 장애 감지. 작업 진행이 멈췄습니다.')
                        self._feedback(run,'작업이 지연되고 있습니다. 현재 복구 상황을 알려주세요.', 'customer_incident')
                    if before == 'recovering' and run.state.phase == 'running':
                        self._emit(run,'recovery','복구 준비가 끝나 정상 실행을 재개했습니다.')
                        self._feedback(run,'작업이 재개된 것을 확인했습니다. 남은 일정에 맞춰 진행 부탁드립니다.', 'customer_recovery')
                    self._finish_if_needed(run)
                    self._check_deadlines(run)
                self._advance_repairs()
                self._deliver_scheduled_requests()

    def respond(self, key):
        run = self.current
        with self._atomic():
            run.state.resolve(key)
            self._emit(run,'response',f'{RESPONSES[key]["label"]}: 필요 {run.state.network_needed} / 가용 {run.state.network_available}. {run.state.result_text}')
            if run.state.phase == 'paused':
                self._feedback(run,'복구가 아직 완료되지 않았습니다. 추가 대응 계획을 부탁드립니다.')
            self._finish_if_needed(run)
        return run.messages[-1:]

    def notify_delay(self):
        run = self.current
        if not self.can_notify_delay(run):
            raise ValueError('안내가 필요한 새 지연 상황이 없거나 같은 상황의 안내를 이미 전달했습니다.')
        with self._atomic():
            run.delay_notified = True
            run.delay_notice_key = self._delay_notice_key(run)
            if run.state.allocated:
                run.state.cost_penalty += 5
            if self.hardware_servers(run) or run.migration_left:
                self._emit(run,'notice','고객에게 서버 장애/이전 준비로 인한 지연을 안내했습니다.\n'+self.delay_reason(run))
                text = '서버 복구·작업 이전 일정을 확인했습니다. 기존 완료 기한은 유지됩니다.'
            elif run.state.phase in ('incident','paused','recovering'):
                self._emit(run,'notice','고객에게 장애와 지연을 안내하고 복구 계획을 전달했습니다.\n'+self.delay_reason(run))
                text = '안내 감사합니다. 복구 작업이 완료될 때까지 기다리겠습니다.'
            else:
                self._emit(run,'notice','고객에게 예상 일정 지연을 안내했습니다. 완료 기한은 유지됩니다.\n'+self.delay_reason(run))
                text = f'일정 안내 감사합니다. 남은 처리 예상 {run.state.remaining_minutes}분을 확인했습니다. 약속된 완료 기한은 유지됩니다.'
            self._feedback(run,text,'customer_notice')

    def can_notify_delay(self, run):
        key = self._delay_notice_key(run)
        return key is not None and key != run.delay_notice_key

    def delay_reason(self, run):
        """표시와 전송에 같은 판정을 사용하고 정상·종료 작업은 제외합니다."""
        s = run.state
        if not s.allocated or run.followup_closed:
            return ''
        repair = max((self.servers.hardware[key].repair_left for key in self.hardware_servers(run)), default=0)
        finish, due = self.minute+s.remaining_minutes+run.migration_left+repair, run.terms.get('due')
        issue = (f'네트워크 장애 · 필요 {s.network_needed} / 가용 {s.network_available} · '
                 f'중단 {s.downtime}/60분 · 대응 {s.response_attempts}/3 · 복구 시각 미정' if s.phase in ('incident','paused') else
                 f'복구·재처리 준비 {s.recovery_left}분 · 일정 변경 안내 필요' if s.phase == 'recovering' else '')
        hardware = self.hardware_status(run)
        issue = '\n'.join(v for v in (hardware, issue) if v)
        if due is not None and (finish > due or self.minute > due):
            timing = (f'완료 기한 {game_time(due)} / 예상 완료 {game_time(finish)} / '
                      f'{max(0, finish-due)}분 지연 예상')
            if self.minute > due:
                timing += f' · 현재 {self.minute-due}분 기한 초과'
            return issue+'\n'+timing if issue else timing
        return issue

    def _delay_notice_key(self, run):
        if not self.delay_reason(run):
            return None
        s = run.state
        base = [s.retry_count, run.terms.get('due'), self.minute > run.terms['due'] if run.terms else False]
        if self.hardware_servers(run) or run.migration_left:
            events = sum(e['kind'] in ('hardware_fault', 'hardware_repair', 'migration')
                         for e in self.db.get_request_events(run.request['id']))
            return base + ['hardware', list(self.hardware_servers(run)), bool(run.migration_left), events,
                           s.phase, s.response_attempts]
        if s.phase in ('incident','paused'):
            # 중단 중 시간 경과만으로 같은 장애 안내가 다시 활성화되지 않습니다.
            incidents = sum(e['kind'] == 'incident' for e in self.db.get_request_events(run.request['id']))
            return base + ['incident', incidents, s.work_done, s.response_attempts]
        return base + ['schedule', self.minute+s.remaining_minutes]

    def report_failure(self):
        run = self.current
        with self._atomic():
            if run.state.allocated:
                run.state.response = 'report_failure'
                run.state.finish(False,'고객에게 처리 불가를 보고하고 수행을 중단했습니다.')
                self._finish_if_needed(run)
            if run.state.phase != 'finished' or run.state.succeeded or run.followup_closed:
                raise ValueError('후속 대응이 필요한 실패 작업만 최종 보고할 수 있습니다.')
            run.followup_closed = True
            self._emit(run,'final_report','고객에게 처리 불가와 피해 사실을 설명하고 최종 실패로 보고했습니다.')
            self._feedback(run,'처리 불가 사유를 확인했습니다. 이번 요청은 종료하겠습니다.')

    def retry(self, key):
        run = self.current
        old = run.state
        if old.phase != 'finished' or old.succeeded or run.followup_closed:
            raise ValueError('후속 대응이 필요한 실패 수행만 재처리할 수 있습니다.')
        if old.retry_count >= 2:
            raise ValueError('재처리는 요청당 2회까지 가능합니다. 처리 불가 보고를 선택해 주세요.')
        with self._atomic():
            parent = run.playthrough_id
            run.state = GameState(center=self.center,country=run.mission['country'],retry_count=old.retry_count+1)
            run.delay_notified = False
            run.delay_notice_key = None
            self._start(run,key,retry=True)
            self.db.link_retry(run.request['id'],run.playthrough_id,parent,run.state.retry_count)
            self._refresh_request(run)
            self._emit(run,'retry',f'실패 수행 #{parent} 재처리. 새 수행 #{run.playthrough_id}, 준비 20분, 최종 점수 추가 차감 {run.state.retry_count*10}점.')
            self._feedback(run,'재처리 계획을 확인했습니다. 추가 준비 후 결과를 알려주세요.')

    def restart(self):
        if self.story:
            raise ValueError('현재 제공되는 스토리는 Chapter 1까지입니다. 다음 요청은 이후 미션에서 제공됩니다.')
        run = self.current
        if run.request['status'] not in ('completed','rejected') or (run.state.succeeded is False and not run.followup_closed):
            raise ValueError('이전 요청의 후속 조치를 마친 뒤 새 요청을 받아 주세요.')
        with self._atomic():
            self.selected_id = self._receive(run.mission['id'])

    def conversation(self, rid, history=False):
        run = self.runs[rid]
        events = [e for e in self.db.get_request_events(rid)
                  if e['kind'].startswith('customer_') or e['kind'] in ('feedback','notice','decision','final_report','proposal')]
        if history:
            prefix = [] if any(e['kind']=='customer_request' for e in events) else [('과거 요청 기록', run.request['message'])]
            return prefix + [
                (run.mission['company_name'] if e['kind'].startswith('customer_') or e['kind']=='feedback'
                 else '운영 담당자 · 기록', e['message']) for e in events]
        # 상태 전환 전의 요청/장애 대화가 새 사건의 앞뒤에 다시 붙지 않게 합니다.
        # 읽지 않은 사건은 시간순으로 표시하고, 협의 중인 대안은 재열람해도 비교 내용을 유지합니다.
        lifecycle = {'customer_request','customer_accept','customer_start','customer_incident',
                     'customer_recovery','customer_complete','customer_failure','customer_reject','customer_expired',
                     'customer_hardware_fault','customer_hardware_repair','customer_hardware_recovered',
                     'customer_migration','customer_migration_ready',
                     'proposal'}
        boundary = max((e['id'] for e in events if e['kind'] in lifecycle), default=0)
        if run.proposals and run.request['status'] in ('new','review','waiting'):
            # 수락만/배정 대기는 대안에 대한 고객 동의와 별개이므로 제안 내용을 가리지 않습니다.
            boundary = max((e['id'] for e in events if e['kind'] == 'proposal'), default=boundary)
        if not boundary:
            if run.request['status'] in ('new','review','waiting'):
                return [(run.mission['company_name'], run.request['message'])]
            if run.state.phase == 'finished':
                return [('운영 시스템', run.state.result_text)]
            if run.request['status'] == 'rejected':
                return [('운영 담당자', '요청 종료: '+str(run.request['rejection_reason']))]
            return [(run.mission['company_name'], run.last_feedback or '현재 작업을 운영 중입니다.')]
        current = [e for e in events if e['id'] >= boundary]
        unread = [e for e in current if e['id'] > run.message_read_id]
        selected = unread or (current if current[0]['kind'] == 'proposal' else current[-1:])
        if selected:
            return [(run.mission['company_name'] if e['kind'].startswith('customer_') or e['kind']=='feedback'
                     else '운영 담당자', e['message']) for e in selected]
        if run.state.phase in ('ready','accepted') and run.request['status'] not in ('completed','rejected'):
            return [(run.mission['company_name'], run.request['message'])]
        return [('운영 시스템', run.last_feedback or run.state.result_text or REQUEST_LABELS[run.request['status']])]

    def read_conversation(self, rid):
        """새 메시지 표시와 과거 기록 읽기를 분리하고 확인 지점을 원자적으로 저장합니다."""
        with self._atomic():
            steps = self.conversation(rid)
            events = self.db.get_request_events(rid)
            self.runs[rid].message_read_id = max((e['id'] for e in events), default=0)
            self.db.mark_request_read(rid)
            self._refresh_request(self.runs[rid])
            self.selected_id = rid
            if self.story and self.story.request_id == rid:
                self.story.request_read = True
            if self.story and self.story.chapter2_active:
                self.story.chapter2.mark_read(rid)
        return steps

    def recent_records(self):
        return self.db.get_recent_records(50)
    def logs(self, run_id):
        return self.db.get_logs(run_id)
    def save(self):
        with self._atomic():
            pass
    def close(self):
        self.save()
        self.db.close()
