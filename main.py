"""AIDC Simulator v0.4: 미래형 울산 데이터센터 운영실."""
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from database import Database
from game import RESPONSES
from session import GameSession
from ui import (BG, PANEL, BORDER, TEXT, MUTED, CYAN, GREEN, RED, AMBER, FONT,
                CUSTOMER_COLORS, ActionButton, Tooltip, ScrollArea, MissionCard,
                NetworkMap, ResourcePanel, label, status_of)


class SimulatorApp:
    def __init__(self, root: tk.Tk, db: Database | None = None):
        self.root = root
        root.title("AIDC Simulator v0.4 | 울산 AI 데이터센터 관제실")
        root.geometry("1360x940")
        root.minsize(980, 680)
        root.configure(bg=BG)
        self.db = db if db is not None else Database()
        self.session = GameSession(self.db)
        self.center = self.session.center
        self.setup_ui()
        self.refresh()
        self.network.start()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    @property
    def state(self):
        return self.session.current.state

    @property
    def mission(self):
        return self.session.current.mission

    @property
    def playthrough_id(self):
        return self.session.current.playthrough_id

    def setup_ui(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED,
                        font=(FONT, 10), padding=(16, 7))
        style.map("TNotebook.Tab", background=[("selected", BORDER)], foreground=[("selected", CYAN)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        borderwidth=0, rowheight=29, font=(FONT, 9))
        style.configure("Treeview.Heading", background=BORDER, foreground=TEXT,
                        font=(FONT, 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", BORDER)], foreground=[("selected", CYAN)])
        style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=BG, borderwidth=0)
        header = tk.Frame(self.root, bg=BG, padx=22, pady=14)
        header.pack(fill="x")
        label(header, "AIDC", 24, CYAN, True).pack(side="left")
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", padx=14)
        label(titles, "ULSAN  /  AI DATA CENTER", 12, bold=True).pack(anchor="w")
        label(titles, "운영 시뮬레이션  ·  고객의 요청을 연결하고 자원을 배분하세요", 9, MUTED).pack(anchor="w")
        label(header, "CONTROL ROOM   /   v0.4", 10, CYAN).pack(side="right")
        self.scroll = ScrollArea(self.root)
        self.scroll.pack(fill="both", expand=True)
        page = self.scroll.content
        page.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar()
        tk.Label(page, textvariable=self.status_var, bg=PANEL, fg=CYAN, font=(FONT, 10),
                 anchor="w", padx=14, pady=10).grid(row=0, column=0, sticky="ew", padx=18, pady=(0, 12))
        body = tk.Frame(page, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=18)
        body.columnconfigure(0, minsize=250)
        body.columnconfigure(1, weight=1, minsize=340)
        body.columnconfigure(2, minsize=245)
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        label(left, "01  /  고객 미션", 12, bold=True).pack(anchor="w", pady=(0, 10))
        self.cards = {}
        for i, (mid, run) in enumerate(self.session.runs.items()):
            card = MissionCard(left, run, CUSTOMER_COLORS[i % len(CUSTOMER_COLORS)],
                               lambda mission_id=mid: self.select_mission(mission_id))
            card.pack(fill="x", pady=(0, 9))
            self.cards[mid] = card
        middle = tk.Frame(body, bg=PANEL, padx=14, pady=14)
        middle.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        label(middle, "02  /  글로벌 연결망", 12, bold=True).pack(anchor="w")
        label(middle, "● 정상   ! 장애   ┄ 백업 우회", 9, MUTED).pack(anchor="w", pady=(5, 7))
        self.network = NetworkMap(middle, self.session, self.select_mission)
        self.network.pack(fill="both", expand=True)
        label(middle, "교육용으로 단순화한 가상 네트워크입니다.", 8, MUTED).pack(anchor="w", pady=(8, 0))
        self.resources = ResourcePanel(body, self.session)
        self.resources.grid(row=0, column=2, sticky="nsew")
        controls = tk.Frame(page, bg=PANEL, padx=16, pady=12)
        controls.grid(row=2, column=0, sticky="ew", padx=18, pady=12)
        self.detail_title = label(controls, size=12, bold=True, anchor="w")
        self.detail_title.pack(fill="x")
        self.detail = label(controls, size=9, color=MUTED, justify="left", anchor="w")
        self.detail.pack(fill="x", pady=(4, 7))
        self.detail.bind("<Configure>", lambda e: self.detail.configure(wraplength=max(250, e.width-10)))
        self.action_hint = label(controls, size=10, color=CYAN, anchor="w", justify="left")
        self.action_hint.pack(fill="x", pady=(0, 8))
        self.action_hint.bind("<Configure>", lambda e: self.action_hint.configure(wraplength=max(250, e.width-10)))
        self.action_frame = tk.Frame(controls, bg=PANEL)
        self.action_frame.pack(fill="x")
        self.action_frame.columnconfigure((0, 1, 2), weight=1, uniform="action")
        notebook = ttk.Notebook(page)
        notebook.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 14))
        events, records = tk.Frame(notebook, bg=PANEL), tk.Frame(notebook, bg=PANEL)
        notebook.add(events, text="선택 고객 · 이벤트")
        notebook.add(records, text="전체 수행 기록 · 더블클릭으로 로그 보기")
        self.story = ScrolledText(events, height=6, wrap="word", font=(FONT, 9),
                                  bg=PANEL, fg=TEXT, insertbackground=TEXT, bd=0, padx=12, pady=10)
        self.story.pack(fill="both", expand=True)
        self.story.configure(state="disabled")
        self.history = ttk.Treeview(records, columns=("id", "company", "country", "title", "result", "score"),
                                    show="headings", height=5)
        for key, title, width in (("id", "회차", 50), ("company", "고객사", 150), ("country", "국가", 70),
                                  ("title", "미션", 220), ("result", "상태", 140), ("score", "점수", 60)):
            self.history.heading(key, text=title)
            self.history.column(key, width=width, minwidth=50, stretch=key in ("title", "company"))
        ybar = ttk.Scrollbar(records, orient="vertical", command=self.history.yview)
        xbar = ttk.Scrollbar(records, orient="horizontal", command=self.history.xview)
        self.history.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        records.rowconfigure(0, weight=1)
        records.columnconfigure(0, weight=1)
        self.history.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.history.bind("<Double-1>", self.show_record)
        label(page, "가상의 고객 · 게임 단위 자원  /  정상 종료 시 미완료 작업은 실패·0점으로 기록됩니다.",
              8, MUTED).grid(row=4, column=0, sticky="w", padx=20, pady=(0, 12))

    def refresh(self):
        self.update_status()
        self.render_actions()
        self.render_story()
        self.refresh_history()

    def update_status(self):
        active = sum(run.state.phase == "incident" for run in self.session.runs.values())
        self.status_var.set(f"운영 중 {active}건   /   GPU {self.center.gpu_used}/{self.center.gpu_total}   /   "
                            f"전력 {self.center.power_used}/{self.center.power_total}   ·   고객 카드를 눌러 작업을 전환하세요")
        for mid, card in self.cards.items():
            card.refresh(mid == self.session.selected_id)
        self.resources.refresh()
        self.network.redraw()

    def render_actions(self):
        for widget in self.action_frame.winfo_children():
            widget.destroy()
        state = self.state
        name, color = status_of(state)
        self.detail_title.configure(text=f"{self.mission['company_name']}  /  {self.mission['country']}  ·  {name}", fg=color)
        self.detail.configure(text=f"{self.mission['title']} — {self.mission['description']}")
        self.action_buttons = {}
        if state.phase == "ready":
            self.action_hint.configure(text="01  운영 모드 선택 → 02  회선 장애 대응 → 03  결과 확인 · 자원 반환", fg=CYAN)
            for i, (key, plan) in enumerate(state.plans.items()):
                fits = plan["gpu"] <= self.center.available_gpu() and plan["power"] <= self.center.available_power()
                missing = []
                if plan["gpu"] > self.center.available_gpu():
                    missing.append(f"GPU {plan['gpu'] - self.center.available_gpu()}개")
                if plan["power"] > self.center.available_power():
                    missing.append(f"전력 {plan['power'] - self.center.available_power()}단위")
                text = f"{plan['label']}\nGPU {plan['gpu']} · 전력 {plan['power']} · 망 {plan['network']}"
                if not fits:
                    text += f"\n부족: {' / '.join(missing)}"
                button = ActionButton(self.action_frame, text, lambda k=key: self.choose_plan(k),
                                      state="normal" if fits else "disabled")
                button.grid(row=0, column=i, sticky="nsew", padx=(0, 8))
                Tooltip(button, "자원이 부족하면 다른 고객의 작업을 완료해 자원을 반환받으세요." if not fits
                        else "선택 즉시 자원이 배정됩니다. 장애가 발생하면 대응을 선택해 완료하세요.")
                self.action_buttons[key] = button
        elif state.phase == "incident":
            self.action_hint.configure(text=f"! 회선 장애  ·  필요 {state.network_needed} / 가용 {state.network_available}단위. "
                                       "요구량이 가용량 이하여야 성공합니다.", fg=RED)
            for i, (key, response) in enumerate(RESPONSES.items()):
                required = max(1, state.network_needed-2) if key == "compress" else state.network_needed
                available = min(8, state.network_available+4) if key == "reroute" else state.network_available
                effect = {"reroute": "가용량 +4", "compress": "필요량 −2", "ignore": "변화 없음"}[key]
                text = f"{response['label']}\n{effect} · 필요 {required} / 가용 {available}"
                button = ActionButton(self.action_frame, text, lambda k=key: self.respond(k), accent=AMBER)
                button.grid(row=0, column=i, sticky="nsew", padx=(0, 8))
                self.action_buttons[key] = button
                Tooltip(button, "백업 경로는 장애가 발생했을 때 사용하는 대체 통신 경로입니다." if key == "reroute"
                        else f"대응 점수 차감: {response['penalty']}점. 필요량이 가용량을 넘으면 실패합니다.")
        else:
            self.action_hint.configure(text=state.result_text, fg=GREEN if state.succeeded else RED)
            button = ActionButton(self.action_frame, "같은 고객의 새 요청 받기", self.new_mission)
            button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
            self.action_buttons["restart"] = button
            label(self.action_frame, "다른 고객 카드를 선택해\n진행 중인 작업도 이어갈 수 있습니다.", 9, MUTED,
                  justify="left").grid(row=0, column=1, columnspan=2, sticky="w")

    def render_story(self):
        messages = self.session.current.messages
        text = "\n\n".join(messages) if messages else (
            f"[요청 도착] {self.mission['company_name']} ({self.mission['country']})\n"
            f"{self.mission['title']}\n{self.mission['description']}\n\n운영 모드를 선택해 자원을 배정하세요.")
        self.story.configure(state="normal")
        self.story.delete("1.0", "end")
        self.story.insert("end", text)
        self.story.see("end")
        self.story.configure(state="disabled")

    def select_mission(self, mission_id):
        try:
            self.session.select(mission_id)
        except ValueError as exc:
            messagebox.showerror("미션 선택 오류", str(exc), parent=self.root)
            return
        self.refresh()

    def new_mission(self):
        try:
            self.session.restart()
        except ValueError as exc:
            messagebox.showwarning("미션 진행 중", str(exc), parent=self.root)
            return
        self.refresh()

    def choose_plan(self, key):
        self._perform(lambda: self.session.choose_plan(key))

    def respond(self, key):
        self._perform(lambda: self.session.respond(key))

    def _perform(self, action):
        try:
            action()
        except Exception as exc:
            messagebox.showerror("처리 오류", str(exc), parent=self.root)
            return
        self.refresh()

    def refresh_history(self):
        selected = self.history.selection()
        for item in self.history.get_children():
            self.history.delete(item)
        active_ids = {r.playthrough_id for r in self.session.runs.values() if r.state.phase == "incident"}
        for row in self.db.get_recent_records():
            status = row["status"]
            if status == "진행중" and row["id"] not in active_ids:
                status = "이전 실행 미완료"
            self.history.insert("", "end", iid=str(row["id"]), values=(
                row["id"], row["company_name"], row["country"], row["title"], status,
                "—" if row["score"] is None else row["score"]))
        for item in selected:
            if self.history.exists(item):
                self.history.selection_add(item)

    def show_record(self, _event=None):
        selected = self.history.selection()
        if not selected:
            return
        run_id = int(selected[0])
        win = tk.Toplevel(self.root)
        win.title(f"수행 기록 #{run_id}")
        win.geometry("740x480")
        text = ScrolledText(win, wrap="word", font=(FONT, 10), bg=PANEL, fg=TEXT, padx=16, pady=16)
        text.pack(fill="both", expand=True)
        for row in self.db.get_logs(run_id):
            text.insert("end", f"{row['created_at']}\n{row['message']}\n\n")
        text.configure(state="disabled")

    def on_close(self):
        try:
            self.session.abandon_active()
        except Exception as exc:
            messagebox.showerror("종료 기록 저장 오류", f"종료하지 않았습니다. 다시 시도해 주세요.\n{exc}", parent=self.root)
            return
        self.network.stop()
        self.db.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    SimulatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
