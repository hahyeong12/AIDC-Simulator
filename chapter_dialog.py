"""실제 완료 결과와 다음 행동을 보여 주는 Chapter 1·2 결과창.

v0.9-2b 원칙: 결과는 요약표로 먼저, 설명은 아래에, 고객 반응은 실제 결과에 맞게.
표시 값은 모두 session.chapter_result()/chapter2_result()가 실제 기록에서 계산한 것이며 이 창은 읽기 전용입니다.
"""
import tkinter as tk

from tkinter.scrolledtext import ScrolledText

from story import chapter2_failure_pages
from ui import BG, PANEL, CYAN, MUTED, TEXT, FONT, RED, GREEN, ActionButton, label
from story_portraits import draw_portrait
from scroll_area import ScrollArea
from window_placement import center_dialog


def _mentor_box(parent, title, lines):
    """선배 초상화와 짧은 분석 문장을 PANEL 박스로 묶어 반환합니다."""
    box = tk.Frame(parent, bg=PANEL)
    box.columnconfigure(1, weight=1)
    portrait = tk.Canvas(box, width=44, height=60, bd=0, highlightthickness=0)
    portrait.grid(row=0, column=0, sticky='n', padx=8, pady=6)
    draw_portrait(portrait, 'mentor')
    portrait.scale('all', 0, 0, .37, .37)
    text = label(box, title+'\n'+'\n'.join('· '+line for line in lines), 10, TEXT, justify='left', anchor='w', wraplength=640)
    text.grid(row=0, column=1, sticky='w', padx=6, pady=6)
    box.bind('<Configure>', lambda e: text.configure(wraplength=max(300, e.width-90)))
    return box, portrait, text


class ChapterCompleteDialog(tk.Toplevel):
    def __init__(self, parent, result, select_mode, start_free, status, review, start_chapter2=None):
        super().__init__(parent, bg=BG)
        self.title('Chapter 1 완료 · 첫 출근 · MISSION SUCCESS')
        self.withdraw()
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.result = result
        top = tk.Frame(self, bg=BG)
        top.grid(row=0, sticky='ew', padx=22, pady=(14, 6))
        top.columnconfigure(0, weight=1)
        label(top, 'CHAPTER 1 · 첫 출근', 9, MUTED).grid(row=0, sticky='w')
        self.verdict = label(top, 'MISSION SUCCESS', 22, GREEN, True)
        self.verdict.grid(row=1, sticky='w')
        self.congratulations = label(top, '첫 업무를 성공적으로 마쳤네요. 처음에는 복잡해 보여도 조금씩 익숙해질 겁니다.',
                                     10, TEXT, justify='left', wraplength=560)
        self.congratulations.grid(row=2, sticky='w')
        deadline = '기한 내 완료' if result['on_time'] is True else '기한 초과' if result['on_time'] is False else '기한 평가 제외'
        self.full_text = (f'첫 번째 고객 업무를 완료했습니다.\n'
                          f'고객: {result["company"]}\n작업: {result["task"]}\n'
                          f'운영 점수: {result["score"]}점 · 완료 기한: {deadline}\n'
                          f'반환 GPU: {result["gpu"]}개 · 반환 전력: {result["power"]}단위\n'
                          + '서버 상태: '+' / '.join(f'{key} {value}' for key, value in result['servers'].items())
                          + f'\n고객 완료 안내: {result["feedback"]}')
        # 결과 요약표를 먼저, 선배 설명은 그 아래에 둡니다.
        # 가운데만 스크롤하고 아래 버튼 영역은 항상 보이게 합니다(v0.9-2b-1).
        self.scroll = ScrollArea(self)
        self.scroll.grid(row=1, sticky='nsew')
        self.rowconfigure(1, weight=1)
        body = self.scroll.body
        self.summary = tk.Frame(body, bg=PANEL)
        self.summary.grid(row=0, sticky='ew', padx=22)
        self.summary.columnconfigure(1, weight=1)
        self.summary_cells = {}
        for index, (name, value) in enumerate(result.get('summary', [])):
            label(self.summary, name, 10, MUTED, anchor='w').grid(row=index, column=0, sticky='w', padx=(12, 18), pady=2)
            cell = label(self.summary, value, 11, GREEN if name == '운영 점수' else TEXT, True, anchor='w')
            cell.grid(row=index, column=1, sticky='w', pady=2)
            self.summary_cells[name] = cell
        box, self.mentor_portrait, self.mentor_note = _mentor_box(body, '[선배 엔지니어]', [
            '고객 요청을 확인하고, 서버를 고르고, 모드를 정해 시작한 것이 첫 업무의 전체 흐름입니다.',
            '완료되면 쓰던 GPU와 전력이 서버로 돌아옵니다. 앞으로 모든 업무의 기본이 됩니다.'])
        box.grid(row=1, sticky='ew', padx=22, pady=(10, 0))
        self.customer_reply = label(body, '고객 안내 · '+str(result['feedback']), 9, MUTED, justify='left', wraplength=700)
        self.customer_reply.grid(row=2, sticky='w', padx=22, pady=(6, 0))
        notice = ('다음에는 여러 고객의 요청이 동시에 들어옵니다. [Chapter 2 시작]으로 일본·미국 고객의 요청을 비교하고 서버를 배정해 보세요.\n'
                  '기존 Chapter 1 기록은 그대로 보존됩니다.' if start_chapter2 is not None else
                  '다음에는 여러 고객 요청과 네트워크 장애도 경험하게 됩니다.\nChapter 2는 이후 개발 예정입니다. 지금은 자유 운영을 이어가실 수 있습니다.')
        self.next_notice = label(body, notice, 10, MUTED, justify='left', wraplength=700)
        self.next_notice.grid(row=3, sticky='w', padx=22, pady=8)
        buttons = tk.Frame(self, bg=BG)
        buttons.grid(row=2, sticky='ew', padx=22, pady=(6, 10))
        buttons.columnconfigure((0, 1), weight=1)
        self.buttons = {}
        for index, (key, text, command) in enumerate((
            ('modes', '모드 선택 화면으로', select_mode), ('free', '자유 운영 모드 시작', start_free),
            ('status', '스토리 진행 현황', status), ('review', '교육 내용 다시 보기', review))):
            button = ActionButton(buttons, text, command)
            button.grid(row=index//2, column=index%2, sticky='ew', padx=4, pady=2)
            self.buttons[key] = button
        if start_chapter2 is not None:
            button = ActionButton(buttons, 'Chapter 2 시작 · 여러 고객 요청', start_chapter2)
            button.grid(row=2, column=0, columnspan=2, sticky='ew', padx=4, pady=2)
            self.buttons['chapter2'] = button
        center_dialog(self, parent, size=(760, 580), minimum=(640, 400))


class Chapter2CompleteDialog(tk.Toplevel):
    """Chapter 2 실제 결과. 미션 성공/실패와 종합 점수, 고객별 표, 선배 분석을 먼저 보여 주고 긴 기록은 접어 둡니다."""
    def __init__(self, parent, result, select_mode, start_free, status, review, retry=None):
        super().__init__(parent, bg=BG)
        self.withdraw()
        success = result.get('mission') == 'success'
        self.title('Chapter 2 '+('성공' if success else '실패')+' · 여러 고객의 요청과 서버 배정')
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.result = result
        summary = result.get('summary') or {}
        # 스토리가 끝난 것과 미션에 성공한 것은 별개입니다. 두 고객 모두 기한 내 정상 처리했을 때만 성공입니다.
        lines = ['미션 성공 · 두 고객의 요청을 모두 기한 내에 정상 처리했습니다.' if success else
                 '미션 실패 · 두 고객의 요청을 모두 기한 내에 정상 처리하지 못했습니다.']
        if result.get('overall') is not None:
            lines.append(f'Chapter 2 종합 평가: {result["overall"]:g}/100 (두 고객 점수의 평균 · 미처리·실패 고객은 0점)')
        if not success and result.get('failure'):
            lines.append('실패 원인\n'+'\n'.join('· '+page.text for page in chapter2_failure_pages(result['failure'])[:-2]))
        if success and result.get('highlights'):
            lines.append('기한을 지킨 방법\n'+'\n'.join('· '+line for line in result['highlights']))
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

        top = tk.Frame(self, bg=BG)
        top.grid(row=0, sticky='ew', padx=22, pady=(12, 4))
        top.columnconfigure(0, weight=1)
        label(top, 'CHAPTER 2 · 여러 고객의 요청과 서버 배정', 9, MUTED).grid(row=0, column=0, sticky='w')
        self.verdict = label(top, 'MISSION SUCCESS' if success else 'MISSION FAILED', 22, GREEN if success else RED, True)
        self.verdict.grid(row=1, column=0, sticky='w')
        overall = result.get('overall')
        self.score_label = label(top, f'{overall:g}' if overall is not None else '미확정', 30, CYAN, True)
        self.score_label.grid(row=0, column=1, rowspan=2, sticky='e', padx=6)
        label(top, '종합 점수 / 100', 9, MUTED).grid(row=2, column=1, sticky='e', padx=6)
        note = summary.get('verdict', '')
        if not success and overall is not None:
            note += ' · 종합 점수와 별개로 한 고객이라도 기한 내 정상 완료하지 못하면 미션은 실패입니다.'
        self.verdict_note = label(top, note, 10, TEXT, anchor='w', justify='left', wraplength=560)
        self.verdict_note.grid(row=2, column=0, sticky='w')

        self.scroll = ScrollArea(self)
        self.scroll.grid(row=1, sticky='nsew')
        self.rowconfigure(1, weight=1)
        body = self.scroll.body
        stats = tk.Frame(body, bg=PANEL)
        stats.grid(row=1, sticky='ew', padx=22, pady=(4, 6))
        stats.columnconfigure(1, weight=1)
        self.stats = {}
        for index, (name, value) in enumerate((('성공 고객', f'{summary.get("ok", 0)} / {summary.get("total", 2)}'),
                                              ('운영 전략', summary.get('strategy', '')), ('배정', summary.get('arrangement', '')),
                                              ('자원', summary.get('resources', '')))):
            label(stats, name, 9, MUTED, anchor='w').grid(row=index, column=0, sticky='w', padx=(10, 14), pady=1)
            self.stats[name] = label(stats, value, 10, TEXT, True, anchor='w')
            self.stats[name].grid(row=index, column=1, sticky='w', pady=1)

        table = tk.Frame(body, bg=PANEL)
        table.grid(row=2, sticky='ew', padx=22)
        for column, weight in enumerate((2, 2, 3, 2, 2)):
            table.columnconfigure(column, weight=weight)
        for column, name in enumerate(('고객', '운영 모드', '결과', '기한', '점수')):
            label(table, name, 9, MUTED, True, anchor='w').grid(row=0, column=column, sticky='w', padx=8, pady=(4, 2))
        self.table_cells = []
        for row, job in enumerate(result['jobs'], start=1):
            ok = job.get('state') == 'success'
            if job.get('eval_score') is None:
                score = '미확정'
            else:
                score = f'{job["eval_score"]}점' + ('' if ok else ' (미션 평가)')
            cells = (job['country'], job['mode'], job['outcome'], job.get('deadline', ''), score)
            row_cells = []
            for column, text in enumerate(cells):
                color = (GREEN if ok else RED) if column in (2, 3) else TEXT
                cell = label(table, text, 10, color, column in (0, 4), anchor='w', wraplength=170, justify='left')
                cell.grid(row=row, column=column, sticky='w', padx=8, pady=3)
                row_cells.append(cell)
            self.table_cells.append(row_cells)

        self.key_decisions = label(body, '주요 운영 결정\n· 전략: '+summary.get('strategy', '')+'\n· 배정: '+summary.get('arrangement', '')
                                   + '\n· 자원: '+summary.get('resources', '')+'\n· 결과: '+summary.get('verdict', '')
                                   + '\n· 평가: '+('미션 성공' if success else '미션 실패'),
                                   10, TEXT, justify='left', anchor='w')
        self.key_decisions.grid(row=3, sticky='w', padx=22, pady=(8, 2))

        analysis = ([page.text for page in chapter2_failure_pages(result['failure'])[:-2]][:4] if (not success and result.get('failure'))
                    else list(result.get('highlights') or [])[:4])
        self.mentor_lines = analysis or ['분석할 실패·성공 기록이 없습니다.']
        box, self.mentor_portrait, self.mentor_label = _mentor_box(body, '[선배 엔지니어의 분석]', self.mentor_lines)
        box.grid(row=4, sticky='ew', padx=22, pady=(6, 2))

        self.detail_shown = False
        self.detail_button = ActionButton(body, '상세 기록 보기 ▼', self.toggle_detail)
        self.detail_button.grid(row=5, sticky='w', padx=22, pady=(6, 2))
        self.summary = ScrolledText(body, wrap='word', height=9, font=(FONT, 10), bg=PANEL, fg=TEXT, bd=0, padx=12, pady=10)
        self.summary.insert('1.0', self.full_text)
        self.summary.configure(state='disabled')

        buttons = tk.Frame(self, bg=BG)
        buttons.grid(row=2, sticky='ew', padx=22, pady=(6, 10))
        buttons.columnconfigure((0, 1, 2, 3), weight=1)
        self.buttons = {}
        for index, (key, text, command) in enumerate((
            ('modes', '모드 선택 화면으로', select_mode), ('free', '자유 운영 모드 시작', start_free),
            ('status', '스토리 진행 현황', status), ('review', '교육 내용 다시 보기', review))):
            button = ActionButton(buttons, text, command)
            button.grid(row=0, column=index, sticky='ew', padx=3, pady=2)
            self.buttons[key] = button
        if retry is not None:
            button = ActionButton(buttons, 'Chapter 2 다시 도전 · 새 슬롯에서 처음부터 (현재 기록은 보존)', retry)
            button.grid(row=1, column=0, columnspan=4, sticky='ew', padx=3, pady=2)
            self.buttons['retry'] = button
        center_dialog(self, parent, size=(820, 640), minimum=(640, 400))

    def toggle_detail(self):
        """긴 서버별 배정·대기 기록은 접어 두었다가 필요할 때만 펼칩니다. 조회 전용이며 게임 상태를 바꾸지 않습니다."""
        self.detail_shown = not self.detail_shown
        if self.detail_shown:
            self.summary.grid(row=6, sticky='nsew', padx=22)
            self.detail_button.configure(text='상세 기록 접기 ▲')
        else:
            self.summary.grid_remove()
            self.detail_button.configure(text='상세 기록 보기 ▼')
