"""v0.9-4a 공통 UI 구성요소(점진 도입용). 기존 Chapter 화면은 바꾸지 않고 새 화면부터 사용합니다.

원칙: 상태는 색상만이 아니라 아이콘·텍스트로도 구분하고(정상/장애/복구/완료를 일관되게), 중요한 값은 큰 게이지로,
기본 행동은 배경·테두리·대비가 분명한 버튼으로 표시합니다. 게임 상태를 바꾸지 않는 순수 표시 도구입니다.
"""
import tkinter as tk

from ui import BG, PANEL, RAISED, BORDER, TEXT, MUTED, CYAN, BLUE, GREEN, RED, AMBER, FONT

MONO = 'Consolas'
# tone -> (색, 아이콘, 기본 문구). 아이콘은 Windows 기본 글꼴에서 보이는 단순 기호만 사용합니다.
TONES = {
    'ok': (GREEN, '●', '정상'), 'fault': (RED, '▲', '장애'), 'recover': (BLUE, '◐', '복구 중'),
    'done': (CYAN, '■', '완료'), 'failed': (RED, '✕', '실패'), 'idle': (MUTED, '○', '대기'),
    'warn': (AMBER, '▲', '주의'),
}
HEALTH_TONES = {'HEALTHY': 'ok', 'FAULT': 'fault', 'REPAIRING': 'recover'}


def tone_color(tone):
    return TONES.get(tone, TONES['idle'])[0]


def chip_text(tone, text=None):
    _, icon, default = TONES.get(tone, TONES['idle'])
    return f'{icon} {text or default}'


class StatusChip(tk.Label):
    """테두리가 있는 상태 표시. set(tone, text)로 갱신합니다."""
    def __init__(self, parent, tone='idle', text=None, size=10):
        super().__init__(parent, bg=RAISED, font=(FONT, size, 'bold'), padx=8, pady=3,
                         highlightthickness=1, bd=0)
        self.set(tone, text)

    def set(self, tone, text=None):
        color = tone_color(tone)
        self.tone = tone
        self.configure(text=chip_text(tone, text), fg=color, highlightbackground=color)


class Gauge(tk.Canvas):
    """제목·큰 값·막대로 이루어진 게이지. set(value, maximum, text, tone)."""
    def __init__(self, parent, title, height=64, bar=12):
        super().__init__(parent, height=height, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, bd=0)
        self.title, self.bar = title, bar
        self.value = self.maximum = 0
        self.text, self.caption, self.tone = '', '', 'idle'
        self.bind('<Configure>', lambda _: self.draw())

    def set(self, value, maximum, text=None, tone='ok', caption=''):
        self.value, self.maximum = value, maximum
        self.text = text if text is not None else f'{value}/{maximum}'
        self.tone, self.caption = tone, caption
        self.draw()

    def draw(self):
        self.delete('all')
        width, height = max(self.winfo_width(), 160), max(self.winfo_height(), 40)
        color = tone_color(self.tone)
        self.create_text(12, 10, text=self.title, anchor='nw', fill=MUTED, font=(FONT, 9, 'bold'), tags='title')
        self.create_text(width-12, 6, text=self.text, anchor='ne', fill=color, font=(FONT, 15, 'bold'), tags='value')
        top = height-self.bar-10
        self.create_rectangle(12, top, width-12, top+self.bar, fill=BG, outline=BORDER, tags='track')
        ratio = 0 if not self.maximum else max(0, min(1, self.value/self.maximum))
        if ratio:
            self.create_rectangle(12, top, 12+(width-24)*ratio, top+self.bar, fill=color, outline=color, tags='fill')
        if self.caption:
            self.create_text(12, top-4, text=self.caption, anchor='sw', fill=MUTED, font=(FONT, 8), tags='caption')


class PrimaryButton(tk.Button):
    """화면의 기본 행동. 일반 ActionButton보다 배경·테두리 대비가 강합니다.
    strong=True(v0.9-4a-2): 화면에서 지금 눌러야 할 단 하나의 행동. 밝은 청록 배경 + 어두운 글자 + 큰 글꼴."""
    def __init__(self, parent, text, command, strong=False, **kwargs):
        self.base_bg, hover = ('#38d9d0', '#7ae8e1') if strong else ('#14414a', '#1d5d68')
        super().__init__(parent, text=text, command=command, bg=self.base_bg, fg=BG if strong else TEXT,
                         activebackground=hover, activeforeground=BG if strong else TEXT,
                         disabledforeground=MUTED, relief='flat', bd=0,
                         highlightthickness=2, highlightbackground=CYAN, highlightcolor=CYAN,
                         font=(FONT, 12 if strong else 10, 'bold'), padx=18 if strong else 12, pady=9 if strong else 7,
                         cursor='hand2', **kwargs)
        self.bind('<Enter>', lambda _: self.configure(bg=hover) if self.cget('state') != 'disabled' else None)
        self.bind('<Leave>', lambda _: self.configure(bg=self.base_bg))


class ToggleButton(tk.Button):
    """탭처럼 하나만 선택되는 버튼(선택 상태는 테두리와 글자색, ▶ 기호로 함께 표시)."""
    def __init__(self, parent, text, command, **kwargs):
        self.base_text = text
        super().__init__(parent, text=text, command=command, bg=RAISED, fg=MUTED, activebackground=BORDER,
                         activeforeground=TEXT, relief='flat', bd=0, highlightthickness=2, highlightbackground=BORDER,
                         font=(FONT, 10, 'bold'), padx=10, pady=6, cursor='hand2', **kwargs)

    def set_selected(self, selected):
        self.selected = selected
        self.configure(text=('▶ ' if selected else '')+self.base_text, fg=CYAN if selected else MUTED,
                       highlightbackground=CYAN if selected else BORDER)
