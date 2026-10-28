"""AIDC Simulator v0.3: Tkinter 기반 운영 시뮬레이션 GUI."""

from dataclasses import replace
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from database import Database
from game import (
    GameState,
    DataCenter,
    PLANS,
    RESPONSES,
)


class SimulatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AIDC Simulator | 울산 데이터센터 운영실")
        self.root.geometry("1180x800")
        self.root.minsize(1000, 720)

        self.db = Database()
        self.mission = self.db.get_mission()

        # 데이터센터 생성
        self.center = DataCenter()
        self.other_customer_active = False

        # 게임 미션과 데이터센터 연결
        self.state = GameState(center=self.center)

        self.playthrough_id = None

        self.setup_ui()
        self.new_mission()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_ui(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Malgun Gothic", 17, "bold"))
        style.configure("TButton", font=("Malgun Gothic", 10), padding=7)
        style.configure(
            "TLabelframe.Label", font=("Malgun Gothic", 10, "bold")
        )

        wrapper = ttk.Frame(self.root, padding=16)
        wrapper.pack(fill="both", expand=True)
        ttk.Label(
            wrapper,
            text="AIDC SIMULATOR  |  울산 운영실",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            wrapper,
            text="가상의 훈련 환경 · 모든 자원 수치는 교육용 게임 단위입니다.",
        ).pack(anchor="w", pady=(3, 12))

        status_frame = ttk.LabelFrame(wrapper, text="운영 현황", padding=12)
        status_frame.pack(fill="x", pady=(0, 12))
        self.status_var = tk.StringVar()
        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            font=("Malgun Gothic", 10),
        ).pack(anchor="w")
        
        # 다른 고객의 작업 시작 및 종료 버튼
        self.other_customer_button = ttk.Button(
            status_frame,
            text="다른 고객 작업 시작 (GPU 4 / 전력 4)",
            command=self.toggle_other_customer
        )
        
        self.other_customer_button.pack(anchor="w", pady=(8, 0))

        mission_frame = ttk.LabelFrame(wrapper, text="요청된 미션 (진행 중에는 변경할 수 없습니다)", padding=8)
        mission_frame.pack(fill="x", pady=(0, 12))
        self.mission_list = ttk.Treeview(
            mission_frame, columns=("company", "country", "title"),
            show="headings", height=3, selectmode="browse",
        )
        for key, label, width in (
            ("company", "고객사", 200), ("country", "국가", 80), ("title", "요청 내용", 550),
        ):
            self.mission_list.heading(key, text=label)
            self.mission_list.column(key, width=width, minwidth=70)
        mission_scroll = ttk.Scrollbar(mission_frame, orient="vertical", command=self.mission_list.yview)
        self.mission_list.configure(yscrollcommand=mission_scroll.set)
        self.mission_list.pack(side="left", fill="x", expand=True)
        mission_scroll.pack(side="right", fill="y")
        for mission in self.db.get_missions():
            self.mission_list.insert(
                "", "end", iid=str(mission["id"]),
                values=(mission["company_name"], mission["country"], mission["title"]),
            )
        self.mission_list.selection_set(str(self.mission["id"]))
        self.mission_list.bind("<<TreeviewSelect>>", self.on_mission_selected)

        main = ttk.Frame(wrapper)
        main.pack(fill="both", expand=True)
        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))
        right = ttk.LabelFrame(
            main, text="완료 기록 (더블클릭: 상세 로그)", padding=8
        )
        right.configure(width=430)
        right.pack(side="right", fill="both", expand=False)
        right.pack_propagate(False)

       # 결정할 행동 영역을 아래쪽에 먼저 배치
        self.action_frame = ttk.LabelFrame(
            left, text="결정할 행동", padding=10
        )
        self.action_frame.pack(side="bottom", fill="x", pady=(12, 0))
        
        # 스토리 영역은 남은 공간을 사용
        story_frame = ttk.LabelFrame(
            left, text="운영 상황 · 스토리", padding=8
        )
        story_frame.pack(side="top", fill="both", expand=True)
        
        self.story = ScrolledText(
            story_frame, wrap="word", height=8, width=45,
            font=("Malgun Gothic", 11), padx=9, pady=9
        )
        self.story.pack(fill="both", expand=True)
        self.story.configure(state="disabled")

        self.history = ttk.Treeview(
            right,
            columns=("id", "company", "country", "title", "result", "score"),
            show="headings",
            height=20,
        )
        for key, name, width in [
            ("id", "회차", 50),
            ("company", "고객사", 125),
            ("country", "국가", 55),
            ("title", "미션", 210),
            ("result", "결과", 55),
            ("score", "점수", 50),
        ]:
            self.history.heading(key, text=name)
            self.history.column(key, width=width, minwidth=50, anchor="center", stretch=False)
        sb = ttk.Scrollbar(
            right, orient="vertical", command=self.history.yview
        )
        self.history.configure(yscrollcommand=sb.set)
        history_scroll = ttk.Scrollbar(right, orient="horizontal", command=self.history.xview)
        self.history.configure(xscrollcommand=history_scroll.set)
        history_scroll.pack(side="bottom", fill="x")
        self.history.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.history.bind("<Double-1>", self.show_record)

    def append_story(self, text: str, store: bool = True) -> None:
        self.story.configure(state="normal")
        self.story.insert("end", text + "\n\n")
        self.story.see("end")
        self.story.configure(state="disabled")
        if store and self.playthrough_id is not None:
            self.db.add_log(self.playthrough_id, text)

    def update_status(self) -> None:
        s = self.state
        phase_name = {
            "ready": "요청 대기",
            "incident": "장애 대응",
            "finished": "처리 완료",
        }[s.phase]

        score = "-" if s.score is None else str(s.score)

        # 현재 남아 있는 자원 계산
        gpu_remaining = self.center.available_gpu()
        power_remaining = self.center.available_power()

        self.status_var.set(
            f"상태: {phase_name}    |    "
            f"GPU: {self.center.gpu_used}/{self.center.gpu_total} 사용    |    "
            f"전력: {self.center.power_used}/{self.center.power_total} 사용    |    "
            f"네트워크: 필요 {s.network_needed} / 가용 {s.network_available}    |    "
            f"점수: {score}\n"
            f"잔여 자원: GPU {gpu_remaining}개    |    전력 {power_remaining}단위"
        )

    def render_actions(self) -> None:
        self.mission_list.configure(selectmode="none" if self.state.phase == "incident" else "browse")
        for widget in self.action_frame.winfo_children():
            widget.destroy()
        if self.state.phase == "ready":
            ttk.Label(
                self.action_frame, text="이 요청을 어떻게 처리하시겠습니까?"
            ).pack(anchor="w", pady=(0, 5))
            options = [
                ("performance", "GPU 7 · 전력 7 · 필요 네트워크 5"),
                ("economy", "GPU 4 · 전력 4 · 필요 네트워크 3"),
            ]
            for key, desc in options:
                ttk.Button(
                    self.action_frame,
                    text=f"{PLANS[key]['label']}  |  {desc}",
                    command=lambda k=key: self.choose_plan(k),
                ).pack(fill="x", pady=3)
        elif self.state.phase == "incident":
            ttk.Label(
                self.action_frame,
                text="회선 장애 발생! 대응 방법을 선택하십시오.",
            ).pack(anchor="w", pady=(0, 5))
            options = [
                ("reroute", "가용 네트워크 +4 · 운영 비용 증가"),
                ("compress", "필요 네트워크 -2 · 압축 비용 발생"),
                ("ignore", "네트워크 변화 없음 · 대응 비용 없음"),
            ]
            for key, desc in options:
                ttk.Button(
                    self.action_frame,
                    text=f"{RESPONSES[key]['label']}  |  {desc}",
                    command=lambda k=key: self.respond(k),
                ).pack(fill="x", pady=3)
        else:
            ttk.Button(
                self.action_frame,
                text="새 미션 시작",
                command=self.new_mission,
            ).pack(fill="x", pady=3)
            
            
    def toggle_other_customer(self):

        # 다른 고객이 이미 작업 중이라면 종료
        if self.other_customer_active:
    
            self.center.release(4, 4)
            self.other_customer_active = False
    
            self.other_customer_button.config(
                text="다른 고객 작업 시작 (GPU 4 / 전력 4)"
            )
    
            self.append_story(
                "[외부 작업] 다른 고객의 작업이 종료되었습니다.",
                store=False
            )
    
        # 다른 고객이 작업 중이지 않다면 시작
        else:
    
            if not self.center.allocate(4, 4):
                messagebox.showwarning(
                    "자원 부족",
                    "다른 고객에게 자원을 배정할 수 없습니다."
                )
                return
    
            self.other_customer_active = True
    
            self.other_customer_button.config(
                text="다른 고객 작업 종료 (GPU 4 / 전력 4)"
            )
    
            self.append_story(
                "[외부 작업] 다른 고객이 GPU 4개를 사용하기 시작했습니다.",
                store=False
            )
    
        self.update_status()        
    

    def on_mission_selected(self, _event=None) -> None:
        selected = self.mission_list.selection()
        if selected:
            self.select_mission(int(selected[0]))

    def select_mission(self, mission_id: int) -> None:
        if self.state.phase == "incident":
            # 직접 호출이나 지연된 선택 이벤트도 진행 중인 미션을 바꾸지 못하게 합니다.
            current = str(self.mission["id"])
            if self.mission_list.selection() != (current,):
                self.mission_list.selection_set(current)
            return
        if mission_id == self.mission["id"]:
            return
        try:
            mission = self.db.get_mission(mission_id)
        except Exception as exc:
            messagebox.showerror("미션 선택 오류", str(exc))
            self.mission_list.selection_set(str(self.mission["id"]))
            return
        self.mission = mission
        self.mission_list.selection_set(str(mission_id))
        self.new_mission()

    def new_mission(self) -> None:
        if self.state.phase == "incident":
            messagebox.showwarning("미션 진행 중", "현재 미션의 장애 대응을 먼저 완료해 주세요.")
            return
        self.state = GameState(center=self.center)
        self.playthrough_id = None
        self.story.configure(state="normal")
        self.story.delete("1.0", "end")
        self.story.configure(state="disabled")
        self.append_story(
            "[근무 시작] 울산 AIDC 운영실에 새로운 고객 요청이 도착했습니다.\n"
            f"고객: {self.mission['company_name']} ({self.mission['country']})\n"
            f"요청: {self.mission['title']}\n{self.mission['description']}\n"
            "운영 담당자로서 GPU와 통신 자원을 결정해야 합니다.",
            store=False,
        )
        self.update_status()
        self.render_actions()
        self.refresh_history()

    def choose_plan(self, key: str) -> None:
        previous = replace(self.state)
        usage = (self.center.gpu_used, self.center.power_used)
        previous_id = self.playthrough_id
        try:
            with self.db.transaction():
                self.state.choose_plan(key)
                self.playthrough_id = self.db.create_playthrough(
                    self.mission["id"], key
                )
                messages = [
                    f"[고객 요청] {self.mission['company_name']} ({self.mission['country']}) · {self.mission['title']}\n"
                    f"{self.mission['description']}\n"
                    f"[자원 배정] {PLANS[key]['label']} 선택. "
                    f"GPU {self.state.gpu_used}개, 전력 {self.state.power_used}단위 배정.",
                    "[긴급 알림] 울산 AIDC와 해외 고객을 연결하는 국제 네트워크 회선에 장애가 발생했습니다!\n"
                    "네트워크 가용량이 8에서 2단위로 감소했습니다. 대응 방법을 선택해 주십시오.",
                ]
                for message in messages:
                    self.db.add_log(self.playthrough_id, message)
        except Exception as exc:
            self.state = previous
            self.center.gpu_used, self.center.power_used = usage
            self.playthrough_id = previous_id
            messagebox.showerror("처리 오류", str(exc))
            return
        for message in messages:
            self.append_story(message, store=False)
        self.update_status()
        self.render_actions()

    def respond(self, key: str) -> None:
        previous = replace(self.state)
        usage = (self.center.gpu_used, self.center.power_used)
        try:
            with self.db.transaction():
                self.state.resolve(key)
                messages = [
                    f"[운영 조치] {RESPONSES[key]['label']} 선택.",
                    f"[처리 결과] {self.state.result_text}",
                ]
                for message in messages:
                    self.db.add_log(self.playthrough_id, message)
                self.db.save_result(
                    self.playthrough_id,
                    key,
                    bool(self.state.succeeded),
                    int(self.state.score),
                    self.state.result_text,
                )
        except Exception as exc:
            self.state = previous
            self.center.gpu_used, self.center.power_used = usage
            messagebox.showerror("처리 오류", str(exc))
            return
        for message in messages:
            self.append_story(message, store=False)
        self.update_status()
        self.render_actions()
        self.refresh_history()

    def refresh_history(self) -> None:
        for item in self.history.get_children():
            self.history.delete(item)
        for row in self.db.get_recent_results():
            self.history.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(row["id"], row["company_name"], row["country"], row["title"], row["status"], row["score"]),
            )

    def show_record(self, _event=None) -> None:
        selected = self.history.selection()
        if not selected:
            return
        run_id = int(selected[0])
        win = tk.Toplevel(self.root)
        win.title(f"수행 기록 #{run_id}")
        win.geometry("690x430")
        text = ScrolledText(
            win, wrap="word", font=("Malgun Gothic", 10), padx=12, pady=12
        )
        text.pack(fill="both", expand=True, padx=10, pady=10)
        for row in self.db.get_logs(run_id):
            text.insert("end", f"{row['created_at']}\n{row['message']}\n\n")
        text.configure(state="disabled")

    def on_close(self) -> None:
        self.db.close()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    SimulatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
