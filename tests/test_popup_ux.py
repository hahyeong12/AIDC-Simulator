"""v0.9-1d 실제 행동/피드백, 요청 조건, 시각적 강조와 카드 선택 회귀."""
from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from allocation_dialog import AllocationDialog
from database import Database
from game import game_time
from main import SimulatorApp
from request_summary import request_summary
from server_widgets import OWNER_COLORS, RED
from session import GameSession
from tests.support import dismiss_story_popups
from tests.test_story import gameplay
from tutorial_highlight import GOLD, GOLD_DIM
from window_placement import nearby_bounds, work_area


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:'); self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=9, incident_chance=0)

    def test_original_fields_use_real_request_and_are_read_only(self):
        run = self.s.current
        before = gameplay(self.s), '\n'.join(self.db.conn.iterdump())
        values = request_summary(run)
        self.assertEqual(values['고객명'], run.mission['company_name'])
        self.assertEqual(values['국가'], run.mission['country'])
        self.assertEqual(values['작업 종류'], run.conditions['task'])
        p = run.conditions['plans'][run.conditions['requested_mode']]
        self.assertEqual(values['요청 운영 모드'], p['label'])
        self.assertEqual(values['GPU 요구량'], str(p['gpu']))
        self.assertEqual(values['전력 요구량'], str(p['power']))
        self.assertEqual(values['접수 시각'], game_time(run.terms['received']))
        self.assertEqual(values['완료 기한'], game_time(run.terms['due']))
        self.assertEqual((gameplay(self.s), '\n'.join(self.db.conn.iterdump())), before)

    def test_different_customers_have_their_own_requirements(self):
        summaries = []
        for _ in range(3):
            run = self.s.current
            summary = request_summary(run)
            p = run.conditions['plans'][run.conditions['requested_mode']]
            self.assertEqual(summary['GPU 요구량'], str(p['gpu']))
            self.assertEqual(summary['전력 요구량'], str(p['power']))
            summaries.append(summary)
            self.s.deliver_next_request(); self.s.select(max(self.s.runs))
        self.assertEqual(len({r['국가'] for r in summaries}), 3)
        self.assertGreater(len({r['GPU 요구량'] for r in summaries}), 1)

    def test_pending_proposal_is_not_presented_as_agreement(self):
        self.s.propose_alternative()
        v = request_summary(self.s.current)
        self.assertIn('답변 대기', v['고객 동의'])
        self.assertIn('변경 제안 · 답변 대기', v)
        self.assertNotIn('동의한 변경 조건', v)
        self.assertEqual(v['GPU 요구량'], '7')

    def test_accepted_proposal_keeps_original_and_separates_changed_conditions(self):
        original = request_summary(self.s.current)
        self.s.propose_alternative(); self.s.review_alternative()
        v = request_summary(self.s.current)
        p = self.s.current.proposals[-1]['proposed']
        for name in ('GPU 요구량', '전력 요구량', '요청 운영 모드', '완료 기한'):
            self.assertEqual(v[name], original[name])
        self.assertIn(f'GPU {p["gpu"]} / 전력 {p["power"]}', v['동의한 변경 조건'])
        self.assertIn('동의 완료', v['고객 동의'])

    def test_rejected_proposal_keeps_original_permission(self):
        self.s.propose_alternative()
        for minutes in (60, 60, 60, 30, 10): self.s.advance_time(minutes)
        self.s.review_alternative()
        v = request_summary(self.s.current)
        self.assertIn('거절', v['고객 동의'])
        self.assertIn('변경 제안 · 거절됨', v)
        self.assertNotIn('동의한 변경 조건', v)

    def test_legacy_does_not_invent_requested_mode_resources_or_deadline(self):
        self.s.current.conditions = {}; self.s.current.terms = {}
        values = request_summary(self.s.current)
        for field in ('요청 운영 모드', 'GPU 요구량', '전력 요구량', '접수 시각', '완료 기한'):
            self.assertIn('기록 없음', values[field])

    def test_legacy_proposal_preserves_recorded_original(self):
        self.s.propose_alternative(); self.s.current.conditions = {}
        v = request_summary(self.s.current)
        self.assertEqual(v['GPU 요구량'], str(self.s.current.proposals[-1]['original']['gpu']))


class PopupFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.db = Database(':memory:'); self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, mode='story', seed=9)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()

    def dismiss(self):
        dismiss_story_popups(self.app, self.root)

    def arrival(self):
        self.app.story_window.skip_button.invoke(); self.app.story_window.next_button.invoke()
        self.root.update()

    def resources(self):
        self.arrival(); self.app.network.select('A'); self.dismiss()

    def request(self):
        self.resources(); self.app.resource_confirm_button.invoke(); self.dismiss()

    def preview(self):
        self.request(); self.app.arrival_open_button.invoke(); self.app.message_window.destroy(); self.dismiss()

    def allocation(self):
        self.preview(); self.app.resources.show_preview(); self.dismiss()

    def running(self):
        self.allocation(); self.app.action_buttons['start'].invoke(); self.dismiss()

    def test_story_to_action_to_success_feedback_to_next_action(self):
        self.assertEqual(self.app.story_phase, 'STORY')
        self.arrival()
        self.assertFalse(self.app.story_window.winfo_exists())
        self.assertEqual(self.app.story_phase, 'ACTION')
        self.assertEqual(self.app.tutorial_highlight.key, 'server')
        self.app.network.select('A'); self.root.update()
        self.assertEqual(self.app.story_phase, 'FEEDBACK')
        self.assertEqual(self.app.feedback_window.event, 'server')
        self.assertIsNone(self.root.grab_current())
        self.assertIsNone(self.app.tutorial_highlight.timer)
        self.dismiss()
        self.assertEqual(self.app.story_phase, 'ACTION')
        self.assertIs(self.app.tutorial_highlight.target, self.app.resource_confirm_button)
        self.app.resources.show_preview(); self.root.update()
        self.assertIs(self.app.tutorial_highlight.target, self.app.resources)
        self.app.tutorial_highlight.pointer.event_generate('<Button-1>'); self.root.update()
        self.assertEqual(self.app.resources.book.select(), str(self.app.resources.inspector_frame))
        self.assertIs(self.app.tutorial_highlight.target, self.app.resource_confirm_button)
        self.assertFalse(self.app.session.story.resources_confirmed)

    def test_feedback_acknowledgment_never_completes_next_action(self):
        self.arrival(); self.app.network.select('A')
        before = deepcopy(self.app.session.story.payload()), gameplay(self.app.session)
        self.app.feedback_window.close_button.invoke(); self.root.update()
        self.assertEqual((self.app.session.story.payload(), gameplay(self.app.session)), before)
        self.assertFalse(self.app.session.story.resources_confirmed)

    def test_wrong_server_and_dialogue_pages_do_not_complete_server_action(self):
        self.arrival(); self.app.network.select('B')
        self.assertEqual(self.app.session.story.step, 'server')
        self.assertIsNone(self.app.feedback_window)
        d = self.app.show_story_help(); d.skip_button.invoke(); d.next_button.invoke(); self.root.update()
        self.assertEqual(self.app.session.story.step, 'server')
        self.assertIsNone(self.app.feedback_window)

    def test_request_target_survives_read_marker_refresh_and_button_replacement(self):
        self.request()
        self.app.select_request(self.app.session.story.request_id)
        self.assertTrue(self.app.session.current.request['is_read'])
        self.assertFalse(self.app.session.story.request_read)
        for _ in range(5): self.app.refresh()
        self.root.update()
        h = self.app.tutorial_highlight
        self.assertIs(h.target, self.app.arrival_open_button)
        self.assertEqual(h.target.cget('state'), 'normal')
        self.assertTrue(h.target.winfo_ismapped())
        self.assertEqual(len(h.edges), 8)
        self.assertTrue(all(e.winfo_ismapped() and e.winfo_width() > 0 and e.winfo_height() > 0 for e in h.edges))
        self.assertTrue(h.pointer.winfo_ismapped())
        self.assertIn('여기를 클릭', h.pointer.cget('text'))
        self.assertEqual(h.target.cget('fg'), GOLD)

    def test_emphasis_has_double_rack_border_caption_and_distinct_color(self):
        self.arrival(); c = self.app.network
        self.assertEqual(len(c.find_withtag('tutorial-highlight')), 1)
        self.assertEqual(len(c.find_withtag('tutorial-glow')), 1)
        self.assertIn('여기를 클릭', c.itemcget(c.find_withtag('tutorial-caption')[0], 'text'))
        border = c.find_withtag('tutorial-highlight')[0]
        self.assertGreaterEqual(float(c.itemcget(border, 'width')), 4)
        self.assertNotIn(c.itemcget(border, 'outline'), (*OWNER_COLORS.values(), RED))
        self.root.tk.call('after', 520); self.root.update()
        self.assertEqual(len(c.find_withtag('tutorial-glow')), 1)
        self.assertEqual(len(c.find_withtag('tutorial-caption')), 1)

    def test_repeated_action_refresh_and_reopening_do_not_duplicate_feedback(self):
        self.arrival(); self.app.network.select('A')
        d = self.app.feedback_window
        for _ in range(4): self.app.network.select('A'); self.app.refresh()
        self.assertIs(self.app.feedback_window, d)
        self.dismiss()
        for _ in range(4): self.app.show_story_event(); self.app.refresh()
        self.root.update()
        self.assertFalse(d.winfo_exists())
        self.assertEqual(len(self.app.feedback_events), 1)

    def test_customer_window_defers_feedback_until_after_reading(self):
        self.request(); self.app.arrival_open_button.invoke(); self.root.update()
        self.assertEqual(self.app.session.story.step, 'preview')
        self.assertFalse(self.app.feedback_window.winfo_exists())
        self.assertNotIn('preview', self.app.session.story.dialogue_seen)
        self.app.message_window.destroy(); self.root.update()
        self.assertEqual(self.app.feedback_window.event, 'request')
        self.assertIn('preview', self.app.session.story.dialogue_seen)

    def test_allocation_success_waits_for_comparison_close(self):
        self.preview(); d = self.app.open_allocation_plans(); self.root.update()
        d.plan_buttons[1].invoke()
        self.assertEqual(self.app.center.gpu_used, 0)
        parts = d.options[1]; d.start_button.invoke(); self.root.update()
        self.assertEqual(self.app.feedback_window.event, 'allocation')
        self.assertEqual(self.app.session.current.server_allocations[-1].slices, parts)
        self.assertEqual(self.app.center.gpu_used, 7)

    def test_plus_ten_feedback_is_near_button_and_does_not_cover_it(self):
        self.running()
        button = self.app.time_buttons[10]
        anchor = self.app.story_anchor('time')
        self.app.time_buttons[10].invoke(); self.root.update()
        d = self.app.feedback_window
        self.assertEqual(d.event, 'time')
        self.assertGreater(self.app.state.work_done, 0)
        self.assert_no_overlap(d, anchor)
        self.assertLess(abs(d.winfo_rootx()-anchor[0])+abs(d.winfo_rooty()-anchor[1]), 550)
        self.assertFalse(self.app.session.story.operations_confirmed)
        self.dismiss()
        self.assertFalse(self.app.session.story.operations_confirmed)
        self.assertEqual(self.app.tutorial_highlight.key, 'operations')

    def assert_no_overlap(self, dialog, anchor):
        x, y, w, h = anchor
        dx, dy = dialog.winfo_rootx(), dialog.winfo_rooty()
        self.assertTrue(dx+dialog.winfo_width() <= x or x+w <= dx or
                        dy+dialog.winfo_height() <= y or y+h <= dy)

    def test_feedback_has_no_expiry_timer_and_remains_until_confirmed(self):
        self.arrival(); self.app.network.select('A'); self.root.update()
        d = self.app.feedback_window
        before = set(self.root.tk.call('after', 'info'))
        self.root.tk.call('after', 550); self.root.update()
        self.assertTrue(d.winfo_exists())
        self.assertEqual(self.app.story_phase, 'FEEDBACK')
        self.assertIsNone(self.app.tutorial_highlight.timer)
        self.assertEqual(self.errors, [])

    def test_failed_actual_action_has_no_success_feedback(self):
        self.arrival()
        before = deepcopy(self.app.session.story.payload()), gameplay(self.app.session)
        with patch.object(self.db, 'save_runtime', side_effect=OSError('실패')), patch('main.messagebox.showerror'):
            self.app.network.select('A')
        self.assertEqual((self.app.session.story.payload(), gameplay(self.app.session)), before)
        self.assertIsNone(self.app.feedback_window)
        self.assertEqual(self.app.tutorial_highlight.key, 'server')

    def test_failed_feedback_history_save_preserves_actual_action_and_can_retry(self):
        self.arrival()
        with patch.object(self.app.session, 'mark_story_dialogue', side_effect=OSError('표시 저장 실패')), patch('main.messagebox.showerror'):
            self.app.network.select('A')
        self.assertEqual(self.app.session.story.step, 'resources')
        self.assertEqual(self.app.session.story.selected_server, 'A')
        self.assertFalse(self.app.feedback_window.winfo_exists())
        self.assertEqual(self.app.feedback_events, set())
        d = self.app.show_story_event(); self.root.update()
        self.assertEqual(d.event, 'server')
        self.dismiss(); self.assertEqual(len(self.app.feedback_events), 1)

    def test_partial_feedback_screen_failure_cleans_only_new_window_and_preserves_action(self):
        self.arrival()
        def fail(parent, *_args, **_kwargs):
            tk.Toplevel(parent)
            raise RuntimeError('피드백 화면 생성 실패')
        with patch('main.StoryFeedbackDialog', side_effect=fail), patch('main.messagebox.showerror'):
            self.app.network.select('A')
        self.assertEqual(self.app.session.story.step, 'resources')
        self.assertFalse(any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()))
        self.assertIsNotNone(self.app.pending_feedback)
        self.assertEqual(self.app.tutorial_highlight.key, 'resources')
        self.assertEqual(self.app.feedback_events, set())
        self.assertEqual(self.errors, [])

    def test_mode_switch_closes_feedback_and_cancels_deferred_work(self):
        self.arrival(); self.app.network.select('A')
        d = self.app.feedback_window
        self.app.db_factory = lambda _: Database(':memory:')
        self.app.return_to_modes('free'); self.root.update()
        free = self.app.mode_selector.app
        self.addCleanup(free.db.close)
        self.assertFalse(d.winfo_exists())
        self.assertIsNone(self.app.story_event_timer)
        self.assertIsNone(free.feedback_window)
        self.assertIsNone(free.tutorial_highlight.timer)
        self.assertEqual(self.errors, [])

    def test_conditions_visible_above_customer_dialogue_and_page_controls_remain(self):
        self.request(); d = self.app.open_message(1); self.root.update()
        self.assertEqual(d.summary_values, request_summary(self.app.session.current))
        self.assertLess(d.summary_frame.winfo_rooty(), d.bubble.winfo_rooty())
        self.assertTrue(d.summary_frame.winfo_ismapped())
        index = d.index; d.reveal(); d.next_button.invoke()
        self.assertEqual(d.index, min(index+1, len(d.steps)-1))
        self.assertEqual(d.summary_values['GPU 요구량'], '7')
        self.assertEqual(self.app.center.gpu_used, 0)

    def test_small_feedback_layout_and_condition_table_fit_resolutions(self):
        self.arrival()
        for size in ('1000x650', '1280x680', '1366x768', 'zoomed'):
            with self.subTest(size=size):
                if size == 'zoomed': self.root.state('zoomed')
                else: self.root.state('normal'); self.root.geometry(size)
                self.root.update()
                # 표시만 검증하며 업무 상태는 바꾸지 않습니다.
                from story_feedback import StoryFeedbackDialog
                anchor = self.app.story_anchor('time')
                d = StoryFeedbackDialog(self.root, 'time', self.app.session.story.objective, anchor)
                self.root.update()
                self.assert_no_overlap(d, anchor)
                for widget in (d.heading, d.body, d.goal, d.close_button):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), d.winfo_rooty()+d.winfo_height())
                d.destroy()
                from ui import MessageDialog
                run = self.app.session.current
                message = MessageDialog(self.root, run.mission['company_name'], run.mission['country'],
                                        self.app.session.conversation(run.request['id']), animate=False,
                                        summary=request_summary(run))
                self.root.update()
                for widget in (message.summary_frame, message.bubble, message.page, message.next_button, message.skip_button):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreaterEqual(widget.winfo_rooty(), message.winfo_rooty())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), message.winfo_rooty()+message.winfo_height())
                message.destroy()

    def test_free_mode_shows_agreed_summary_without_changing_conversation_or_resources(self):
        root = tk.Toplevel(self.root)
        db = Database(':memory:'); self.addCleanup(db.close)
        free = SimulatorApp(root, db, seed=9)
        free.session.propose_alternative(); free.session.review_alternative()
        contract = deepcopy(free.session.current.conditions)
        d = free.open_message(1); self.root.update()
        self.assertIn('동의한 변경 조건', d.summary_values)
        self.assertEqual(d.summary_values['GPU 요구량'], '7')
        self.assertEqual(free.session.current.conditions, contract)
        self.assertEqual(free.center.gpu_used, 0)
        self.assertIsNone(free.tutorial_highlight.target)
        self.assertIsNone(free.feedback_window)
        root.destroy(); self.root.update()
        self.assertEqual(self.errors, [])


class CardTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.root.geometry('1000x650+50+40')
        self.db = Database(':memory:'); self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=9, incident_chance=0)
        self.d = AllocationDialog(self.root, self.s, 'performance', lambda *_: False)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()

    def test_card_background_and_all_label_regions_select_exact_plan_without_resources(self):
        before = gameplay(self.s), '\n'.join(self.db.conn.iterdump())
        for i, card in enumerate(self.d.plan_cards):
            for widget in (card, *[w for w in card.winfo_children() if w.winfo_class() == 'Label']):
                self.d.selection.set(-1)
                widget.event_generate('<Button-1>', x=2, y=2); self.root.update()
                self.assertEqual(self.d.selection.get(), i)
                self.assertIn('선택 중', self.d.plan_buttons[i].cget('text'))
        self.assertEqual((gameplay(self.s), '\n'.join(self.db.conn.iterdump())), before)

    def test_selected_card_has_distinct_background_and_border_and_previous_clears(self):
        self.d.plan_buttons[0].invoke(); self.root.update()
        first = self.d.plan_cards[0]
        self.assertEqual(first.cget('highlightbackground'), GOLD)
        self.assertGreaterEqual(int(first.cget('highlightthickness')), 3)
        self.assertNotEqual(first.cget('bg'), self.d.plan_cards[1].cget('bg'))
        self.d.select_card(1); self.root.update()
        self.assertNotEqual(first.cget('highlightbackground'), GOLD)
        self.assertNotIn('선택 중', self.d.plan_buttons[0].cget('text'))
        self.assertEqual(self.d.plan_cards[1].cget('highlightbackground'), GOLD)

    def test_hover_and_keyboard_select_cards(self):
        card = self.d.plan_cards[1]
        before = card.cget('bg')
        card.event_generate('<Enter>'); self.root.update()
        self.assertNotEqual(card.cget('bg'), before)
        card.event_generate('<Leave>'); self.root.update()
        self.assertEqual(card.cget('bg'), before)
        card.focus_force(); card.event_generate('<Return>'); self.root.update()
        self.assertEqual(self.d.selection.get(), 1)
        card.event_generate('<Right>'); self.root.update()
        self.assertEqual(self.d.selection.get(), 2)
        self.assertEqual(self.errors, [])

    def test_gpu_planned_tags_and_changes_are_calculated_from_real_parts(self):
        self.d.select_card(0); self.root.update()
        before = self.d.options[0]
        self.d.select_card(1); self.root.update()
        parts = self.d.options[1]
        actual = {tag for item in self.d.canvas.find_withtag('planned-slot')
                  for tag in self.d.canvas.gettags(item) if tag.startswith('planned-') and tag != 'planned-slot'}
        expected = {f'planned-{p.server_id}-{slot}' for p in parts for slot in p.gpu_slots}
        self.assertEqual(actual, expected)
        self.assertNotEqual(before, parts)
        for part in parts:
            old = next((p for p in before if p.server_id == part.server_id), None)
            delta = part.gpu-(old.gpu if old else 0)
            if delta: self.assertIn(f'GPU {delta:+d}', self.d.change_text)
        self.assertEqual(self.s.center.gpu_used, 0)

    def test_dialog_center_and_internal_cards_controls_at_resolutions_and_zoomed(self):
        for size in ('1000x650', '1280x680', '1366x768', 'zoomed'):
            if size == 'zoomed': self.root.state('zoomed')
            else: self.root.state('normal'); self.root.geometry(size+'+40+40')
            self.root.update()
            from window_placement import center_dialog
            center_dialog(self.d, self.root, size=(940, 570), minimum=(880, 540))
            self.root.update()
            self.assertAlmostEqual(self.d.winfo_rootx()+self.d.winfo_width()/2,
                                   self.root.winfo_rootx()+self.root.winfo_width()/2, delta=2)
            self.assertAlmostEqual(self.d.winfo_rooty()+self.d.winfo_height()/2,
                                   self.root.winfo_rooty()+self.root.winfo_height()/2, delta=2)
            for widget in (*self.d.plan_cards, self.d.canvas, self.d.start_button, self.d.close_button):
                with self.subTest(size=size, widget=str(widget)):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.d.winfo_rooty()+self.d.winfo_height())


class FeedbackResumeTests(unittest.TestCase):
    def test_request_with_read_marker_resumes_with_visible_clickable_emphasis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'request.db'
            db = Database(path); s = GameSession(db, mode='story')
            s.confirm_story_arrival(); s.select_story_server('A'); s.confirm_story_resources()
            s.select(1); s.mark_story_dialogue('request')
            expected = deepcopy(s.story.payload()), gameplay(s)
            s.close()
            root = tk.Tk(); db = Database(path)
            try:
                app = SimulatorApp(root, db, mode='story'); root.update()
                self.assertEqual((app.session.story.payload(), gameplay(app.session)), expected)
                self.assertIs(app.tutorial_highlight.target, app.arrival_open_button)
                self.assertEqual(app.arrival_open_button.cget('state'), 'normal')
                self.assertTrue(app.tutorial_highlight.pointer.winfo_ismapped())
                self.assertTrue(all(e.winfo_ismapped() for e in app.tutorial_highlight.edges))
                self.assertFalse(app.session.story.request_read)
            finally:
                root.destroy(); db.close()

    def test_resume_does_not_replay_completed_action_feedback_or_reset_old_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'story.db'
            root = tk.Tk(); db = Database(path)
            try:
                app = SimulatorApp(root, db, mode='story'); root.update()
                app.story_window.skip_button.invoke(); app.story_window.next_button.invoke()
                app.network.select('A'); root.update()
                self.assertEqual(app.feedback_window.event, 'server')
                expected = deepcopy(app.session.story.payload()), gameplay(app.session)
                app.on_close()
                root = tk.Tk(); db = Database(path)
                app = SimulatorApp(root, db, mode='story'); root.update()
                self.assertEqual((app.session.story.payload(), gameplay(app.session)), expected)
                self.assertIsNone(app.feedback_window)
                self.assertEqual(app.tutorial_highlight.key, 'resources')
            finally:
                if root.winfo_exists(): root.destroy()
                db.close()

    def test_nearby_bounds_avoid_action_and_screen_edges(self):
        for anchor in ((12, 12, 90, 40), (1800, 960, 90, 40), (500, 500, 90, 40), (-1800, 650, 90, 40)):
            area = (-1920, 0, 0, 1040) if anchor[0] < 0 else (0, 0, 1920, 1040)
            w, h, x, y = nearby_bounds(anchor, area, (390, 210))
            self.assertGreaterEqual(x, area[0]); self.assertGreaterEqual(y, area[1])
            self.assertLessEqual(x+w, area[2]); self.assertLessEqual(y+h, area[3])
            ax, ay, aw, ah = anchor
            self.assertTrue(x+w <= ax or ax+aw <= x or y+h <= ay or ay+ah <= y)


if __name__ == '__main__':
    unittest.main()
