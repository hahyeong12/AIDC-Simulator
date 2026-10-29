"""Tkinter 관제실의 공통 위젯과 별도 메시지 창."""
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from game import game_time

BG, PANEL, RAISED, BORDER = '#080f1d', '#101c2e', '#17273d', '#263b54'
TEXT, MUTED, CYAN, BLUE = '#e3edf8', '#91a7c1', '#38d9d0', '#6d9fff'
GREEN, RED, AMBER = '#66e0a3', '#ff6b79', '#ffbf69'
FONT = 'Malgun Gothic'
CUSTOMER_COLORS = (CYAN, BLUE, '#c5a1ff', AMBER)


def label(parent, text='', size=10, color=TEXT, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                    font=(FONT, size, 'bold' if bold else 'normal'), **kwargs)


def status_of(state):
    names = {'ready': ('미배정', MUTED), 'accepted': ('수락 · 배정 대기', BLUE),
             'running': ('정상 실행 중', CYAN), 'incident': ('! 네트워크 장애', RED),
             'paused': ('일시 중단 · 추가 대응 필요', AMBER), 'recovering': ('복구 / 재처리 준비 중', BLUE)}
    if state.phase in names:
        return names[state.phase]
    return (f'완료 · {state.score}점', GREEN) if state.succeeded else (f'실패 · {state.score}점', RED)


def request_status_of(run):
    status = run.request['status']
    if run.terms.get('expired'):
        return '미처리 · 기한 만료', RED
    if status in ('operating', 'completed') or run.state.phase == 'accepted':
        return status_of(run.state)
    return {'new': ('신규 요청', CYAN), 'review': ('검토 중', BLUE),
            'waiting': ('대기 · 미점유', AMBER), 'rejected': ('거절', MUTED)}[status]


class ActionButton(tk.Button):
    def __init__(self, parent, text, command, accent=CYAN, **kwargs):
        super().__init__(parent, text=text, command=command, bg=RAISED, fg=accent,
                         activebackground=BORDER, activeforeground=TEXT, disabledforeground=MUTED,
                         relief='flat', bd=0, highlightthickness=1, highlightbackground=BORDER,
                         font=(FONT, 10, 'bold'), padx=10, pady=7, cursor='hand2', **kwargs)
        self.bind('<Enter>', lambda _: self.configure(bg=BORDER) if self.cget('state') != 'disabled' else None)
        self.bind('<Leave>', lambda _: self.configure(bg=RAISED))


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.timer, self.window = widget, text, None, None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<Destroy>', self.hide, add='+')
    def schedule(self, _=None):
        self.hide()
        self.timer = self.widget.after(500, self.show)
    def show(self):
        self.timer = None
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f'+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty()+28}')
        tk.Label(self.window, text=self.text, bg=BORDER, fg=TEXT, wraplength=280,
                 font=(FONT, 10), padx=10, pady=8).pack()
    def hide(self, _=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class TextDialog(tk.Toplevel):
    def __init__(self, parent, title, text):
        super().__init__(parent, bg=BG)
        self.title(title)
        self.geometry('800x510')
        self.minsize(520, 330)
        box = ScrolledText(self, wrap='word', bg=PANEL, fg=TEXT, font=(FONT, 11), padx=18, pady=15)
        box.pack(fill='both', expand=True, padx=10, pady=10)
        box.insert('1.0', text)
        box.configure(state='disabled')
        self.text = box


class MessageDialog(tk.Toplevel):
    """단계별 업무 메신저. 전체 보기와 즉시 표시를 지원합니다."""
    def __init__(self, parent, company, country, steps, animate=True, message_kind='업무 메시지'):
        super().__init__(parent, bg=BG)
        self.title(f'AIDC LINK | {company} · {country}')
        self.geometry('760x470')
        self.minsize(610, 390)
        self.steps, self.index, self.animate = steps, 0, animate
        self.message_kind = message_kind
        self.timer, self.shown = None, 0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        label(self, f'AIDC LINK   /   {company} · {country}', 14, CYAN, True).grid(row=0, sticky='w', padx=20, pady=(18, 10))
        self.speaker = label(self, size=11, bold=True, anchor='w')
        self.speaker.grid(row=1, sticky='ew', padx=20)
        self.bubble = ScrolledText(self, wrap='word', font=(FONT, 12), bg=PANEL, fg=TEXT,
                                   bd=0, padx=18, pady=18, height=7)
        self.bubble.grid(row=2, sticky='nsew', padx=20, pady=10)
        self.page = label(self, color=MUTED)
        self.page.grid(row=3, sticky='w', padx=20)
        buttons = tk.Frame(self, bg=BG)
        buttons.grid(row=4, sticky='ew', padx=20, pady=(10, 18))
        self.previous_button = ActionButton(buttons, '◀ 이전', self.previous)
        self.previous_button.pack(side='left', padx=(0, 6))
        self.next_button = ActionButton(buttons, '다음 ▶', self.next)
        self.next_button.pack(side='left', padx=6)
        self.reveal_button = ActionButton(buttons, '즉시 표시', self.reveal)
        self.reveal_button.pack(side='left', padx=6)
        ActionButton(buttons, '전체 보기', self.show_all).pack(side='left', padx=6)
        self.skip_button = ActionButton(buttons, '건너뛰기', self.skip)
        self.skip_button.pack(side='right')
        self.bind('<Destroy>', self._cancel, add='+')
        self.render()
    def _cancel(self, event=None):
        if event is not None and event.widget is not self:
            return
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
    def render(self):
        self._cancel()
        speaker, self.full_text = self.steps[self.index]
        self.speaker.configure(text=speaker)
        self.page.configure(text=f'{self.index+1} / {len(self.steps)}   ·   {self.message_kind} · 과거 내용은 운영실 [대화 기록]')
        self.previous_button.configure(state='normal' if self.index else 'disabled')
        self.next_button.configure(text='확인 · 운영실로' if self.index == len(self.steps)-1 else '다음 ▶')
        self.shown = 0
        self.reveal_button.configure(state='normal')
        self._type() if self.animate else self.reveal()
    def _set_text(self, text):
        self.bubble.configure(state='normal')
        self.bubble.delete('1.0', 'end')
        self.bubble.insert('end', text)
        self.bubble.configure(state='disabled')
    def _type(self):
        self.timer = None
        self.shown = min(len(self.full_text), self.shown+3)
        self._set_text(self.full_text[:self.shown])
        if self.shown < len(self.full_text):
            self.timer = self.after(18, self._type)
        else:
            self.reveal_button.configure(state='disabled')
    def reveal(self):
        self._cancel()
        self.shown = len(self.full_text)
        self._set_text(self.full_text)
        self.reveal_button.configure(state='disabled')
    def skip(self):
        self.index = len(self.steps)-1
        self.render()
        self.reveal()
    def next(self):
        if self.shown < len(self.full_text):
            self.reveal()
        elif self.index < len(self.steps)-1:
            self.index += 1
            self.render()
        else:
            self.destroy()
    def previous(self):
        if self.index:
            self.index -= 1
            self.render()
    def show_all(self):
        return TextDialog(self, '업무 메시지 전체 보기', '\n\n'.join(f'{s}\n{t}' for s, t in self.steps))


class NetworkMap(tk.Canvas):
    def __init__(self, parent, session, select):
        super().__init__(parent, bg=BG, highlightthickness=0, width=300, height=220)
        self.session, self.select, self.tick, self.timer = session, select, 0, None
        self.bind('<Configure>', lambda _: self.redraw())
    def start(self):
        self.animate()
    def stop(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
    def animate(self):
        self.tick = (self.tick+1) % 32
        self.redraw()
        self.timer = self.after(100, self.animate)
    def redraw(self):
        self.delete('all')
        w, h = max(260, self.winfo_width()), max(180, self.winfo_height())
        cx, cy = w*.5, h*.50
        for x in range(15, int(w), 30):
            for y in range(15, int(h), 30):
                self.create_oval(x, y, x+1, y+1, fill=BORDER, outline='')
        visible = {}
        for rid, run in self.session.runs.items():
            if run.state.phase not in ('ready', 'accepted'):
                visible[run.mission['id']] = (rid, run)
        if not visible:
            self.create_text(cx, h*.84, text='운영할 고객 요청을 선택하세요', fill=MUTED, font=(FONT, 10), tags='empty-network')
        for i, (rid, run) in enumerate(visible.values()):
            x, y = ((w*.22, h*.17), (w*.78, h*.17), (w*.5, h*.84))[i % 3]
            s = run.state
            caption, color = status_of(s)
            fault = s.phase in ('incident', 'paused')
            self.create_line(cx, cy, x, y, fill=RED if fault else color, width=2, dash=(5, 4) if fault else ())
            if s.response == 'reroute':
                self.create_line(cx, cy, (cx+x)/2+35, (cy+y)/2, x, y, fill=CYAN,
                                 width=2, smooth=True, dash=(6, 4), dashoffset=self.tick, tags='backup')
            if s.phase in ('running', 'incident', 'recovering'):
                t = self.tick/32
                dx, dy = cx+(x-cx)*t, cy+(y-cy)*t
                self.create_oval(dx-3, dy-3, dx+3, dy+3, fill=color, outline='', tags='packet')
            tag = f'request-{rid}'
            self.create_rectangle(x-63, y-24, x+63, y+24, fill=PANEL, outline=color, width=2, tags=tag)
            self.create_text(x, y-7, text=run.mission['country'], fill=TEXT, font=(FONT, 11, 'bold'), tags=tag)
            progress = getattr(s, 'progress', 0)
            self.create_text(x, y+11, text=f'{caption.split(" · ")[0]} {progress:.0f}%', fill=color, font=(FONT, 9), tags=tag)
            self.tag_bind(tag, '<Button-1>', lambda _, key=rid: self.select(key))
        self.create_oval(cx-43, cy-43, cx+43, cy+43, fill=PANEL, outline=CYAN, width=2)
        self.create_text(cx, cy-8, text='ULSAN', fill=CYAN, font=(FONT, 14, 'bold'))
        self.create_text(cx, cy+13, text='AI DATA CENTER', fill=TEXT, font=(FONT, 8))


class ResourcePanel(tk.Frame):
    def __init__(self, parent, session):
        super().__init__(parent, bg=PANEL, padx=12, pady=10)
        self.session, self.preview_plan = session, 'performance'
        label(self, '자원 관제', 12, bold=True).pack(anchor='w')
        self.gpu_label = label(self, size=11, bold=True)
        self.gpu_label.pack(anchor='w', pady=(4, 2))
        self.rack = tk.Canvas(self, bg=PANEL, width=220, height=48, highlightthickness=0)
        self.rack.pack(fill='x')
        self.rack.bind('<Configure>', lambda _: self.refresh())
        self.power_label = label(self, size=10)
        self.power_label.pack(anchor='w', pady=(3, 2))
        self.power = tk.Canvas(self, bg=PANEL, width=220, height=12, highlightthickness=0)
        self.power.pack(fill='x')
        self.power.bind('<Configure>', lambda _: self.refresh())
        self.free = label(self, color=CYAN, size=10)
        # 가용량은 위 두 자원 제목에 상시 표시하며 중복 줄을 늘리지 않습니다.
        self.owners = label(self, size=9, justify='left', wraplength=230, anchor='w')
        self.owners.pack(fill='x', pady=(3, 3))
        label(self, '선택 모드 배정 미리보기', 10, bold=True).pack(anchor='w')
        self.preview_bar = tk.Canvas(self, bg=PANEL, width=220, height=16, highlightthickness=0)
        self.preview_bar.pack(fill='x', pady=(3, 2))
        self.preview = label(self, size=10, justify='left', wraplength=230, anchor='w')
        self.preview.pack(fill='x')
    def refresh(self, plan=None):
        if plan is not None:
            self.preview_plan = plan
        c = self.session.center
        active = [r for r in self.session.runs.values() if r.state.phase in ('running', 'incident', 'paused', 'recovering')]
        colors = []
        for run in active:
            index = list(self.session.missions).index(run.mission['id'])
            colors.extend([CUSTOMER_COLORS[index % 4]]*run.state.gpu_used)
        self.gpu_label.configure(text=f'GPU  사용 {c.gpu_used}  /  가용 {c.available_gpu()}  /  총 {c.gpu_total}')
        self.rack.delete('all')
        width = max(180, self.rack.winfo_width())
        for i in range(c.gpu_total):
            x, y = i%5*width/5, i//5*24
            color = colors[i] if i < len(colors) else BORDER
            self.rack.create_rectangle(x+1, y+1, x+width/5-4, y+21, fill=color, outline=MUTED if i >= c.gpu_used else color, tags='gpu-block')
        self.power_label.configure(text=f'전력  사용 {c.power_used} / 가용 {c.available_power()} / 총 {c.power_total}')
        self.power.delete('all')
        width = max(180, self.power.winfo_width())
        self.power.create_rectangle(0, 0, width, 12, fill=BORDER, outline='')
        self.power.create_rectangle(0, 0, width*c.power_used/c.power_total, 12, fill=CYAN, outline='')
        self.free.configure(text=f'배정 가능 GPU {c.available_gpu()}개 · 전력 {c.available_power()}단위')
        countries = {'싱가포르':'SG','일본':'JP','미국':'US'}
        owners = ' · '.join(f'{countries.get(r.mission["country"], r.mission["country"])} {r.state.gpu_used}/{r.state.power_used}' for r in active)
        self.owners.configure(text='고객별 점유 GPU/전력\n'+owners if active else '현재 점유 작업 없음')
        s = self.session.current.state
        p = s.plans[self.preview_plan]
        dg, dp = c.available_gpu()-p['gpu'], c.available_power()-p['power']
        fits = min(dg, dp) >= 0
        self.preview.configure(text=f'{p["label"]} · GPU {p["gpu"]} / 전력 {p["power"]}\n'
                               f'GPU {"잔여" if dg >= 0 else "부족"} {abs(dg)} · '
                               f'전력 {"잔여" if dp >= 0 else "부족"} {abs(dp)}', fg=GREEN if fits else AMBER)
        self.preview_bar.delete('all')
        width = max(180, self.preview_bar.winfo_width())
        self.preview_bar.create_rectangle(0, 0, width, 14, fill=BORDER, outline='')
        self.preview_bar.create_rectangle(0, 0, width*min(c.gpu_total, c.gpu_used+p['gpu'])/c.gpu_total, 14,
                                          fill=GREEN if fits else AMBER, outline='')
        if s.allocated:
            self.preview.configure(text=f'현재 작업 GPU {s.gpu_used} / 전력 {s.power_used}\n진행 {s.progress:.0f}% · 잔여 약 {s.remaining_minutes}분', fg=CYAN)
            self.preview_bar.delete('all')
            self.preview_bar.create_rectangle(0, 0, width, 14, fill=BORDER, outline='')
            self.preview_bar.create_rectangle(0, 0, width*s.progress/100, 14, fill=CYAN, outline='')
        if s.phase != 'finished' and self.session.current.request['status'] != 'rejected':
            estimates = []
            for key, short in (('performance','고성능'),('economy','절약형')):
                duration = s.estimate_minutes(key)
                estimates.append(f'{short} {duration}분 → {game_time(self.session.minute+duration)}')
            t = self.session.current.terms
            selected = s.plan if s.allocated else self.preview_plan
            outcome = ('기한 내 예상' if self.session.minute+s.estimate_minutes(selected) <= t['due']
                       else '기한 초과 예상') if t else '기존 요청 · 기한 평가 제외'
            self.preview.configure(text=self.preview.cget('text')+'\n'+'\n'.join(estimates)+'\n'+outcome,
                                   fg=RED if outcome=='기한 초과 예상' else self.preview.cget('fg'))


class RejectionDialog(tk.Toplevel):
    def __init__(self, parent, submit):
        super().__init__(parent, bg=PANEL)
        self.title('고객 요청 거절')
        self.geometry('520x310')
        self.minsize(450, 280)
        self.transient(parent)
        self.submit = submit
        label(self, '거절 사유를 선택해 주세요', 13, bold=True).pack(anchor='w', padx=18, pady=15)
        from session import REJECTION_REASONS
        self.reason = tk.StringVar()
        ttk.Combobox(self, textvariable=self.reason, values=REJECTION_REASONS, state='readonly').pack(fill='x', padx=18)
        label(self, '기타 사유는 설명 필수 · 거절은 수행 실패와 별도 기록', 10, MUTED).pack(anchor='w', padx=18, pady=8)
        self.note = tk.Text(self, height=3, bg=BG, fg=TEXT, insertbackground=TEXT, font=(FONT, 10), bd=0)
        self.note.pack(fill='both', expand=True, padx=18, pady=8)
        self.confirm_button = ActionButton(self, '거절 기록 저장', self.confirm, accent=AMBER)
        self.confirm_button.pack(fill='x', padx=18, pady=12)
        self.grab_set()
    def confirm(self):
        reason, note = self.reason.get(), self.note.get('1.0', 'end').strip()
        if not reason or (reason == '기타 사유' and not note):
            messagebox.showwarning('거절 사유 필요', '사유를 선택하고 기타 사유라면 설명을 입력해 주세요.', parent=self)
            return
        if self.submit(f'{reason}: {note}' if note else reason):
            self.destroy()
