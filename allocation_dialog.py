"""서버 배정 비교 창. 확정 전까지는 원장과 DB를 변경하지 않습니다."""
import tkinter as tk

from server_resources import SERVERS
from server_console import server_views
from server_widgets import (BG, PANEL, EDGE, TEXT, MUTED, CYAN, RED, FONT,
                            gpu_module, reset_hardware, ink)


class AllocationDialog(tk.Toplevel):
    def __init__(self, parent, session, mode, on_start, migration=False):
        super().__init__(parent)
        self.session, self.mode, self.on_start = session, mode, on_start
        self.request_id = session.selected_id
        self.migration = migration
        self.title(('작업 이전 계획' if migration else '서버 배정 계획 비교')+' · v0.9-1b-1')
        self.configure(bg=BG)
        self.transient(parent)
        self.geometry('940x550')
        self.minsize(880, 530)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.selection = tk.IntVar(value=-1)
        self.heading = tk.Label(self, bg=BG, fg=TEXT, font=(FONT, 11, 'bold'), anchor='w', justify='left')
        self.heading.grid(row=0, sticky='ew', padx=14, pady=(12, 4))
        self.auto_button = tk.Radiobutton(self, text='자동 추천 · 시작 시 현재 자원으로 다시 계산',
                                         variable=self.selection, value=-1, command=self.draw_preview,
                                         bg=BG, fg=CYAN, selectcolor=PANEL, activebackground=BG,
                                         activeforeground=CYAN, font=(FONT, 10), anchor='w')
        self.auto_button.grid(row=1, sticky='ew', padx=12)
        if migration:
            self.auto_button.grid_remove()
        self.cards = tk.Frame(self, bg=BG)
        self.cards.grid(row=2, sticky='ew', padx=12, pady=6)
        self.canvas = tk.Canvas(self, bg=PANEL, height=135, highlightthickness=1, highlightbackground=EDGE)
        self.canvas.grid(row=3, sticky='nsew', padx=12)
        self.canvas.bind('<Configure>', lambda _: self.draw_preview())
        footer = tk.Frame(self, bg=BG)
        footer.grid(row=4, sticky='ew', padx=12, pady=10)
        footer.columnconfigure(0, weight=1)
        self.notice = tk.Label(footer, bg=BG, fg=MUTED, font=(FONT, 9), anchor='w', justify='left', wraplength=880)
        self.notice.grid(row=0, columnspan=3, sticky='ew', pady=(0, 7))
        self.reload_button = self.button(footer, '현재 자원으로 다시 확인', self.reload)
        self.reload_button.grid(row=1, column=0, sticky='w')
        self.start_button = self.button(footer, '선택한 계획으로 작업 시작', self.start)
        if migration:
            self.start_button.configure(text='선택한 계획으로 이전 · 준비 10분')
        self.start_button.grid(row=1, column=1, padx=8)
        self.close_button = self.button(footer, '닫기', self.destroy)
        self.close_button.grid(row=1, column=2)
        self.reload()
        self.grab_set()

    @staticmethod
    def button(parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=PANEL, fg=CYAN,
                         activebackground=EDGE, activeforeground=TEXT, font=(FONT, 10),
                         relief='flat', padx=12, pady=7)

    def reload(self):
        # 재조회 버튼을 누른 경우에만 기존 직접 선택을 해제합니다.
        run = self.session.runs[self.request_id]
        result = self.session.migration_preview(run) if self.migration else self.session.allocation_options(run, self.mode)
        self.options = result['options']
        self.source = result.get('source')
        self.views = server_views(self.session, exclude_playthrough=run.playthrough_id if self.migration else None)
        self.selection.set(0 if self.migration else -1)
        p = run.state.plans[self.mode]
        self.heading.configure(text=f'요청 #{self.request_id} · {run.mission["company_name"]} · {p["label"]}'
                               f'  |  GPU {p["gpu"]} / 전력 {p["power"]}\n'
                               '서버별 배정과 잔여량 비교 · 수치는 GPU / 전력 순서입니다.')
        if self.migration:
            current = ', '.join(f'{s.server_id} {s.gpu}/{s.power}' for s in self.source.slices) if self.source else '점유 없음'
            self.heading.configure(text=self.heading.cget('text')+f'\n현재 위치: {current} · 기존 수행/진행률/기한 유지 · 이전 준비 10분')
        for child in self.cards.winfo_children():
            child.destroy()
        for i in range(3):
            self.cards.columnconfigure(i, weight=0, uniform='')
        self.plan_buttons = []
        self.comparison_rows = []
        for i, parts in enumerate(self.options):
            self.cards.columnconfigure(i, weight=1, uniform='plans')
            card = tk.Frame(self.cards, bg=PANEL, highlightthickness=1, highlightbackground=EDGE, padx=7, pady=5)
            card.grid(row=0, column=i, sticky='nsew', padx=3)
            title = '추천안 직접 선택' if i == 0 else f'대안 {i}'
            radio = tk.Radiobutton(card, text=title, variable=self.selection, value=i,
                                   command=self.draw_preview, bg=PANEL, fg=CYAN, selectcolor=BG,
                                   activebackground=PANEL, activeforeground=CYAN, font=(FONT, 10, 'bold'))
            radio.grid(row=0, columnspan=3, sticky='w')
            self.plan_buttons.append(radio)
            for column, text in enumerate(('서버', '배정 GPU/전력', '잔여 GPU/전력')):
                tk.Label(card, text=text, bg=PANEL, fg=MUTED, font=(FONT, 9)).grid(row=1, column=column, padx=4)
            rows = []
            for row, view in enumerate(self.views, 2):
                spec = view['spec']
                part = next((s for s in parts if s.server_id == spec.key), None)
                g, power = (part.gpu, part.power) if part else (0, 0)
                values = (spec.name, f'{g} / {power}', f'{view["gpu_available"]-g} / {view["power_available"]-power}')
                rows.append((spec.key, g, power, view['gpu_available']-g, view['power_available']-power))
                for column, value in enumerate(values):
                    tk.Label(card, text=value, bg=PANEL, fg=TEXT if part else MUTED,
                             font=(FONT, 9)).grid(row=row, column=column, padx=4, pady=2)
            self.comparison_rows.append(rows)
            left_g = sum(v['gpu_available'] for v in self.views)-p['gpu']
            left_p = sum(v['power_available'] for v in self.views)-p['power']
            tk.Label(card, text=f'{len(parts)}개 서버 사용 · 전체 잔여 {left_g} / {left_p}\n배정 가능 (조회 시점)',
                     bg=PANEL, fg=CYAN, font=(FONT, 9)).grid(row=6, columnspan=3, pady=(5, 0))
        self.auto_button.configure(state='normal' if self.options else 'disabled')
        self.start_button.configure(state='normal' if self.options else 'disabled')
        self.notice.configure(text=('선택은 자원을 점유하지 않습니다. 직접 선택한 안은 슬롯까지 그대로 적용하며, 시작 직전에 다시 검사합니다.'
                                    if self.options else '배정 불가 · '+result['reason']+' · 조건을 확인한 후 다시 조회해 주세요.'),
                              fg=MUTED if self.options else RED)
        self.draw_preview()

    def draw_preview(self):
        if not hasattr(self, 'options'):
            return
        c = self.canvas
        c.delete('all')
        reset_hardware(c)
        index = self.selection.get()
        parts = self.options[max(0, index)] if self.options else ()
        width = c.winfo_width()
        if width < 100:
            return
        ink(c, 10, 7, '점유 예정 미리보기 · 테두리 = 선택 예정 / 고객 코드 = 기존 작업', 9, MUTED)
        cell = (width-20)/4
        for i, view in enumerate(self.views):
            spec = view['spec']
            part = next((s for s in parts if s.server_id == spec.key), None)
            x = 10+i*cell
            ink(c, x+4, 29, spec.name+(f' · 예정 {part.gpu}/{part.power}' if part else ' · 유지'), 10, TEXT, True)
            for slot, owner in enumerate(view['slots']):
                mx, my = x+4+(slot%2)*72, 54+(slot//2)*36
                gpu_module(c, mx, my, 64, 27, 'fault' if view['health'] != 'HEALTHY' else 'busy' if owner else 'available',
                           owner['code'] if owner else None, slot)
                if part and slot in part.gpu_slots:
                    c.create_rectangle(mx-2, my-2, mx+66, my+29, outline=CYAN, width=2,
                                       dash=(4, 2), tags=('planned-slot', f'planned-{spec.key}-{slot}'))

    def start(self):
        if not self.options:
            return
        if self.session.selected_id != self.request_id:
            self.notice.configure(text='선택한 고객 요청이 변경되었습니다. 창을 닫고 해당 요청에서 다시 열어 주세요.', fg=RED)
            self.start_button.configure(state='disabled')
            return
        index = self.selection.get()
        parts = None if index == -1 else self.options[index]
        if self.on_start(self.mode, parts):
            self.destroy()
        else:
            self.notice.configure(text='작업을 시작하지 못했습니다. 선택은 유지됩니다. [현재 자원으로 다시 확인] 후 계획을 다시 선택해 주세요.', fg=RED)
