"""AIDC Simulator v0.1: Tkinter 기반 운영 시뮬레이션 GUI."""
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from database import Database
from game import GameState, PLANS, RESPONSES, GPU_TOTAL, POWER_TOTAL


class SimulatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AIDC Simulator | 울산 데이터센터 운영실")
        self.root.geometry("1040x710")
        self.root.minsize(850, 600)
        self.db = Database()
        self.mission = self.db.get_mission()
        self.state = GameState()
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
        style.configure("TLabelframe.Label", font=("Malgun Gothic", 10, "bold"))

        wrapper = ttk.Frame(self.root, padding=16)
        wrapper.pack(fill="both", expand=True)
        ttk.Label(wrapper, text="AIDC SIMULATOR  |  울산 운영실", style="Title.TLabel").pack(anchor="w")
        ttk.Label(wrapper, text="가상의 훈련 환경 · 모든 자원 수치는 교육용 게임 단위입니다.").pack(anchor="w", pady=(3, 12))

        status_frame = ttk.LabelFrame(wrapper, text="운영 현황", padding=12)
        status_frame.pack(fill="x", pady=(0, 12))
        self.status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.status_var,
                  font=("Malgun Gothic", 10)).pack(anchor="w")

        main = ttk.Frame(wrapper)
        main.pack(fill="both", expand=True)
        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))
        right = ttk.LabelFrame(main, text="완료 기록 (더블클릭: 상세 로그)", padding=8)
        right.pack(side="right", fill="both", expand=False)

        story_frame = ttk.LabelFrame(left, text="운영 상황 · 스토리", padding=8)
        story_frame.pack(fill="both", expand=True)
        self.story = ScrolledText(story_frame, wrap="word", height=16,
                                 font=("Malgun Gothic", 11), padx=9, pady=9)
        self.story.pack(fill="both", expand=True)
        self.story.configure(state="disabled")
        self.action_frame = ttk.LabelFrame(left, text="결정할 행동", padding=10)
        self.action_frame.pack(fill="x", pady=(12, 0))

        self.history = ttk.Treeview(right, columns=("id", "result", "score"),
                                    show="headings", height=20)
        for key, name, width in [("id", "회차", 60), ("result", "결과", 65),
                                 ("score", "점수", 65)]:
            self.history.heading(key, text=name)
            self.history.column(key, width=width, minwidth=50, anchor="center")
        sb = ttk.Scrollbar(right, orient="vertical", command=self.history.yview)
        self.history.configure(yscrollcommand=sb.set)
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
            "finished": "처리 완료"
        }[s.phase]
    
        score = "-" if s.score is None else str(s.score)
    
        # 현재 남아 있는 자원 계산
        gpu_remaining = GPU_TOTAL - s.gpu_used
        power_remaining = POWER_TOTAL - s.power_used
    
        self.status_var.set(
            f"상태: {phase_name}    |    "
            f"GPU: {s.gpu_used}/{GPU_TOTAL} 사용    |    "
            f"전력: {s.power_used}/{POWER_TOTAL} 사용    |    "
            f"네트워크: 필요 {s.network_needed} / 가용 {s.network_available}    |    "
            f"점수: {score}\n"
            f"잔여 자원: GPU {gpu_remaining}개    |    전력 {power_remaining}단위"
        )


    def render_actions(self) -> None:
        for widget in self.action_frame.winfo_children():
            widget.destroy()
        if self.state.phase == "ready":
            ttk.Label(self.action_frame, text="이 요청을 어떻게 처리하시겠습니까?").pack(anchor="w", pady=(0, 5))
            options = [("performance", "GPU 7 · 전력 7 · 필요 네트워크 5"),
                       ("economy", "GPU 4 · 전력 4 · 필요 네트워크 3")]
            for key, desc in options:
                ttk.Button(self.action_frame, text=f"{PLANS[key]['label']}  |  {desc}",
                           command=lambda k=key: self.choose_plan(k)).pack(fill="x", pady=3)
        elif self.state.phase == "incident":
            ttk.Label(self.action_frame, text="회선 장애 발생! 대응 방법을 선택하십시오.").pack(anchor="w", pady=(0, 5))
            options = [("reroute", "가용 네트워크 +4 · 운영 비용 증가"),
                       ("compress", "필요 네트워크 -2 · 압축 비용 발생"),
                       ("ignore", "네트워크 변화 없음 · 대응 비용 없음")]
            for key, desc in options:
                ttk.Button(self.action_frame, text=f"{RESPONSES[key]['label']}  |  {desc}",
                           command=lambda k=key: self.respond(k)).pack(fill="x", pady=3)
        else:
            ttk.Button(self.action_frame, text="새 미션 시작",
                       command=self.new_mission).pack(fill="x", pady=3)

    def new_mission(self) -> None:
        self.state = GameState()
        self.playthrough_id = None
        self.story.configure(state="normal")
        self.story.delete("1.0", "end")
        self.story.configure(state="disabled")
        self.append_story(
            "[근무 시작] 울산 AIDC 운영실에 새로운 고객 요청이 도착했습니다.\n"
            f"고객: {self.mission['company_name']} ({self.mission['country']})\n"
            f"요청: {self.mission['title']}\n{self.mission['description']}\n"
            "운영 담당자로서 GPU와 통신 자원을 결정해야 합니다.", store=False,
        )
        self.update_status()
        self.render_actions()
        self.refresh_history()

    def choose_plan(self, key: str) -> None:
        try:
            self.state.choose_plan(key)
            self.playthrough_id = self.db.create_playthrough(self.mission["id"], key)
            self.append_story(f"[자원 배정] {PLANS[key]['label']} 선택. "
                              f"GPU {self.state.gpu_used}개, 전력 {self.state.power_used}단위 배정.")
            self.append_story(
                "[긴급 알림] 동남아 연결 구간의 가상 해저 통신 회선에 장애가 발생했습니다!\n"
                "네트워크 가용량이 8에서 2단위로 감소했습니다. 대응 방법을 선택해 주십시오."
            )
            self.update_status()
            self.render_actions()
        except Exception as exc:
            messagebox.showerror("처리 오류", str(exc))

    def respond(self, key: str) -> None:
        try:
            self.state.resolve(key)
            self.append_story(f"[운영 조치] {RESPONSES[key]['label']} 선택.")
            self.append_story(f"[처리 결과] {self.state.result_text}")
            self.db.save_result(self.playthrough_id, key, bool(self.state.succeeded),
                                int(self.state.score), self.state.result_text)
            self.update_status()
            self.render_actions()
            self.refresh_history()
        except Exception as exc:
            messagebox.showerror("처리 오류", str(exc))

    def refresh_history(self) -> None:
        for item in self.history.get_children():
            self.history.delete(item)
        for row in self.db.get_recent_results():
            self.history.insert("", "end", iid=str(row["id"]),
                                values=(row["id"], row["status"], row["score"]))

    def show_record(self, _event=None) -> None:
        selected = self.history.selection()
        if not selected:
            return
        run_id = int(selected[0])
        win = tk.Toplevel(self.root)
        win.title(f"수행 기록 #{run_id}")
        win.geometry("690x430")
        text = ScrolledText(win, wrap="word", font=("Malgun Gothic", 10), padx=12, pady=12)
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
