"""스크롤 없는 관제실과 단계별 메신저를 실제 Tk로 검증합니다."""
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from main import SimulatorApp
from ui import MessageDialog


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, seed=9, incident_chance=0)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()

    def test_primary_controls_fit_work_area_without_page_scroll(self):
        app = self.app
        app.next_request()
        app.next_request()
        for rid in (1,2,3):
            app.select_request(rid)
            app.choose_plan('economy')
        app.state.trigger_incident()
        app.refresh()
        for width, height in ((1280, 680), (1000, 650), (1840, 980)):
            self.root.geometry(f'{width}x{height}')
            self.root.update()
            widgets = [app.inbox, app.active_list, app.resources.preview, app.network,
                       app.controls, app.arrival_notice, app.arrival_open_button, app.arrival_schedule,
                       *app.time_buttons.values(), *app.action_buttons.values()]
            for widget in widgets:
                with self.subTest(size=(width,height), widget=str(widget)):
                    x = widget.winfo_rootx()-self.root.winfo_rootx()
                    y = widget.winfo_rooty()-self.root.winfo_rooty()
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x+widget.winfo_width(), self.root.winfo_width())
                    self.assertLessEqual(y+widget.winfo_height(), self.root.winfo_height())
            self.assertFalse(hasattr(app, 'scroll'))
            self.assertGreaterEqual(app.resources.preview.winfo_height(), app.resources.preview.winfo_reqheight())
        for _ in range(3):
            app.respond('ignore')
        self.root.geometry('1000x650')
        self.root.update()
        for widget in (app.resources.preview, app.action_hint, *app.action_buttons.values(), *app.time_buttons.values()):
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
        self.assertEqual(self.errors, [])

    def test_mode_preview_never_allocates_real_resources(self):
        app = self.app
        before = (app.center.gpu_used, app.center.power_used)
        app.plan_var.set('economy')
        app.preview_plan()
        self.assertIn('GPU 4', app.resources.preview.cget('text'))
        app.mode_buttons['performance'].event_generate('<Enter>')
        self.root.update()
        self.assertIn('GPU 7', app.resources.preview.cget('text'))
        self.assertEqual((app.center.gpu_used, app.center.power_used), before)

    def test_messenger_previous_next_full_view_and_skip(self):
        dialog = MessageDialog(self.root, 'Merlion AI', '싱가포르',
                               [('고객','첫 메시지'), ('고객','요청 자원'), ('시스템','가용 자원')], animate=False)
        self.root.update()
        self.assertEqual(dialog.index, 0)
        dialog.next_button.invoke()
        self.assertEqual(dialog.index, 1)
        dialog.previous_button.invoke()
        self.assertEqual(dialog.index, 0)
        full = dialog.show_all()
        self.assertIn('가용 자원', full.text.get('1.0','end'))
        full.destroy()
        dialog.destroy()
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_typewriter_can_be_revealed_and_cancelled(self):
        dialog = MessageDialog(self.root, '고객', '일본', [('고객','가'*120)])
        self.assertLess(dialog.shown, len(dialog.full_text))
        dialog.reveal()
        self.assertEqual(dialog.shown, len(dialog.full_text))
        self.assertIsNone(dialog.timer)
        dialog.destroy()
        self.root.update()
        self.assertEqual(self.errors, [])

    def test_notification_opens_large_message_and_marks_read(self):
        dialog = self.app.open_latest_message()
        self.root.update()
        self.assertGreater(dialog.winfo_width(), 600)
        self.assertEqual(self.app.session.current.request['is_read'], 1)
        self.assertIn('Merlion AI', dialog.title())
        dialog.destroy()

    def test_long_details_are_separate_windows(self):
        popup = self.app.show_events()
        self.assertIsInstance(popup, tk.Toplevel)
        popup.destroy()
        popup = self.app.show_history()
        self.assertTrue(self.app.history.winfo_exists())
        popup.destroy()

    def test_automatic_notice_opens_matching_request_without_advancing_time(self):
        app=self.app
        app.choose_plan('economy')
        state=app.state
        app.time_buttons[30].invoke()
        self.assertEqual(len(app.session.runs),3)
        rid=app.arrival_request_id
        incoming=app.session.runs[rid]
        notice=app.arrival_notice.cget('text')
        self.assertIn(incoming.mission['company_name'],notice)
        self.assertIn(incoming.mission['title'],notice)
        self.assertIn(f'필요 GPU {incoming.state.plans["performance"]["gpu"]}',notice)
        self.assertIn('가용 GPU 6',notice)
        self.assertEqual(app.session.selected_id,1)
        self.assertEqual(state.work_done,21)
        self.root.geometry('1000x650')
        self.root.update()
        bottom=app.body.winfo_rooty()+app.body.winfo_height()
        for widget in (app.arrival_notice,app.arrival_open_button,app.arrival_schedule,app.active_list):
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),bottom)
        app.arrival_open_button.invoke()
        self.root.update()
        self.assertIn(incoming.mission['company_name'],app.message_window.title())
        self.assertEqual(app.session.selected_id,rid)
        self.assertEqual(incoming.request['is_read'],1)
        self.assertEqual((app.session.minute,state.work_done,app.center.gpu_used),(570,21,4))
        self.assertFalse(hasattr(app,'next_request_button'))
        app.message_window.destroy()
        self.assertEqual(self.errors,[])

    def test_japan_time_button_updates_progress_clock_and_saved_allocation(self):
        app=self.app
        app.next_request(); app.select_request(2); app.choose_plan('performance')
        self.assertEqual(app.state.progress,0)
        self.assertIn('+10',app.action_hint.cget('text'))
        app.time_buttons[10].invoke()
        self.assertAlmostEqual(app.state.progress,100/6)
        self.assertIn('17%',app.active_list.item('2','values')[1])
        self.assertIn('09:10',app.status_var.get())
        self.assertEqual((app.center.gpu_used,app.center.power_used),(3,4))
        self.assertEqual(self.db.get_runtime(2)['state']['work_done'],10)

    def test_actual_next_previous_skip_buttons_keep_sequence_consistent(self):
        dialog = MessageDialog(self.root, '고객', '일본',
                               [('고객','첫 메시지'*60), ('고객','중간'*60), ('고객','마지막'*60)])
        self.assertFalse(hasattr(dialog, 'reveal_button'))
        dialog.next_button.invoke()
        self.assertEqual(dialog.bubble.get('1.0','end-1c'), dialog.full_text)
        self.assertIsNone(dialog.timer)
        dialog.next_button.invoke()
        self.assertEqual(dialog.index, 1)
        dialog.next_button.invoke()  # 타이핑 중 첫 다음은 현재 페이지를 전부 표시
        self.assertEqual(dialog.index, 1)
        self.assertEqual(dialog.shown, len(dialog.full_text))
        dialog.previous_button.invoke()
        self.assertEqual(dialog.index, 0)
        dialog.skip_button.invoke()
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(dialog.index, 2)
        self.assertEqual(dialog.bubble.get('1.0','end-1c'), '마지막'*60)
        dialog.skip_button.invoke()
        self.assertEqual(dialog.index, 2)
        full = dialog.show_all()
        for word in ('첫 메시지','중간','마지막'):
            self.assertIn(word, full.text.get('1.0','end'))
        full.destroy()
        dialog.next_button.invoke()
        self.root.update()
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(self.errors, [])

    def test_finished_job_dialog_does_not_replay_request_or_allow_delay(self):
        app = self.app
        app.choose_plan('performance')
        app.state.work_done = app.state.work_total-1
        app.advance_time(10)
        self.assertNotIn('delay', app.action_buttons)
        dialog = app.open_message(1)
        dialog.reveal()
        self.assertIn('작업 완료', dialog.bubble.get('1.0','end'))
        self.assertNotIn('[신규 작업 요청]', dialog.bubble.get('1.0','end'))
        self.assertEqual(len(dialog.steps), 1)
        history = app.show_conversation_history()
        self.assertIn('[신규 작업 요청]', history.text.get('1.0','end'))
        self.assertIn('작업 완료', history.text.get('1.0','end'))
        history.destroy(); dialog.destroy()

    def test_deadline_preview_colours_and_controls_at_laptop_size(self):
        from ui import AMBER, RED
        app = self.app
        app.next_request(); app.select_request(2)
        for mode, outcome in (('performance','기한 내 예상'),('economy','기한 초과 예상')):
            app.plan_var.set(mode); app.preview_plan()
            text = app.resources.preview.cget('text')
            self.assertIn('고성능 60분 → D1 10:00', text)
            self.assertIn('절약형 90분 → D1 10:30', text)
            self.assertIn(outcome, text)
        app.advance_time(60)
        self.assertIn('대기 60분', app.action_hint.cget('text'))
        self.assertEqual(app.inbox.tag_configure('request-2')['foreground'], AMBER)
        app.advance_time(30)
        self.assertEqual(app.inbox.tag_configure('request-2')['foreground'], RED)
        for width,height in ((1280,680),(1000,650),(1366,700)):
            self.root.geometry(f'{width}x{height}'); self.root.update()
            for widget in (app.resources.preview, app.inbox, app.action_hint,
                           *app.action_buttons.values(), *app.time_buttons.values()):
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+height)
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+width)
            self.assertGreaterEqual(app.resources.preview.winfo_height(), app.resources.preview.winfo_reqheight())
            self.assertGreaterEqual(app.inbox.winfo_height(), 55)
        self.assertEqual(self.errors, [])

    def test_expired_requests_appear_in_history_separately_from_failed_jobs(self):
        app = self.app
        for _ in range(6): app.advance_time(60)
        history = app.show_history()
        self.assertIn('request-1', app.history.get_children())
        self.assertEqual(app.history.item('request-1','values')[-2:], ('미처리 · 기한 만료','0'))
        app.history.selection_set('request-1')
        detail = app.show_record()
        self.assertIn('미처리 종료', detail.text.get('1.0','end'))
        detail.destroy(); history.destroy()
