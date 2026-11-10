"""v0.9-2b-1: 작업 시작 = 운영 모드 선택 → 서버 배정 계획 검토 → 최종 확인. Tk 창을 만들지 않는 검증.

설정창(AllocationDialog)의 화면 동작은 `tests/test_allocation_flow_gui.py`에 작성만 했고 실행하지 않았습니다.
여기서는 설정창이 의존하는 조회 함수·시작 차단 규칙·원장 보존·저장 호환을 실제 세션 엔진으로 확인합니다.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from allocation_dialog import start_blocker
from database import Database
from scroll_area import needs_scroll
from session import GameSession
from story_slots import StorySlots
from tests.test_chapter2 import ready, start, finish_all
from tests.test_chapter2_balance import until_finished
from tests.test_story_patch import prepare
from version import VERSION

ROOT = Path(__file__).resolve().parent.parent


def snapshot(s):
    """게임 시간·점유·원장·저장 JSON을 한 번에 비교하기 위한 값."""
    return (s.minute, s.center.gpu_used, s.center.power_used, deepcopy(s.servers.allocations),
            json.dumps(s.db.get_simulation(), sort_keys=True, default=str),
            {rid: (r.request['status'], r.state.phase, r.state.plan) for rid, r in s.runs.items()})


class ModeRowTests(unittest.TestCase):
    def test_rows_show_requirements_times_deadline_and_consent(self):
        s, jp, us = ready()
        rows = {r['key']: r for r in s.allocation_mode_rows(s.runs[us])}
        self.assertEqual((rows['performance']['gpu'], rows['performance']['power'], rows['performance']['minutes']), (6, 6, 70))
        self.assertEqual((rows['economy']['gpu'], rows['economy']['power'], rows['economy']['minutes']), (4, 3, 100))
        for row in rows.values():
            self.assertEqual(row['finish'], s.minute+row['minutes'])
            self.assertEqual(row['on_time'], row['finish'] <= s.runs[us].terms['due'])
            self.assertTrue(row['agreed'])
            self.assertEqual(row['reason'], '')
        self.assertEqual(rows['economy']['late_minutes'], max(0, rows['economy']['finish']-s.runs[us].terms['due']))

    def test_customer_that_does_not_allow_economy_needs_negotiation_explained(self):
        s, jp, us = ready()
        rows = {r['key']: r for r in s.allocation_mode_rows(s.runs[jp])}
        self.assertTrue(rows['performance']['agreed'])
        self.assertFalse(rows['economy']['agreed'])
        self.assertIn('협의', rows['economy']['reason'])
        self.assertIn('동의', rows['economy']['reason'])
        self.assertEqual(rows['economy']['status'], '고객 동의 필요')

    def test_pending_and_rejected_negotiation_are_explained_separately(self):
        s, jp, us = ready()
        run = s.runs[jp]
        run.proposals = [{'status': 'pending', 'proposed': {'mode': 'economy'}, 'original': {'mode': 'performance'}}]
        pending = {r['key']: r for r in s.allocation_mode_rows(run)}
        self.assertIn('협의 중', pending['economy']['reason'])
        run.proposals[-1]['status'] = 'rejected'
        rejected = {r['key']: r for r in s.allocation_mode_rows(run)}
        self.assertIn('거절', rejected['economy']['reason'])
        self.assertFalse(rejected['economy']['agreed'])

    def test_queries_never_change_time_resources_or_saved_game(self):
        s, jp, us = ready()
        before = snapshot(s)
        for rid in (jp, us):
            run = s.runs[rid]
            s.allocation_mode_rows(run)
            for mode in ('performance', 'economy'):
                s.allocation_preview(run, mode)
                s.allocation_options(run, mode)
        self.assertEqual(before, snapshot(s))
        self.assertEqual((s.center.gpu_used, s.center.power_used, s.servers.allocations), (0, 0, {}))

    def test_switching_mode_recomputes_plans_for_that_modes_requirement(self):
        s, jp, us = ready()
        run = s.runs[us]
        for mode, (gpu, power) in (('performance', (6, 6)), ('economy', (4, 3))):
            options = s.allocation_options(run, mode)['options']
            self.assertTrue(options)
            for parts in options:
                self.assertEqual((sum(p.gpu for p in parts), sum(p.power for p in parts)), (gpu, power))


class FinalStartTests(unittest.TestCase):
    def test_only_the_final_start_applies_the_chosen_mode_and_plan(self):
        s, jp, us = ready()
        s.selected_id = us
        options = s.allocation_options(s.runs[us], 'economy')['options']
        chosen = options[-1]
        self.assertEqual(s.servers.allocations, {})
        s.choose_plan('economy', server_plan=chosen)
        run = s.runs[us]
        self.assertEqual(run.state.plan, 'economy')
        self.assertEqual(run.server_allocations[-1].slices, chosen)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (4, 3))
        self.assertEqual(sum(a.gpu for a in s.servers.allocations.values()), s.center.gpu_used)

    def test_automatic_recommendation_equals_the_first_option(self):
        s, jp, us = ready()
        s.selected_id = jp
        options = s.allocation_options(s.runs[jp], 'performance')['options']
        s.choose_plan('performance')
        self.assertEqual(s.runs[jp].server_allocations[-1].slices, options[0])

    def test_mode_the_customer_did_not_agree_to_cannot_start_and_ledger_is_kept(self):
        s, jp, us = ready()
        s.selected_id = jp
        before = snapshot(s)
        with self.assertRaises(ValueError):
            s.choose_plan('economy')
        self.assertEqual(before, snapshot(s))

    def test_chapter1_request_does_not_allow_economy_without_agreement(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, mode='story', seed=9)
        prepare(s)
        run = s.runs[s.story.request_id]
        rows = {r['key']: r for r in s.allocation_mode_rows(run)}
        self.assertFalse(rows['economy']['agreed'])
        before = snapshot(s)
        with self.assertRaises(ValueError):
            s.choose_plan('economy')
        self.assertEqual(before, snapshot(s))
        self.assertFalse(run.state.allocated)

    def test_stale_plan_after_another_job_started_is_rejected_without_changing_ledger(self):
        s, jp, us = ready()
        old = s.allocation_options(s.runs[us], 'performance')['options']
        start(s, jp, 'performance')            # 다른 작업이 먼저 배정되어 자원이 줄었습니다.
        before = snapshot(s)
        s.selected_id = us
        with self.assertRaises(ValueError):
            s.choose_plan('performance', server_plan=old[0])
        self.assertEqual(before, snapshot(s))
        self.assertFalse(s.runs[us].state.allocated)

    def test_resource_shortage_keeps_ledger(self):
        s, jp, us = ready()
        start(s, us, 'performance')            # GPU 6/전력 6 사용 → 일본 고성능(4/5)은 전력이 부족합니다.
        before = snapshot(s)
        s.selected_id = jp
        self.assertFalse(s.allocation_options(s.runs[jp], 'performance')['allowed'])
        with self.assertRaises(ValueError):
            s.choose_plan('performance')
        self.assertEqual(before, snapshot(s))

    def test_second_customer_sees_reduced_options_after_first_is_placed(self):
        s, jp, us = ready()
        before = s.servers.available()
        start(s, jp, 'performance')
        after = s.servers.available()
        self.assertEqual((before[0]-after[0], before[1]-after[1]), (4, 5))
        rows = {r['key']: r for r in s.allocation_mode_rows(s.runs[us])}
        self.assertTrue(rows['economy']['agreed'])
        self.assertTrue(s.allocation_options(s.runs[us], 'economy')['allowed'])
        self.assertFalse(s.allocation_options(s.runs[us], 'performance')['allowed'])

    def test_chapter2_flow_still_succeeds_with_concurrent_plans(self):
        s, jp, us = ready()
        start(s, jp, 'performance'); start(s, us, 'economy')
        finish_all(s)
        self.assertEqual(s.chapter2_result()['mission'], 'success')
        self.assertEqual((s.center.gpu_used, s.center.power_used, s.servers.allocations), (0, 0, {}))


class StartGateTests(unittest.TestCase):
    def test_unconfirmed_choice_cannot_start(self):
        self.assertIn('직접 선택', start_blocker(True, False, False, 1, 1))

    def test_confirmed_choice_can_start_when_nothing_changed(self):
        self.assertIsNone(start_blocker(True, True, False, ('a',), ('a',)))

    def test_changed_situation_requires_reconfirmation(self):
        self.assertIn('다시 확인', start_blocker(True, True, False, ('a',), ('b',)))

    def test_no_options_cannot_start(self):
        self.assertIsNotNone(start_blocker(False, True, False, 1, 1))

    def test_migration_keeps_its_existing_first_plan_selection(self):
        self.assertIsNone(start_blocker(True, True, True, None, None))

    def test_scroll_only_when_content_is_taller(self):
        self.assertTrue(needs_scroll(900, 500))
        self.assertFalse(needs_scroll(500, 500))
        self.assertFalse(needs_scroll(300, 500))


class FlowWiringTests(unittest.TestCase):
    """GUI를 만들지 않고 소스에서 시작 우회 경로가 없는지 확인합니다."""
    source = (ROOT / 'main.py').read_text(encoding='utf-8')

    def test_main_start_button_opens_settings_instead_of_starting(self):
        self.assertIn("('start','배정 설정·선택',self.open_allocation_plans)", self.source)
        self.assertNotIn("('start','배정하고 작업 시작'", self.source)
        self.assertNotRegex(self.source, r"\('start',[^\n]*choose_plan")

    def test_only_the_dialog_final_start_calls_session_choose_plan_from_the_ui(self):
        calls = re.findall(r"session\.choose_plan\(", self.source)
        self.assertEqual(len(calls), 2)       # 프로그램용 choose_plan()과 설정창의 on_start 콜백뿐입니다.
        self.assertIn("server_plan=parts", self.source)

    def test_both_result_outcomes_receive_the_retry_callback(self):
        self.assertIn('retry=self.retry_chapter2', self.source)
        dialog = (ROOT / 'chapter_dialog.py').read_text(encoding='utf-8')
        self.assertIn('if retry is not None:', dialog)
        self.assertNotRegex(dialog, r"if success[^\n]*retry")
        self.assertIn("buttons.grid(row=2", dialog)       # 버튼 영역은 스크롤 영역 밖 고정 행입니다.

    def test_no_stale_version_strings_in_the_ui(self):
        for name in ('main.py', 'allocation_dialog.py', 'chapter_dialog.py'):
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertNotRegex(text, r"v0\.9-2a-3", name)
        self.assertEqual(VERSION, 'v0.9-3b')
        self.assertIn(VERSION, (ROOT / 'README.md').read_text(encoding='utf-8').split('\n', 3)[2])


class RetryKeepsSlotsTests(unittest.TestCase):
    def test_retry_uses_a_new_independent_slot_and_keeps_previous_result(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        slots = StorySlots(folder.name)
        first = slots.reserve_new()
        db = Database(str(first))
        s = GameSession(db, mode='story', start_chapter=2, seed=9)
        s.confirm_chapter2_briefing()
        jp, us = s.story.chapter2.request_ids
        start(s, jp, 'performance'); until_finished(s, jp)
        start(s, us, 'performance'); finish_all(s)      # 순차 고성능은 실패합니다.
        result = s.chapter2_result()
        s.close()
        digest = hashlib.md5(first.read_bytes()).hexdigest()
        second = slots.reserve_new()
        self.assertNotEqual(first, second)
        self.assertEqual(hashlib.md5(first.read_bytes()).hexdigest(), digest)
        reopened = Database(str(first)); self.addCleanup(reopened.close)
        again = GameSession(reopened, mode='story').chapter2_result()
        self.assertEqual((again['mission'], again['overall']), (result['mission'], result['overall']))
        self.assertEqual(second.stat().st_size, 0)


class FreeModeUnaffectedTests(unittest.TestCase):
    def test_free_mode_start_retry_and_hardware_rules_still_work(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, seed=9, incident_chance=0)
        s.deliver_next_request(); s.select(2)
        before = snapshot(s)
        options = s.allocation_options(s.current, 'performance')['options']
        self.assertEqual(before, snapshot(s))
        s.choose_plan('performance', server_plan=options[0])
        self.assertEqual(s.current.server_allocations[-1].slices, options[0])
        s.inject_server_fault(options[0][0].server_id)
        self.assertTrue(s.hardware_servers(s.current))
        self.assertEqual(sum(a.gpu for a in s.servers.allocations.values()), s.center.gpu_used)


if __name__ == '__main__':
    unittest.main()
