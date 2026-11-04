"""v0.8-3 배정안 선택의 실제 점유·원자성·GUI 회귀. 임시 DB만 사용."""
from copy import deepcopy
from itertools import islice
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from game import CUSTOMER_PLANS
from main import SimulatorApp
from server_resources import SERVERS, Allocation, ServerPool, ServerSlice
from session import GameSession


class PlanGenerationTests(unittest.TestCase):
    def test_options_are_unique_deterministic_and_keep_existing_recommendation(self):
        pool = ServerPool()
        for modes in CUSTOMER_PLANS.values():
            for plan in modes.values():
                options = pool.options(plan['gpu'], plan['power'])
                self.assertEqual(len(options), 3)
                self.assertEqual(len(set(options)), len(options))
                self.assertEqual(options, pool.options(plan['gpu'], plan['power']))
                self.assertEqual(options[0], pool.plan(plan['gpu'], plan['power']))
                self.assertEqual(options, tuple(islice(pool.plans(plan['gpu'], plan['power']), 3)))
                for parts in options:
                    self.assertEqual((sum(s.gpu for s in parts), sum(s.power for s in parts)),
                                     (plan['gpu'], plan['power']))
                    self.assertTrue(all(s.gpu > 0 and s.power > 0 for s in parts))
                    pool.validate_plan(parts, plan['gpu'], plan['power'])
        self.assertEqual(pool.allocations, {})

    def test_seven_gpu_examples_have_different_distributions(self):
        plans = ServerPool().options(7, 7)
        self.assertEqual([(p.server_id, p.gpu, p.power) for p in plans[0]],
                         [('A', 4, 4), ('B', 2, 2), ('C', 1, 1)])
        self.assertEqual([(p.server_id, p.gpu, p.power) for p in plans[1]],
                         [('A', 4, 4), ('B', 2, 1), ('C', 1, 2)])

    def test_only_one_or_no_option_is_shown_without_duplicates(self):
        pool = ServerPool()
        pool.reserve(Allocation(1, (ServerSlice('A', (0, 1, 2, 3), 4),
                                    ServerSlice('B', (0, 1, 2), 2), ServerSlice('C', (0, 1), 3))))
        self.assertEqual(pool.options(1, 1), ((ServerSlice('D', (0,), 1),),))
        self.assertEqual(pool.options(2, 2), ())

    def test_occupied_slots_and_power_are_excluded_without_changing_pool(self):
        pool = ServerPool()
        pool.reserve(Allocation(1, (ServerSlice('A', (0, 2), 1),)))
        before = deepcopy(pool.allocations)
        for parts in pool.options(4, 4):
            pool.validate_plan(parts, 4, 4)
            for part in parts:
                if part.server_id == 'A':
                    self.assertFalse(set(part.gpu_slots) & {0, 2})
                    self.assertLessEqual(part.power, 3)
        self.assertEqual(pool.allocations, before)

    def test_validation_checks_all_slices_before_any_reservation(self):
        pool = ServerPool()
        bad = (
            (ServerSlice('A', (0,), 1), ServerSlice('C', (9,), 1)),
            (ServerSlice('A', (0,), 1), ServerSlice('A', (1,), 1)),
            (ServerSlice('A', (0, 0), 2),),
            (ServerSlice('A', (), 2), ServerSlice('B', (0, 1), 0)),
            (ServerSlice('X', (0, 1), 2),),
            (ServerSlice('D', (0, 1), 2),),
        )
        for parts in bad:
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                pool.validate_plan(parts, 2, 2)
            self.assertEqual(pool.allocations, {})


class SelectedPlanTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=9, incident_chance=0)

    def snapshot(self):
        return (self.s.center.gpu_used, self.s.center.power_used, self.s.minute, self.s.roll_index,
                deepcopy(self.s.servers.allocations), deepcopy(self.s.current.server_allocations),
                deepcopy(vars(self.s.current.state)), deepcopy(self.s.current.terms),
                deepcopy(self.s.current.proposals), self.db.conn.serialize())

    def assert_unchanged(self, before):
        after = self.snapshot()
        # center의 객체 동일성 대신 값은 위에서 별도로 비교합니다.
        before[6].pop('center'); after[6].pop('center')
        self.assertEqual(after, before)

    def test_selected_alternative_is_exact_actual_ledger_not_recommendation(self):
        choices = self.s.allocation_options(self.s.current, 'performance')['options']
        before = self.snapshot()
        self.assertNotEqual(choices[0], choices[2])
        self.assert_unchanged(before)
        self.s.choose_plan('performance', server_plan=choices[2])
        actual = self.s.servers.allocations[self.s.current.playthrough_id]
        self.assertEqual(actual.slices, choices[2])
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (7, 7))
        self.assertEqual(self.s.current.server_allocations, [actual])

    def test_default_and_explicit_auto_keep_old_recommendation(self):
        expected = self.s.servers.plan(7, 7)
        self.s.choose_plan('performance', server_plan=None)
        self.assertEqual(self.s.current.server_allocations[-1].slices, expected)

    def test_selected_plan_never_bypasses_consent_and_pending_proposal(self):
        parts = self.s.servers.options(4, 4)[1]
        before = self.snapshot()
        with patch.object(self.s.servers, 'validate_plan', side_effect=AssertionError('consent first')):
            with self.assertRaisesRegex(ValueError, '고객'):
                self.s.choose_plan('economy', server_plan=parts)
            self.assertEqual(self.s.allocation_options(self.s.current, 'economy')['options'], ())
        self.assert_unchanged(before)
        self.s.propose_alternative()
        with self.assertRaisesRegex(ValueError, '고객'):
            self.s.choose_plan('economy', server_plan=parts)

    def test_agreed_economy_selection_preserves_original_conditions(self):
        conditions = deepcopy(self.s.current.conditions)
        self.s.propose_alternative(); self.s.review_alternative()
        proposals = deepcopy(self.s.current.proposals)
        parts = self.s.allocation_options(self.s.current, 'economy')['options'][1]
        self.s.choose_plan('economy', server_plan=parts)
        self.assertEqual(self.s.current.server_allocations[-1].slices, parts)
        self.assertEqual(self.s.current.conditions, conditions)
        self.assertEqual(self.s.current.proposals, proposals)

    def test_flexible_mode_accepts_direct_plan_without_proposal(self):
        self.s.deliver_next_request(); self.s.deliver_next_request(); self.s.select(3)
        parts = self.s.allocation_options(self.s.current, 'economy')['options'][2]
        self.s.choose_plan('economy', server_plan=parts)
        self.assertEqual(self.s.current.proposals, [])
        self.assertEqual(self.s.current.server_allocations[-1].slices, parts)

    def test_wrong_totals_and_malformed_plans_roll_back_entire_action(self):
        for parts in ((), [], (ServerSlice('A', (0,), 1),),
                      (ServerSlice('A', (0, 1, 2, 3), 4), ServerSlice('X', (0, 1, 2), 3)),
                      (ServerSlice('A', (0, 1, 2, 3), 4), ServerSlice('B', (0, 1, 2), True))):
            before = self.snapshot()
            with self.subTest(parts=parts), self.assertRaisesRegex(ValueError, '선택한 배정안'):
                self.s.choose_plan('performance', server_plan=parts)
            self.assert_unchanged(before)

    def prepare_shared_jobs(self):
        self.s.deliver_next_request(); self.s.deliver_next_request()
        self.s.select(3)
        self.s.choose_plan('economy', server_plan=(ServerSlice('B', (0, 1, 2), 2), ServerSlice('C', (0,), 1)))
        owner = self.s.current.playthrough_id
        self.s.select(2)
        self.s.choose_plan('performance', server_plan=(ServerSlice('A', (0, 1), 3), ServerSlice('C', (1,), 1)))
        return owner

    def test_completion_releases_only_selected_job_and_keeps_other_slots(self):
        owner = self.prepare_shared_jobs()
        expected = self.s.servers.allocations[owner]
        self.s.advance_time(60)
        self.assertTrue(self.s.runs[2].state.succeeded)
        self.assertEqual(self.s.servers.allocations, {owner:expected})
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (4, 3))
        self.assertEqual(self.s.servers.free_slots(SERVERS[1]), ())
        self.assertEqual(self.s.servers.free_slots(SERVERS[2]), (1,))

    def test_stale_slots_are_blocked_even_if_another_plan_is_available(self):
        self.s.deliver_next_request(); self.s.deliver_next_request(); self.s.select(2)
        stale = self.s.allocation_options(self.s.current, 'performance')['options'][0]
        self.s.select(3); self.s.choose_plan('economy'); self.s.select(2)
        self.assertTrue(self.s.allocation_preview(self.s.current, 'performance')['allowed'])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '다시 확인'):
            self.s.choose_plan('performance', server_plan=stale)
        self.assert_unchanged(before)

    def test_stale_power_is_blocked_without_replacing_slots(self):
        pool = self.s.servers
        parts = pool.options(3, 4)[0]
        # 같은 서버에서 선택 슬롯과 겹치지 않는 점유라도 전력 부족이면 무효입니다.
        pool.reserve(Allocation(99, (ServerSlice('A', (3,), 1),)))
        before = dict(pool.allocations)
        with self.assertRaises(ValueError):
            pool.validate_plan(parts, 3, 4)
        self.assertEqual(pool.allocations, before)

    def test_freed_other_resources_do_not_change_valid_direct_selection(self):
        self.s.deliver_next_request(); self.s.deliver_next_request()
        self.s.select(3); self.s.choose_plan('economy'); self.s.select(2)
        selected = self.s.allocation_options(self.s.current, 'performance')['options'][2]
        self.s.select(3); self.s.report_failure()
        self.s.select(2); self.s.choose_plan('performance', server_plan=selected)
        self.assertEqual(self.s.current.server_allocations[-1].slices, selected)

    def test_shared_selected_slots_resume_without_changing_existing_job(self):
        self.prepare_shared_jobs()
        before = deepcopy(self.s.servers.allocations)
        self.s.save()
        restored = GameSession(self.db)
        self.assertEqual(restored.servers.allocations, before)
        self.assertEqual(len(restored.servers.allocations), 2)
        slots = [part.gpu_slots for a in before.values() for part in a.slices if part.server_id == 'C']
        self.assertEqual(slots, [(0,), (1,)])

    def test_save_failures_restore_selected_plan_history_db_and_rng(self):
        parts = self.s.servers.options(7, 7)[2]
        for method in ('create_playthrough', 'add_log', 'save_runtime', 'save_simulation'):
            before = self.snapshot()
            with self.subTest(method=method), patch.object(self.db, method, side_effect=sqlite3.OperationalError('disk')):
                with self.assertRaises(sqlite3.OperationalError):
                    self.s.choose_plan('performance', server_plan=parts)
            self.assert_unchanged(before)
        self.s.choose_plan('performance', server_plan=parts)
        self.assertEqual(self.s.current.server_allocations[-1].slices, parts)

    def test_completion_save_failure_restores_selected_slots_and_other_job(self):
        self.prepare_shared_jobs()
        self.s.current.state.work_done = 59
        before = self.snapshot()
        with patch.object(self.db, 'save_result', side_effect=sqlite3.OperationalError('disk')):
            with self.assertRaises(sqlite3.OperationalError):
                self.s.advance_time(10)
        self.assert_unchanged(before)

    def test_retry_uses_auto_without_changing_previous_selected_history(self):
        parts = self.s.servers.options(7, 7)[2]
        self.s.choose_plan('performance', server_plan=parts)
        original = self.s.current.server_allocations[-1]
        self.s.current.state.trigger_incident()
        for _ in range(3):
            self.s.respond('ignore')
        self.s.retry('performance')
        self.assertEqual(self.s.current.server_allocations[0], original)
        self.assertEqual(self.s.current.server_allocations[-1].slices, ServerPool().plan(7, 7))
        self.assertEqual(self.s.current.state.recovery_left, 20)
        self.assertEqual(self.s.current.state.retry_count, 1)

    def test_disk_resume_preserves_selected_slots_consent_and_existing_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'selected.db'
            db = Database(path)
            try:
                s = GameSession(db, seed=9, incident_chance=0)
                s.propose_alternative(); s.review_alternative()
                parts = s.allocation_options(s.current, 'economy')['options'][2]
                s.choose_plan('economy', server_plan=parts)
                s.advance_time(10)
                expected = deepcopy(s.servers.allocations)
                proposals, conditions = deepcopy(s.current.proposals), deepcopy(s.current.conditions)
                records = list(map(tuple, db.conn.execute('SELECT * FROM playthroughs')))
                s.close()
                for _ in range(2):
                    db = Database(path)
                    s = GameSession(db)
                    self.assertEqual(s.servers.allocations, expected)
                    self.assertEqual(s.current.proposals, proposals)
                    self.assertEqual(s.current.conditions, conditions)
                    self.assertEqual(list(map(tuple, db.conn.execute('SELECT * FROM playthroughs'))), records)
                    self.assertEqual(db.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(db.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
                    s.close()
            finally:
                db.close()

    def test_v082_active_allocation_is_not_rearranged_and_missing_field_still_loads(self):
        self.s.choose_plan('performance')
        old = deepcopy(self.s.servers.allocations)
        self.s.save()
        restored = GameSession(self.db)
        self.assertEqual(restored.servers.allocations, old)
        payload = self.db.get_runtime(1)
        payload.pop('server_allocations')
        self.db.save_runtime(1, 1, payload)
        restored = GameSession(self.db)
        self.assertTrue(restored.current.server_allocations[-1].reconstructed)
        self.assertEqual((restored.center.gpu_used, restored.center.power_used), (7, 7))


class PlanDialogTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, seed=9, incident_chance=0)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()

    def dialog(self):
        self.app.resources.compare_button.invoke()
        self.root.update()
        return self.app.allocation_window

    def test_actual_radio_and_start_apply_exact_alternative(self):
        a = self.app
        d = self.dialog()
        expected = d.options[2]
        d.plan_buttons[2].invoke(); self.root.update()
        self.assertEqual(d.selection.get(), 2)
        self.assertEqual(len(d.canvas.find_withtag('planned-slot')), 7)
        self.assertEqual(a.session.servers.allocations, {})
        d.start_button.invoke(); self.root.update()
        self.assertFalse(d.winfo_exists())
        self.assertEqual(a.session.current.server_allocations[-1].slices, expected)
        self.assertEqual(len(a.network.find_withtag('gpu-busy')), 7)
        self.assertEqual(self.errors, [])

    def test_auto_and_close_do_not_apply_temporary_choice(self):
        d = self.dialog()
        d.plan_buttons[1].invoke(); d.close_button.invoke(); self.root.update()
        self.assertEqual(self.app.session.servers.allocations, {})
        self.assertEqual(self.db.get_recent_records(), [])
        d = self.dialog()
        self.assertEqual(d.selection.get(), -1)
        expected = self.app.session.servers.plan(7, 7)
        d.start_button.invoke(); self.root.update()
        self.assertEqual(self.app.session.current.server_allocations[-1].slices, expected)

    def test_no_consent_shows_reason_without_options_or_start(self):
        self.app.plan_var.set('economy'); self.app.refresh()
        d = self.dialog()
        self.assertEqual(d.options, ())
        self.assertIn('고객 동의', d.notice.cget('text'))
        self.assertEqual(d.start_button.cget('state'), 'disabled')
        self.assertEqual(self.app.session.servers.allocations, {})

    def test_comparison_rows_match_actual_capacity_and_highlights_switch(self):
        d = self.dialog()
        for i, rows in enumerate(d.comparison_rows):
            d.plan_buttons[i].invoke(); self.root.update()
            self.assertEqual(sum(r[1] for r in rows), 7)
            self.assertEqual(sum(r[2] for r in rows), 7)
            for spec, row in zip(SERVERS, rows):
                self.assertEqual((row[3], row[4]), (spec.gpu-row[1], spec.power-row[2]))
            for part in d.options[i]:
                for slot in part.gpu_slots:
                    self.assertTrue(d.canvas.find_withtag(f'planned-{part.server_id}-{slot}'))
        self.assertEqual(self.errors, [])

    def test_stale_selection_remains_until_explicit_reload(self):
        a = self.app; s = a.session
        s.deliver_next_request(); s.deliver_next_request(); s.select(2); a.refresh()
        d = self.dialog(); d.plan_buttons[0].invoke()
        old = d.options
        s.select(3); s.choose_plan('economy'); s.select(2)
        before = deepcopy(s.servers.allocations)
        with patch('main.messagebox.showerror') as error:
            d.start_button.invoke(); self.root.update()
        error.assert_called_once()
        self.assertEqual(s.servers.allocations, before)
        self.assertEqual(d.selection.get(), 0)
        self.assertEqual(d.options, old)
        self.assertIn('다시', d.notice.cget('text'))
        d.reload_button.invoke(); self.root.update()
        self.assertEqual(d.selection.get(), -1)
        self.assertNotEqual(d.options, old)
        self.assertEqual(s.servers.allocations, before)
        self.assertEqual(self.errors, [])

    def test_request_switch_cannot_start_different_customer(self):
        d = self.dialog()
        self.app.session.deliver_next_request(); self.app.session.select(2)
        d.start_button.invoke(); self.root.update()
        self.assertIn('요청이 변경', d.notice.cget('text'))
        self.assertEqual(self.app.session.servers.allocations, {})

    def test_gui_layout_at_all_three_resolutions_including_internal_text(self):
        a = self.app
        for width, height in ((1000, 650), (1280, 680), (1366, 768)):
            self.root.geometry(f'{width}x{height}'); self.root.update()
            d = self.dialog()
            self.root.update()
            for widget in (a.resources.compare_button, d.heading, d.auto_button, d.cards, d.canvas,
                           d.notice, d.start_button, d.reload_button, d.close_button, *d.plan_buttons):
                host = d if widget.winfo_toplevel() == d else self.root
                self.assertGreaterEqual(widget.winfo_rootx(), host.winfo_rootx())
                self.assertGreaterEqual(widget.winfo_rooty(), host.winfo_rooty())
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), host.winfo_rootx()+host.winfo_width())
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), host.winfo_rooty()+host.winfo_height())
                self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
            for item in d.canvas.find_all():
                if d.canvas.type(item) == 'text':
                    x1, y1, x2, y2 = d.canvas.bbox(item)
                    self.assertGreaterEqual(x1, 0); self.assertGreaterEqual(y1, 0)
                    self.assertLessEqual(x2, d.canvas.winfo_width()); self.assertLessEqual(y2, d.canvas.winfo_height())
            d.destroy(); self.root.update()
        self.assertEqual(self.errors, [])
