"""서버 배정 비교 창. 확정 전까지는 원장과 DB를 변경하지 않습니다."""
import tkinter as tk

from server_resources import SERVERS
from server_console import server_views
from window_placement import center_dialog
from server_widgets import (BG, PANEL, EDGE, TEXT, MUTED, CYAN, RED, FONT,
                            gpu_module, reset_hardware, ink)


class AllocationDialog(tk.Toplevel):
    def __init__(self, parent, session, mode, on_start, migration=False, on_review=None, on_reload=None):
        super().__init__(parent)
        self.session, self.mode, self.on_start = session, mode, on_start
        self.on_review, self.on_reload = on_review, on_reload
        self.request_id = session.selected_id
        self.migration = migration
        self.title(('작업 이전 계획' if migration else '서버 배정 계획 비교')+' · v0.9-1e')
        self.configure(bg=BG)
        self.transient(parent)
        self.geometry('940x590')
        self.minsize(880, 560)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.selection = tk.IntVar(value=-1)
        self.heading = tk.Label(self, bg=BG, fg=TEXT, font=(FONT, 11, 'bold'), anchor='w', justify='left')
        self.heading.grid(row=0, sticky='ew', padx=14, pady=(12, 4))
        self.auto_button = tk.Radiobutton(self, text='자동 추천 · 시작 시 현재 자원으로 다시 계산',
                                         variable=self.selection, value=-1, command=self.user_select,
                                         bg=BG, fg=CYAN, selectcolor=PANEL, activebackground=BG,
                                         activeforeground=CYAN, font=(FONT, 10), anchor='w')
        self.auto_button.grid(row=1, sticky='ew', padx=12)
        if migration:
            self.auto_button.grid_remove()
        self.cards = tk.Frame(self, bg=BG)
        self.cards.grid(row=2, sticky='ew', padx=12, pady=6)
        self.canvas = tk.Canvas(self, bg=PANEL, height=110, highlightthickness=1, highlightbackground=EDGE)
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
        center_dialog(self, parent, size=(940, 600), minimum=(880, 570))
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
        self.plan_cards = []
        self.card_captions = []
        self.previous_parts = None
        self.change_text = ''
        self.comparison_rows = []
        for i, parts in enumerate(self.options):
            self.cards.columnconfigure(i, weight=1, uniform='plans')
            card = tk.Frame(self.cards, bg=PANEL, highlightthickness=3, highlightbackground=EDGE, padx=5, pady=4,
                            cursor='hand2', takefocus=True)
            self.plan_cards.append(card)
            card.grid(row=0, column=i, sticky='nsew', padx=3)
            radio = tk.Radiobutton(card, text=self.plan_title(i), variable=self.selection, value=i,
                                   command=self.user_select, bg=PANEL, fg=CYAN, selectcolor=BG,
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
            caption = tk.Label(card, text=self.caption(i, parts), bg=PANEL, fg=CYAN, font=(FONT, 9),
                               justify='left', anchor='w', wraplength=270)
            caption.grid(row=6, columnspan=3, pady=(5, 0), sticky='w')
            self.card_captions.append(caption)
            for widget in (card, *card.winfo_children()):
                # Radio의 기본 클릭/키보드 동작은 유지합니다.
                if widget is not radio:
                    widget.bind('<Button-1>', lambda _, n=i: self.select_card(n))
                widget.bind('<Enter>', lambda _, n=i: self.paint_cards(n), add='+')
                widget.bind('<Leave>', lambda _: self.paint_cards(), add='+')
                widget.configure(cursor='hand2')
            card.bind('<Return>', lambda _, n=i: self.select_card(n))
            card.bind('<space>', lambda _, n=i: self.select_card(n))
            card.bind('<Left>', lambda _, n=i: self.select_card((n-1) % len(self.options), focus=True))
            card.bind('<Right>', lambda _, n=i: self.select_card((n+1) % len(self.options), focus=True))
        self.auto_button.configure(state='normal' if self.options else 'disabled')
        if self.options and not self.migration and len(self.options) == 1:
            self.heading.configure(text=self.heading.cget('text')+'\n이 조건에서 의미 있게 구별되는 배정안은 하나뿐입니다.')
        self.start_button.configure(state='normal' if self.options else 'disabled')
        self.notice.configure(text=('선택은 자원을 점유하지 않습니다. 직접 선택한 안은 슬롯까지 그대로 적용하며, 시작 직전에 다시 검사합니다.'
                                    if self.options else '배정 불가 · '+result['reason']+' · 조건을 확인한 후 다시 조회해 주세요.'),
                              fg=MUTED if self.options else RED)
        self.draw_preview()
        if self.on_reload is not None:
            self.on_reload()

    def plan_title(self, index):
        name = '이전안' if self.migration else '배정안'
        return f'{name} {index+1}'+(' (추천)' if index == 0 else '')

    def caption(self, index, parts):
        """실제 원장 수치로만 특징을 설명합니다. 성능/안정성 효과는 주장하지 않습니다."""
        lefts = [{v['spec'].key:(v['gpu_available']-next((s.gpu for s in o if s.server_id == v['spec'].key), 0),
                                 v['power_available']-next((s.power for s in o if s.server_id == v['spec'].key), 0))
                  for v in self.views} for o in self.options]
        total_g = sum(g for g, _ in lefts[index].values())
        total_p = sum(p for _, p in lefts[index].values())
        lines = [f'{len(parts)}개 서버 사용 · 전체 잔여 GPU {total_g} / 전력 {total_p}']
        counts = [len(o) for o in self.options]
        if len(set(counts)) > 1 and len(parts) == min(counts):
            lines.append('특징: 사용 서버 수가 가장 적음')
        elif len(set(counts)) > 1 and len(parts) == max(counts):
            lines.append('특징: 여러 서버에 나누어 배정')
        biggest = max(sorted(lefts[index].items()), key=lambda kv: kv[1][0])
        lines.append(f'남는 GPU 최대: Server {biggest[0]} {biggest[1][0]}개')
        if not self.migration:
            if index == 0:
                lines.append('자동 추천과 같은 배분')
            else:
                base = {s.server_id:s for s in self.options[0]}
                diff = []
                for server in SERVERS:
                    new = next((s for s in parts if s.server_id == server.key), None)
                    g = (new.gpu if new else 0)-(base[server.key].gpu if server.key in base else 0)
                    if g:
                        diff.append(f'{server.key} {g:+d}')
                if diff:
                    lines.append('추천안 대비 GPU: '+', '.join(diff))
        return '\n'.join(lines)

    def user_select(self):
        """라디오/카드로 계획을 직접 고른 사용자 행동. 화면 갱신 뒤에만 검토 확인을 알립니다."""
        self.draw_preview()
        if self.on_review is not None and not self.migration:
            self.on_review()

    def select_card(self, index, focus=False):
        self.selection.set(index)
        if focus:
            self.plan_cards[index].focus_set()
        self.user_select()

    def paint_cards(self, hover=None):
        for index, card in enumerate(self.plan_cards):
            selected = self.selection.get() == index
            bg = '#253746' if selected else '#182a3b' if hover == index else PANEL
            card.configure(bg=bg, highlightbackground='#ffe08a' if selected else '#91a7c1' if hover == index else EDGE)
            for widget in card.winfo_children():
                widget.configure(bg=bg)
            self.plan_buttons[index].configure(text=self.plan_title(index)+
                                                (' · 선택 중 ✓' if selected else ' · 클릭하여 선택'))

    def update_selection(self, parts):
        self.paint_cards()
        if self.previous_parts is not None and parts != self.previous_parts:
            changes = []
            for server in SERVERS:
                old = next((p for p in self.previous_parts if p.server_id == server.key), None)
                new = next((p for p in parts if p.server_id == server.key), None)
                g = (new.gpu if new else 0)-(old.gpu if old else 0)
                power = (new.power if new else 0)-(old.power if old else 0)
                if g or power:
                    changes.append(f'Server {server.key} '+', '.join(text for text in
                                   (f'GPU {g:+d}' if g else '', f'전력 {power:+d}' if power else '') if text))
            self.change_text = '이전 선택 대비: '+(' / '.join(changes) if changes else 'GPU 슬롯 위치 변경')
        self.previous_parts = parts
        if not hasattr(self, 'change_label'):
            self.change_label = tk.Label(self.notice.master, bg=BG, fg='#ffe08a', font=(FONT, 9),
                                         anchor='w', justify='left', wraplength=880)
            self.change_label.grid(row=2, columnspan=3, sticky='ew', pady=(4, 0))
        self.change_label.configure(text=self.change_text)

    def draw_preview(self):
        if not hasattr(self, 'options'):
            return
        c = self.canvas
        c.delete('all')
        reset_hardware(c)
        index = self.selection.get()
        parts = self.options[max(0, index)] if self.options else ()
        self.update_selection(parts)
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
                    c.create_rectangle(mx-3, my-3, mx+67, my+30, outline='#ffe08a', width=3,
                                       tags=('planned-slot', f'planned-{spec.key}-{slot}'))
                    c.create_rectangle(mx-5, my-5, mx+69, my+32, outline='#a97d31', width=1, tags='planned-glow')

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
