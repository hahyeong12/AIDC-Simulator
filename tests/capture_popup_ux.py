"""메모리 DB로 실제 Tk 화면을 캡처합니다: python -m tests.capture_popup_ux"""
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageGrab

from database import Database
from main import SimulatorApp
from tests.support import dismiss_story_popups


def capture_client(widget):
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    width, height = widget.winfo_width(), widget.winfo_height()
    try:
        return ImageGrab.grab(bbox=(x, y, x+width, y+height), all_screens=True)
    except OSError:
        # 화면 읽기가 제한된 Windows 세션에서는 이 앱의 클라이언트만 직접 그립니다.
        import ctypes
        from ctypes import wintypes as wt
        user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        user.GetParent.argtypes = [wt.HWND]; user.GetParent.restype = wt.HWND
        user.GetDC.argtypes = [wt.HWND]; user.GetDC.restype = wt.HDC
        user.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        user.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
        gdi.CreateCompatibleDC.argtypes = [wt.HDC]; gdi.CreateCompatibleDC.restype = wt.HDC
        gdi.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
        gdi.CreateCompatibleBitmap.restype = wt.HBITMAP
        gdi.SelectObject.argtypes = [wt.HDC, wt.HANDLE]; gdi.SelectObject.restype = wt.HANDLE
        gdi.DeleteObject.argtypes = [wt.HANDLE]; gdi.DeleteDC.argtypes = [wt.HDC]
        gdi.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, wt.LPVOID, wt.LPVOID, wt.UINT]
        hwnd = user.GetParent(widget.winfo_id())
        dc = user.GetDC(hwnd)
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        old = gdi.SelectObject(memory, bitmap)
        try:
            if not user.PrintWindow(hwnd, memory, 3):
                raise OSError('화면 읽기와 PrintWindow 캡처가 모두 지원되지 않습니다.')
            import struct
            info = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0))
            pixels = ctypes.create_string_buffer(width*height*4)
            if not gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0):
                raise OSError('창 이미지 읽기에 실패했습니다.')
            result = Image.frombytes('RGB', (width, height), pixels.raw, 'raw', 'BGRX')
            if len(result.getcolors(maxcolors=64) or []) == 1:
                raise OSError('창 캡처가 빈 화면을 반환했습니다.')
            return result
        finally:
            gdi.SelectObject(memory, old)
            gdi.DeleteObject(bitmap); gdi.DeleteDC(memory); user.ReleaseDC(hwnd, dc)


def capture(directory='artifacts/v0.9-1d'):
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    db = Database(':memory:')
    try:
        app = SimulatorApp(root, db, mode='story', seed=9)
        root.geometry('1280x680+60+40'); root.update()

        def save(widget, name):
            widget.lift(); root.update()
            frame = capture_client(widget)
            frame.save(destination/(name+'.png'))

        save(app.story_window, '01_story')
        app.story_window.skip_button.invoke(); app.story_window.next_button.invoke(); root.update()
        app.tutorial_highlight.clear()
        save(root, '02_server_normal')
        app.update_tutorial_highlight(); save(root, '03_server_action')
        app.network.select('A'); root.update()
        save(app.feedback_window, '04_server_feedback')
        dismiss_story_popups(app, root)
        app.resource_confirm_button.invoke(); dismiss_story_popups(app, root)
        save(root, '05_request_action')
        app.arrival_open_button.invoke(); root.update()
        app.message_window.reveal(); save(app.message_window, '06_customer_conditions')
        app.message_window.destroy(); dismiss_story_popups(app, root)
        plans = app.open_allocation_plans(); plans.plan_buttons[0].invoke(); root.update()
        save(plans, '07_plan_recommended')
        plans.plan_buttons[2].invoke(); root.update()
        save(plans, '08_plan_alternative')
        plans.start_button.invoke(); dismiss_story_popups(app, root)
        app.time_buttons[10].invoke(); root.update()
        save(root, '09_time_feedback_context')
        save(app.feedback_window, '10_time_feedback')
        print(f'화면 캡처 10개 저장: {destination.resolve()}')
    finally:
        root.destroy()
        db.close()


if __name__ == '__main__':
    capture()
