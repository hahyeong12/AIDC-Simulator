"""실제 Tk 위젯과 임시 SQLite로 화면과 게임 상태의 연결을 검증합니다."""
import sqlite3
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from main import SimulatorApp
from ui import CYAN, RED


class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk 화면 사용 불가: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.app = SimulatorApp(self.root, self.db)
        self.addCleanup(self.app.network.stop)
        self.dialogs = patch("main.messagebox")
        self.messages = self.dialogs.start()
        self.addCleanup(self.dialogs.stop)
        self.root.update()

    def test_customer_cards_and_actual_buttons_update_shared_resources(self):
        app = self.app
        app.select_mission(2)
        app.action_buttons["performance"].invoke()
        app.select_mission(3)
        app.action_buttons["performance"].invoke()
        self.assertEqual((app.center.gpu_used, app.center.power_used), (9, 10))
        self.assertIn("09 / 10", app.resources.gpu_label.cget("text"))
        app.select_mission(1)
        self.assertEqual(app.action_buttons["economy"].cget("state"), "disabled")
        self.assertIn("부족", app.action_buttons["economy"].cget("text"))
        self.assertIn("전력 4단위", app.action_buttons["economy"].cget("text"))
        app.select_mission(2)
        app.action_buttons["compress"].invoke()
        self.assertEqual((app.center.gpu_used, app.center.power_used), (6, 6))
        app.select_mission(1)
        self.assertEqual(app.action_buttons["economy"].cget("state"), "normal")
        self.assertEqual(self.errors, [])

    def test_network_warning_backup_and_log_survive_switch(self):
        app = self.app
        app.action_buttons["economy"].invoke()
        run_id = app.playthrough_id
        self.assertEqual(app.cards[1].status.cget("fg"), RED)
        self.assertTrue(app.network.find_withtag("packet"))
        app.select_mission(2)
        app.select_mission(1)
        self.assertIn("국제 네트워크", app.story.get("1.0", "end"))
        app.action_buttons["reroute"].invoke()
        self.assertTrue(app.network.find_withtag("backup"))
        self.assertEqual(app.network.itemcget(app.network.find_withtag("backup")[0], "fill"), CYAN)
        self.assertEqual(app.state.network_available, 6)
        self.assertIn("성공", app.cards[1].status.cget("text"))
        self.assertEqual(app.center.gpu_used, 0)
        self.assertEqual(app.history.item(str(run_id), "values")[-2:], ("성공", "80"))

    def test_resize_keeps_panels_inside_scrollable_page(self):
        app = self.app
        self.root.deiconify()
        for width, height in ((1360, 940), (980, 680), (1100, 760)):
            self.root.geometry(f"{width}x{height}")
            self.root.update()
            content = app.scroll.content
            for widget in (app.resources, app.network, app.action_frame, app.history):
                left = widget.winfo_rootx() - content.winfo_rootx()
                self.assertGreaterEqual(left, 0)
                self.assertLessEqual(left + widget.winfo_width(), content.winfo_width())
            app.scroll.canvas.yview_moveto(1)
            self.root.update()
            self.assertLess(app.action_frame.winfo_rooty(), self.root.winfo_rooty()+self.root.winfo_height())
        self.assertEqual(self.errors, [])

    def test_records_include_old_incomplete_runs_and_detail_window(self):
        app = self.app
        old_id = self.db.create_playthrough(1, "economy")
        self.db.add_log(old_id, "이전 기록 보존")
        app.refresh_history()
        self.assertEqual(app.history.item(str(old_id), "values")[-2], "이전 실행 미완료")
        app.history.selection_set(str(old_id))
        app.show_record()
        self.root.update()
        dialogs = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(dialogs), 1)
        frame = dialogs[0].winfo_children()[0]
        text = next(w for w in frame.winfo_children() if isinstance(w, tk.Text))
        self.assertIn("이전 기록 보존", text.get("1.0", "end"))

    def test_close_save_failure_keeps_window_and_active_state(self):
        app = self.app
        app.choose_plan("economy")
        with patch.object(self.db, "save_result", side_effect=sqlite3.OperationalError("실패")):
            app.on_close()
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(app.state.phase, "incident")
        self.assertEqual(app.center.gpu_used, 4)
        self.assertIsNotNone(app.network.timer)
        self.messages.showerror.assert_called_once()

    def test_hover_and_tooltip_callbacks_have_no_errors(self):
        button = self.app.action_buttons["economy"]
        original = button.cget("bg")
        button.event_generate("<Enter>")
        self.root.update()
        self.assertNotEqual(button.cget("bg"), original)
        button.event_generate("<Leave>")
        self.root.update()
        self.assertEqual(button.cget("bg"), original)
        self.assertEqual(self.errors, [])
