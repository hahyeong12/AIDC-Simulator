"""AIDC Simulator v0.8-4: 서버 장애·장비 복구·작업 이전을 운영하는 관제실."""
import tkinter as tk
from tkinter import ttk, messagebox

from database import Database
from session import GameSession, MAX_PENDING_REQUESTS
from game import RESPONSES, game_time
from server_console import LiveOverview, LiveServerRoom, ServerPanel
from allocation_dialog import AllocationDialog
from ui import (BG, PANEL, BORDER, TEXT, MUTED, CYAN, GREEN, RED, AMBER, FONT,
                ActionButton, RejectionDialog, MessageDialog,
                TextDialog, label, request_status_of, status_of)


class SimulatorApp:
    def __init__(self, root, db=None, **session_options):
        self.root = root
        root.title('AIDC Simulator v0.8-4 | 울산 AI 데이터센터 관제실')
        root.geometry(f'{min(1280, root.winfo_screenwidth()-40)}x{min(680, root.winfo_screenheight()-100)}')
        root.minsize(1000, 650)
        root.configure(bg=BG)
        self.db = db if db is not None else Database()
        self.session = GameSession(self.db, **session_options)
        self.center = self.session.center
        self.message_window = None
        self.allocation_window = None
        self.setup_ui()
        self.refresh()
        self.network.start()
        root.protocol('WM_DELETE_WINDOW', self.on_close)

    @property
    def state(self):
        return self.session.current.state
    @property
    def mission(self):
        return self.session.current.mission
    @property
    def playthrough_id(self):
        return self.session.current.playthrough_id

    def setup_ui(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        borderwidth=0, rowheight=29, font=(FONT, 10))
        style.configure('Treeview.Heading', background=BORDER, foreground=TEXT, font=(FONT, 10, 'bold'))
        style.map('Treeview', background=[('selected', BORDER)], foreground=[('selected', CYAN)])
        style.configure('TNotebook',background=PANEL,borderwidth=0)
        style.configure('TNotebook.Tab',background=BORDER,foreground=MUTED,padding=(7,4))
        style.map('TNotebook.Tab',background=[('selected',PANEL)],foreground=[('selected',CYAN)])
        style.configure('Treeview',bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        header = tk.Frame(self.root, bg=BG, padx=16, pady=8)
        header.grid(row=0, sticky='ew')
        label(header, 'AIDC', 22, CYAN, True).pack(side='left')
        label(header, 'ULSAN / CONTROL ROOM  v0.8-4', 11, bold=True).pack(side='left', padx=12)
        self.notice_var = tk.StringVar()
        self.notice_button = ActionButton(header, 'AIDC LINK', self.open_latest_message)
        self.notice_button.pack(side='right')
        self.status_var = tk.StringVar()
        tk.Label(header, textvariable=self.status_var, bg=BG, fg=CYAN, font=(FONT, 11),
                 justify='right').pack(side='right', padx=14)
        self.overview = LiveOverview(self.root, self.session)
        self.overview.grid(row=1, sticky='ew', padx=12, pady=(0,6))
        body = self.body = tk.Frame(self.root, bg=BG)
        body.grid(row=2, sticky='nsew', padx=12, pady=(0, 5))
        body.columnconfigure(0, minsize=220)
        body.columnconfigure(1, weight=1, minsize=300)
        body.columnconfigure(2, minsize=244)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=PANEL, padx=6, pady=5)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=2, minsize=55)
        left.rowconfigure(4, weight=1, minsize=60)
        label(left, 'AIDC LINK · 고객 요청함', 11, bold=True).grid(row=0, sticky='w', pady=(0, 5))
        self.inbox = self.make_list(left, ('client', 'status'), ('고객 / 국가', '상태 / 기한'), (110, 100), 4)
        self.inbox.grid(row=1, sticky='nsew')
        self.inbox.bind('<ButtonRelease-1>', self.on_inbox_click)
        self.inbox.bind('<Return>', lambda _: self.open_selected_message())
        arrival = tk.Frame(left, bg=BORDER, padx=8, pady=6)
        arrival.grid(row=2, sticky='ew', pady=6)
        arrival.columnconfigure(0, weight=1)
        self.arrival_notice = label(arrival, size=9, justify='left', anchor='w', wraplength=190)
        self.arrival_notice.grid(row=0, sticky='ew')
        self.arrival_request_id = None
        self.arrival_open_button = ActionButton(arrival, '요청 확인', self.open_arrival_message)
        self.arrival_open_button.grid(row=1, sticky='ew', pady=(4, 0))
        self.arrival_schedule = label(arrival, size=9, color=MUTED, anchor='w', wraplength=190)
        self.arrival_schedule.grid(row=2, sticky='ew', pady=(4,0))
        label(left, '운영 작업 · 진행률', 11, bold=True).grid(row=3, sticky='w', pady=(3, 5))
        self.active_list = self.make_list(left, ('client', 'progress'), ('고객', '상태 / 진행'), (70, 140), 3)
        self.active_list.grid(row=4, sticky='nsew')
        self.active_list.bind('<ButtonRelease-1>', self.on_active_click)
        middle = tk.Frame(body, bg=PANEL, padx=0, pady=0)
        middle.grid(row=0, column=1, sticky='nsew', padx=(0, 10))
        self.resources = ServerPanel(body, self.session)
        self.resources.compare_button.configure(command=self.open_allocation_plans)
        self.resources.fault_button.configure(command=lambda:self._perform(
            lambda:self.session.inject_server_fault(self.resources.selected)))
        self.resources.repair_button.configure(command=lambda:self._perform(
            lambda:self.session.begin_server_repair(self.resources.selected)))
        self.network = self.server_room = LiveServerRoom(middle, self.session, self.resources.select_server)
        self.network.pack(fill='both', expand=True)
        self.alert = label(middle, size=10, color=AMBER, justify='left', wraplength=400)
        self.alert.pack(fill='x', pady=(3, 0))
        self.resources.grid(row=0, column=2, sticky='nsew')
        self.network.extra_canvases = [self.overview, self.resources.inspector]
        controls = self.controls = tk.Frame(self.root, bg=PANEL, padx=12, pady=4)
        controls.grid(row=3, sticky='ew', padx=12, pady=(0, 5))
        controls.columnconfigure(0, weight=1)
        self.detail_title = label(controls, size=11, bold=True, anchor='w')
        self.detail_title.grid(row=0, sticky='ew')
        self.action_hint = label(controls, size=9, color=MUTED, anchor='w', justify='left')
        self.action_hint.grid(row=1, sticky='ew', pady=(3, 5))
        self.action_hint.bind('<Configure>', lambda e: self.action_hint.configure(wraplength=max(300, e.width-5)))
        modes = tk.Frame(controls, bg=PANEL)
        modes.grid(row=2, sticky='ew', pady=(0, 5))
        label(modes, '배정 미리보기', 10, MUTED).pack(side='left', padx=(0, 10))
        self.plan_var = tk.StringVar(value='performance')
        self.mode_buttons = {}
        for key, text in (('performance', '고성능 모드'), ('economy', '절약형 모드')):
            button = tk.Radiobutton(modes, text=text, variable=self.plan_var, value=key,
                                    command=lambda:self.preview_plan(show_preview=True), bg=PANEL, fg=TEXT, selectcolor=BORDER,
                                    activebackground=PANEL, activeforeground=CYAN, font=(FONT, 10))
            button.pack(side='left', padx=(0, 12))
            button.bind('<Enter>', lambda _, k=key: self.resources.refresh(k))
            button.bind('<Leave>', lambda _: self.preview_plan())
            self.mode_buttons[key] = button
        self.action_frame = tk.Frame(controls, bg=PANEL)
        self.action_frame.grid(row=3, sticky='ew')
        tools = tk.Frame(self.root, bg=BG, padx=12)
        tools.grid(row=4, sticky='ew', pady=(0, 5))
        label(tools, '가상 시간 진행', 10, CYAN, True).pack(side='left', padx=(0, 10))
        self.time_buttons = {}
        for minutes in (10, 30, 60):
            b = ActionButton(tools, f'+{minutes}분', lambda m=minutes: self.advance_time(m))
            b.pack(side='left', padx=(0, 6))
            self.time_buttons[minutes] = b
        ActionButton(tools, '대화 기록', self.show_conversation_history).pack(side='right', padx=(6, 0))
        ActionButton(tools, '수행 기록', self.show_history).pack(side='right', padx=6)
        ActionButton(tools, '이벤트 / 로그', self.show_events).pack(side='right', padx=6)

    def make_list(self, parent, columns, names, widths, height):
        tree = ttk.Treeview(parent, columns=columns, show='headings', height=height, selectmode='browse')
        for key, name, width in zip(columns, names, widths):
            tree.heading(key, text=name)
            tree.column(key, width=width, minwidth=45, stretch=True)
        # 긴 목록만 자체 스크롤하며 관제실 전체는 스크롤하지 않습니다.
        tree.bind('<MouseWheel>', lambda e: tree.yview_scroll(-int(e.delta/120), 'units'))
        return tree

    def refresh(self):
        self.update_status()
        self.render_actions()
        self.preview_plan()

    def update_status(self):
        active = [r for r in self.session.runs.values() if r.state.phase in ('running','incident','paused','recovering')]
        unread = sum(not r.request['is_read'] for r in self.session.runs.values())
        clock = getattr(self.session, 'time_label', '09:00')
        self.status_var.set(f'{clock}   운영 {len(active)}건\nGPU {self.center.gpu_used}/10 · 전력 {self.center.power_used}/10')
        self.notice_var.set(f'새 업무 메시지 {unread}건' if unread else '모든 메시지 확인함')
        self.notice_button.configure(text=f'AIDC LINK · {self.notice_var.get()}', fg=CYAN if unread else MUTED)
        for tree in (self.inbox, self.active_list):
            for item in tree.get_children():
                tree.delete(item)
        for rid, run in self.session.runs.items():
            name, color = request_status_of(run)
            short = {'new':'신규','review':'검토','waiting':'대기','operating':'운영','rejected':'거절','completed':'완료'}[run.request['status']]
            if run.state.phase == 'accepted': short = '수락'
            elif run.state.phase in ('incident','paused'): short = '장애'
            elif run.state.phase == 'recovering': short = '복구'
            elif run.terms.get('expired'): short = '만료'
            elif run.state.phase == 'finished' and not run.state.succeeded: short = '실패'
            if self.session.hardware_servers(run):
                short, color = '장비', RED
            elif run.state.allocated and run.migration_left:
                short = '이전'
            level = self.session.deadline_level(run)
            if level:
                color = RED if level=='overdue' else AMBER
                name = ('초과 · ' if level=='overdue' else '임박 · ') + name
            tag = f'request-{rid}'
            if run.terms:
                t = run.terms
                wait = t.get('started', t.get('completed', t.get('closed', self.session.minute)))-t['received']
                name = f'{short} {wait}분/{game_time(t["due"]).split()[-1]}'
            self.inbox.tag_configure(tag, foreground=color)
            marker = '● ' if not run.request['is_read'] else ''
            country = {'싱가포르':'SG','일본':'JP','미국':'US'}.get(run.mission['country'],run.mission['country'])
            self.inbox.insert('', 'end', iid=str(rid), values=(f'{marker}{country} · {run.mission["company_name"]}', name), tags=(tag,))
            if run in active:
                status = '서버 장애' if self.session.hardware_servers(run) else '이전 준비' if run.migration_left else status_of(run.state)[0]
                self.active_list.insert('', 'end', iid=str(rid), values=(run.mission['country'], f'{status} {getattr(run.state,"progress",0):.0f}%'))
        self.inbox.selection_set(str(self.session.selected_id))
        unread_new = [r for r in self.session.runs.values()
                      if not r.request['is_read'] and r.request['status']=='new']
        incoming = max(unread_new, key=lambda r:r.request['id']) if unread_new else None
        self.arrival_request_id = incoming.request['id'] if incoming else None
        if incoming:
            plan = incoming.state.plans['performance']
            self.arrival_notice.configure(text=f'{incoming.mission["company_name"]} · 새 요청\n'
                                          f'필요 GPU {plan["gpu"]} · 가용 GPU {self.session.servers.available()[0]}', fg=CYAN)
        else:
            self.arrival_notice.configure(text='새 요청은 시간 진행 중 자동 도착합니다.', fg=MUTED)
        self.arrival_open_button.configure(state='normal' if incoming else 'disabled')
        pending = self.session.pending_request_count
        limit_note = ' · 접수 보류' if pending >= MAX_PENDING_REQUESTS else ''
        self.arrival_schedule.configure(text=f'다음 {self.session.next_arrival_label} · '
                                       f'{pending}/{MAX_PENDING_REQUESTS}'+(' 보류' if limit_note else ''))
        faults = [r for r in active if r.state.phase in ('incident','paused')]
        self.alert.configure(text='! ' + ' · '.join(r.mission['country'] for r in faults)+' 장애 / 중단 · 대응을 선택하세요' if faults else '정상 작업은 시간 진행 버튼으로 함께 처리됩니다.')
        hardware = [key for key,value in self.session.servers.hardware.items() if value.state != 'HEALTHY']
        if hardware:
            self.alert.configure(text='장비 사용 불가: '+', '.join(hardware)+' · 랙 선택 → 복구 / 고객 선택 → 작업 이전')
        self.network.redraw()
        self.overview.refresh()

    def preview_plan(self, show_preview=False):
        self.resources.refresh(self.plan_var.get())
        if show_preview:
            self.resources.show_preview()
        plan = self.state.plans[self.plan_var.get()]
        available_gpu, available_power = self.session.servers.available()
        available_gpu = min(available_gpu, self.center.available_gpu())
        available_power = min(available_power, self.center.available_power())
        fits = plan['gpu'] <= available_gpu and plan['power'] <= available_power
        editable = self.state.phase in ('ready','accepted') or (self.state.phase == 'finished' and not self.state.succeeded)
        for key, button in self.mode_buttons.items():
            p = self.state.plans[key]
            status = self.session.mode_status(self.session.current, key)
            if editable and (p['gpu'] > available_gpu or p['power'] > available_power):
                status += ' · 자원 부족'
            button.configure(text=f'{p["label"]} — {status}', state='normal' if editable else 'disabled')
        for key in ('start','retry'):
            if key in self.action_buttons:
                allowed = fits and self.session.allocation_preview(self.session.current, self.plan_var.get())['allowed'] and (key != 'retry' or self.state.retry_count < 2)
                self.action_buttons[key].configure(state='normal' if allowed else 'disabled')

    def render_actions(self):
        for widget in self.action_frame.winfo_children():
            widget.destroy()
        for column in range(6):
            self.action_frame.columnconfigure(column, weight=0)
        s, r = self.state, self.session.current.request
        name, color = request_status_of(self.session.current)
        if self.session.hardware_status(self.session.current):
            name += ' · '+self.session.hardware_status(self.session.current)
            color = RED if self.session.hardware_servers(self.session.current) else AMBER
        self.detail_title.configure(text=f'요청 #{r["id"]} · {self.mission["company_name"]} / {self.mission["country"]} · {name}', fg=color)
        eta = getattr(s, 'remaining_minutes', 0)
        self.action_hint.configure(text=f'{self.mission["title"]}  |  진행 {getattr(s,"progress",0):.0f}% · 예상 잔여 {eta}분 (장애·복구 지연 제외)')
        if s.phase in ('ready','accepted'):
            self.action_hint.configure(text='아직 자원이 배정되지 않았습니다. 모드를 확인한 뒤 [배정하고 작업 시작]을 선택하세요.')
            if self.session.current.proposals:
                proposal = self.session.current.proposals[-1]
                status = {'pending':'고객 답변 대기 · 시작 전 답변 확인', 'accepted':'고객 동의 · 절약형으로 시작 가능',
                          'rejected':'고객 거절 · 기존 고성능 조건 유지'}[proposal['status']]
                self.action_hint.configure(text=f'절약형 대안: {status}. 자원은 작업 시작 시 다시 확인합니다.')
        elif s.phase == 'running' and s.progress == 0:
            self.action_hint.configure(text='자원 배정 완료 · 진행 0% · +10/+30/+60분을 누르면 모든 정상 작업이 함께 진행됩니다.')
        elif s.phase in ('incident','paused'):
            self.action_hint.configure(text=f'필요 네트워크 {s.network_needed} / 가용 {s.network_available} · 중단 {s.downtime}/60분 · 대응 {s.response_attempts}/3회 · 자원 점유 유지')
        elif s.phase == 'recovering':
            self.action_hint.configure(text=f'복구·재처리 준비 {s.recovery_left}분 · 진행 {s.progress:.0f}% · 준비 후 정상 실행을 재개합니다.')
        elif s.phase == 'finished':
            self.action_hint.configure(text=s.result_text if s.succeeded else f'{s.result_text} 재처리 {s.retry_count}/2회 · 새 배정과 20분 준비가 필요합니다.')
        delay_reason = self.session.delay_reason(self.session.current)
        if delay_reason:
            self.action_hint.configure(text=delay_reason)
        else:
            self.action_hint.configure(text=self.action_hint.cget('text')+'\n'+self.session.deadline_summary(self.session.current))
        options = []
        if r['status'] in ('new','review','waiting'):
            options = [('start','배정하고 작업 시작',lambda: self.choose_plan(self.plan_var.get())),
                       ('propose','대안 제시',self.propose_alternative),
                       ('wait','요청 대기',self.wait_request), ('reject','거절 · 사유',self.show_rejection)]
            if self.session.current.proposals and self.session.current.proposals[-1]['status'] in ('pending','accepted'):
                options[1] = ('propose','대안 · 고객 답변',lambda: self.open_message(self.session.selected_id))
            elif self.session.current.conditions and (self.session.current.proposals
                    or 'economy' in self.session.current.conditions['allowed_modes']):
                options = [option for option in options if option[0] != 'propose']
            if s.phase != 'accepted':
                options.insert(0, ('accept','수락만 · 배정 대기',lambda: self._perform(self.session.accept_request)))
        elif s.phase in ('incident','paused'):
            options = [(key, value['label'], lambda k=key: self.respond(k)) for key,value in RESPONSES.items()]
            options += [('delay','고객 지연 안내',lambda: self._perform(self.session.notify_delay)),
                        ('fail','처리 불가 보고',lambda: self._perform(self.session.report_failure))]
        elif s.phase in ('running','recovering'):
            options = [('delay','고객 지연 안내',lambda: self._perform(self.session.notify_delay))]
            if self.session.hardware_servers(self.session.current) or self.session.current.migration_left:
                options += [('fail','처리 불가 보고',lambda:self._perform(self.session.report_failure))]
        elif s.phase == 'finished' and not s.succeeded and not self.session.current.followup_closed:
            options = [('retry','선택 모드로 재처리',lambda: self._perform(lambda: self.session.retry(self.plan_var.get()))),
                       ('delay','고객 지연 안내',lambda: self._perform(self.session.notify_delay)),
                       ('report','처리 불가 · 최종 보고',lambda: self._perform(self.session.report_failure))]
        else:
            options = [('restart','같은 고객의 새 요청',self.new_mission)]
        if not self.session.can_notify_delay(self.session.current):
            options = [option for option in options if option[0] != 'delay']
        if self.session.hardware_servers(self.session.current) and not self.session.current.migration_left:
            options.insert(0, ('migrate','작업 이전 계획',self.open_migration_plans))
        if options:
            self.action_frame.grid()
        else:
            self.action_frame.grid_remove()
        self.action_buttons = {}
        for index,(key,text,command) in enumerate(options):
            b = ActionButton(self.action_frame, text, command, accent=AMBER if key in ('fail','report','reject') else CYAN)
            b.grid(row=0, column=index, sticky='ew', padx=(0, 6))
            self.action_frame.columnconfigure(index, weight=1, uniform='actions')
            self.action_buttons[key] = b

    def _perform(self, action):
        try:
            action()
        except Exception as exc:
            messagebox.showerror('처리 오류', str(exc), parent=self.root)
            return False
        self.refresh()
        return True
    def select_request(self, rid):
        success = self._perform(lambda: self.session.select(rid))
        if success and hasattr(self, 'resources') and not self.state.allocated:
            self.resources.show_preview()
        return success
    def choose_plan(self, key):
        return self._perform(lambda: self.session.choose_plan(key))
    def open_allocation_plans(self):
        if self.allocation_window is not None and self.allocation_window.winfo_exists():
            self.allocation_window.lift()
            return self.allocation_window
        self.allocation_window = AllocationDialog(
            self.root, self.session, self.plan_var.get(),
            lambda mode, parts: self._perform(lambda: self.session.choose_plan(mode, server_plan=parts)))
        return self.allocation_window
    def open_migration_plans(self):
        if self.allocation_window is not None and self.allocation_window.winfo_exists():
            self.allocation_window.lift()
            return self.allocation_window
        self.allocation_window = AllocationDialog(
            self.root, self.session, self.state.plan,
            lambda mode, parts:self._perform(lambda:self.session.migrate(parts, self.allocation_window.source)),
            migration=True)
        return self.allocation_window
    def propose_alternative(self):
        if self._perform(self.session.propose_alternative):
            return self.open_message(self.session.selected_id)
    def review_alternative(self, rid, proposal_count):
        if self.session.selected_id != rid or len(self.session.current.proposals) != proposal_count:
            messagebox.showerror('고객 협의 오류', '대안을 제시한 요청을 다시 선택해 고객 답변을 확인해 주세요.', parent=self.root)
            return
        if self._perform(self.session.review_alternative):
            if self.session.current.proposals[-1]['status'] == 'accepted':
                self.plan_var.set('economy')
            else:
                self.plan_var.set('performance')
            return self.open_message(rid)
    def respond(self, key):
        return self._perform(lambda: self.session.respond(key))
    def next_request(self):
        return self._perform(self.session.deliver_next_request)
    def open_arrival_message(self):
        if self.arrival_request_id is not None:
            return self.open_message(self.arrival_request_id)
    def wait_request(self):
        return self._perform(self.session.wait_request)
    def new_mission(self):
        return self._perform(self.session.restart)
    def advance_time(self, minutes):
        return self._perform(lambda: self.session.advance_time(minutes))
    def on_inbox_click(self, event):
        rid = self.inbox.identify_row(event.y)
        if rid:
            self.open_message(int(rid))
    def on_active_click(self, event):
        rid = self.active_list.identify_row(event.y)
        if rid:
            self.select_request(int(rid))
    def open_latest_message(self):
        rid = next((rid for rid,r in self.session.runs.items() if not r.request['is_read']), self.session.selected_id)
        return self.open_message(rid)
    def open_selected_message(self):
        selected = self.inbox.selection()
        return self.open_message(int(selected[0]) if selected else self.session.selected_id)
    def open_message(self, rid):
        was_unread = not self.session.runs[rid].request['is_read']
        try:
            steps = self.session.read_conversation(rid)
        except Exception as exc:
            messagebox.showerror('메시지 확인 오류', str(exc), parent=self.root)
            return
        self.refresh()
        if self.message_window is not None and self.message_window.winfo_exists():
            self.message_window.destroy()
        run = self.session.current
        if not run.state.allocated:
            self.resources.show_preview()
        confirm = None
        if (run.proposals and run.proposals[-1]['status'] == 'pending'
                and run.request['status'] in ('new','review','waiting')):
            confirm = ('고객 답변 확인', lambda count=len(run.proposals): self.review_alternative(rid, count))
        self.message_window = MessageDialog(self.root, run.mission['company_name'], run.mission['country'], steps,
                                            message_kind='새 메시지' if was_unread else '확인한 메시지 · 현재 상태',
                                            confirm=confirm)
        return self.message_window
    def show_conversation_history(self):
        steps = self.session.conversation(self.session.selected_id, history=True)
        return TextDialog(self.root, 'AIDC LINK · 과거 대화 기록', '\n\n'.join(f'{s}\n{t}' for s,t in steps))
    def show_rejection(self):
        rid = self.session.selected_id
        return RejectionDialog(self.root, lambda reason: self._perform(lambda: self.session.reject_request(reason))
                               if self.session.selected_id == rid else False)
    def show_events(self):
        text = '\n\n'.join(self.session.current.messages) or '아직 이벤트가 없습니다.'
        return TextDialog(self.root, '작업 이벤트 / 고객 피드백', text)
    def show_history(self):
        win = tk.Toplevel(self.root, bg=BG)
        win.title('전체 수행 기록 · 더블클릭으로 상세 로그')
        win.geometry('950x420')
        self.history = self.make_list(win, ('id','client','plan','status','score'),
                                      ('수행 ID','고객','모드','결과','점수'), (70,220,140,140,80), 10)
        self.history.pack(fill='both', expand=True, padx=10, pady=10)
        for row in self.session.recent_records():
            active_ids = {r.playthrough_id for r in self.session.runs.values() if r.state.allocated}
            status = '이전 실행 미완료' if row['status']=='진행중' and row['id'] not in active_ids else row['status']
            self.history.insert('', 'end', iid=str(row['id']), values=(row['id'],row['company_name'],row['plan'],status,row['score']))
        for rid,run in self.session.runs.items():
            if run.terms.get('expired'):
                self.history.insert('', 'end', iid=f'request-{rid}',
                                    values=(f'요청 {rid}', run.mission['company_name'], '미배정', '미처리 · 기한 만료', 0))
        self.history.bind('<Double-1>', self.show_record)
        return win
    def show_record(self, _=None):
        selected = self.history.selection()
        if selected:
            if selected[0].startswith('request-'):
                rid = int(selected[0].split('-')[1])
                return TextDialog(self.root, f'미처리 요청 #{rid}', '\n\n'.join(self.session.runs[rid].messages))
            return TextDialog(self.root, f'수행 기록 #{selected[0]}', '\n\n'.join(
                f'{r["created_at"]}\n{r["message"]}' for r in self.session.logs(int(selected[0]))))
    def on_close(self):
        try:
            self.session.close()
        except Exception as exc:
            messagebox.showerror('저장 오류', f'현재 상태를 저장하지 못해 종료하지 않았습니다.\n{exc}', parent=self.root)
            return
        self.network.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    SimulatorApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
