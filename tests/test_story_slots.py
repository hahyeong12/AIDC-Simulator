"""v0.9-1b-1 중앙 메뉴, 독립 스토리 슬롯, 중복 실행과 전환 복구."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from database import Database, DB_PATH
from main import ModeSelection, SimulatorApp
from save_lease import SaveLease
from session import GameSession
from story_slots import StorySlots
from tests.test_story import gameplay
from tests.test_story_patch import prepare, finish


def saved_story(path, complete=False):
    db = Database(path)
    s = GameSession(db, mode='story', seed=9)
    if complete:
        prepare(s); finish(s)
    result = deepcopy(gameplay(s))
    s.close()
    return result


class SlotFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.slots = StorySlots(self.temp.name)

    def test_menu_discovery_does_not_create_any_files(self):
        self.assertEqual(self.slots.available(), [])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_new_slots_never_overwrite_legacy_or_previous_slot(self):
        saved_story(self.slots.legacy_path, complete=True)
        original = self.slots.legacy_path.read_bytes()
        first = self.slots.reserve_new(); saved_story(first)
        previous = first.read_bytes()
        second = self.slots.reserve_new()
        self.assertEqual(first.name, 'aidc_story_slot_001.db')
        self.assertEqual(second.name, 'aidc_story_slot_002.db')
        self.assertEqual(self.slots.legacy_path.read_bytes(), original)
        self.assertEqual(first.read_bytes(), previous)
        self.assertEqual(self.slots.available(), [self.slots.legacy_path, first, second])

    def test_discovery_ignores_other_files_and_sqlite_auxiliary_files(self):
        for name in ('aidc_story_slot_002.db', 'aidc_story_slot_010.db', 'aidc_story_slot_bad.db',
                     'aidc_story_slot_002.db-wal', 'aidc_story_slot_002.db-shm',
                     'aidc_story_slot_002.db.lock', 'aidc_game.db'):
            (Path(self.temp.name)/name).touch()
        self.assertEqual([p.name for p in self.slots.available()],
                         ['aidc_story_slot_002.db', 'aidc_story_slot_010.db'])

    def test_exclusive_create_retries_if_another_launcher_reserves_same_number(self):
        original = Path.open
        collision = self.slots.directory/'aidc_story_slot_001.db'
        def racing_open(path, *args, **kwargs):
            if path == collision and not path.exists():
                with original(path, 'wb') as file: file.write(b'other session')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', racing_open):
            path = self.slots.reserve_new()
        self.assertEqual(path.name, 'aidc_story_slot_002.db')
        self.assertEqual(collision.read_bytes(), b'other session')

    def test_slot_labels_clearly_distinguish_legacy_and_new_records(self):
        self.assertIn('기존 스토리', self.slots.title(self.slots.legacy_path))
        self.assertIn('새 스토리 1', self.slots.title(self.slots.reserve_new()))

    def test_git_ignores_slots_journal_wal_shm_and_lease(self):
        names = ['aidc_story_slot_001.db', 'aidc_story_slot_001.db-journal',
                 'aidc_story_slot_001.db-wal', 'aidc_story_slot_001.db-shm',
                 'aidc_story_slot_001.db.lock', 'aidc_game.db.lock', 'aidc_story.db.lock']
        result = subprocess.run(['git', 'check-ignore', '-z', '--stdin'], input=('\0'.join(names)+'\0').encode(),
                                capture_output=True, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode().rstrip('\0').split('\0'), names)

    def test_lease_blocks_same_file_and_releases_on_close(self):
        path = self.slots.reserve_new()
        lease = SaveLease(path)
        try:
            with self.assertRaises(ValueError): SaveLease(path)
        finally:
            lease.close()
        other = SaveLease(path); other.close()

    def test_lease_blocks_separate_process_and_does_not_depend_on_lock_file_deletion(self):
        path = self.slots.reserve_new()
        lease = SaveLease(path)
        script = ('from save_lease import SaveLease; import sys\n'
                  'try: lease=SaveLease(sys.argv[1])\n'
                  'except ValueError: sys.exit(17)\n'
                  'lease.close()\n')
        try:
            result = subprocess.run([sys.executable, '-c', script, str(path)], capture_output=True)
            self.assertEqual(result.returncode, 17, result.stderr)
        finally:
            lease.close()
        self.assertTrue(Path(str(path)+'.lock').exists())
        result = subprocess.run([sys.executable, '-c', script, str(path)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class SlotMenuGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.slots = StorySlots(self.temp.name)
        self.opened, self.databases, self.apps = [], [], []
        def factory(path):
            actual = Path(self.temp.name)/DB_PATH.name if Path(path) == DB_PATH else Path(path)
            self.opened.append(actual)
            db = Database(actual); self.databases.append(db)
            return db
        self.factory = factory
        self.addCleanup(self.cleanup_games)
        self.menu = ModeSelection(self.root, db_factory=factory, story_slots=self.slots)
        self.errors = []
        self.root.report_callback_exception = lambda *args:self.errors.append(args)
        self.root.update()

    def cleanup_games(self):
        for app in self.apps:
            app.closed = True
            app.cancel_story_event()
            app.network.stop()
        for db in self.databases: db.close()

    def story_menu(self, menu=None):
        menu = menu or self.menu
        menu.buttons['story'].invoke(); self.root.update()
        return menu

    def new(self, menu=None):
        menu = self.story_menu(menu)
        menu.story_buttons['new'].invoke(); self.root.update()
        if menu.app is not None: self.apps.append(menu.app)
        return menu.app

    def resume(self, path, menu=None):
        menu = self.story_menu(menu)
        menu.slot_choice.current(menu.slot_paths.index(path))
        menu.story_buttons['continue'].invoke(); self.root.update()
        if menu.app is not None: self.apps.append(menu.app)
        return menu.app

    def assert_centered(self, menu):
        self.root.update()
        panel = menu.content
        left, top = panel.winfo_x(), panel.winfo_y()
        right = menu.frame.winfo_width()-left-panel.winfo_width()
        bottom = menu.frame.winfo_height()-top-panel.winfo_height()
        self.assertLessEqual(abs(left-right), 2)
        self.assertLessEqual(abs(top-bottom), 2)
        self.assertGreaterEqual(min(left, top, right, bottom), 0)
        self.assertLessEqual(panel.winfo_width(), 860)
        for button in (*menu.buttons.values(), *menu.story_buttons.values()):
            if not button.winfo_ismapped(): continue
            self.assertGreaterEqual(button.winfo_rootx(), self.root.winfo_rootx())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),
                                 self.root.winfo_rooty()+self.root.winfo_height())

    def test_both_menus_are_centered_at_three_resolutions(self):
        for width, height in ((1000,650), (1280,680), (1366,768)):
            self.root.geometry(f'{width}x{height}')
            self.menu.show_modes(); self.assert_centered(self.menu)
            self.story_menu(); self.assert_centered(self.menu)

    def test_actual_maximized_window_keeps_balanced_margins(self):
        self.root.state('zoomed'); self.root.update()
        self.assertEqual(self.root.state(), 'zoomed')
        self.assert_centered(self.menu)
        self.story_menu(); self.assert_centered(self.menu)
        self.assertEqual(self.root.state(), 'zoomed')

    def test_story_choice_and_back_open_no_database(self):
        self.story_menu()
        self.assertTrue(self.menu.story_panel.winfo_ismapped())
        self.assertEqual(set(self.menu.story_buttons), {'new', 'continue', 'back'})
        self.menu.story_buttons['back'].invoke(); self.root.update()
        self.assertTrue(self.menu.mode_panel.winfo_ismapped())
        self.assertEqual(self.opened, [])
        self.assertEqual(self.slots.available(), [])

    def test_continue_is_disabled_when_there_is_no_saved_story(self):
        self.story_menu()
        self.assertEqual(str(self.menu.story_buttons['continue'].cget('state')), 'disabled')
        self.menu.story_buttons['continue'].invoke()
        self.assertEqual(self.opened, [])

    def test_legacy_completed_record_resumes_with_same_score_and_history(self):
        expected = saved_story(self.slots.legacy_path, complete=True)
        app = self.resume(self.slots.legacy_path)
        self.assertEqual(gameplay(app.session), expected)
        self.assertTrue(app.session.story.chapter_completed)
        self.assertTrue(app.chapter_window.winfo_exists())
        self.assertIsNone(app.story_window)
        self.assertEqual(len(app.db.get_recent_records()), 1)

    def test_new_story_starts_at_first_monologue_even_with_legacy_completion(self):
        saved_story(self.slots.legacy_path, complete=True)
        original = self.slots.legacy_path.read_bytes()
        app = self.new()
        self.assertNotEqual(app.db.path, self.slots.legacy_path)
        self.assertEqual(app.session.minute, 540)
        self.assertEqual(app.session.story.step, 'arrival')
        self.assertFalse(app.session.story.chapter_completed)
        self.assertIsNone(app.chapter_window)
        self.assertEqual(app.story_window.active_role, 'player')
        self.assertIn('여기가 오늘부터', app.story_window.full_text)
        self.assertEqual(app.center.gpu_used, 0)
        self.assertEqual(app.center.power_used, 0)
        self.assertEqual(len(app.session.runs), 1)
        self.assertEqual(app.db.get_recent_records(), [])
        self.assertEqual(self.slots.legacy_path.read_bytes(), original)

    def test_new_story_character_emphasis_and_events_are_unchanged(self):
        app = self.new(); dialog = app.story_window
        self.assertEqual(dialog.active_role, 'player')
        self.assertTrue(dialog.portraits['mentor'].find_withtag('inactive'))
        dialog.next_button.invoke()
        self.assertEqual(dialog.active_role, 'mentor')
        dialog.skip_button.invoke(); dialog.next_button.invoke()
        self.assertEqual(app.session.story.step, 'server')
        app.story_window.close_button.invoke()
        app.select_server('B'); self.root.update()
        self.assertEqual(app.session.story.step, 'server')
        app.select_server('A'); self.root.update()
        self.assertEqual(app.session.story.step, 'resources')
        self.assertIn('resources', app.session.story.dialogue_seen)
        old = app.story_window; old.destroy(); app.refresh(); app.select_server('A')
        self.assertFalse(old.winfo_exists())

    def test_new_story_full_chapter_through_real_widgets_preserves_old_record(self):
        saved_story(self.slots.legacy_path, complete=True)
        original = self.slots.legacy_path.read_bytes()
        app = self.new()
        dialog = app.story_window; dialog.skip_button.invoke(); dialog.next_button.invoke()
        self.assertEqual(app.session.story.step, 'server')
        app.story_window.close_button.invoke()
        bounds = app.network.rack_bounds['A']
        app.network.event_generate('<Button-1>', x=int((bounds[0]+bounds[2])/2),
                                    y=int((bounds[1]+bounds[3])/2))
        self.root.update()
        self.assertEqual(app.session.story.step, 'resources')
        app.story_window.close_button.invoke(); app.resource_confirm_button.invoke()
        self.assertEqual(app.session.story.step, 'request')
        app.arrival_open_button.invoke(); self.root.update()
        self.assertIn('Merlion AI', app.message_window.title())
        app.message_window.destroy(); self.root.update()
        self.assertEqual(app.session.story.step, 'preview')
        plans = app.open_allocation_plans(); plans.plan_buttons[1].invoke()
        selected = plans.options[1]; plans.start_button.invoke(); self.root.update()
        self.assertEqual(app.session.current.server_allocations[-1].slices, selected)
        self.assertEqual(app.session.story.step, 'time')
        self.assertEqual((app.center.gpu_used, app.center.power_used), (7,7))
        app.time_buttons[10].invoke(); self.root.update()
        self.assertGreater(app.state.work_done, 0)
        app.story_window.skip_button.invoke(); app.story_window.next_button.invoke()
        app.time_buttons[60].invoke(); app.time_buttons[60].invoke(); self.root.update()
        self.assertTrue(app.session.story.chapter_completed)
        self.assertTrue(app.session.story.tutorial_completed)
        self.assertEqual((app.center.gpu_used, app.center.power_used), (0,0))
        self.assertEqual(app.chapter_window.result['score'], app.state.score)
        self.assertEqual(len(app.db.get_recent_records()), 1)
        self.assertEqual(self.slots.legacy_path.read_bytes(), original)
        self.assertEqual(self.errors, [])

    def test_repeated_new_start_click_does_not_create_second_game_or_slot(self):
        app = self.new()
        self.assertIs(self.menu.new_story(), app)
        self.assertEqual(len(self.slots.available()), 1)
        self.assertEqual(len(self.opened), 1)

    def test_two_new_slots_keep_time_resources_score_and_progress_separate(self):
        first = self.new(); path1 = first.db.path
        prepare(first.session); finish(first.session)
        expected = deepcopy(gameplay(first.session))
        first.return_to_modes(); self.root.update()
        second = self.new(first.mode_selector); path2 = second.db.path
        self.assertNotEqual(path1, path2)
        self.assertEqual(second.session.minute, 540)
        self.assertIsNone(second.session.current.state.score)
        self.assertFalse(second.session.story.chapter_completed)
        second.session.read_conversation(1); second.session.choose_plan('performance'); second.advance_time(10)
        self.assertEqual(second.center.gpu_used, 7)
        second.return_to_modes(); self.root.update()
        resumed = self.resume(path1, second.mode_selector)
        self.assertEqual(gameplay(resumed.session), expected)
        self.assertEqual(resumed.center.gpu_used, 0)
        self.assertEqual(len(resumed.db.get_recent_records()), 1)

    def test_return_to_menu_prefers_current_slot_and_resumes_last_save(self):
        app = self.new(); path = app.db.path
        app.session.confirm_story_arrival(); app.select_server('A')
        expected = deepcopy(gameplay(app.session)), deepcopy(app.session.story.payload())
        timer = app.network.timer
        app.return_to_modes(); self.root.update()
        self.assertIsNone(app.network.timer)
        self.assertNotIn(timer, self.root.tk.call('after', 'info'))
        menu = self.story_menu(app.mode_selector)
        self.assertEqual(menu.slot_paths[menu.slot_choice.current()], path)
        menu.story_buttons['continue'].invoke(); self.root.update()
        self.apps.append(menu.app)
        self.assertEqual((gameplay(menu.app.session), menu.app.session.story.payload()), expected)
        self.assertIsNone(menu.app.story_window)  # 표시한 안내를 자동 반복하지 않습니다.

    def test_switch_to_free_preserves_both_story_slots_and_free_progress(self):
        free_path = self.slots.directory/DB_PATH.name
        db = Database(free_path); s = GameSession(db, seed=9, incident_chance=0)
        s.choose_plan('performance'); s.advance_time(30)
        free_expected = deepcopy(gameplay(s)); s.close()
        saved_story(self.slots.legacy_path, complete=True)
        legacy_bytes = self.slots.legacy_path.read_bytes()
        app = self.new(); new_path = app.db.path
        app.return_to_modes('free'); self.root.update()
        free = app.mode_selector.app; self.apps.append(free)
        self.assertEqual(gameplay(free.session), free_expected)
        self.assertEqual(self.slots.legacy_path.read_bytes(), legacy_bytes)
        self.assertTrue(new_path.is_file())
        self.assertIsNone(free.session.story)

    def test_continue_missing_file_does_not_create_a_replacement(self):
        path = self.slots.reserve_new(); saved_story(path)
        self.story_menu(); path.unlink()
        with patch('main.messagebox.showerror') as error:
            self.menu.story_buttons['continue'].invoke()
        error.assert_called_once()
        self.assertFalse(path.exists())
        self.assertEqual(self.opened, [])
        self.assertTrue(self.menu.story_panel.winfo_ismapped())

    def test_empty_slot_continue_does_not_silently_start_new_game(self):
        path = self.slots.reserve_new()
        self.story_menu()
        with patch('main.messagebox.showerror') as error:
            self.menu.story_buttons['continue'].invoke()
        error.assert_called_once()
        db = Database(path)
        try: self.assertIsNone(db.get_simulation())
        finally: db.close()
        self.assertIsNone(self.menu.app)

    def test_new_database_open_failure_keeps_legacy_and_usable_menu(self):
        saved_story(self.slots.legacy_path, complete=True)
        original = self.slots.legacy_path.read_bytes()
        self.menu.db_factory = lambda path:(_ for _ in ()).throw(OSError('열기 실패'))
        self.story_menu()
        with patch('main.messagebox.showerror') as error:
            self.menu.new_story()
        error.assert_called_once()
        self.assertIsNone(self.menu.app)
        self.assertFalse(self.menu.starting)
        self.assertTrue(self.menu.story_panel.winfo_ismapped())
        self.assertEqual(self.slots.legacy_path.read_bytes(), original)

    def test_new_initial_save_failure_keeps_old_record_and_stops_timers(self):
        saved_story(self.slots.legacy_path, complete=True)
        original = self.slots.legacy_path.read_bytes()
        self.story_menu()
        with patch.object(Database, 'save_simulation', side_effect=OSError('저장 실패')):
            with patch('main.messagebox.showerror') as error: self.menu.new_story()
        error.assert_called_once()
        self.assertIsNone(self.menu.app)
        self.assertFalse(self.root.tk.call('after', 'info'))
        self.assertEqual(self.slots.legacy_path.read_bytes(), original)
        self.assertFalse(self.databases[-1]._game_claimed)

    def test_partial_new_ui_failure_preserves_saved_slot_and_allows_resume(self):
        self.story_menu()
        with patch.object(SimulatorApp, 'show_story_event', side_effect=ValueError('화면 생성 실패')):
            with patch('main.messagebox.showerror') as error: self.menu.new_story()
        error.assert_called_once()
        self.assertFalse(self.root.tk.call('after', 'info'))
        path = self.slots.available()[0]
        app = self.resume(path)
        self.assertEqual(app.session.story.step, 'arrival')
        self.assertEqual(app.session.minute, 540)
        self.assertEqual(self.errors, [])

    def test_save_failure_keeps_active_slot_dialog_and_timer(self):
        app = self.new(); timer = app.network.timer; dialog = app.story_window
        before = deepcopy(app.session.story.payload()), '\n'.join(app.db.conn.iterdump())
        with patch.object(app.db, 'save_runtime', side_effect=OSError('저장 실패')):
            with patch('main.messagebox.showerror'):
                self.assertFalse(app.return_to_modes())
        self.assertFalse(app.closed)
        self.assertTrue(app.db._game_claimed)
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(timer, app.network.timer)
        self.assertEqual((app.session.story.payload(), '\n'.join(app.db.conn.iterdump())), before)

    def test_target_open_failure_preserves_previous_slot_after_safe_save(self):
        app = self.new(); path = app.db.path
        app.db_factory = lambda path:(_ for _ in ()).throw(OSError('대상 열기 실패'))
        with patch('main.messagebox.showerror'):
            app.return_to_modes('free'); self.root.update()
        self.assertTrue(app.closed)
        self.assertFalse(app.db._game_claimed)
        self.assertTrue(app.mode_selector.frame.winfo_ismapped())
        db = Database(path)
        try: self.assertEqual(GameSession(db, mode='story').story.step, 'arrival')
        finally: db.close()

    def test_duplicate_same_connection_cannot_start_second_gui(self):
        app = self.new(); extra_root = tk.Toplevel(self.root)
        with self.assertRaises(ValueError):
            SimulatorApp(extra_root, db=app.db, mode='story')
        self.assertTrue(app.db._game_claimed)
        self.assertIsNotNone(app.db.get_simulation())
        self.assertTrue(app.story_window.winfo_exists())

    def test_duplicate_file_connection_cannot_start_second_game(self):
        app = self.new(); db = Database(app.db.path)
        try:
            with self.assertRaises(ValueError): SimulatorApp(tk.Toplevel(self.root), db=db, mode='story')
            self.assertFalse(db._game_claimed)
            self.assertTrue(app.db._game_claimed)
        finally: db.close()
        app.return_to_modes(); self.root.update()
        resumed = self.resume(app.db.path, app.mode_selector)
        self.assertTrue(resumed.db._game_claimed)


if __name__ == '__main__':
    unittest.main()
