"""창 가운데 내용만 스크롤하고 아래 버튼 영역은 항상 보이게 하는 공통 위젯 (v0.9-2b-1).

`ScrollArea(parent, bg)`는 Frame처럼 grid/pack으로 배치하고, 내용은 `area.body`에 넣습니다.
본문이 창보다 작으면 스크롤바는 숨겨지고, 커지면 휠/스크롤바로 이동합니다. 게임 상태와는 무관한 순수 표시 도구입니다.
"""
import tkinter as tk

from ui import BG, PANEL, BORDER


def needs_scroll(content_height, view_height):
    """본문이 보이는 높이를 넘을 때만 스크롤이 필요합니다(순수 함수)."""
    return content_height > view_height + 1


class ScrollArea(tk.Frame):
    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                                      bg=PANEL, troughcolor=BG, activebackground=BORDER)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.body.columnconfigure(0, weight=1)
        self.body.bind('<Configure>', lambda _: self._update())
        self.canvas.bind('<Configure>', self._resize)
        self.scrollbar_shown = False
        self.bind('<Enter>', lambda _: self._bind_wheel())
        self.bind('<Leave>', lambda _: self._unbind_wheel())
        self.bind('<Destroy>', lambda e: self._unbind_wheel() if e.widget is self else None, add='+')

    def _resize(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self._update()

    def _update(self):
        self.canvas.configure(scrollregion=self.canvas.bbox('all') or (0, 0, 0, 0))
        content = self.body.winfo_reqheight()
        shown = needs_scroll(content, self.canvas.winfo_height())
        if shown and not self.scrollbar_shown:
            self.scrollbar.grid(row=0, column=1, sticky='ns')
        elif not shown and self.scrollbar_shown:
            self.scrollbar.grid_remove()
            self.canvas.yview_moveto(0)
        self.scrollbar_shown = shown

    def _bind_wheel(self):
        try:
            self.winfo_toplevel().bind_all('<MouseWheel>', self._wheel)
        except tk.TclError:
            pass

    def _unbind_wheel(self):
        try:
            self.winfo_toplevel().unbind_all('<MouseWheel>')
        except tk.TclError:
            pass

    def _wheel(self, event):
        if self.scrollbar_shown:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
