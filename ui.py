"""표준 Tkinter로 그리는 관제실 위젯. 게임 상태를 변경하지 않습니다."""
import math
import tkinter as tk
from tkinter import ttk

BG = "#080f1d"
PANEL = "#101c2e"
RAISED = "#17273d"
BORDER = "#263b54"
TEXT = "#e3edf8"
MUTED = "#91a7c1"
CYAN = "#38d9d0"
BLUE = "#6d9fff"
GREEN = "#66e0a3"
RED = "#ff6b79"
AMBER = "#ffbf69"
FONT = "Malgun Gothic"
CUSTOMER_COLORS = (CYAN, BLUE, "#c5a1ff", AMBER)


def status_of(state):
    if state.phase == "ready":
        return "○ 요청 대기", MUTED
    if state.phase == "incident":
        return "! 회선 장애 · 대응 필요", RED
    if state.response == "abandon":
        return "■ 종료로 중단 · 0점", AMBER
    if state.succeeded:
        return f"✓ 미션 성공 · {state.score}점", GREEN
    return f"× 처리 실패 · {state.score}점", RED


def label(parent, text="", size=10, color=TEXT, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color,
                    font=(FONT, size, "bold" if bold else "normal"), **kwargs)


class ActionButton(tk.Button):
    def __init__(self, parent, text, command, accent=CYAN, **kwargs):
        super().__init__(parent, text=text, command=command, bg=RAISED, fg=accent,
                         activebackground=BORDER, activeforeground=TEXT,
                         disabledforeground=MUTED, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=BORDER,
                         font=(FONT, 10, "bold"), padx=12, pady=10,
                         cursor="hand2", **kwargs)
        self.bind("<Enter>", lambda _: self.configure(bg=BORDER)
                  if self.cget("state") != "disabled" else None)
        self.bind("<Leave>", lambda _: self.configure(bg=RAISED))


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.timer = self.window = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def schedule(self, _event):
        self.hide()
        self.timer = self.widget.after(550, self.show)

    def show(self):
        self.timer = None
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f"+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty() + 30}")
        tk.Label(self.window, text=self.text, bg=BORDER, fg=TEXT, wraplength=280,
                 font=(FONT, 10), padx=12, pady=8).pack()

    def hide(self, _event=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class ScrollArea(tk.Frame):
    """작은 창에서는 전체 화면을 스크롤하여 행동 버튼까지 접근합니다."""
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=BG)
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.item, width=e.width))
        # toplevel 바인딩은 자식 위젯에서도 동작하며 로그/기록의 자체 스크롤은 존중합니다.
        parent.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        if event.widget.winfo_class() in ("Text", "Treeview"):
            return
        if self.content.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta / 120), "units")


class MissionCard(tk.Frame):
    def __init__(self, parent, run, color, command):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER,
                         padx=13, pady=11, cursor="hand2")
        self.run, self.color = run, color
        self.columnconfigure(0, weight=1)
        self.country = label(self, run.mission["country"].upper(), 9, color, True)
        self.country.grid(row=0, column=0, sticky="w")
        label(self, run.mission["company_name"], 12, bold=True).grid(row=1, column=0, sticky="w", pady=(3, 1))
        label(self, run.mission["title"], 9, MUTED, wraplength=220, justify="left").grid(row=2, column=0, sticky="w")
        self.requirements = label(self, size=9, color=MUTED, justify="left")
        self.requirements.grid(row=3, column=0, sticky="w", pady=(7, 4))
        self.status = label(self, size=9, bold=True)
        self.status.grid(row=4, column=0, sticky="w")
        for widget in (self, *self.winfo_children()):
            widget.bind("<Button-1>", lambda _: command())
            widget.bind("<Enter>", lambda _: self.configure(highlightbackground=color))
            widget.bind("<Leave>", lambda _: self.configure(
                highlightbackground=color if self.selected else BORDER))
        self.selected = False

    def refresh(self, selected):
        self.selected = selected
        state = self.run.state
        if state.phase == "ready":
            p, e = state.plans["performance"], state.plans["economy"]
            text = f"고성능  GPU {p['gpu']} / 전력 {p['power']} / 망 {p['network']}\n절약형  GPU {e['gpu']} / 전력 {e['power']} / 망 {e['network']}"
        else:
            suffix = "점유 중" if state.phase == "incident" else "반환 완료"
            text = f"{state.plans[state.plan]['label']}\nGPU {state.gpu_used} / 전력 {state.power_used} · {suffix}"
        self.requirements.configure(text=text)
        name, color = status_of(state)
        self.status.configure(text=name, fg=color)
        self.configure(highlightbackground=self.color if selected else BORDER,
                       highlightthickness=2 if selected else 1)


class NetworkMap(tk.Canvas):
    def __init__(self, parent, session, select):
        super().__init__(parent, bg=BG, highlightthickness=0, width=300, height=310)
        self.session, self.select = session, select
        self.tick = 0
        self.timer = None
        self.bind("<Configure>", lambda _: self.redraw())

    def start(self):
        self.animate()

    def stop(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def animate(self):
        self.tick = (self.tick + 1) % 32
        self.redraw()
        self.timer = self.after(90, self.animate)

    def redraw(self):
        self.delete("all")
        w, h = max(300, self.winfo_width()), max(260, self.winfo_height())
        for x in range(16, int(w), 28):
            for y in range(14, int(h), 28):
                self.create_oval(x, y, x+1, y+1, fill=BORDER, outline="")
        cx, cy = w * .5, h * .51
        positions = ((.22, .18), (.78, .18), (.5, .88))
        for i, (mission_id, run) in enumerate(self.session.runs.items()):
            if i < 3:
                px, py = positions[i]
            else:
                angle = 2 * math.pi * i / len(self.session.runs)
                px, py = .5 + .35 * math.cos(angle), .5 + .36 * math.sin(angle)
            x, y = w * px, h * py
            state = run.state
            _, color = status_of(state)
            backup = state.response == "reroute"
            line_color = RED if state.phase == "incident" or backup else GREEN if state.succeeded else BORDER
            self.create_line(cx, cy, x, y, fill=line_color, width=2,
                             dash=(5, 5) if state.phase == "incident" or backup else ())
            if backup:
                bx, by = (cx+x)/2 + 45, (cy+y)/2
                self.create_line(cx, cy, bx, by, x, y, fill=CYAN, width=3, smooth=True,
                                 dash=(7, 4), dashoffset=self.tick, tags="backup")
                self.create_text(bx, by+12, text="백업 +4", fill=CYAN, font=(FONT, 8))
            if state.phase == "incident":
                t = self.tick / 32
                dx, dy = cx+(x-cx)*t, cy+(y-cy)*t
                self.create_oval(dx-3, dy-3, dx+3, dy+3, fill=RED, outline="", tags="packet")
                self.create_text((cx+x)/2, (cy+y)/2-10,
                                 text="!  가용 2", fill=RED if self.tick % 12 < 8 else AMBER,
                                 font=(FONT, 9, "bold"))
            elif state.phase == "finished":
                hint = f"필요 {state.network_needed} / 가용 {state.network_available}"
                self.create_text((cx+x)/2, (cy+y)/2-10, text=hint, fill=color, font=(FONT, 8))
            tag = f"mission-{mission_id}"
            self.create_rectangle(x-54, y-25, x+54, y+25, fill=PANEL,
                                  outline=color if mission_id == self.session.selected_id else BORDER,
                                  width=2, tags=tag)
            self.create_text(x, y-6, text=run.mission["country"], fill=TEXT, font=(FONT, 10, "bold"), tags=tag)
            caption = "대기" if state.phase == "ready" else "! 장애" if state.phase == "incident" else "✓ 성공" if state.succeeded else "× 실패"
            self.create_text(x, y+11, text=caption, fill=color, font=(FONT, 8), tags=tag)
            self.tag_bind(tag, "<Button-1>", lambda _, mid=mission_id: self.select(mid))
            self.tag_bind(tag, "<Enter>", lambda _: self.configure(cursor="hand2"))
            self.tag_bind(tag, "<Leave>", lambda _: self.configure(cursor=""))
        self.create_oval(cx-48, cy-48, cx+48, cy+48, fill=PANEL, outline=CYAN, width=2)
        self.create_oval(cx-41, cy-41, cx+41, cy+41, outline=BORDER)
        self.create_text(cx, cy-10, text="ULSAN", fill=CYAN, font=(FONT, 14, "bold"))
        self.create_text(cx, cy+12, text="AI DATA CENTER", fill=TEXT, font=(FONT, 8))


class ResourcePanel(tk.Frame):
    def __init__(self, parent, session):
        super().__init__(parent, bg=PANEL, padx=15, pady=14)
        self.session = session
        label(self, "03  /  자원 관제", 12, bold=True).pack(anchor="w")
        self.gpu_label = label(self, size=11, bold=True)
        self.gpu_label.pack(anchor="w", pady=(20, 4))
        Tooltip(self.gpu_label, "GPU는 AI 연산을 처리하는 장치입니다. 색이 채워진 블록은 고객에게 배정되어 있습니다.")
        self.rack = tk.Canvas(self, bg=PANEL, width=200, height=80, highlightthickness=0)
        self.rack.pack(fill="x")
        self.rack.bind("<Configure>", lambda _: self.refresh())
        self.power_label = label(self, size=11, bold=True)
        self.power_label.pack(anchor="w", pady=(12, 5))
        self.power = tk.Canvas(self, bg=PANEL, width=200, height=14, highlightthickness=0)
        self.power.pack(fill="x")
        self.power.bind("<Configure>", lambda _: self.refresh())
        self.free = label(self, color=CYAN, size=9)
        self.free.pack(anchor="w", pady=(8, 18))
        label(self, "고객별 점유량", 10, bold=True).pack(anchor="w")
        self.owners = label(self, size=9, justify="left", anchor="w")
        self.owners.pack(fill="x", pady=(8, 0))
        label(self, "작업 완료 → 해당 자원만 반환\n회선 가용량은 고객별로 독립 관리", 9,
              MUTED, justify="left").pack(anchor="w", pady=(18, 0))

    def refresh(self):
        center = self.session.center
        active = [(i, run) for i, run in enumerate(self.session.runs.values()) if run.state.phase == "incident"]
        self.gpu_label.configure(text=f"GPU 서버   {center.gpu_used:02d} / {center.gpu_total:02d}")
        self.rack.delete("all")
        colors = [CUSTOMER_COLORS[i % len(CUSTOMER_COLORS)] for i, run in active for _ in range(run.state.gpu_used)]
        width = max(180, self.rack.winfo_width())
        step = width / 5
        for index in range(center.gpu_total):
            x, y = (index % 5)*step, (index // 5)*39
            color = colors[index] if index < len(colors) else BORDER
            self.rack.create_rectangle(x+2, y+2, x+step-4, y+33, fill=RAISED, outline=color, width=2)
            self.rack.create_rectangle(x+7, y+8, x+step-9, y+12, fill=color, outline="")
            self.rack.create_oval(x+8, y+21, x+12, y+25, fill=color, outline="")
        self.power_label.configure(text=f"전력   {center.power_used:02d} / {center.power_total:02d}")
        self.power.delete("all")
        width = max(180, self.power.winfo_width())
        self.power.create_rectangle(0, 1, width, 13, fill=BORDER, outline="")
        offset = 0
        for i, run in active:
            end = offset + run.state.power_used / center.power_total * width
            self.power.create_rectangle(offset, 1, end, 13, fill=CUSTOMER_COLORS[i % len(CUSTOMER_COLORS)], outline="")
            offset = end
        self.free.configure(text=f"배정 가능  GPU {center.available_gpu()}개 · 전력 {center.available_power()}단위",
                            fg=AMBER if min(center.available_gpu(), center.available_power()) == 0 else CYAN)
        self.owners.configure(text="\n\n".join(
            f"{run.mission['country']}  ·  GPU {run.state.gpu_used} / 전력 {run.state.power_used}"
            for _, run in active) or "현재 배정된 작업이 없습니다.")
