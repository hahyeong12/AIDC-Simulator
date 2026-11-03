"""Live server HUD regression tests replacing the aggregate Canvas layout."""
import tkinter as tk
import unittest
from database import Database
from main import SimulatorApp
from tests.support import start_with_consent, start_legacy_plan
from server_console import server_views

class ResourceHudTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.root.destroy)
        self.db=Database(':memory:'); self.addCleanup(self.db.close)
        self.app=SimulatorApp(self.root,self.db,seed=9,incident_chance=0)
        self.addCleanup(self.app.network.stop)
        self.errors=[]; self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.root.update()

    def test_initial_four_racks_have_ten_available_gpu_chips(self):
        a=self.app
        self.assertEqual(len(a.network.find_withtag('gpu-slot')),10)
        self.assertEqual(len(a.network.find_withtag('available-gpu')),10)
        self.assertEqual(a.overview.values['gpu_available'],10)
        self.assertEqual(a.overview.values['power_available'],10)
        self.assertEqual(a.overview.values['active_servers'],0)

    def test_zero_available_is_healthy_allocation_not_hardware_failure(self):
        a=self.app; a.choose_plan('performance'); a.network.select('A')
        self.assertEqual(a.resources.view['gpu_available'],0)
        self.assertEqual(a.resources.view['status'],'ACTIVE')
        self.assertFalse(a.network.find_withtag('gpu-fault'))
        self.assertEqual(a.overview.values['gpu_available'],3)

    def test_actual_allocation_and_return_restore_only_owned_modules(self):
        a=self.app; start_with_consent(a,'economy')
        self.assertEqual(len(a.network.find_withtag('gpu-busy')),4)
        a.state.work_done=a.state.work_total-1; a.advance_time(10)
        self.assertEqual(len(a.network.find_withtag('gpu-busy')),0)
        self.assertEqual(a.overview.values['gpu_available'],10)
        self.assertTrue(all(not v['owners'] for v in server_views(a.session)))

    def test_customer_ownership_and_untouched_slot_positions_survive_return(self):
        a=self.app; a.next_request(); a.next_request()
        for rid in (3,1,2):
            a.select_request(rid); start_legacy_plan(a,'economy')
        self.assertEqual(a.overview.values['jobs'],3)
        before={v['spec'].key:[o['playthrough_id'] if o else None for o in v['slots']] for v in server_views(a.session)}
        a.select_request(2); pid=a.playthrough_id
        a.state.work_done=a.state.work_total-1; a.advance_time(10)
        for v in server_views(a.session):
            after=[o['playthrough_id'] if o else None for o in v['slots']]
            self.assertEqual(after,[None if x==pid else x for x in before[v['spec'].key]])
        self.assertEqual(a.overview.values['gpu_available'],2)

    def test_battery_displays_available_power_from_server_sum(self):
        a=self.app; a.choose_plan('performance')
        views=server_views(a.session)
        self.assertEqual(a.overview.values['power_available'],sum(v['power_available'] for v in views))
        for v in views:
            a.network.select(v['spec'].key)
            self.assertEqual(a.resources.inspector.values['power_used'],v['power_used'])
            percent=a.resources.inspector.find_withtag('battery-percent')[0]
            self.assertIn(str(round(v['power_available']/v['spec'].power*100)),a.resources.inspector.itemcget(percent,'text'))

    def test_assignment_preview_never_reserves_server_slots(self):
        a=self.app
        before=dict(a.session.servers.allocations)
        for key in ('performance','economy'):
            a.plan_var.set(key); a.preview_plan(show_preview=True)
        self.assertEqual(a.session.servers.allocations,before)
        self.assertEqual(a.action_buttons['start'].cget('state'),'disabled')
        self.assertEqual(a.center.gpu_used,0)

    def test_refresh_does_not_add_gpu_items_or_timers(self):
        a=self.app; start_with_consent(a,'economy'); timer=a.network.timer
        items=len(a.network.find_all())
        for _ in range(100):
            a.network.redraw(); a.resources.refresh()
        self.assertEqual(len(a.network.find_all()),items)
        self.assertEqual(a.network.timer,timer)
        self.assertEqual(self.root.tk.call('after','info').count(timer),1)
        self.assertEqual(self.errors,[])

    def test_usage_change_and_stop_do_not_leak_animation_callbacks(self):
        a=self.app; timer=a.network.timer
        a.choose_plan('performance'); a.network.stop()
        self.assertIsNone(a.network.timer)
        self.assertNotIn(timer,self.root.tk.call('after','info'))
        a.network.start(); current=a.network.timer; a.network.start()
        self.assertEqual(a.network.timer,current)

    def test_hud_fits_laptop_and_minimum_window(self):
        a=self.app
        for size,cols in (('1000x650',2),('1280x680',4),('1366x768',4)):
            self.root.geometry(size);self.root.update()
            self.assertEqual(a.network.columns,cols)
            for widget in (a.overview,a.network,a.resources,a.action_hint,*a.action_buttons.values(),*a.time_buttons.values()):
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
            self.assertEqual(len(a.network.find_withtag('gpu-slot')),10)
        self.assertEqual(self.errors,[])
