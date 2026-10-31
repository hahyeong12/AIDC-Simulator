"""Tkinter 관제실의 공통 위젯과 별도 메시지 창."""
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from game import game_time, GameState

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
    """타이핑 완성과 페이지 이동을 다음 버튼 하나로 처리하는 업무 메신저."""
    def __init__(self, parent, company, country, steps, animate=True, message_kind='업무 메시지', confirm=None):
        super().__init__(parent, bg=BG)
        self.title(f'AIDC LINK | {company} · {country}')
        self.geometry('760x470')
        self.minsize(610, 390)
        self.steps, self.index, self.animate = steps, 0, animate
        self.message_kind = message_kind
        self.confirm = confirm
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
        final_text = self.confirm[0] if self.confirm else '확인 · 운영실로'
        self.next_button.configure(text=final_text if self.index == len(self.steps)-1 else '다음 ▶')
        self.shown = 0
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
    def reveal(self):
        self._cancel()
        self.shown = len(self.full_text)
        self._set_text(self.full_text)
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
        elif self.confirm:
            self.confirm[1]()
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
    """가용 에너지 셀과 어두운 사용 슬롯을 구분하는 Canvas 자원 HUD."""
    def __init__(self, parent, session):
        super().__init__(parent, bg=PANEL, padx=10, pady=4, highlightthickness=1,
                         highlightbackground='#31516a')
        self.session, self.preview_plan = session, 'performance'
        self.slot_signature = None
        self.slot_owners = [None]*session.center.gpu_total
        self.pulse_timer = None
        self.pulse_step = 0
        self.changed_slots = set()
        self.rack = tk.Canvas(self, bg=PANEL, width=240, height=118, highlightthickness=0)
        self.rack.pack(fill='x')
        self.rack.bind('<Configure>', lambda _: self.refresh())
        self.gpu_label = label(self.rack, size=10, color=CYAN, bold=True)
        self.gpu_numbers = {}
        for key, size in (('available', 26), ('total', 16), ('used', 11)):
            self.gpu_numbers[key] = label(self.rack, size=size, color=CYAN if key == 'available' else TEXT, bold=True)
        for widget in (self.gpu_label, *self.gpu_numbers.values()):
            widget.configure(bg='#0c192a', bd=0, padx=0, pady=0, highlightthickness=0)
        self.legend = tk.Frame(self, bg=PANEL)
        self.legend.pack(fill='x', pady=(2, 5))
        self.owners = label(self.legend, size=10, color=MUTED)
        self.owners.pack(side='left')
        self.legend_labels = []
        for _ in session.missions:
            self.legend_labels.append(label(self.legend, size=10))
        self.power = tk.Canvas(self, bg=PANEL, width=240, height=60, highlightthickness=0)
        self.power.pack(fill='x')
        self.power.bind('<Configure>', lambda _: self.refresh())
        self.power_label = label(self.power, size=10)
        self.power_label.configure(bg='#0c192a', bd=0, padx=0, pady=0)
        self.preview_frame = tk.Frame(self, bg='#0c192a', padx=5, pady=2,
                                      highlightthickness=1, highlightbackground='#31516a')
        self.preview_frame.pack(fill='x', pady=(4, 0))
        self.preview_title = label(self.preview_frame, size=11, bold=True, anchor='w')
        self.preview_title.pack(fill='x')
        self.preview = label(self.preview_frame, size=10, justify='left', wraplength=245, anchor='w')
        self.preview.pack(fill='x', pady=(3, 0))
        self.bind('<Destroy>', self._stop_pulse, add='+')
        self.bind('<Configure>', self._resize_hud, add='+')

    def _resize_hud(self, event):
        if event.widget is self:
            # 최소 창에서는 중복 비교 캡션만 생략하고 숫자·셀·본문 글자 크기는 유지합니다.
            height = 118 if event.height >= 365 else 106
            if int(self.rack.cget('height')) != height:
                self.rack.configure(height=height)
                self.refresh()

    @staticmethod
    def _chassis(canvas, width, height):
        """절삭 모서리와 상·하단 하이라이트로 금속 장비 프레임을 그립니다."""
        canvas.create_polygon(1, 8, 8, 1, width-9, 1, width-2, 8,
                              width-2, height-2, 1, height-2,
                              fill='#0c192a', outline='#31516a', width=1)
        canvas.create_line(10, 3, width-12, 3, fill='#284056')
        canvas.create_line(3, height-4, width-4, height-4, fill='#060c16')
        canvas.create_line(2, 15, 2, 30, fill=CYAN, width=2)

    def _stop_pulse(self, event=None):
        if event is not None and event.widget is not self:
            return
        if self.pulse_timer is not None:
            self.after_cancel(self.pulse_timer)
            self.pulse_timer = None

    def _pulse(self):
        self.pulse_timer = None
        self.pulse_step += 1
        if self.pulse_step >= 6:
            self.changed_slots.clear()
        self._draw_gpu()
        if self.changed_slots:
            self.pulse_timer = self.after(50, self._pulse)

    def _draw_gpu(self):
        c, canvas = self.session.center, self.rack
        canvas.delete('all')
        width = max(220, canvas.winfo_width())
        height = int(canvas.cget('height'))
        self._chassis(canvas, width, height)
        self.gpu_label.configure(text='GPU CAPACITY · 가용 GPU')
        canvas.create_window(12, 11, window=self.gpu_label, anchor='w')
        canvas.create_window(12, 44, window=self.gpu_numbers['available'], anchor='w')
        canvas.create_text(75, 49, text='/', fill=MUTED, font=(FONT, 16))
        canvas.create_window(87, 49, window=self.gpu_numbers['total'], anchor='w')
        canvas.create_text(width-64, 46, text='사용', fill=MUTED, font=(FONT, 10))
        canvas.create_window(width-34, 46, window=self.gpu_numbers['used'])
        canvas.create_line(12, 68, width-12, 68, fill='#294157')
        pending, needed, fits = self.gpu_request
        step = (width-20)/c.gpu_total
        free_index = 0
        for i, owner in enumerate(self.slot_signature):
            used = owner is not None
            color, country = owner[:2] if used else (CYAN, 'A')
            x, right = 10+i*step, 10+(i+1)*step-3
            selected = i in self.selected_slots
            pulse = i in self.changed_slots and self.pulse_step % 2 == 0
            # 밝은 가용 셀과 고객 LED만 켜진 어두운 사용 장비는 면적·문자로도 구분합니다.
            edge = '#efffff' if pulse else CYAN if not used else '#48627a' if selected else '#243449'
            canvas.create_polygon(x, 74, x+3, 71, right-3, 71, right, 74, right, 100, x, 100,
                                  fill='#173e47' if not used else '#09111e', outline=edge,
                                  width=2 if pulse or selected else 1, tags=('slot', f'slot-{i}'))
            canvas.create_line(x+3, 75, right-3, 75, fill='#a5fff4' if not used else '#30475d')
            canvas.create_rectangle(x+3, 79, right-3, 97 if not used else 82,
                                    fill=color, outline='', tags=('gpu-block', 'used' if used else 'available'))
            canvas.create_text((x+right)/2, 88, text=country,
                               fill=color if used else '#05282e', font=(FONT, 10, 'bold'),
                               tags=('slot-state', 'used-state' if used else 'available-state'))
            if selected:
                canvas.create_line(x+2, 103, right-2, 103, fill=color, width=2, tags='selected-owner')
            if pending and not used and free_index < needed:
                canvas.create_line(x+2, 104, right-2, 104, fill=CYAN if fits else AMBER,
                                   width=2, tags='request-marker')
            if not used:
                free_index += 1
        if pending and height >= 118:
            hint = f'요청 {needed} / 가용 {c.available_gpu()}'
            hint += f' · {needed-c.available_gpu()} 부족' if needed > c.available_gpu() else f' · 배정 후 {c.available_gpu()-needed} 잔여'
            canvas.create_text(width/2, 113, text=hint, fill=AMBER if not fits else CYAN,
                               font=(FONT, 10), tags='gpu-comparison')

    def _draw_power(self):
        c, canvas = self.session.center, self.power
        canvas.delete('all')
        width = max(220, canvas.winfo_width())
        ratio = c.power_used/c.power_total
        color = RED if ratio >= 1 else AMBER if ratio >= .7 else CYAN
        self._chassis(canvas, width, 60)
        canvas.create_text(12, 14, text='POWER / 전력', anchor='w', fill=TEXT, font=(FONT, 11, 'bold'))
        canvas.create_text(width-12, 14, text=f'{ratio:.0%}', anchor='e', fill=color, font=(FONT, 13, 'bold'))
        canvas.create_window(width/2, 34, window=self.power_label)
        canvas.create_rectangle(0, 47, width, 59, fill='#07101e', outline='#31516a', tags='power-total')
        canvas.create_rectangle(0, 48, width*ratio, 58, fill=color, outline='', tags='power-used')
        if ratio:
            canvas.create_line(1, 49, width*ratio, 49, fill='#c4fff4' if ratio < .7 else '#ffe7c4')
        for i in range(1, 10):
            canvas.create_line(width*i/10, 53, width*i/10, 58, fill='#0c192a')

    def refresh(self, plan=None):
        if plan is not None:
            self.preview_plan = plan
        c = self.session.center
        active = [r for r in self.session.runs.values() if r.state.allocated]
        owners, counts = {}, {}
        missions = list(self.session.missions)
        for run in active:
            color = CUSTOMER_COLORS[missions.index(run.mission['id']) % len(CUSTOMER_COLORS)]
            code = {'싱가포르':'S', '일본':'J', '미국':'U'}.get(run.mission['country'], 'X')
            key = (run.request['id'], run.playthrough_id)
            owners[key], counts[key] = (color, code, key), run.state.gpu_used
        external = max(0, c.gpu_used-sum(counts.values()))
        if external:
            owners[(-1, 0)], counts[(-1, 0)] = (MUTED, 'X', (-1, 0)), external
        # 다른 고객의 반환 때문에 계속 가동 중인 장비 위치가 이동하지 않게 합니다.
        occupied = [None]*c.gpu_total
        for i, key in enumerate(self.slot_owners):
            if counts.get(key, 0):
                occupied[i] = key
                counts[key] -= 1
        for key, count in counts.items():
            for _ in range(count):
                occupied[occupied.index(None)] = key
        self.slot_owners = occupied
        signature = tuple(owners[key] if key is not None else None for key in occupied)
        if signature != self.slot_signature:
            self._stop_pulse()
            self.changed_slots = {i for i in range(c.gpu_total) if self.slot_signature is not None and signature[i] != self.slot_signature[i]}
            self.slot_signature = signature
            self.pulse_step = 0
            if self.changed_slots:
                self.pulse_timer = self.after(50, self._pulse)
        selected = (self.session.current.request['id'], self.session.current.playthrough_id)
        self.selected_slots = {i for i,key in enumerate(occupied) if key == selected}
        for key, value in (('total', c.gpu_total), ('used', c.gpu_used), ('available', c.available_gpu())):
            self.gpu_numbers[key].configure(text=f'{value:02d}' if key == 'available' else str(value))
        self.gpu_numbers['available'].configure(fg=RED if c.available_gpu() == 0 else CYAN)
        countries = {'싱가포르':'SG', '일본':'JP', '미국':'US'}
        self.owners.configure(text='A 가용 / 사용 ' if active else 'A 가용 · 사용 없음')
        # 같은 고객의 실행이 여러 개여도 고객별 합계로 범례를 표시합니다.
        grouped = {}
        for run in active:
            mid = run.mission['id']
            grouped[mid] = grouped.get(mid, 0)+run.state.gpu_used
        for widget in self.legend_labels:
            widget.pack_forget()
        for widget, (mid, used) in zip(self.legend_labels, grouped.items()):
            mission = self.session.missions[mid]
            widget.configure(text=f'■ {countries.get(mission["country"], mission["country"])} {used}',
                             fg=CUSTOMER_COLORS[missions.index(mid) % len(CUSTOMER_COLORS)])
            widget.pack(side='left', padx=(0, 5))
        self.power_label.configure(text=f'사용 {c.power_used} / 가용 {c.available_power()} / 총 {c.power_total}')
        self._draw_power()
        run, s = self.session.current, self.session.current.state
        retry = s.phase == 'finished' and not s.succeeded and not run.followup_closed and s.retry_count < 2
        pending = run.request['status'] in ('new','review','waiting') and s.phase in ('ready','accepted')
        requested = s.plans[self.preview_plan]['gpu']
        p = s.plans[self.preview_plan]
        self.gpu_request = (pending or retry, requested,
                            requested <= c.available_gpu() and p['power'] <= c.available_power())
        self._draw_gpu()
        self.preview_frame.configure(highlightbackground='#31516a')
        if s.allocated:
            self.preview_title.configure(text='현재 작업 점유 자원')
            self.preview.configure(text=f'현재 작업 GPU {s.gpu_used} / 전력 {s.power_used}\n'
                                   f'{s.plans[s.plan]["label"]} · 진행 {s.progress:.0f}%\n'
                                   f'예상 잔여 {s.remaining_minutes}분', fg=CYAN)
            selected, duration = s.plan, s.remaining_minutes
        elif pending or retry:
            p = s.plans[self.preview_plan]
            dg, dp = c.available_gpu()-p['gpu'], c.available_power()-p['power']
            fits = min(dg, dp) >= 0
            gpu_after = f'잔여 {dg}' if dg >= 0 else f'부족 {-dg}'
            power_after = f'잔여 {dp}' if dp >= 0 else f'부족 {-dp}'
            self.preview_title.configure(text=f'{"재처리" if retry else "배정"} 검토 · {p["label"]}')
            allowed = self.session.plan_agreed(run, self.preview_plan)
            result = '배정 가능' if fits and allowed else '배정 불가 · 고객 동의 확인 필요' if fits else f'{p["label"]} 배정 불가'
            self.preview_frame.configure(highlightbackground=GREEN if fits and allowed else RED)
            self.preview.configure(text=f'GPU {p["gpu"]} 필요 / 가용 {c.available_gpu()} → {gpu_after}\n'
                                   f'전력 {p["power"]} 필요 / 가용 {c.available_power()} → {power_after}\n'
                                   + result, fg=GREEN if fits and allowed else AMBER)
            estimates = []
            for key, short in (('performance','고성능'), ('economy','절약형')):
                if retry:
                    duration = GameState(country=s.country).estimate_minutes(key)+20
                else:
                    duration = s.estimate_minutes(key)
                estimates.append(f'{short} {duration}분 → {game_time(self.session.minute+duration)}')
            self.preview.configure(text=self.preview.cget('text')+'\n'+'\n'.join(estimates))
            selected = self.preview_plan
            duration = (GameState(country=s.country).estimate_minutes(selected)+20 if retry else s.estimate_minutes(selected))
        else:
            self.preview_title.configure(text='요청 처리 결과')
            self.preview.configure(text=(f'자원 반환 완료 · 현재 점유 없음\n이번 수행 GPU {s.gpu_used} / 전력 {s.power_used}'
                                        if s.phase == 'finished' else '요청 종료 · 배정 자원 없음'), fg=MUTED)
            return
        t = run.terms
        if t:
            outcome = '기한 내 예상' if self.session.minute+duration <= t['due'] else '기한 초과 예상'
        else:
            outcome = '기존 요청 · 기한 평가 제외'
        self.preview.configure(text=self.preview.cget('text')+'\n'+outcome,
                               fg=RED if outcome == '기한 초과 예상' else self.preview.cget('fg'))


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
