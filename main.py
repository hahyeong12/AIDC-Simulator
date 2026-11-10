"""AIDC Simulator: 첫 출근부터 Chapter 2, 모드 전환과 결과 보고까지."""
import tkinter as tk
from tkinter import ttk, messagebox

from database import Database, DB_PATH, STORY_DB_PATH
from session import GameSession, MAX_PENDING_REQUESTS
from game import RESPONSES, game_time
from server_console import LiveOverview, LiveServerRoom, ServerPanel, server_views
from allocation_dialog import AllocationDialog
from server_widgets import gpu_module, reset_hardware
from story import GUIDES, STEPS, Dialogue, chapter2_failure_pages
from chapter_dialog import ChapterCompleteDialog, Chapter2CompleteDialog, Chapter3CompleteDialog
from network_dialog import NetworkDiagnosisDialog, HardwareDiagnosisDialog, Chapter3FeedbackDialog
from story_dialog import StoryDialogueDialog, StoryReviewDialog
from story_slots import StorySlots
from tutorial_highlight import TutorialHighlight
from result_summary import free_result_lines
from version import VERSION
from story_feedback import StoryFeedbackDialog, FEEDBACK
from request_summary import request_summary
from ui import (BG, PANEL, BORDER, TEXT, MUTED, CYAN, GREEN, RED, AMBER, FONT,
                ActionButton, RejectionDialog, MessageDialog,
                TextDialog, label, request_status_of, status_of)


class SimulatorApp:
    def __init__(self, root, db=None, db_factory=Database, story_slots=None, **session_options):
        self.root = root
        self.db_factory, self.closed, self.transitioning = db_factory, False, False
        root.title(f'AIDC Simulator {VERSION} | 울산 AI 데이터센터 관제실')
        root.geometry(f'{min(1280, root.winfo_screenwidth()-40)}x{min(680, root.winfo_screenheight()-100)}')
        root.minsize(1000, 650)
        root.configure(bg=BG)
        self.db = db if db is not None else Database(STORY_DB_PATH if session_options.get('mode') == 'story' else DB_PATH)
        self.story_slots = story_slots or StorySlots(self.db.path.parent if self.db.path else None)
        before = set(root.winfo_children())
        claimed = False
        try:
            self.db.claim_game()
            claimed = True
            self.session = GameSession(self.db, **session_options)
            self.center = self.session.center
            self.message_window = None
            self.allocation_window = None
            self.story_window = None
            self.chapter_window = None
            self.story_event_timer = None
            self.story_reviews = set()
            self.feedback_window = None
            self.diagnosis_window = None
            self.pending_feedback = None
            self.feedback_events = set()
            self.story_ui_busy = False
            self.tutorial_highlight = TutorialHighlight(root)
            self.story_destroy_binding = root.bind('<Destroy>', self.cancel_story_event, add='+')
            self.setup_ui()
            if self.session.story:
                self.resources.book.select(self.resources.inspector_frame)
            self.refresh()
            self.network.start()
            root.protocol('WM_DELETE_WINDOW', self.on_close)
            if self.session.story:
                if self.session.story.ui_done:
                    self.show_chapter_complete()
                else:
                    self.show_story_event()
        except Exception:
            if claimed:
                self.closed = True
                if hasattr(self, 'network'):
                    self.network.stop()
                if hasattr(self, 'tutorial_highlight'):
                    self.tutorial_highlight.stop()
                if hasattr(self, 'story_destroy_binding'):
                    self.cancel_story_event()
                    root.unbind('<Destroy>', self.story_destroy_binding)
                for widget in set(root.winfo_children()) - before:
                    widget.destroy()
                self.db.release_game()
            if db is None:
                self.db.close()
            raise

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
        mode_label = '스토리 모드' if self.session.story else '자유 운영 모드'
        label(header, f'ULSAN / {VERSION} · {mode_label}', 10, bold=True).pack(side='left', padx=12)
        self.notice_var = tk.StringVar()
        self.notice_button = ActionButton(header, 'AIDC LINK', self.open_latest_message)
        self.notice_button.pack(side='right')
        self.mode_select_button = ActionButton(header, '모드 선택', self.return_to_modes)
        self.mode_select_button.pack(side='right', padx=(0, 8))
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
        left.rowconfigure(1, weight=2, minsize=58 if self.session.story else 55)
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
        self.network = self.server_room = LiveServerRoom(middle, self.session, self.select_server)
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
        label(modes, '배정 설정 · 운영 모드', 10, MUTED).pack(side='left', padx=(0, 10))
        self.allocation_choice = None
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
        # 모드 오른쪽: 현재 선택한 모드와 배정안 설정 여부(실제 선택은 [배정 설정·선택] 창에서 합니다).
        self.allocation_status = label(modes, '', 9, CYAN, anchor='w')
        self.allocation_status.pack(side='left', padx=(8, 0))
        self.action_frame = tk.Frame(controls, bg=PANEL)
        self.action_frame.grid(row=3, sticky='ew')
        tools = tk.Frame(self.root, bg=BG, padx=12)
        tools.grid(row=4, sticky='ew', pady=(0, 5))
        label(tools, '가상 시간 진행', 10, CYAN, True).pack(side='left', padx=(0, 10))
        self.time_buttons = {}
        # 교육에서는 세 시간 버튼을 하나의 대상으로 묶어 강조합니다.
        self.time_group = tk.Frame(tools, bg=BG, highlightthickness=0)
        self.time_group.pack(side='left')
        for minutes in (10, 30, 60):
            b = ActionButton(self.time_group, f'+{minutes}분', lambda m=minutes: self.advance_time(m))
            b.pack(side='left', padx=(0, 6))
            self.time_buttons[minutes] = b
        ActionButton(tools, '대화 기록', self.show_conversation_history).pack(side='right', padx=(6, 0))
        ActionButton(tools, '수행 기록', self.show_history).pack(side='right', padx=6)
        ActionButton(tools, '이벤트 / 로그', self.show_events).pack(side='right', padx=6)
        if self.session.story:
            self.story_bar = tk.Frame(self.root, bg=PANEL, padx=12, pady=5)
            self.story_bar.grid(row=5, sticky='ew', padx=12, pady=(0, 5))
            self.story_bar.columnconfigure(0, weight=1)
            self.story_objective = label(self.story_bar, size=9, color=CYAN, anchor='w', justify='left')
            self.story_objective.grid(row=0, column=0, sticky='ew')
            self.story_objective.bind('<Configure>', lambda e:self.story_objective.configure(wraplength=max(300, e.width-4)))
            self.story_help_button = ActionButton(self.story_bar, '교육 도움말', self.show_story_help)
            self.story_help_button.grid(row=0, column=1, padx=6)
            self.story_skip_button = ActionButton(self.story_bar, '튜토리얼 건너뛰기', self.skip_tutorial, accent=AMBER)
            self.story_skip_button.grid(row=0, column=2)
            self.story_complete_button = ActionButton(self.story_bar, 'Chapter 1 완료', self.show_chapter_complete)
            self.story_retry_button = ActionButton(self.story_bar, '이번 시도 종료 · 재도전', self.confirm_retry_chapter2, accent=AMBER)
            self.story_retry3_button = ActionButton(self.story_bar, 'Chapter 3 다시 도전', self.confirm_retry_chapter3, accent=AMBER)
            self.story_retry3b_button = ActionButton(self.story_bar, 'Chapter 3b 다시 도전', self.confirm_retry_chapter3b, accent=AMBER)
            self.resources.book.bind('<<NotebookTabChanged>>', self.on_story_preview, add='+')
            self.resource_confirm_button = tk.Button(
                self.resources.inspector_frame, text='GPU·전력 정보 확인', bg=PANEL, fg=CYAN,
                font=(FONT, 9), command=self.confirm_story_resources, relief='flat')
            self.resource_confirm_button.pack(fill='x', before=self.resources.fault_button.master)

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
        if self.session.story:
            story = self.session.story
            self.story_objective.configure(text=f'{story.chapter_label} · ACTION · 현재 목표: {self.session.story_objective()}')
            self.story_skip_button.configure(state='disabled' if story.tutorial_completed else 'normal')
            self.resource_confirm_button.configure(state='normal' if story.step == 'resources' else 'disabled')
            if story.chapter3 is None and story.chapter3b is None and story.chapter2 is not None and self.session.chapter2_retry_available:
                self.story_retry_button.grid(row=0, column=3, padx=(6, 0))
            else:
                self.story_retry_button.grid_remove()
            if story.chapter3 is not None and story.chapter3b is None and self.session.chapter3_retry_available:
                self.story_retry3_button.grid(row=0, column=3, padx=(6, 0))
            else:
                self.story_retry3_button.grid_remove()
            if story.chapter3b is not None and self.session.chapter3b_retry_available:
                self.story_retry3b_button.grid(row=0, column=3, padx=(6, 0))
            else:
                self.story_retry3b_button.grid_remove()
            if story.chapter3b is not None:
                self.story_skip_button.grid_remove()
                if story.chapter3b.completed:
                    self.story_complete_button.configure(text='Chapter 3b 결과')
                    self.story_complete_button.grid(row=0, column=2)
                else:
                    self.story_complete_button.grid_remove()
            elif story.chapter3 is not None:
                # Chapter 3(독립 연습 포함)에는 Chapter 1 건너뛰기가 없습니다. 완료한 뒤에는 결과 창을 다시 열 수 있습니다.
                self.story_skip_button.grid_remove()
                if story.chapter3.completed:
                    self.story_complete_button.configure(text='Chapter 3 결과')
                    self.story_complete_button.grid(row=0, column=2)
                else:
                    self.story_complete_button.grid_remove()
            elif story.chapter2 is not None:
                # Chapter 2(연습 포함)에는 Chapter 1 건너뛰기가 없습니다. 완료한 뒤에는 결과 창을 다시 열 수 있습니다.
                self.story_skip_button.grid_remove()
                if story.chapter2.completed:
                    self.story_complete_button.configure(text='Chapter 2 결과')
                    self.story_complete_button.grid(row=0, column=2)
                else:
                    self.story_complete_button.grid_remove()
            elif story.chapter_completed:
                self.story_skip_button.grid_remove()
                self.story_complete_button.configure(text=f'{story.chapter_label} 완료')
                self.story_complete_button.grid(row=0, column=2)
            else:
                self.story_complete_button.grid_remove()
        self.update_tutorial_highlight()

    def update_tutorial_highlight(self):
        """현재 사실에서 대상을 재계산합니다. 대화/복습을 읽는 동안 관제실은 점멸하지 않습니다."""
        highlight = self.tutorial_highlight
        story = self.session.story
        if (story and not self.closed and not self.transitioning
                and self.story_objective.winfo_exists()):
            self.story_objective.configure(text=f'{story.chapter_label} · {self.story_phase} · 현재 목표: {self.session.story_objective()}')
        if (self.closed or self.transitioning or not story or story.tutorial_completed or story.chapter2 is not None
                or story.chapter3 is not None or story.chapter3b is not None or story.chapter_completed or story.mission_status == 'closed'
                or any(w is not None and w.winfo_exists()
                       for w in (self.story_window, self.feedback_window, self.message_window, *self.story_reviews))):
            highlight.clear()
            return
        step, widget, key = story.step, None, story.step
        plan_window = self.allocation_window
        if plan_window is not None and plan_window.winfo_exists():
            # 팝업이 열려 있으면 팝업 안의 위젯만 대상으로 합니다. 부모 화면 버튼은 강조하지 않습니다.
            if plan_window.migration:
                pass
            elif step == 'allocation' and plan_window.start_button.cget('state') != 'disabled':
                widget = plan_window.start_button
            elif step == 'allocation' and plan_window.plan_buttons:
                # 아직 계획을 확인하지 않았다면 먼저 계획 카드를 직접 선택하게 합니다.
                widget, key = plan_window.plan_buttons[0], 'plan'
            elif step == 'preview' and plan_window.plan_buttons:
                widget, key = plan_window.plan_buttons[0], 'plan'
        elif step == 'server':
            widget = self.network
        elif step == 'resources':
            if self.resources.book.select() == str(self.resources.inspector_frame):
                widget = self.resource_confirm_button
            else:
                widget, key = self.resources, 'inspector'
        elif step == 'request':
            widget = self.arrival_open_button if self.arrival_request_id == story.request_id else self.notice_button
        elif step == 'preview':
            # 탭은 이동 수단일 뿐입니다. 탭이 열려 있으면 실제 비교 버튼을 가리킵니다.
            if self.resources.book.select() == str(self.resources.review_frame):
                if self.resources.compare_button.cget('state') != 'disabled':
                    widget, key = self.resources.compare_button, 'compare'
            else:
                widget = self.resources
        elif step == 'allocation':
            allowed = self.session.allocation_preview(self.session.current, self.plan_var.get())['allowed']
            widget = self.action_buttons.get('start') if allowed else self.mode_buttons['performance']
        elif step in ('time', 'work_complete'):
            widget = self.time_group
        elif step == 'operations':
            widget = self.action_buttons.get('operations')
        highlight.show(key, widget)

    def tutorial_window_closed(self, event):
        if event.widget is self.story_window:
            pass  # 기존 호출부가 닫힌 대화창의 존재 여부도 조회할 수 있도록 참조를 유지합니다.
        elif event.widget in self.story_reviews:
            self.story_reviews.discard(event.widget)
        else:
            return
        self.update_tutorial_highlight()

    @property
    def story_phase(self):
        if self.feedback_window is not None and self.feedback_window.winfo_exists():
            return 'FEEDBACK'
        if any(w is not None and w.winfo_exists() for w in (self.story_window, self.chapter_window)):
            return 'STORY'
        return 'ACTION' if self.session.story else None

    def story_anchor(self, step):
        widget = {'server': self.network, 'resources': getattr(self, 'resource_confirm_button', self.resources),
                  'request': self.arrival_open_button, 'preview': self.resources,
                  'allocation': self.action_frame, 'time': self.time_group,
                  'work_complete': self.time_group, 'operations': self.action_frame,
                  'c2_requests': self.arrival_open_button, 'c2_review': self.resources,
                  'c2_allocate': self.action_frame, 'c2_progress': self.time_group,
                  'c2_finish': self.time_group, 'c3_a_start': self.arrival_open_button, 'c3_b_start': self.arrival_open_button,
                  'c3_a_incident': self.time_group, 'c3_b_incident': self.time_group,
                  'c3_a_finish': self.time_group, 'c3_b_finish': self.time_group}.get(step, self.controls)
        if step == 'server' and 'A' in self.network.rack_bounds:
            x, y, right, bottom = self.network.rack_bounds['A']
            return self.network.winfo_rootx()+int(x), self.network.winfo_rooty()+int(y), int(right-x), int(bottom-y)
        return widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height()

    def queue_story_feedback(self, previous, anchor):
        story = self.session.story
        if (not story or previous not in FEEDBACK or story.skipped or story.ui_done
                or story.mission_status == 'closed' or previous not in story.ui_completed_steps):
            return
        # 완료 단계는 단조 증가합니다. 실행 중 실제 전환에서만 생성하므로 재실행 시 성공을 재생하지 않습니다.
        token = (previous, story.ui_step)
        if token not in self.feedback_events:
            self.pending_feedback = (token, previous, anchor)

    def build_popup(self, factory, *args, **kwargs):
        # 중앙/인접 배치의 update_idletasks 중 종료 예약이 재진입하지 않게 합니다.
        previous = self.story_ui_busy
        before = set(self.root.winfo_children())
        self.story_ui_busy = True
        try:
            return factory(*args, **kwargs)
        except Exception:
            for widget in set(self.root.winfo_children())-before:
                if isinstance(widget, tk.Toplevel):
                    widget.destroy()
            raise
        finally:
            self.story_ui_busy = previous

    def feedback_closed(self, event):
        if event.widget is not self.feedback_window or self.closed or self.transitioning:
            return
        self.cancel_story_event()
        self.story_event_timer = self.root.after_idle(self.resume_story_event)

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
                status = ('서버 장애' if self.session.hardware_servers(run) else '이전 준비' if run.migration_left else
                          f'복구 준비 {run.state.recovery_left}분' if run.state.incident_kind and run.state.recovered_by and run.state.phase == 'recovering'
                          else status_of(run.state)[0])
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
        if self.session.story:
            self.arrival_schedule.configure(text=f'{self.session.story.chapter_label} · 미션에 따라 요청 접수')
            story = self.session.story
            if story.step == 'request' and not story.request_read and not story.tutorial_completed:
                target = self.session.runs[story.request_id]
                self.arrival_request_id = story.request_id
                self.arrival_notice.configure(text=f'{target.mission["company_name"]} · 고객 조건 확인\n요청 모드·자원·완료 기한을 읽어 주세요.', fg=CYAN)
                self.arrival_open_button.configure(state='normal')
            if not incoming:
                if self.arrival_request_id is None:
                    self.arrival_notice.configure(text=f'{story.chapter_label} · 고객 업무', fg=MUTED)
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
        self.update_allocation_status()
        for key in ('start','retry'):
            if key in self.action_buttons:
                # 시작할 수 없는 모드(자원 부족·고객 동의 없음)는 설정 버튼도 비활성화합니다. 이유는 모드 표시와 Inspector의
                # [배정 계획 비교·선택]으로 열리는 설정창에서 확인할 수 있습니다.
                allowed = fits and self.session.allocation_preview(self.session.current, self.plan_var.get())['allowed'] and (key != 'retry' or self.state.retry_count < 2)
                self.action_buttons[key].configure(state='normal' if allowed else 'disabled')
        self.update_tutorial_highlight()

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
            self.action_hint.configure(text='아직 자원이 배정되지 않았습니다. [배정 설정·선택]에서 운영 모드와 서버 배정안을 확인한 뒤 작업을 시작하세요.')
            if self.session.current.proposals:
                proposal = self.session.current.proposals[-1]
                status = {'pending':'고객 답변 대기 · 시작 전 답변 확인', 'accepted':'고객 동의 · 절약형으로 시작 가능',
                          'rejected':'고객 거절 · 기존 고성능 조건 유지'}[proposal['status']]
                self.action_hint.configure(text=f'절약형 대안: {status}. 자원은 작업 시작 시 다시 확인합니다.')
        elif s.phase == 'running' and s.progress == 0:
            self.action_hint.configure(text='자원 배정 완료 · 진행 0% · +10/+30/+60분을 누르면 모든 정상 작업이 함께 진행됩니다.')
        elif s.phase in ('incident','paused'):
            self.action_hint.configure(text=f'필요 네트워크 {s.network_needed} / 가용 {s.network_available} · 중단 {s.downtime}/60분 · 대응 {s.response_attempts}/3회 · 자원 점유 유지')
            if s.incident_kind:
                # Chapter 3: 원인은 알려 주지 않고 장비가 정상이라는 사실과 확인 방법만 안내합니다.
                self.action_hint.configure(text='GPU·서버 장비 정상 · 네트워크 문제로 작업 중단 · [네트워크 진단]에서 원인을 확인한 뒤 대응하세요.\n'
                                           f'필요 네트워크 {s.network_needed} / 가용 {s.network_available} · 중단 {s.downtime}/60분 · 대응 {s.response_attempts}/3회'
                                           + (f'\n{s.result_text}' if s.phase == 'paused' and s.response_attempts else ''))
        elif s.phase == 'recovering':
            self.action_hint.configure(text=f'복구·재처리 준비 {s.recovery_left}분 · 진행 {s.progress:.0f}% · 준비 후 정상 실행을 재개합니다.')
        elif s.phase == 'finished':
            self.action_hint.configure(text=s.result_text if s.succeeded else f'{s.result_text} 재처리 {s.retry_count}/2회 · 새 배정과 20분 준비가 필요합니다.')
        delay_reason = self.session.delay_reason(self.session.current)
        recovery = self.session.recovery_status_lines(self.session.current)
        if recovery:
            # 장애 해결 뒤: 복구 준비 중 / 정상 실행 중 상태를 간략히 표시(지연 위험이 실제로 있을 때만 그 내용을 덧붙임)
            self.action_hint.configure(text='\n'.join(recovery)+('\n'+delay_reason if delay_reason else '')
                                       +'\n'+self.session.deadline_summary(self.session.current))
        elif delay_reason:
            self.action_hint.configure(text=delay_reason)
        else:
            self.action_hint.configure(text=self.action_hint.cget('text')+'\n'+self.session.deadline_summary(self.session.current))
        if self.session.mode == 'free':
            # v0.9-2b: 팝업 없이 운영 패널에 실제 결과 요약을 덧붙입니다. 끝나지 않은 요청에는 표시하지 않습니다.
            summary = free_result_lines(self.session.current)
            if summary:
                self.action_hint.configure(text=self.action_hint.cget('text')+'\n── 결과 요약 ──\n'+'\n'.join(summary))
        options = []
        if r['status'] in ('new','review','waiting'):
            options = [('start','배정 설정·선택',self.open_allocation_plans),
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
            if s.incident_kind and self.session.story and self.session.story.chapter3 is not None:
                options.insert(0, ('diagnose','네트워크 진단',self.open_network_diagnosis))
        elif s.phase in ('running','recovering'):
            options = [('delay','고객 지연 안내',lambda: self._perform(self.session.notify_delay))]
            if self.session.hardware_servers(self.session.current) or self.session.current.migration_left:
                options += [('fail','처리 불가 보고',lambda:self._perform(self.session.report_failure))]
            if self.session.story and self.session.story.chapter3b is not None:
                if self.session.hardware_servers(self.session.current):
                    # 장비 장애: 먼저 진단(이전 가능 여부 조회) → 복구 또는 이전 중 직접 선택
                    options.insert(0, ('hwrepair','장비 복구 · 20분',self.repair_faulted_server))
                    options.insert(0, ('hwdiag','장비 진단',self.open_hardware_diagnosis))
                if self.session.chapter3b_card(self.session.selected_id) is not None:
                    options.append(('result3b','장애 결과 보기',lambda rid=self.session.selected_id: self.open_chapter3b_card(rid)))
        elif s.phase == 'finished' and not s.succeeded and not self.session.current.followup_closed:
            options = [('retry','선택 모드로 재처리',lambda: self._perform(lambda: self.session.retry(self.plan_var.get()))),
                       ('delay','고객 지연 안내',lambda: self._perform(self.session.notify_delay)),
                       ('report','처리 불가 · 최종 보고',lambda: self._perform(self.session.report_failure))]
            if self.session.chapter3_card(self.session.selected_id) is not None:
                options.insert(0, ('result3', '장애 결과 보기', lambda rid=self.session.selected_id: self.open_chapter3_card(rid)))
            if self.session.story and self.session.story.chapter3b is not None and self.session.chapter3b_card(self.session.selected_id) is not None:
                options.insert(0, ('result3b', '장애 결과 보기', lambda rid=self.session.selected_id: self.open_chapter3b_card(rid)))
        else:
            options = [('restart','같은 고객의 새 요청',self.new_mission)]
        if self.session.story:
            options = [option for option in options if option[0] != 'restart']
            if self.session.story.step == 'operations' and not self.session.story.tutorial_completed:
                options.append(('operations', '운영 상태 확인', self.show_story_help))
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
            if key in RESPONSES and self.session.chapter3_response_locked(self.session.current):
                b.configure(state='disabled')  # 진단창을 열기 전에는 대응을 선택할 수 없습니다.
            if key in ('hwrepair', 'migrate') and self.session.chapter3b_locked(self.session.current):
                b.configure(state='disabled')  # 장비 진단을 열기 전에는 복구/이전을 선택할 수 없습니다.
            if key == 'hwrepair' and not any(self.session.servers.hardware[k].state == 'FAULT'
                                             for k in self.session.hardware_servers(self.session.current)):
                b.configure(state='disabled')  # 이미 복구 중

    def _perform(self, action):
        story = self.session.story
        previous = (story.ui_step, story.tutorial_completed, story.ui_done) if story else None
        anchor = self.story_anchor(story.ui_step) if story else None
        try:
            action()
        except Exception as exc:
            messagebox.showerror('처리 오류', str(exc), parent=self.root)
            return False
        self.refresh()
        if story:
            current = self.session.story
            if current.ui_step != previous[0]:
                if self.story_window is not None and self.story_window.winfo_exists():
                    self.story_window.destroy()
                self.queue_story_feedback(previous[0], anchor)
            if current.ui_done and not previous[2]:
                self.show_chapter_complete()
            else:
                self.show_story_event()
        return True

    def select_server(self, key):
        previous = self.resources.selected
        self.resources.select_server(key)
        if self.session.story:
            if not self._perform(lambda:self.session.select_story_server(key)):
                self.resources.select_server(previous)
                self.network.selected = previous
                self.network.redraw()

    def show_story_event(self):
        """실제 세션 작업 뒤에만 호출합니다. refresh/타이머는 대화를 만들지 않습니다."""
        story = self.session.story
        if not story or self.closed or self.transitioning or self.story_ui_busy or story.ui_done:
            return None
        # 고객 요청/계획을 읽는 중에는 해당 창을 닫은 뒤 사건 대화를 보여 줍니다.
        for window in (self.message_window, self.allocation_window):
            if window is not None and window.winfo_exists():
                return None
        if self.story_window is not None and self.story_window.winfo_exists():
            return self.story_window
        if self.session.chapter2_failure_pending:
            return self.show_chapter2_failure()
        if story.chapter3b is not None and self.session.chapter3b_pending_feedback() is not None:
            return self.show_chapter3b_feedback()
        if story.chapter3b is None and story.chapter3 is not None and self.session.chapter3_pending_feedback() is not None:
            return self.show_chapter3_feedback()
        if self.pending_feedback is not None:
            token, completed, anchor = self.pending_feedback
            self.pending_feedback = None
            if self.feedback_window is not None and self.feedback_window.winfo_exists():
                self.feedback_window.destroy()
            self.tutorial_highlight.clear()
            try:
                self.feedback_window = self.build_popup(StoryFeedbackDialog, self.root, completed, story.objective, anchor,
                                                        avoid=(self.story_anchor(story.ui_step),))
            except Exception as exc:
                self.pending_feedback = (token, completed, anchor)
                messagebox.showerror('피드백 표시 오류', str(exc), parent=self.root)
                self.update_tutorial_highlight()
                return None
            try:
                if story.step != 'request':
                    self.session.mark_story_dialogue(story.dialogue_event)
            except Exception as exc:
                self.feedback_window.destroy()
                self.pending_feedback = (token, completed, anchor)
                messagebox.showerror('피드백 저장 오류', str(exc), parent=self.root)
                self.update_tutorial_highlight()
                return None
            self.feedback_events.add(token)
            self.feedback_window.bind('<Destroy>', self.feedback_closed, add='+')
            self.update_tutorial_highlight()
            return self.feedback_window
        if self.feedback_window is not None and self.feedback_window.winfo_exists():
            return self.feedback_window
        if (story.dialogue_event in ('arrival', 'request', 'closed', 'skipped', 'c2_briefing', 'c3_briefing',
                                     'c3_a_diagnose', 'c3_b_start', 'c3_b_diagnose',
                                     'c3b_briefing', 'c3b_a_diagnose', 'c3b_b_start', 'c3b_b_diagnose')
                and story.dialogue_event not in story.dialogue_seen):
            return self.show_story_help()
        self.update_tutorial_highlight()
        return None

    def show_chapter2_failure(self):
        """Chapter 2 실패가 확정된 순간 선배가 원인과 다음 선택을 알려 줍니다. 같은 실패는 한 번만 표시합니다."""
        story = self.session.story
        if (not story or story.chapter2 is None or not self.session.chapter2_failure_pending
                or self.closed or self.transitioning):
            return None
        self.pending_feedback = None
        for window in (self.feedback_window, self.story_window):
            if window is not None and window.winfo_exists():
                window.destroy()
        self.tutorial_highlight.clear()
        pages = [line.page() for line in chapter2_failure_pages(story.chapter2.failure)]
        pages.insert(len(pages)-1, Dialogue('system', '현재 미션 평가\n'+'\n'.join(self.session.chapter2_evaluation_lines())).page())
        # 다른 고객의 작업이 진행 중이어도 바로 새 슬롯에서 다시 도전할 수 있습니다.
        self.story_window = self.build_popup(StoryDialogueDialog, self.root, pages,
                                             confirm=('Chapter 2 다시 도전', self.retry_chapter2), chapter_label='Chapter 2')
        self.story_window.close_button.configure(text='기존 진행 계속 보기')
        self.story_window.bind('<Destroy>', self.tutorial_window_closed, add='+')
        try:
            self.session.mark_chapter2_failure_seen()
        except Exception as exc:
            self.story_window.destroy()
            messagebox.showerror('실패 안내 저장 오류', str(exc), parent=self.root)
            return None
        self.update_tutorial_highlight()
        return self.story_window

    def chapter3_card_actions(self, card):
        """카드의 다음 행동 버튼. 시간 진행은 기존 advance_time(10분)을 그대로 사용합니다."""
        actions = []
        if card['can_advance']:
            actions.append(('업무로 돌아가기', self.close_feedback))
            actions.append(('복구 준비 10분 진행', lambda: (self.close_feedback(), self.advance_time(10))))
        elif card['can_retry']:
            actions.append(('Chapter 3 다시 도전', lambda: (self.close_feedback(), self.confirm_retry_chapter3())))
            actions.append(('후속 처리로 돌아가기', self.close_feedback))
        else:
            actions.append(('업무로 돌아가기', self.close_feedback))
        return actions

    def close_feedback(self):
        if self.feedback_window is not None and self.feedback_window.winfo_exists():
            self.feedback_window.destroy()

    def open_chapter3_card(self, rid):
        """장애 결과 카드를 엽니다(조회 전용). 확인 기록은 남기지 않으므로 닫았다가 다시 열 수 있습니다."""
        card = self.session.chapter3_card(rid)
        if card is None or self.closed or self.transitioning:
            return None
        for window in (self.feedback_window, self.story_window):
            if window is not None and window.winfo_exists():
                window.destroy()
        self.tutorial_highlight.clear()
        self.feedback_window = self.build_popup(Chapter3FeedbackDialog, self.root, card, self.chapter3_card_actions(card))
        self.feedback_window.bind('<Destroy>', self.feedback_closed, add='+')
        return self.feedback_window

    def show_chapter3_feedback(self):
        """실제 대응/결과가 기록된 뒤에만 짧은 결과 카드를 보여 줍니다. 같은 사건은 한 번만 표시합니다."""
        story = self.session.story
        pending = self.session.chapter3_pending_feedback() if story and story.chapter3 is not None else None
        if pending is None or self.closed or self.transitioning:
            return None
        key = pending[0]
        self.pending_feedback = None
        window = self.open_chapter3_card(int(key.split(':')[0]))
        if window is None:
            return None
        try:
            self.session.mark_chapter3_feedback_seen(key)
        except Exception as exc:
            window.destroy()
            messagebox.showerror('피드백 저장 오류', str(exc), parent=self.root)
            return None
        self.update_tutorial_highlight()
        return window

    def story_work_window_closed(self, event):
        if self.closed or self.transitioning:
            return
        if event.widget is self.message_window:
            self.message_window = None
        elif event.widget is self.allocation_window:
            self.allocation_window = None
        else:
            return
        self.cancel_story_event()
        self.story_event_timer = self.root.after_idle(self.resume_story_event)

    def resume_story_event(self):
        self.story_event_timer = None
        if not self.closed and not self.transitioning:
            self.show_story_event()
            self.update_tutorial_highlight()

    def cancel_story_event(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        if event is not None:
            self.tutorial_highlight.stop()
        if self.story_event_timer is not None:
            self.root.after_cancel(self.story_event_timer)
            self.story_event_timer = None

    def show_story_help(self):
        story = self.session.story
        if not story:
            return None
        if self.feedback_window is not None and self.feedback_window.winfo_exists():
            self.feedback_window.destroy()
        if self.story_window is not None and self.story_window.winfo_exists():
            self.story_window.destroy()
        self.tutorial_highlight.clear()
        confirms = {'arrival':('첫 업무 시작', lambda:self.confirm_story_step(self.session.confirm_story_arrival)),
                    'resources':('자원 정보 확인', self.confirm_story_resources),
                    'operations':('운영 상태 확인', lambda:self.confirm_story_step(self.session.confirm_story_operations)),
                    'c2_briefing':('브리핑 확인', lambda:self.confirm_story_step(self.session.confirm_chapter2_briefing)),
                    'c3_briefing':('브리핑 확인', lambda:self.confirm_story_step(self.session.confirm_chapter3_briefing)),
                    'c3b_briefing':('브리핑 확인', lambda:self.confirm_story_step(self.session.confirm_chapter3b_briefing))}
        confirm = confirms.get(story.ui_step) if not story.ui_done and not story.skipped else None
        pages = [line.page() for line in story.dialogue]
        if story.step == 'operations' and not story.chapter_completed:
            run = self.session.runs[story.request_id]
            remaining = '\n'.join(f'Server {v["spec"].key}: GPU {v["gpu_available"]} · 전력 {v["power_available"]}'
                                  for v in server_views(self.session))
            info = (f'예상 완료: {game_time(self.session.minute+run.state.remaining_minutes)}\n'
                    + self.session.deadline_summary(run) + '\n\n서버별 잔여 자원\n' + remaining)
            pages.append(Dialogue('system', info).page())
        if story.chapter2_active:
            # Chapter 2: 두 고객의 조건을 현재 엔진 값으로 나란히 보여 줍니다. 정답이나 권장 순서는 없습니다.
            comparison = self.session.chapter2_comparison_lines()
            if comparison:
                pages.append(Dialogue('system', '\n'.join(comparison)).page())
        self.story_window = self.build_popup(StoryDialogueDialog, self.root, pages, confirm=confirm,
                                             chapter_label=story.chapter_label)
        self.story_window.bind('<Destroy>', self.tutorial_window_closed, add='+')
        try:
            self.session.mark_story_dialogue(story.dialogue_event)
        except Exception as exc:
            self.story_window.destroy()
            messagebox.showerror('대화 저장 오류', str(exc), parent=self.root)
            return None
        self.update_tutorial_highlight()
        return self.story_window

    def confirm_story_step(self, action):
        if self._perform(action):
            return True
        return False

    def on_story_preview(self, _=None):
        if self.closed or self.transitioning:
            return
        story = self.session.story
        # 탭 이동은 검토가 아닙니다. 배정 검토는 비교 창에서 계획을 직접 고를 때만 확인합니다.
        self.update_tutorial_highlight()

    def show_story_review(self):
        self.tutorial_highlight.clear()
        window = StoryReviewDialog(self.root)
        self.story_reviews.add(window)
        window.bind('<Destroy>', self.tutorial_window_closed, add='+')
        return window

    def show_story_status(self):
        story = self.session.story
        if story.chapter3b is not None:
            state = '진행 중' if story.chapter3b_active else '완료'
            origin = ('Chapter 3a(네트워크 장애) 기록은 그대로 보존됩니다.' if story.chapter3 is not None
                      else '독립 연습 슬롯입니다. 이전 Chapter를 완료한 기록은 없습니다.')
            return TextDialog(self.root, '스토리 진행 현황',
                              f'Chapter 3b · 서버 장비 장애 · {state}\n장비 복구와 작업 이전을 자원·시간으로 비교해 선택합니다.\n{origin}')
        if story.chapter3 is not None:
            state = '진행 중' if story.chapter3_active else '완료'
            origin = ('Chapter 2 기록은 그대로 보존됩니다.' if story.chapter2 is not None
                      else '독립 연습 슬롯입니다. Chapter 1·2를 완료한 기록은 없습니다.')
            return TextDialog(self.root, '스토리 진행 현황',
                              f'Chapter 3 · 네트워크 장애 진단과 대응 · {state}\n두 번의 장애를 진단하고 원인에 맞는 대응을 선택합니다.\n{origin}')
        if story.chapter2 is not None:
            chapter2 = '진행 중' if story.chapter2_active else '완료'
            tail = f'\n\nChapter 2 · 여러 고객 요청과 서버 배정 · {chapter2}\n두 요청의 확인·비교·배정·진행·종료 단계로 진행합니다.'
        elif story.chapter_completed:
            tail = '\n\nChapter 2 · 시작 가능\nChapter 1 완료 화면의 [Chapter 2 시작]으로 시작할 수 있습니다. Chapter 3은 Chapter 2 성공 후 이어서 시작하거나 모드 선택에서 독립 연습으로 시작할 수 있습니다.'
        else:
            tail = '\n\nChapter 2 · Chapter 1 완료 후 시작 가능\nChapter 3은 Chapter 2 성공 후 또는 독립 연습으로 시작할 수 있습니다.'
        text = ('Chapter 1 · '+('완료' if story.chapter_completed else '진행 중')
                + '\n튜토리얼 안내: '+('완료' if story.tutorial_completed else '진행 중')
                + '\n첫 고객 업무: '+('정상 완료' if story.first_work_completed else '미완료')
                + tail)
        return TextDialog(self.root, '스토리 진행 현황', text)

    def show_chapter_complete(self):
        self.pending_feedback = None
        if self.feedback_window is not None and self.feedback_window.winfo_exists():
            self.feedback_window.destroy()
        if self.chapter_window is not None and self.chapter_window.winfo_exists():
            self.chapter_window.lift()
            return self.chapter_window
        if self.story_window is not None and self.story_window.winfo_exists():
            self.story_window.destroy()
        if self.session.story.chapter3b is not None:
            self.chapter_window = Chapter3CompleteDialog(
                self.root, self.session.chapter3b_result(), self.return_to_modes,
                lambda:self.return_to_modes('free'), self.show_story_status, self.show_story_review,
                retry=self.retry_chapter3b)
        elif self.session.story.chapter3 is not None:
            self.chapter_window = Chapter3CompleteDialog(
                self.root, self.session.chapter3_result(), self.return_to_modes,
                lambda:self.return_to_modes('free'), self.show_story_status, self.show_story_review,
                retry=self.retry_chapter3,
                start_next=self.begin_chapter3b if not self.session.chapter3b_unlock_reason() else None,
                next_label='Chapter 3b 시작 · 서버 장비 장애')
        elif self.session.story.chapter2 is not None:
            self.chapter_window = Chapter2CompleteDialog(
                self.root, self.session.chapter2_result(), self.return_to_modes,
                lambda:self.return_to_modes('free'), self.show_story_status, self.show_story_review,
                retry=self.retry_chapter2,
                start_chapter3=self.begin_chapter3 if not self.session.chapter3_unlock_reason() else None)
        else:
            self.chapter_window = ChapterCompleteDialog(
                self.root, self.session.chapter_result(), self.return_to_modes,
                lambda:self.return_to_modes('free'), self.show_story_status, self.show_story_review,
                start_chapter2=self.begin_chapter2)
        return self.chapter_window

    def confirm_retry_chapter2(self):
        """플레이어가 직접 선택했을 때만 재도전합니다. 현재 슬롯과 진행 중인 작업은 그대로 저장됩니다."""
        if messagebox.askyesno('이번 시도 종료 · 재도전',
                               '지금 진행은 현재 슬롯에 그대로 저장하고, 새 슬롯에서 Chapter 2를 처음부터 다시 시작할까요?',
                               parent=self.root):
            return self.retry_chapter2()
        return False

    def retry_chapter2(self):
        """현재 슬롯과 기록은 그대로 저장하고, 새 독립 슬롯에서 Chapter 2를 처음부터 시작합니다."""
        return self.return_to_modes('chapter2')

    # ---- Chapter 3b: 서버 장비 장애 ----
    def open_hardware_diagnosis(self):
        """장비 진단창을 실제로 여는 행동만 진단(이전 가능 여부 조회) 확인으로 기록합니다."""
        rid, box = self.session.selected_id, []
        if not self._perform(lambda: box.append(self.session.view_hardware_diagnosis(rid))):
            return None
        if self.diagnosis_window is not None and self.diagnosis_window.winfo_exists():
            self.diagnosis_window.destroy()
        self.diagnosis_window = self.build_popup(HardwareDiagnosisDialog, self.root, box[0])
        return self.diagnosis_window

    def repair_faulted_server(self):
        """장애가 난 서버의 장비 복구를 시작합니다(시간은 흐르지 않고, 시간 버튼으로 20분이 진행됩니다)."""
        servers = self.session.hardware_servers(self.session.current)
        faulted = [key for key in servers if self.session.servers.hardware[key].state == 'FAULT']
        if not faulted:
            return False
        return self._perform(lambda: self.session.begin_server_repair(faulted[0]))

    def chapter3b_card_actions(self, card):
        if card['can_retry']:
            return [('Chapter 3b 다시 도전', lambda: (self.close_feedback(), self.confirm_retry_chapter3b())),
                    ('후속 처리로 돌아가기', self.close_feedback)]
        return [('업무로 돌아가기', self.close_feedback)]

    def open_chapter3b_card(self, rid):
        card = self.session.chapter3b_card(rid)
        if card is None or self.closed or self.transitioning:
            return None
        for window in (self.feedback_window, self.story_window):
            if window is not None and window.winfo_exists():
                window.destroy()
        self.tutorial_highlight.clear()
        self.feedback_window = self.build_popup(Chapter3FeedbackDialog, self.root, card, self.chapter3b_card_actions(card))
        self.feedback_window.bind('<Destroy>', self.feedback_closed, add='+')
        return self.feedback_window

    def show_chapter3b_feedback(self):
        key = self.session.chapter3b_pending_feedback()
        if key is None or self.closed or self.transitioning:
            return None
        self.pending_feedback = None
        window = self.open_chapter3b_card(int(key.split(':')[0]))
        if window is None:
            return None
        try:
            self.session.mark_chapter3b_feedback_seen(key)
        except Exception as exc:
            window.destroy()
            messagebox.showerror('피드백 저장 오류', str(exc), parent=self.root)
            return None
        self.update_tutorial_highlight()
        return window

    def confirm_retry_chapter3b(self):
        if messagebox.askyesno('Chapter 3b 다시 도전',
                               '지금 진행은 현재 슬롯에 그대로 저장하고, 새 슬롯에서 Chapter 3b를 처음부터 다시 시작할까요?',
                               parent=self.root):
            return self.retry_chapter3b()
        return False

    def retry_chapter3b(self):
        return self.return_to_modes('chapter3b')

    def begin_chapter3b(self):
        """Chapter 3a 성공 결과 화면에서 호출합니다. 3a 기록은 그대로 두고 첫 장비 장애 미션 요청만 접수합니다."""
        if self.closed or self.transitioning:
            return False
        old = self.chapter_window
        if not self._perform(self.session.start_chapter3b):
            return False
        if old is not None and old.winfo_exists():
            old.destroy()
        self.chapter_window = None
        self.refresh()
        return True

    def confirm_retry_chapter3(self):
        """플레이어가 직접 선택했을 때만 재도전합니다. 현재 슬롯과 기록은 그대로 저장되고 새 슬롯에서 시작합니다."""
        if messagebox.askyesno('Chapter 3 다시 도전',
                               '지금 진행은 현재 슬롯에 그대로 저장하고, 새 슬롯에서 Chapter 3을 처음부터 다시 시작할까요?',
                               parent=self.root):
            return self.retry_chapter3()
        return False

    def retry_chapter3(self):
        return self.return_to_modes('chapter3')

    def begin_chapter3(self):
        """Chapter 2 성공 결과 화면에서 호출합니다. Chapter 2 기록은 그대로 두고 첫 장애 미션 요청만 접수합니다."""
        if self.closed or self.transitioning:
            return False
        old = self.chapter_window
        if not self._perform(self.session.start_chapter3):
            return False
        if old is not None and old.winfo_exists():
            old.destroy()
        self.chapter_window = None
        self.refresh()
        return True

    def begin_chapter2(self):
        """Chapter 1 완료 화면에서 호출합니다. 기존 완료 기록은 그대로 두고 일본·미국 요청만 접수합니다."""
        if self.closed or self.transitioning:
            return False
        old = self.chapter_window
        if not self._perform(self.session.start_chapter2):
            return False
        if old is not None and old.winfo_exists():
            old.destroy()
        self.chapter_window = None
        self.refresh()
        return True

    def return_to_modes(self, mode=None):
        if self.closed or self.transitioning:
            return False
        self.transitioning = True
        try:
            self.session.close()
        except Exception as exc:
            self.transitioning = False
            messagebox.showerror('저장 오류', f'현재 상태를 저장하지 못해 모드를 전환하지 않았습니다.\n{exc}', parent=self.root)
            return False
        self.closed = True
        self.cancel_story_event()
        self.tutorial_highlight.stop()
        self.root.unbind('<Destroy>', self.story_destroy_binding)
        self.network.stop()
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.rowconfigure(2, weight=0)
        self.mode_selector = ModeSelection(self.root, db_factory=self.db_factory, story_slots=self.story_slots,
                                           preferred_story=self.db.path if self.session.story else None)
        if mode == 'chapter2':
            self.mode_selector.new_story(2)
        elif mode == 'chapter3':
            self.mode_selector.new_story(3)
        elif mode == 'chapter3b':
            self.mode_selector.new_story('3b')
        elif mode is not None:
            self.mode_selector.start(mode)
        return True

    def confirm_story_resources(self):
        if (self.resources.selected != 'A'
                or self.resources.book.select() != str(self.resources.inspector_frame)):
            messagebox.showerror('교육 안내', 'Server A를 다시 선택하고 Inspector를 확인해 주세요.', parent=self.root)
            return False
        self.resources.book.select(self.resources.inspector_frame)
        if self._perform(self.session.confirm_story_resources):
            return True
        return False

    def skip_tutorial(self):
        if (not self.session.story or self.session.story.tutorial_completed or self.session.story.chapter2 is not None
                or self.session.story.chapter3 is not None or self.session.story.chapter3b is not None):
            return False
        if messagebox.askyesno('튜토리얼 건너뛰기',
                               '교육 안내를 건너뛸까요? 고객 업무는 직접 진행하며 스토리 모드는 유지됩니다.', parent=self.root):
            return self._perform(self.session.skip_tutorial)
        return False
    def select_request(self, rid):
        success = self._perform(lambda: self.session.select(rid))
        if success and hasattr(self, 'resources') and not self.state.allocated and not self.session.story:
            self.resources.show_preview()
        return success
    def choose_plan(self, key):
        """프로그램/테스트용 직접 시작. 화면의 시작 흐름은 반드시 [배정 설정·선택] 창을 거칩니다."""
        return self._perform(lambda: self.session.choose_plan(key))
    def update_allocation_status(self):
        """[배정 설정·선택] 옆에 현재 모드와 배정안 설정 여부를 간결하게 보여 줍니다."""
        if not hasattr(self, 'allocation_status') or self.closed:
            return
        run, key = self.session.current, self.plan_var.get()
        if run.state.allocated or run.request['status'] not in ('new', 'review', 'waiting'):
            self.allocation_status.configure(text='')
            return
        choice = self.allocation_choice
        valid = (choice is not None and choice[0] == run.request['id'] and choice[1] == key and choice[3] == self.session.minute)
        plan = '자동 추천' if valid and choice[2] is None else f'배정안 {choice[2]+1}' if valid else None
        self.allocation_status.configure(text=f'선택 모드: {run.state.plans[key]["label"]} · 배정안: '
                                         + (f'{plan} 확인됨 · 설정창에서 시작' if plan else '설정 전'))
    def remember_allocation_choice(self, mode, index):
        self.allocation_choice = (self.session.selected_id, mode, index, self.session.minute)
        self.update_allocation_status()
    def change_allocation_mode(self, mode):
        self.plan_var.set(mode)
        self.preview_plan()
    def open_allocation_plans(self):
        if self.allocation_window is not None and self.allocation_window.winfo_exists():
            self.allocation_window.lift()
            return self.allocation_window
        if self.feedback_window is not None and self.feedback_window.winfo_exists():
            self.feedback_window.destroy()
        self.allocation_window = self.build_popup(AllocationDialog,
            self.root, self.session, self.plan_var.get(),
            lambda mode, parts: self._perform(lambda: self.session.choose_plan(mode, server_plan=parts)),
            on_review=self.review_allocation_plan if self.session.story else None,
            on_reload=self.update_tutorial_highlight if self.session.story else None,
            on_mode=self.change_allocation_mode, on_choice=self.remember_allocation_choice)
        if self.session.story and self.story_window is not None and self.story_window.winfo_exists():
            self.story_window.destroy()
        if self.session.story:
            self.allocation_window.bind('<Destroy>', self.story_work_window_closed, add='+')
        self.update_tutorial_highlight()
        return self.allocation_window
    def review_allocation_plan(self):
        """비교 창에서 계획(추천안 포함)을 직접 고른 행동만 배정 검토로 확인합니다."""
        window = self.allocation_window
        if window is None or not window.winfo_exists() or window.migration:
            return
        rid = window.request_id
        if self.session.selected_id == rid:
            self._perform(lambda:self.session.inspect_story_preview(rid))
            window.paint_cards()

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
        done = self._perform(lambda: self.session.respond(key))
        window = getattr(self, 'diagnosis_window', None)
        if done and window is not None and window.winfo_exists():
            window.destroy()  # 대응 전의 진단 값이 남지 않도록 닫고, 다시 열어 비교하게 합니다.
        return done

    def open_network_diagnosis(self):
        """Chapter 3: 진단창을 실제로 여는 행동만 진단 확인으로 기록합니다."""
        rid, box = self.session.selected_id, []
        if not self._perform(lambda: box.append(self.session.view_network_diagnosis(rid))):
            return None
        if self.diagnosis_window is not None and self.diagnosis_window.winfo_exists():
            self.diagnosis_window.destroy()
        self.diagnosis_window = self.build_popup(NetworkDiagnosisDialog, self.root, box[0])
        return self.diagnosis_window
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
        story = self.session.story
        previous = story.ui_step if story else None
        anchor = self.story_anchor(previous) if story else None
        try:
            steps = self.session.read_conversation(rid)
        except Exception as exc:
            messagebox.showerror('메시지 확인 오류', str(exc), parent=self.root)
            return
        if story and story.ui_step != previous:
            self.queue_story_feedback(previous, anchor)
        self.refresh()
        if self.feedback_window is not None and self.feedback_window.winfo_exists():
            self.feedback_window.destroy()
        if self.message_window is not None and self.message_window.winfo_exists():
            self.message_window.destroy()
        run = self.session.current
        if not run.state.allocated and not self.session.story:
            self.resources.show_preview()
        confirm = None
        if (run.proposals and run.proposals[-1]['status'] == 'pending'
                and run.request['status'] in ('new','review','waiting')):
            confirm = ('고객 답변 확인', lambda count=len(run.proposals): self.review_alternative(rid, count))
        self.message_window = self.build_popup(MessageDialog, self.root, run.mission['company_name'], run.mission['country'], steps,
                                            message_kind='새 메시지' if was_unread else '확인한 메시지 · 현재 상태',
                                            confirm=confirm, summary=request_summary(run),
                                            availability=self.available_for_request())
        if self.session.story:
            if self.story_window is not None and self.story_window.winfo_exists():
                self.story_window.destroy()
            self.message_window.bind('<Destroy>', self.story_work_window_closed, add='+')
        self.update_tutorial_highlight()
        return self.message_window
    def available_for_request(self):
        gpu, power = self.session.servers.available()
        return min(gpu, self.center.available_gpu()), min(power, self.center.available_power())
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
        if self.closed:
            return
        try:
            self.session.close()
        except Exception as exc:
            messagebox.showerror('저장 오류', f'현재 상태를 저장하지 못해 종료하지 않았습니다.\n{exc}', parent=self.root)
            return
        self.network.stop()
        self.closed = True
        self.root.destroy()


class ModeSelection:
    """중앙 모드 메뉴와 독립 스토리 슬롯 선택. 메뉴에서는 DB를 열지 않습니다."""
    def __init__(self, root, db_factory=Database, story_slots=None, preferred_story=None):
        self.root, self.db_factory, self.app = root, db_factory, None
        self.story_slots = story_slots or StorySlots()
        self.preferred_story = preferred_story
        self.starting = False
        root.protocol('WM_DELETE_WINDOW', root.destroy)
        root.title(f'AIDC Simulator {VERSION} | 모드 선택')
        if root.winfo_width() <= 1:
            root.geometry('1000x650')
        root.minsize(1000, 650)
        root.configure(bg=BG)
        self.frame = tk.Frame(root, bg=BG)
        self.frame.pack(fill='both', expand=True)
        self.content = tk.Frame(self.frame, bg=BG)
        self.content.place(relx=.5, rely=.5, anchor='center', width=860)
        self.frame.bind('<Configure>', self.layout_content)
        title = tk.Frame(self.content, bg=BG)
        title.pack(anchor='w')
        icon = tk.Canvas(title, width=76, height=40, bg=BG, highlightthickness=0)
        icon.pack(side='left', padx=(0, 12))
        reset_hardware(icon)
        gpu_module(icon, 6, 6, 64, 27, 'available')
        label(title, 'AIDC Simulator', 30, CYAN, True).pack(side='left')
        label(self.content, '울산 AI 데이터센터 운영 시뮬레이션', 14, MUTED).pack(anchor='w', pady=(8, 28))
        self.menu_body = tk.Frame(self.content, bg=BG)
        self.menu_body.pack(fill='x')
        self.mode_panel = tk.Frame(self.menu_body, bg=BG)
        self.mode_panel.pack(fill='x')
        self.buttons = {}
        for mode, title, text in (
            ('story', '스토리 모드', '신입 엔지니어로 첫 출근하여 데이터센터 운영을 배우고 단계별 미션에 도전합니다.'),
            ('free', '자유 운영 모드', '기존 데이터센터 운영 기록을 이어가거나 고객 요청을 자유롭게 처리합니다.')):
            card = tk.Frame(self.mode_panel, bg=PANEL, padx=22, pady=18)
            card.pack(fill='x', pady=(0, 18))
            command = self.show_story_menu if mode == 'story' else lambda:self.start('free')
            self.buttons[mode] = ActionButton(card, title, command)
            self.buttons[mode].pack(anchor='w')
            description = label(card, text, 11, MUTED, wraplength=760, justify='left')
            description.pack(anchor='w', pady=(10, 0))
            card.bind('<Configure>', lambda e, text=description:text.configure(wraplength=max(300, e.width-44)))
        self.story_panel = tk.Frame(self.menu_body, bg=PANEL, padx=22, pady=18)
        label(self.story_panel, '스토리 모드 · Chapter 1–3', 15, CYAN, True).pack(anchor='w', pady=(0, 10))
        self.story_buttons = {}
        self.story_buttons['new'] = ActionButton(self.story_panel, 'Chapter 1 새로 시작 · 첫 출근부터', self.new_story)
        self.story_buttons['new'].pack(fill='x')
        label(self.story_panel, '첫 출근부터 정식으로 시작합니다. 이전 기록은 별도 슬롯에 보존됩니다.',
              10, MUTED).pack(anchor='w', pady=(7, 12))
        self.story_buttons['chapter2'] = ActionButton(self.story_panel, 'Chapter 2 새로 시작 · 연습', lambda:self.new_story(2))
        self.story_buttons['chapter2'].pack(fill='x')
        label(self.story_panel, 'Chapter 1 없이 여러 고객의 요청 미션만 새 슬롯에서 시작합니다. Chapter 1 진행이나 점수로 기록되지 않습니다.',
              10, MUTED, wraplength=700, justify='left').pack(anchor='w', pady=(7, 12))
        self.story_buttons['chapter3'] = ActionButton(self.story_panel, 'Chapter 3 새로 시작 · 연습', lambda:self.new_story(3))
        self.story_buttons['chapter3'].pack(fill='x')
        label(self.story_panel, 'Chapter 1·2 없이 네트워크 장애 진단 미션만 새 슬롯에서 시작합니다. Chapter 1·2를 완료한 것으로 기록되지 않습니다.',
              10, MUTED, wraplength=700, justify='left').pack(anchor='w', pady=(7, 12))
        self.story_buttons['continue3'] = ActionButton(self.story_panel, 'Chapter 3 이어하기 · 진행 중인 최근 기록', self.continue_chapter3)
        self.story_buttons['continue3'].pack(fill='x', pady=(0, 14))
        self.story_buttons['chapter3b'] = ActionButton(self.story_panel, 'Chapter 3b 새로 시작 · 연습 (서버 장비 장애)', lambda:self.new_story('3b'))
        self.story_buttons['chapter3b'].pack(fill='x')
        label(self.story_panel, 'Chapter 3a를 마친 슬롯은 결과 화면의 [Chapter 3b 시작]으로 이어서 시작합니다. 연습은 이전 Chapter를 완료한 것으로 기록하지 않습니다.',
              10, MUTED, wraplength=700, justify='left').pack(anchor='w', pady=(7, 12))
        self.story_buttons['continue3b'] = ActionButton(self.story_panel, 'Chapter 3b 이어하기 · 진행 중인 최근 기록', self.continue_chapter3b)
        self.story_buttons['continue3b'].pack(fill='x', pady=(0, 14))
        label(self.story_panel, '이어갈 저장 기록', 10, MUTED).pack(anchor='w')
        self.slot_choice = ttk.Combobox(self.story_panel, state='readonly', font=(FONT, 10))
        self.slot_choice.pack(fill='x', pady=7)
        self.story_buttons['continue'] = ActionButton(self.story_panel, '이어하기', self.continue_story)
        self.story_buttons['continue'].pack(fill='x')
        self.story_buttons['back'] = ActionButton(self.story_panel, '돌아가기', self.show_modes)
        self.story_buttons['back'].pack(anchor='w', pady=(16, 0))
        self.version_label = label(self.content, f'{VERSION} · 현재 스토리는 Chapter 3까지 제공됩니다.', 10, MUTED)
        self.version_label.pack(anchor='w', pady=(14, 0))

    def layout_content(self, event):
        self.content.place_configure(width=min(860, max(600, event.width-80)))

    def show_story_menu(self):
        if self.starting or self.app is not None:
            return
        self.slot_paths = self.story_slots.available()
        self.slot_choice.configure(values=[self.story_slots.title(p)+self.story_slots.describe(p) for p in self.slot_paths])
        if self.slot_paths:
            preferred = self.preferred_story
            index = self.slot_paths.index(preferred) if preferred in self.slot_paths else len(self.slot_paths)-1
            self.slot_choice.current(index)
        else:
            self.slot_choice.set('저장된 스토리가 없습니다.')
        self.story_buttons['continue'].configure(state='normal' if self.slot_paths else 'disabled')
        self.chapter3_paths = self.story_slots.chapter3_in_progress()
        self.story_buttons['continue3'].configure(state='normal' if self.chapter3_paths else 'disabled')
        self.chapter3b_paths = self.story_slots.chapter3b_in_progress()
        self.story_buttons['continue3b'].configure(state='normal' if self.chapter3b_paths else 'disabled')
        self.mode_panel.pack_forget()
        self.story_panel.pack(fill='x')

    def show_modes(self):
        if not self.starting:
            self.story_panel.pack_forget()
            self.mode_panel.pack(fill='x')

    def new_story(self, chapter=1):
        if self.app is not None or self.starting:
            return self.app
        try:
            path = self.story_slots.reserve_new()
        except Exception as exc:
            messagebox.showerror('새 스토리 시작 오류', str(exc), parent=self.root)
            return None
        return self.start('story', path=path, fresh=True, chapter=chapter)

    def continue_chapter3b(self):
        paths = getattr(self, 'chapter3b_paths', None) or self.story_slots.chapter3b_in_progress()
        if not paths:
            return None
        return self.start('story', path=paths[-1], resume=True)

    def continue_chapter3(self):
        """진행 중인 Chapter 3 슬롯 중 가장 최근 번호를 이어갑니다. 다른 슬롯은 건드리지 않습니다."""
        paths = getattr(self, 'chapter3_paths', None) or self.story_slots.chapter3_in_progress()
        if not paths:
            return None
        return self.start('story', path=paths[-1], resume=True)

    def continue_story(self):
        index = self.slot_choice.current()
        if index < 0 or index >= len(self.slot_paths):
            return None
        return self.start('story', path=self.slot_paths[index], resume=True)

    def start(self, mode, path=None, fresh=False, resume=False, chapter=1):
        # 직접 start('story')를 쓰는 기존 호출은 기존 스토리 파일을 이어갑니다.
        if self.app is not None or self.starting:
            return self.app
        if mode not in ('free', 'story'):
            raise ValueError('존재하지 않는 게임 모드입니다.')
        db = None
        self.starting = True
        before = set(self.root.winfo_children())
        try:
            target = path if path is not None else self.story_slots.legacy_path if mode == 'story' else DB_PATH
            if resume and not target.is_file():
                raise ValueError('선택한 저장 파일을 찾을 수 없습니다. 새 스토리 시작을 이용해 주세요.')
            db = self.db_factory(target)
            if fresh and (db.get_simulation() or db.get_requests()):
                raise ValueError('새 스토리에 기존 기록을 사용할 수 없습니다.')
            if resume and not db.get_simulation():
                raise ValueError('이 슬롯에는 이어갈 진행 기록이 없습니다. 새 스토리 시작을 이용해 주세요.')
            self.frame.pack_forget()
            options = {'start_chapter': chapter} if chapter in (2, 3, '3b') else {}
            self.app = SimulatorApp(self.root, db=db, db_factory=self.db_factory,
                                    story_slots=self.story_slots, mode=mode, **options)
        except Exception as exc:
            if db is not None and not db._game_claimed:
                db.close()
            for widget in set(self.root.winfo_children()) - before:
                widget.destroy()
            self.root.rowconfigure(2, weight=0)
            self.frame.pack(fill='both', expand=True)
            self.root.protocol('WM_DELETE_WINDOW', self.root.destroy)
            messagebox.showerror('게임 시작 오류', str(exc), parent=self.root)
            return None
        finally:
            self.starting = False
        self.frame.destroy()
        return self.app


def main():
    root = tk.Tk()
    ModeSelection(root)
    root.mainloop()


if __name__ == '__main__':
    main()
