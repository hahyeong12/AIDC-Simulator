"""Engineering Lab(Prototype) 화면. 같은 사건을 운영 상태·구조도·서버 내부·명령어 학습·가상 터미널로 관찰합니다.

v0.9-4a: 모든 탭은 `lab_model.observe()`의 같은 관찰 결과를 사용하고, 명령은 `lab_terminal.run_command()` 하나로 실행합니다.
v0.9-4a-1: 모드별 구성
- training(정규 심화 연수): [연수 진행] 탭의 Stage 지도·현재 목표·확인 질문. 개방되지 않은 Stage 기능은 잠기며,
  잠금은 화면뿐 아니라 세션 엔진(`GameSession.training_*`)이 다시 검증합니다.
- practice([Engineering Lab 연습]): 모든 Stage를 자유롭게 고르되 정규 기록으로 남기지 않습니다.
- preview(Chapter 3a 미션 A): 관찰 탭만 열리고 학습·명령 기능은 잠깁니다.
학습 행동은 연수 기록에만 저장되고 게임 시간·자원·점수·동의를 바꾸지 않습니다. 복구 조치는 관제실에서 합니다.
흐름 애니메이션 타이머는 화면만 다시 그리고 게임 시간을 진행하지 않습니다.
"""
import tkinter as tk
from tkinter import ttk

from lab_model import LAB_NETWORK, LAB_NOTICE, UNSUPPORTED_INTERNALS, LabLearningTrace, lab_mode, observe
from lab_terminal import (CHOICE_FIT, CHOICE_QUESTION, COMMAND_SPECS, BLOCKS, block_feedback, choice_command,
                          interpret, run_command)
from scroll_area import ScrollArea
from story import SPEAKERS
from story_portraits import draw_portrait
from training import QUESTIONS, STAGE_INFO, STAGES
from ui import BG, PANEL, RAISED, BORDER, TEXT, MUTED, CYAN, BLUE, GREEN, RED, AMBER, FONT, ActionButton, label
from ui_kit import MONO, HEALTH_TONES, Gauge, PrimaryButton, StatusChip, ToggleButton, tone_color
from window_placement import center_dialog

TABS = ('운영 상태', '네트워크 구조', '서버 내부', '명령어 학습', '가상 터미널')
TRAINING_TAB = '연수 진행'
LEVELS = (('beginner', '초급 · 객관식 (L1)'), ('intermediate', '중급 · 블록 조립 (L2)'), ('advanced', '고급 · 직접 입력 (L3)'))
LEVEL_STAGE = {'beginner': 'tool', 'intermediate': 'assemble', 'advanced': 'terminal'}
FLOW_NOTE = '교육용 흐름 애니메이션 · 실제 패킷 캡처가 아닙니다 · 게임 시간·작업량과 무관합니다'
TERM_BG, TERM_FG = '#050b14', '#cfe3f5'
OWNER_FILL = {'sg': CYAN, 'jp': BLUE, 'us': '#c5a1ff'}
GOLD = '#ffe08a'
ANIMATION_MS = 120
STATE_STYLE = {'completed': ('■ 완료', CYAN), 'current': ('▶ 현재', GOLD), 'open': ('○ 선택 가능', TEXT), 'locked': ('잠금', MUTED)}
EVIDENCE_LABELS = (('near', '가까운 네트워크 장비 관측'), ('remote', '원격 서버(AIDC 쪽) 관측'), ('route', '라우팅 정보 확인'))


class EngineeringLabDialog(tk.Toplevel):
    def __init__(self, parent, session, rid, on_change=None, on_result=None):
        super().__init__(parent, bg=BG)
        self.withdraw()
        self.session, self.rid = session, rid
        self.on_change, self.on_result = on_change, on_result
        self.mode = lab_mode(session, rid)[0] or 'preview'
        self.trace = LabLearningTrace()
        self.status = session.training_status() if self.mode in ('training', 'practice') else None
        self.obs = observe(session, rid)
        self.anim_timer, self.anim_step = None, 0
        self.choice = None
        self.blocks = {'command': None, 'option': None, 'target': None}
        self.block_result = None
        self.history, self.history_index = [], 0
        self.fact_choices = {}
        self.feedback = ('', TEXT)
        self.server_key = self.obs.job_servers[0] if self.obs.job_servers else 'A'
        self.title('Engineering Lab (Prototype) | 교육용 관찰 · 학습 화면')
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self.book = ttk.Notebook(self)
        self.book.grid(row=1, sticky='nsew', padx=12, pady=(0, 10))
        self.tabs = {}
        names = ((TRAINING_TAB,) if self.training_mode else ()) + TABS
        for name in names:
            frame = tk.Frame(self.book, bg=BG)
            self.book.add(frame, text=name)
            self.tabs[name] = frame
        if self.training_mode:
            self._build_training(self.tabs[TRAINING_TAB])
        self._build_operations(self.tabs['운영 상태'])
        self._build_network(self.tabs['네트워크 구조'])
        self._build_servers(self.tabs['서버 내부'])
        self._build_learning(self.tabs['명령어 학습'])
        self._build_terminal(self.tabs['가상 터미널'])
        self.bind('<Destroy>', self._destroyed, add='+')
        self.bind('<Escape>', lambda _: self.destroy())
        center_dialog(self, parent, size=(1060, 700), minimum=(900, 620))
        self.refresh()
        self._schedule()

    @property
    def training_mode(self):
        return self.mode in ('training', 'practice')

    # ── 공통 ─────────────────────────────────────────────
    def _build_header(self):
        top = tk.Frame(self, bg=BG)
        top.grid(row=0, sticky='ew', padx=14, pady=(10, 6))
        top.columnconfigure(1, weight=1)
        left = tk.Frame(top, bg=BG)
        left.grid(row=0, column=0, sticky='w')
        label(left, 'ENGINEERING LAB', 17, CYAN, True).pack(side='left')
        StatusChip(left, 'warn', 'PROTOTYPE', 9).pack(side='left', padx=(10, 0))
        self.mission_label = label(top, '', 11, TEXT, True, anchor='w')
        self.mission_label.grid(row=0, column=1, sticky='w', padx=16)
        right = tk.Frame(top, bg=BG)
        right.grid(row=0, column=2, sticky='e')
        self.clock_label = label(right, '', 16, TEXT, True)
        self.clock_label.pack(side='left', padx=(0, 10))
        self.status_chip = StatusChip(right, 'idle', size=11)
        self.status_chip.pack(side='left')
        info = tk.Frame(top, bg=BG)
        info.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(6, 0))
        info.columnconfigure(0, weight=1)
        text = ('관찰과 명령은 게임 시간 · 자원 · 점수 · 고객 동의를 바꾸지 않습니다. 학습 행동만 연수 기록에 저장되며, 복구 조치는 관제실에서 합니다.'
                if self.training_mode else
                '관찰 미리보기입니다. 명령어 학습과 가상 터미널은 심화 연수에서 열리며, 자유 체험은 스토리 메뉴의 [Engineering Lab 연습]을 이용하세요.')
        self.readonly_label = label(info, text, 9, MUTED, anchor='w', justify='left', wraplength=760)
        self.readonly_label.grid(row=0, column=0, sticky='w')
        ActionButton(info, '새로고침', self.refresh).grid(row=0, column=1, padx=(8, 6))
        self.return_button = PrimaryButton(info, '관제실로 돌아가기', self.destroy)
        self.return_button.grid(row=0, column=2)
        self.notice_label = label(info, '', 10, AMBER, True, anchor='w', justify='left', wraplength=900)
        self.notice_label.grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 0))

    def notify(self, text, color=AMBER):
        self.notice_label.configure(text=text, fg=color)

    def refresh(self):
        """현재 세션 상태로 모든 탭을 다시 계산합니다(조회 전용)."""
        if not self.winfo_exists() or self.rid not in self.session.runs:
            return
        self.obs = o = observe(self.session, self.rid)
        self.status = self.session.training_status() if self.training_mode else None
        head = {'training': '심화 연수', 'practice': 'Engineering Lab 연습 · 정규 기록 아님',
                'preview': 'Chapter 3a · 미션 A · 관찰 미리보기'}[self.mode]
        self.mission_label.configure(text=f'{head}  |  요청 #{o.request_id} · {o.customer} / {o.country} · {o.task}')
        self.clock_label.configure(text=o.time_label)
        if self.hide_answers:
            self.status_chip.set('warn', '작업 중단 · 원인 미확인' if o.tone == 'fault' else o.phase_label)
        else:
            self.status_chip.set(o.tone, o.phase_label)
        if self.training_mode:
            self._refresh_training()
        self._refresh_operations()
        self._draw_network()
        self._refresh_servers()
        self._refresh_learning()
        self._refresh_terminal_lock()

    def _changed(self):
        """학습 행동 뒤: 관제실(목표·버튼)과 Lab을 함께 다시 계산합니다."""
        if self.on_change is not None:
            self.on_change()
        if self.winfo_exists():
            self.refresh()

    def _destroyed(self, event):
        if event.widget is self and self.anim_timer is not None:
            try:
                self.after_cancel(self.anim_timer)
            except tk.TclError:
                pass
            self.anim_timer = None

    def _schedule(self):
        self.anim_timer = self.after(ANIMATION_MS, self._tick)

    def _tick(self):
        """화면 애니메이션만 진행합니다. 세션·게임 시간은 건드리지 않습니다."""
        self.anim_timer = None
        if not self.winfo_exists():
            return
        self.anim_step += 1
        if self.book.select() == str(self.tabs['네트워크 구조']):
            self._draw_packets()
        self._schedule()

    def show_tab(self, name):
        self.book.select(self.tabs[name])

    # ── 잠금 · 힌트 판단(표시용. 실제 잠금은 세션 엔진이 다시 검증) ──
    def stage_locked(self, stage):
        if not self.training_mode:
            return True
        return next(s['state'] for s in self.status['stages'] if s['key'] == stage) == 'locked'

    @property
    def hide_answers(self):
        """Stage 5(독립 진단)에서 원인을 판단하기 전에는 구조도·운영 상태의 장애 표시를 숨깁니다(정답 강조·자동 힌트 감춤)."""
        st = getattr(self, 'status', None)
        return bool(st and st['current'] == 'independent' and not st['done']
                    and not (st['stage5']['cause'] and st['stage5']['cause']['correct']))

    def _terminal_stage(self):
        current = self.status['current'] if self.status else None
        return current if current in ('terminal', 'independent') else 'terminal'

    def _learn(self, source, payload, stage):
        """학습 행동을 세션 엔진으로 실행합니다. 잠긴 Stage나 잘못된 입력 방식은 엔진이 거부합니다."""
        try:
            result = self.session.training_command(source, payload, stage)
        except ValueError as exc:
            self.notify(str(exc))
            return None
        self.trace.record({'choice': 'choice', 'blocks': 'blocks', 'terminal': 'terminal'}[source], result.line, result.ok,
                          result.time_label)
        self.notify('')
        self._changed()
        return result

    def _answer(self, stage, question, answer):
        try:
            correct, text = self.session.training_answer(stage, question, answer)
        except ValueError as exc:
            self.notify(str(exc))
            return None
        self.feedback = (('✔ ' if correct else '✕ ')+text, GREEN if correct else AMBER)
        self.notify('')
        self._changed()
        return correct

    # ── 연수 진행 ─────────────────────────────────────────
    def _build_training(self, frame):
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        head = tk.Frame(frame, bg=BG)
        head.grid(row=0, sticky='ew', padx=10, pady=(10, 4))
        self.progress_label = label(head, '', 15, TEXT, True)
        self.progress_label.pack(side='left')
        self.mode_chip = StatusChip(head, 'idle', size=9)
        self.mode_chip.pack(side='left', padx=10)
        self.stage_map = tk.Frame(frame, bg=BG)
        self.stage_map.grid(row=1, sticky='ew', padx=10, pady=(0, 6))
        self.stage_boxes = {}
        for index, key in enumerate(STAGES):
            self.stage_map.columnconfigure(index, weight=1, uniform='stage')
            box = tk.Frame(self.stage_map, bg=RAISED, highlightthickness=2, highlightbackground=BORDER, padx=8, pady=6,
                           cursor='hand2')
            box.grid(row=0, column=index, sticky='nsew', padx=(0, 6))
            state = label(box, '', 9, MUTED, True, anchor='w')
            state.pack(anchor='w')
            title = label(box, f'Stage {index+1}\n{STAGE_INFO[key]["short"]}', 10, TEXT, True, anchor='w', justify='left')
            title.pack(anchor='w')
            for widget in (box, state, title):
                widget.bind('<Button-1>', lambda _, k=key: self.on_stage_click(k))
            self.stage_boxes[key] = (box, state, title)
        self.training_area = ScrollArea(frame)
        self.training_area.grid(row=2, sticky='nsew', padx=4)
        self.training_bar = tk.Frame(frame, bg=PANEL, padx=10, pady=8)
        self.training_bar.grid(row=3, sticky='ew', padx=10, pady=(4, 8))

    def _refresh_training(self):
        st = self.status
        if st['practice']:
            self.progress_label.configure(text=f'Engineering Lab 연습 · 체험한 Stage {st["count"]} / 5')
            self.mode_chip.set('warn', '연습 모드 · 정규 연수 기록 아님')
        else:
            self.progress_label.configure(text=f'심화 연수 진행률 {st["count"]} / 5')
            self.mode_chip.set('done' if st['done'] else 'ok', '연수 완료' if st['done'] else '정규 연수')
        for item in st['stages']:
            box, state, title = self.stage_boxes[item['key']]
            text, color = STATE_STYLE[item['state']]
            if item['state'] == 'current' and item['passed']:
                text, color = '■ 통과 · 현재', GREEN
            elif item['state'] in ('open', 'current') and item['passed']:
                text = text+' · 통과'
            state.configure(text=text, fg=color)
            title.configure(fg=MUTED if item['state'] == 'locked' else TEXT)
            box.configure(highlightbackground=color if item['state'] == 'current' else BORDER)
        body = self.training_area.body
        for widget in body.winfo_children():
            widget.destroy()
        body.columnconfigure(1, weight=1)
        info = st['info']
        label(body, f'Stage {info["no"]} · {info["title"]}', 17, CYAN, True, anchor='w').grid(
            row=0, column=0, columnspan=2, sticky='w', padx=8, pady=(6, 2))
        label(body, info['goal'], 11, TEXT, anchor='w', justify='left', wraplength=900).grid(
            row=1, column=0, columnspan=2, sticky='w', padx=8, pady=(0, 6))
        portrait = tk.Canvas(body, width=44, height=60, bd=0, highlightthickness=0, bg=BG)
        portrait.grid(row=2, column=0, sticky='nw', padx=(8, 6))
        draw_portrait(portrait, 'mentor', True)
        portrait.scale('all', 0, 0, .37, .37)
        lines = '\n'.join(f'{SPEAKERS[role].split(" · ")[-1]}: “{text}”' for role, text in info['intro'])
        label(body, lines, 10, MUTED, anchor='w', justify='left', wraplength=860).grid(row=2, column=1, sticky='w', pady=2)
        task = tk.Frame(body, bg=PANEL, padx=12, pady=10)
        task.grid(row=3, column=0, columnspan=2, sticky='ew', padx=8, pady=(8, 4))
        task.columnconfigure(0, weight=1)
        self._incident_banner(task)
        getattr(self, '_task_'+st['current'])(task)
        text, color = self.feedback
        self.training_feedback = label(body, text, 11, color, True, anchor='w', justify='left', wraplength=900)
        self.training_feedback.grid(row=4, column=0, columnspan=2, sticky='w', padx=8, pady=(4, 2))
        if st['passed']:
            label(body, f'✔ Stage {info["no"]} 통과 — 선배: “{info["done"]}”', 11, GREEN, True, anchor='w', justify='left',
                  wraplength=900).grid(row=5, column=0, columnspan=2, sticky='w', padx=8, pady=(4, 8))
        self._render_training_bar()

    def _incident_banner(self, task):
        st = self.status
        text = ''
        if st['can_restart']:
            text = '연수 사건이 끝났습니다. 아래 [연수 사건 다시 받기]로 같은 장애를 다시 준비할 수 있습니다(통과한 Stage는 유지).'
        elif st['incident'] == 'waiting':
            run = self.session.runs[st['rid']]
            text = ('장애가 아직 발생하지 않았습니다. 관제실에서 연수 요청을 배정하고 시간을 진행하세요.' if run.state.allocated else
                    '관제실 AIDC LINK에서 연수 요청을 확인하고 배정해 작업을 시작하세요. 장애가 발생하면 이 화면에서 진행합니다.')
        if text:
            label(task, '⚠ '+text, 10, AMBER, True, anchor='w', justify='left', wraplength=860).grid(
                row=0, sticky='w', pady=(0, 8))

    def _question(self, task, row, stage, question, options, answered):
        label(task, QUESTIONS[(stage, question)]['prompt'] if (stage, question) in QUESTIONS else '', 11, TEXT, True,
              anchor='w').grid(row=row, sticky='w', pady=(6, 4))
        line = tk.Frame(task, bg=PANEL)
        line.grid(row=row+1, sticky='w')
        for key, text in options:
            chosen = answered and answered['answer'] == key
            button = ToggleButton(line, text, lambda k=key: self._answer(stage, question, k), wraplength=260, justify='left')
            button.set_selected(chosen)
            button.pack(side='left', padx=(0, 6), pady=2)

    def _check(self, task, row, done, text):
        label(task, ('✔ ' if done else '○ ')+text, 11, GREEN if done else MUTED, True, anchor='w').grid(row=row, sticky='w', pady=1)

    def _task_structure(self, task):
        st = self.status
        segment = st['segment']
        self._check(task, 1, bool(segment and segment['correct']), '구조도에서 끊어진 구간 직접 선택  (네트워크 구조 탭에서 연결선을 클릭)')
        if segment and not segment['correct']:
            label(task, '마지막 선택은 끊어진 구간이 아니었어요. 다시 찾아보세요.', 10, AMBER, anchor='w').grid(row=2, sticky='w')
        if segment and segment['correct']:
            self._check(task, 3, bool(st['impact'] and st['impact']['correct']), '그 구간이 고객 통신에 주는 영향 확인')
            self._question(task, 4, 'structure', 'impact', QUESTIONS[('structure', 'impact')]['options'], st['impact'])

    def _task_tool(self, task):
        st = self.status
        choice = st['choice']
        self._check(task, 1, bool(choice and choice['correct']), '진단 목적에 맞는 도구 선택  (명령어 학습 › 초급)')
        if choice and not choice['correct']:
            label(task, f'마지막으로 고른 {choice["answer"]}은(는) 다른 질문에 답하는 도구예요. 미션에는 영향이 없으니 다시 골라 보세요.',
                  10, AMBER, anchor='w', justify='left', wraplength=860).grid(row=2, sticky='w')
        if choice and choice['correct']:
            self._check(task, 3, bool(st['limit'] and st['limit']['correct']), '그 도구만으로 확정할 수 없는 정보 이해')
            self._question(task, 4, 'tool', 'limit', QUESTIONS[('tool', 'limit')]['options'], st['limit'])

    def _task_assemble(self, task):
        st = self.status
        record = st['assembly']
        self._check(task, 1, record is not None, '횟수 옵션(-c)과 서버 주소를 붙인 ping 조립 · 실행  (명령어 학습 › 중급)')
        if record:
            self._check(task, 2, bool(st['received'] and st['received']['correct']), f'실행 결과 확인: {record["line"]}')
            label(task, '방금 실행한 명령의 결과에서 응답(received)은 몇 개였나요?', 11, TEXT, True, anchor='w').grid(row=3, sticky='w', pady=(6, 4))
            line = tk.Frame(task, bg=PANEL)
            line.grid(row=4, sticky='w')
            for value in st['received_options']:
                button = ToggleButton(line, f'{value}개', lambda v=value: self._answer('assemble', 'received', v))
                button.set_selected(bool(st['received'] and st['received']['answer'] == value))
                button.pack(side='left', padx=(0, 6))

    def _task_terminal(self, task):
        st = self.status
        for row, (key, text) in enumerate(EVIDENCE_LABELS, start=1):
            self._check(task, row, st['evidence'][key], text+'  (가상 터미널에 직접 입력)')
        if not st['statements']:
            return
        label(task, '지금까지의 관측으로 알 수 있는 사실과 아직 확정할 수 없는 사실을 구별하세요.', 11, TEXT, True,
              anchor='w').grid(row=5, sticky='w', pady=(10, 4))
        table = tk.Frame(task, bg=PANEL)
        table.grid(row=6, sticky='ew')
        table.columnconfigure(0, weight=1)
        for row, (key, text) in enumerate(st['statements']):
            label(table, text, 10, TEXT, anchor='w', justify='left', wraplength=520).grid(row=row, column=0, sticky='w', pady=2)
            for column, (value, name) in enumerate((('confirmed', '확인된 사실'), ('unknown', '아직 확정 불가')), start=1):
                button = ToggleButton(table, name, lambda k=key, v=value: self._choose_fact(k, v))
                button.set_selected(self.fact_choices.get(key) == value)
                button.grid(row=row, column=column, padx=(6, 0), pady=2)
        ready = len(self.fact_choices) == len(st['statements'])
        PrimaryButton(task, '정리 제출', self.submit_facts, state='normal' if ready else 'disabled').grid(row=7, sticky='w', pady=(8, 0))
        facts = st['facts']
        if facts:
            self._check(task, 8, facts['correct'], '알 수 있는 사실과 확정할 수 없는 사실 구별')

    def _choose_fact(self, key, value):
        self.fact_choices[key] = value
        self._refresh_training()

    def submit_facts(self):
        keys = {key for key, _ in self.status['statements']}
        return self._answer('terminal', 'facts', {k: v for k, v in self.fact_choices.items() if k in keys})

    def _task_independent(self, task):
        st = self.status
        s5 = st['stage5']
        label(task, '증상: 싱가포르 고객의 작업이 멈췄습니다. 고객 연동 단말에서 AIDC 서버까지의 상태를 직접 조사하세요.', 11, TEXT, True,
              anchor='w', justify='left', wraplength=860).grid(row=1, sticky='w', pady=(0, 6))
        self._check(task, 2, s5['evidence_ok'], f'① 조치 전 직접 관측한 증거 확보 (현재 {s5["evidence_count"]}개)')
        cause = s5['cause']
        self._check(task, 3, bool(cause and cause['correct']), '② 증거를 바탕으로 원인 판단')
        if s5['evidence_ok'] and not (cause and cause['correct']):
            self._question(task, 4, 'independent', 'cause', QUESTIONS[('independent', 'cause')]['options'], cause)
        self._check(task, 6, s5['recovered'], '③ 관제실에서 원인에 맞는 조치 선택 (기존 대응 버튼)')
        if cause and cause['correct'] and not s5['recovered']:
            PrimaryButton(task, '관제실로 돌아가 조치하기', self.destroy).grid(row=7, sticky='w', pady=(4, 4))
        self._check(task, 8, s5['verified'], '④ 같은 관측 도구로 정상화 재확인 (가상 터미널)')

    def _render_training_bar(self):
        bar = self.training_bar
        for widget in bar.winfo_children():
            widget.destroy()
        st = self.status
        info = st['info']
        if st['done']:
            if self.on_result is not None:
                PrimaryButton(bar, '연수 결과 보기 ▶', self.on_result).pack(side='left')
            label(bar, '다섯 Stage를 모두 통과했습니다. 완료한 Stage는 언제든 복습할 수 있습니다.', 10, GREEN, True).pack(side='left', padx=10)
        elif st['can_advance']:
            nxt = STAGE_INFO[st['next']]
            PrimaryButton(bar, f'다음 Stage 시작 ▶  Stage {nxt["no"]} · {nxt["short"]}', self.start_next).pack(side='left')
        else:
            PrimaryButton(bar, f'{info["tab"]} 탭에서 진행하기 ▶', lambda: self.show_tab(info['tab'])).pack(side='left')
        if st['can_restart']:
            ActionButton(bar, '연수 사건 다시 받기', self.restart_incident, accent=AMBER).pack(side='left', padx=8)
        if st['practice']:
            label(bar, '연습: 위 단계 지도에서 원하는 Stage를 고를 수 있습니다.', 9, MUTED).pack(side='right')

    def on_stage_click(self, key):
        st = self.status
        item = next(s for s in st['stages'] if s['key'] == key)
        info = STAGE_INFO[key]
        if st['practice']:
            try:
                self.session.focus_training_stage(key)
            except ValueError as exc:
                self.notify(str(exc))
                return
            self.feedback = ('', TEXT)
            self._changed()
        elif item['state'] == 'locked':
            self.notify(f'잠금: Stage {info["no"]} · {info["short"]}은(는) 앞 Stage를 통과하고 [다음 Stage 시작]을 눌러야 열립니다.')
        elif item['state'] == 'completed':
            self.notify(f'복습: Stage {info["no"]} · {info["short"]}은(는) {info["tab"]} 탭에서 다시 해 볼 수 있습니다(진행 기록은 바뀌지 않음).',
                        CYAN)
            self.show_tab(info['tab'])
        else:
            self.show_tab(info['tab'])

    def start_next(self):
        try:
            self.session.start_next_stage()
        except ValueError as exc:
            self.notify(str(exc))
            return None
        self.feedback = ('', TEXT)
        self.fact_choices = {}
        self._changed()
        self.set_level(self._preferred_level())
        self.show_tab(TRAINING_TAB)
        return self.session.training.current

    def _preferred_level(self):
        """현재 Stage에 맞는 도움 수준(열려 있을 때). 없으면 열린 수준 중 첫 번째, 모두 잠겼으면 None."""
        current = self.status['current'] if self.status else None
        wanted = {'tool': 'beginner', 'assemble': 'intermediate', 'terminal': 'advanced', 'independent': 'advanced'}.get(current)
        if wanted and not self.stage_locked_for_level(wanted):
            return wanted
        return next((k for k, _ in LEVELS if not self.stage_locked_for_level(k)), None)

    def restart_incident(self):
        try:
            self.session.restart_training_incident()
        except ValueError as exc:
            self.notify(str(exc))
            return None
        self.rid = self.session.training.rid
        self.feedback = ('새 연수 사건을 접수했습니다. 관제실에서 배정하고 시간을 진행해 장애를 다시 준비하세요.', CYAN)
        self._changed()
        return self.rid

    # ── 운영 상태 ──────────────────────────────────────────
    def _build_operations(self, frame):
        frame.columnconfigure((0, 1), weight=1, uniform='ops')
        self.ops_gauges = {}
        for index, (key, title) in enumerate((('progress', '고객 작업 진행률'), ('network', '네트워크 대역폭 (가용 / 필요)'),
                                              ('gpu', '이 작업의 GPU 점유'), ('power', '이 작업의 전력 점유'))):
            gauge = Gauge(frame, title, height=76, bar=16)
            gauge.grid(row=index//2, column=index % 2, sticky='ew', padx=8, pady=8)
            self.ops_gauges[key] = gauge
        chips = tk.Frame(frame, bg=PANEL, padx=12, pady=10)
        chips.grid(row=2, column=0, columnspan=2, sticky='ew', padx=8, pady=(4, 8))
        chips.columnconfigure((1, 3), weight=1)
        self.ops_chips = {}
        for index, name in enumerate(('주 통신 경로', '백업 경로', '장애 상태', '복구 상태', '사용 서버', '운영 모드')):
            label(chips, name, 9, MUTED, anchor='w').grid(row=index//2, column=(index % 2)*2, sticky='w', padx=(0, 10), pady=4)
            chip = StatusChip(chips, 'idle')
            chip.grid(row=index//2, column=(index % 2)*2+1, sticky='w', pady=4)
            self.ops_chips[name] = chip
        self.ops_next = label(frame, '', 10, CYAN, anchor='w', justify='left', wraplength=900)
        self.ops_next.grid(row=3, column=0, columnspan=2, sticky='w', padx=10, pady=(2, 8))

    def _refresh_operations(self):
        o, n = self.obs, self.obs.network
        g = self.ops_gauges
        hidden = self.hide_answers
        g['progress'].set(o.progress, 100, f'{o.progress:.0f}%', 'fault' if o.tone == 'fault' else
                          'recover' if o.tone == 'recover' else 'ok', '작업 중단' if hidden and o.tone == 'fault' else o.phase_label)
        if hidden:
            g['network'].set(0, 1, '숨김', 'idle', 'Stage 5: 직접 관측해 확인하세요')
        else:
            shortage = not n.link_ok or n.needed > n.available
            g['network'].set(n.available if n.link_ok else 0, max(n.needed, 1),
                             f'{n.available if n.link_ok else 0} / {n.needed}' + ('' if n.link_ok else ' · 경로 없음'),
                             'fault' if shortage else 'ok', '교육용 가상 단위')
        g['gpu'].set(o.gpu_used, 10, f'{o.gpu_used} / 10', 'ok' if o.gpu_used else 'idle',
                     '서버 ' + (', '.join(o.job_servers) if o.job_servers else '미배정') + ' · 장애 중에도 점유 유지')
        g['power'].set(o.power_used, 10, f'{o.power_used} / 10', 'ok' if o.power_used else 'idle')
        c = self.ops_chips
        if hidden:
            for name in ('주 통신 경로', '백업 경로', '장애 상태'):
                c[name].set('idle', '숨김 (Stage 5 · 직접 관측)')
        else:
            c['주 통신 경로'].set('ok' if n.primary_up else 'fault', 'UP' if n.primary_up else 'DOWN · 링크 신호 없음')
            c['백업 경로'].set('ok' if n.rerouted else 'idle', f'사용 중 · 용량 {n.backup_capacity}' if n.rerouted else '대기 (UP)')
            c['장애 상태'].set('fault' if n.incident_kind and not n.link_ok else 'ok' if n.recovered_by else
                             'warn' if n.incident_kind else 'ok', o.incident_label)
        c['복구 상태'].set('recover' if o.phase == 'recovering' else 'fault' if o.phase in ('incident', 'paused') else
                         'ok' if n.recovered_by else 'idle', o.recovery_label)
        c['사용 서버'].set('ok' if o.job_servers else 'idle',
                         ', '.join(f'Server {k} ({LAB_NETWORK["servers"][k]})' for k in o.job_servers) or '미배정')
        c['운영 모드'].set('ok' if o.plan_label != '미선택' else 'idle', o.plan_label)
        if hidden:
            text = 'Stage 5 독립 진단: 장애 표시를 숨겼습니다. 가상 터미널로 직접 관측해 원인을 판단하세요.'
        elif o.phase in ('incident', 'paused'):
            text = ('다음 관찰: [네트워크 구조]에서 끊긴 구간을 찾아보세요. 조치는 관제실의 대응 버튼으로 합니다.' if self.training_mode or self.mode == 'preview'
                    else '')
        elif n.recovered_by:
            text = '장애 조치 후 상태입니다. 같은 명령을 다시 실행해 조치 전과 결과를 비교해 보세요.'
        else:
            text = '정상 상태의 구조와 명령 결과를 먼저 관찰해 두면, 장애가 났을 때 무엇이 달라졌는지 비교할 수 있습니다.'
        self.ops_next.configure(text=text)

    # ── 네트워크 구조 ──────────────────────────────────────
    def _build_network(self, frame):
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.net_canvas = tk.Canvas(frame, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, bd=0)
        self.net_canvas.grid(row=0, sticky='nsew', padx=8, pady=(8, 4))
        self.net_canvas.bind('<Configure>', lambda _: self._draw_network())
        legend = tk.Frame(frame, bg=BG)
        legend.grid(row=1, sticky='ew', padx=8, pady=(0, 6))
        for text, color in (('━ 정상 연결', GREEN), ('┅ ✕ 단절 · 영향 구간', RED), ('┅ 대기 중인 백업 경로', MUTED),
                            ('● 데이터 흐름(교육용)', CYAN)):
            label(legend, text, 9, color, True).pack(side='left', padx=(0, 14))
        self.net_task = label(frame, '', 10, GOLD, True, anchor='w', justify='left', wraplength=900)
        self.net_task.grid(row=2, sticky='w', padx=10)
        self.flow_label = label(frame, FLOW_NOTE+'\n'+LAB_NOTICE, 9, MUTED, anchor='w', justify='left')
        self.flow_label.grid(row=3, sticky='w', padx=10, pady=(0, 8))

    def _layout(self):
        w, h = max(self.net_canvas.winfo_width(), 700), max(self.net_canvas.winfo_height(), 360)
        nodes = {'edge': (.09*w, .5*h), 'primary': (.30*w, .25*h), 'backup': (.30*w, .76*h),
                 'gateway': (.52*w, .5*h), 'job': (.915*w, .5*h)}
        for index, server in enumerate('ABCD'):
            nodes[server] = (.73*w, h*(.14+index*.24))
        return nodes, w, h

    def _segment_style(self, status):
        return {'up': (GREEN, 3, None), 'active': (GREEN, 4, None), 'down': (RED, 4, (7, 5)),
                'standby': (MUTED, 2, (4, 4)), 'hidden': (BORDER, 3, None)}[status]

    @property
    def segment_selectable(self):
        return self.training_mode and not self.stage_locked('structure')

    def select_segment(self, segment):
        """Stage 1: 구조도의 연결선을 직접 선택합니다(판정은 세션이 현재 관찰 상태로 합니다)."""
        if not self.segment_selectable:
            return None
        try:
            correct, text = self.session.training_select_segment(segment)
        except ValueError as exc:
            self.notify(str(exc))
            return None
        self.feedback = (('✔ ' if correct else '✕ ')+text, GREEN if correct else AMBER)
        self.net_task.configure(text=self.feedback[0], fg=self.feedback[1])
        self._changed()
        return correct

    def _draw_network(self):
        canvas = self.net_canvas
        canvas.delete('all')
        o, n = self.obs, self.obs.network
        hidden = self.hide_answers
        nodes, w, h = self._layout()
        seg = {k: ('hidden' if hidden else v) for k, v in n.segments.items()}
        used = () if hidden else self._used_path_nodes()
        chosen = (self.status or {}).get('segment') if self.training_mode else None
        links = [('edge-primary', 'edge', 'primary'), ('primary-wan', 'primary', 'gateway'),
                 ('edge-backup', 'edge', 'backup'), ('backup-wan', 'backup', 'gateway')]
        for seg_id, a, b in links:
            (x1, y1), (x2, y2) = nodes[a], nodes[b]
            if self.segment_selectable:
                # 얇은 선도 쉽게 고를 수 있도록 배경색의 넓은 선택 영역을 먼저 그립니다.
                hit = canvas.create_line(x1, y1, x2, y2, fill=PANEL, width=22, tags=('hit', 'hit:'+seg_id))
                canvas.tag_bind(hit, '<Button-1>', lambda _, s=seg_id: self.select_segment(s))
            if chosen and chosen['answer'] == seg_id:
                canvas.create_line(x1, y1, x2, y2, fill=GOLD, width=10, tags=('chosen', seg_id))
            if a in used and b in used:
                canvas.create_line(x1, y1, x2, y2, fill='#1b4b52', width=12, capstyle='round', tags=('glow', seg_id))
            color, width, dash = self._segment_style(seg[seg_id])
            line = canvas.create_line(x1, y1, x2, y2, fill=color, width=width, dash=dash, tags=('link', seg_id))
            if self.segment_selectable:
                canvas.tag_bind(line, '<Button-1>', lambda _, s=seg_id: self.select_segment(s))
            mx, my = (x1+x2)/2, (y1+y2)/2
            if seg[seg_id] == 'down':
                canvas.create_text(mx, my, text='✕', fill=RED, font=(FONT, 20, 'bold'), tags=('break', seg_id))
                canvas.create_text(mx, my-24, text='DOWN · 영향 구간', fill=RED, font=(FONT, 9, 'bold'), tags=('break-label',))
            elif seg_id == 'backup-wan' and not hidden:
                canvas.create_text(mx, my+18, text=('사용 중' if seg[seg_id] == 'active' else '대기') + f' · 용량 {n.backup_capacity}',
                                   fill=GREEN if seg[seg_id] == 'active' else MUTED, font=(FONT, 9, 'bold'), tags=('seg-label',))
            elif seg_id == 'primary-wan' and not hidden:
                canvas.create_text(mx, my-18, text=f'가용 {n.available}', fill=GREEN, font=(FONT, 9, 'bold'), tags=('seg-label',))
        gx, gy = nodes['gateway']
        for server in o.servers:
            sx, sy = nodes[server.key]
            job = server.has_job
            canvas.create_line(gx, gy, sx, sy, fill=CYAN if job else BORDER, width=3 if job else 1, tags=('link', 'gateway-servers'))
            if job:
                jx, jy = nodes['job']
                running = o.phase in ('running', 'recovering')
                canvas.create_line(sx, sy, jx, jy, fill=CYAN if running else RED, width=3, dash=None if running else (5, 4),
                                   tags=('link', 'job-link'))
        router = LAB_NETWORK['routers']
        self._node(canvas, nodes['edge'], f'고객 {o.code.upper()}', f'{LAB_NETWORK["host"]}\neth0 192.168.10.5\neth1 192.168.20.5', 'ok')
        self._node(canvas, nodes['primary'], router['primary']['label'], f'{router["primary"]["name"]}\n{router["primary"]["address"]}', 'ok')
        self._node(canvas, nodes['backup'], router['backup']['label'], f'{router["backup"]["name"]}\n{router["backup"]["address"]}',
                   'ok' if n.rerouted else 'idle')
        gw = LAB_NETWORK['aidc_gateway']
        self._node(canvas, nodes['gateway'], gw['label'], f'{gw["name"]}\n{gw["address"]}', 'ok')
        for server in o.servers:
            tone = HEALTH_TONES[server.health]
            sub = f'{server.address}\nGPU {server.gpu_used}/{server.gpu_total}' + (' · 이 작업' if server.has_job else '')
            self._node(canvas, nodes[server.key], f'{server.name} · {server.health}', sub, tone, small=True,
                       accent=server.has_job)
        job_phase = '작업 중단' if hidden and o.tone == 'fault' else o.phase_label
        self._node(canvas, nodes['job'], '고객 작업', f'{o.code.upper()} · {o.progress:.0f}%\n{job_phase}',
                   'warn' if hidden and o.tone == 'fault' else o.tone)
        if hidden:
            status, color = 'Stage 5 · 장애 표시 숨김 — 가상 터미널로 직접 관측하세요', AMBER
        else:
            status = ('주 경로 DOWN — 고객 단말에서 보낸 데이터가 AIDC에 도달하지 못합니다' if not n.link_ok else
                      '백업 경로로 우회 중 — 데이터가 백업 라우터를 거쳐 전달됩니다' if n.rerouted else '주 경로 정상')
            color = RED if not n.link_ok else GREEN
        canvas.create_text(14, 12, text=status, anchor='nw', fill=color, font=(FONT, 11, 'bold'), tags=('status',))
        canvas.create_text(14, 34, text=f'관측 시각 {o.time_label} · 필요 대역폭 {n.needed}', anchor='nw', fill=MUTED,
                           font=(FONT, 9), tags=('status',))
        if not o.transferring:
            canvas.create_text(w/2, h-14, text=f'데이터 전송 없음 · 작업 {o.phase_label}', fill=MUTED, font=(FONT, 9), tags=('status',))
        if self.segment_selectable and self.status['current'] == 'structure':
            if not self.net_task.cget('text'):
                self.net_task.configure(text='Stage 1 · 끊어진 구간이라고 생각하는 연결선을 직접 클릭하세요.', fg=GOLD)
        elif not self.segment_selectable or (self.status and self.status['current'] != 'structure'):
            self.net_task.configure(text='')
        self._draw_packets()

    def _node(self, canvas, center, title, sub, tone, small=False, accent=False):
        x, y = center
        bw, bh = (64, 30) if small else (70, 36)
        color = tone_color(tone)
        canvas.create_rectangle(x-bw, y-bh, x+bw, y+bh, fill=RAISED, outline=CYAN if accent else color,
                                width=3 if accent else 2, tags=('node',))
        canvas.create_text(x, y-bh+11, text=title, fill=color, font=(FONT, 9, 'bold'), tags=('node-title',))
        canvas.create_text(x, y+6, text=sub, fill=TEXT, font=(MONO, 8), justify='center', tags=('node-sub',))

    def _used_path_nodes(self):
        o, n = self.obs, self.obs.network
        if not o.transferring:
            return ()
        return ('edge', n.active_path, 'gateway') if n.link_ok else ('edge', 'primary')

    def _packet_path(self):
        o, n = self.obs, self.obs.network
        if not o.transferring or self.hide_answers:
            return None, False
        nodes, _, _ = self._layout()
        if not n.link_ok:
            (x1, y1), (x2, y2) = nodes['primary'], nodes['gateway']
            return [nodes['edge'], nodes['primary'], ((x1+x2)/2, (y1+y2)/2)], True
        points = [nodes['edge'], nodes[n.active_path], nodes['gateway']]
        if o.job_servers:
            points += [nodes[o.job_servers[0]], nodes['job']]
        return points, False

    def _draw_packets(self):
        canvas = self.net_canvas
        canvas.delete('packet')
        points, dropped = self._packet_path()
        if not points:
            return
        lengths = [((bx-ax)**2+(by-ay)**2)**.5 for (ax, ay), (bx, by) in zip(points, points[1:])]
        total = sum(lengths) or 1
        for k in range(3):
            t = (self.anim_step*.012 + k/3) % 1
            distance, index = t*total, 0
            while index < len(lengths)-1 and distance > lengths[index]:
                distance -= lengths[index]
                index += 1
            (ax, ay), (bx, by) = points[index], points[index+1]
            ratio = distance/(lengths[index] or 1)
            x, y = ax+(bx-ax)*ratio, ay+(by-ay)*ratio
            color = RED if dropped and t > .85 else CYAN
            canvas.create_oval(x-5, y-5, x+5, y+5, fill=color, outline='', tags=('packet',))

    # ── 서버 내부 ──────────────────────────────────────────
    def _build_servers(self, frame):
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)
        side = tk.Frame(frame, bg=PANEL, padx=8, pady=8)
        side.grid(row=0, column=0, sticky='ns', padx=(8, 6), pady=8)
        label(side, '서버 선택', 10, MUTED, True).pack(anchor='w', pady=(0, 6))
        self.server_buttons = {}
        for key in 'ABCD':
            button = ToggleButton(side, f'Server {key}', lambda k=key: self.select_server(k), width=16, anchor='w')
            button.pack(fill='x', pady=3)
            self.server_buttons[key] = button
        body = tk.Frame(frame, bg=BG)
        body.grid(row=0, column=1, sticky='nsew', padx=(0, 8), pady=8)
        body.columnconfigure((0, 1), weight=1, uniform='server')
        head = tk.Frame(body, bg=BG)
        head.grid(row=0, column=0, columnspan=2, sticky='ew')
        self.server_title = label(head, '', 15, TEXT, True)
        self.server_title.pack(side='left')
        self.server_chip = StatusChip(head, 'ok', size=11)
        self.server_chip.pack(side='left', padx=10)
        self.server_jobs = label(body, '', 10, TEXT, anchor='w', justify='left', wraplength=640)
        self.server_jobs.grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 4))
        self.server_gauges = {}
        for index, (key, title) in enumerate((('gpu', '서버 GPU 점유'), ('power', '서버 전력 사용'),
                                              ('job', '관찰 중인 고객 작업 진행률'), ('jobgpu', '이 작업의 GPU (이 서버)'))):
            gauge = Gauge(body, title, height=70, bar=16)
            gauge.grid(row=2+index//2, column=index % 2, sticky='ew', padx=(0, 8) if index % 2 == 0 else 0, pady=5)
            self.server_gauges[key] = gauge
        self.slot_canvas = tk.Canvas(body, height=58, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, bd=0)
        self.slot_canvas.grid(row=4, column=0, columnspan=2, sticky='ew', pady=5)
        self.slot_canvas.bind('<Configure>', lambda _: self._draw_slots())
        missing = tk.Frame(body, bg=PANEL, padx=10, pady=8)
        missing.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(6, 0))
        label(missing, '아직 시뮬레이션하지 않는 서버 내부 정보 · 미구현', 10, AMBER, True).grid(row=0, columnspan=5, sticky='w')
        label(missing, '실제 OS 프로세스 · GPU 드라이버 · 소켓 · 커널 동작을 지어내 표시하지 않습니다. 향후 같은 관찰 모델에 연결할 자리입니다.',
              9, MUTED, anchor='w', justify='left', wraplength=640).grid(row=1, columnspan=5, sticky='w', pady=(2, 6))
        for index, (name, command) in enumerate(UNSUPPORTED_INTERNALS):
            StatusChip(missing, 'idle', f'{name} · {command} — 미구현', 9).grid(row=2+index//3, column=index % 3, sticky='w',
                                                                             padx=(0, 6), pady=2)

    def select_server(self, key):
        self.server_key = key
        self._refresh_servers()

    def _refresh_servers(self):
        o = self.obs
        server = o.server(self.server_key)
        for key, button in self.server_buttons.items():
            item = o.server(key)
            button.base_text = f'Server {key} · {item.health}' + (' · 이 작업' if item.has_job else '')
            button.set_selected(key == self.server_key)
        self.server_title.configure(text=f'{server.name} · {server.address}')
        self.server_chip.set(HEALTH_TONES[server.health], server.health + (f' · 복구 {server.repair_left}분' if server.repair_left else ''))
        phase = '작업 중단' if self.hide_answers and o.tone == 'fault' else o.phase_label
        if server.has_job:
            jobs = f'고객 작업: {o.customer}({o.code.upper()}) — {phase} · 이 서버 GPU {server.job_gpu} / 전력 {server.job_power}'
        else:
            jobs = '이 서버에는 관찰 중인 고객 작업이 없습니다.'
        others = [c.upper() for c in server.owners if c != o.code or not server.has_job]
        if others:
            jobs += '\n다른 고객 점유: ' + ', '.join(others)
        jobs += f'\n연결: {LAB_NETWORK["aidc_gateway"]["name"]}({LAB_NETWORK["aidc_gateway"]["address"]}) — 교육용 가상 주소'
        self.server_jobs.configure(text=jobs)
        healthy = server.health == 'HEALTHY'
        g = self.server_gauges
        g['gpu'].set(server.gpu_used, server.gpu_total, f'{server.gpu_used} / {server.gpu_total}', 'ok' if healthy else 'fault')
        g['power'].set(server.power_used, server.power_total, f'{server.power_used} / {server.power_total}', 'ok' if healthy else 'fault')
        if server.has_job:
            tone = 'fault' if o.tone == 'fault' else 'recover' if o.tone == 'recover' else 'ok'
            g['job'].set(o.progress, 100, f'{o.progress:.0f}%', tone, phase)
            g['jobgpu'].set(server.job_gpu, server.gpu_total, f'{server.job_gpu} / {server.gpu_total}', 'ok',
                            '중단돼도 배정은 유지' if o.tone == 'fault' else '')
        else:
            g['job'].set(0, 100, '-', 'idle', '이 서버에 관찰 중인 작업 없음')
            g['jobgpu'].set(0, server.gpu_total, '0', 'idle')
        self._draw_slots()

    def _draw_slots(self):
        canvas = self.slot_canvas
        canvas.delete('all')
        server = self.obs.server(self.server_key)
        canvas.create_text(12, 8, text='GPU 슬롯 (서버 원장)', anchor='nw', fill=MUTED, font=(FONT, 9, 'bold'))
        for slot in server.slots:
            x = 12+slot.index*92
            fault = server.health != 'HEALTHY'
            fill = RED if fault else OWNER_FILL.get(slot.owner, MUTED) if slot.owner else BG
            canvas.create_rectangle(x, 28, x+84, 50, fill=fill, outline=CYAN if slot.this_job else BORDER, width=3 if slot.this_job else 1,
                                    tags=('slot',))
            text = f'GPU{slot.index} · ' + ('FAULT' if fault else (slot.owner.upper() if slot.owner else '빈 슬롯'))
            canvas.create_text(x+42, 39, text=text, fill=BG if slot.owner or fault else MUTED, font=(FONT, 8, 'bold'))

    # ── 명령어 학습 ────────────────────────────────────────
    def _build_learning(self, frame):
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        bar = tk.Frame(frame, bg=BG)
        bar.grid(row=0, sticky='ew', padx=8, pady=(8, 4))
        label(bar, '도움 수준', 10, MUTED, True).pack(side='left', padx=(0, 8))
        self.level_buttons = {}
        for key, text in LEVELS:
            button = ToggleButton(bar, text, lambda k=key: self.set_level(k))
            button.pack(side='left', padx=(0, 6))
            self.level_buttons[key] = button
        label(bar, '학습 인터페이스 · 숙련도 인증 아님', 9, MUTED).pack(side='right')
        self.level_frames = {}
        for key, builder in (('beginner', self._build_choice), ('intermediate', self._build_blocks),
                             ('advanced', self._build_advanced)):
            area = ScrollArea(frame)
            builder(area.body)
            self.level_frames[key] = area
        self.locked_frame = tk.Frame(frame, bg=BG)
        self.locked_label = label(self.locked_frame, '', 14, MUTED, True, anchor='w', justify='left', wraplength=860)
        self.locked_label.pack(anchor='w', padx=12, pady=30)
        self.level = None
        self.set_level(self._preferred_level() if self.training_mode else None)

    def stage_locked_for_level(self, level):
        if not self.training_mode:
            return True
        if not hasattr(self, 'status') or self.status is None:
            self.status = self.session.training_status()
        return self.stage_locked(LEVEL_STAGE[level])

    def set_level(self, level):
        """도움 수준 전환. 연수에서는 개방된 Stage의 수준만 고를 수 있습니다(실행은 엔진이 다시 검증)."""
        if level is not None and self.stage_locked_for_level(level):
            info = STAGE_INFO[LEVEL_STAGE[level]]
            if hasattr(self, 'notice_label'):
                self.notify(f'잠금: {dict(LEVELS)[level]}은(는) Stage {info["no"]} · {info["short"]}에서 열립니다.')
            return False
        self.level = level
        self.trace.level = level or 'beginner'
        for key, area in self.level_frames.items():
            if key == level:
                area.grid(row=1, sticky='nsew', padx=8, pady=(0, 8))
            else:
                area.grid_remove()
        if level is None:
            text = ('명령어 학습은 Stage 2(진단 도구 선택)부터 열립니다.' if self.training_mode else
                    '명령어 학습은 심화 연수(Chapter 3b 이후)에서 단계별로 열립니다.\n자유 체험은 스토리 메뉴의 [Engineering Lab 연습]을 이용하세요.')
            self.locked_label.configure(text='잠금 · '+text)
            self.locked_frame.grid(row=1, sticky='nsew')
        else:
            self.locked_frame.grid_remove()
        self._refresh_level_buttons()
        if hasattr(self, 'term_hint'):
            self._refresh_terminal_lock()
        return True

    def _refresh_level_buttons(self):
        for key, text in LEVELS:
            button = self.level_buttons[key]
            locked = self.stage_locked_for_level(key)
            stage = STAGE_INFO[LEVEL_STAGE[key]]
            button.base_text = (f'잠금 · {text}' if locked else text) + (f' · Stage {stage["no"]}' if self.training_mode else '')
            button.set_selected(key == self.level)
            button.configure(state='disabled' if locked else 'normal')

    def _show_interpretation(self, stage):
        """초급·중급(Stage 2·3) 학습에서만 해석 도움을 보여 줍니다."""
        return stage in ('tool', 'assemble')

    def _output_box(self, parent, height=8):
        box = tk.Text(parent, height=height, bg=TERM_BG, fg=TERM_FG, font=(MONO, 10), bd=0, padx=10, pady=8,
                      wrap='none', highlightthickness=1, highlightbackground=BORDER)
        box.tag_configure('meta', foreground=MUTED)
        box.tag_configure('prompt', foreground=CYAN)
        box.tag_configure('error', foreground=RED)
        box.configure(state='disabled')
        return box

    def _set_box(self, box, result):
        box.configure(state='normal')
        box.delete('1.0', 'end')
        box.insert('end', f'[가상 시각 {result.time_label} · 교육용 출력]\n', 'meta')
        box.insert('end', f'{self._prompt()} {result.line}\n', 'prompt')
        box.insert('end', result.output+'\n', 'error' if result.kind == 'error' else ())
        box.configure(state='disabled')

    def _build_choice(self, body):
        body.columnconfigure(0, weight=1)
        label(body, 'L1 · 설명이 있는 명령어 객관식', 9, MUTED, True).grid(row=0, sticky='w', padx=4, pady=(4, 0))
        label(body, CHOICE_QUESTION, 14, TEXT, True, anchor='w', justify='left', wraplength=900).grid(row=1, sticky='w', padx=4, pady=(2, 8))
        cards = tk.Frame(body, bg=BG)
        cards.grid(row=2, sticky='ew', padx=4)
        cards.columnconfigure((0, 1, 2), weight=1, uniform='cards')
        self.choice_buttons = {}
        for index, name in enumerate(('ping', 'ip route', 'ip addr')):
            button = tk.Button(cards, text=f'{name}\n{COMMAND_SPECS[name]["summary"]}', command=lambda n=name: self.choose_command(n),
                               bg=RAISED, fg=TEXT, activebackground=BORDER, activeforeground=TEXT, relief='flat', bd=0,
                               highlightthickness=2, highlightbackground=BORDER, font=(FONT, 11, 'bold'), pady=10, cursor='hand2')
            button.grid(row=0, column=index, sticky='ew', padx=(0, 8))
            self.choice_buttons[name] = button
        detail = self.choice_detail = tk.Frame(body, bg=PANEL, padx=12, pady=10)
        detail.columnconfigure(1, weight=1)
        self.choice_fit = label(detail, '', 12, GREEN, True, anchor='w', justify='left', wraplength=860)
        self.choice_fit.grid(row=0, columnspan=2, sticky='w', pady=(0, 6))
        self.choice_fields = {}
        for row, name in enumerate(('1. 목적', '2. 확인할 수 있는 정보', '3. 확인할 수 없는 정보'), start=1):
            label(detail, name, 9, MUTED, True, anchor='nw').grid(row=row, column=0, sticky='nw', padx=(0, 12), pady=3)
            value = label(detail, '', 10, TEXT, anchor='w', justify='left', wraplength=700)
            value.grid(row=row, column=1, sticky='w', pady=3)
            self.choice_fields[name] = value
        label(detail, '4. 현재 가상 네트워크에서 실행한 관측 결과', 9, MUTED, True).grid(row=4, columnspan=2, sticky='w', pady=(8, 2))
        self.choice_output = self._output_box(detail, 9)
        self.choice_output.grid(row=5, columnspan=2, sticky='ew')
        self.choice_interpret = label(detail, '', 10, AMBER, anchor='w', justify='left', wraplength=860)
        self.choice_interpret.grid(row=6, columnspan=2, sticky='w', pady=(6, 0))
        self.choice_next = PrimaryButton(detail, '[연수 진행]의 확인 질문으로 ▶', lambda: self.show_tab(TRAINING_TAB))

    def choose_command(self, name):
        """객관식 선택: 엔진이 Stage 잠금을 확인한 뒤 같은 결과 생성기로 실행합니다. 틀려도 미션에는 영향이 없습니다."""
        result = self._learn('choice', name, 'tool')
        if result is not None:
            self.choice = name
            self._render_choice(result)
        return result

    def _render_choice(self, result):
        name = self.choice
        for key, button in self.choice_buttons.items():
            button.configure(highlightbackground=CYAN if key == name else BORDER, fg=CYAN if key == name else TEXT)
        fit, why = CHOICE_FIT[name]
        self.choice_fit.configure(text=('● 질문에 직접 답하는 도구 — ' if fit == 'best' else '▲ 다른 질문에 답하는 도구 (미션 실패 아님) — ')+why,
                                  fg=GREEN if fit == 'best' else AMBER)
        spec = COMMAND_SPECS[name]
        self.choice_fields['1. 목적'].configure(text=spec['purpose'])
        self.choice_fields['2. 확인할 수 있는 정보'].configure(text='\n'.join('· '+v for v in spec['can']))
        self.choice_fields['3. 확인할 수 없는 정보'].configure(text='\n'.join('· '+v for v in spec['cannot']))
        self._set_box(self.choice_output, result)
        self.choice_interpret.configure(text='해석 도움: '+interpret(result, self.obs))
        self.choice_detail.grid(row=3, sticky='ew', padx=4, pady=(10, 4))
        if self.status and self.status['current'] == 'tool' and fit == 'best' and not self.status['passed']:
            self.choice_next.grid(row=7, columnspan=2, sticky='w', pady=(8, 0))
        else:
            self.choice_next.grid_remove()
        self.choice_result = result

    def _build_blocks(self, body):
        body.columnconfigure(0, weight=1)
        label(body, 'L2 · 명령어 블록 조립', 9, MUTED, True).grid(row=0, sticky='w', padx=4, pady=(4, 0))
        label(body, '명령 → 옵션 → 대상 순서로 블록을 골라 실제 Linux 문법의 한 줄을 만들어 보세요.', 12, TEXT, True,
              anchor='w').grid(row=1, sticky='w', padx=4, pady=(2, 8))
        palette = tk.Frame(body, bg=PANEL, padx=10, pady=8)
        palette.grid(row=2, sticky='ew', padx=4)
        self.block_buttons = {}
        rows = (('command', '명령', [(name, name) for name in BLOCKS['command']]),
                ('option', '옵션', [(name, name) for name in BLOCKS['option']] + [(None, '옵션 없음')]),
                ('target', '대상', self._target_blocks() + [(None, '대상 없음')]))
        for row, (kind, title, items) in enumerate(rows):
            label(palette, title, 10, MUTED, True).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=4)
            for column, (value, text) in enumerate(items, start=1):
                button = tk.Button(palette, text=text, command=lambda k=kind, v=value: self.place_block(k, v), bg=RAISED,
                                   fg={'command': CYAN, 'option': AMBER, 'target': GREEN}[kind], activebackground=BORDER,
                                   relief='flat', bd=0, highlightthickness=1, highlightbackground=BORDER,
                                   font=(MONO if value else FONT, 10, 'bold'), padx=10, pady=5, cursor='hand2')
                button.grid(row=row, column=column, sticky='w', padx=(0, 6), pady=4)
                self.block_buttons[(kind, value)] = button
        line = tk.Frame(body, bg=BG)
        line.grid(row=3, sticky='ew', padx=4, pady=(10, 4))
        line.columnconfigure(1, weight=1)
        label(line, '조립한 명령', 10, MUTED, True).grid(row=0, column=0, sticky='w', padx=(0, 10))
        self.block_line = tk.Label(line, text='', bg=TERM_BG, fg=TERM_FG, font=(MONO, 13, 'bold'), anchor='w', padx=10, pady=6)
        self.block_line.grid(row=0, column=1, sticky='ew')
        PrimaryButton(line, '조립 확인 · 실행', self.run_blocks).grid(row=0, column=2, padx=(8, 6))
        ActionButton(line, '지우기', self.clear_blocks).grid(row=0, column=3)
        self.block_roles = label(body, '', 10, TEXT, anchor='w', justify='left', wraplength=900)
        self.block_roles.grid(row=4, sticky='w', padx=4, pady=(4, 2))
        self.block_errors = label(body, '', 10, RED, True, anchor='w', justify='left', wraplength=900)
        self.block_errors.grid(row=5, sticky='w', padx=4)
        self.block_output = self._output_box(body, 9)
        self.block_output.grid(row=6, sticky='ew', padx=4, pady=(6, 2))
        self.block_interpret = label(body, '', 10, AMBER, anchor='w', justify='left', wraplength=900)
        self.block_interpret.grid(row=7, sticky='w', padx=4, pady=(2, 4))
        self.block_next = PrimaryButton(body, '[연수 진행]의 결과 확인 질문으로 ▶', lambda: self.show_tab(TRAINING_TAB))
        self._render_blocks()

    def _target_blocks(self):
        servers = LAB_NETWORK['servers']
        keys = list(dict.fromkeys([*self.obs.job_servers, 'A']))
        routers = LAB_NETWORK['routers']
        return ([(servers[k], f'{servers[k]} (Server {k})') for k in keys]
                + [(routers['primary']['address'], f'{routers["primary"]["address"]} (주 경로 라우터)'),
                   (routers['backup']['address'], f'{routers["backup"]["address"]} (백업 라우터)')])

    def place_block(self, kind, value):
        self.blocks[kind] = value
        self.block_result = None
        self._render_blocks()

    def clear_blocks(self):
        self.blocks = {'command': None, 'option': None, 'target': None}
        self.block_result = None
        self._render_blocks()

    def _render_blocks(self):
        line, roles, errors = block_feedback(**self.blocks)
        self.block_line.configure(text='$ '+(line or '(블록을 선택하세요)'))
        for (kind, value), button in self.block_buttons.items():
            button.configure(highlightbackground=CYAN if self.blocks[kind] == value and value is not None else BORDER)
        self.block_roles.configure(text='\n'.join('· '+role for role in roles))
        self.block_errors.configure(text='\n'.join('✕ '+e for e in errors))
        return line, errors

    def run_blocks(self):
        """조립한 한 줄을 터미널과 같은 해석기로 실행합니다(엔진이 Stage 잠금 확인). 잘못된 조합도 같은 오류로 안내합니다."""
        line, errors = self._render_blocks()
        if not line:
            self.block_errors.configure(text='✕ 명령 블록부터 선택해 주세요.')
            return None
        result = self._learn('blocks', (self.blocks['command'], self.blocks['option'], self.blocks['target']), 'assemble')
        if result is None:
            return None
        self.block_result = result
        self._render_block_result(result)
        return result

    def _render_block_result(self, result):
        self._set_box(self.block_output, result)
        text = interpret(result, self.obs)
        self.block_interpret.configure(text='해석 도움: '+text if text else '')
        st = self.status
        if st and st['current'] == 'assemble' and st['assembly'] and not st['passed']:
            self.block_next.grid(row=8, sticky='w', padx=4, pady=(4, 8))
        else:
            self.block_next.grid_remove()

    def _build_advanced(self, body):
        body.columnconfigure(0, weight=1)
        label(body, 'L3 · 직접 입력 (힌트 최소화)', 9, MUTED, True).grid(row=0, sticky='w', padx=4, pady=(4, 0))
        label(body, '고객 작업이 멈췄습니다. 고객 연동 단말(sg-edge)에서 AIDC 서버까지의 통신 상태를 직접 조사하세요.', 14, TEXT, True,
              anchor='w', justify='left', wraplength=900).grid(row=1, sticky='w', padx=4, pady=(4, 8))
        label(body, '이 단계는 명령어 선택지 · 블록 · 해석 도움을 제공하지 않습니다. 필요한 명령은 터미널의 help로 찾을 수 있습니다.\n'
              '학습 단계는 게임 운영 점수와 분리되어 있으며, 숙련도를 인증하지 않습니다.',
              10, MUTED, anchor='w', justify='left', wraplength=900).grid(row=2, sticky='w', padx=4, pady=(0, 10))
        PrimaryButton(body, '가상 터미널로 이동', lambda: self.show_tab('가상 터미널')).grid(row=3, sticky='w', padx=4)

    def _refresh_learning(self):
        """잠금 표시를 갱신하고, 선택한 객관식·조립 결과를 현재 상태로 다시 계산합니다(표시만, 기록 없음)."""
        self._refresh_level_buttons()
        if self.level is not None and self.stage_locked_for_level(self.level):
            self.set_level(None)
        if self.level is None and self.training_mode:
            self.set_level(self._preferred_level())
        if self.choice:
            self._render_choice(run_command(choice_command(self.choice, self.obs), self.obs))
        if self.block_result is not None:
            self.block_result = run_command(self.block_result.line, self.obs)
            self._render_block_result(self.block_result)

    # ── 가상 터미널 ────────────────────────────────────────
    def _prompt(self):
        return f'{LAB_NETWORK["user"]}@{LAB_NETWORK["host"]}:~$'

    def _build_terminal(self, frame):
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        label(frame, '교육용 가상 터미널 · 실제 Windows/Linux 명령을 실행하지 않습니다 · 출력은 현재 게임 상태로 계산한 시뮬레이션입니다',
              9, AMBER, True, anchor='w').grid(row=0, sticky='w', padx=10, pady=(8, 4))
        self.term = tk.Text(frame, bg=TERM_BG, fg=TERM_FG, insertbackground=TERM_FG, font=(MONO, 10), bd=0, padx=10, pady=8,
                            wrap='char', highlightthickness=1, highlightbackground=BORDER)
        self.term.grid(row=1, sticky='nsew', padx=8)
        for tag, color in (('meta', MUTED), ('prompt', CYAN), ('error', RED), ('hint', AMBER)):
            self.term.tag_configure(tag, foreground=color)
        self._term_write('AIDC Engineering Lab 가상 터미널 (교육용 시뮬레이션)\n', 'meta')
        self._term_write(f'접속 지점: {LAB_NETWORK["host"]} ({LAB_NETWORK["host_label"]} · 교육용 가상 장비)\n', 'meta')
        self._term_write("지원 명령은 'help'로 확인할 수 있습니다.\n\n", 'meta')
        bottom = tk.Frame(frame, bg=BG)
        bottom.grid(row=2, sticky='ew', padx=8, pady=(6, 2))
        bottom.columnconfigure(1, weight=1)
        tk.Label(bottom, text=self._prompt(), bg=BG, fg=CYAN, font=(MONO, 11, 'bold')).grid(row=0, column=0, padx=(0, 6))
        self.term_entry = tk.Entry(bottom, bg=TERM_BG, fg=TERM_FG, insertbackground=TERM_FG, font=(MONO, 11), relief='flat',
                                   highlightthickness=2, highlightbackground=BORDER, highlightcolor=CYAN,
                                   disabledbackground=PANEL, disabledforeground=MUTED)
        self.term_entry.grid(row=0, column=1, sticky='ew', ipady=4)
        self.term_entry.bind('<Return>', lambda _: self.submit_terminal())
        self.term_entry.bind('<Up>', lambda _: self._history(-1))
        self.term_entry.bind('<Down>', lambda _: self._history(1))
        self.term_run = PrimaryButton(bottom, '실행', self.submit_terminal)
        self.term_run.grid(row=0, column=2, padx=(8, 0))
        self.term_hint = label(frame, '', 9, MUTED, anchor='w', justify='left')
        self.term_hint.grid(row=3, sticky='w', padx=10, pady=(2, 8))

    def terminal_locked(self):
        return not self.training_mode or self.stage_locked('terminal')

    def _refresh_terminal_lock(self):
        locked = self.terminal_locked()
        self.term_entry.configure(state='disabled' if locked else 'normal')
        self.term_run.configure(state='disabled' if locked else 'normal')
        if not self.training_mode:
            text = '잠금 · 가상 터미널은 심화 연수 Stage 4에서 열립니다. 자유 체험은 스토리 메뉴의 [Engineering Lab 연습]을 이용하세요.'
        elif locked:
            text = '잠금 · 가상 터미널은 Stage 4(터미널 직접 입력)에서 열립니다.'
        elif self._terminal_stage() == 'independent':
            text = 'Stage 5 · 힌트 없음. 입력 오류 안내만 표시합니다.'
        else:
            text = '무엇을 확인할지 스스로 정해 입력하세요. help로 지원 명령을 볼 수 있습니다.  (↑/↓: 이전 명령)'
        self.term_hint.configure(text=text, fg=AMBER if locked else MUTED)

    def _term_write(self, text, tag=()):
        self.term.configure(state='normal')
        self.term.insert('end', text, tag)
        self.term.see('end')
        self.term.configure(state='disabled')

    def submit_terminal(self):
        line = self.term_entry.get()
        self.term_entry.delete(0, 'end')
        return self.run_terminal(line)

    def run_terminal(self, line):
        """직접 입력: 엔진이 Stage 잠금을 확인하고 최신 관찰 상태로 같은 결과 생성기를 실행합니다."""
        if self.terminal_locked():
            self.notify('잠금: 가상 터미널은 Stage 4에서 열립니다.')
            return None
        stage = self._terminal_stage()
        result = self._learn('terminal', line, stage)
        if result is None:
            return None
        if line.strip():
            self.history.append(line)
        self.history_index = len(self.history)
        if result.kind == 'clear':
            self.term.configure(state='normal')
            self.term.delete('1.0', 'end')
            self.term.configure(state='disabled')
        else:
            self._term_write(f'{self._prompt()} {line}\n', 'prompt')
            if result.kind != 'empty':
                self._term_write(f'[가상 시각 {result.time_label} · 교육용 출력]\n', 'meta')
                self._term_write(result.output+'\n', 'error' if result.kind == 'error' else ())
                if result.hint:
                    self._term_write(f'입력 안내: {result.hint}\n', 'hint')
                self._term_write('\n')
        return result

    def _history(self, step):
        if not self.history:
            return 'break'
        self.history_index = max(0, min(len(self.history), self.history_index+step))
        self.term_entry.delete(0, 'end')
        if self.history_index < len(self.history):
            self.term_entry.insert(0, self.history[self.history_index])
        return 'break'


class TrainingResultDialog(tk.Toplevel):
    """심화 연수 결과: 통과한 Stage와 Stage 5 기록, 숙련도 인증이 아니라는 안내, 향후 전문 과정(미구현)."""
    def __init__(self, parent, result, on_modes, on_lab):
        super().__init__(parent, bg=BG)
        self.withdraw()
        self.result = result
        practice = result['practice']
        self.title('Engineering Lab 연습 결과' if practice else '심화 연수 결과')
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        head = tk.Frame(self, bg=BG)
        head.grid(row=0, sticky='ew', padx=16, pady=(12, 4))
        label(head, 'TRAINING COMPLETE', 9, MUTED, True).pack(anchor='w')
        self.heading = label(head, 'Engineering Lab 연습 · 다섯 Stage 체험' if practice else '심화 연수 완료 · Stage 5 / 5', 17,
                             GREEN, True)
        self.heading.pack(anchor='w')
        if practice:
            StatusChip(head, 'warn', '연습 기록 · 정규 연수 통과로 기록되지 않음', 9).pack(anchor='w', pady=(4, 0))
        area = ScrollArea(self)
        area.grid(row=1, sticky='nsew')
        body = area.body
        table = tk.Frame(body, bg=PANEL, padx=10, pady=8)
        table.grid(row=0, sticky='ew', padx=16, pady=6)
        table.columnconfigure(2, weight=1)
        for row, (name, state, detail) in enumerate(result['rows']):
            label(table, name, 10, TEXT, True, anchor='w').grid(row=row, column=0, sticky='w', padx=(0, 12), pady=2)
            label(table, '■ '+state, 10, CYAN, True).grid(row=row, column=1, sticky='w', padx=(0, 12))
            label(table, detail, 10, MUTED, anchor='w').grid(row=row, column=2, sticky='w')
        s5 = result['stage5']
        label(body, f'Stage 5 독립 진단 · 조치 전 증거 {s5["evidence"]}개 · 원인 판단 {s5["cause_attempts"]}회 · '
              f'조치 {s5["recovered_by"]} · 고객 작업 {s5["job"]}' + (f' · 연수 사건 다시 받기 {result["restarts"]}회' if result['restarts'] else ''),
              10, TEXT, anchor='w', justify='left', wraplength=620).grid(row=1, sticky='w', padx=16, pady=4)
        label(body, result['notice'], 10, AMBER, True, anchor='w', justify='left', wraplength=620).grid(row=2, sticky='w', padx=16, pady=4)
        label(body, '선배: “'+result['outro']+'”', 10, TEXT, anchor='w', justify='left', wraplength=620).grid(row=3, sticky='w', padx=16, pady=4)
        label(body, '향후 전문 엔지니어 과정(미구현): 원인을 미리 알 수 없는 새 장애, 더 많은 관측 도구, 조치 후 검증 평가.', 10, MUTED,
              anchor='w', justify='left', wraplength=620).grid(row=4, sticky='w', padx=16, pady=(4, 8))
        buttons = tk.Frame(self, bg=BG)
        buttons.grid(row=2, sticky='ew', padx=16, pady=(4, 12))
        self.lab_button = PrimaryButton(buttons, 'Engineering Lab 복습', on_lab)
        self.lab_button.pack(side='left')
        ActionButton(buttons, '모드 선택', on_modes).pack(side='left', padx=8)
        self.close_button = ActionButton(buttons, '닫기', self.destroy)
        self.close_button.pack(side='right')
        self.bind('<Escape>', lambda _: self.destroy())
        center_dialog(self, parent, size=(680, 500), minimum=(560, 400))
