"""v0.8-4 서버 장애·복구·이전. 메모리 또는 임시 DB에서만 실행합니다."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from main import SimulatorApp
from server_console import server_views
from server_resources import SERVERS, ServerPool, ServerSlice, ServerHealth
from session import GameSession


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.s = GameSession(self.db, seed=9, incident_chance=0)
        self.s.deliver_next_request(); self.s.deliver_next_request()

    def japan(self):
        self.s.select(2); self.s.choose_plan('performance')
        return self.s.current

    def shared(self, migratable=False):
        self.s.select(3)
        us_parts = ((ServerSlice('A', (0, 1), 2), ServerSlice('B', (0, 1), 1)) if migratable else
                    (ServerSlice('B', (0, 1, 2), 2), ServerSlice('C', (0,), 1)))
        self.s.choose_plan('economy', us_parts)
        self.s.select(2)
        jp_parts = ((ServerSlice('A', (2,), 1), ServerSlice('C', (0,), 2), ServerSlice('D', (0,), 1)) if migratable else
                    (ServerSlice('A', (0, 1), 3), ServerSlice('C', (1,), 1)))
        self.s.choose_plan('performance', jp_parts)

    def snapshot(self):
        runs = {rid:({k:deepcopy(v) for k,v in vars(r.state).items() if k != 'center'},
                     r.playthrough_id, deepcopy(r.server_allocations), r.hardware_downtime, r.migration_left,
                     r.migration_downtime, deepcopy(r.terms), deepcopy(r.conditions), deepcopy(r.proposals),
                     deepcopy(r.request), list(r.messages), r.last_feedback)
                for rid,r in self.s.runs.items()}
        return (self.s.minute, self.s.roll_index, self.s.selected_id,
                self.s.center.gpu_used, self.s.center.power_used, dict(self.s.servers.hardware),
                dict(self.s.servers.allocations), runs, self.db.conn.serialize())

    def assert_totals(self):
        pool = self.s.servers
        self.assertEqual((pool.gpu_used, pool.power_used), (self.s.center.gpu_used, self.s.center.power_used))
        views = server_views(self.s)
        for i,key in enumerate(('gpu', 'power')):
            self.assertEqual(sum(v[key+'_available']+v[key+'_used']+v[key+'_unavailable'] for v in views), 10)
            self.assertEqual(pool.available()[i], sum(v[key+'_available'] for v in views))

    def test_old_default_has_four_healthy_servers(self):
        self.assertEqual({h.state for h in self.s.servers.hardware.values()}, {'HEALTHY'})
        self.assertEqual(self.s.servers.available(), (10, 10))
        self.assert_totals()

    def test_fault_excludes_idle_server_from_options_and_normal_availability(self):
        self.s.inject_server_fault('A')
        self.assertEqual(self.s.servers.hardware['A'].state, 'FAULT')
        self.assertEqual(self.s.servers.available(), (6, 6))
        self.assertTrue(all(p.server_id != 'A' for parts in self.s.servers.options(3, 4) for p in parts))
        self.assert_totals()

    def test_duplicate_or_unknown_fault_changes_nothing(self):
        self.s.inject_server_fault('A'); before = self.snapshot()
        for key in ('A', 'X'):
            with self.assertRaises(ValueError): self.s.inject_server_fault(key)
            self.assertEqual(self.snapshot(), before)

    def test_fault_preserves_current_slots_and_total_usage(self):
        self.japan(); old = dict(self.s.servers.allocations)
        self.s.inject_server_fault('A')
        self.assertEqual(self.s.servers.allocations, old)
        self.assertEqual((self.s.center.gpu_used, self.s.center.power_used), (3, 4))
        self.assertEqual(self.s.hardware_servers(self.s.current), ('A',))
        self.assert_totals()

    def test_stale_direct_new_allocation_on_fault_server_is_rejected(self):
        self.s.select(2)
        parts = self.s.allocation_options(self.s.current, 'performance')['options'][0]
        self.s.inject_server_fault('A'); before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '다시 확인'):
            self.s.choose_plan('performance', parts)
        self.assertEqual(self.snapshot(), before)

    def test_fault_pauses_only_affected_work_and_healthy_work_advances(self):
        jp = self.japan()
        self.s.select(3)
        self.s.choose_plan('economy', (ServerSlice('B', (0, 1, 2), 2), ServerSlice('C', (0,), 1)))
        us = self.s.current
        self.s.inject_server_fault('A'); self.s.advance_time(30)
        self.assertEqual(jp.state.work_done, 0)
        self.assertEqual(jp.hardware_downtime, 30)
        self.assertEqual(us.state.work_done, 21)
        self.assertEqual(us.hardware_downtime, 0)

    def test_shared_fault_stops_every_affected_customer_without_network_timeout(self):
        self.shared(); self.s.inject_server_fault('C'); self.s.advance_time(60)
        for rid in (2, 3):
            run = self.s.runs[rid]
            self.assertEqual(run.state.work_done, 0)
            self.assertEqual(run.hardware_downtime, 60)
            self.assertEqual(run.state.downtime, 0)
            self.assertTrue(run.state.allocated)
        self.assert_totals()

    def test_idle_fault_does_not_pause_unrelated_work(self):
        run = self.japan(); self.s.inject_server_fault('D'); self.s.advance_time(10)
        self.assertEqual(run.state.work_done, 10)
        self.assertEqual(run.hardware_downtime, 0)

    def test_repair_requires_fault_and_cannot_restart(self):
        with self.assertRaises(ValueError): self.s.begin_server_repair('A')
        self.s.inject_server_fault('A'); self.s.begin_server_repair('A')
        before = self.snapshot()
        with self.assertRaises(ValueError): self.s.begin_server_repair('A')
        with self.assertRaises(ValueError): self.s.inject_server_fault('A')
        self.assertEqual(self.snapshot(), before)

    def test_repair_takes_twenty_game_minutes_then_preserves_slots_and_resumes(self):
        run = self.japan(); old = dict(self.s.servers.allocations)
        self.s.inject_server_fault('A'); minute = self.s.minute
        self.s.begin_server_repair('A')
        self.assertEqual(self.s.minute, minute)
        self.assertEqual(self.s.servers.hardware['A'].repair_left, 20)
        self.s.advance_time(10)
        self.assertEqual(self.s.servers.hardware['A'], ServerHealth('REPAIRING', 10, self.s.servers.hardware['A'].reason))
        self.assertEqual(run.state.work_done, 0)
        self.s.advance_time(10)
        self.assertEqual(self.s.servers.hardware['A'].state, 'HEALTHY')
        self.assertEqual(run.state.work_done, 0)
        self.assertEqual(self.s.servers.allocations, old)
        messages = '\n'.join(text for _,text in self.s.conversation(2))
        self.assertIn('장비 복구 완료', messages)
        self.assertNotIn('장애로 작업이 멈췄습니다', messages)
        self.s.advance_time(10)
        self.assertEqual(run.state.work_done, 10)
        self.assertEqual(run.hardware_downtime, 20)

    def test_repairing_server_is_excluded_from_new_plans(self):
        self.s.inject_server_fault('A'); self.s.begin_server_repair('A')
        self.assertEqual(self.s.servers.available(), (6, 6))
        for parts in self.s.servers.options(3, 4):
            self.assertNotIn('A', [p.server_id for p in parts])

    def test_hardware_repair_does_not_resolve_network_or_double_count_downtime(self):
        run = self.japan(); run.state.trigger_incident()
        self.s.inject_server_fault('A'); self.s.begin_server_repair('A'); self.s.advance_time(30)
        self.assertEqual(run.state.phase, 'incident')
        self.assertEqual(run.state.work_done, 0)
        self.assertEqual(run.hardware_downtime, 20)
        self.assertEqual(run.state.downtime, 10)
        self.assertEqual(run.state.elapsed, 30)

    def test_network_response_does_not_repair_hardware_and_recovery_waits(self):
        run = self.japan(); run.state.trigger_incident(); self.s.inject_server_fault('A')
        self.s.respond('compress'); self.s.advance_time(30)
        self.assertEqual(run.state.phase, 'recovering')
        self.assertEqual(run.state.recovery_left, 10)
        self.assertEqual(run.state.work_done, 0)
        self.assertEqual(self.s.servers.hardware['A'].state, 'FAULT')
        self.s.begin_server_repair('A'); self.s.advance_time(30)
        self.assertEqual(run.state.phase, 'running')
        self.assertEqual(run.state.work_done, 0)
        self.s.advance_time(10); self.assertEqual(run.state.work_done, 10)

    def test_deadline_is_preserved_and_late_completion_keeps_old_penalty(self):
        run = self.japan(); due = run.terms['due']
        self.s.inject_server_fault('A'); self.s.begin_server_repair('A')
        self.s.advance_time(60); self.s.advance_time(30)
        self.assertTrue(run.state.succeeded)
        self.assertEqual(run.terms['due'], due)
        self.assertEqual(run.terms['late_minutes'], 10)
        self.assertEqual(run.terms['penalty'], 5)
        self.assertEqual(run.state.score, 95)

    def test_migration_preview_is_read_only_and_uses_only_healthy_servers(self):
        self.japan(); self.s.inject_server_fault('A'); before = self.snapshot()
        result = self.s.migration_preview(self.s.current)
        self.assertTrue(result['allowed']); self.assertEqual(len(result['options']), 3)
        self.assertEqual(result, self.s.migration_preview(self.s.current))
        for parts in result['options']:
            self.assertNotIn('A', [p.server_id for p in parts])
            self.assertEqual((sum(p.gpu for p in parts), sum(p.power for p in parts)), (3, 4))
        self.assertEqual(self.snapshot(), before)

    def test_migration_prefers_healthy_existing_slots_even_with_lower_free_slots(self):
        self.s.select(2)
        self.s.choose_plan('performance', (ServerSlice('A', (0,), 2), ServerSlice('C', (1,), 1), ServerSlice('D', (0,), 1)))
        self.s.inject_server_fault('A')
        parts = self.s.migration_preview(self.s.current)['options'][0]
        current_c = next(p for p in parts if p.server_id == 'C')
        self.assertIn(1, current_c.gpu_slots)
        self.assertTrue(any(p.server_id == 'D' and p.gpu_slots == (0,) for p in parts))

    def test_exact_selected_migration_preserves_id_progress_mode_terms_and_total(self):
        run = self.japan(); self.s.advance_time(10); self.s.inject_server_fault('A')
        old = (run.playthrough_id, run.state.work_done, run.state.plan, deepcopy(run.terms), deepcopy(run.conditions),
               deepcopy(run.proposals), self.s.center.gpu_used, self.s.center.power_used, self.s.roll_index)
        result = self.s.migration_preview(run); selected = result['options'][2]
        self.s.migrate(selected, result['source'])
        after = (run.playthrough_id, run.state.work_done, run.state.plan, run.terms, run.conditions, run.proposals,
                 self.s.center.gpu_used, self.s.center.power_used, self.s.roll_index)
        self.assertEqual(after, old)
        self.assertEqual(self.s.servers.allocations[run.playthrough_id].slices, selected)
        self.assertEqual(run.server_allocations, [result['source'], self.s.servers.allocations[run.playthrough_id]])
        self.assertEqual(self.s.servers.hardware['A'].state, 'FAULT')
        self.assert_totals()

    def test_migration_preparation_takes_ten_minutes_without_new_work(self):
        run = self.japan(); self.s.inject_server_fault('A')
        result = self.s.migration_preview(run); self.s.migrate(result['options'][0], result['source'])
        minute = self.s.minute
        self.assertEqual(run.migration_left, 10)
        self.assertEqual(run.state.elapsed, 0)
        self.s.advance_time(10)
        self.assertEqual(run.migration_left, 0); self.assertEqual(run.state.work_done, 0)
        self.assertEqual(run.migration_downtime, 10); self.assertEqual(self.s.minute, minute+10)
        messages = '\n'.join(text for _,text in self.s.conversation(2))
        self.assertIn('이전 준비가 끝났습니다', messages)
        self.assertNotIn('장애로 작업이 멈췄습니다', messages)
        self.s.advance_time(10); self.assertEqual(run.state.work_done, 10)

    def test_migration_preserves_unresolved_network_incident(self):
        run = self.japan(); run.state.trigger_incident(); self.s.inject_server_fault('A')
        result = self.s.migration_preview(run); self.s.migrate(result['options'][0], result['source'])
        self.s.advance_time(10)
        self.assertEqual(run.state.phase, 'incident'); self.assertEqual(run.state.downtime, 0)
        self.s.advance_time(10)
        self.assertEqual(run.state.phase, 'incident'); self.assertEqual(run.state.downtime, 10)
        self.assertEqual(run.state.work_done, 0)

    def test_no_migration_plan_keeps_old_allocation(self):
        self.s.choose_plan('performance'); self.s.inject_server_fault('A')
        before = self.snapshot(); result = self.s.migration_preview(self.s.current)
        self.assertFalse(result['allowed']); self.assertEqual(result['options'], ())
        with self.assertRaises(ValueError): self.s.migrate((), result['source'])
        self.assertEqual(self.snapshot(), before)

    def test_migration_does_not_return_or_relocate_other_customer(self):
        self.shared(migratable=True); self.s.inject_server_fault('D')
        other = self.s.servers.allocations[self.s.runs[3].playthrough_id]
        result = self.s.migration_preview(self.s.current)
        self.assertTrue(result['allowed'])
        self.s.migrate(result['options'][0], result['source'])
        self.assertEqual(self.s.servers.allocations[other.playthrough_id], other)
        self.assert_totals()

    def test_stale_target_fault_or_repair_rejects_without_partial_moves(self):
        self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(self.s.current)
        self.s.inject_server_fault('B')
        for repairing in (False, True):
            if repairing: self.s.begin_server_repair('B')
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, '다시 확인'):
                self.s.migrate(result['options'][0], result['source'])
            self.assertEqual(self.snapshot(), before)

    def test_stale_target_occupied_by_new_customer_is_rejected(self):
        self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(self.s.current)
        self.s.select(3); self.s.choose_plan('economy'); self.s.select(2)
        before = self.snapshot()
        with self.assertRaises(ValueError): self.s.migrate(result['options'][0], result['source'])
        self.assertEqual(self.snapshot(), before)

    def test_stale_source_or_resolved_fault_cannot_migrate(self):
        self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(self.s.current)
        self.s.begin_server_repair('A'); self.s.advance_time(30); before = self.snapshot()
        with self.assertRaises(ValueError): self.s.migrate(result['options'][0], result['source'])
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_migration_cannot_restart_preparation(self):
        self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(self.s.current)
        self.s.migrate(result['options'][0], result['source']); before = self.snapshot()
        with self.assertRaises(ValueError): self.s.migrate(result['options'][1], result['source'])
        self.assertEqual(self.snapshot(), before)

    def test_mode_consent_is_checked_before_migration(self):
        run = self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(run)
        run.conditions['allowed_modes'] = []
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '고객'): self.s.migrate(result['options'][0], result['source'])
        self.assertEqual(self.snapshot(), before)

    def test_wrong_totals_or_overlap_cannot_change_any_allocation(self):
        self.japan(); self.s.inject_server_fault('A'); source = self.s.migration_preview(self.s.current)['source']
        bad = ((ServerSlice('B', (0,), 1),),
               (ServerSlice('B', (0, 0), 2), ServerSlice('C', (0,), 2)),
               (ServerSlice('B', (0, 1), 2), ServerSlice('C', (9,), 2)))
        for parts in bad:
            before = self.snapshot()
            with self.assertRaises(ValueError): self.s.migrate(parts, source)
            self.assertEqual(self.snapshot(), before)

    def test_migration_save_failure_restores_every_state_and_database(self):
        self.shared(migratable=True); self.s.inject_server_fault('D'); result = self.s.migration_preview(self.s.current)
        for method in ('save_runtime', 'save_simulation', 'add_log', 'add_request_event'):
            before = self.snapshot()
            with patch.object(self.db, method, side_effect=sqlite3.OperationalError('disk')):
                with self.assertRaises(sqlite3.OperationalError): self.s.migrate(result['options'][0], result['source'])
            self.assertEqual(self.snapshot(), before)
        self.assert_totals()

    def test_fault_and_repair_start_save_failures_roll_back(self):
        self.japan()
        for action in (lambda:self.s.inject_server_fault('A'),):
            before = self.snapshot()
            with patch.object(self.db, 'save_simulation', side_effect=sqlite3.OperationalError('disk')):
                with self.assertRaises(sqlite3.OperationalError): action()
            self.assertEqual(self.snapshot(), before)
        self.s.inject_server_fault('A'); before = self.snapshot()
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('disk')):
            with self.assertRaises(sqlite3.OperationalError): self.s.begin_server_repair('A')
        self.assertEqual(self.snapshot(), before)

    def test_repair_completion_and_migration_timer_save_failures_restore_time(self):
        self.japan(); self.s.inject_server_fault('A'); self.s.begin_server_repair('A'); self.s.advance_time(10)
        before = self.snapshot()
        with patch.object(self.db, 'save_simulation', side_effect=sqlite3.OperationalError('disk')):
            with self.assertRaises(sqlite3.OperationalError): self.s.advance_time(10)
        self.assertEqual(self.snapshot(), before)
        result = self.s.migration_preview(self.s.current); self.s.migrate(result['options'][0], result['source'])
        before = self.snapshot()
        with patch.object(self.db, 'save_runtime', side_effect=sqlite3.OperationalError('disk')):
            with self.assertRaises(sqlite3.OperationalError): self.s.advance_time(10)
        self.assertEqual(self.snapshot(), before)

    def test_latest_allocation_restored_and_history_never_replayed(self):
        run = self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(run)
        self.s.migrate(result['options'][2], result['source'])
        current = dict(self.s.servers.allocations); events = list(map(tuple,self.db.get_request_events(2)))
        for _ in range(3):
            self.s = GameSession(self.db); self.s.select(2)
            self.assertEqual(self.s.servers.allocations, current)
            self.assertEqual(self.s.current.migration_left, 10)
            self.assertEqual(len(self.s.current.server_allocations), 2)
            self.assertEqual(list(map(tuple,self.db.get_request_events(2))), events)
            self.s.save()

    def test_multiple_moves_same_id_restore_last_history_entry(self):
        run = self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(run)
        self.s.migrate(result['options'][0], result['source']); self.s.advance_time(10)
        self.s.begin_server_repair('A'); self.s.advance_time(30)
        self.s.inject_server_fault('B'); result = self.s.migration_preview(run)
        self.s.migrate(result['options'][0], result['source'])
        expected = dict(self.s.servers.allocations); pid = run.playthrough_id
        self.s = GameSession(self.db); self.s.select(2)
        self.assertEqual(self.s.current.playthrough_id, pid)
        self.assertEqual(len(self.s.current.server_allocations), 3)
        self.assertEqual(self.s.servers.allocations, expected)

    def test_legacy_save_without_hardware_fields_preserves_allocations(self):
        self.japan(); self.s.save(); expected = dict(self.s.servers.allocations)
        sim = self.db.get_simulation(); sim.pop('server_health'); self.db.save_simulation(sim)
        for rid,r in self.s.runs.items():
            payload = self.db.get_runtime(rid)
            for key in ('hardware_downtime', 'migration_left', 'migration_downtime'): payload.pop(key)
            self.db.save_runtime(rid, r.playthrough_id, payload)
        restored = GameSession(self.db)
        self.assertEqual(restored.servers.allocations, expected)
        self.assertTrue(all(h.state == 'HEALTHY' for h in restored.servers.hardware.values()))

    def test_corrupt_hardware_or_migration_state_is_reported_without_rewrite(self):
        self.japan(); self.s.save()
        sim = self.db.get_simulation(); sim['server_health']['A']['state'] = 'UNKNOWN'; self.db.save_simulation(sim)
        before = self.db.conn.serialize()
        with self.assertRaises(ValueError): GameSession(self.db)
        self.assertEqual(self.db.conn.serialize(), before)
        sim['server_health']['A']['state'] = 'HEALTHY'; self.db.save_simulation(sim)
        payload = self.db.get_runtime(2); payload['migration_left'] = 5
        self.db.save_runtime(2, self.s.runs[2].playthrough_id, payload)
        before = self.db.conn.serialize()
        with self.assertRaises(ValueError): GameSession(self.db)
        self.assertEqual(self.db.conn.serialize(), before)

    def test_migrated_completion_save_failure_restores_latest_slots_and_history(self):
        self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(self.s.current)
        self.s.migrate(result['options'][0], result['source']); self.s.advance_time(10)
        self.s.current.state.work_done = 59; before = self.snapshot()
        with patch.object(self.db, 'save_result', side_effect=sqlite3.OperationalError('disk')):
            with self.assertRaises(sqlite3.OperationalError): self.s.advance_time(10)
        self.assertEqual(self.snapshot(), before)

    def test_target_fault_during_preparation_freezes_migration_until_repaired(self):
        run = self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(run)
        self.s.migrate(result['options'][0], result['source'])
        self.s.inject_server_fault('B'); self.s.begin_server_repair('B'); self.s.advance_time(30)
        self.assertEqual(run.hardware_downtime, 20)
        self.assertEqual(run.migration_downtime, 10)
        self.assertEqual(run.migration_left, 0)
        self.assertEqual(run.state.work_done, 0)
        self.s.advance_time(10); self.assertEqual(run.state.work_done, 10)

    def test_ten_sixty_and_thirty_minute_steps_have_same_repair_result(self):
        self.japan(); self.s.inject_server_fault('A'); self.s.begin_server_repair('A')
        for _ in range(6): self.s.advance_time(10)
        expected = (self.s.current.state.work_done, self.s.current.hardware_downtime,
                    self.s.current.state.elapsed, self.s.servers.hardware['A'])
        for steps in ((60,), (30,30)):
            db = Database(':memory:')
            try:
                s = GameSession(db, seed=9, incident_chance=0); s.deliver_next_request(); s.select(2)
                s.choose_plan('performance'); s.inject_server_fault('A'); s.begin_server_repair('A')
                for step in steps: s.advance_time(step)
                self.assertEqual((s.current.state.work_done, s.current.hardware_downtime,
                                  s.current.state.elapsed, s.servers.hardware['A']), expected)
            finally: db.close()

    def test_completion_after_migration_returns_only_current_allocation(self):
        self.shared(migratable=True); self.s.inject_server_fault('D'); result = self.s.migration_preview(self.s.current)
        other = self.s.servers.allocations[self.s.runs[3].playthrough_id]
        self.s.migrate(result['options'][0], result['source']); self.s.advance_time(60); self.s.advance_time(10)
        self.assertTrue(self.s.runs[2].state.succeeded)
        self.assertEqual(self.s.servers.allocations, {other.playthrough_id:other})
        self.assertEqual(len(self.s.runs[2].server_allocations), 2)
        self.assert_totals()

    def test_report_failure_during_migration_returns_current_slots_and_cancels_timer(self):
        self.japan(); self.s.inject_server_fault('A'); result = self.s.migration_preview(self.s.current)
        self.s.migrate(result['options'][0], result['source']); self.s.report_failure()
        self.assertEqual(self.s.current.migration_left, 0)
        self.assertEqual(self.s.servers.allocations, {})
        self.assert_totals()

    def test_delay_notice_distinguishes_fault_migration_and_network_without_spam(self):
        self.japan(); self.s.inject_server_fault('A'); self.s.notify_delay()
        self.assertFalse(self.s.can_notify_delay(self.s.current))
        self.s.advance_time(10)
        self.assertFalse(self.s.can_notify_delay(self.s.current))
        result = self.s.migration_preview(self.s.current); self.s.migrate(result['options'][0], result['source'])
        self.assertTrue(self.s.can_notify_delay(self.s.current))
        self.assertIn('이전 준비', self.s.delay_reason(self.s.current))

    def test_disk_resume_of_repair_and_migration_preserves_other_customer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'hardware.db'
            db = Database(path)
            try:
                s = GameSession(db, seed=9, incident_chance=0)
                s.deliver_next_request(); s.deliver_next_request(); s.select(2); s.choose_plan('performance')
                s.inject_server_fault('A'); s.begin_server_repair('A'); s.advance_time(10)
                s.close(); db = Database(path); s = GameSession(db); s.select(2)
                self.assertEqual(s.servers.hardware['A'].repair_left, 10)
                self.assertEqual(s.current.hardware_downtime, 10)
                result = s.migration_preview(s.current); s.migrate(result['options'][1], result['source'])
                expected = dict(s.servers.allocations); s.close()
                db = Database(path); s = GameSession(db); s.select(2)
                self.assertEqual(s.current.migration_left, 10); self.assertEqual(s.servers.allocations, expected)
                s.advance_time(10); self.assertEqual(s.current.state.work_done, 0)
                self.assertEqual(db.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
            finally: db.close()


class HardwareGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.db = Database(':memory:'); self.addCleanup(self.db.close)
        self.a = SimulatorApp(self.root, self.db, seed=9, incident_chance=0)
        self.addCleanup(self.a.network.stop)
        self.errors = []; self.root.report_callback_exception = lambda *args:self.errors.append(args)
        self.a.session.deliver_next_request(); self.a.session.select(2); self.a.choose_plan('performance')
        self.a.network.select('A'); self.root.update()

    def fault(self):
        self.a.resources.fault_button.invoke(); self.root.update()

    def test_actual_fault_button_changes_rack_inspector_and_customer_warning(self):
        self.fault(); a = self.a
        self.assertEqual(a.resources.inspector.values['status'], 'FAULT')
        self.assertEqual(len(a.network.find_withtag('gpu-fault')), 4)
        self.assertIn('서버 장애', a.action_hint.cget('text'))
        self.assertIn('migrate', a.action_buttons)
        self.assertEqual(a.resources.fault_button.cget('state'), 'disabled')
        self.assertEqual(len(a.resources.owners.get_children()), 1)
        self.assertEqual(self.errors, [])

    def test_actual_repair_and_time_buttons_resume_existing_job(self):
        self.fault(); a = self.a
        a.resources.repair_button.invoke(); self.root.update()
        self.assertEqual(a.resources.inspector.values['repair_left'], 20)
        a.time_buttons[10].invoke(); self.root.update()
        self.assertEqual(a.resources.inspector.values['repair_left'], 10)
        self.assertEqual(a.state.work_done, 0)
        a.time_buttons[10].invoke(); a.time_buttons[10].invoke(); self.root.update()
        self.assertEqual(a.state.work_done, 10)
        self.assertFalse(a.network.find_withtag('gpu-fault'))
        self.assertEqual(self.errors, [])

    def test_migration_dialog_selection_matches_ledger_and_pending_timer(self):
        self.fault(); a = self.a
        a.action_buttons['migrate'].invoke(); self.root.update(); d = a.allocation_window
        before = dict(a.session.servers.allocations)
        d.plan_buttons[2].invoke(); self.root.update(); selected = d.options[2]
        self.assertEqual(a.session.servers.allocations, before)
        self.assertTrue(all(p.server_id != 'A' for p in selected))
        d.start_button.invoke(); self.root.update()
        self.assertEqual(a.session.servers.allocations[a.playthrough_id].slices, selected)
        self.assertEqual(a.session.current.migration_left, 10)
        self.assertIn('이전 준비', a.action_hint.cget('text'))
        self.assertEqual(self.errors, [])

    def test_hud_partition_counts_occupied_and_unavailable_without_overlap(self):
        self.fault(); values = self.a.overview.values
        for key in ('gpu', 'power'):
            self.assertEqual(values[key+'_used']+values[key+'_available']+values[key+'_unavailable'], 10)
        self.assertEqual(values['gpu_available'], 6)
        self.assertEqual(values['gpu_used'], 3)
        self.assertEqual(values['gpu_unavailable'], 1)
        self.assertEqual(values['hardware'], 1)

    def test_network_only_never_marks_hardware_as_fault(self):
        self.a.state.trigger_incident(); self.a.refresh(); self.root.update()
        self.assertEqual(self.a.overview.values['hardware'], 0)
        self.assertEqual(len(self.a.network.find_withtag('gpu-fault')), 0)
        self.assertEqual(self.a.resources.inspector.values['health'], 'HEALTHY')

    def test_stale_migration_error_keeps_gui_selection_and_real_resources(self):
        self.fault(); a = self.a; d = a.open_migration_plans(); d.plan_buttons[0].invoke()
        a.session.inject_server_fault('B'); before = dict(a.session.servers.allocations)
        with patch('main.messagebox.showerror') as error:
            d.start_button.invoke(); self.root.update()
        error.assert_called_once(); self.assertEqual(a.session.servers.allocations, before)
        self.assertEqual(d.selection.get(), 0)
        self.assertTrue(d.winfo_exists())
        self.assertEqual(self.errors, [])

    def test_impossible_migration_dialog_has_reason_and_disabled_start(self):
        a = self.a
        a.session.report_failure(); a.session.select(1); a.choose_plan('performance')
        a.network.select('A'); self.fault()
        a.action_buttons['migrate'].invoke(); self.root.update(); d = a.allocation_window
        self.assertEqual(d.options, ())
        self.assertEqual(d.start_button.cget('state'), 'disabled')
        self.assertIn('이전할 수 없습니다', d.notice.cget('text'))
        self.assertEqual(self.errors, [])

    def test_layout_at_three_resolutions_during_fault_repair_and_migration(self):
        a = self.a; self.fault()
        for phase in ('fault', 'repair', 'migration'):
            if phase == 'repair': a.resources.repair_button.invoke()
            if phase == 'migration':
                d = a.open_migration_plans(); self.root.update()
            for width,height in ((1000,650), (1280,680), (1366,768)):
                self.root.geometry(f'{width}x{height}'); self.root.update()
                widgets = (a.resources.fault_button, a.resources.repair_button, a.resources.inspector,
                           *a.action_buttons.values(), *a.time_buttons.values())
                for widget in widgets:
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreaterEqual(widget.winfo_rooty(), self.root.winfo_rooty())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+height)
                for canvas in (a.network, a.overview, a.resources.inspector):
                    for item in canvas.find_all():
                        if canvas.type(item) == 'text':
                            x1,y1,x2,y2 = canvas.bbox(item)
                            self.assertGreaterEqual(x1,0); self.assertGreaterEqual(y1,0)
                            self.assertLessEqual(x2,canvas.winfo_width()); self.assertLessEqual(y2,canvas.winfo_height())
                if phase == 'migration':
                    for widget in (d.heading,d.cards,d.canvas,d.notice,d.start_button,d.reload_button):
                        self.assertGreaterEqual(widget.winfo_height(),widget.winfo_reqheight())
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),d.winfo_rooty()+d.winfo_height())
            if phase == 'migration': d.destroy()
        self.assertEqual(self.errors, [])
