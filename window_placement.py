"""부모 창과 해당 모니터의 작업 영역을 기준으로 팝업을 배치합니다."""
import sys


def work_area(parent):
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD)]

        user = ctypes.windll.user32
        user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user.MonitorFromWindow.restype = wintypes.HANDLE
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        monitor = user.MonitorFromWindow(parent.winfo_id(), 2)
        if user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.work
            return r.left, r.top, r.right, r.bottom
    x, y = parent.winfo_vrootx(), parent.winfo_vrooty()
    return x, y, x + parent.winfo_vrootwidth(), y + parent.winfo_vrootheight()


def centered_bounds(parent_bounds, area, size, margin=12, decoration=(16, 40)):
    left, top, right, bottom = area
    width = min(size[0], max(1, right-left-2*margin-decoration[0]))
    height = min(size[1], max(1, bottom-top-2*margin-decoration[1]))
    px, py, pw, ph = parent_bounds
    x = max(left+margin, min(round(px+(pw-width)/2), right-margin-width-decoration[0]))
    y = max(top+margin, min(round(py+(ph-height)/2), bottom-margin-height-decoration[1]))
    return width, height, x, y


def center_dialog(dialog, parent, size=(820, 470), minimum=(740, 430)):
    parent.update_idletasks()
    bounds = (parent.winfo_rootx(), parent.winfo_rooty(), parent.winfo_width(), parent.winfo_height())
    area = work_area(parent)
    width, height, x, y = centered_bounds(bounds, area, size)
    dialog.minsize(min(minimum[0], width), min(minimum[1], height))
    # geometry의 좌표는 창틀 기준이고 Tk 위젯 좌표는 클라이언트 기준입니다.
    dx, dy = dialog.winfo_rootx()-dialog.winfo_x(), dialog.winfo_rooty()-dialog.winfo_y()
    x, y = max(area[0]+12, x-dx), max(area[1]+12, y-dy)
    dialog.geometry(f'{width}x{height}{x:+d}{y:+d}')
    if sys.platform == 'win32' and (x < 0 or y < 0):
        # Tk의 음수 geometry는 화면 오른쪽/아래로부터의 거리입니다.
        import ctypes
        from ctypes import wintypes
        dialog.update_idletasks()
        user = ctypes.windll.user32
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos(user.GetParent(dialog.winfo_id()), None, x, y, 0, 0, 0x15)
    dialog.deiconify()


def nearby_bounds(anchor, area, size, avoid=(), gap=14):
    """조작 영역을 피하는 가까운 위치를 우선하고 화면 안으로 제한합니다."""
    ax, ay, aw, ah = anchor
    left, top, right, bottom = area
    width = min(size[0], right-left-32)
    height = min(size[1], bottom-top-56)
    candidates = ((ax, ay-height-gap-32), (ax+aw+gap, ay),
                  (ax-width-gap-16, ay), (ax, ay+ah+gap))
    def overlap(x, y, rect):
        rx, ry, rw, rh = rect
        return max(0, min(x+width+16, rx+rw)-max(x, rx)) * max(0, min(y+height+32, ry+rh)-max(y, ry))
    positions = [(max(left+8, min(x, right-width-24)),
                  max(top+8, min(y, bottom-height-40))) for x, y in candidates]
    x, y = min(positions, key=lambda p: (sum(overlap(*p, rect) for rect in (anchor, *avoid)),
                                       abs(p[0]-ax)+abs(p[1]-ay)))
    return width, height, x, y


def place_near(dialog, parent, anchor, size=(390, 210), avoid=()):
    parent.update_idletasks()
    width, height, x, y = nearby_bounds(anchor, work_area(parent), size, avoid)
    dialog.geometry(f'{width}x{height}{x:+d}{y:+d}')
    # center_dialog과 같은 음수 모니터 좌표 처리.
    if sys.platform == 'win32' and (x < 0 or y < 0):
        import ctypes
        from ctypes import wintypes
        dialog.update_idletasks()
        user = ctypes.windll.user32
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos(user.GetParent(dialog.winfo_id()), None, x, y, 0, 0, 0x15)
