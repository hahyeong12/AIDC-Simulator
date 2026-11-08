"""한 번에 한 조작 대상만 강조하는 화면 전용 구성요소. 저장/게임 상태는 수정하지 않습니다."""
import tkinter as tk

GOLD, GOLD_DIM = '#ffe08a', '#d9ae54'
TAB_KEYS = {'inspector': 0, 'preview': 1}
POINTER_TEXT = {'time': '▼ 시간 버튼 중 하나를 클릭', 'work_complete': '▼ 시간 버튼 중 하나를 클릭'}


class TutorialHighlight:
    def __init__(self, root, animate=True):
        self.root, self.animate = root, animate
        self.target = self.key = self.timer = None
        self.original = None
        self.target_binding = None
        self.top = self.top_binding = None
        self.custom = False
        self.edges = []
        self.pointer = None
        self.bright = True
        self.binding = root.bind('<Destroy>', self._destroyed, add='+')
        self.layout_binding = root.bind('<Configure>', lambda _: self.position_pointer(), add='+')

    def _destroyed(self, event):
        if event.widget is self.root:
            self.stop()
        elif event.widget is self.target:
            self.clear()

    def clear(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.target is not None and self.target.winfo_exists():
            if self.target_binding is not None:
                self.target.unbind('<Destroy>', self.target_binding)
            if self.custom:
                self.target.set_tutorial_highlight(None)
            else:
                self.target.configure(**self.original)
        for edge in self.edges:
            if edge.winfo_exists():
                edge.destroy()
        self.edges.clear()
        if self.pointer is not None:
            self.pointer.destroy()
            self.pointer = None
        if self.top is not None and self.top_binding is not None:
            try:
                self.top.unbind('<Configure>', self.top_binding)
            except tk.TclError:
                pass
        self.top = self.top_binding = None
        self.target = self.key = self.original = None
        self.target_binding = None
        self.custom = False

    def show(self, key=None, widget=None):
        if widget is self.target and key == self.key:
            return
        self.clear()
        if widget is None or not widget.winfo_exists():
            return
        self.key, self.target, self.bright = key, widget, True
        self.custom = key in ('server', *TAB_KEYS) and hasattr(widget, 'set_tutorial_highlight')
        self.target_binding = widget.bind('<Destroy>', self._destroyed, add='+')
        top = widget.winfo_toplevel()
        if top is not self.root:
            # 팝업 안의 대상은 팝업이 이동/크기 변경될 때 바로 다시 배치합니다.
            self.top, self.top_binding = top, top.bind('<Configure>', lambda _: self.position_pointer(), add='+')
        if not self.custom:
            self.original = {name: widget.cget(name) for name in
                             ('highlightthickness', 'highlightbackground', 'highlightcolor')}
            if 'foreground' in widget.keys():
                self.original.update(bg=widget.cget('bg'), fg=widget.cget('fg'))
                widget.configure(bg='#3c3019', fg=GOLD)
            # 형제 위젯으로 그려 Windows 기본 버튼의 자체 그리기에 묻히지 않게 합니다.
            for inset, thickness in ((0, 3), (5, 1)):
                for side in ('top', 'bottom', 'left', 'right'):
                    edge = tk.Frame(widget.winfo_toplevel(), bg=GOLD, bd=0, cursor='hand2')
                    edge.tutorial_side = (inset, thickness, side)
                    edge.bind('<Button-1>', lambda _: self.activate())
                    self.edges.append(edge)
        self.pointer = tk.Label(widget.winfo_toplevel(), text=POINTER_TEXT.get(key, '▼ 여기를 클릭'), bg='#251f15', fg=GOLD,
                                font=('Malgun Gothic', 9, 'bold'), padx=7, pady=2, cursor='hand2')
        self.pointer.bind('<Button-1>', lambda _: self.activate())
        self._paint()

    def activate(self):
        if self.target is None:
            return
        if self.key == 'preview':
            self.target.show_preview()
        elif self.key == 'inspector':
            self.target.book.select(self.target.inspector_frame)
        elif self.key in ('time', 'work_complete'):
            self.target.winfo_children()[0].invoke()  # 묶음의 첫 버튼(+10분)과 같은 실제 동작
        elif self.key == 'server':
            self.target.select('A')
        elif hasattr(self.target, 'invoke'):
            self.target.invoke()

    def position_pointer(self):
        if (self.pointer is None or self.target is None or not self.pointer.winfo_exists()
                or not self.target.winfo_exists()):
            return
        top = self.target.winfo_toplevel()
        if self.key == 'server':
            # 랙에는 Canvas 내부의 별도 클릭 안내를 표시합니다.
            self.pointer.place_forget()
            return
        x = self.target.winfo_rootx()-top.winfo_rootx()
        y = self.target.winfo_rooty()-top.winfo_rooty()
        width, height = self.target.winfo_width(), self.target.winfo_height()
        for edge in self.edges:
            inset, thickness, side = edge.tutorial_side
            # 버튼의 자식 테두리는 Windows 버튼 자체 그리기에 가려질 수 있어 형제 위젯으로 표시합니다.
            offset = -3 if inset == 0 else -1
            ex, ey, ew, eh = x+offset, y+offset, width-2*offset, height-2*offset
            if side in ('top', 'bottom'):
                edge.place(x=ex, y=ey if side == 'top' else ey+eh-thickness, width=ew, height=thickness)
            else:
                edge.place(x=ex if side == 'left' else ex+ew-thickness, y=ey, width=thickness, height=eh)
            edge.lift()
        x = max(0, min(x, top.winfo_width()-128))
        py = y-25 if y >= 25 else y+self.target.winfo_height()+2
        self.pointer.place(x=x, y=min(py, max(0, top.winfo_height()-25)))
        self.pointer.lift()

    def _paint(self):
        self.timer = None
        if self.target is None or not self.target.winfo_exists():
            self.clear()
            return
        color = GOLD if self.bright else GOLD_DIM
        if self.custom:
            if self.key in TAB_KEYS:
                self.target.set_tutorial_highlight(color, TAB_KEYS[self.key])
            else:
                self.target.set_tutorial_highlight(color)
        else:
            self.target.configure(highlightbackground=color, highlightcolor=color)
            for index, edge in enumerate(self.edges):
                edge.configure(bg=color if index < 4 else '#b28131')
        self.position_pointer()
        if self.pointer is not None:
            self.pointer.configure(fg=color)
        if self.animate:
            self.bright = not self.bright
            self.timer = self.root.after(500, self._paint)

    def stop(self):
        self.clear()
        if self.binding is not None:
            self.root.unbind('<Destroy>', self.binding)
            self.binding = None
        if self.layout_binding is not None:
            self.root.unbind('<Configure>', self.layout_binding)
            self.layout_binding = None
