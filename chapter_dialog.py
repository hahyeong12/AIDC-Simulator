"""실제 완료 결과와 다음 행동을 보여 주는 Chapter 1 안내창."""
import tkinter as tk

from ui import BG, PANEL, CYAN, MUTED, TEXT, ActionButton, label


class ChapterCompleteDialog(tk.Toplevel):
    def __init__(self, parent, result, select_mode, start_free, status, review):
        super().__init__(parent, bg=BG)
        self.title('Chapter 1 완료 · 첫 출근')
        self.geometry('760x530')
        self.minsize(700, 510)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.result = result
        label(self, 'CHAPTER 1 COMPLETE', 21, CYAN, True).grid(row=0, sticky='w', padx=22, pady=(18, 8))
        self.congratulations = label(self, '첫 업무를 성공적으로 마쳤네요.\n처음에는 복잡해 보여도 조금씩 익숙해질 겁니다.',
                                     11, TEXT, justify='left')
        self.congratulations.grid(row=1, sticky='w', padx=22, pady=(0, 12))
        deadline = '기한 내 완료' if result['on_time'] is True else '기한 초과' if result['on_time'] is False else '기한 평가 제외'
        self.full_text = (f'첫 번째 고객 업무를 완료했습니다.\n'
                          f'고객: {result["company"]}\n작업: {result["task"]}\n'
                          f'운영 점수: {result["score"]}점 · 완료 기한: {deadline}\n'
                          f'반환 GPU: {result["gpu"]}개 · 반환 전력: {result["power"]}단위\n'
                          + '서버 상태: '+ ' / '.join(f'{key} {value}' for key, value in result['servers'].items())
                          + f'\n고객 완료 안내: {result["feedback"]}')
        self.summary = label(self, self.full_text, 10, TEXT, justify='left', anchor='nw', wraplength=690)
        self.summary.configure(bg=PANEL, padx=12, pady=10)
        self.summary.grid(row=2, sticky='ew', padx=22)
        self.summary.bind('<Configure>', lambda e:self.summary.configure(wraplength=max(300, e.width-24)))
        self.next_notice = label(self, '다음에는 여러 고객 요청과 네트워크 장애도 경험하게 됩니다.\nChapter 2는 이후 개발 예정입니다. 지금은 자유 운영을 이어가실 수 있습니다.',
                                 10, MUTED, justify='left')
        self.next_notice.grid(row=3, sticky='w', padx=22, pady=12)
        buttons = tk.Frame(self, bg=BG)
        buttons.grid(row=4, sticky='ew', padx=22, pady=(0, 12))
        buttons.columnconfigure((0, 1), weight=1)
        self.buttons = {}
        for index, (key, text, command) in enumerate((
            ('modes', '모드 선택 화면으로', select_mode), ('free', '자유 운영 모드 시작', start_free),
            ('status', '스토리 진행 현황', status), ('review', '교육 내용 다시 보기', review))):
            button = ActionButton(buttons, text, command)
            button.grid(row=index//2, column=index%2, sticky='ew', padx=4, pady=4)
            self.buttons[key] = button
