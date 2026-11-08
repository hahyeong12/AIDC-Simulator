"""v0.9-1e: 배정안 차별화·요청서 레이아웃·Chapter 완료창 중앙 정렬. 메모리 DB만 사용."""
import tkinter as tk
import unittest

from database import Database
from game import CUSTOMER_PLANS
from main import SimulatorApp
from request_summary import request_summary
from server_resources import Allocation, ServerPool, ServerSlice
from tests.test_story_patch import prepare
from ui import MessageDialog


class DistinctOptionTests(unittest.TestCase):
    def test_distinct_options_never_repeat_gpu_distribution_and_keep_recommendation(self):
        pool = ServerPool()
        for modes in CUSTOMER_PLANS.values():
            for plan in modes.values():
                options = pool.distinct_options(plan['gpu'], plan['power'])
                self.assertEqual(options[0], pool.plan(plan['gpu'], plan['power']))
                signatures = [tuple((s.server_id, s.gpu) for s in parts) for parts in options]
                self.assertEqual(len(set(signatures)), len(signatures))
                self.assertLessEqual(len(options), 3)
                for parts in options:
                    pool.validate_plan(parts, plan['gpu'], plan['power'])
        self.assertEqual(pool.allocations, {})

    def test_power_only_variants_are_collapsed(self):
        pool = ServerPool()
        raw = pool.options(7, 7)
        raw_signatures = [tuple((s.server_id, s.gpu) for s in parts) for parts in raw]
        self.assertEqual(raw_signatures[0], raw_signatures[1])  # 기존 안은 GPU가 같고 전력만 다름
        distinct = pool.distinct_options(7, 7)
        self.assertEqual(len({tuple((s.server_id, s.gpu) for s in p) for p in distinct}), len(distinct))
        self.assertEqual(distinct[0], raw[0])

    def test_single_possible_plan_is_shown_alone(self):
        pool = ServerPool()
        pool.reserve(Allocation(1, (ServerSlice('A', (0, 1, 2, 3), 4),
                                    ServerSlice('B', (0, 1, 2), 2), ServerSlice('C', (0, 1), 3))))
        self.assertEqual(len(pool.distinct_options(1, 1)), 1)
        self.assertEqual(pool.distinct_options(2, 2), ())


class FreeModeGuiTests(unittest.TestCase):
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

    def test_dialog_uses_numbered_names_and_explains_real_differences(self):
        self.app.resources.compare_button.invoke(); self.root.update()
        d = self.app.allocation_window
        titles = [b.cget('text') for b in d.plan_buttons]
        self.assertIn('배정안 1 (추천)', titles[0])
        self.assertTrue(all('대안' not in t and '추천안' not in t for t in titles))
        for caption in d.card_captions:
            text = caption.cget('text')
            self.assertIn('개 서버 사용', text)
            self.assertIn('남는 GPU 최대', text)
            self.assertNotIn('성능', text)
            self.assertNotIn('안정', text)
        self.assertIn('자동 추천과 같은 배분', d.card_captions[0].cget('text'))
        self.assertIn('추천안 대비 GPU', d.card_captions[1].cget('text'))
        signatures = [tuple((s.server_id, s.gpu) for s in o) for o in d.options]
        self.assertEqual(len(set(signatures)), len(signatures))
        self.assertEqual(self.app.center.gpu_used, 0)
        self.assertEqual(self.errors, [])

    def test_request_sheet_puts_large_gpu_and_power_first_using_real_data(self):
        run = self.app.session.current
        d = self.app.open_message(run.request['id']); self.root.update()
        summary = request_summary(run)
        tiles = d.requirement_tiles
        self.assertEqual(set(tiles), {'GPU 요구량', '전력 요구량'})
        for name, tile in tiles.items():
            labels = [w for w in tile.winfo_children() if isinstance(w, tk.Label)]
            self.assertIn(summary[name], [w.cget('text') for w in labels])
            big = next(w for w in labels if w.cget('text') == summary[name])
            self.assertGreaterEqual(big.winfo_reqheight(), 30)
            self.assertLess(tile.winfo_rooty(), d.bubble.winfo_rooty())
            self.assertTrue(any('현재 가용' in w.cget('text') for w in labels))
        texts = [w.cget('text') for w in d.summary_frame.winfo_children() if isinstance(w, tk.Label)]
        self.assertTrue(any(run.mission['company_name'] in t and run.mission['country'] in t for t in texts))
        self.assertEqual(d.summary_values, summary)
        # 고객 대화와 읽기 컨트롤 보존
        self.assertTrue(d.bubble.winfo_ismapped() and d.next_button.winfo_ismapped())
        self.assertEqual(self.app.center.gpu_used, 0)

    def test_request_sheet_fits_small_and_large_windows(self):
        run = self.app.session.current
        for size in ('1000x650', '1280x680', '1366x768', 'zoomed'):
            with self.subTest(size=size):
                if size == 'zoomed': self.root.state('zoomed')
                else: self.root.state('normal'); self.root.geometry(size)
                self.root.update()
                d = MessageDialog(self.root, run.mission['company_name'], run.mission['country'],
                                  self.app.session.conversation(run.request['id']), animate=False,
                                  summary=request_summary(run), availability=(10, 10))
                self.root.update()
                for widget in (d.summary_frame, d.bubble, d.page, d.next_button, d.skip_button, *d.requirement_tiles.values()):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreaterEqual(widget.winfo_rooty(), d.winfo_rooty())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), d.winfo_rooty()+d.winfo_height())
                self.assertGreaterEqual(d.bubble.winfo_height(), 60)
                d.destroy()


class ChapterWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, mode='story', seed=9)
        self.addCleanup(self.app.network.stop)
        self.root.update()

    def complete(self):
        prepare(self.app.session)
        self.app.session.choose_plan('performance')
        self.app.advance_time(10)
        self.app.session.confirm_story_operations()
        self.app.advance_time(60); self.app.advance_time(60)
        self.root.update()
        return self.app.chapter_window

    def assert_centered(self, d):
        self.root.update()
        px = self.root.winfo_rootx()+self.root.winfo_width()/2
        py = self.root.winfo_rooty()+self.root.winfo_height()/2
        dx = d.winfo_rootx()+d.winfo_width()/2
        dy = d.winfo_rooty()+d.winfo_height()/2
        self.assertLessEqual(abs(px-dx), 40)
        self.assertLessEqual(abs(py-dy), 60)
        self.assertGreater(d.winfo_rootx(), 0)
        self.assertGreater(d.winfo_rooty(), 0)

    def test_chapter_dialog_is_centered_on_game_window(self):
        self.root.geometry('1280x680+200+60'); self.root.update()
        d = self.complete()
        self.assertTrue(d.winfo_exists())
        self.assert_centered(d)
        for key in ('modes', 'free', 'status', 'review'):
            self.assertTrue(d.buttons[key].winfo_ismapped())
        self.assertIn('운영 점수', d.full_text)

    def test_chapter_dialog_stays_inside_work_area_on_small_window(self):
        self.root.geometry('1000x650+0+0'); self.root.update()
        d = self.complete()
        self.root.update()
        from window_placement import work_area
        left, top, right, bottom = work_area(self.root)
        self.assertGreaterEqual(d.winfo_rootx(), left)
        self.assertGreaterEqual(d.winfo_rooty(), top)
        self.assertLessEqual(d.winfo_rootx()+d.winfo_width(), right)
        self.assertLessEqual(d.winfo_rooty()+d.winfo_height(), bottom)
        for key in ('modes', 'free', 'status', 'review'):
            self.assertLessEqual(d.buttons[key].winfo_rooty()+d.buttons[key].winfo_height(),
                                 d.winfo_rooty()+d.winfo_height())

    def test_chapter_dialog_is_centered_when_maximized(self):
        self.root.state('zoomed'); self.root.update()
        self.assert_centered(self.complete())


if __name__ == '__main__':
    unittest.main()
