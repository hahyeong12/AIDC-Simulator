"""v0.5 요청·자원·저장 복구 보장을 v0.6 실제 Tk 화면에서 검증합니다."""
import sqlite3
import tkinter as tk
import unittest
from unittest.mock import patch
from database import Database
from main import SimulatorApp
from test_operations import finish_current
from ui import CYAN


class GuiTests(unittest.TestCase):
    def setUp(self):
        try: self.root=tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        self.root.withdraw(); self.addCleanup(self.root.destroy)
        self.db=Database(':memory:'); self.addCleanup(self.db.close)
        self.errors=[]; self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.app=SimulatorApp(self.root,self.db,incident_chance=0)
        self.addCleanup(self.app.network.stop)
        p=patch('main.messagebox'); self.messages=p.start(); self.addCleanup(p.stop)
        self.root.update()

    def test_customer_cards_and_actual_buttons_update_shared_resources(self):
        a=self.app; a.next_request(); a.next_request()
        a.select_request(2); a.action_buttons['start'].invoke()
        a.select_request(3); a.action_buttons['start'].invoke()
        self.assertEqual((a.center.gpu_used,a.center.power_used),(9,10))
        self.assertIn('사용 9',a.resources.gpu_label.cget('text'))
        a.select_request(1); a.plan_var.set('economy'); a.preview_plan()
        self.assertEqual(a.action_buttons['start'].cget('state'),'disabled')
        self.assertIn('부족',a.resources.preview.cget('text'))
        a.select_request(2); a.state.work_done=a.state.work_total-1; a.advance_time(10)
        self.assertEqual(a.center.gpu_used,6)
        a.select_request(1)
        self.assertEqual(a.action_buttons['start'].cget('state'),'normal')
        self.assertEqual(self.errors,[])

    def test_network_warning_backup_and_log_survive_switch(self):
        a=self.app; a.choose_plan('economy'); run_id=a.playthrough_id
        a.state.incident_at=7; a.advance_time(10)
        self.assertIn('장애',a.alert.cget('text'))
        a.next_request(); a.select_request(2); a.select_request(1)
        self.assertEqual(a.state.phase,'incident')
        a.action_buttons['reroute'].invoke()
        self.assertTrue(a.network.find_withtag('backup'))
        self.assertEqual(a.network.itemcget(a.network.find_withtag('backup')[0],'fill'),CYAN)
        self.assertEqual(a.state.phase,'recovering')
        self.assertEqual(a.center.gpu_used,4)
        finish_current(a.session); a.refresh()
        self.assertEqual(a.center.gpu_used,0)
        win=a.show_history()
        self.assertEqual(tuple(a.history.item(str(run_id),'values'))[-2:],('성공','80'))
        win.destroy()

    def test_resize_keeps_panels_inside_console(self):
        a=self.app; a.next_request(); a.next_request(); a.wait_request(); self.root.deiconify()
        for w,h in ((1280,680),(1000,650),(1840,980)):
            self.root.geometry(f'{w}x{h}'); self.root.update()
            for widget in (a.resources.preview,a.network,a.action_frame,*a.time_buttons.values()):
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        self.assertEqual(self.errors,[])

    def test_records_include_old_incomplete_runs_and_detail_window(self):
        a=self.app; old=self.db.create_playthrough(1,'economy'); self.db.add_log(old,'이전 기록 보존')
        history=a.show_history()
        self.assertEqual(a.history.item(str(old),'values')[-2],'이전 실행 미완료')
        a.history.selection_set(str(old)); dialog=a.show_record()
        self.assertIn('이전 기록 보존',dialog.text.get('1.0','end'))
        dialog.destroy(); history.destroy()

    def test_close_save_failure_keeps_window_and_active_state(self):
        a=self.app; a.choose_plan('economy')
        with patch.object(self.db,'save_simulation',side_effect=sqlite3.OperationalError('실패')): a.on_close()
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(a.state.phase,'running')
        self.assertEqual(a.center.gpu_used,4)
        self.assertIsNotNone(a.network.timer)
        self.messages.showerror.assert_called_once()

    def test_hover_and_tooltip_callbacks_have_no_errors(self):
        self.root.deiconify(); self.root.update()
        button=self.app.action_buttons['start']; before=button.cget('bg')
        button.event_generate('<Enter>'); self.root.update()
        self.assertNotEqual(button.cget('bg'),before)
        button.event_generate('<Leave>'); self.root.update()
        self.assertEqual(button.cget('bg'),before)
        self.assertEqual(self.errors,[])

    def test_initial_inbox_message_notification_and_read_receipt(self):
        a=self.app
        self.assertEqual(len(a.inbox.get_children()),1)
        self.assertIn('1건',a.notice_var.get())
        self.assertTrue(a.network.find_withtag('empty-network'))
        dialog=a.open_latest_message(); dialog.reveal()
        self.assertEqual(a.session.current.request['status'],'review')
        self.assertIn('Merlion AI',dialog.title())
        self.assertIn('모든 메시지',a.notice_var.get())
        dialog.destroy()

    def test_auto_arrival_preserves_selected_job_and_marks_new_request(self):
        a=self.app; a.choose_plan('economy'); state,run_id=a.state,a.playthrough_id
        a.time_buttons[30].invoke()
        self.assertGreaterEqual(len(a.inbox.get_children()),2)
        self.assertIs(a.state,state); self.assertEqual(a.playthrough_id,run_id)
        self.assertEqual(state.work_done,21)
        self.assertIn('●',a.inbox.item('2','values')[0])
        self.assertEqual(a.arrival_open_button.cget('state'),'normal')
        self.assertIn('새 요청', a.arrival_notice.cget('text'))
        self.assertEqual(a.center.gpu_used,4)

    def test_waiting_group_then_accept_has_no_premature_allocation(self):
        a=self.app; a.action_buttons['wait'].invoke()
        self.assertEqual(a.session.current.request['status'],'waiting')
        self.assertIn('대기',a.inbox.item('1','values')[1])
        self.assertEqual(a.center.gpu_used,0)
        a.plan_var.set('economy'); a.preview_plan(); a.action_buttons['start'].invoke()
        self.assertEqual(a.session.current.request['status'],'operating')
        self.assertEqual(a.state.phase,'running')
        self.assertEqual(a.center.gpu_used,4)

    def test_rejection_dialog_requires_reason_and_keeps_rejection_separate(self):
        a=self.app; dialog=a.show_rejection()
        with patch('ui.messagebox') as messages:
            dialog.confirm_button.invoke(); dialog.reason.set('기타 사유'); dialog.confirm_button.invoke()
            self.assertEqual(messages.showwarning.call_count,2)
            dialog.note.insert('1.0','요청 조건 재검토 필요'); dialog.confirm_button.invoke()
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(a.session.current.request['status'],'rejected')
        self.assertIn('재검토',a.session.current.request['rejection_reason'])
        self.assertEqual(self.db.get_recent_records(),[])
        self.assertEqual(a.center.gpu_used,0)
        self.assertNotIn('start',a.action_buttons)

    def test_rejection_save_failure_leaves_dialog_open_for_retry(self):
        a=self.app; dialog=a.show_rejection(); dialog.reason.set('현재 GPU 자원 부족')
        with patch.object(self.db,'change_request_status',side_effect=sqlite3.OperationalError('실패')): dialog.confirm_button.invoke()
        self.assertTrue(dialog.winfo_exists()); self.assertEqual(a.session.current.request['status'],'new')
        dialog.confirm_button.invoke()
        self.assertFalse(dialog.winfo_exists()); self.assertEqual(a.session.current.request['status'],'rejected')
        self.assertEqual(self.errors,[])
