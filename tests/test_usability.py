"""상황별 지연 안내와 실제 Tk 자원·대화 표시의 회귀 검증."""
from copy import deepcopy
import sqlite3
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from main import SimulatorApp
from session import GameSession
from ui import MessageDialog, CUSTOMER_COLORS


class DelayNoticeTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=9, incident_chance=0)

    def japan_late(self):
        self.s.deliver_next_request()
        self.s.select(2)
        self.s.choose_plan('economy')
        return self.s.current

    def test_on_time_pending_and_closed_jobs_have_no_notice_reason(self):
        for action in (lambda: None, self.s.accept_request, lambda: self.s.choose_plan('performance')):
            action()
            self.assertEqual(self.s.delay_reason(self.s.current), '')
            self.assertFalse(self.s.can_notify_delay(self.s.current))
        self.s.report_failure()
        self.assertFalse(self.s.can_notify_delay(self.s.current))
        self.assertEqual(self.s.delay_reason(self.s.current), '')

    def test_reason_shows_deadline_estimate_and_lateness_in_minutes(self):
        run = self.japan_late()
        reason = self.s.delay_reason(run)
        for text in ('완료 기한 D1 10:10', '예상 완료 D1 10:30', '20분 지연 예상'):
            self.assertIn(text, reason)
        self.s.notify_delay()
        self.assertIn(reason, '\n'.join(run.messages))
        self.assertEqual(run.state.cost_penalty, 5)
        self.assertEqual(run.terms['due'], 610)

    def test_same_schedule_is_not_renotified_as_time_and_work_advance(self):
        run = self.japan_late()
        self.s.notify_delay()
        for _ in range(6):
            self.s.advance_time(10)
            self.assertFalse(self.s.can_notify_delay(run))
            with self.assertRaises(ValueError):
                self.s.notify_delay()
        notices = [e for e in self.db.get_request_events(2) if e['kind'] == 'notice']
        self.assertEqual(len(notices), 1)
        self.assertEqual(run.state.cost_penalty, 5)

    def test_actual_deadline_breach_can_be_reported_once_then_completion_blocks(self):
        run = self.japan_late()
        self.s.notify_delay()
        self.s.advance_time(60)
        self.s.advance_time(10)
        self.assertFalse(self.s.can_notify_delay(run))  # 기한과 같은 시각
        self.s.advance_time(10)
        self.assertIn('현재 10분 기한 초과', self.s.delay_reason(run))
        self.assertTrue(self.s.can_notify_delay(run))
        self.s.notify_delay()
        self.assertFalse(self.s.can_notify_delay(run))
        self.s.advance_time(10)
        self.assertTrue(run.state.succeeded)
        self.assertFalse(self.s.can_notify_delay(run))

    def test_new_incident_after_schedule_notice_allows_new_notice(self):
        run = self.japan_late()
        self.s.notify_delay()
        run.state.incident_at = 7
        self.s.advance_time(10)
        self.assertIn('네트워크 장애', self.s.delay_reason(run))
        self.assertTrue(self.s.can_notify_delay(run))
        self.s.notify_delay()
        self.s.advance_time(10)
        self.assertFalse(self.s.can_notify_delay(run))
        self.assertEqual(len([e for e in self.db.get_request_events(2) if e['kind'] == 'notice']), 2)

    def test_recovery_update_can_be_reported_but_unchanged_resumed_schedule_cannot(self):
        run = self.japan_late()
        run.state.trigger_incident()
        self.s.notify_delay()
        self.s.respond('reroute')
        self.assertIn('복구·재처리 준비', self.s.delay_reason(run))
        self.assertTrue(self.s.can_notify_delay(run))
        self.s.notify_delay()
        self.s.advance_time(10)
        self.assertEqual(run.state.phase, 'running')
        self.assertFalse(self.s.can_notify_delay(run))

    def test_new_expected_finish_after_interruption_allows_schedule_update(self):
        run = self.japan_late()
        self.s.notify_delay()
        run.state.trigger_incident()
        self.s.advance_time(10)
        self.s.respond('reroute')
        self.s.advance_time(10)
        self.assertEqual(run.state.phase, 'running')
        self.assertTrue(self.s.can_notify_delay(run))
        self.assertIn('40분 지연 예상', self.s.delay_reason(run))

    def test_repeated_incident_after_recovery_has_its_own_notice(self):
        run = self.s.current
        self.s.choose_plan('performance')
        run.state.incident_at = 10
        self.s.advance_time(10)
        self.s.notify_delay()
        self.s.respond('reroute')
        self.s.advance_time(10)
        # 다음 장애는 정상 작업을 진행한 뒤 새로 발생한 사건입니다.
        run.state.incident_occurred = False
        run.state.incident_at = 20
        self.s.advance_time(10)
        self.assertEqual(run.state.phase, 'incident')
        self.assertTrue(self.s.can_notify_delay(run))
        self.s.notify_delay()
        self.assertFalse(self.s.can_notify_delay(run))

    def test_same_notice_stays_blocked_on_resume_and_old_runtime_upgrade(self):
        self.japan_late()
        self.s.notify_delay()
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if legacy:
                    payload = self.db.get_runtime(2)
                    payload.pop('delay_notice_key')
                    self.db.save_runtime(2, self.s.current.playthrough_id, payload)
                restored = GameSession(self.db)
                restored.select(2)
                self.assertTrue(restored.current.delay_notified)
                self.assertFalse(restored.can_notify_delay(restored.current))
                restored.current.state.trigger_incident()
                self.assertTrue(restored.can_notify_delay(restored.current))

    def test_failed_notice_save_restores_key_penalty_and_records(self):
        run = self.japan_late()
        before = deepcopy(run.delay_notice_key), run.state.cost_penalty, list(run.messages)
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('실패')):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.notify_delay()
        self.assertEqual((run.delay_notice_key, run.state.cost_penalty, run.messages), before)
        self.assertTrue(self.s.can_notify_delay(run))
        self.assertFalse(any(e['kind'] == 'notice' for e in self.db.get_request_events(2)))


class UsabilityGuiTests(unittest.TestCase):
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

    def test_rapid_next_previous_skip_cancel_old_typewriter_and_preserve_history(self):
        app = self.app
        before = list(map(tuple, self.db.get_request_events(1)))
        dialog = MessageDialog(self.root, '고객', '싱가포르',
                               [('운영팀', '첫 메시지'*80), ('고객', '둘째'*80), ('고객', '마지막'*80)])
        timer = dialog.timer
        self.assertIsNotNone(timer)
        self.assertFalse(hasattr(dialog, 'reveal_button'))
        dialog.next_button.invoke()
        self.assertEqual(dialog.index, 0)
        self.assertIsNone(dialog.timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        dialog.next_button.invoke()
        second_timer = dialog.timer
        dialog.previous_button.invoke()
        self.assertEqual(dialog.index, 0)
        self.assertNotIn(second_timer, self.root.tk.call('after', 'info'))
        for _ in range(4):
            dialog.next_button.invoke()
        self.assertEqual(dialog.index, 2)
        timer = dialog.timer
        dialog.skip_button.invoke()
        dialog.skip_button.invoke()
        self.assertEqual(dialog.bubble.get('1.0', 'end-1c'), '마지막'*80)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        full = dialog.show_all()
        self.assertIn('첫 메시지', full.text.get('1.0', 'end'))
        full.destroy()
        dialog.previous_button.invoke()
        timer = dialog.timer
        dialog.destroy()
        self.root.update()
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        self.assertEqual(list(map(tuple, self.db.get_request_events(1))), before)
        self.assertEqual(self.errors, [])

    def test_delay_button_visibility_matches_reason_and_sending_hides_it(self):
        app = self.app
        self.assertNotIn('delay', app.action_buttons)
        app.choose_plan('performance')
        self.assertNotIn('delay', app.action_buttons)
        app.state.trigger_incident()
        app.refresh()
        self.assertIn('delay', app.action_buttons)
        self.assertIn('네트워크 장애', app.action_hint.cget('text'))
        app.action_buttons['delay'].invoke()
        self.assertNotIn('delay', app.action_buttons)
        app.respond('reroute')
        self.assertIn('delay', app.action_buttons)
        app.action_buttons['delay'].invoke()
        self.assertNotIn('delay', app.action_buttons)
        app._perform(app.session.report_failure)
        self.assertNotIn('delay', app.action_buttons)
        self.assertEqual(self.errors, [])

    def test_late_running_job_displays_specific_delay_explanation(self):
        app = self.app
        app.next_request()
        app.select_request(2)
        app.choose_plan('economy')
        self.assertIn('delay', app.action_buttons)
        self.assertIn('20분 지연 예상', app.action_hint.cget('text'))
        app.action_buttons['delay'].invoke()
        self.assertNotIn('delay', app.action_buttons)
        app.advance_time(60)
        app.advance_time(30)
        self.assertNotIn('delay', app.action_buttons)

    def test_gpu_blocks_and_power_gauge_match_three_customers(self):
        app = self.app
        app.next_request()
        app.next_request()
        for rid in (1, 2, 3):
            app.select_request(rid)
            app.choose_plan('economy')
        panel = app.resources
        self.assertEqual([int(panel.gpu_numbers[k].cget('text')) for k in ('total','used','available')], [10,10,0])
        self.assertEqual(len(panel.rack.find_withtag('gpu-block')), 10)
        self.assertEqual(len(panel.rack.find_withtag('used')), 10)
        colors = [panel.rack.itemcget(block, 'fill') for block in panel.rack.find_withtag('gpu-block')]
        for color, count in zip(CUSTOMER_COLORS, (4, 2, 4)):
            self.assertEqual(colors.count(color), count)
        self.assertEqual([w.cget('text') for w in panel.legend_labels], ['■ SG 4','■ JP 2','■ US 4'])
        self.assertIn('사용 9 / 가용 1 / 총 10', panel.power_label.cget('text'))
        total = panel.power.coords(panel.power.find_withtag('power-total')[0])[2]
        used = panel.power.coords(panel.power.find_withtag('power-used')[0])[2]
        self.assertAlmostEqual(used/total, .9)
        app.select_request(2)
        app.state.work_done = app.state.work_total-1
        app.advance_time(10)
        self.assertEqual(len(panel.rack.find_withtag('available')), 2)
        for block in panel.rack.find_withtag('available'):
            self.assertEqual(panel.rack.itemcget(block, 'fill'), CUSTOMER_COLORS[0])
        self.assertEqual(panel.gpu_numbers['used'].cget('text'), '8')
        self.assertIn('사용 7 / 가용 3', panel.power_label.cget('text'))

    def test_preview_shortage_and_exact_remaining_change_without_allocating(self):
        app = self.app
        app.next_request()
        app.next_request()
        app.select_request(3)
        app.choose_plan('economy')
        app.select_request(1)
        before = (app.center.gpu_used, app.center.power_used)
        text = app.resources.preview.cget('text')
        for expected in ('GPU 7 필요 / 가용 6 → 부족 1', '전력 7 필요 / 가용 7 → 잔여 0', '배정 불가'):
            self.assertIn(expected, text)
        app.plan_var.set('economy')
        app.preview_plan()
        text = app.resources.preview.cget('text')
        for expected in ('GPU 4 필요 / 가용 6 → 잔여 2', '전력 4 필요 / 가용 7 → 잔여 3', '배정 가능'):
            self.assertIn(expected, text)
        self.assertEqual((app.center.gpu_used, app.center.power_used), before)
        self.assertFalse(hasattr(app.resources, 'preview_bar'))
        app.action_buttons['start'].invoke()
        self.assertEqual(app.resources.preview_title.cget('text'), '현재 작업 점유 자원')
        self.assertIn('현재 작업 GPU 4 / 전력 4', app.resources.preview.cget('text'))
        self.assertNotIn('가용', app.resources.preview.cget('text'))
        self.assertNotIn('필요', app.resources.preview.cget('text'))

    def test_power_only_shortage_and_closed_request_hide_assignment_preview(self):
        app = self.app
        app.choose_plan('performance')
        app.next_request()
        app.select_request(2)
        text = app.resources.preview.cget('text')
        self.assertIn('GPU 3 필요 / 가용 3 → 잔여 0', text)
        self.assertIn('전력 4 필요 / 가용 3 → 부족 1', text)
        self.assertIn('배정 불가', text)
        app._perform(lambda: app.session.reject_request('전력 부족'))
        self.assertIn('배정 자원 없음', app.resources.preview.cget('text'))
        self.assertNotIn('필요', app.resources.preview.cget('text'))
        app.select_request(1)
        app.state.work_done = app.state.work_total-1
        app.advance_time(10)
        self.assertIn('자원 반환 완료', app.resources.preview.cget('text'))

    def test_laptop_and_minimum_layout_show_complete_resource_text_and_controls(self):
        app = self.app
        # OS 테두리와 작업 표시줄을 뺀 노트북 작업 영역 및 기존 최소 크기입니다.
        for state in ('pending','running','incident','recovering','finished'):
            if state == 'running':
                app.choose_plan('performance')
            elif state == 'incident':
                app.state.trigger_incident()
                app.refresh()
            elif state == 'recovering':
                app.respond('reroute')
            elif state == 'finished':
                app.state.work_done = app.state.work_total-1
                app.advance_time(30)
            for width, height in ((1366, 768), (1280, 680), (1000, 650)):
                with self.subTest(state=state, size=(width,height)):
                    self.root.geometry(f'{width}x{height}')
                    self.root.update()
                    panel = app.resources
                    for widget in (panel.preview, panel.preview_title, panel.rack, panel.power,
                                   *panel.gpu_numbers.values(), app.action_hint,
                                   *app.action_buttons.values(), *app.time_buttons.values()):
                        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
                    self.assertGreaterEqual(panel.preview.winfo_height(), panel.preview.winfo_reqheight())
                    self.assertFalse(hasattr(app, 'scroll'))
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
