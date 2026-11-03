"""독립 서버실 GUI 시안. 게임 모듈·SQLite를 사용하지 않는 고정 샘플 화면입니다.

실행: python server_ui_preview.py
"""
from dataclasses import dataclass
import tkinter as tk
from server_widgets import (ink, gpu_state, reset_hardware, gpu_module, animate_hardware, battery, availability_hint)


BG = '#080e18'
PANEL = '#101c2a'
SURFACE = '#152536'
EDGE = '#2a4054'
TEXT = '#e5eef7'
MUTED = '#91a6bb'
CYAN = '#4ce4cd'
BLUE = '#74abff'
PURPLE = '#c2a0ff'
RED = '#ff6e7f'
FONT = 'Malgun Gothic'
MONO = 'Consolas'


@dataclass(frozen=True)
class Customer:
    key: str
    company: str
    country: str
    task: str
    color: str


CUSTOMERS = {
    'sg': Customer('sg', 'Merlion AI', '싱가포르', '생성형 AI 모델 학습', CYAN),
    'jp': Customer('jp', 'Sakura Robotics', '일본', '로봇 AI 추론', BLUE),
    'us': Customer('us', 'Northstar AI', '미국', '대규모 데이터 분석', PURPLE),
}


@dataclass(frozen=True)
class ServerSpec:
    key: str
    name: str
    gpu: int
    power: int


SERVERS = (
    ServerSpec('A', 'Server A', 4, 4), ServerSpec('B', 'Server B', 3, 2),
    ServerSpec('C', 'Server C', 2, 3), ServerSpec('D', 'Server D', 1, 1),
)


@dataclass(frozen=True)
class SampleUsage:
    owner: str | None = None
    gpu: int = 0
    power: int = 0
    fault: bool = False


@dataclass(frozen=True)
class PreviewDemand:
    """선택 서버의 표시 비교만을 위한 고정 요청. 실제 배정과 무관합니다."""
    gpu: int = 3
    power: int = 2




@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    usage: tuple[SampleUsage, ...]
    completed: tuple[str, ...] = ()

    def __post_init__(self):
        if len(self.usage) != len(SERVERS):
            raise ValueError('샘플은 서버 4개의 사용량이 필요합니다.')
        for spec, used in zip(SERVERS, self.usage):
            if (type(used.gpu) is not int or type(used.power) is not int
                    or not 0 <= used.gpu <= spec.gpu or not 0 <= used.power <= spec.power):
                raise ValueError('샘플 사용량이 서버 용량을 초과하거나 올바르지 않습니다.')
            occupied = used.gpu > 0 or used.power > 0
            if (used.owner is not None and used.owner not in CUSTOMERS) or occupied != (used.owner is not None):
                raise ValueError('점유 고객과 샘플 자원 사용량이 일치하지 않습니다.')
        owners = {u.owner for u in self.usage if u.owner}
        if any(key not in CUSTOMERS or key in owners for key in self.completed):
            raise ValueError('완료 고객이 자원을 점유하거나 존재하지 않습니다.')

    def summary(self):
        gpu = sum(u.gpu for u in self.usage)
        power = sum(u.power for u in self.usage)
        return {'gpu_total': sum(s.gpu for s in SERVERS), 'gpu_used': gpu,
                'gpu_available': sum(s.gpu for s in SERVERS)-gpu,
                'power_total': sum(s.power for s in SERVERS), 'power_used': power,
                'power_available': sum(s.power for s in SERVERS)-power,
                'active_servers': sum(u.owner is not None for u in self.usage),
                'jobs': len({u.owner for u in self.usage if u.owner}),
                'fault_servers': sum(u.fault for u in self.usage)}


EMPTY = SampleUsage()
SCENARIOS = (
    Scenario('initial', '초기 상태', '모든 서버가 비어 있습니다. GPU와 전력의 가용량을 확인해 보세요.',
             (EMPTY, EMPTY, EMPTY, EMPTY)),
    Scenario('assigned', '학습 배정', 'Server A에 싱가포르 학습 작업을 표시합니다. GPU 3 · 전력 3 점유 예시입니다.',
             (SampleUsage('sg', 3, 3), EMPTY, EMPTY, EMPTY)),
    Scenario('parallel', '동시 운영', '싱가포르는 Server A, 일본은 Server B를 점유합니다. 서로 다른 고객을 색상과 이름으로 구분합니다.',
             (SampleUsage('sg', 3, 3), SampleUsage('jp', 2, 1), EMPTY, EMPTY)),
    Scenario('distributed', '분산 시안', '싱가포르 GPU 7 · 전력 7을 A(4/4), B(1/1), C(2/2)에 나눈 화면 예시입니다.',
             (SampleUsage('sg', 4, 4), SampleUsage('sg', 1, 1), SampleUsage('sg', 2, 2), EMPTY)),
    Scenario('returned', '학습 완료', '싱가포르 작업이 끝나 Server A가 비워집니다. Server B의 일본 작업은 계속 점유합니다.',
             (EMPTY, SampleUsage('jp', 2, 1), EMPTY, EMPTY), ('sg',)),
    Scenario('fault', '장애 표시', '세 고객의 점유 상태에서 Server C의 장애 표시를 비교합니다. 점유 자원은 유지되는 고정 샘플입니다.',
             (SampleUsage('sg', 3, 3), SampleUsage('jp', 2, 1), SampleUsage('us', 2, 2, True), EMPTY)),
)


def server_status(usage):
    return 'FAULT' if usage.fault else 'ACTIVE' if usage.owner else 'IDLE'














class Overview(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg=PANEL, height=94, highlightthickness=1, highlightbackground=EDGE)
        self.scenario = SCENARIOS[0]
        self.bind('<Configure>', lambda _: self.draw())

    def draw(self):
        self.delete('all')
        reset_hardware(self)
        w = self.winfo_width()
        if w < 50:
            return
        summary = self.scenario.summary()
        gpu_end = w*.34
        power_end = w*.66
        for x in (gpu_end, power_end):
            self.create_line(x, 16, x, 78, fill=EDGE)
        ink(self, 18, 11, 'GPU AVAILABLE', 9, MUTED, True)
        available = summary['gpu_available']
        ink(self, 17, 29, f'{available:02d}', 29, CYAN, True)
        ink(self, 81, 53, '/ 10', 12, MUTED)
        start = 125
        chip_width = (gpu_end-start-22)/5-4
        modules = [(gpu_state(u, index), u.owner) for spec, u in zip(SERVERS, self.scenario.usage)
                   for index in range(spec.gpu)]
        for i, (state, owner) in enumerate(modules):
            gpu_module(self, start+(i % 5)*(chip_width+4), 31+(i//5)*22,
                       chip_width, 18, state, owner, body_tags=('summary-gpu',), summary=True)
        ink(self, 18, 78, f'가용 {available} / 총 10 · 사용 {summary["gpu_used"]}', 9, MUTED)
        px = gpu_end+20
        ink(self, px, 11, 'POWER / 가용 전력', 9, MUTED, True)
        power = summary['power_available']
        ink(self, px, 32, f'{power:02d}', 25, CYAN, True)
        ink(self, px+60, 53, '/ 10', 12, MUTED)
        battery(self, px+110, 35, max(75, power_end-px-130), 32, power, 10)
        ink(self, px, 78, f'가용 {power} / 총 10 · 사용 {summary["power_used"]}', 9, MUTED)
        cell = (w-power_end)/3
        for i, (name, key) in enumerate((('운영 서버', 'active_servers'), ('진행 작업', 'jobs'), ('장애 서버', 'fault_servers'))):
            x = power_end+cell*(i+.5)
            ink(self, x, 15, name, 10, MUTED, anchor='n')
            color = RED if key == 'fault_servers' and summary[key] else TEXT
            ink(self, x, 38, f'{summary[key]:02d}', 23, color, True, anchor='n')
            ink(self, x, 77, '/ 4' if key != 'jobs' else '고객 작업 수', 9, MUTED, anchor='n')


class Inbox(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=EDGE)
        self.scenario = SCENARIOS[0]
        self.bind('<Configure>', lambda _: self.draw())

    def draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        ink(self, 15, 16, 'AIDC LINK', 12, CYAN, True)
        ink(self, 15, 40, '고객 요청함 / 샘플 03', 10, MUTED)
        card_h = min(106, (h-91)/3)
        for i, customer in enumerate(CUSTOMERS.values()):
            y = 71+i*(card_h+7)
            occupied = [(s, u) for s, u in zip(SERVERS, self.scenario.usage) if u.owner == customer.key]
            self.create_rectangle(12, y, w-12, y+card_h, fill=SURFACE, outline=EDGE)
            self.create_rectangle(12, y, 15, y+card_h, fill=customer.color, outline='')
            ink(self, 25, y+9, f'REQ 00{i+1} / {customer.country}', 9, customer.color)
            ink(self, 25, y+31, customer.company, 11, TEXT, True)
            ink(self, 25, y+52, customer.task, 9, MUTED)
            text = '대기 · 미점유'
            if occupied:
                text = f'샘플 실행 · GPU {sum(u.gpu for _, u in occupied)} / 전력 {sum(u.power for _, u in occupied)}'
            elif customer.key in self.scenario.completed:
                text = '완료 · 자원 반환'
            ink(self, 25, y+card_h-19, text, 9, customer.color if occupied else MUTED)


class ServerRoom(tk.Canvas):
    def __init__(self, parent, on_select):
        super().__init__(parent, bg='#0a1421', highlightthickness=1, highlightbackground=EDGE, takefocus=True)
        self.on_select = on_select
        self.scenario = SCENARIOS[0]
        self.selected = 'A'
        self.rack_bounds = {}
        self.columns = 4
        self.phase = 0
        self.bind('<Configure>', lambda _: self.draw())
        for key, step in (('<Left>', -1), ('<Right>', 1), ('<Up>', -2), ('<Down>', 2)):
            self.bind(key, lambda _, amount=step: self.move_selection(amount))

    def move_selection(self, step):
        index = next(i for i, spec in enumerate(SERVERS) if spec.key == self.selected)
        self.on_select(SERVERS[(index+step) % len(SERVERS)].key)

    def draw(self):
        self.delete('all')
        reset_hardware(self)
        self.rack_bounds.clear()
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80 or h < 80:
            return
        ink(self, 18, 15, 'SERVER FLOOR', 12, TEXT, True)
        ink(self, w-18, 18, 'ULSAN / HALL 01', 9, MUTED, anchor='ne')
        ink(self, 18, 41, '서버를 클릭해 잔량과 점유 고객을 확인하세요', 9, MUTED)
        # 바닥의 얇은 원근 격자는 장비의 정면 표현과 분리합니다.
        for i in range(9):
            x = w*i/8
            self.create_line(w/2+(x-w/2)*.6, 68, max(4, min(w-4, x)), h-4, fill='#132437')
        for y in range(80, h, 36):
            self.create_line(4, y, w-4, y, fill='#132437')
        self.columns = 4 if w >= 640 else 2
        rows = 1 if self.columns == 4 else 2
        gap, margin, top, bottom = 12, 18, 73, 24
        rw = (w-margin*2-gap*(self.columns-1))/self.columns
        rh = (h-top-bottom-gap*(rows-1))/rows
        for i, (spec, used) in enumerate(zip(SERVERS, self.scenario.usage)):
            x = margin+(i % self.columns)*(rw+gap)
            y = top+(i//self.columns)*(rh+gap)
            self.rack_bounds[spec.key] = (x, y, x+rw, y+rh)
            self.draw_rack(spec, used, x, y, rw, rh)

    def draw_rack(self, spec, used, x, y, w, h):
        tag = f'server-{spec.key}'
        tags = (tag,)
        color = RED if used.fault else CUSTOMERS[used.owner].color if used.owner else '#5b7185'
        selected = spec.key == self.selected
        self.create_rectangle(x+3, y+5, x+w+3, y+h+5, fill='#050b13', outline='', tags=tags)
        self.create_polygon(x+8, y, x+w-8, y, x+w, y+8, x+w, y+h-8, x+w-8, y+h,
                            x+8, y+h, x, y+h-8, x, y+8,
                            fill='#152232', outline=CYAN if selected else EDGE, width=2 if selected else 1, tags=tags)
        # 장착 레일, 고정 볼트, 전원 LED와 상태 표시를 독자적인 Canvas 도형으로 그립니다.
        for rail in (x+7, x+w-10):
            self.create_rectangle(rail, y+33, rail+3, y+h-13, fill='#24364a', outline='', tags=tags)
            for sy in (y+38, y+h-20):
                self.create_oval(rail-1, sy, rail+4, sy+5, fill='#8394a4', outline='', tags=tags)
        ink(self, x+14, y+10, spec.name, 11, TEXT, True, tags=tags)
        self.create_oval(x+w-25, y+12, x+w-17, y+20, fill=color if used.owner or used.fault else CYAN,
                         outline='', tags=tags+('power-led',))
        tall = self.columns == 4
        if tall:
            ink(self, x+16, y+37, server_status(used), 9, color, True, tags=tags)
            self.create_line(x+14, y+59, x+w-14, y+59, fill=EDGE, tags=tags)
            slots_top = y+72
            slot_h = 27
        else:
            slots_top = y+35
            slot_h = 27
        for index in range(4):
            module_w = min(64, (w-42)/2) if tall else (w-30)/4-4
            sy = slots_top+(index//2)*(slot_h+12) if tall else slots_top
            left = (x+(w-2*module_w-12)/2+(index % 2)*(module_w+12)
                    if tall else x+15+index*(w-30)/4)
            exists = index < spec.gpu
            gpu_module(self, left, sy, module_w, slot_h, gpu_state(used, index, exists), used.owner, index,
                       tags=tags, body_tags=('gpu-slot',) if exists else ('spare-bay',))
        ga, pa = spec.gpu-used.gpu, spec.power-used.power
        if tall:
            resource_y = y+h-112
            ink(self, x+16, resource_y, 'GPU AVAILABLE', 8, MUTED, True, tags=tags)
            ink(self, x+16, resource_y+16, f'{ga} / {spec.gpu}', 21, RED if used.fault else CYAN, True, tags=tags)
            hint, hint_color = availability_hint(ga, spec.gpu, fault=used.fault)
            ink(self, x+w-16, resource_y+31, hint, 8, hint_color, anchor='e', tags=tags)
            ink(self, x+16, y+h-57, f'전력 가용 {pa}/{spec.power}', 9, TEXT, tags=tags)
            battery(self, x+16, y+h-35, w-32, 19, pa, spec.power, tags)
            # 고객 이름은 점유가 있을 때만 나타납니다.
            owner_y = min(slots_top+2*(slot_h+12)+8, resource_y-28)
            ink(self, x+w/2, owner_y, CUSTOMERS[used.owner].company if used.owner else '미점유',
                9, color if used.owner else MUTED, anchor='n', tags=tags+('owner-label',))
        else:
            ink(self, x+16, y+h-70, f'GPU {ga}/{spec.gpu}', 12, RED if used.fault else CYAN, True, tags=tags)
            battery(self, x+w-96, y+h-69, 80, 19, pa, spec.power, tags)
            ink(self, x+w-16, y+h-48, f'전력 가용 {pa}/{spec.power}', 8, MUTED, anchor='ne', tags=tags)
            owner = CUSTOMERS[used.owner].company if used.owner else '미점유'
            ink(self, x+16, y+h-16, f'{server_status(used)} · {owner}', 9, color, anchor='w', tags=tags+('owner-label',))
        self.tag_bind(tag, '<Button-1>', lambda _, key=spec.key: self.select(key))
        self.tag_bind(tag, '<Enter>', lambda _: self.configure(cursor='hand2'))
        self.tag_bind(tag, '<Leave>', lambda _: self.configure(cursor=''))

    def select(self, key):
        self.focus_set()
        self.on_select(key)

    def animate(self, phase=None):
        self.phase = self.phase+1 if phase is None else phase
        animate_hardware(self, self.phase)


class ServerDetails(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=EDGE)
        self.spec, self.usage = SERVERS[0], EMPTY
        self.demand = None
        self.values = {}
        self.bind('<Configure>', lambda _: self.draw())

    def draw(self):
        self.delete('all')
        reset_hardware(self)
        w, h = self.winfo_width(), self.winfo_height()
        spec, used = self.spec, self.usage
        ga, pa = spec.gpu-used.gpu, spec.power-used.power
        self.values = {'name':spec.name, 'gpu_total':spec.gpu, 'gpu_used':used.gpu, 'gpu_available':ga,
                       'power_total':spec.power, 'power_used':used.power, 'power_available':pa,
                       'owner':CUSTOMERS[used.owner].company if used.owner else '없음', 'status':server_status(used)}
        ink(self, 16, 16, 'SERVER INSPECTOR', 10, MUTED, True)
        ink(self, 16, 42, spec.name, 20, TEXT, True)
        color = RED if used.fault else CUSTOMERS[used.owner].color if used.owner else MUTED
        ink(self, w-17, 53, server_status(used), 10, color, True, anchor='ne')
        self.create_line(16, 80, w-16, 80, fill=EDGE)
        # 두 잔량 영역은 모양과 레이블을 모두 달리합니다.
        ink(self, 16, 90, 'GPU / 연산 장비', 10, MUTED, True)
        required = self.demand.gpu if self.demand else None
        hint, hint_color = availability_hint(ga, spec.gpu, required, used.fault)
        self.values.update(gpu_shortage=max(0, required-ga) if required is not None and not used.fault else 0,
                           power_shortage=max(0, self.demand.power-pa) if self.demand and not used.fault else 0)
        ink(self, 16, 110, f'{ga} / {spec.gpu}', 25, RED if used.fault else CYAN, True)
        ink(self, w-17, 128, hint, 9, hint_color, anchor='ne', tags=('gpu-availability-hint',))
        slot_w = (w-38)/4
        for index in range(spec.gpu):
            x = 16+index*(slot_w+2)
            gpu_module(self, x, 151, slot_w-3, 26, gpu_state(used, index), used.owner, index,
                       body_tags=('detail-gpu-slot',))
        ink(self, 16, 184, f'총 {spec.gpu}  ·  사용 {used.gpu}  ·  가용 {ga}', 10, MUTED)
        self.create_line(16, 210, w-16, 210, fill=EDGE)
        ink(self, 16, 220, 'POWER / 가용 전력', 10, MUTED, True)
        power_shortage = self.values['power_shortage']
        battery(self, 16, 245, w-32, 29, pa, spec.power, shortage=power_shortage > 0)
        power_text = f'총{spec.power} · 사용{used.power} · 가용{pa}'
        if self.demand and not used.fault:
            power_text += f' · {power_shortage}부족' if power_shortage else ' · 요청 충족'
        ink(self, 16, 283, power_text, 9, RED if power_shortage else MUTED, tags=('power-availability-hint',))
        self.create_line(16, 309, w-16, 309, fill=EDGE)
        ink(self, 16, 319, '점유 고객', 9, MUTED)
        ink(self, 16, 337, self.values['owner'], 12, color if used.owner else TEXT, True, tags=('detail-owner',))
        if h >= 433:
            ink(self, 16, h-22, '샘플 정보 · 실제 게임과 미연결', 9, MUTED, anchor='sw')


class ServerPreviewApp:
    def __init__(self, root):
        self.root = root
        self.scenario = SCENARIOS[0]
        self.selected = 'A'
        self.animation_id = None
        self.animation_phase = 1
        self.closed = False
        root.title('AIDC Simulator · 서버실 GUI 프로토타입')
        root.geometry('1280x680')
        root.minsize(1000, 650)
        root.configure(bg=BG)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        header = tk.Frame(root, bg=BG, height=52)
        header.grid(row=0, sticky='ew', padx=16)
        tk.Label(header, text='AIDC', bg=BG, fg=CYAN, font=(MONO, 24, 'bold')).pack(side='left', pady=8)
        tk.Label(header, text='ULSAN  /  SERVER CONTROL', bg=BG, fg=TEXT,
                 font=(FONT, 11, 'bold')).pack(side='left', padx=14)
        tk.Label(header, text='독립 GUI 시안  ·  샘플 데이터', bg='#173439', fg=CYAN,
                 font=(FONT, 10, 'bold'), padx=12, pady=5).pack(side='right')
        self.compare_var = tk.BooleanVar(value=False)
        self.compare_toggle = tk.Checkbutton(header, text='선택 서버 비교 · GPU3 / 전력2',
                                             variable=self.compare_var,
                                             command=lambda: self.set_comparison(self.compare_var.get()),
                                             bg=BG, fg=MUTED, selectcolor=SURFACE, activebackground=BG,
                                             activeforeground=CYAN, font=(FONT, 9), cursor='hand2')
        self.compare_toggle.pack(side='right', padx=8)
        self.overview = Overview(root)
        self.overview.grid(row=1, sticky='ew', padx=16, pady=(0, 12))
        self.body = tk.Frame(root, bg=BG)
        self.body.grid(row=2, sticky='nsew', padx=16)
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.inbox = Inbox(self.body)
        self.inbox.configure(width=208)
        self.inbox.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        self.room = ServerRoom(self.body, self.select_server)
        self.room.grid(row=0, column=1, sticky='nsew')
        self.details = ServerDetails(self.body)
        self.details.configure(width=244)
        self.details.grid(row=0, column=2, sticky='nsew', padx=(10, 0))
        controls = tk.Frame(root, bg=BG)
        controls.grid(row=3, sticky='ew', padx=16, pady=(12, 0))
        controls.columnconfigure(0, weight=1)
        self.scenario_note = tk.Label(controls, bg=BG, fg=TEXT, anchor='w', justify='left', font=(FONT, 10))
        self.scenario_note.grid(row=0, sticky='ew', pady=(0, 9))
        self.scenario_note.bind('<Configure>', lambda e: self.scenario_note.configure(wraplength=max(100, e.width-5)))
        switches = tk.Frame(controls, bg=BG)
        switches.grid(row=1, sticky='ew')
        self.scenario_buttons = {}
        for index, scenario in enumerate(SCENARIOS):
            switches.columnconfigure(index, weight=1, uniform='scenario')
            button = tk.Button(switches, text=f'{chr(65+index)}  {scenario.title}',
                               command=lambda key=scenario.key: self.set_scenario(key),
                               bg=SURFACE, fg=MUTED, activebackground=EDGE, activeforeground=TEXT,
                               relief='flat', bd=0, padx=6, pady=7, cursor='hand2',
                               font=(FONT, 10, 'bold'), highlightthickness=1, highlightbackground=EDGE)
            button.grid(row=0, column=index, sticky='ew', padx=(0, 8 if index < len(SCENARIOS)-1 else 0))
            self.scenario_buttons[scenario.key] = button
        tk.Label(root, text='VISUAL PROTOTYPE  /  배정·분산·장애는 화면 예시입니다. 실제 게임의 규칙과 저장 데이터에 연결되지 않습니다.',
                 bg=BG, fg=MUTED, font=(FONT, 9), anchor='w').grid(row=4, sticky='ew', padx=16, pady=(8, 9))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Destroy>', self._on_destroy, add='+')
        self.refresh()
        self.animation_id = root.after(450, self._animate)

    def set_scenario(self, key):
        scenario = next((s for s in SCENARIOS if s.key == key), None)
        if scenario is None:
            raise ValueError('존재하지 않는 샘플 화면입니다.')
        self.scenario = scenario
        self.refresh()

    def select_server(self, key):
        if not any(s.key == key for s in SERVERS):
            raise ValueError('존재하지 않는 샘플 서버입니다.')
        self.selected = key
        self.refresh()

    def set_comparison(self, enabled):
        self.compare_var.set(enabled)
        self.details.demand = PreviewDemand() if enabled else None
        self.refresh()

    def refresh(self):
        self.overview.scenario = self.inbox.scenario = self.room.scenario = self.scenario
        self.room.selected = self.selected
        index = next(i for i, spec in enumerate(SERVERS) if spec.key == self.selected)
        self.details.spec, self.details.usage = SERVERS[index], self.scenario.usage[index]
        for canvas in (self.overview, self.inbox, self.room, self.details):
            canvas.draw()
        for canvas in (self.overview, self.room, self.details):
            animate_hardware(canvas, self.animation_phase)
        self.scenario_note.configure(text=f'{self.scenario.title}  /  {self.scenario.description}')
        for key, button in self.scenario_buttons.items():
            button.configure(bg='#1c4648' if key == self.scenario.key else SURFACE,
                             fg=CYAN if key == self.scenario.key else MUTED,
                             text=f'{"●" if key == self.scenario.key else chr(65+list(self.scenario_buttons).index(key))}  '
                                  + next(s.title for s in SCENARIOS if s.key == key))

    def _animate(self):
        self.animation_id = None
        if not self.closed:
            self.animation_phase = (self.animation_phase+1) % 20
            self.room.animate(self.animation_phase)
            for canvas in (self.overview, self.details):
                animate_hardware(canvas, self.animation_phase)
            self.animation_id = self.root.after(450, self._animate)

    def _stop_animation(self):
        self.closed = True
        if self.animation_id is not None:
            self.root.after_cancel(self.animation_id)
            self.animation_id = None

    def _on_destroy(self, event):
        if event.widget == self.root:
            self._stop_animation()

    def close(self):
        self._stop_animation()
        self.root.destroy()


def main():
    root = tk.Tk()
    ServerPreviewApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
