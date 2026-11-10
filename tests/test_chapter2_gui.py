"""v0.9-2a: Chapter 2 화면 연결(실제 Tk). 작성만 했으며 사용자 데스크톱 보호를 위해 아직 실행하지 않았습니다."""
import tkinter as tk
import unittest

from database import Database
from main import SimulatorApp
from tests.support import dismiss_story_popups
from tests.test_story_patch import prepare, finish


class Chapter2GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.app = SimulatorApp(self.root, self.db, mode='story', seed=9)
        self.addCleanup(self.app.network.stop)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.update()
        prepare(self.app.session); finish(self.app.session)
        self.app.refresh(); self.app.show_chapter_complete(); self.root.update()

    def test_chapter_one_dialog_offers_chapter_two_and_start_opens_briefing(self):
        self.assertIn('chapter2', self.app.chapter_window.buttons)
        self.app.chapter_window.buttons['chapter2'].invoke(); self.root.update()
        story = self.app.session.story
        self.assertTrue(story.chapter2_active)
        self.assertTrue(story.chapter_completed)
        self.assertIsNone(self.app.chapter_window)
        self.assertTrue(self.app.story_window.winfo_exists())
        self.assertIn('Chapter 2', self.app.story_objective.cget('text'))
        self.assertEqual(self.app.session.center.gpu_used, 0)
        self.assertEqual(self.errors, [])

    def test_briefing_confirm_moves_to_requests_and_feedback_appears(self):
        self.app.chapter_window.buttons['chapter2'].invoke(); self.root.update()
        d = self.app.story_window
        d.skip_button.invoke()
        d.next_button.invoke(); self.root.update()
        self.assertTrue(self.app.session.story.chapter2.briefing_confirmed)
        self.assertEqual(self.app.session.story.ui_step, 'c2_requests')
        self.assertEqual(self.app.feedback_window.event, 'c2_briefing')
        dismiss_story_popups(self.app, self.root)

    def test_comparison_dialog_lists_other_request_impact_in_chapter_two(self):
        self.app.chapter_window.buttons['chapter2'].invoke(); self.root.update()
        dismiss_story_popups(self.app, self.root)
        self.app.session.confirm_chapter2_briefing()
        self.app.select_request(self.app.session.story.chapter2.us_request_id)
        d = self.app.open_allocation_plans(); self.root.update()
        self.assertIn('이 안을 선택하면', d.impact_label.cget('text'))
        d.plan_buttons[0].invoke(); self.root.update()
        self.assertIn(self.app.session.story.chapter2.us_request_id, self.app.session.story.chapter2.reviewed)
        self.assertEqual(self.app.session.center.gpu_used, 0)
        d.destroy()



class PracticeAndRetryGuiTests(unittest.TestCase):
    """Chapter 2 연습 시작과 재도전 화면. 작성만 했으며 사용자 데스크톱 보호를 위해 아직 실행하지 않았습니다."""
    def setUp(self):
        import tempfile
        from main import ModeSelection
        from story_slots import StorySlots
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.databases = []

        def factory(path):
            db = Database(':memory:'); self.databases.append(db)
            self.addCleanup(db.close)
            return db
        self.selector = ModeSelection(self.root, db_factory=factory, story_slots=StorySlots(self.directory.name))
        self.root.update()

    def test_story_menu_offers_chapter_one_chapter_two_and_continue(self):
        self.selector.show_story_menu(); self.root.update()
        self.assertEqual({'new', 'chapter2', 'continue', 'back'}, set(self.selector.story_buttons))

    def test_new_chapter_two_practice_starts_clean_in_a_new_slot(self):
        app = self.selector.new_story(2); self.root.update()
        self.addCleanup(app.network.stop)
        story = app.session.story
        self.assertTrue(story.practice and story.chapter2_active)
        self.assertFalse(story.chapter_completed)
        self.assertEqual(len(app.session.runs), 2)
        self.assertEqual(app.session.minute, 540)
        self.assertIn('Chapter 2', app.story_objective.cget('text'))
        self.assertTrue(app.story_window.winfo_exists())      # 브리핑
        self.assertFalse(app.story_skip_button.winfo_ismapped())
        # v0.9-2a-4: 브리핑 마지막 장에 두 고객 비교표(실제 엔진 값)가 붙습니다. 작성만 했으며 아직 실행하지 않았습니다.
        texts = [text for _, text in app.story_window.steps]
        self.assertIn('두 고객 요청 비교', texts[-1])
        self.assertIn('서버별 남은 GPU/전력', texts[-1])

    def test_result_dialog_has_retry_and_retry_opens_a_new_practice_slot(self):
        app = self.selector.new_story(2); self.root.update()
        self.addCleanup(app.network.stop)
        s = app.session
        s.confirm_chapter2_briefing()
        jp, us = s.story.chapter2.request_ids
        s.selected_id = jp; s.choose_plan('performance')
        s.selected_id = us; s.choose_plan('economy')
        for _ in range(20):
            if s.story.chapter2.completed:
                break
            s.advance_time(10)
        app.refresh(); app.show_chapter_complete(); self.root.update()
        dialog = app.chapter_window
        self.assertIn('retry', dialog.buttons)
        self.assertIn('주요 운영 결정', dialog.full_text)
        self.assertEqual(dialog.verdict.cget('text'), 'MISSION SUCCESS')
        self.assertIn('기한을 지킨 방법', dialog.full_text)      # v0.9-2a-4 성공 설명(작성만, 미실행)
        # v0.9-2b: 요약표 우선 구조(작성만, 미실행). 상세 기록은 처음에 접혀 있고 버튼으로 펼칩니다.
        self.assertEqual(dialog.stats['성공 고객'].cget('text'), '2 / 2')
        self.assertEqual(len(dialog.table_cells), 2)
        self.assertFalse(dialog.summary.winfo_ismapped())
        dialog.detail_button.invoke(); self.root.update()
        self.assertTrue(dialog.summary.winfo_ismapped())
        app.db_factory = lambda path: Database(':memory:')
        dialog.buttons['retry'].invoke(); self.root.update()
        fresh = self.selector.app if self.selector.app is not None else app.mode_selector.app
        self.addCleanup(fresh.db.close)
        self.assertTrue(fresh.session.story.practice)
        self.assertEqual(fresh.session.story.chapter2.completed_steps, [])



class FailureFeedbackGuiTests(unittest.TestCase):
    """실패 확정 즉시 선배 안내와 SUCCESS/FAILED 결과 창. 작성만 했으며 아직 실행하지 않았습니다."""
    def setUp(self):
        from main import ModeSelection
        from story_slots import StorySlots
        import tempfile
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.selector = ModeSelection(self.root, db_factory=lambda path: Database(':memory:'),
                                      story_slots=StorySlots(self.directory.name))
        self.app = self.selector.new_story(2); self.root.update()
        self.addCleanup(self.app.network.stop)
        dismiss_story_popups(self.app, self.root)
        self.app.session.confirm_chapter2_briefing()
        self.jp, self.us = self.app.session.story.chapter2.request_ids

    def test_us_first_does_not_show_failure_until_the_request_is_actually_lost(self):
        self.app.select_request(self.us)
        self.app.choose_plan('performance'); self.root.update()
        self.assertFalse(self.app.story_window is not None and self.app.story_window.winfo_exists())
        self.assertFalse(self.app.session.chapter2_failure_pending)
        self.assertFalse(self.app.story_retry_button.winfo_ismapped())     # 아직 대응을 시도하지 않음
        # 일본 요청을 직접 거절하면 그때 선배가 설명하고 재도전을 제안합니다.
        self.app.select_request(self.jp)
        self.app._perform(lambda: self.app.session.reject_request('현재 GPU 자원 부족')); self.root.update()
        window = self.app.story_window
        self.assertTrue(window.winfo_exists())
        self.assertIn('일본 고객', window.full_text)
        self.assertEqual(window.close_button.cget('text'), '기존 진행 계속 보기')
        self.assertFalse(self.app.session.chapter2_failure_pending)
        window.destroy(); self.root.update()
        self.app.advance_time(10); self.root.update()
        self.assertFalse(self.app.story_window is not None and self.app.story_window.winfo_exists())
        self.assertEqual(self.app.session.runs[self.us].state.phase, 'running')

    def test_failed_result_dialog_does_not_celebrate(self):
        s = self.app.session
        s.selected_id = self.us; s.choose_plan('performance')
        for _ in range(20):
            if s.story.chapter2.completed:
                break
            s.advance_time(10)
        self.app.refresh(); self.app.show_chapter_complete(); self.root.update()
        dialog = self.app.chapter_window
        self.assertEqual(dialog.verdict.cget('text'), 'MISSION FAILED')
        self.assertIn('50/100', dialog.full_text)
        self.assertNotIn('COMPLETE', dialog.verdict.cget('text'))
        self.assertIn('retry', dialog.buttons)


if __name__ == '__main__':
    unittest.main()
