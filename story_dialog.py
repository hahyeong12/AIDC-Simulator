"""짧은 사건별 교육 대화와 주제 선택 복습. 고객 메신저와 별도 UI."""
import tkinter as tk
from tkinter import ttk

from story import GUIDES, STEPS, SPEAKERS
from story_portraits import draw_portrait
from ui import BG, MUTED, CYAN, MessageDialog, label, ActionButton


class StoryDialogueDialog(MessageDialog):
    def __init__(self, parent, pages, confirm=None, portrait_renderer=draw_portrait):
        self.portrait_renderer = portrait_renderer
        self.portraits = {}
        super().__init__(parent, '교육 담당자', '울산 AIDC 운영팀', pages,
                         animate=False, message_kind='현장 교육', confirm=confirm,
                         history_hint='교육 도움말에서 다시 보기')
        self.title('현장 교육 | 교육 담당자 · Chapter 1')
        self.geometry('820x470')
        self.minsize(740, 430)
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        header = self.grid_slaves(row=0)[0]
        header.configure(text='ULSAN AIDC   /   현장 교육')
        for row in (0, 1, 3, 4):
            for widget in self.grid_slaves(row=row):
                widget.grid_configure(columnspan=2)
        self.cast = tk.Frame(self, bg=BG)
        self.cast.grid(row=2, column=0, padx=(20, 0), sticky='n')
        for column, role in enumerate(('player', 'mentor')):
            frame = tk.Frame(self.cast, bg=BG)
            frame.grid(row=0, column=column, padx=3)
            canvas = tk.Canvas(frame, width=120, height=165, bd=0)
            canvas.pack()
            label(frame, '신입 엔지니어' if role == 'player' else '선배 엔지니어',
                  9, MUTED).pack(pady=5)
            self.portraits[role] = canvas
        self.bubble.grid_configure(column=1, padx=(12, 20))
        self.skip_button.configure(text='마지막 안내')
        self.close_button = ActionButton(self.next_button.master, '업무로 돌아가기', self.destroy)
        self.close_button.pack(side='right', padx=6)
        self.render()

    def render(self):
        super().render()
        speaker = self.steps[self.index][0]
        self.active_role = next((role for role, name in SPEAKERS.items() if name == speaker), 'system')
        for role, canvas in self.portraits.items():
            self.portrait_renderer(canvas, role, role == self.active_role)
        self.speaker.configure(fg=CYAN if self.active_role == 'player' else '#a9beff')


class StoryReviewDialog(StoryDialogueDialog):
    def __init__(self, parent):
        super().__init__(parent, [line.page() for line in GUIDES['arrival'][1]])
        self.title('교육 복습 · 장면 선택')
        header = self.grid_slaves(row=0, column=0)[0]
        header.configure(text='교육 복습')
        header.grid_configure(columnspan=1)
        self.scene_keys = STEPS
        self.scene = ttk.Combobox(self, state='readonly', width=35,
                                  values=[f'{i+1}. {GUIDES[key][0]}' for i, key in enumerate(STEPS)])
        self.scene.grid(row=0, column=1, sticky='e', padx=20)
        self.scene.current(0)
        self.scene.bind('<<ComboboxSelected>>', self.select_scene)
        self.page.configure(text='장면을 선택해 복습하세요. 업무 진행은 바뀌지 않습니다.')

    def select_scene(self, _=None):
        key = self.scene_keys[self.scene.current()]
        self.steps = [line.page() for line in GUIDES[key][1]]
        self.index = 0
        self.render()
