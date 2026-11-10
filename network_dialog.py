"""Chapter 3 화면: 네트워크 진단창과 장애 결과 카드.

진단창은 현재 작업의 실제 네트워크 상태를 읽기 전용으로 보여 주며 정답 대응은 표시하지 않습니다.
결과 카드는 성공/실패 모두 같은 구조(제목 · 원인 · 선택 대응 · 실제 결과 · 선배 한마디 · 다음 행동)입니다.
"""
import tkinter as tk

from chapter3 import RESPONSE_LABELS
from story_portraits import draw_portrait
from ui import BG, PANEL, CYAN, MUTED, TEXT, RED, GREEN, AMBER, ActionButton, label
from scroll_area import ScrollArea
from window_placement import center_dialog


class NetworkDiagnosisDialog(tk.Toplevel):
    """2열 진단표. 보통 크기에서는 스크롤 없이 보이고, 창이 내용보다 작을 때만 ScrollArea가 스크롤바를 보입니다."""
    def __init__(self, parent, diagnosis):
        super().__init__(parent, bg=BG)
        self.withdraw()
        self.title('Chapter 3 | 네트워크 진단')
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.diagnosis = d = diagnosis
        top = tk.Frame(self, bg=BG)
        top.grid(row=0, sticky='ew', padx=16, pady=(8, 2))
        label(top, 'NETWORK DIAGNOSIS', 9, MUTED).pack(anchor='w')
        self.summary_label = label(top, '장애 관측: '+d['summary'], 13, CYAN, True, anchor='w')
        self.summary_label.pack(anchor='w')

        self.scroll = ScrollArea(self)
        self.scroll.grid(row=1, sticky='nsew')
        self.rowconfigure(1, weight=1)
        table = tk.Frame(self.scroll.body, bg=PANEL)
        table.grid(row=0, sticky='ew', padx=16, pady=4)
        for column in (1, 3):
            table.columnconfigure(column, weight=1, uniform='value')
        shortage = d['link_ok'] and d['needed'] > d['available']
        backup = d['backup'].split(': ', 1)[1] if ': ' in d['backup'] else d['backup']
        tried = ' → '.join(RESPONSE_LABELS[r] for r in d['responses'])
        cells = [
            [('주 경로 상태', d['primary'], GREEN if d['primary'] == 'UP' else RED),
             ('GPU·서버', '정상' if d['equipment_ok'] else d['equipment'], GREEN if d['equipment_ok'] else RED)],
            [('필요 대역폭', str(d['needed']), TEXT),
             ('가용 대역폭', str(d['available'])+('' if d['link_ok'] else ' (경로 없음)'), AMBER if shortage or not d['link_ok'] else GREEN)],
            [('백업 경로', backup, TEXT),
             ('중단 시간', f'{d["downtime"]} / {d["limit"]}분', AMBER if d['downtime'] else TEXT)],
            [('대응 횟수', f'{d["attempts"]} / 3회'+(f' · {tried}' if tried else ''), TEXT),
             ('작업 진행률', f'{d["progress"]}%', TEXT)]]
        self.cells = {}
        for row, pair in enumerate(cells):
            for side, (name, value, color) in enumerate(pair):
                label(table, name, 9, MUTED, anchor='nw').grid(row=row, column=side*2, sticky='nw', padx=(10, 6), pady=3)
                cell = label(table, value, 11, color, True, anchor='w', justify='left', wraplength=190)
                cell.grid(row=row, column=side*2+1, sticky='w', padx=(0, 8), pady=3)
                self.cells[name] = cell
        # 이전 버전 이름도 같은 위젯으로 찾을 수 있게 둡니다.
        self.cells['주 통신 경로 상태'], self.cells['현재 가용 대역폭'], self.cells['작업 필요 대역폭'] = (
            self.cells['주 경로 상태'], self.cells['가용 대역폭'], self.cells['필요 대역폭'])
        bottom = tk.Frame(self, bg=BG)
        bottom.grid(row=2, sticky='ew', padx=16, pady=(4, 8))
        bottom.columnconfigure(0, weight=1)
        label(bottom, '현재 진단 정보를 확인했습니다.', 10, MUTED, anchor='w').grid(row=0, column=0, sticky='w')
        self.close_button = ActionButton(bottom, '진단 확인 · 대응 선택', self.destroy)
        self.close_button.grid(row=0, column=1, sticky='e')
        self.bind('<Escape>', lambda _: self.destroy())
        center_dialog(self, parent, size=(600, 340), minimum=(460, 260))


class Chapter3FeedbackDialog(tk.Toplevel):
    """장애 결과 카드(FEEDBACK). actions: [(버튼 문구, 명령)]. 닫기는 항상 가능합니다."""
    def __init__(self, parent, card, actions=()):
        super().__init__(parent, bg=BG)
        self.withdraw()
        self.card = card
        self.title('FEEDBACK · Chapter 3 · '+card['title'])
        self.transient(parent)
        self.columnconfigure(1, weight=1)
        color = {'success': GREEN, 'fail': RED, 'warn': AMBER}[card['tone']]
        self.heading = label(self, card['title'], 15, color, True, anchor='w')
        self.heading.grid(row=0, columnspan=2, sticky='w', padx=16, pady=(10, 4))
        table = tk.Frame(self, bg=PANEL)
        table.grid(row=1, columnspan=2, sticky='ew', padx=16)
        table.columnconfigure(1, weight=1)
        self.cells = {}
        for row, (name, value) in enumerate(card['rows']):
            label(table, name, 10, MUTED, anchor='w').grid(row=row, column=0, sticky='w', padx=(10, 14), pady=2)
            self.cells[name] = label(table, value, 11, TEXT, True, anchor='w', justify='left', wraplength=380)
            self.cells[name].grid(row=row, column=1, sticky='w', pady=2)
        self.portrait = tk.Canvas(self, width=44, height=60, bd=0, highlightthickness=0)
        self.portrait.grid(row=2, column=0, sticky='n', padx=(16, 4), pady=8)
        draw_portrait(self.portrait, 'mentor', True)
        self.portrait.scale('all', 0, 0, .37, .37)
        self.mentor_label = label(self, '선배: “'+card['mentor']+'”', 10, TEXT, justify='left', anchor='w', wraplength=440)
        self.mentor_label.grid(row=2, column=1, sticky='w', padx=(0, 16), pady=8)
        buttons = tk.Frame(self, bg=BG)
        buttons.grid(row=3, columnspan=2, sticky='e', padx=16, pady=(0, 10))
        self.buttons = {}
        for index, (text, command) in enumerate(actions):
            button = ActionButton(buttons, text, command)
            button.pack(side='left', padx=(0, 6))
            self.buttons[text] = button
        self.close_button = ActionButton(buttons, '닫기', self.destroy)
        self.close_button.pack(side='left')
        self.bind('<Escape>', lambda _: self.destroy())
        center_dialog(self, parent, size=(560, 330), minimum=(460, 280))


class HardwareDiagnosisDialog(tk.Toplevel):
    """Chapter 3b 장비 진단창. 복구/이전의 자원과 예상 시간을 표로 비교해 보여 주기만 하고, 대응을 자동 선택·실행하지 않습니다."""
    def __init__(self, parent, diagnosis):
        super().__init__(parent, bg=BG)
        self.withdraw()
        from chapter3b import diagnosis_rows
        self.title('Chapter 3b | 장비 진단')
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.diagnosis = d = diagnosis
        top = tk.Frame(self, bg=BG)
        top.grid(row=0, sticky='ew', padx=16, pady=(8, 2))
        label(top, 'HARDWARE DIAGNOSIS', 9, MUTED).pack(anchor='w')
        self.summary_label = label(top, f'장애 관측: Server {d["server"]} 장비 장애 · 고객 작업 중단', 13, CYAN, True, anchor='w')
        self.summary_label.pack(anchor='w')
        self.scroll = ScrollArea(self)
        self.scroll.grid(row=1, sticky='nsew')
        self.rowconfigure(1, weight=1)
        table = tk.Frame(self.scroll.body, bg=PANEL)
        table.grid(row=0, sticky='ew', padx=16, pady=4)
        table.columnconfigure(1, weight=1)
        self.cells = {}
        colors = {'bad': RED, 'good': GREEN, None: TEXT}
        for row, (name, value, tone) in enumerate(diagnosis_rows(d)):
            label(table, name, 9, MUTED, anchor='nw').grid(row=row, column=0, sticky='nw', padx=(10, 12), pady=2)
            cell = label(table, value, 10, colors[tone], True, anchor='w', justify='left', wraplength=400)
            cell.grid(row=row, column=1, sticky='w', pady=2)
            self.cells[name] = cell
        note = d['reason'] + ('\n'+d['advice'] if d['advice'] else '') if not d['migrate_possible'] else ''
        self.reason_label = label(self.scroll.body, note, 10, AMBER, justify='left', anchor='w', wraplength=520)
        self.reason_label.grid(row=1, sticky='w', padx=16, pady=(2, 6))
        bottom = tk.Frame(self, bg=BG)
        bottom.grid(row=2, sticky='ew', padx=16, pady=(4, 8))
        bottom.columnconfigure(0, weight=1)
        label(bottom, '현재 진단 정보를 확인했습니다.', 10, MUTED, anchor='w').grid(row=0, column=0, sticky='w')
        self.close_button = ActionButton(bottom, '진단 확인 · 대응 선택', self.destroy)
        self.close_button.grid(row=0, column=1, sticky='e')
        self.bind('<Escape>', lambda _: self.destroy())
        center_dialog(self, parent, size=(640, 470), minimum=(480, 300))
