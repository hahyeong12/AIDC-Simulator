"""v0.9-2a-4: Chapter 2 전략 밸런스. Tk 창을 만들지 않는 규칙/저장 검증.

새 Chapter 2(`ch2_jp` + `ch2_us_v2`)
- 일본: 고성능 GPU 4/전력 5 · 처리 40분 · 완료 기한 50분 · 최종 배정 80분 · 절약형은 고객 동의 필요
- 미국: 고성능 GPU 6/전력 6 · 70분, 절약형 GPU 4/전력 3 · 100분 · 완료 기한 100분 · 최종 배정 120분 · 두 모드 허용
- 서버 용량 GPU 10/전력 10 유지

모든 성공/실패는 실제 세션 엔진(시간 진행·자원 원장·기한 판정·점수)을 돌려서 얻은 결과만 확인합니다.
이전 v0.9-2a-2~3 슬롯의 `ch2_us`(작업 100·기한 150분)는 그대로 이어서 플레이됩니다.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chapter2
from chapter2 import CHAPTER2_SCENARIOS
from database import Database
from game import GameState, SCENARIOS
from session import GameSession
from story import GUIDES2, chapter2_failure_pages
from tests.test_chapter2 import ready, start, finish_all, ledger_matches_center, after_chapter1
from tests.test_story import gameplay


def run_strategy(actions):
    """actions(s, jp, us)를 실행하고 두 작업이 끝날 때까지 10분씩 진행합니다."""
    s, jp, us = ready()
    actions(s, jp, us)
    finish_all(s)
    return s, jp, us


def until_finished(s, rid):
    while s.runs[rid].state.phase != 'finished':
        s.advance_time(10)


def feedback_text(s):
    return '\n'.join(page.text for page in chapter2_failure_pages(s.story.chapter2.failure))


def blocking_option(s, jp):
    """일본 고성능 배정안 중 미국 절약형 동시 배정을 막는 안(실제 미리보기 계산으로 찾음)."""
    for parts in s.allocation_options(s.runs[jp], 'performance')['options']:
        if any('절약형 모드 GPU 4/전력 3 배정 불가' in line for line in s.allocation_impacts(s.runs[jp], parts)):
            return parts
    raise AssertionError('막는 배정안이 없습니다.')


class BalanceDataTests(unittest.TestCase):
    def test_new_chapter_uses_new_scenario_and_keeps_capacity(self):
        self.assertEqual(CHAPTER2_SCENARIOS, {'일본': 'ch2_jp', '미국': 'ch2_us_v2'})
        s, jp, us = ready()
        self.assertEqual((s.runs[jp].state.scenario, s.runs[us].state.scenario), ('ch2_jp', 'ch2_us_v2'))
        self.assertEqual((s.center.gpu_total, s.center.power_total), (10, 10))
        jp_run, us_run = s.runs[jp], s.runs[us]
        self.assertEqual([(p['gpu'], p['power']) for p in jp_run.state.plans.values()], [(4, 5), (2, 3)])
        self.assertEqual([(p['gpu'], p['power']) for p in us_run.state.plans.values()], [(6, 6), (4, 3)])
        self.assertEqual((jp_run.state.estimate_minutes('performance'), us_run.state.estimate_minutes('performance'),
                          us_run.state.estimate_minutes('economy')), (40, 70, 100))
        received = jp_run.terms['received']
        self.assertEqual((jp_run.terms['due'] - received, jp_run.terms['expires'] - received), (50, 80))
        self.assertEqual((us_run.terms['due'] - received, us_run.terms['expires'] - received), (100, 120))
        # 요청서에 실제 모드별 처리 시간이 들어갑니다.
        self.assertIn('고성능 모드 70분 / 절약형 모드 100분', us_run.request['message'])

    def test_old_scenario_numbers_are_unchanged(self):
        self.assertEqual(SCENARIOS['ch2_us']['work'], 100)
        self.assertEqual(SCENARIOS['ch2_us']['window'], ('우선 · 데이터 분석', 40, 150, 240))
        self.assertEqual(SCENARIOS['ch2_us']['plans'], SCENARIOS['ch2_us_v2']['plans'])

    def test_estimates_match_actual_completion_at_every_step(self):
        # 42/0.7 같은 부동소수점 오차가 남은 시간을 10분 늘리지 않습니다(예측 = 실제).
        for scenario, country in (('ch2_us_v2', '미국'), ('ch2_jp', '일본'), ('ch2_us', '미국')):
            for mode in ('performance', 'economy'):
                state = GameState(scenario=scenario, country=country)
                state.choose_plan(mode)
                predicted, elapsed = state.remaining_minutes, 0
                while state.phase != 'finished':
                    self.assertEqual(state.remaining_minutes, predicted - elapsed, (scenario, mode, elapsed))
                    state.advance(10); elapsed += 10
                self.assertEqual(elapsed, predicted, (scenario, mode))

    def test_free_mode_and_chapter_one_rules_are_unchanged(self):
        for country, work in (('싱가포르', 120), ('일본', 60), ('미국', 100)):
            self.assertEqual(GameState(country=country).work_total, work)
        self.assertEqual(GameState(country='싱가포르').estimate_minutes('economy'), 180)
        self.assertEqual(GameState(country='미국').estimate_minutes('economy'), 150)
        free = GameSession(Database(':memory:'), seed=9)
        self.assertTrue(all(r.state.scenario is None for r in free.runs.values()))
        self.assertEqual(free.chapter2_comparison_lines(), [])


class StrategyTests(unittest.TestCase):
    """요구 전략 A~E. 성공/실패는 실제 엔진의 기한·점수 판정에서만 나옵니다."""

    def test_1_japan_high_then_us_high_fails_us_deadline(self):
        def actions(s, jp, us):
            start(s, jp, 'performance'); until_finished(s, jp); start(s, us, 'performance')
        s, jp, us = run_strategy(actions)
        result = s.chapter2_result()
        jp_job, us_job = result['jobs']
        self.assertEqual((jp_job['on_time'], us_job['on_time']), (True, False))
        self.assertEqual((s.runs[us].terms['started'] - s.runs[us].terms['received'], us_job['late_minutes']), (40, 10))
        self.assertEqual(result['mission'], 'failed')
        self.assertEqual((result['failure']['request_id'], result['failure']['reason']), (us, 'late'))
        self.assertFalse(result['concurrent'])
        text = feedback_text(s)
        self.assertIn('일본 고객을 먼저 처리했지만', text)
        self.assertIn('미국 고객도 고성능 모드로 실행하면서 완료 기한을 넘겼습니다', text)
        self.assertNotIn('자원이 부족해졌습니다', text)          # 실제로 막은 작업은 없었음

    def test_2_us_high_then_japan_high_fails_japan(self):
        # 미국 고성능이 끝난 뒤(70분) 일본을 시작하면 기한(50분)을 넘깁니다.
        def actions(s, jp, us):
            start(s, us, 'performance')
            with self.assertRaises(ValueError):
                start(s, jp, 'performance')                       # 전력 11 > 10
            until_finished(s, us); start(s, jp, 'performance')
        s, jp, us = run_strategy(actions)
        result = s.chapter2_result()
        self.assertEqual([j['on_time'] for j in result['jobs']], [False, True])
        self.assertEqual(result['mission'], 'failed')
        failure = result['failure']
        self.assertEqual((failure['request_id'], failure['reason']), (jp, 'late'))
        self.assertEqual((failure['blocker']['country'], failure['blocker']['placement']), ('미국', False))
        text = feedback_text(s)
        self.assertIn('미국 고객의 고성능 모드 작업(GPU 6/전력 6)을 배정하면서 일본 고객의 작업에 필요한 자원이 부족해졌습니다', text)
        self.assertNotIn('먼저 처리했지만', text)
        # 아무 대응 없이 기다리면 일본 요청은 최종 배정 기한에 철회됩니다.
        s, jp, us = run_strategy(lambda s, jp, us: start(s, us, 'performance'))
        self.assertEqual(s.chapter2_result()['failure']['reason'], 'expired')
        self.assertEqual(s.chapter2_result()['failure']['blocker']['country'], '미국')

    def test_3_japan_high_with_us_economy_together_succeeds(self):
        for order in ('jp_first', 'us_first'):
            with self.subTest(order=order):
                def actions(s, jp, us):
                    pair = ((jp, 'performance'), (us, 'economy'))
                    for rid, mode in (pair if order == 'jp_first' else reversed(pair)):
                        start(s, rid, mode)
                    self.assertEqual((s.center.gpu_used, s.center.power_used), (8, 8))
                s, jp, us = run_strategy(actions)
                result = s.chapter2_result()
                self.assertEqual(result['mission'], 'success')
                self.assertTrue(all(j['on_time'] is True and j['succeeded'] for j in result['jobs']))
                self.assertTrue(result['concurrent'])
                self.assertIsNone(result['failure'])
                self.assertEqual(s.runs[us].terms['completed'], s.runs[us].terms['due'])   # 기한에 정확히 맞춤
                text = '\n'.join(result['highlights'])
                self.assertIn('고객이 원래 요청한 고성능 모드', text)
                self.assertIn('고객이 허용한 절약형 모드', text)
                self.assertIn('완료 기한 D1 09:50보다 10분 먼저 끝냈습니다', text)
                self.assertIn('완료 기한 D1 10:40에 맞춰 끝냈습니다', text)
                self.assertIn('두 작업을 동시에 실행하며 GPU 8개와 전력 8단위', text)
                self.assertEqual(s.servers.allocations, {})
                self.assertTrue(ledger_matches_center(s))

    def test_4_unfavourable_placement_blocks_us_despite_enough_total_resources(self):
        s, jp, us = ready()
        parts = blocking_option(s, jp)
        start(s, jp, 'performance', plan=parts)
        gpu, power = s.servers.available()
        self.assertGreaterEqual((gpu, power), (4, 3))           # 전체 숫자로는 미국 절약형(4/3)이 들어감
        preview = s.allocation_preview(s.runs[us], 'economy')
        self.assertEqual((preview['allowed'], preview['reason']), (False, '서버별 GPU·전력 조합 불가'))
        before = gameplay(s), '\n'.join(s.db.conn.iterdump())
        with self.assertRaises(ValueError):
            start(s, us, 'economy')
        self.assertEqual((gameplay(s), '\n'.join(s.db.conn.iterdump())), before)
        # 일본이 끝나 자원이 반환된 뒤에야 시작할 수 있고, 그만큼 늦어 실패합니다.
        until_finished(s, jp); start(s, us, 'economy'); finish_all(s)
        failure = s.story.chapter2.failure
        self.assertEqual((failure['request_id'], failure['reason']), (us, 'late'))
        self.assertTrue(failure['blocker']['placement'])
        self.assertIn('서버별 GPU와 전력을 함께 묶을 수 없었습니다', feedback_text(s))
        # 같은 모드라도 다른 배정안을 고르면 함께 시작할 수 있습니다.
        s2, jp2, us2 = ready()
        other = next(p for p in s2.allocation_options(s2.runs[jp2], 'performance')['options'] if p != parts)
        start(s2, jp2, 'performance', plan=other)
        self.assertTrue(s2.allocation_preview(s2.runs[us2], 'economy')['allowed'])

    def test_5_time_buttons_change_the_outcome(self):
        outcomes = {}
        for skip in (0, 10, 30, 60):
            def actions(s, jp, us, skip=skip):
                if skip:
                    s.advance_time(skip)
                start(s, jp, 'performance'); start(s, us, 'economy')
            s, jp, us = run_strategy(actions)
            result = s.chapter2_result()
            outcomes[skip] = (result['mission'], tuple(j['late_minutes'] for j in result['jobs']))
        self.assertEqual(outcomes[0], ('success', (0, 0)))
        self.assertEqual(outcomes[10], ('failed', (0, 10)))     # 일본은 여유 10분, 미국 절약형은 여유가 없음
        self.assertEqual(outcomes[30], ('failed', (20, 30)))
        self.assertEqual(outcomes[60], ('failed', (50, 60)))
        # 결정을 모두 내린 뒤에는 버튼 크기(+10 반복 / +60)가 결과를 바꾸지 않습니다.
        results = []
        for step in (10, 30, 60):
            s, jp, us = ready(); start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s, step=step)
            results.append([(j['completed'], j['score']) for j in s.chapter2_result()['jobs']])
        self.assertEqual(results[0], results[1]); self.assertEqual(results[0], results[2])

    def test_6_failure_feedback_waits_for_the_confirmed_outcome(self):
        s, jp, us = ready(); start(s, jp, 'performance'); until_finished(s, jp); start(s, us, 'performance')
        self.assertEqual(s.chapter2_job_state(s.runs[us]), ('failed', 'late_certain'))   # 내부 예측
        while s.minute - 540 < 110:
            self.assertIsNone(s.story.chapter2.failure, s.minute - 540)
            self.assertFalse(s.chapter2_failure_pending)
            self.assertFalse(s.chapter2_retry_available)
            s.advance_time(10)
        self.assertEqual(s.story.chapter2.failure['reason'], 'late')    # 실제로 늦게 끝난 110분에 확정
        self.assertEqual(s.story.chapter2.failure['minute'] - 540, 110)
        self.assertTrue(s.chapter2_failure_pending)
        # 미국 고성능 선행: 일본 철회(80분) 전에는 안내하지 않습니다.
        s, jp, us = ready(); start(s, us, 'performance')
        while s.minute - 540 < 80:
            self.assertIsNone(s.story.chapter2.failure); s.advance_time(10)
        self.assertEqual(s.story.chapter2.failure['reason'], 'expired')
        # 성공 전략은 진행 중 어떤 순간에도 실패 예측/확정이 없습니다(예상 시간 오차 회귀 검증).
        s, jp, us = ready(); start(s, jp, 'performance'); start(s, us, 'economy')
        while not s.story.chapter2.completed:
            self.assertEqual({s.chapter2_job_state(s.runs[r])[0] for r in (jp, us)} - {'running', 'success'}, set())
            self.assertIsNone(s.story.chapter2.failure)
            s.advance_time(10)

    def test_7_conditions_cannot_change_without_customer_consent(self):
        s, jp, us = ready()
        jp_conditions, us_conditions = deepcopy(s.runs[jp].conditions), deepcopy(s.runs[us].conditions)
        s.selected_id = jp
        with self.assertRaises(ValueError):
            s.choose_plan('economy')                              # 일본 절약형은 동의 필요
        self.assertEqual(s.mode_status(s.runs[jp], 'economy'), '고객 동의 필요')
        s.propose_alternative()
        with self.assertRaises(ValueError):
            s.choose_plan('economy')                              # 답변 대기 중에도 불가
        self.assertFalse(s.review_alternative())                  # 절약형 60분 > 기한 50분 → 고객 거절
        with self.assertRaises(ValueError):
            s.choose_plan('economy')
        with self.assertRaises(ValueError):
            s.propose_alternative()                               # 재협의 없음
        self.assertEqual((s.runs[jp].conditions, s.runs[us].conditions), (jp_conditions, us_conditions))
        # 미국은 두 모드를 처음부터 허용하므로 협의 없이 선택할 수 있고, 협의 자체가 필요 없습니다.
        self.assertTrue(s.plan_agreed(s.runs[us], 'economy') and s.plan_agreed(s.runs[us], 'performance'))
        s.selected_id = us
        with self.assertRaises(ValueError):
            s.propose_alternative()
        self.assertIsNone(s.runs[jp].playthrough_id)
        self.assertEqual(s.center.gpu_used, 0)

    def test_8_overall_score_matches_customer_scores(self):
        strategies = {
            'A': lambda s, jp, us: (start(s, jp, 'performance'), until_finished(s, jp), start(s, us, 'performance')),
            'B': lambda s, jp, us: (start(s, us, 'performance'), until_finished(s, us), start(s, jp, 'performance')),
            'B_wait': lambda s, jp, us: start(s, us, 'performance'),
            'C': lambda s, jp, us: (start(s, jp, 'performance'), start(s, us, 'economy')),
            'late': lambda s, jp, us: (s.advance_time(30), start(s, jp, 'performance'), start(s, us, 'economy')),
        }
        missions = {}
        for name, actions in strategies.items():
            with self.subTest(name=name):
                s, jp, us = run_strategy(actions)
                evaluation = s.chapter2_evaluation()
                expected = []
                for rid in (jp, us):
                    run = s.runs[rid]
                    expected.append(run.state.score if run.request['status'] == 'completed' and run.state.succeeded else 0)
                    if run.terms.get('expired'):
                        self.assertEqual(expected[-1], 0)
                self.assertEqual([j['score'] for j in evaluation['jobs']], expected)
                self.assertEqual(evaluation['overall'], sum(expected) / 2)
                result = s.chapter2_result()
                self.assertEqual(result['overall'], evaluation['overall'])
                self.assertEqual([j['eval_score'] for j in result['jobs']], expected)
                self.assertIn(f'{evaluation["overall"]:g}/100', s.chapter2_evaluation_lines()[-1])
                missions[name] = (evaluation['mission'], evaluation['overall'])
        self.assertEqual({k for k, v in missions.items() if v[0] == 'success'}, {'C'})
        self.assertEqual(missions['C'][1], max(v[1] for v in missions.values()))


class InformationTests(unittest.TestCase):
    def test_comparison_shows_real_values_for_both_customers_without_an_answer(self):
        s, jp, us = ready()
        before = gameplay(s), '\n'.join(s.db.conn.iterdump())
        text = '\n'.join(s.chapter2_comparison_lines())
        self.assertEqual((gameplay(s), '\n'.join(s.db.conn.iterdump())), before)   # 조회 전용
        for expected in ('일본', '미국', '고성능 모드: GPU 4/전력 5 · 처리 40분 · 고객 원래 요청',
                         '절약형 모드: GPU 2/전력 3 · 처리 60분 · 고객 동의 필요',
                         '고성능 모드: GPU 6/전력 6 · 처리 70분 · 고객 원래 요청',
                         '절약형 모드: GPU 4/전력 3 · 처리 100분 · 고객 허용 모드',
                         '완료 기한 D1 09:50 (남은 50분)', '완료 기한 D1 10:40 (남은 100분)',
                         '최종 배정 기한 D1 10:20', '최종 배정 기한 D1 11:00',
                         '서버별 남은 GPU/전력: A 4/4 · B 3/2 · C 2/3 · D 1/1'):
            self.assertIn(expected, text)
        for hint in ('추천', '권장', '정답', '먼저 처리', '선택하세요'):
            self.assertNotIn(hint, text)
        # 실제 배정 후에는 현재 원장으로 다시 계산합니다.
        start(s, jp, 'performance')
        text = '\n'.join(s.chapter2_comparison_lines())
        self.assertIn('실행 중 · 고성능 모드 GPU 4/전력 5 · 남은 처리 40분', text)
        self.assertNotIn('A 4/4', text)
        s.advance_time(10)
        self.assertIn('완료 기한 D1 10:40 (남은 90분)', '\n'.join(s.chapter2_comparison_lines()))

    def test_mentor_lines_list_what_to_check_but_never_the_answer(self):
        text = '\n'.join(d.text for key in ('briefing', 'requests', 'review', 'allocate') for d in GUIDES2[key][1])
        for item in ('GPU 요구량', '전력 요구량', '운영 모드별 예상 처리 시간', '완료 기한', '고객이 허용하는 운영 모드', '서버별로 남은 자원'):
            self.assertIn(item, text)
        for answer in ('절약형을 선택', '고성능을 선택', '일본 고객을 먼저', '미국 고객을 먼저', '동시에 배정하세요'):
            self.assertNotIn(answer, text)

    def test_allocation_briefing_reports_each_mode_against_the_deadline(self):
        s, jp, us = ready()
        lines = s.chapter2_briefing_lines(s.runs[us])
        self.assertTrue(any('고성능 모드' in l and '처리 70분' in l and '기한 내' in l for l in lines))
        self.assertTrue(any('절약형 모드' in l and '처리 100분' in l and '기한 내' in l for l in lines))
        s.advance_time(10)
        lines = s.chapter2_briefing_lines(s.runs[us])
        self.assertTrue(any('절약형 모드' in l and '기한 10분 초과' in l for l in lines))   # 시간이 흐르면 실제 값이 바뀜

    def test_old_failure_records_without_new_fields_still_render(self):
        record = {'request_id': 1, 'reason': 'expired', 'country': '일본', 'company': 'Sakura Robotics',
                  'expiry': 'D1 10:20', 'due': 'D1 09:50', 'waited': None, 'mode': None,
                  'blocker': {'country': '미국', 'company': 'Northstar AI', 'mode': '고성능 모드',
                              'gpu': 6, 'power': 6, 'until': 'D1 10:40'},
                  'tried': {'proposal': None, 'wait_choices': 0}, 'other': {'country': '미국', 'state': 'running'}}
        text = '\n'.join(p.text for p in chapter2_failure_pages(record))
        self.assertIn('미국 고객의 고성능 모드 작업(GPU 6/전력 6)', text)
        self.assertNotIn('서버별 GPU와 전력을 함께 묶을 수 없었습니다', text)
        self.assertIn('정상적으로 진행되고 있지만', text)


class CompatibilityTests(unittest.TestCase):
    """v0.9-2a-2~3에서 만든 Chapter 2 슬롯(`ch2_us`)은 이전 조건 그대로 이어집니다."""

    def make_old_slot(self, path, practice=True):
        db = Database(path)
        with patch.dict(chapter2.CHAPTER2_SCENARIOS, {'미국': 'ch2_us'}):
            if practice:
                s = GameSession(db, mode='story', start_chapter=2, seed=9)
            else:
                s = after_chapter1(db); s.start_chapter2()
        return s

    def test_in_progress_old_slot_keeps_old_numbers_after_resume(self):
        for practice in (True, False):
            with self.subTest(practice=practice), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'old.db'
                s = self.make_old_slot(path, practice)
                s.confirm_chapter2_briefing()
                jp, us = s.story.chapter2.request_ids
                start(s, jp, 'performance'); s.advance_time(10)
                terms = deepcopy(s.runs[us].terms)
                s.close()
                db = Database(path); old = GameSession(db, mode='story')
                run = old.runs[us]
                self.assertEqual(run.state.scenario, 'ch2_us')
                self.assertEqual(run.terms, terms)
                self.assertEqual((run.state.work_total, run.terms['due'] - run.terms['received']), (100, 150))
                self.assertEqual(run.state.estimate_minutes('performance'), 100)
                # 이전 조건에서는 일본 완료 직후 미국 고성능으로도 두 기한을 지킵니다(기존 결과 보존).
                until_finished(old, jp); start(old, us, 'performance'); finish_all(old)
                result = old.chapter2_result()
                self.assertEqual((result['mission'], result['overall']), ('success', 100))
                self.assertTrue(ledger_matches_center(old))
                old.close()

    def test_completed_old_slot_keeps_scores_and_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'done.db'
            s = self.make_old_slot(path)
            s.confirm_chapter2_briefing()
            jp, us = s.story.chapter2.request_ids
            start(s, jp, 'performance'); until_finished(s, jp); start(s, us, 'performance'); finish_all(s)
            stored = deepcopy({rid: (r.state.score, r.terms) for rid, r in s.runs.items()})
            result = s.chapter2_result()
            s.close()
            db = Database(path); again = GameSession(db, mode='story')
            self.assertEqual({rid: (r.state.score, r.terms) for rid, r in again.runs.items()}, stored)
            self.assertEqual(again.chapter2_result(), result)
            self.assertEqual(again.chapter2_result()['mission'], 'success')
            self.assertEqual(again.runs[us].state.scenario, 'ch2_us')
            again.close()

    def test_new_slot_after_old_slot_uses_new_rules_and_leaves_old_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            old_path = Path(directory)/'old.db'
            s = self.make_old_slot(old_path); s.confirm_chapter2_briefing(); s.close()
            before = old_path.read_bytes()
            fresh = GameSession(Database(Path(directory)/'new.db'), mode='story', start_chapter=2, seed=9)
            self.assertEqual(fresh.runs[fresh.story.chapter2.us_request_id].state.scenario, 'ch2_us_v2')
            fresh.close()
            self.assertEqual(old_path.read_bytes(), before)


class RollbackTests(unittest.TestCase):
    def test_failed_save_on_allocation_rolls_back_ledger_and_progress(self):
        s, jp, us = ready(); start(s, jp, 'performance')
        before = deepcopy(s.story.payload()), gameplay(s), dict(s.servers.allocations), '\n'.join(s.db.conn.iterdump())
        with patch.object(s.db, 'save_simulation', side_effect=OSError('저장 실패')):
            with self.assertRaises(OSError):
                start(s, us, 'economy')
        self.assertEqual((s.story.payload(), gameplay(s), s.servers.allocations, '\n'.join(s.db.conn.iterdump())), before)
        self.assertIsNone(s.runs[us].playthrough_id)
        self.assertTrue(ledger_matches_center(s))
        start(s, us, 'economy')                                     # 다시 시도하면 정상 배정
        self.assertEqual((s.center.gpu_used, s.center.power_used), (8, 8))
        self.assertTrue(ledger_matches_center(s))

    def test_failed_save_at_the_moment_of_failure_keeps_job_running_and_unrecorded(self):
        s, jp, us = ready(); start(s, jp, 'performance'); until_finished(s, jp); start(s, us, 'performance')
        while s.minute - 540 < 100:
            s.advance_time(10)
        before = deepcopy(s.story.payload()), gameplay(s), dict(s.servers.allocations), s.minute
        with patch.object(s.db, 'save_simulation', side_effect=OSError('저장 실패')):
            with self.assertRaises(OSError):
                s.advance_time(10)                                  # 이 10분에 미국 작업이 늦게 끝나며 실패가 확정될 차례
        self.assertEqual((s.story.payload(), gameplay(s), s.servers.allocations, s.minute), before)
        self.assertIsNone(s.story.chapter2.failure)
        self.assertEqual(s.runs[us].state.phase, 'running')
        self.assertTrue(ledger_matches_center(s))
        s.advance_time(10)
        self.assertEqual(s.story.chapter2.failure['reason'], 'late')
        self.assertEqual(s.servers.allocations, {})
        self.assertTrue(ledger_matches_center(s))

    def test_disk_resume_mid_strategy_keeps_ledger_and_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'slot.db'
            s = GameSession(Database(path), mode='story', start_chapter=2, seed=9)
            s.confirm_chapter2_briefing()
            jp, us = s.story.chapter2.request_ids
            start(s, jp, 'performance'); start(s, us, 'economy'); s.advance_time(30)
            allocations = dict(s.servers.allocations)
            s.close()
            again = GameSession(Database(path), mode='story')
            self.assertEqual(again.servers.allocations, allocations)
            self.assertEqual(again.runs[us].state.remaining_minutes, 70)
            self.assertTrue(ledger_matches_center(again))
            finish_all(again)
            self.assertEqual(again.chapter2_result()['mission'], 'success')
            again.close()


if __name__ == '__main__':
    unittest.main()
