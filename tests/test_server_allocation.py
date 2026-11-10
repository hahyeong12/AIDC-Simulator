"""v0.8-2 실제 배정·저장·호환·GUI 통합. 메모리 또는 임시 DB만 사용합니다."""
from copy import deepcopy
import sqlite3
import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from tests.support import start_via_dialog
from unittest.mock import patch

from database import Database
from game import CUSTOMER_PLANS
from main import SimulatorApp
from server_resources import SERVERS, ServerPool, ServerSlice, Allocation
from server_console import server_views
from session import GameSession


class ServerPoolTests(unittest.TestCase):
    def test_server_capacities_and_every_current_plan_are_feasible(self):
        self.assertEqual((sum(s.gpu for s in SERVERS),sum(s.power for s in SERVERS)),(10,10))
        for country,plans in CUSTOMER_PLANS.items():
            for key,p in plans.items():
                with self.subTest(country=country,mode=key):
                    parts=ServerPool().plan(p['gpu'],p['power'])
                    self.assertIsNotNone(parts)
                    self.assertEqual((sum(s.gpu for s in parts),sum(s.power for s in parts)),(p['gpu'],p['power']))
                    self.assertTrue(all(s.gpu>0 and s.power>0 for s in parts))

    def test_training_seven_uses_minimum_three_servers_deterministically(self):
        pool=ServerPool(); parts=pool.plan(7,7)
        self.assertEqual(len(parts),3)
        self.assertEqual(parts,pool.plan(7,7))
        self.assertTrue(all(len(plan)>=3 for plan in pool.plans(7,7)))
        self.assertEqual([(p.server_id,p.gpu,p.power) for p in parts],[('A',4,4),('B',2,2),('C',1,1)])
        self.assertEqual(pool.allocations,{})

    def test_shared_server_reserves_distinct_gpu_slots(self):
        pool=ServerPool()
        pool.reserve(Allocation(1,pool.plan(2,2)))
        pool.reserve(Allocation(2,pool.plan(2,2)))
        self.assertEqual(pool.usage('A'),(4,4))
        first,second=(a.slices[0].gpu_slots for a in pool.allocations.values())
        self.assertFalse(set(first)&set(second))
        pool.release(1)
        self.assertEqual(pool.usage('A'),(2,2))
        self.assertEqual(pool.allocations[2].slices[0].gpu_slots,second)
        with self.assertRaises(ValueError):pool.release(1)

    def test_fragmentation_blocks_even_with_sufficient_total_resources(self):
        pool=ServerPool()
        pool.reserve(Allocation(1,pool.plan(4,4)))
        pool.reserve(Allocation(2,pool.plan(2,2)))
        self.assertEqual((10-pool.gpu_used,10-pool.power_used),(4,4))
        self.assertIsNone(pool.plan(4,3))
        self.assertEqual(len(pool.allocations),2)

    def test_invalid_or_duplicate_reservation_is_atomic(self):
        pool=ServerPool(); valid=Allocation(1,pool.plan(2,2));pool.reserve(valid)
        before=dict(pool.allocations)
        bad=[valid,Allocation(2,(ServerSlice('A',(0,),1),)),Allocation(2,(ServerSlice('B',(0,),0),)),
             Allocation(2,(ServerSlice('B',(),1),)),Allocation(2,(ServerSlice('X',(0,),1),)),
             Allocation(2,(ServerSlice('B',(0,0),1),)),Allocation(2,(ServerSlice('B',(0,),3),)),
             Allocation(2,(ServerSlice('B',(0,),1),ServerSlice('C',(9,),1)))]
        for allocation in bad:
            with self.subTest(allocation=allocation),self.assertRaises(ValueError):pool.reserve(allocation)
            self.assertEqual(pool.allocations,before)

    def test_exhaustive_small_demands_never_exceed_capacity(self):
        for gpu in range(1,11):
            for power in range(1,11):
                pool=ServerPool();parts=pool.plan(gpu,power)
                if parts is not None:
                    a=Allocation(1,parts);pool.reserve(a)
                    self.assertEqual((a.gpu,a.power),(gpu,power))
                    for spec in SERVERS:
                        g,p=pool.usage(spec.key)
                        self.assertLessEqual(g,spec.gpu);self.assertLessEqual(p,spec.power)
                    self.assertEqual(parts,ServerPool().plan(gpu,power))


class ServerSessionTests(unittest.TestCase):
    def setUp(self):
        self.db=Database(':memory:');self.addCleanup(self.db.close)
        self.s=GameSession(self.db,seed=9,incident_chance=0)

    def usage(self):
        return (self.s.center.gpu_used,self.s.center.power_used,deepcopy(self.s.servers.allocations),
                deepcopy(self.s.current.server_allocations),list(map(tuple,self.db.get_recent_records())))

    def assert_totals(self):
        self.assertEqual((self.s.center.gpu_used,self.s.center.power_used),
                         (self.s.servers.gpu_used,self.s.servers.power_used))
        self.assertEqual(sum(self.s.servers.usage(s.key)[0] for s in SERVERS),self.s.center.gpu_used)
        self.assertEqual(sum(self.s.servers.usage(s.key)[1] for s in SERVERS),self.s.center.power_used)

    def test_preview_and_seven_gpu_start_have_identical_slices(self):
        before=self.usage();preview=self.s.allocation_preview(self.s.current,'performance')
        self.assertTrue(preview['allowed']);self.assertEqual(self.usage(),before)
        self.s.choose_plan('performance')
        allocation=self.s.servers.allocations[self.s.current.playthrough_id]
        self.assertEqual(allocation.slices,preview['slices'])
        self.assertEqual((allocation.gpu,allocation.power),(7,7));self.assert_totals()
        self.assertEqual(self.db.get_runtime(1)['server_allocations'][0]['playthrough_id'],self.s.current.playthrough_id)

    def test_consent_validation_precedes_server_planning(self):
        before=self.usage()
        with patch.object(self.s.servers,'plan',side_effect=AssertionError('must not plan')) as plan:
            with self.assertRaisesRegex(ValueError,'고객'):self.s.choose_plan('economy')
            self.assertFalse(self.s.allocation_preview(self.s.current,'economy')['allowed'])
            plan.assert_not_called()
        self.assertEqual(self.usage(),before)

    def test_pending_and_rejected_alternatives_cannot_reserve_servers(self):
        self.s.propose_alternative()
        for key in ('performance','economy'):
            with self.assertRaises(ValueError):self.s.choose_plan(key)
        self.s.advance_time(60);self.assertFalse(self.s.review_alternative())
        with self.assertRaises(ValueError):self.s.choose_plan('economy')
        self.assertEqual(self.s.servers.allocations,{})

    def test_agreed_economy_and_urgent_inference_share_capacity(self):
        self.s.propose_alternative();self.assertTrue(self.s.review_alternative());self.s.choose_plan('economy')
        self.s.deliver_next_request();self.s.select(2);self.s.choose_plan('performance')
        self.assertEqual((self.s.center.gpu_used,self.s.center.power_used),(7,8));self.assert_totals()

    def test_japan_and_usa_performance_and_flexible_economy(self):
        for rid,key,expected in ((2,'performance',(3,4)),(3,'performance',(6,6)),(3,'economy',(4,3))):
            with self.subTest(rid=rid,key=key):
                db=Database(':memory:')
                try:
                    s=GameSession(db,seed=9,incident_chance=0);s.deliver_next_request();s.deliver_next_request();s.select(rid)
                    s.choose_plan(key)
                    self.assertEqual((s.servers.gpu_used,s.servers.power_used),expected)
                finally:db.close()

    def test_shared_server_can_show_two_distinct_customers(self):
        self.s.deliver_next_request();self.s.deliver_next_request();self.s.select(2)
        self.s.current.conditions={}  # 이전 저장의 일본 절약형
        self.s.choose_plan('economy');self.s.select(3);self.s.choose_plan('economy')
        shared=next(v for v in server_views(self.s) if len(v['owners'])==2)
        self.assertEqual({o['company'] for o in shared['owners']},{'Sakura Robotics','Northstar AI'})
        self.assertEqual({o['code'] for o in shared['slots'] if o},{'jp','us'});self.assert_totals()

    def test_joint_impossibility_blocks_without_partial_start(self):
        self.s.propose_alternative();self.s.review_alternative();self.s.choose_plan('economy')
        self.s.deliver_next_request();self.s.deliver_next_request();self.s.select(2)
        self.s.current.conditions={};self.s.choose_plan('economy');self.s.select(3)
        before=self.usage()
        self.assertEqual((self.s.center.available_gpu(),self.s.center.available_power()),(4,4))
        preview=self.s.allocation_preview(self.s.current,'economy');self.assertFalse(preview['allowed'])
        with self.assertRaisesRegex(ValueError,'서버별'):self.s.choose_plan('economy')
        self.assertEqual(self.usage(),before);self.assertIsNone(self.s.current.playthrough_id);self.assert_totals()

    def test_completion_releases_only_that_job_and_keeps_other_slots(self):
        self.s.propose_alternative();self.s.review_alternative();self.s.choose_plan('economy');first=self.s.current
        self.s.deliver_next_request();self.s.select(2);self.s.choose_plan('performance')
        other=self.s.servers.allocations[self.s.current.playthrough_id]
        self.s.select(1);first.state.work_done=first.state.work_total-1;self.s.advance_time(10)
        self.assertEqual(list(self.s.servers.allocations.values()),[other]);self.assert_totals()
        self.assertTrue(first.server_allocations);self.assertEqual(self.s.servers.usage('A'),(0,0))

    def test_network_incident_recovery_hold_the_same_allocation(self):
        self.s.choose_plan('performance');before=dict(self.s.servers.allocations)
        self.s.current.state.trigger_incident();self.s.respond('reroute');self.s.advance_time(10)
        self.assertEqual(self.s.servers.allocations,before);self.assert_totals()
        self.assertTrue(all(v['status'] in ('ACTIVE','IDLE') for v in server_views(self.s)))

    def fail(self):
        self.s.choose_plan('performance');self.s.current.state.trigger_incident()
        for _ in range(3):self.s.respond('ignore')

    def test_retry_gets_new_allocation_without_overwriting_failed_history(self):
        self.fail();parent=self.s.current.playthrough_id;record=tuple(self.db.get_playthrough(parent))
        self.assertEqual(self.s.servers.allocations,{})
        self.s.retry('performance')
        self.assertEqual(len(self.s.current.server_allocations),2)
        self.assertEqual(len(self.s.servers.allocations),1)
        self.assertNotIn(parent,self.s.servers.allocations)
        self.assertEqual(tuple(self.db.get_playthrough(parent)),record);self.assert_totals()

    def test_retry_preparation_is_not_reported_as_network_or_hardware_failure(self):
        self.fail();self.s.retry('performance')
        self.assertEqual(self.s.current.state.phase,'recovering')
        self.assertFalse(any(v['network'] for v in server_views(self.s)))
        self.s.advance_time(30);self.s.current.state.trigger_incident()
        self.assertTrue(any(v['network'] for v in server_views(self.s)))
        self.assertTrue(all(v['status'] in ('ACTIVE','IDLE') for v in server_views(self.s)))

    def test_start_database_failure_restores_ledger_and_history(self):
        before=self.usage()
        for method in ('create_playthrough','save_runtime','add_log'):
            with self.subTest(method=method),patch.object(self.db,method,side_effect=sqlite3.OperationalError('failure')):
                with self.assertRaises(sqlite3.OperationalError):self.s.choose_plan('performance')
            self.assertEqual(self.usage(),before);self.assertEqual(self.s.current.state.phase,'ready');self.assert_totals()

    def test_completion_save_failure_restores_server_occupancy(self):
        self.s.choose_plan('performance');self.s.current.state.work_done=119;before=self.usage()
        with patch.object(self.db,'save_result',side_effect=sqlite3.OperationalError('failure')):
            with self.assertRaises(sqlite3.OperationalError):self.s.advance_time(10)
        self.assertEqual(self.usage(),before);self.assertTrue(self.s.current.state.allocated);self.assert_totals()

    def test_retry_link_failure_restores_original_failure_and_no_new_slots(self):
        self.fail();before=self.usage()
        with patch.object(self.db,'link_retry',side_effect=sqlite3.OperationalError('failure')):
            with self.assertRaises(sqlite3.OperationalError):self.s.retry('performance')
        self.assertEqual(self.usage(),before);self.assert_totals()

    def test_resume_preserves_exact_slots_without_replaying_events(self):
        self.s.choose_plan('performance');self.s.advance_time(30)
        before=self.usage();events=list(map(tuple,self.db.get_request_events(1)))
        for _ in range(2):
            self.s=GameSession(self.db)
            self.assertEqual(self.usage(),before);self.assertEqual(self.s.current.state.work_done,30)
            self.assertEqual(list(map(tuple,self.db.get_request_events(1))),events);self.s.save();self.assert_totals()

    def test_old_active_save_reconstructs_without_changing_terms_or_records(self):
        self.s.choose_plan('performance');self.s.advance_time(30)
        payload=self.db.get_runtime(1);payload.pop('server_allocations');self.db.save_runtime(1,1,payload)
        record=tuple(self.db.get_playthrough(1));events=list(map(tuple,self.db.get_request_events(1)))
        terms=deepcopy(self.s.current.terms);proposals=deepcopy(self.s.current.proposals)
        self.s=GameSession(self.db)
        self.assertTrue(self.s.current.server_allocations[-1].reconstructed)
        self.assertEqual(self.s.current.terms,terms);self.assertEqual(self.s.current.proposals,proposals)
        self.assertEqual(tuple(self.db.get_playthrough(1)),record)
        self.assertEqual(list(map(tuple,self.db.get_request_events(1))),events);self.assert_totals()

        # 서버 기록이 전혀 없는 여러 과거 작업은 첫 탐욕 조합이 실패해도 공동 재구성합니다.
        db=Database(':memory:')
        try:
            old=GameSession(db,seed=9,incident_chance=0);old.deliver_next_request();old.deliver_next_request()
            for rid in (1,2,3):
                run=old.runs[rid];run.conditions={}
                run.state.choose_plan('economy')
                run.playthrough_id=db.create_playthrough(run.mission['id'],'economy')
                db.change_request_status(rid,'operating',run.playthrough_id)
            old.save()
            for rid in old.runs:
                payload=db.get_runtime(rid);payload.pop('server_allocations')
                db.save_runtime(rid,old.runs[rid].playthrough_id,payload)
            records=list(map(tuple,db.conn.execute('SELECT * FROM playthroughs ORDER BY id')))
            restored=GameSession(db)
            self.assertEqual((restored.servers.gpu_used,restored.servers.power_used),(10,9))
            self.assertTrue(all(a.reconstructed and not a.legacy for a in restored.servers.allocations.values()))
            self.assertEqual(list(map(tuple,db.conn.execute('SELECT * FROM playthroughs ORDER BY id'))),records)
        finally:db.close()

    def test_legacy_impossible_joint_layout_preserves_exact_old_totals(self):
        self.s.deliver_next_request();self.s.deliver_next_request()
        for rid in (1,2,3):
            run=self.s.runs[rid]
            run.state.choose_plan('economy')  # 서버가 없던 버전의 진행 저장 구성
            run.playthrough_id=self.db.create_playthrough(run.mission['id'],'economy')
            self.db.change_request_status(rid,'operating',run.playthrough_id)
        self.s.save()
        for rid,part in ((1,ServerSlice('A',(0,1,2,3),4)),(2,ServerSlice('B',(0,1),2))):
            payload=self.db.get_runtime(rid);payload['server_allocations']=[Allocation(rid,(part,)).payload()]
            self.db.save_runtime(rid,rid,payload)
        self.s=GameSession(self.db)
        self.assertTrue(self.s.runs[3].server_allocations[-1].legacy)
        self.assertEqual((self.s.center.gpu_used,self.s.center.power_used),(10,9));self.assert_totals()
        self.s.save();self.s=GameSession(self.db);self.assert_totals()

    def test_corrupted_saved_slot_overlap_is_rejected_without_database_changes(self):
        self.s.choose_plan('performance')
        value=self.db.get_runtime(1);value['server_allocations'][0]['slices'][0]['gpu_slots']=[0,0,1,2]
        self.db.save_runtime(1,1,value)
        with self.assertRaises(ValueError):GameSession(self.db)
        self.assertEqual(self.db.get_runtime(1),value)

    def test_disk_close_and_reopen_preserve_allocation_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'servers.db';db=Database(path)
            s=GameSession(db,seed=9,incident_chance=0);s.choose_plan('performance');s.advance_time(30)
            expected=deepcopy(s.servers.allocations);terms=deepcopy(s.current.terms)
            records=list(map(tuple,db.conn.execute('SELECT * FROM playthroughs ORDER BY id')))
            s.close()
            for _ in range(2):
                db=Database(path)
                try:
                    s=GameSession(db)
                    self.assertEqual(s.servers.allocations,expected);self.assertEqual(s.current.terms,terms)
                    self.assertEqual(list(map(tuple,db.conn.execute('SELECT * FROM playthroughs ORDER BY id'))),records)
                    self.assertEqual(s.current.state.work_done,30);s.save()
                finally:db.close()


class ServerConsoleTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        self.addCleanup(self.root.destroy)
        self.db=Database(':memory:');self.addCleanup(self.db.close)
        self.app=SimulatorApp(self.root,self.db,seed=9,incident_chance=0)
        self.addCleanup(self.app.network.stop)
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.root.update()

    def test_start_button_applies_preview_and_rack_click_updates_inspector(self):
        a=self.app;parts=a.session.allocation_preview(a.session.current,'performance')['slices']
        start_via_dialog(a);self.root.update()
        self.assertEqual(a.session.servers.allocations[a.playthrough_id].slices,parts)
        x1,y1,x2,y2=a.network.rack_bounds['C'];x,y=int((x1+x2)/2),int((y1+y2)/2)
        a.network.event_generate('<Motion>',x=x,y=y);a.network.event_generate('<Button-1>',x=x,y=y);self.root.update()
        self.assertEqual(a.resources.selected,'C')
        self.assertEqual(a.resources.inspector.values['gpu_used'],1)
        self.assertEqual(a.resources.inspector.values['power_used'],1)
        self.assertEqual(self.errors,[])

    def test_network_warning_keeps_gpu_healthy_and_actions_accessible(self):
        a=self.app;a.choose_plan('performance');a.state.trigger_incident();a.refresh()
        self.assertIn('reroute',a.action_buttons);self.assertIn('compress',a.action_buttons)
        self.assertTrue(any(v['network'] for v in a.network.views))
        self.assertFalse(a.network.find_withtag('gpu-fault'))
        self.assertEqual(len(a.network.find_withtag('gpu-busy')),7)

    def test_inspector_lists_every_customer_sharing_the_selected_server(self):
        a=self.app;s=a.session;s.deliver_next_request();s.deliver_next_request();s.select(2)
        s.current.conditions={};s.choose_plan('economy');s.select(3);s.choose_plan('economy');a.refresh()
        a.network.select('A');self.root.update()
        rows=[a.resources.owners.item(i,'values') for i in a.resources.owners.get_children()]
        self.assertEqual({row[0] for row in rows},{'Sakura Robotics','Northstar AI'})
        self.assertEqual(a.resources.inspector.values['gpu_used'],4)
        self.assertEqual(a.resources.inspector.values['power_used'],4)
        self.assertEqual({o['code'] for o in a.resources.inspector.values['slots']},{'jp','us'})

    def test_joint_block_disables_start_and_preview_does_not_reserve(self):
        a=self.app;s=a.session;s.propose_alternative();s.review_alternative();s.choose_plan('economy')
        s.deliver_next_request();s.deliver_next_request();s.select(2);s.current.conditions={};s.choose_plan('economy');s.select(3)
        a.plan_var.set('economy');a.refresh()
        before=dict(s.servers.allocations)
        self.assertEqual(a.action_buttons['start'].cget('state'),'disabled')
        self.assertIn('서버별',a.resources.preview.cget('text'))
        self.assertEqual(s.servers.allocations,before)

    def test_layout_and_chip_text_at_three_resolutions(self):
        a=self.app
        for state in ('pending','running','incident','finished'):
            if state=='running':a.choose_plan('performance')
            elif state=='incident':a.state.trigger_incident();a.refresh()
            elif state=='finished':a._perform(a.session.report_failure)
            for size in ('1000x650','1280x680','1366x768'):
                self.root.geometry(size);self.root.update()
                for item in a.network.find_all():
                    if a.network.type(item)=='text':
                        x1,y1,x2,y2=a.network.bbox(item)
                        with self.subTest(state=state,size=size,text=a.network.itemcget(item,'text')):
                            self.assertGreaterEqual(x1,0);self.assertGreaterEqual(y1,0)
                            self.assertLessEqual(x2,a.network.winfo_width());self.assertLessEqual(y2,a.network.winfo_height())
                for widget in (a.network,a.resources,a.notice_button,*a.action_buttons.values(),*a.time_buttons.values()):
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
                if a.active_list.get_children():
                    first=a.active_list.get_children()[0]
                    _,row_y,_,row_height=a.active_list.bbox(first)
                    self.assertLessEqual(row_y+row_height,a.active_list.winfo_height())
                    self.assertLessEqual(a.active_list.winfo_rooty()+a.active_list.winfo_height(),
                                         a.body.winfo_rooty()+a.body.winfo_height())
        self.assertEqual(self.errors,[])
