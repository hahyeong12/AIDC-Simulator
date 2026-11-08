"""v0.9-2a-1: Chapter 2(여러 고객의 요청과 서버 배정). Tk 창을 만들지 않는 규칙/저장 검증.

일본(GPU 4/전력 5·기한 50분·최종 배정 80분)과 미국(고성능 6/6·절약형 4/3·기한 140분)의 원래 고성능 요청은
전력 합계 11로 동시에 실행할 수 없습니다. 결과는 아래 테스트가 실제 엔진을 돌려 확인하며 하드코딩하지 않습니다.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chapter2 import Chapter2Progress, STEPS2, CHAPTER2_COUNTRIES, CHAPTER2_SCENARIOS
from database import Database
from game import SCENARIOS, GameState
from session import GameSession
from story import StoryProgress
from story_slots import StorySlots
from tests.test_story import gameplay
from tests.test_story_patch import prepare, finish


def after_chapter1(db, seed=9):
    s = GameSession(db, mode='story', seed=seed)
    prepare(s); finish(s)
    assert s.story.chapter_completed
    return s


def practice(db=None, seed=9):
    db = db or Database(':memory:')
    s = GameSession(db, mode='story', start_chapter=2, seed=seed)
    return s


def ready():
    """브리핑까지 확인한 새 Chapter 2 연습."""
    s = practice()
    s.confirm_chapter2_briefing()
    jp, us = s.story.chapter2.request_ids
    return s, jp, us


def start(s, rid, mode, plan=None):
    s.selected_id = rid
    s.choose_plan(mode, server_plan=plan)


def finish_all(s, step=10, limit=60):
    for _ in range(limit):
        if s.story.chapter2.completed:
            return
        s.advance_time(step)
    raise AssertionError('Chapter 2가 끝나지 않습니다.')


def summary(s, rid):
    run = s.runs[rid]
    t = run.terms
    return {'status': run.request['status'], 'score': run.state.score, 'mode': run.state.plan,
            'started': t.get('started'), 'completed': t.get('completed'), 'expired': bool(t.get('expired')),
            'late': t.get('late_minutes')}


def ledger_matches_center(s):
    return (sum(a.gpu for a in s.servers.allocations.values()) == s.center.gpu_used
            and sum(a.power for a in s.servers.allocations.values()) == s.center.power_used)


class ScenarioDataTests(unittest.TestCase):
    def test_server_capacity_and_free_mode_rules_are_unchanged(self):
        from server_resources import SERVERS
        self.assertEqual([(s.key, s.gpu, s.power) for s in SERVERS], [('A', 4, 4), ('B', 3, 2), ('C', 2, 3), ('D', 1, 1)])
        self.assertEqual(GameState(country='일본').plans['performance']['gpu'], 3)
        self.assertEqual(GameState(country='일본').work_total, 60)
        self.assertEqual(GameState(country='미국').plans['performance']['power'], 6)
        self.assertIsNone(GameState().scenario)

    def test_original_requests_exceed_power_even_though_gpu_fits(self):
        jp, us = (SCENARIOS[CHAPTER2_SCENARIOS[c]]['plans']['performance'] for c in CHAPTER2_COUNTRIES)
        self.assertLessEqual(jp['gpu']+us['gpu'], 10)
        self.assertGreater(jp['power']+us['power'], 10)

    def test_customer_rules_follow_existing_country_types(self):
        s, jp, us = ready()
        self.assertEqual(s.runs[jp].conditions['allowed_modes'], ['performance'])
        self.assertEqual(s.runs[us].conditions['allowed_modes'], ['performance', 'economy'])
        self.assertEqual(s.runs[jp].conditions['type'], 'fixed')
        self.assertEqual(s.runs[us].conditions['type'], 'flexible')
        self.assertEqual({r.state.scenario for r in s.runs.values()}, {'ch2_jp', 'ch2_us'})


class StartTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)

    def test_cannot_start_before_chapter_one_is_completed(self):
        s = GameSession(self.db, mode='story', seed=9)
        before = deepcopy(s.story.payload()), gameplay(s), '\n'.join(self.db.conn.iterdump())
        with self.assertRaises(ValueError):
            s.start_chapter2()
        self.assertEqual((s.story.payload(), gameplay(s), '\n'.join(self.db.conn.iterdump())), before)

    def test_free_mode_has_no_chapter_two_and_ignores_scenarios(self):
        s = GameSession(self.db, seed=9)
        with self.assertRaises(ValueError):
            s.start_chapter2()
        self.assertEqual(s.allocation_impacts(s.current, s.servers.plan(1, 1)), [])
        self.assertEqual(s.chapter2_briefing_lines(s.current), [])
        self.assertTrue(all(r.state.scenario is None for r in s.runs.values()))
        with self.assertRaises(ValueError):
            GameSession(Database(':memory:'), start_chapter=2)   # 자유 운영에는 연습 시작 없음

    def test_chapter_one_save_format_has_no_new_keys_and_loads(self):
        s = after_chapter1(self.db)
        self.assertNotIn('chapter2', s.story.payload())
        self.assertNotIn('practice', s.story.payload())
        again = GameSession(self.db, mode='story')
        self.assertIsNone(again.story.chapter2)
        self.assertTrue(again.story.chapter_completed)

    def test_start_after_chapter_one_keeps_record_and_adds_only_scenario_requests(self):
        s = after_chapter1(self.db)
        first = s.runs[s.story.request_id]
        chapter1 = (first.state.score, first.terms.copy(), s.story.completed_steps[:], s.story.first_work_completed,
                    self.db.get_recent_records(10), first.state.scenario)
        ids = s.start_chapter2()
        self.assertEqual(len(s.runs), 3)
        self.assertEqual([s.runs[i].mission['country'] for i in ids], list(CHAPTER2_COUNTRIES))
        self.assertEqual((first.state.score, first.terms, s.story.completed_steps, s.story.first_work_completed,
                          self.db.get_recent_records(10), first.state.scenario), chapter1)
        self.assertTrue(s.story.chapter_completed and s.story.chapter2_active and not s.story.practice)
        self.assertEqual((s.center.gpu_used, s.servers.allocations), (0, {}))
        with self.assertRaises(ValueError):
            s.start_chapter2()

    def test_start_failure_rolls_back_requests_and_progress(self):
        s = after_chapter1(self.db)
        before = deepcopy(s.story.payload()), gameplay(s), len(self.db.get_requests())
        with patch.object(self.db, 'save_simulation', side_effect=OSError('저장 실패')):
            with self.assertRaises(OSError):
                s.start_chapter2()
        self.assertIsNone(s.story.chapter2)
        self.assertEqual((s.story.payload(), gameplay(s), len(self.db.get_requests())), before)

    def test_story_never_schedules_random_arrivals_or_incidents(self):
        s = practice(self.db)
        for _ in range(8):
            s.advance_time(60)
        self.assertEqual(len(s.runs), 2)
        self.assertTrue(all(r.state.incident_at is None for r in s.runs.values()))


class PracticeSlotTests(unittest.TestCase):
    def test_practice_starts_from_a_clean_initial_state_without_fake_chapter_one(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = practice(db)
        story = s.story
        self.assertTrue(story.practice and story.chapter2_active)
        self.assertFalse(story.chapter_completed or story.tutorial_completed or story.first_work_completed)
        self.assertEqual((story.completed_steps, story.request_id, story.mission_status), ([], None, 'pending'))
        self.assertEqual(len(s.runs), 2)
        self.assertEqual([r.mission['country'] for r in s.runs.values()], list(CHAPTER2_COUNTRIES))
        self.assertEqual((s.minute, s.time_label), (540, 'D1 09:00'))
        self.assertEqual((s.center.gpu_used, s.center.power_used, s.servers.allocations), (0, 0, {}))
        self.assertEqual(db.get_recent_records(10), [])
        self.assertTrue(all(r.state.score is None for r in s.runs.values()))
        with self.assertRaises(ValueError):
            s.chapter_result()
        self.assertEqual(story.ui_step, 'c2_briefing')

    def test_practice_cannot_open_an_existing_save_or_story_slot_with_progress(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        after_chapter1(db)
        with self.assertRaises(ValueError):
            GameSession(db, mode='story', start_chapter=2)

    def test_practice_payload_round_trips_and_rejects_fake_chapter_one_records(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = practice(db)
        s.confirm_chapter2_briefing()
        again = GameSession(db, mode='story')
        self.assertTrue(again.story.practice)
        self.assertEqual(again.story.payload(), s.story.payload())
        good = deepcopy(db.get_simulation())
        for bad in ({'chapter_completed': True}, {'completed_steps': ['arrival']}, {'request_id': 1}, {'tutorial_completed': True}):
            with self.subTest(bad=bad):
                saved = deepcopy(good)
                saved['story'].update(bad)
                db.save_simulation(saved)
                with self.assertRaises(ValueError):
                    GameSession(db, mode='story')
                db.save_simulation(good)

    def test_two_practice_slots_and_an_old_completed_slot_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory)/'old.db'
            db = Database(old)
            s = after_chapter1(db); s.start_chapter2()
            s.confirm_chapter2_briefing()
            jp, us = s.story.chapter2.request_ids
            start(s, jp, 'performance'); start(s, us, 'economy')
            finish_all(s)
            old_result = s.chapter2_result()
            s.close()
            before = Path(old).read_bytes()
            slots = []
            for name in ('a.db', 'b.db'):
                path = Path(directory)/name
                fresh = Database(path)
                p = GameSession(fresh, mode='story', start_chapter=2, seed=9)
                self.assertEqual((p.minute, p.center.gpu_used, len(p.runs)), (540, 0, 2))
                self.assertFalse(p.story.chapter_completed)
                slots.append((path, fresh, p))
            # 한 연습 슬롯의 진행은 다른 슬롯과 기존 슬롯에 영향을 주지 않습니다.
            _, _, a = slots[0]
            a.confirm_chapter2_briefing()
            start(a, a.story.chapter2.request_ids[0], 'performance')
            a.advance_time(30)
            _, _, b = slots[1]
            self.assertEqual((b.minute, b.center.gpu_used, b.story.chapter2.completed_steps), (540, 0, []))
            for _, fresh, p in slots:
                p.close()
            self.assertEqual(Path(old).read_bytes(), before)
            again = GameSession(Database(old), mode='story')
            self.assertEqual(again.chapter2_result()['jobs'][0]['score'], old_result['jobs'][0]['score'])
            self.assertTrue(again.story.chapter_completed and not again.story.practice)
            again.close()

    def test_slot_description_is_read_only_and_distinguishes_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            slots = StorySlots(directory)
            p1, p2, p3, p4 = (slots.reserve_new() for _ in range(4))
            db = Database(p1); full = after_chapter1(db); full.close()
            db = Database(p2); after = after_chapter1(db); after.start_chapter2(); after.close()
            db = Database(p3); GameSession(db, mode='story', start_chapter=2, seed=9).close()
            db = Database(p4); q = GameSession(db, mode='story', start_chapter=2, seed=9)
            q.confirm_chapter2_briefing()
            jp, us = q.story.chapter2.request_ids
            start(q, jp, 'performance'); start(q, us, 'economy'); finish_all(q); q.close()
            snapshot = {p: Path(p).read_bytes() for p in (p1, p2, p3, p4)}
            self.assertEqual(slots.describe(p1), ' · Chapter 1 완료')
            self.assertEqual(slots.describe(p2), ' · Chapter 2 진행 중')
            self.assertEqual(slots.describe(p3), ' · Chapter 2 연습 진행 중')
            self.assertEqual(slots.describe(p4), ' · Chapter 2 연습 완료')
            self.assertEqual(slots.describe(Path(directory)/'missing.db'), '')
            self.assertEqual({p: Path(p).read_bytes() for p in snapshot}, snapshot)


class CompetitionTests(unittest.TestCase):
    """A~E: 서로 다른 합리적 선택이 실제 엔진에서 서로 다른 결과를 낳는지 검증합니다."""

    def test_A_original_requests_cannot_start_together_and_briefing_says_so(self):
        s, jp, us = ready()
        lines = s.chapter2_briefing_lines(s.runs[us])
        self.assertTrue(any('동시 실행' in line and '불가' in line for line in lines))
        start(s, jp, 'performance')
        before = (gameplay(s), '\n'.join(s.db.conn.iterdump()))
        with self.assertRaises(ValueError) as caught:
            start(s, us, 'performance')
        self.assertIn('전력', str(caught.exception))
        self.assertEqual((gameplay(s), '\n'.join(s.db.conn.iterdump())), before)  # 실패해도 상태가 꼬이지 않음
        self.assertIsNone(s.runs[us].playthrough_id)
        self.assertTrue(ledger_matches_center(s))

    def test_B_first_assignment_changes_the_other_customers_options(self):
        # 미국 고성능을 먼저 시작하면 일본의 고성능 요청은 실행할 수 없습니다.
        s, jp, us = ready()
        self.assertTrue(s.allocation_preview(s.runs[jp], 'performance')['allowed'])
        start(s, us, 'performance')
        self.assertFalse(s.allocation_preview(s.runs[jp], 'performance')['allowed'])
        # 일본을 먼저 시작하면 미국 고성능은 막히지만 고객이 허용한 절약형은 가능합니다.
        s, jp, us = ready()
        start(s, jp, 'performance')
        self.assertFalse(s.allocation_preview(s.runs[us], 'performance')['allowed'])
        self.assertTrue(s.allocation_preview(s.runs[us], 'economy')['allowed'])
        # 미국 절약형을 먼저 시작해도 일본은 시작할 수 있습니다.
        s, jp, us = ready()
        start(s, us, 'economy')
        self.assertTrue(s.allocation_preview(s.runs[jp], 'performance')['allowed'])

    def test_B_server_placement_matters_for_the_displayed_plans(self):
        s, jp, us = ready()
        results = []
        for parts in s.allocation_options(s.runs[jp], 'performance')['options']:
            text = ' '.join(s.allocation_impacts(s.runs[jp], parts))
            results.append(('절약형 모드 GPU 4/전력 3 배정 불가' in text))
        self.assertIn(True, results)    # 어떤 배정안은 미국 절약형 동시 실행을 막고
        self.assertIn(False, results)   # 어떤 배정안은 막지 않습니다.
        # 막는다고 표시한 안을 실제로 선택하면 실제 엔진도 미국 절약형을 차단합니다.
        blocking = next(p for p, flag in zip(s.allocation_options(s.runs[jp], 'performance')['options'], results) if flag)
        start(s, jp, 'performance', plan=blocking)
        self.assertFalse(s.allocation_preview(s.runs[us], 'economy')['allowed'])

    def test_C_order_and_mode_change_deadline_score_and_outcome(self):
        outcomes = {}
        # 일본과 미국 절약형을 동시에 시작
        s, jp, us = ready(); start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
        outcomes['eco'] = (summary(s, jp), summary(s, us))
        # 일본 완료 시각(40분)에 맞춰 미국 고성능 시작
        s, jp, us = ready(); start(s, jp, 'performance'); s.advance_time(30); s.advance_time(10)
        start(s, us, 'performance'); finish_all(s)
        outcomes['exact'] = (summary(s, jp), summary(s, us))
        # 같은 순서지만 +60분으로 건너뛰어 시작이 늦어짐
        s, jp, us = ready(); start(s, jp, 'performance'); s.advance_time(60)
        start(s, us, 'performance'); finish_all(s)
        outcomes['overshoot'] = (summary(s, jp), summary(s, us))
        # 미국 고성능을 먼저 시작
        s, jp, us = ready(); start(s, us, 'performance'); finish_all(s)
        outcomes['us_first'] = (summary(s, jp), summary(s, us))
        self.assertEqual(len({repr(v) for v in outcomes.values()}), 4)
        # 정확히 맞춘 순차 실행이 기한을 모두 지키며 가장 높은 미국 점수를 받습니다.
        exact_us = outcomes['exact'][1]
        self.assertEqual((exact_us['late'], exact_us['mode']), (0, 'performance'))
        self.assertGreater(exact_us['score'], outcomes['eco'][1]['score'])
        self.assertGreater(outcomes['eco'][1]['score'], outcomes['overshoot'][1]['score'])
        # 절약형은 기한(150분)에 딱 맞지만 고성능보다 낮은 보너스 점수를 받습니다.
        self.assertEqual(outcomes['eco'][1]['late'], 0)
        # 시작을 놓친 순차 실행은 기한을 넘깁니다.
        self.assertGreater(outcomes['overshoot'][1]['late'], 0)
        # 미국을 먼저 시작하면 일본은 최종 배정 기한 안에 시작하지 못합니다.
        self.assertTrue(outcomes['us_first'][0]['expired'])
        self.assertIsNone(outcomes['us_first'][0]['started'])

    def test_D_good_judgement_completes_both_jobs_on_time(self):
        s, jp, us = ready()
        for rid in (jp, us):
            s.read_conversation(rid)
        start(s, jp, 'performance')
        while s.runs[jp].state.phase != 'finished':
            s.advance_time(10)
        start(s, us, 'performance')
        finish_all(s)
        result = s.chapter2_result()
        self.assertTrue(all(j['succeeded'] and j['on_time'] is True for j in result['jobs']))
        self.assertFalse(result['concurrent'])
        self.assertEqual(s.servers.allocations, {})
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))

    def test_D_concurrent_economy_path_also_completes_on_time_with_a_lower_score(self):
        s, jp, us = ready(); start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
        result = s.chapter2_result()
        self.assertTrue(result['concurrent'])
        jp_job, us_job = result['jobs']
        self.assertEqual((jp_job['outcome'], us_job['outcome']), ('정상 완료', '정상 완료'))
        self.assertIs(us_job['on_time'], True)
        self.assertEqual(us_job['penalty'], 0)
        self.assertEqual(result['mission'], 'success')
        self.assertLess(us_job['score'], jp_job['score'])   # 절약형 보너스(5)가 고성능(15)보다 낮음

    def test_E_unfavourable_decisions_are_handled_without_corrupting_state(self):
        # 1) 미국 고성능 선행 → 일본 미처리 만료
        s, jp, us = ready(); start(s, us, 'performance')
        with self.assertRaises(ValueError):
            start(s, jp, 'performance')
        finish_all(s)
        self.assertEqual(s.runs[jp].request['status'], 'rejected')
        self.assertTrue(s.runs[jp].terms['expired'])
        self.assertEqual(s.chapter2_result()['jobs'][0]['outcome'], '기한 만료 · 미처리')
        self.assertTrue(ledger_matches_center(s)); self.assertEqual(s.servers.allocations, {})
        # 2) 둘 다 기다리다 늦게 시작 → 감점되지만 정상 처리
        s, jp, us = ready()
        for rid in (jp, us):
            s.selected_id = rid; s.wait_request()
        s.advance_time(30)
        start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
        self.assertTrue(all(s.runs[r].terms['penalty'] > 0 for r in (jp, us)))
        self.assertEqual(s.chapter2_result()['jobs'][0]['wait_choices'], 1)
        # 3) 미국 거절 → 일본만 처리
        s, jp, us = ready(); start(s, jp, 'performance')
        s.selected_id = us; s.reject_request('현재 전력 공급 여유 부족'); finish_all(s)
        self.assertEqual([j['outcome'] for j in s.chapter2_result()['jobs']], ['정상 완료', '거절'])
        # 4) 전부 대기하다 최종 배정 기한까지 방치 → 둘 다 미처리로 종료, 시간이 더 흘러도 안정
        s, jp, us = ready()
        for rid in (jp, us):
            s.selected_id = rid; s.wait_request()
        finish_all(s, step=60)
        self.assertEqual(sorted(j['outcome'] for j in s.chapter2_result()['jobs']), ['기한 만료 · 미처리'] * 2)
        s.advance_time(60)
        self.assertTrue(s.story.chapter2.completed)

    def test_japan_cannot_be_forced_to_economy_and_customer_rejects_the_proposal(self):
        s, jp, us = ready()
        s.selected_id = jp
        with self.assertRaises(ValueError):
            s.choose_plan('economy')
        conditions = deepcopy(s.runs[jp].conditions)
        s.propose_alternative()
        self.assertFalse(s.review_alternative())          # 절약형은 기한(50분)을 넘기므로 고객이 거절
        self.assertEqual(s.runs[jp].proposals[-1]['status'], 'rejected')
        self.assertEqual(s.runs[jp].conditions, conditions)
        with self.assertRaises(ValueError):
            s.choose_plan('economy')
        self.assertIsNone(s.runs[jp].playthrough_id)

    def test_us_economy_needs_no_new_consent_but_costs_time(self):
        s, jp, us = ready()
        self.assertTrue(s.plan_agreed(s.runs[us], 'economy'))
        self.assertFalse(s.plan_agreed(s.runs[jp], 'economy'))
        run = s.runs[us]
        self.assertGreater(run.state.estimate_minutes('economy'), run.state.estimate_minutes('performance'))

    def test_briefing_lines_report_real_estimates_and_deadline_status(self):
        s, jp, us = ready()
        lines = s.chapter2_briefing_lines(s.runs[us])
        self.assertTrue(any('고성능' in l and '기한 내' in l for l in lines))
        self.assertTrue(any('절약형' in l and '150분' in l for l in lines))
        jp_lines = s.chapter2_briefing_lines(s.runs[jp])
        self.assertFalse(any('절약형' in l for l in jp_lines if '처리' in l))   # 동의 없는 모드는 제시하지 않음
        start(s, jp, 'performance')
        self.assertEqual(s.chapter2_briefing_lines(s.runs[jp]), [])
        self.assertTrue(any('절약형' in l for l in s.chapter2_briefing_lines(s.runs[us])))

    def test_impact_query_is_read_only(self):
        s, jp, us = ready()
        before = gameplay(s), '\n'.join(s.db.conn.iterdump())
        for rid in (jp, us):
            for key in ('performance', 'economy'):
                for parts in s.allocation_options(s.runs[rid], key)['options']:
                    s.allocation_impacts(s.runs[rid], parts)
            s.chapter2_briefing_lines(s.runs[rid])
        self.assertEqual((gameplay(s), '\n'.join(s.db.conn.iterdump())), before)


class DecisionRecordTests(unittest.TestCase):
    def test_results_show_only_recorded_decisions(self):
        s, jp, us = ready()
        s.selected_id = jp; s.wait_request()
        start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
        result = s.chapter2_result()
        text = '\n'.join(result['decisions'])
        self.assertIn('같은 시각', text)
        self.assertIn('요청 대기 1회', text)
        self.assertIn('절약형 모드', text)
        self.assertIn('기한 내 완료', text)
        self.assertNotIn('먼저 배정한 고객', text)
        self.assertNotIn('자원을 반환했습니다', text)
        self.assertNotIn('대안 협의', text)

    def test_blocked_customer_is_explained_from_recorded_times(self):
        s, jp, us = ready(); start(s, us, 'performance'); finish_all(s)
        text = '\n'.join(s.chapter2_result()['decisions'])
        self.assertIn('먼저 배정한 고객: 미국', text)
        self.assertIn('최종 배정 기한', text)
        self.assertIn('기한 만료 · 미처리', text)
        self.assertNotIn('요청 대기', text)

    def test_proposal_and_rejection_are_reported_when_they_happened(self):
        s, jp, us = ready()
        s.selected_id = jp; s.propose_alternative(); s.review_alternative()
        start(s, jp, 'performance')
        s.selected_id = us; s.reject_request('현재 GPU 자원 부족'); finish_all(s)
        result = s.chapter2_result()
        text = '\n'.join(result['decisions'])
        self.assertIn('대안 협의 거절', text)
        self.assertIn('거절', text)
        self.assertFalse(result['concurrent'])

    def test_result_requires_completion_and_marks_practice(self):
        s, jp, us = ready()
        with self.assertRaises(ValueError):
            s.chapter2_result()
        start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
        self.assertTrue(s.chapter2_result()['practice'])
        s2 = after_chapter1(Database(':memory:')); s2.start_chapter2()
        s2.confirm_chapter2_briefing()
        a, b = s2.story.chapter2.request_ids
        start(s2, a, 'performance'); start(s2, b, 'economy'); finish_all(s2)
        self.assertFalse(s2.chapter2_result()['practice'])


class FailureJudgementTests(unittest.TestCase):
    """v0.9-2a-3: 실패 예측(내부 판단)과 실패 확정(선배 안내)을 구분합니다. 확정은 실제로 철회·거절·만료·기한 초과 완료가 된 뒤입니다."""

    def run_until_failure(self, s, limit=30):
        for _ in range(limit):
            if s.story.chapter2.failure is not None:
                return
            s.advance_time(10)
        raise AssertionError('실패가 확정되지 않았습니다.')

    def test_A_starting_us_high_performance_does_not_show_failure_feedback(self):
        s, jp, us = ready()
        start(s, us, 'performance')
        self.assertIsNone(s.story.chapter2.failure)
        self.assertFalse(s.chapter2_failure_pending)
        # 일본 고객의 기한 내 완료가 어렵다는 예측은 내부 판단 자료로만 남습니다.
        self.assertEqual(s.chapter2_job_state(s.runs[jp]), ('failed', 'late_certain'))
        self.assertFalse(s.chapter2_retry_available)                  # 아직 아무 대응도 시도하지 않음
        self.assertEqual(s.runs[jp].request['status'], 'new')
        self.assertIsNone(s.runs[jp].playthrough_id)
        self.assertFalse(s.story.chapter2.completed)
        s.advance_time(10)                                            # 시간이 흘러도 예측만으로는 안내하지 않음
        self.assertFalse(s.chapter2_failure_pending)

    def test_B_failed_japan_allocation_explains_cause_only_and_keeps_request_alive(self):
        s, jp, us = ready(); start(s, us, 'performance')
        before = gameplay(s)
        with self.assertRaises(ValueError) as caught:
            start(s, jp, 'performance')
        message = str(caught.exception)
        self.assertIn('GPU 또는 전력이 부족', message)
        self.assertIn('조건 협의', message)
        self.assertNotIn('실패', message)
        self.assertEqual(gameplay(s), before)
        self.assertEqual(s.runs[jp].request['status'], 'new')
        self.assertIsNone(s.story.chapter2.failure)
        self.assertFalse(s.chapter2_failure_pending)
        self.assertFalse(s.story.chapter2.completed)
        # 같은 안내는 Chapter 2 요청에만 붙고 자유 운영 메시지는 바뀌지 않습니다.
        free = GameSession(Database(':memory:'), seed=9)
        with patch.object(free, 'allocation_preview', return_value={'allowed': True, 'slices': None}):
            self.assertEqual(free._chapter2_hint(free.current), '')

    def test_C_japan_alternative_can_be_proposed_and_the_customer_answer_is_checked(self):
        s, jp, us = ready(); start(s, us, 'performance')
        s.selected_id = jp
        s.propose_alternative()
        self.assertEqual(s.runs[jp].proposals[-1]['status'], 'pending')
        self.assertFalse(s.review_alternative())                      # 고객은 기한을 넘기는 절약형을 거절
        proposal = s.runs[jp].proposals[-1]
        self.assertEqual(proposal['status'], 'rejected')
        self.assertEqual(s.runs[jp].conditions['allowed_modes'], ['performance'])   # 고객 조건은 그대로
        with self.assertRaises(ValueError):
            s.choose_plan('economy')                                  # 동의 없는 변경은 불가
        self.assertEqual(s.runs[jp].request['status'], 'new')         # 요청은 아직 살아 있음
        self.assertIsNone(s.story.chapter2.failure)                   # 협의 거절만으로는 실패 확정이 아님
        self.assertFalse(s.chapter2_failure_pending)
        self.assertTrue(s.chapter2_retry_available)                   # 대응을 시도했으므로 직접 선택하는 재도전은 가능
        self.assertEqual(s.runs[jp].request['status'], 'new')         # 재도전 가능 여부 확인이 요청을 바꾸지 않음

    def test_D_feedback_appears_only_after_the_request_is_actually_lost(self):
        s, jp, us = ready(); start(s, us, 'performance')
        s.selected_id = jp; s.propose_alternative(); s.review_alternative()
        s.advance_time(60)
        self.assertIsNone(s.story.chapter2.failure)                    # 최종 배정 기한(80분) 전에는 확정되지 않음
        self.run_until_failure(s)
        failure = s.story.chapter2.failure
        self.assertEqual((failure['request_id'], failure['reason']), (jp, 'expired'))
        self.assertEqual(s.minute - 540, 80)
        self.assertTrue(s.chapter2_failure_pending)
        self.assertEqual(failure['tried']['proposal'], 'rejected')
        self.assertEqual(failure['blocker']['country'], '미국')
        from story import chapter2_failure_pages
        text = '\n'.join(p.text for p in chapter2_failure_pages(failure))
        self.assertIn('일본 고객의 요청이 결국 철회됐습니다', text)
        self.assertIn('미국 고객의 고성능 모드 작업', text)
        self.assertIn('절약형 대안을 협의했지만 고객이 거절했습니다', text)
        self.assertIn('다른 방법도 검토했지만 이번에는 해결하지 못했습니다', text)
        self.assertIn('정상적으로 진행되고 있지만', text)
        self.assertIn('비교해 보세요', text)
        # 시도하지 않은 행동은 시도했다고 말하지 않습니다.
        s2, jp2, us2 = ready(); start(s2, us2, 'performance'); self.run_until_failure(s2)
        text2 = '\n'.join(p.text for p in chapter2_failure_pages(s2.story.chapter2.failure))
        self.assertNotIn('협의', text2)
        self.assertNotIn('요청 대기', text2)
        self.assertNotIn('다른 방법도 검토했지만', text2)

    def test_D_player_reject_and_waiting_are_judged_from_real_choices(self):
        s, jp, us = ready(); start(s, jp, 'performance')
        s.selected_id = us; s.reject_request('현재 전력 공급 여유 부족')
        self.assertEqual((s.story.chapter2.failure['request_id'], s.story.chapter2.failure['reason']), (us, 'rejected'))
        self.assertTrue(s.chapter2_failure_pending)
        s, jp, us = ready(); s.selected_id = jp; s.wait_request(); s.advance_time(30)
        self.assertIsNone(s.story.chapter2.failure)                    # 아직 자원이 있어 시작할 수 있으니 확정이 아님
        self.assertTrue(s.chapter2_retry_available)
        self.run_until_failure(s, limit=40)
        self.assertEqual(s.story.chapter2.failure['reason'], 'expired')
        self.assertEqual(s.story.chapter2.failure['tried']['wait_choices'], 1)
        from story import chapter2_failure_pages
        text = '\n'.join(p.text for p in chapter2_failure_pages(s.story.chapter2.failure))
        self.assertIn('요청 대기를 1회 선택했습니다', text)
        self.assertNotIn('자원을 사용하는 동안', text)               # 선점 원인이 없으므로 쓰지 않음

    def test_E_retry_is_available_right_after_final_failure_with_other_job_running(self):
        s, jp, us = ready(); start(s, us, 'performance'); self.run_until_failure(s)
        self.assertTrue(s.chapter2_retry_available)
        self.assertEqual(s.runs[us].state.phase, 'running')
        snapshot = deepcopy(gameplay(s)), s.db.conn.serialize()
        new = GameSession(Database(':memory:'), mode='story', start_chapter=2, seed=9)
        self.assertEqual((new.minute, new.center.gpu_used, len(new.runs), new.story.chapter_completed), (540, 0, 2, False))
        self.assertIsNone(new.story.chapter2.failure)
        self.assertEqual((deepcopy(gameplay(s)), s.db.conn.serialize()), snapshot)   # 기존 슬롯 보존

    def test_F_other_customers_job_is_never_cancelled_or_changed_by_the_failure(self):
        s, jp, us = ready(); start(s, us, 'performance')
        allocation = s.servers.allocations[s.runs[us].playthrough_id]
        self.run_until_failure(s)
        run = s.runs[us]
        self.assertEqual((run.state.phase, run.request['status']), ('running', 'operating'))
        self.assertEqual(s.servers.allocations[run.playthrough_id], allocation)
        self.assertTrue(ledger_matches_center(s))
        finish_all(s)
        result = s.chapter2_result()
        self.assertEqual(result['jobs'][1]['score'], 100)              # 미국 점수는 그대로 보존
        self.assertEqual((result['mission'], result['overall']), ('failed', 50))
        self.assertEqual(result['jobs'][0]['score'], None)

    def test_G_successful_strategies_never_produce_failure_feedback(self):
        for name in ('eco', 'exact'):
            s, jp, us = ready()
            if name == 'eco':
                start(s, jp, 'performance'); start(s, us, 'economy')
            else:
                start(s, jp, 'performance')
            for step in range(40):
                self.assertIsNone(s.story.chapter2.failure, (name, step))
                self.assertFalse(s.chapter2_failure_pending)
                self.assertFalse(s.chapter2_retry_available)
                if s.story.chapter2.completed:
                    break
                if name == 'exact' and s.minute - 540 == 40:
                    start(s, us, 'performance')
                s.advance_time(10)
            self.assertTrue(s.story.chapter2.completed)
            self.assertEqual(s.chapter2_result()['mission'], 'success')
            self.assertIsNone(s.story.chapter2.failure)

    def test_H_failure_feedback_is_not_duplicated_after_save_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'story.db'
            db = Database(path)
            s = GameSession(db, mode='story', start_chapter=2, seed=9)
            s.confirm_chapter2_briefing()
            jp, us = s.story.chapter2.request_ids
            start(s, us, 'performance')
            s.close()
            db = Database(path); mid = GameSession(db, mode='story')   # 확정 전에 이어하기: 안내 없음
            self.assertFalse(mid.chapter2_failure_pending)
            self.run_until_failure(mid)
            mid.close()
            db = Database(path); again = GameSession(db, mode='story')   # 확정 후 아직 보지 않음: 다시 안내
            self.assertTrue(again.chapter2_failure_pending)
            again.mark_chapter2_failure_seen(); again.mark_chapter2_failure_seen()
            first = deepcopy(again.story.chapter2.failure)
            again.advance_time(10)
            again.close()
            db = Database(path); resumed = GameSession(db, mode='story')
            self.assertFalse(resumed.chapter2_failure_pending)
            self.assertEqual(resumed.story.chapter2.failure, first)
            finish_all(resumed)
            self.assertFalse(resumed.chapter2_failure_pending)
            self.assertEqual(resumed.story.chapter2.failure, first)
            resumed.close()

    def test_final_score_is_average_with_zero_for_unprocessed_customer(self):
        s, jp, us = ready(); start(s, us, 'performance')
        self.assertIsNone(s.chapter2_evaluation()['overall'])          # 진행 중 점수는 확정하지 않음
        finish_all(s)
        evaluation = s.chapter2_evaluation()
        self.assertEqual([j['score'] for j in evaluation['jobs']], [0, 100])
        self.assertEqual(evaluation['overall'], 50)
        result = s.chapter2_result()
        self.assertEqual((result['mission'], result['overall']), ('failed', 50))
        self.assertEqual(result['failure']['reason'], 'expired')

    def test_success_requires_both_on_time_and_gives_average_score(self):
        s, jp, us = ready(); start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
        result = s.chapter2_result()
        self.assertEqual((result['mission'], result['failure']), ('success', None))
        self.assertEqual(result['overall'], (s.runs[jp].state.score + s.runs[us].state.score) / 2)
        s, jp, us = ready(); start(s, jp, 'performance'); s.advance_time(30); s.advance_time(10)
        start(s, us, 'performance'); finish_all(s)
        self.assertEqual((s.chapter2_result()['mission'], s.chapter2_result()['overall']), ('success', 100))

    def test_late_completion_is_confirmed_when_it_happens_and_keeps_the_real_score(self):
        s, jp, us = ready(); start(s, jp, 'performance'); s.advance_time(60)
        self.assertIsNone(s.story.chapter2.failure)                    # 예측만 있고 아직 확정이 아님
        start(s, us, 'performance')
        self.assertIsNone(s.story.chapter2.failure)
        self.run_until_failure(s)
        self.assertEqual((s.story.chapter2.failure['request_id'], s.story.chapter2.failure['reason']), (us, 'late'))
        self.assertIsNone(s.story.chapter2.failure['blocker'])
        finish_all(s)
        result = s.chapter2_result()
        self.assertEqual(result['mission'], 'failed')
        us_job = result['jobs'][1]
        self.assertEqual((us_job['outcome'], us_job['on_time'], us_job['reason']), ('정상 완료', False, 'late'))
        self.assertEqual(us_job['eval_score'], s.runs[us].state.score)  # 이중 감점 없이 기존 점수 사용
        self.assertGreater(us_job['eval_score'], 0)
        self.assertEqual(result['overall'], (100 + us_job['eval_score']) / 2)

    def test_resource_shortage_or_rejected_proposal_alone_is_not_a_final_failure(self):
        s, jp, us = ready()
        s.selected_id = jp; s.propose_alternative(); self.assertFalse(s.review_alternative())
        self.assertIsNone(s.story.chapter2.failure)
        start(s, jp, 'performance')
        with self.assertRaises(ValueError):
            start(s, us, 'performance')
        self.assertIsNone(s.story.chapter2.failure)
        start(s, us, 'economy')
        self.assertIsNone(s.story.chapter2.failure)

    def test_failure_detection_rolls_back_with_a_failed_save(self):
        s, jp, us = ready(); start(s, jp, 'performance')
        before = deepcopy(s.story.payload()), gameplay(s)
        s.selected_id = us
        with patch.object(s.db, 'save_simulation', side_effect=OSError('저장 실패')):
            with self.assertRaises(OSError):
                s.reject_request('현재 GPU 자원 부족')
        self.assertIsNone(s.story.chapter2.failure)
        self.assertEqual(s.runs[us].request['status'], 'new')
        self.assertEqual((s.story.payload(), gameplay(s)), before)

    def test_mark_seen_failure_save_keeps_feedback_pending(self):
        s, jp, us = ready(); start(s, jp, 'performance')
        s.selected_id = us; s.reject_request('현재 전력 공급 여유 부족')
        with patch.object(s.db, 'save_simulation', side_effect=OSError('저장 실패')):
            with self.assertRaises(OSError):
                s.mark_chapter2_failure_seen()
        self.assertTrue(s.chapter2_failure_pending)
        with self.assertRaises(ValueError):
            ready()[0].mark_chapter2_failure_seen()                      # 실패가 없으면 기록할 수 없음

    def test_saves_from_earlier_versions_are_reread_without_losing_a_real_failure(self):
        for finished in (False, True):
            with self.subTest(finished=finished), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'old.db'
                db = Database(path)
                s = GameSession(db, mode='story', start_chapter=2, seed=9)
                s.confirm_chapter2_briefing()
                jp, us = s.story.chapter2.request_ids
                start(s, us, 'performance')
                if finished:
                    finish_all(s)
                s.close()
                db = Database(path)
                saved = db.get_simulation()
                if finished:
                    saved['story']['chapter2'].pop('failure'); saved['story']['chapter2'].pop('failure_seen')   # v0.9-2a 형식
                else:
                    # v0.9-2a-2는 예측만으로 실패를 기록했습니다. 확정이 아니므로 다시 판정합니다.
                    saved['story']['chapter2']['failure'] = {'request_id': jp, 'reason': 'late_certain', 'minute': 540}
                    saved['story']['chapter2']['failure_seen'] = False
                db.save_simulation(saved)
                db.close()
                db = Database(path); old = GameSession(db, mode='story')
                if finished:
                    self.assertEqual(old.story.chapter2.failure['reason'], 'expired')
                    self.assertFalse(old.chapter2_failure_pending)       # 끝난 저장은 결과 화면에만 표시
                    self.assertEqual(old.chapter2_result()['mission'], 'failed')
                else:
                    self.assertIsNone(old.story.chapter2.failure)
                    self.assertFalse(old.chapter2_failure_pending)
                old.close()

    def test_chapter_one_scores_and_free_mode_are_untouched(self):
        s = after_chapter1(Database(':memory:'))
        score = s.runs[s.story.request_id].state.score
        s.start_chapter2()
        s.confirm_chapter2_briefing()
        a, b = s.story.chapter2.request_ids
        start(s, b, 'performance'); finish_all(s)
        self.assertEqual(s.runs[s.story.request_id].state.score, score)
        free = GameSession(Database(':memory:'), seed=9)
        self.assertIsNone(free.story)
        self.assertTrue(all(r.state.scenario is None for r in free.runs.values()))


class ProgressTests(unittest.TestCase):
    def test_steps_follow_real_actions_only(self):
        s = practice()
        jp, us = s.story.chapter2.request_ids
        steps = lambda: list(s.story.chapter2.completed_steps)
        s.read_conversation(jp); s.read_conversation(us)
        self.assertEqual(steps(), [])                 # 브리핑 확인 전에는 올라가지 않음
        s.confirm_chapter2_briefing()
        self.assertEqual(steps(), ['briefing', 'requests'])
        s.inspect_story_preview(jp)
        self.assertEqual(steps(), ['briefing', 'requests'])
        s.inspect_story_preview(us)
        self.assertEqual(steps(), ['briefing', 'requests', 'review'])
        start(s, jp, 'performance')
        self.assertEqual(steps(), ['briefing', 'requests', 'review'])
        start(s, us, 'economy')
        self.assertEqual(steps()[-1], 'allocate')
        s.advance_time(10)
        self.assertEqual(steps()[-1], 'progress')
        finish_all(s)
        self.assertEqual(s.story.ui_step, 'c2_done')

    def test_selecting_or_previewing_does_not_allocate(self):
        s, jp, us = ready()
        before = gameplay(s), '\n'.join(s.db.conn.iterdump())
        for rid in (jp, us):
            for parts in s.allocation_options(s.runs[rid], 'performance')['options']:
                s.allocation_impacts(s.runs[rid], parts)
        self.assertEqual((gameplay(s), '\n'.join(s.db.conn.iterdump())), before)
        self.assertNotIn('allocate', s.story.chapter2.completed_steps)

    def test_briefing_cannot_be_confirmed_twice_and_save_failure_rolls_back(self):
        s = practice()
        with patch.object(s.db, 'save_simulation', side_effect=OSError('저장 실패')):
            with self.assertRaises(OSError):
                s.confirm_chapter2_briefing()
        self.assertFalse(s.story.chapter2.briefing_confirmed)
        s.confirm_chapter2_briefing()
        with self.assertRaises(ValueError):
            s.confirm_chapter2_briefing()

    def test_direct_start_without_reading_does_not_block_later_steps(self):
        s, jp, us = ready()
        start(s, jp, 'performance'); start(s, us, 'economy')
        self.assertEqual(s.story.chapter2.completed_steps[:4], ['briefing', 'requests', 'review', 'allocate'])

    def test_shared_ledger_never_double_books_slots(self):
        s, jp, us = ready()
        start(s, jp, 'performance'); start(s, us, 'economy')
        taken = []
        for allocation in s.servers.allocations.values():
            for part in allocation.slices:
                taken += [(part.server_id, slot) for slot in part.gpu_slots]
        self.assertEqual(len(taken), len(set(taken)))
        self.assertTrue(ledger_matches_center(s))
        self.assertEqual((s.center.gpu_used, s.center.power_used), (8, 8))


class ResumeAndCompatibilityTests(unittest.TestCase):
    def test_disk_resume_at_every_stage_for_full_story_and_practice(self):
        for kind in ('after_chapter1', 'practice'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'story.db'
                db = Database(path)
                if kind == 'practice':
                    s = GameSession(db, mode='story', start_chapter=2, seed=9)
                    jp, us = s.story.chapter2.request_ids
                else:
                    s = after_chapter1(db); jp, us = s.start_chapter2()
                s.close()
                actions = (lambda s: None, lambda s: s.confirm_chapter2_briefing(),
                           lambda s: (s.read_conversation(jp), s.read_conversation(us)),
                           lambda s: (s.inspect_story_preview(jp), s.inspect_story_preview(us)),
                           lambda s: start(s, jp, 'performance'), lambda s: start(s, us, 'economy'),
                           lambda s: s.advance_time(10), lambda s: s.advance_time(60),
                           lambda s: s.advance_time(60), lambda s: s.advance_time(60))
                for action in actions:
                    db = Database(path); s = GameSession(db, mode='story')
                    action(s)
                    expected = deepcopy((s.story.payload(), s.minute, {k: vars(r.state) for k, r in s.runs.items()},
                                         s.servers.allocations))
                    s.close()
                    db = Database(path); restored = GameSession(db, mode='story')
                    self.assertEqual((restored.story.payload(), restored.minute,
                                      {k: vars(r.state) for k, r in restored.runs.items()}, restored.servers.allocations), expected)
                    self.assertEqual(db.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(db.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
                    self.assertTrue(ledger_matches_center(restored))
                    restored.close()
                db = Database(path); final = GameSession(db, mode='story')
                self.assertTrue(final.story.chapter2.completed)
                self.assertEqual(final.chapter2_result()['jobs'][0]['country'], '일본')
                self.assertEqual(final.story.practice, kind == 'practice')
                final.close()

    def test_v092a_save_without_scenario_keeps_its_original_numbers(self):
        # v0.9-2a에서 시작한 Chapter 2 저장(scenario 필드 없음)은 그대로 이어집니다.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'old.db'
            db = Database(path)
            s = after_chapter1(db)
            with s._atomic():
                ids = [s._receive(mid, f'chapter2:{mid}') for mid, m in s.missions.items() if m['country'] in CHAPTER2_COUNTRIES]
                s.story.chapter2 = Chapter2Progress(*ids)
            s.close()
            db = Database(path); old = GameSession(db, mode='story')
            jp, us = old.story.chapter2.request_ids
            self.assertEqual([old.runs[i].state.scenario for i in (jp, us)], [None, None])
            self.assertEqual(old.runs[jp].state.plans['performance']['gpu'], 3)
            self.assertEqual(old.runs[us].state.plans['performance']['power'], 6)
            old.confirm_chapter2_briefing()
            start(old, jp, 'performance'); start(old, us, 'performance')    # 이전 요구량은 동시 실행 가능
            finish_all(old)
            self.assertTrue(old.chapter2_result()['concurrent'])
            old.close()

    def test_invalid_saved_chapter_two_is_reported_without_repair(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = after_chapter1(db); s.start_chapter2()
        saved = db.get_simulation()
        saved['story']['chapter2']['us_request_id'] = saved['story']['request_id']
        db.save_simulation(saved)
        with self.assertRaises(ValueError):
            GameSession(db, mode='story')

    def test_chapter_two_needs_chapter_one_or_practice_and_validates_ids(self):
        with self.assertRaises(ValueError):
            StoryProgress(chapter2={'jp_request_id': 2, 'us_request_id': 3})
        StoryProgress(practice=True, chapter2={'jp_request_id': 1, 'us_request_id': 2})
        with self.assertRaises(ValueError):
            Chapter2Progress(2, 3, requests_read=[9])
        with self.assertRaises(ValueError):
            Chapter2Progress(2, 3, completed_steps=['requests'])
        with self.assertRaises(ValueError):
            Chapter2Progress(2, 2)
        self.assertEqual(Chapter2Progress(2, 3).step, STEPS2[0])


if __name__ == '__main__':
    unittest.main()
