"""v0.9-3a: Chapter 3 화면 연결(실제 Tk). 작성만 했으며 사용자 데스크톱 보호를 위해 실행하지 않았습니다.

사용자가 직접 확인할 화면: 모드 선택의 Chapter 3 버튼, 브리핑/장애 안내 대화, [네트워크 진단] 창, 진단 전 대응 버튼 비활성,
대응 뒤 선배 피드백, Chapter 3 결과창(고정 버튼), Chapter 2 성공 결과창의 [Chapter 3 시작].
"""
import tempfile
import tkinter as tk
import unittest

from database import Database
from main import ModeSelection, SimulatorApp
from session import GameSession
from story_slots import StorySlots
from tests.support import dismiss_story_popups, start_with_consent
from tests.test_chapter3 import to_incident, finish_job, play_a_correctly


class Chapter3MenuGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        def factory(path):
            db = Database(':memory:')
            self.addCleanup(db.close)
            return db
        self.selector = ModeSelection(self.root, db_factory=factory, story_slots=StorySlots(self.directory.name))
        self.root.update()

    def test_story_menu_offers_chapter_three_start_and_resume(self):
        self.selector.show_story_menu(); self.root.update()
        self.assertEqual({'new', 'chapter2', 'chapter3', 'continue', 'continue3', 'back'}, set(self.selector.story_buttons))
        self.assertEqual(str(self.selector.story_buttons['continue3'].cget('state')), 'disabled')   # 진행 중인 Chapter 3이 없음

    def test_new_chapter_three_practice_starts_in_a_new_clean_slot(self):
        app = self.selector.new_story(3); self.root.update()
        self.addCleanup(app.network.stop)
        story = app.session.story
        self.assertTrue(story.practice and story.chapter3_active)
        self.assertIsNone(story.chapter2)
        self.assertFalse(story.chapter_completed)
        self.assertEqual(len(app.session.runs), 1)
        self.assertEqual(app.session.center.gpu_used, 0)
        self.assertIn('Chapter 3', app.story_objective.cget('text'))
        self.assertTrue(app.story_window.winfo_exists())                    # 선배 브리핑


class Chapter3PlayGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, mode='story', start_chapter=3, seed=5)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()
        self.session = self.app.session
        self.a = self.session.story.chapter3.request_ids[0]

    def begin(self):
        self.app.story_window.skip_button.invoke()
        self.app.story_window.next_button.invoke(); self.root.update()
        dismiss_story_popups(self.app, self.root)
        self.app.open_message(self.a); self.app.message_window.destroy()
        self.app.action_buttons['start'].invoke(); self.root.update()
        dialog = self.app.allocation_window
        dialog.auto_button.invoke(); dialog.start_button.invoke(); self.root.update()
        dismiss_story_popups(self.app, self.root)

    def test_responses_are_locked_until_the_diagnosis_window_is_opened(self):
        self.begin()
        self.app.advance_time(60); self.root.update()
        dismiss_story_popups(self.app, self.root)
        self.assertEqual(self.session.runs[self.a].state.phase, 'incident')
        self.assertIn('diagnose', self.app.action_buttons)
        for key in ('reroute', 'compress', 'ignore'):
            self.assertEqual(str(self.app.action_buttons[key].cget('state')), 'disabled')
        self.assertIn('GPU·서버 장비 정상', self.app.action_hint.cget('text'))
        self.assertNotIn('우회', self.app.story_objective.cget('text'))
        self.app.action_buttons['diagnose'].invoke(); self.root.update()
        window = self.app.diagnosis_window
        self.assertEqual(window.cells['주 통신 경로 상태'].cget('text'), 'DOWN')
        self.assertEqual(self.session.story.chapter3.diagnosed, [self.a])
        for key in ('reroute', 'compress', 'ignore'):
            self.assertEqual(str(self.app.action_buttons[key].cget('state')), 'normal')
        self.assertEqual(self.errors, [])

    def test_wrong_response_shows_observed_feedback_and_keeps_the_mission_open(self):
        self.begin()
        self.app.advance_time(60); dismiss_story_popups(self.app, self.root)
        self.app.action_buttons['diagnose'].invoke(); self.root.update()
        self.app.action_buttons['compress'].invoke(); self.root.update()
        state = self.session.runs[self.a].state
        self.assertEqual((state.phase, state.response_log), ('paused', ['compress']))
        self.assertTrue(self.app.feedback_window.winfo_exists())            # 짧은 결과 카드(FEEDBACK)
        self.assertIn('Chapter 3', self.app.feedback_window.title())
        self.assertFalse(self.app.diagnosis_window.winfo_exists())          # 대응 뒤 이전 진단 값은 닫힘
        dismiss_story_popups(self.app, self.root)
        self.assertIsNone(self.session.chapter3_pending_feedback())
        self.assertEqual(self.errors, [])

    def test_after_recovery_the_panel_shows_recovery_state_not_diagnosis(self):
        """v0.9-3a-2 (작성만, 미실행): 복구 후에는 [네트워크 진단]/[고객 지연 안내]가 주요 행동으로 남지 않습니다."""
        self.begin()
        self.app.advance_time(60); dismiss_story_popups(self.app, self.root)
        self.app.action_buttons['diagnose'].invoke(); self.root.update()
        self.app.action_buttons['reroute'].invoke(); self.root.update()
        self.assertIn('복구 준비 중', self.app.action_hint.cget('text'))
        self.assertIn('복구 준비: 10분 남음', self.app.action_hint.cget('text'))
        self.assertNotIn('diagnose', self.app.action_buttons)
        self.assertNotIn('delay', self.app.action_buttons)
        self.assertIn('복구 준비', self.app.story_objective.cget('text'))
        card = self.app.feedback_window
        self.assertEqual(card.cells['상태'].cget('text'), '복구 준비 중 · 10분')
        card.buttons['업무로 돌아가기'].invoke(); self.root.update()                 # 시간은 진행되지 않음
        self.assertEqual(self.session.runs[self.a].state.recovery_left, 10)
        self.app.advance_time(10); self.root.update()
        self.assertIn('정상 실행 중', self.app.action_hint.cget('text'))


class Chapter3ResultGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.session = GameSession(self.db, mode='story', start_chapter=3, seed=5)
        self.session.confirm_chapter3_briefing()
        a = self.session.story.chapter3.request_ids[0]
        self.session.read_conversation(a); self.session.selected_id = a
        self.session.choose_plan('performance')
        play_a_correctly(self.session, a)
        b = self.session.story.chapter3.request_ids[1]
        self.session.read_conversation(b); self.session.selected_id = b
        start_with_consent(self.session, 'performance')
        to_incident(self.session, b)
        self.session.view_network_diagnosis(b); self.session.respond('compress')
        finish_job(self.session, b)
        self.app = SimulatorApp.__new__(SimulatorApp)

    def test_result_dialog_shows_table_first_and_keeps_buttons_visible(self):
        from chapter_dialog import Chapter3CompleteDialog
        calls = []
        dialog = Chapter3CompleteDialog(self.root, self.session.chapter3_result(), lambda: calls.append('modes'),
                                        lambda: calls.append('free'), lambda: calls.append('status'),
                                        lambda: calls.append('review'), retry=lambda: calls.append('retry'))
        self.addCleanup(dialog.destroy)
        self.root.update()
        self.assertEqual(dialog.verdict.cget('text'), 'MISSION SUCCESS')
        self.assertEqual([c.cget('text') for c in dialog.table_cells[0]][:4], ['A', '경로 단절', '우회 성공 · 1회', '성공'])
        self.assertEqual([c.cget('text') for c in dialog.table_cells[1]][:4], ['B', '대역폭 부족', '압축 성공 · 1회', '성공'])
        for key in ('modes', 'free', 'status', 'review', 'retry'):
            button = dialog.buttons[key]
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), dialog.winfo_rooty()+dialog.winfo_height())
        self.assertFalse(dialog.summary.winfo_ismapped())                   # 상세 기록은 접혀 있음
        dialog.detail_button.invoke(); self.root.update()
        self.assertTrue(dialog.summary.winfo_ismapped())
        dialog.buttons['retry'].invoke()
        self.assertEqual(calls, ['retry'])


if __name__ == '__main__':
    unittest.main()


class Chapter3FailureCardGuiTests(unittest.TestCase):
    """대응 3회 실패 카드와 다음 행동 버튼(작성만, 미실행)."""
    def test_failed_card_offers_retry_and_follow_up_buttons(self):
        root = tk.Tk(); self.addCleanup(root.destroy)
        db = Database(':memory:'); self.addCleanup(db.close)
        app = SimulatorApp(root, db, mode='story', start_chapter=3, seed=5)
        self.addCleanup(app.network.stop)
        session = app.session
        a = session.story.chapter3.request_ids[0]
        session.confirm_chapter3_briefing(); session.read_conversation(a); session.selected_id = a
        session.choose_plan('performance')
        to_incident(session, a); session.view_network_diagnosis(a)
        for _ in range(3):
            session.respond('compress')
        app.refresh(); app.show_story_event(); root.update()
        card = app.feedback_window
        self.assertEqual(card.heading.cget('text'), 'NETWORK RECOVERY FAILED')
        self.assertEqual(set(card.buttons), {'Chapter 3 다시 도전', '후속 처리로 돌아가기'})
        card.buttons['후속 처리로 돌아가기'].invoke(); root.update()
        self.assertIn('retry', app.action_buttons); self.assertIn('report', app.action_buttons)
        self.assertIn('result3', app.action_buttons)                         # 닫은 뒤에도 결과를 다시 열 수 있음
        app.action_buttons['result3'].invoke(); root.update()
        self.assertTrue(app.feedback_window.winfo_exists())
        self.assertEqual(len(session.story.chapter3.request_ids), 1)         # 다음 미션으로 자동 이동하지 않음
