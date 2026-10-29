"""요청 접수, 가상 시간, 동시 운영과 SQLite 저장의 일관성을 관리합니다."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from copy import deepcopy
import random

from database import Database
from game import DataCenter, GameState, RESPONSES, plans_for, request_terms, game_time

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
    terms: dict = field(default_factory=dict)
    message_read_id: int = 0


class GameSession:
    def __init__(self, db: Database, seed=None, incident_chance=None):
        self.db, self.center = db, DataCenter()
        self.missions = {m['id']:m for m in db.get_missions()}
        saved = db.get_simulation()
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
        self.selected_id = next((rid for rid,r in self.runs.items() if r.request['status'] not in ('completed','rejected')),
                                next(reversed(self.runs)))

    @property
    def current(self):
        return self.runs[self.selected_id]
    @property
    def time_label(self):
        return f'D{self.minute//1440+1} {self.minute//60%24:02d}:{self.minute%60:02d}'
    @property
    def has_next_request(self):
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
                             message_read_id=snapshot.get('message_read_id', 0))
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
        return run

    def _persist(self):
        self.db.save_simulation({'minute':self.minute,'seed':self.seed,'roll_index':self.roll_index,
                                 'incident_chance':self.incident_chance,
                                 'arrivals':{'next_minute':self.next_arrival_minute, 'slot':self.arrival_index,
                                             'last_by_mission':self.arrival_last}})
        for rid,run in self.runs.items():
            state = {k:v for k,v in vars(run.state).items() if k != 'center'}
            self.db.save_runtime(rid,run.playthrough_id,{'state':state,'followup_closed':run.followup_closed,
                                  'last_feedback':run.last_feedback,'delay_notified':run.delay_notified,
                                  'terms':run.terms, 'message_read_id':run.message_read_id, 'version':2})

    @contextmanager
    def _atomic(self):
        before = {rid:(run, {**vars(run), 'terms':deepcopy(run.terms)}, vars(run.state).copy(),list(run.messages),dict(run.request))
                  for rid,run in self.runs.items()}
        usage = self.center.gpu_used,self.center.power_used
        clock = self.minute,self.roll_index,self.selected_id
        arrivals = self.next_arrival_minute,self.arrival_index,dict(self.arrival_last)
        try:
            with self.db.transaction():
                yield
                self._persist()
        except Exception:
            self.runs.clear()
            for rid,(run,fields,state,messages,request) in before.items():
                vars(run).update(fields)
                vars(run.state).update(state)
                run.messages, run.request = messages,request
                self.runs[rid] = run
            self.center.gpu_used,self.center.power_used = usage
            self.minute,self.roll_index,self.selected_id = clock
            self.next_arrival_minute,self.arrival_index,self.arrival_last = arrivals
            raise

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

    def _message(self, mission):
        p,e = (plans_for(mission['country'])[k] for k in ('performance','economy'))
        return (f'[신규 작업 요청]\n발신: {mission["company_name"]}\n국가: {mission["country"]}\n\n안녕하세요.\n'
                f'{mission["description"]}\n요청 작업: {mission["title"]}\n\n'
                f'요청 GPU: {p["gpu"]}개 / 전력: {p["power"]}단위 / 네트워크: {p["network"]}단위\n'
                f'절약형: GPU {e["gpu"]}개 / 전력 {e["power"]}단위\n\n가능한 자원과 운영 일정을 확인해 회신 부탁드립니다. 감사합니다.')

    def _receive(self, mid, key=None):
        existing = self.db.find_request_by_source(key) if key is not None else None
        if existing is not None:
            if existing['id'] not in self.runs:
                self.runs[existing['id']] = self._load_run(existing)
            return existing['id']
        rid = self.db.create_request(mid,self._message(self.missions[mid]),key)
        run = self._load_run(self.db.get_request(rid))
        self.runs[rid] = run
        run.terms = request_terms(run.mission['country'], self.minute)
        self.arrival_last[mid] = self.minute
        self._emit(run,'arrival',f'새 업무 메시지: {run.mission["company_name"]} · {run.mission["country"]}')
        self._feedback(run, self._message(run.mission)+'\n\n'+self.deadline_summary(run)
                       +f'\n미배정 요청의 최종 접수 종료: {game_time(run.terms["expires"])}', 'customer_request')
        return rid

    def deliver_next_request(self):
        """최초 요청 접수 보조 함수. GUI는 시간 기반 자동 접수를 사용합니다."""
        received = {r.mission['id'] for r in self.runs.values()}
        for mid in self.missions:
            if mid not in received:
                with self._atomic():
                    rid = self._receive(mid,f'initial:{mid}')
                return rid
        return None

    def _deliver_scheduled_requests(self):
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

    def _start(self, run, key, retry=False):
        s = run.state
        if run.terms and self.minute >= run.terms['expires'] and not retry:
            raise ValueError('최종 배정 기한을 초과한 요청입니다.')
        if key not in s.plans:
            raise ValueError('존재하지 않는 운영 모드입니다.')
        p = s.plans[key]
        shortage = []
        for name,needed,available in (('GPU',p['gpu'],self.center.available_gpu()),('전력',p['power'],self.center.available_power())):
            if needed > available:
                shortage.append(f'{name} {needed-available}{"개" if name=="GPU" else "단위"}')
        if shortage:
            raise ValueError('자원 부족: '+' / '.join(shortage)+'. 대기하거나 다른 작업 완료를 기다리세요.')
        s.choose_plan(key)
        rng = random.Random(self.seed+self.roll_index)
        self.roll_index += 1
        s.incident_at = s.work_total*rng.uniform(.35,.65) if rng.random() < self.incident_chance else None
        run.playthrough_id = self.db.create_playthrough(run.mission['id'],key)
        if not retry:
            self.db.change_request_status(run.request['id'],'operating',run.playthrough_id)
        self._emit(run,'start',f'[고객 요청 #{run.request["id"]}] {run.mission["company_name"]} · {run.mission["title"]}')
        self._emit(run,'allocation',f'{s.plans[key]["label"]}: GPU {s.gpu_used} / 전력 {s.power_used} 배정. 정상 실행을 시작합니다.')
        if run.terms and not retry:
            run.terms['started'] = self.minute
        self._feedback(run,'현재 작업이 진행 중인 것으로 확인했습니다. 완료 결과를 기다리겠습니다.', 'customer_start')

    def choose_plan(self, key):
        run = self.current
        if run.request['status'] not in ('new','review','waiting'):
            raise ValueError('이미 처리한 요청은 중복 수락할 수 없습니다.')
        with self._atomic():
            self._start(run,key)
            self._refresh_request(run)
        return run.messages[-2:]

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
                self._feedback(run,'회신과 거절 사유를 확인했습니다. 이번 요청은 종료하겠습니다.', 'customer_reject')

    def _finish_if_needed(self, run):
        s = run.state
        if s.phase == 'finished' and run.request['status'] == 'operating':
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
            self._feedback(run,('작업 완료는 확인했지만 예상 일정보다 지연되었습니다. 다음 작업에서는 일정 준수를 부탁드립니다.' if late else
                           '작업 완료를 확인했습니다. 감사합니다.') if s.succeeded else
                           '작업이 중단되었습니다. 장애 사실과 복구 계획을 알려주시기 바랍니다.',
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
            self._feedback(run,'최종 배정 기한까지 작업이 시작되지 않아 요청을 철회합니다. 미처리로 기록해 주세요.', 'customer_expired')
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
                    run.state.advance(10)
                    if before == 'running' and run.state.phase == 'incident':
                        self._emit(run,'incident',f'긴급 경고! {run.mission["country"]} 네트워크 장애 감지. 작업 진행이 멈췄습니다.')
                        self._feedback(run,'작업이 지연되고 있습니다. 현재 복구 상황을 알려주세요.', 'customer_incident')
                    if before == 'recovering' and run.state.phase == 'running':
                        self._emit(run,'recovery','복구 준비가 끝나 정상 실행을 재개했습니다.')
                        self._feedback(run,'작업이 재개된 것을 확인했습니다. 남은 일정에 맞춰 진행 부탁드립니다.', 'customer_recovery')
                    self._finish_if_needed(run)
                    self._check_deadlines(run)
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
            raise ValueError('진행 또는 복구가 필요한 작업에서만 지연 안내를 보낼 수 있습니다.')
        if run.delay_notified:
            raise ValueError('이번 수행의 지연 안내는 이미 전달했습니다.')
        with self._atomic():
            run.delay_notified = True
            if run.state.allocated:
                run.state.cost_penalty += 5
            if run.state.phase in ('incident','paused','recovering'):
                self._emit(run,'notice','고객에게 장애와 지연을 안내하고 복구 계획을 전달했습니다.')
                text = '안내 감사합니다. 복구 작업이 완료될 때까지 기다리겠습니다.'
            else:
                self._emit(run,'notice','고객에게 예상 일정 지연을 안내했습니다. 완료 기한은 유지됩니다.')
                text = f'일정 안내 감사합니다. 남은 처리 예상 {run.state.remaining_minutes}분을 확인했습니다. 약속된 완료 기한은 유지됩니다.'
            self._feedback(run,text,'customer_notice')

    def can_notify_delay(self, run):
        s = run.state
        return not run.delay_notified and (
            s.phase in ('incident','paused','recovering') or
            (s.phase == 'running' and run.terms and self.minute+s.remaining_minutes > run.terms['due']))

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
            self._start(run,key,retry=True)
            self.db.link_retry(run.request['id'],run.playthrough_id,parent,run.state.retry_count)
            self._refresh_request(run)
            self._emit(run,'retry',f'실패 수행 #{parent} 재처리. 새 수행 #{run.playthrough_id}, 준비 20분, 최종 점수 추가 차감 {run.state.retry_count*10}점.')
            self._feedback(run,'재처리 계획을 확인했습니다. 추가 준비 후 결과를 알려주세요.')

    def restart(self):
        run = self.current
        if run.request['status'] not in ('completed','rejected') or (run.state.succeeded is False and not run.followup_closed):
            raise ValueError('이전 요청의 후속 조치를 마친 뒤 새 요청을 받아 주세요.')
        with self._atomic():
            self.selected_id = self._receive(run.mission['id'])

    def conversation(self, rid, history=False):
        run = self.runs[rid]
        events = [e for e in self.db.get_request_events(rid)
                  if e['kind'].startswith('customer_') or e['kind'] in ('feedback','notice','decision','final_report')]
        if history:
            prefix = [] if any(e['kind']=='customer_request' for e in events) else [('과거 요청 기록', run.request['message'])]
            return prefix + [
                (run.mission['company_name'] if e['kind'].startswith('customer_') or e['kind']=='feedback'
                 else '운영 담당자 · 기록', e['message']) for e in events]
        # 상태 전환 전의 요청/장애 대화가 새 사건의 앞뒤에 다시 붙지 않게 합니다.
        # 읽지 않은 사건은 모두 시간순으로, 이미 확인했으면 현재 상태의 마지막 대화만 표시합니다.
        lifecycle = {'customer_request','customer_accept','customer_start','customer_incident',
                     'customer_recovery','customer_complete','customer_failure','customer_reject','customer_expired'}
        boundary = max((e['id'] for e in events if e['kind'] in lifecycle), default=0)
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
        selected = unread or current[-1:]
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
