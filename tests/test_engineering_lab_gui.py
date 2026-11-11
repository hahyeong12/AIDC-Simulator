"""v0.9-4a/4a-1 Engineering Lab(Prototype) 화면 연결(실제 Tk). 작성만 했으며 사용자 데스크톱 보호를 위해 실행하지 않았습니다.

사용자가 직접 확인할 화면: 관제실 하단의 [Engineering Lab (Prototype)] 버튼, 지원하지 않는 미션의 안내,
Lab의 5개 탭(운영 상태·네트워크 구조·서버 내부·명령어 학습·가상 터미널), 장애 구간 표시와 흐름 애니메이션,
객관식/블록/터미널의 같은 결과, 관제실 복구 후 Lab 갱신, 창 종료 시 애니메이션 타이머 정리.
v0.9-4a-1부터 자유 체험은 [Engineering Lab 연습] 슬롯(start_chapter='lab')에서 하고, Chapter 3a에서는 관찰 미리보기만 엽니다.
"""
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database
from main import SimulatorApp
from tests.support import dismiss_story_popups
from tests.test_chapter3 import to_incident


class EngineeringLabGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, mode='story', start_chapter='lab', seed=5)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()
        s = self.app.session
        self.a = s.training.rid
        s.read_conversation(self.a)
        s.selected_id = self.a
        s.choose_plan('performance')
        to_incident(s, self.a)
        self.app.refresh()
        dismiss_story_popups(self.app, self.root)

    def snapshot(self):
        s = self.app.session
        # 학습 행동은 연수 기록(스토리 JSON)에만 남습니다. 게임 상태·원장·런타임은 그대로여야 합니다.
        return (s.minute, vars(s.runs[self.a].state).copy(), dict(s.servers.allocations), s.db.get_runtime(self.a))

    def test_open_lab_shows_same_incident_in_every_tab_without_changing_state(self):
        before = self.snapshot()
        lab = self.app.open_engineering_lab()
        self.root.update()
        self.assertTrue(lab.winfo_exists())
        self.assertIn('장애', lab.status_chip.cget('text'))
        self.assertIn('DOWN', lab.ops_chips['주 통신 경로'].cget('text'))
        lab.show_tab('네트워크 구조'); self.root.update()
        self.assertTrue(lab.net_canvas.find_withtag('break'))           # 끊어진 구간 ✕
        self.root.after(400); self.root.update()
        self.assertTrue(lab.net_canvas.find_withtag('packet'))          # 교육용 흐름 점
        lab.show_tab('서버 내부'); self.root.update()
        self.assertIn('10.0.0.20', lab.server_title.cget('text'))
        result = lab.choose_command('ping')
        self.assertEqual(result.facts['received'], 0)
        for kind, value in (('command', 'ping'), ('option', '-c 3'), ('target', lab.obs.target_address)):
            lab.place_block(kind, value)
        built = lab.run_blocks()
        typed = lab.run_terminal(f'ping -c 3 {lab.obs.target_address}')
        self.assertEqual(built.output, typed.output)
        self.assertEqual(result.output, typed.output)
        self.assertIn('100% packet loss', lab.term.get('1.0', 'end'))
        lab.set_level('advanced'); self.root.update()
        self.assertIn('help', lab.term_hint.cget('text'))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.errors, [])

    def test_recovery_in_control_room_updates_open_lab(self):
        lab = self.app.open_engineering_lab()
        self.root.update()
        self.app.respond('reroute')                                      # 연습 모드는 조치 잠금이 없습니다.
        dismiss_story_popups(self.app, self.root)
        self.assertIn('사용 중', lab.ops_chips['백업 경로'].cget('text'))
        self.assertEqual(lab.run_terminal(f'ping -c 1 {lab.obs.target_address}').facts['received'], 1)
        self.assertIn('192.168.20.1', lab.run_terminal('ip route').output)

    def test_lab_timer_is_cancelled_when_closed_and_on_mode_switch(self):
        lab = self.app.open_engineering_lab()
        self.root.update()
        self.assertIsNotNone(lab.anim_timer)
        lab.return_button.invoke()
        self.root.update()
        self.assertFalse(lab.winfo_exists())
        lab = self.app.open_engineering_lab()
        self.root.update()
        self.assertTrue(self.app.return_to_modes())
        self.root.update()
        self.assertFalse(lab.winfo_exists())
        self.assertEqual(self.errors, [])

    def test_unsupported_mission_only_shows_reason(self):
        app_session = self.app.session
        with patch('main.lab_support', return_value='지원하지 않는 미션'), patch('main.messagebox.showinfo') as info:
            self.assertIsNone(self.app.open_engineering_lab())
        info.assert_called_once()
        self.assertEqual(app_session.minute, self.app.session.minute)


class Chapter1HighlightGuiTests(unittest.TestCase):
    """Chapter 1: GPU·전력 확인 직후 다음 대상(요청 확인)에 금색 강조가 순간적으로 나타나지 않아야 합니다."""
    def test_no_highlight_flash_before_feedback(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        db = Database(':memory:')
        self.addCleanup(db.close)
        app = SimulatorApp(root, db, mode='story', seed=1)
        self.addCleanup(app.network.stop)
        root.update()
        dismiss_story_popups(app, root)
        app.select_server('A'); root.update()
        dismiss_story_popups(app, root)
        app.resources.book.select(app.resources.inspector_frame); root.update()
        shown = []
        original = app.tutorial_highlight.show
        app.tutorial_highlight.show = lambda key=None, widget=None: (shown.append((key, app.feedback_window)), original(key, widget))
        app.resource_confirm_button.invoke()
        root.update()
        # 피드백 창이 열리기 전에 'request' 대상이 강조되지 않습니다.
        self.assertFalse([k for k, window in shown if k == 'request' and window is None])


if __name__ == '__main__':
    unittest.main()


class Chapter3PreviewGuiTests(unittest.TestCase):
    """Chapter 3a 미션 A의 Lab은 관찰 탭만 열고 학습·터미널은 잠급니다(정규 연수 우회 방지)."""
    def test_preview_locks_learning_and_terminal(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        db = Database(':memory:')
        self.addCleanup(db.close)
        app = SimulatorApp(root, db, mode='story', start_chapter=3, seed=5)
        self.addCleanup(app.network.stop)
        s = app.session
        s.confirm_chapter3_briefing()
        a = s.story.chapter3.request_ids[0]
        s.read_conversation(a); s.selected_id = a; s.choose_plan('performance')
        to_incident(s, a)
        app.refresh(); dismiss_story_popups(app, root)
        lab = app.open_engineering_lab()
        root.update()
        self.assertEqual(lab.mode, 'preview')
        self.assertNotIn('연수 진행', lab.tabs)
        self.assertIsNone(lab.level)
        self.assertEqual(str(lab.term_entry.cget('state')), 'disabled')
        self.assertIsNone(lab.run_terminal('ip route'))
        self.assertIsNone(lab.choose_command('ping'))
