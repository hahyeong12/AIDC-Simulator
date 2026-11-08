"""실제 완료 결과와 다음 행동을 보여 주는 Chapter 1 안내창."""
import tkinter as tk

from tkinter.scrolledtext import ScrolledText

from story import chapter2_failure_pages
from ui import BG, PANEL, CYAN, MUTED, TEXT, FONT, RED, GREEN, ActionButton, label
from story_portraits import draw_portrait
from window_placement import center_dialog


class ChapterCompleteDialog(tk.Toplevel):
    def __init__(self, parent, result, select_mode, start_free, status, review, start_chapter2=None):
        super().__init__(parent, bg=BG)
        self.title('Chapter 1 완료 · 첫 출근')
        self.withdraw()
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.result = result
        label(self, 'CHAPTER 1 COMPLETE', 21, CYAN, True).grid(row=0, sticky='w', padx=22, pady=(18, 8))
        self.congratulations = label(self, '첫 업무를 성공적으로 마쳤네요.\n처음에는 복잡해 보여도 조금씩 익숙해질 겁니다.',
                                     11, TEXT, justify='left')
        self.congratulations.grid(row=1, sticky='w', padx=22, pady=(0, 12))
        self.mentor_portrait = tk.Canvas(self, width=72, height=99, bd=0)
        self.mentor_portrait.grid(row=0, rowspan=2, sticky='ne', padx=22, pady=12)
        draw_portrait(self.mentor_portrait, 'mentor')
        self.mentor_portrait.scale('all', 0, 0, .6, .6)
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
        notice = ('다음에는 여러 고객의 요청이 동시에 들어옵니다. [Chapter 2 시작]으로 일본·미국 고객의 요청을 비교하고 서버를 배정해 보세요.\n'
                  '기존 Chapter 1 기록은 그대로 보존됩니다.' if start_chapter2 is not None else
                  '다음에는 여러 고객 요청과 네트워크 장애도 경험하게 됩니다.\nChapter 2는 이후 개발 예정입니다. 지금은 자유 운영을 이어가실 수 있습니다.')
        self.next_notice = label(self, notice, 10, MUTED, justify='left', wraplength=700)
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
        if start_chapter2 is not None:
            button = ActionButton(buttons, 'Chapter 2 시작 · 여러 고객 요청', start_chapter2)
            button.grid(row=2, column=0, columnspan=2, sticky='ew', padx=4, pady=4)
            self.buttons['chapter2'] = button
        center_dialog(self, parent, size=(760, 610), minimum=(700, 550))


class Chapter2CompleteDialog(tk.Toplevel):
    """Chapter 2 실제 결과. 두 고객의 결과·배정 위치·반환 자원과 다음 행동을 보여 줍니다."""
    def __init__(self, parent, result, select_mode, start_free, status, review, retry=None):
        super().__init__(parent, bg=BG)
        self.withdraw()
        success = result.get('mission') == 'success'
        self.title('Chapter 2 '+('성공' if success else '실패')+' · 여러 고객의 요청과 서버 배정')
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.result = result
        # 스토리가 끝난 것과 미션에 성공한 것은 별개입니다. 두 고객 모두 기한 내 정상 처리했을 때만 성공입니다.
        self.verdict = label(self, 'CHAPTER 2 SUCCESS' if success else 'CHAPTER 2 FAILED', 21, GREEN if success else RED, True)
        self.verdict.grid(row=0, sticky='w', padx=22, pady=(18, 8))
        lines = ['미션 성공 · 두 고객의 요청을 모두 기한 내에 정상 처리했습니다.' if success else
                 '미션 실패 · 두 고객의 요청을 모두 기한 내에 정상 처리하지 못했습니다.']
        if result.get('overall') is not None:
            lines.append(f'Chapter 2 종합 평가: {result["overall"]:g}/100 (두 고객 점수의 평균 · 미처리·실패 고객은 0점)')
        if not success and result.get('failure'):
            lines.append('실패 원인\n'+'\n'.join('· '+page.text for page in chapter2_failure_pages(result['failure'])[:-2]))
        for job in result['jobs']:
            deadline = '기한 내' if job['on_time'] is True else '기한 초과' if job['on_time'] is False else '기한 평가 없음'
            earned = f'미션 평가 {job["eval_score"]}점' if job.get('eval_score') is not None else '미션 평가 미확정'
            lines.append(f'{job["country"]} · {job["company"]} — {job["task"]}\n'
                         f'  결과: {job["outcome"]} · {earned} · {deadline}\n'
                         f'  운영 모드: {job["mode"]} · GPU {job["gpu"]} / 전력 {job["power"]} 사용 후 반환\n'
                         f'  배정 위치: {job["placement"]}')
        ran = sum(1 for job in result['jobs'] if job['started'] is not None)
        lines.append('두 작업은 같은 서버 원장을 나누어 쓰며 실행 시간이 겹쳤습니다.' if result['concurrent'] else
                     '두 작업은 실행 시간이 겹치지 않아 먼저 끝난 작업의 자원이 반환된 뒤 처리되었습니다.' if ran == 2 else
                     f'실제로 실행한 작업은 {ran}건입니다.')
        lines.append('서버 상태: '+' / '.join(f'{key} {value}' for key, value in result['servers'].items()))
        if result.get('decisions'):
            lines.append('주요 운영 결정과 기록\n'+'\n'.join('· '+line for line in result['decisions']))
        if result.get('practice'):
            lines.append('이 기록은 Chapter 2 연습 슬롯의 것이며 Chapter 1 진행·점수와 별개입니다.')
        self.full_text = '\n\n'.join(lines)
        self.summary = ScrolledText(self, wrap='word', height=15, font=(FONT, 10), bg=PANEL, fg=TEXT, bd=0, padx=12, pady=10)
        self.summary.insert('1.0', self.full_text)
        self.summary.configure(state='disabled')
        self.summary.grid(row=1, sticky='nsew', padx=22)
        self.rowconfigure(1, weight=1)
        label(self, '다음 단계에서는 네트워크 장애와 고객 협상을 더 깊이 다룹니다. 다시 도전하면 새 슬롯에서 처음부터 시작하며 이 기록은 그대로 보존됩니다.',
              10, MUTED, justify='left', wraplength=700).grid(row=2, sticky='w', padx=22, pady=12)
        buttons = tk.Frame(self, bg=BG)
        buttons.grid(row=3, sticky='ew', padx=22, pady=(0, 12))
        buttons.columnconfigure((0, 1), weight=1)
        self.buttons = {}
        for index, (key, text, command) in enumerate((
            ('modes', '모드 선택 화면으로', select_mode), ('free', '자유 운영 모드 시작', start_free),
            ('status', '스토리 진행 현황', status), ('review', '교육 내용 다시 보기', review))):
            button = ActionButton(buttons, text, command)
            button.grid(row=index//2, column=index%2, sticky='ew', padx=4, pady=4)
            self.buttons[key] = button
        if retry is not None:
            button = ActionButton(buttons, 'Chapter 2 다시 도전 · 새 슬롯에서 처음부터', retry)
            button.grid(row=2, column=0, columnspan=2, sticky='ew', padx=4, pady=4)
            self.buttons['retry'] = button
        center_dialog(self, parent, size=(760, 700), minimum=(700, 600))
