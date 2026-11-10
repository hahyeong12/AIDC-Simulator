"""v0.9-3b: Chapter 3b(서버 장비 장애 — 장비 복구 vs 작업 이전). Tk 창을 만들지 않는 검증.

미션 A(일본 GPU 3/전력 4·완료 기한 접수+75분): 작업량 40%에서 Server A 장애. 이전(10분)은 시작+70분, 복구(20분)는 +80분에 끝나므로 이전만 기한을 지킵니다.
미션 B(싱가포르 GPU 7/전력 7): 정상 서버 GPU가 6이라 전체 작업 이전은 불가능하고 장비 복구만 가능합니다.
결과는 기존 시간·하드웨어 엔진을 실제로 돌려 확인하며 완료 시각을 임의로 지정하지 않습니다.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chapter3b import Chapter3bProgress, STEPS3B, diagnosis_rows
from database import Database
from game import SCENARIOS
from server_resources import Allocation, ServerSlice
from session import GameSession
from story import StoryProgress, GUIDES3B
from story_slots import StorySlots
from tests.support import start_with_consent
from tests.test_chapter3 import (practice3, start_a, to_incident, finish_job, play_a_correctly, open_db, ledger_matches_center)
from tests.test_chapter3_recovery import free_with_two_customers

ROOT = Path(__file__).resolve().parent.parent


def practice3b(db=None, seed=5):
    return GameSession(db or Database(':memory:'), mode='story', start_chapter='3b', seed=seed)


def start_job(s, index=0):
    if index == 0:
        s.confirm_chapter3b_briefing()
    rid = s.story.chapter3b.request_ids[index]
    s.read_conversation(rid); s.selected_id = rid
    s.choose_plan('performance')
    return rid


def to_fault(s, rid, limit=12):
    run = s.runs[rid]
    for _ in range(limit):
        if s.hardware_servers(run):
            return run
        s.advance_time(10)
    raise AssertionError('장비 장애가 발생하지 않습니다.')


def fault_a(seed=5):
    s = practice3b(seed=seed)
    a = start_job(s)
    return s, a, to_fault(s, a)


def migrate_now(s, run):
    s.view_hardware_diagnosis(run.request['id'])
    options = s.migration_preview(run)['options']
    s.migrate(options[0], s.servers.allocations[run.playthrough_id])


def finish(s, rid, limit=30):
    run = s.runs[rid]
    for _ in range(limit):
        if run.state.phase == 'finished':
            return run
        s.advance_time(10)
    raise AssertionError('작업이 끝나지 않습니다.')


def mission_b(choice='repair'):
    s, a, run = fault_a()
    migrate_now(s, run)
    finish(s, a)
    b = s.story.chapter3b.request_ids[1]
    start_job(s, 1)
    runb = to_fault(s, b)
    return s, b, runb


class FaultAndMissionATests(unittest.TestCase):
    def test_fault_is_deterministic_and_stops_the_clock(self):
        seen = []
        for seed in (1, 5, 99):
            s = practice3b(seed=seed)
            a = start_job(s)
            begin = s.minute
            s.advance_time(60)                                              # 장애가 나면 남은 시간 진행은 멈춥니다.
            run = s.runs[a]
            seen.append((s.minute-begin, s.hardware_servers(run), run.state.work_done, s.servers.hardware['A'].state))
        self.assertEqual(len(set(seen)), 1, seen)
        self.assertEqual(seen[0], (30, ('A',), 30, 'FAULT'))

    def test_fault_happens_once_and_only_in_the_story_scenario(self):
        s, a, run = fault_a()
        s.view_hardware_diagnosis(a); s.begin_server_repair('A')
        for _ in range(12):
            s.advance_time(10)
        self.assertEqual(sum(e['kind'] == 'hardware_fault' for e in s.db.get_request_events(a)), 1)
        with self.assertRaises(ValueError):
            s.inject_server_fault('B')                                      # 교육 장애는 자동 발생만

    def test_a_has_a_real_migration_plan_on_healthy_servers(self):
        s, a, run = fault_a()
        preview = s.migration_preview(run)
        self.assertTrue(preview['allowed'])
        self.assertTrue(1 <= len(preview['options']) <= 3)
        for plan in preview['options']:
            self.assertNotIn('A', {p.server_id for p in plan})
            self.assertEqual((sum(p.gpu for p in plan), sum(p.power for p in plan)), (3, 4))
        d = s.view_hardware_diagnosis(a)
        self.assertEqual((d['server'], d['health'], d['migrate_possible'], d['normal_gpu']), ('A', 'FAULT', True, 6))
        self.assertEqual((d['slice_gpu'], d['slice_power'], d['need_gpu'], d['need_power']), (3, 4, 3, 4))

    def test_migration_takes_ten_minutes_and_repair_twenty_with_different_deadline_outcomes(self):
        s, a, run = fault_a()
        received, due = run.terms['received'], run.terms['due']
        self.assertEqual(due-received, 75)
        d = s.view_hardware_diagnosis(a)
        migrate_now(s, run)
        self.assertEqual(run.migration_left, 10)
        finish(s, a)
        self.assertEqual(run.terms['completed']-received, 70)
        self.assertEqual((run.terms['late_minutes'], run.state.succeeded), (0, True))
        record = s.story.chapter3b.records[str(a)]
        self.assertEqual(record['migrate_finish'], run.terms['completed'])        # 진단의 예상이 실제 결과와 일치
        self.assertTrue(d['migrate_on_time'] and d['repair_on_time'] is False)

        s2, a2, run2 = fault_a()
        s2.view_hardware_diagnosis(a2); s2.begin_server_repair('A')
        finish(s2, a2)
        self.assertEqual(run2.terms['completed']-run2.terms['received'], 80)
        self.assertEqual(run2.terms['late_minutes'], 5)
        self.assertEqual(s2.story.chapter3b.records[str(a2)]['repair_finish'], run2.terms['completed'])
        self.assertLess(run2.state.score, run.state.score)                         # 기한 지연 감점이 실제로 반영

    def test_migration_keeps_progress_mode_deadline_consent_and_total_usage(self):
        s, a, run = fault_a()
        before = (run.state.work_done, run.state.plan, run.terms['due'], run.state.gpu_used, run.state.power_used,
                  run.playthrough_id, deepcopy(run.conditions), list(run.proposals), s.center.gpu_used, s.center.power_used)
        migrate_now(s, run)
        after = (run.state.work_done, run.state.plan, run.terms['due'], run.state.gpu_used, run.state.power_used,
                 run.playthrough_id, run.conditions, run.proposals, s.center.gpu_used, s.center.power_used)
        self.assertEqual(before, after)
        self.assertTrue(s.plan_agreed(run, run.state.plan))                       # 고객 동의 조건 유지
        self.assertTrue(ledger_matches_center(s))
        self.assertEqual(len(run.server_allocations), 2)                           # 이전 이력 보존
        self.assertEqual(s.hardware_servers(run), ())

    def test_faulty_server_receives_no_new_allocation(self):
        s, a, run = fault_a()
        plan = s.servers.plan(2, 2)
        self.assertNotIn('A', {p.server_id for p in plan})
        with self.assertRaises(ValueError):
            s.servers.validate_plan((ServerSlice('A', (0, 1), 2),), 2, 2)
        self.assertEqual(s.servers.available(), (6, 6))                           # 정상 서버(B·C·D)만 가용량

    def test_migration_target_is_revalidated(self):
        s, a, run = fault_a()
        s.view_hardware_diagnosis(a)
        source = s.servers.allocations[run.playthrough_id]
        plan = s.migration_preview(run)['options'][0]
        s.servers.reserve(Allocation(10**6, plan))                                 # 다른 곳이 먼저 같은 슬롯을 차지함
        snapshot = (s.minute, run.migration_left, dict(s.servers.allocations), s.center.gpu_used)
        with self.assertRaises(ValueError):
            s.migrate(plan, source)
        self.assertEqual((s.minute, run.migration_left, s.center.gpu_used), (snapshot[0], snapshot[1], snapshot[3]))
        self.assertEqual(s.servers.allocations, snapshot[2])
        self.assertEqual(s.story.chapter3b.records[str(a)]['choices'], [])
        s.servers.release(10**6)
        s.migrate(plan, source)
        self.assertEqual(run.migration_left, 10)

    def test_migration_requires_customer_consent(self):
        s, a, run = fault_a()
        s.view_hardware_diagnosis(a)
        plan = s.migration_preview(run)['options'][0]
        with patch.object(GameSession, 'plan_agreed', return_value=False):
            with self.assertRaises(ValueError):
                s.migrate(plan, s.servers.allocations[run.playthrough_id])
        self.assertEqual(run.migration_left, 0)


class MissionBTests(unittest.TestCase):
    def test_b_migration_is_impossible_and_explains_why(self):
        s, b, run = mission_b()
        self.assertEqual(run.state.gpu_used, 7)
        preview = s.migration_preview(run)
        self.assertFalse(preview['allowed']); self.assertEqual(preview['options'], ())
        self.assertEqual(preview['reason'], '정상 서버의 가용 GPU는 6개입니다. 현재 작업은 GPU 7개가 필요하므로 전체 작업 이전이 불가능합니다.')
        d = s.view_hardware_diagnosis(b)
        self.assertFalse(d['migrate_possible'])
        self.assertEqual(d['advice'], 'Server A를 복구하면 기존 자원 배정을 유지한 채 작업을 재개할 수 있습니다.')
        rows = dict((n, v) for n, v, _ in diagnosis_rows(d))
        self.assertEqual((rows['작업 이전'], rows['작업 이전 예상']), ('불가능', '해당 없음'))
        self.assertIn('Server A · FAULT', rows['장애 서버'])

    def test_failed_migration_attempt_changes_nothing_and_repair_remains_possible(self):
        s, b, run = mission_b()
        s.view_hardware_diagnosis(b)
        before = (s.minute, dict(s.servers.allocations), s.center.gpu_used, dict(s.servers.hardware), run.migration_left,
                  list(run.server_allocations))
        for plan in (None, (), (ServerSlice('B', (0, 1, 2), 2),)):
            with self.assertRaises((ValueError, TypeError)):
                s.migrate(plan, s.servers.allocations[run.playthrough_id])
        self.assertEqual((s.minute, dict(s.servers.allocations), s.center.gpu_used, dict(s.servers.hardware), run.migration_left,
                          list(run.server_allocations)), before)
        s.begin_server_repair('A')                                                  # 다른 해결책은 계속 가능
        self.assertEqual(s.servers.hardware['A'].state, 'REPAIRING')

    def test_b_repair_keeps_allocation_and_progress_and_completes(self):
        s, b, run = mission_b()
        s.view_hardware_diagnosis(b)
        allocation, work, minute = s.servers.allocations[run.playthrough_id], run.state.work_done, s.minute
        s.begin_server_repair('A')
        self.assertEqual((s.minute, s.servers.hardware['A'].repair_left), (minute, 20))   # 버튼만으로 시간이 흐르지 않음
        s.advance_time(10)
        self.assertEqual((s.servers.hardware['A'].state, s.servers.hardware['A'].repair_left, run.state.work_done), ('REPAIRING', 10, work))
        s.advance_time(10)
        self.assertEqual(s.servers.hardware['A'].state, 'HEALTHY')
        self.assertEqual((run.state.work_done, s.servers.allocations[run.playthrough_id]), (work, allocation))
        finish(s, b)
        self.assertTrue(run.state.succeeded)
        self.assertEqual(run.terms['late_minutes'], 0)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))
        self.assertEqual(s.servers.allocations, {})
        self.assertTrue(s.story.chapter3b.completed)

    def test_second_server_fault_mission_opens_only_after_first_ends(self):
        s, a, run = fault_a()
        self.assertEqual(len(s.story.chapter3b.request_ids), 1)
        migrate_now(s, run)
        s.advance_time(10)
        self.assertEqual(len(s.story.chapter3b.request_ids), 1)
        finish(s, a)
        self.assertEqual(len(s.story.chapter3b.request_ids), 2)
        self.assertEqual(s.servers.hardware['A'].state, 'HEALTHY')                  # 다음 미션을 위해 정비 완료
        self.assertEqual(s.runs[s.story.chapter3b.request_ids[1]].mission['country'], '싱가포르')


class StepAndFeedbackTests(unittest.TestCase):
    def test_steps_advance_only_with_real_actions(self):
        s = practice3b()
        c = s.story.chapter3b
        self.assertEqual(c.step, 'briefing')
        a = c.request_ids[0]
        s.read_conversation(a); s.selected_id = a
        s.choose_plan('performance')
        self.assertEqual(c.step, 'briefing')                                        # 브리핑 확인 전에는 앞서가지 않음
        s.confirm_chapter3b_briefing()
        self.assertEqual(c.step, 'a_fault')
        run = to_fault(s, a)
        self.assertEqual(c.step, 'a_diagnose')                                      # 장애 발생 ≠ 진단
        with self.assertRaises(ValueError):
            s.begin_server_repair('A')
        with self.assertRaises(ValueError):
            s.migrate(s.migration_preview(run)['options'][0], s.servers.allocations[run.playthrough_id])
        self.assertTrue(s.chapter3b_locked(run))
        self.assertEqual((s.servers.hardware['A'].state, run.migration_left), ('FAULT', 0))
        s.view_hardware_diagnosis(a)
        self.assertEqual(c.step, 'a_respond')                                       # 진단 ≠ 대응
        self.assertFalse(s.chapter3b_locked(run))
        s.begin_server_repair('A')
        self.assertEqual(c.step, 'a_finish')
        finish(s, a)
        self.assertEqual(c.step, 'b_start')

    def test_briefing_and_guides_do_not_give_the_answer(self):
        s = practice3b()
        s.confirm_chapter3b_briefing()
        s.mark_story_dialogue(s.story.dialogue_event)
        self.assertEqual(s.story.chapter3b.step, 'a_start')
        self.assertEqual(s.center.gpu_used, 0)
        for key, (_, lines) in GUIDES3B.items():
            for line in lines:
                self.assertNotIn('유리', line.text, key); self.assertNotIn('정답은', line.text.replace('정답은 알려', ''), key)
        text = GUIDES3B['a_diagnose'][1][0].text
        for number in '①②③④':
            self.assertEqual(sum(row.startswith(number) for row in text.split('\n')), 1)

    def test_cards_describe_only_what_the_player_chose(self):
        s, a, run = fault_a()
        s.view_hardware_diagnosis(a)
        self.assertIsNone(s.chapter3b_card(a))                                      # 선택 전에는 결과 카드가 없음
        self.assertIsNone(s.chapter3b_pending_feedback())
        migrate_now(s, run)
        card = s.chapter3b_card(a)
        self.assertEqual((card['kind'], card['title']), ('migrate', '작업 이전 확정'))
        text = ' '.join(v for _, v in card['rows'])+card['mentor']
        self.assertNotIn('복구 시작', text)
        self.assertIn('준비 10분', text)
        key = s.chapter3b_pending_feedback()
        s.mark_chapter3b_feedback_seen(key)
        self.assertIsNone(s.chapter3b_pending_feedback())
        with self.assertRaises(ValueError):
            s.mark_chapter3b_feedback_seen(key)
        self.assertEqual(s.chapter3b_card(a)['kind'], 'migrate')                    # 닫았다 다시 열 수 있음

    def test_b_repair_card_mentions_infeasible_migration_only_after_diagnosis(self):
        s, b, run = mission_b()
        s.view_hardware_diagnosis(b); s.begin_server_repair('A')
        card = s.chapter3b_card(b)
        rows = dict(card['rows'])
        self.assertEqual((card['title'], rows['선택 대응']), ('장비 복구 시작', '장비 복구'))
        self.assertIn('불가능', rows['작업 이전'])
        self.assertIn('GPU', card['mentor'])
        keys = []
        while s.chapter3b_pending_feedback() is not None:
            keys.append(s.chapter3b_pending_feedback()); s.mark_chapter3b_feedback_seen(keys[-1])
        self.assertIn(f'{b}:repair:1', keys)


class OtherCustomersTests(unittest.TestCase):
    def test_fault_on_one_server_does_not_stop_jobs_elsewhere(self):
        s, first, second = free_with_two_customers()
        s.select(first); start_with_consent(s, 'economy')
        s.select(second); start_with_consent(s, 'performance')
        run1, run2 = s.runs[first], s.runs[second]
        servers1 = {p.server_id for p in s.servers.allocations[run1.playthrough_id].slices}
        servers2 = {p.server_id for p in s.servers.allocations[run2.playthrough_id].slices}
        target = sorted(servers1 - servers2)[0]
        s.inject_server_fault(target)
        work1, work2 = run1.state.work_done, run2.state.work_done
        s.advance_time(10)
        self.assertEqual(run1.state.work_done, work1)                               # 영향받은 작업만 중단
        self.assertGreater(run2.state.work_done, work2)                             # 다른 고객은 정상 진행
        self.assertTrue(ledger_matches_center(s))
        self.assertIsNone(s.story)                                                  # 자유 운영의 수동 장애/복구 기능 유지
        s.begin_server_repair(target)
        self.assertEqual(s.servers.hardware[target].state, 'REPAIRING')


class PersistenceAndCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 's.db'

    def reopen(self, s):
        s.close()
        return GameSession(open_db(self, self.path), mode='story')

    def test_resume_during_repair_and_migration_keeps_records(self):
        s = practice3b(open_db(self, self.path))
        a = start_job(s); run = to_fault(s, a)
        s.view_hardware_diagnosis(a); s.begin_server_repair('A'); s.advance_time(10)
        work, records = run.state.work_done, deepcopy(s.story.chapter3b.records)
        s = self.reopen(s)
        run = s.runs[a]
        self.assertEqual((s.servers.hardware['A'].state, s.servers.hardware['A'].repair_left, run.state.work_done), ('REPAIRING', 10, work))
        self.assertEqual((s.story.chapter3b.records, s.story.chapter3b.diagnosed), (records, [a]))
        self.assertTrue(ledger_matches_center(s))
        s.advance_time(10); finish(s, a)
        s = self.reopen(s)
        self.assertEqual(s.story.chapter3b.records[str(a)]['choices'], ['repair'])
        self.assertEqual(len(s.story.chapter3b.request_ids), 2)

    def test_save_failure_rolls_back_choice_time_and_ledger(self):
        s, a, run = fault_a()
        s.view_hardware_diagnosis(a)
        snapshot = (s.minute, dict(s.servers.hardware), dict(s.servers.allocations), s.center.gpu_used,
                    deepcopy(s.story.chapter3b.records), vars(run.state).copy(), run.migration_left, list(run.server_allocations))
        source = s.servers.allocations[run.playthrough_id]
        plan = s.migration_preview(run)['options'][0]
        with patch.object(Database, 'save_runtime', side_effect=RuntimeError('disk full')):
            for action in (lambda: s.migrate(plan, source), lambda: s.begin_server_repair('A'), lambda: s.advance_time(10)):
                with self.assertRaises(RuntimeError):
                    action()
        self.assertEqual((s.minute, dict(s.servers.hardware), dict(s.servers.allocations), s.center.gpu_used,
                          s.story.chapter3b.records, vars(run.state), run.migration_left, list(run.server_allocations)), snapshot)
        s.begin_server_repair('A')                                                  # 실패 뒤 정상 재시도
        self.assertEqual(s.servers.hardware['A'].state, 'REPAIRING')

    def test_chapter3a_slot_unlocks_3b_and_keeps_its_records(self):
        s = practice3(open_db(self, self.path))
        a = start_a(s); play_a_correctly(s, a)
        b = s.story.chapter3.request_ids[1]
        s.read_conversation(b); s.selected_id = b
        start_with_consent(s, 'performance')
        to_incident(s, b); s.view_network_diagnosis(b); s.respond('compress'); finish_job(s, b)
        before = deepcopy(s.chapter3_result()['summary']['table'])
        records = deepcopy(s.story.chapter3.records)
        self.assertEqual(s.chapter3b_unlock_reason(), '')
        rid = s.start_chapter3b()
        self.assertEqual((s.story.chapter3b.request_ids, s.runs[rid].state.scenario), ([rid], 'ch3b_jp'))
        self.assertEqual((s.chapter3_result()['summary']['table'], s.story.chapter3.records), (before, records))
        with self.assertRaises(ValueError):
            s.start_chapter3b()
        s = self.reopen(s)
        self.assertEqual((s.story.chapter3.completed, s.story.chapter3b.request_ids), (True, [rid]))
        self.assertEqual(s.chapter3_result()['summary']['table'], before)

    def test_failed_or_unfinished_3a_does_not_unlock_3b(self):
        s = practice3()
        self.assertIn('완료', s.chapter3b_unlock_reason())
        with self.assertRaises(ValueError):
            s.start_chapter3b()
        a = start_a(s); to_incident(s, a)
        s.view_network_diagnosis(a)
        for _ in range(3):
            s.respond('compress')
        s.report_failure()
        b = s.story.chapter3.request_ids[1]
        s.read_conversation(b); s.selected_id = b
        start_with_consent(s, 'performance')
        to_incident(s, b); s.view_network_diagnosis(b); s.respond('compress'); finish_job(s, b)
        self.assertEqual(s.chapter3_result()['mission'], 'failed')
        self.assertIn('성공', s.chapter3b_unlock_reason())
        runs = len(s.runs)
        with self.assertRaises(ValueError):
            s.start_chapter3b()
        self.assertEqual((len(s.runs), s.story.chapter3b), (runs, None))

    def test_practice_slot_has_no_false_history_and_old_payloads_load(self):
        s = practice3b()
        st = s.story
        self.assertTrue(st.practice and st.practice_chapter == '3b' and st.chapter3b_active)
        self.assertEqual((st.chapter2, st.chapter3, st.chapter_completed, st.completed_steps), (None, None, False, []))
        self.assertEqual(st.chapter_label, 'Chapter 3b')
        with self.assertRaises(ValueError):
            s.start_chapter2()
        legacy = StoryProgress.from_payload({'practice': True}, None, False)
        self.assertNotIn('chapter3b', legacy.payload())
        with self.assertRaises(ValueError):
            StoryProgress(chapter3b=Chapter3bProgress([1]))
        with self.assertRaises(ValueError):
            Chapter3bProgress([1], completed_steps=list(STEPS3B[:8]))
        ok = StoryProgress(practice=True, practice_chapter='3b', chapter3b=Chapter3bProgress([1]))
        self.assertEqual(StoryProgress(**ok.payload()).chapter3b.request_ids, [1])

    def test_slots_resume_and_new_attempt_use_separate_files(self):
        slots = StorySlots(self.folder.name)
        first = slots.reserve_new()
        s = practice3b(open_db(self, first))
        a = start_job(s); to_fault(s, a)
        s.close()
        self.assertIn('Chapter 3b 연습 진행 중', slots.describe(first))
        self.assertEqual(slots.chapter3b_in_progress(), [first])
        second = slots.reserve_new()
        self.assertNotEqual(first, second)
        t = practice3b(open_db(self, second), seed=7)
        self.assertEqual(t.story.chapter3b.records, {})
        t.close()
        s = GameSession(open_db(self, first), mode='story')
        self.assertEqual(s.story.chapter3b.records[str(a)]['server'], 'A')
        self.assertEqual(s.servers.hardware['A'].state, 'FAULT')
        self.assertEqual(s.story.chapter_label, 'Chapter 3b')


class ResultTests(unittest.TestCase):
    def play(self, a_choice, b_choice='repair'):
        s, a, run = fault_a()
        if a_choice == 'migrate':
            migrate_now(s, run)
        else:
            s.view_hardware_diagnosis(a); s.begin_server_repair('A')
        finish(s, a)
        b = s.story.chapter3b.request_ids[1]
        start_job(s, 1)
        to_fault(s, b)
        s.view_hardware_diagnosis(b); s.begin_server_repair('A')
        finish(s, b)
        return s, a, b

    def test_success_result_matches_real_scores_and_times(self):
        s, a, b = self.play('migrate')
        result = s.chapter3b_result()
        self.assertEqual(result['mission'], 'success')
        table = result['summary']['table']
        self.assertEqual(table[0], ('A', 'Server A 장애', '작업 이전', '기한 내 완료', '10분', f'{s.runs[a].state.score}점'))
        self.assertEqual(table[1], ('B', 'Server A 장애', '장비 복구', '기한 내 완료', '20분', f'{s.runs[b].state.score}점'))
        self.assertEqual(result['summary']['columns'], ('미션', '장애', '선택 대응', '결과', '중단', '점수'))
        self.assertLessEqual(len(result['mentor']), 3)
        self.assertTrue(result['released'])
        self.assertIn('이전', result['mentor'][0]); self.assertIn('복구', result['mentor'][1])
        self.assertIn('Server A', result['summary']['detail_text'])

    def test_late_completion_is_reported_as_failed_with_the_real_reason(self):
        s, a, b = self.play('repair')
        result = s.chapter3b_result()
        self.assertEqual(result['mission'], 'failed')
        row = result['summary']['table'][0]
        self.assertEqual((row[2], row[3]), ('장비 복구', '기한 초과 완료 (초과 5분)'))
        self.assertEqual(result['summary']['ok'], 1)
        self.assertIn('이전했다면', result['mentor'][0])                           # 선택 시점의 예상(이전 70분)에 근거
        self.assertTrue(s.runs[a].state.succeeded)                                  # 작업 자체를 성공으로 바꾸지 않음
        self.assertTrue(s.chapter3b_retry_available)

    def test_job_failure_shows_failed_card_and_does_not_open_next_mission(self):
        s, a, run = fault_a()
        s.view_hardware_diagnosis(a)
        s.report_failure()
        card = s.chapter3b_card(a)
        self.assertEqual((card['kind'], card['title'], card['can_retry']), ('failed', 'SERVER RECOVERY FAILED', True))
        self.assertEqual(dict(card['rows'])['시도한 대응'], '대응 없음')
        self.assertTrue(s.chapter3b_retry_available)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))

    def test_unfinished_hardware_fault_is_not_failed_by_prediction(self):
        s, a, run = fault_a()
        for _ in range(12):                                                         # 아무 대응 없이 시간이 흘러도 60분 규칙을 적용하지 않음
            s.advance_time(10)
        self.assertNotEqual(run.state.phase, 'finished')
        self.assertEqual(len(s.story.chapter3b.request_ids), 1)
        self.assertFalse(s.story.chapter3b.completed)
        self.assertTrue(s.chapter3b_locked(run))

    def test_dialog_and_ui_sources(self):
        main = (ROOT / 'main.py').read_text(encoding='utf-8')
        for text in ("'hwdiag','장비 진단'", "'hwrepair','장비 복구 · 20분'", "'후속 처리로 돌아가기'", 'chapter3b_locked', "mode == 'chapter3b'"):
            self.assertIn(text, main)
        self.assertIn('scripted', (ROOT / 'server_console.py').read_text(encoding='utf-8'))
        self.assertIn('class HardwareDiagnosisDialog', (ROOT / 'network_dialog.py').read_text(encoding='utf-8'))


class ScenarioDataTests(unittest.TestCase):
    def test_scenarios_and_existing_rules(self):
        jp, sg = SCENARIOS['ch3b_jp'], SCENARIOS['ch3b_sg']
        self.assertEqual((jp['plans']['performance']['gpu'], jp['plans']['performance']['power']), (3, 4))
        self.assertEqual((sg['plans']['performance']['gpu'], sg['plans']['performance']['power']), (7, 7))
        self.assertEqual((jp['window'][2], jp['hardware_fault']['at']), (75, .4))
        self.assertNotIn('incident', jp)
        for name in ('ch2_jp', 'ch2_us', 'ch2_us_v2', 'ch3_path', 'ch3_bw'):
            self.assertNotIn('hardware_fault', SCENARIOS[name])


if __name__ == '__main__':
    unittest.main()
