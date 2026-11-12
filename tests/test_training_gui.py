"""v0.9-4a-1 심화 연수 화면 연결(실제 Tk). 작성만 했으며 사용자 데스크톱 보호를 위해 실행하지 않았습니다.

사용자가 직접 확인할 화면: Chapter 3b 결과창·상단 바의 [심화 연수 시작], Lab [연수 진행] 탭의 Stage 지도(완료/현재/잠금),
잠긴 도움 수준·터미널, 구조도 구간 클릭, 확인 질문, [다음 Stage 시작], Stage 5의 장애 표시 숨김과 관제실 대응 잠금,
연수 결과창, 모드 메뉴의 [Engineering Lab 연습].
"""
import tkinter as tk
import unittest

from database import Database
from engineering_lab import TrainingResultDialog
from main import SimulatorApp
from tests.support import dismiss_story_popups
from tests.test_chapter3 import to_incident
from tests.test_training import (regular_after_3b, to_training_incident, pass_stage1, pass_stage2, pass_stage3, pass_stage4,
                                 stage5_evidence, SERVER)


class RegularTrainingGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        regular_after_3b(self.db).save()
        self.app = SimulatorApp(self.root, self.db, mode='story')
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()

    def test_3b_result_offers_training_and_lab_follows_stages(self):
        app = self.app
        self.assertTrue(app.chapter_window.winfo_exists())                    # Chapter 3b 결과창
        self.assertTrue(app.story_training_button.winfo_ismapped())
        self.assertTrue(app.begin_training())
        dismiss_story_popups(app, self.root)
        s = app.session
        to_training_incident(s)
        app.refresh(); dismiss_story_popups(app, self.root)
        lab = app.open_engineering_lab()
        self.root.update()
        self.assertEqual(lab.mode, 'training')
        self.assertIn('연수 진행', lab.tabs)
        self.assertIn('잠금', lab.stage_boxes['tool'][1].cget('text'))
        self.assertEqual(str(lab.level_buttons['beginner'].cget('state')), 'disabled')
        self.assertEqual(str(lab.term_entry.cget('state')), 'disabled')
        self.assertIsNone(lab.run_terminal('ip route'))
        self.assertTrue(lab.select_segment('primary-wan'))
        self.assertTrue(lab._answer('structure', 'impact', 'blocked'))
        self.root.update()
        self.assertEqual(lab.start_next(), 'tool')
        self.assertEqual(lab.level, 'beginner')
        self.assertEqual(lab.choose_command('ping').facts['received'], 0)
        self.assertEqual(self.errors, [])

    def test_stage5_hides_answers_and_locks_response_until_judged(self):
        app = self.app
        app.begin_training(); dismiss_story_popups(app, self.root)
        s = app.session
        rid = to_training_incident(s)
        for step in (pass_stage1, pass_stage2, pass_stage3, pass_stage4):
            step(s); s.start_next_stage()
        app.select_request(rid)
        app.refresh(); dismiss_story_popups(app, self.root)
        self.assertEqual(str(app.action_buttons['reroute'].cget('state')), 'disabled')
        lab = app.open_engineering_lab()
        self.root.update()
        self.assertTrue(lab.hide_answers)
        self.assertFalse(lab.net_canvas.find_withtag('break'))
        stage5_evidence(s)
        lab.refresh()
        self.assertTrue(lab._answer('independent', 'cause', 'path_down'))
        self.root.update()
        self.assertFalse(lab.hide_answers)
        self.assertEqual(str(app.action_buttons['reroute'].cget('state')), 'normal')
        app.respond('reroute'); dismiss_story_popups(app, self.root)
        lab = app.open_engineering_lab()
        self.assertEqual(lab.run_terminal(f'ping -c 3 {SERVER}').facts['received'], 3)
        self.root.update()
        self.assertTrue(s.training.done)
        self.assertEqual(self.errors, [])


class StageFlowGuiTests(unittest.TestCase):
    """v0.9-4a-2(작성만 · 미실행): 실습 준비 안내, 구조도 클릭, Stage 5 진행 가능 표시, 결과 화면 전환."""

    def make_app(self, **kwargs):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        if not kwargs:
            regular_after_3b(self.db).save()
        self.app = SimulatorApp(self.root, self.db, mode='story', **kwargs)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()
        dismiss_story_popups(self.app, self.root)
        return self.app

    def test_practice_lab_before_assignment_shows_setup_not_a_broken_link_task(self):
        app = self.make_app(start_chapter='lab', seed=5)
        lab = app.open_engineering_lab()
        self.root.update()
        self.assertIn('실습 준비 필요', lab.goal_title.cget('text'))
        self.assertEqual(lab.primary_action, 'control')                       # [관제실로 돌아가기]
        self.assertFalse(lab.segment_selectable)
        lab.show_tab('네트워크 구조'); self.root.update()
        self.assertFalse(lab.net_canvas.find_withtag('hit'))                  # 클릭 영역 없음
        self.assertIn('실습 준비 필요', lab.net_task.cget('text'))
        self.assertIsNone(lab.select_segment('primary-wan'))
        self.assertIsNone(app.session.training.answer('structure', 'segment'))
        s = app.session
        rid = s.training.rid
        s.read_conversation(rid); s.selected_id = rid; s.choose_plan('performance')
        lab.refresh(); self.root.update()
        self.assertIn('작업 진행 중', lab.goal_title.cget('text'))
        to_incident(s, rid)
        lab.refresh(); self.root.update()
        self.assertIn('Stage 1 · 끊어진 네트워크 구간을 찾으세요.', lab.goal_title.cget('text'))
        self.assertEqual(self.errors, [])

    def test_clicking_on_the_broken_segment_midpoint_selects_it(self):
        app = self.make_app(start_chapter='lab', seed=5)
        s = app.session
        to_training_incident(s)
        app.refresh(); dismiss_story_popups(app, self.root)
        lab = app.open_engineering_lab()
        lab.show_tab('네트워크 구조'); self.root.update()
        line = next(i for i in lab.net_canvas.find_withtag('pick:primary-wan') if 'link' in lab.net_canvas.gettags(i))
        x1, y1, x2, y2 = lab.net_canvas.coords(line)
        lab.net_canvas.event_generate('<Motion>', x=int((x1+x2)/2), y=int((y1+y2)/2))
        lab.net_canvas.event_generate('<Button-1>', x=int((x1+x2)/2), y=int((y1+y2)/2))
        self.root.update()
        self.assertTrue(s.training.answered('structure', 'segment'))
        self.assertTrue(lab.net_canvas.find_withtag('break'))                 # 맞힌 뒤 ✕ 표시
        self.assertTrue(lab.net_canvas.find_withtag('chosen'))
        self.assertIn('✔', lab.net_task.cget('text'))
        self.assertEqual(self.errors, [])

    def test_stage5_available_banner_and_result_after_verification(self):
        app = self.make_app()
        app.begin_training(); dismiss_story_popups(app, self.root)
        s = app.session
        rid = to_training_incident(s)
        for step in (pass_stage1, pass_stage2, pass_stage3):
            step(s); s.start_next_stage()
        pass_stage4(s)
        app.refresh(); dismiss_story_popups(app, self.root)
        lab = app.open_engineering_lab()
        self.root.update()
        self.assertEqual(lab.goal_title.cget('text'), 'Stage 5 · 독립 진단')
        self.assertIn('진행 가능', lab.goal_chip.cget('text'))
        self.assertIn('지금까지 배운 방법을 이용해 직접 장애를 해결해 보세요.', lab.goal_detail.cget('text'))
        self.assertIn('진행 가능', lab.stage_boxes['independent'][1].cget('text'))
        self.assertEqual(lab.primary_action, 'next')
        self.assertEqual(lab.on_stage_click('independent'), 'independent')    # '진행 가능' 상자 클릭 = 다음 Stage 시작
        stage5_evidence(s)
        lab.refresh()
        self.assertTrue(lab._answer('independent', 'cause', 'path_down'))
        app.select_request(rid)
        app.respond('reroute'); dismiss_story_popups(app, self.root)
        lab = app.open_engineering_lab()
        lab.run_terminal(f'ping -c 3 {SERVER}')
        self.root.update()
        self.assertTrue(s.training.done)
        self.assertIsInstance(app.chapter_window, TrainingResultDialog)       # 마지막 Stage 통과 → 결과 화면
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
