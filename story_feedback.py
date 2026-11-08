"""실제 행동 뒤의 짧은 비모달 결과 안내. 확인은 업무 상태를 변경하지 않습니다."""
import tkinter as tk

from story_portraits import draw_portrait
from ui import BG, TEXT, MUTED, FONT, ActionButton, label
from window_placement import place_near


FEEDBACK = {
    'server': ('Server A 선택 완료', '좋아요! Server A를 선택했네요. 이제 오른쪽 GPU와 전력 정보를 살펴보세요.'),
    'resources': ('자원 정보 확인 완료', 'GPU와 전력을 확인했네요. 이제 고객이 요청한 조건과 완료 기한을 읽어 봅시다.'),
    'request': ('고객 요청 확인 완료', '잘하셨어요. GPU와 전력뿐 아니라 고객의 완료 기한도 확인해야 합니다.'),
    'preview': ('배정 계획 확인 완료', '계획을 검토했네요. 아직 자원은 점유하지 않았습니다. 조건에 맞는 계획으로 실제 작업을 시작하세요.'),
    'allocation': ('작업 시작 완료', 'GPU가 실제로 배정됐네요. SG 표시와 전력 사용량을 확인해 보세요.'),
    'time': ('작업량 증가 확인', '작업 진행률이 증가했습니다. 예상 완료 시각과 고객 기한을 비교해 보세요.'),
    'operations': ('운영 상태 확인 완료', '운영 정보를 확인했네요. 시간 버튼으로 첫 고객 업무를 정상 완료해 봅시다.'),
    'c2_briefing': ('브리핑 확인 완료', '좋아요. 이제 AIDC LINK에서 일본·미국 두 요청서를 하나씩 열어 GPU·전력·완료 기한을 비교해 보세요.'),
    'c2_requests': ('두 요청 확인 완료', '두 고객의 조건을 모두 읽었네요. 이제 서버별 가용량과 배정안을 비교해 보세요. 한 요청의 배정이 다른 요청에 주는 영향은 비교창에서 확인할 수 있어요.'),
    'c2_review': ('배정안 비교 완료', '두 요청의 배정안을 비교해 봤네요. 선택만으로는 자원을 점유하지 않습니다. 이제 직접 판단해 실제로 배정해 보세요.'),
    'c2_allocate': ('배정 판단 완료', '두 요청에 대한 판단이 끝났네요. 서버 랙의 고객 색상과 남은 GPU·전력을 확인하고 시간을 진행해 보세요.'),
    'c2_progress': ('작업 진행 확인', '작업량이 늘었습니다. 두 고객의 진행률과 기한, 반환될 자원을 보며 끝까지 진행해 보세요.'),
}


class StoryFeedbackDialog(tk.Toplevel):
    def __init__(self, parent, event, objective, anchor, avoid=()):
        super().__init__(parent, bg=BG)
        self.event = event
        title, text = FEEDBACK[event]
        self.title('FEEDBACK · '+title)
        self.transient(parent)
        self.resizable(False, False)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.heading = label(self, '✓ '+title, 11, '#ffe08a', True)
        self.heading.grid(row=0, columnspan=2, sticky='w', padx=12, pady=(10, 3))
        self.portrait = tk.Canvas(self, width=66, height=88, bg=BG, highlightthickness=0)
        self.portrait.grid(row=1, column=0, padx=(8, 2), sticky='n')
        # 기존 독창적 선배 초상화를 작은 아이콘으로 재사용합니다.
        draw_portrait(self.portrait, 'mentor', True)
        self.portrait.scale('all', 0, 0, .55, .53)
        self.body = label(self, text, 10, TEXT, justify='left', wraplength=288)
        self.body.grid(row=1, column=1, sticky='nw', padx=(0, 12), pady=3)
        self.goal = label(self, '다음 목표: '+objective, 9, MUTED, justify='left', wraplength=365)
        self.goal.grid(row=2, columnspan=2, sticky='w', padx=12, pady=4)
        self.close_button = ActionButton(self, '확인 · 다음 목표', self.destroy, accent='#ffe08a')
        self.close_button.grid(row=3, columnspan=2, sticky='e', padx=12, pady=(3, 10))
        self.bind('<Escape>', lambda _: self.destroy())
        place_near(self, parent, anchor, avoid=avoid)
