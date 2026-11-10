"""v0.9-3a: Chapter 3(네트워크 장애 진단과 대응). Tk 창을 만들지 않는 규칙/저장 검증.

미션 A(ch3_path): 주 통신 경로 단절 → 백업 경로 우회만 복구(압축 불가).
미션 B(ch3_bw): 경로는 연결, 가용 대역폭 4 < 필요 6 → 압축만 복구(백업 경로는 같은 병목 공유라 우회 불가).
결과는 실제 엔진을 돌려 확인하며 하드코딩하지 않습니다.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chapter3 import Chapter3Progress, STEPS3, network_diagnosis
from database import Database
from game import GameState, SCENARIOS, RESPONSES, NETWORK_DURING_INCIDENT
from session import GameSession
from story import StoryProgress, GUIDES3, chapter3_feedback_pages
from story_slots import StorySlots
from tests.support import start_with_consent
from tests.test_chapter2 import ready, start, finish_all, after_chapter1


def practice3(db=None, seed=5):
    return GameSession(db or Database(':memory:'), mode='story', start_chapter=3, seed=seed)


def start_a(s):
    s.confirm_chapter3_briefing()
    a = s.story.chapter3.request_ids[0]
    s.read_conversation(a)
    s.selected_id = a
    s.choose_plan('performance')
    return a


def to_incident(s, rid=None, limit=12):
    rid = rid or s.selected_id
    for _ in range(limit):
        if s.runs[rid].state.phase == 'incident':
            return s.runs[rid].state
        s.advance_time(10)
    raise AssertionError('장애가 발생하지 않습니다.')


def finish_job(s, rid, limit=30):
    for _ in range(limit):
        if s.runs[rid].state.phase == 'finished':
            return s.runs[rid].state
        s.advance_time(10)
    raise AssertionError('작업이 끝나지 않습니다.')


def incident_a(seed=5):
    s = practice3(seed=seed)
    a = start_a(s)
    to_incident(s, a)
    return s, a


def play_a_correctly(s, a):
    to_incident(s, a)
    s.view_network_diagnosis(a)
    s.respond('reroute')
    finish_job(s, a)


def incident_b(mode='performance', seed=5):
    s = practice3(seed=seed)
    a = start_a(s)
    play_a_correctly(s, a)
    b = s.story.chapter3.request_ids[1]
    s.read_conversation(b)
    s.selected_id = b
    start_with_consent(s, mode)
    to_incident(s, b)
    return s, b


def expected_score(run):
    st = run.state
    raw = max(0, min(100, 80+st.plans[st.plan]['bonus']-st.cost_penalty-10*st.retry_count
                     - min(20, st.downtime//10) + (10 if st.succeeded else -65)))
    return max(0, raw - (run.terms.get('penalty') or 0))


def ledger_matches_center(s):
    return (sum(a.gpu for a in s.servers.allocations.values()) == s.center.gpu_used
            and sum(a.power for a in s.servers.allocations.values()) == s.center.power_used)


class IncidentOccursTests(unittest.TestCase):
    def test_mission_a_incident_is_deterministic_and_stops_the_clock(self):
        results = []
        for seed in (1, 5, 99, 12345):
            s = practice3(seed=seed)
            a = start_a(s)
            begin = s.minute
            s.advance_time(60)                      # 장애가 나면 남은 시간 진행은 멈춥니다.
            st = s.runs[a].state
            results.append((s.minute-begin, st.phase, st.incident_kind, st.work_done))
            self.assertEqual(st.downtime, 0)
        self.assertEqual(len(set(results)), 1, results)
        self.assertEqual(results[0][:3], (30, 'incident', 'path_down'))

    def test_incident_chance_setting_does_not_change_chapter3(self):
        for chance in (0, 1):
            s = GameSession(Database(':memory:'), mode='story', start_chapter=3, seed=2, incident_chance=chance)
            a = start_a(s)
            self.assertEqual(to_incident(s, a).incident_kind, 'path_down')

    def test_diagnosis_values_for_path_down_come_from_the_real_state(self):
        s, a = incident_a()
        d = s.view_network_diagnosis(a)
        st = s.runs[a].state
        self.assertEqual((d['kind'], d['primary'], d['link_ok']), ('path_down', 'DOWN', False))
        self.assertEqual((d['needed'], d['available']), (st.network_needed, st.network_available))
        self.assertEqual(d['available'], 0)
        self.assertIn('UP', d['backup']); self.assertIn('6', d['backup'])
        self.assertTrue(d['equipment_ok'])
        self.assertEqual(s.hardware_status(s.runs[a]), '')             # GPU/서버 정상, 하드웨어 중단 아님
        self.assertEqual(d['downtime'], st.downtime)
        self.assertEqual(d['progress'], round(st.progress))

    def test_diagnosis_values_for_bandwidth_shortage(self):
        s, b = incident_b()
        d = s.view_network_diagnosis(b)
        self.assertEqual((d['kind'], d['primary'], d['link_ok']), ('bandwidth', 'UP', True))
        self.assertGreater(d['needed'], d['available'])
        self.assertIn('공유', d['backup'])
        self.assertTrue(d['equipment_ok'])
        self.assertNotEqual(network_diagnosis(s.runs[b].state)['observations'],
                            network_diagnosis(self._path_state())['observations'])

    @staticmethod
    def _path_state():
        s, a = incident_a()
        return s.runs[a].state

    def test_no_diagnosis_without_an_incident(self):
        s = practice3()
        a = start_a(s)
        with self.assertRaises(ValueError):
            s.view_network_diagnosis(a)
        self.assertEqual(s.story.chapter3.diagnosed, [])


class ResponseEffectTests(unittest.TestCase):
    def test_a_compress_alone_never_restores_a_broken_path(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        st = s.runs[a].state
        s.respond('compress')
        self.assertEqual((st.phase, st.link_ok, st.response_log, st.response_attempts), ('paused', False, ['compress'], 1))
        self.assertLessEqual(st.network_needed, st.network_available + 5)
        self.assertEqual(st.cost_penalty, RESPONSES['compress']['penalty'])
        self.assertIsNone(st.recovered_by)
        self.assertEqual(st.network_available, 0)
        work = st.work_done
        s.advance_time(10)
        self.assertEqual((st.work_done, st.downtime), (work, 10))     # 작업은 재개되지 않고 중단 시간만 쌓입니다.
        s.respond('compress')                                         # 압축을 거듭해도 길은 생기지 않습니다.
        self.assertEqual((st.phase, st.network_available), ('paused', 0))
        self.assertEqual(st.network_needed, 1)                        # 필요량은 실제로 줄었습니다.
        self.assertFalse(st.link_ok)

    def test_a_backup_reroute_restores_and_job_completes(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        st = s.runs[a].state
        s.respond('reroute')
        self.assertEqual((st.phase, st.recovered_by, st.link_ok, st.rerouted), ('recovering', 'reroute', True, True))
        self.assertFalse(st.primary_up)                              # 주 경로는 여전히 끊어져 있고 백업을 씁니다.
        self.assertEqual(st.response_log, ['reroute'])
        finish_job(s, a)
        self.assertTrue(st.succeeded)
        self.assertEqual(s.runs[a].request['status'], 'completed')

    def test_b_reroute_alone_does_not_remove_the_bottleneck(self):
        s, b = incident_b()
        s.view_network_diagnosis(b)
        st = s.runs[b].state
        before = (st.network_available, st.network_needed)
        s.respond('reroute')
        self.assertEqual((st.phase, st.network_available, st.network_needed), ('paused', *before))
        self.assertTrue(st.rerouted and st.link_ok)
        self.assertIsNone(st.recovered_by)
        self.assertEqual(st.response_log, ['reroute'])
        self.assertIn('재개되지 않았습니다', st.result_text)
        self.assertNotIn('압축', st.result_text)                      # 정답을 알려 주지 않습니다.

    def test_b_compression_that_meets_the_condition_recovers(self):
        for mode in ('performance', 'economy'):
            with self.subTest(mode=mode):
                s, b = incident_b(mode)
                s.view_network_diagnosis(b)
                st = s.runs[b].state
                needed = st.network_needed
                s.respond('compress')
                self.assertEqual((st.phase, st.recovered_by), ('recovering', 'compress'))
                self.assertEqual(st.network_needed, needed-2)
                self.assertLessEqual(st.network_needed, st.network_available)
                finish_job(s, b)
                self.assertTrue(st.succeeded)

    def test_same_button_never_solves_both_missions(self):
        outcome = {}
        for key in RESPONSES:
            s, a = incident_a()
            s.view_network_diagnosis(a)
            s.respond(key)
            a_ok = s.runs[a].state.recovered_by == key
            s, b = incident_b()
            s.view_network_diagnosis(b)
            s.respond(key)
            outcome[key] = (a_ok, s.runs[b].state.recovered_by == key)
        self.assertEqual(outcome, {'reroute': (True, False), 'compress': (False, True), 'ignore': (False, False)})

    def test_wrong_then_right_counts_and_scores_exactly(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        st, run = s.runs[a].state, s.runs[a]
        s.respond('compress')                 # 잘못된 대응(비용 10)
        s.advance_time(10); s.advance_time(10)  # 중단 20분
        s.respond('reroute')                  # 올바른 대응(비용 15)
        self.assertEqual((st.response_attempts, st.cost_penalty, st.downtime), (2, 25, 20))
        finish_job(s, a)
        self.assertEqual(st.score, expected_score(run))
        self.assertEqual(st.score, 80+15-25-2+10-(run.terms.get('penalty') or 0))
        self.assertEqual(s.story.chapter3.records[str(a)]['responses'], ['compress', 'reroute'])
        self.assertEqual(s.story.chapter3.records[str(a)]['attempts'], 2)

    def test_three_wrong_responses_fail_and_return_resources(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        st = s.runs[a].state
        for _ in range(3):
            s.respond('compress')
        self.assertEqual((st.phase, st.succeeded, st.response_attempts, st.cost_penalty), ('finished', False, 3, 30))
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))
        self.assertEqual(s.servers.allocations, {})
        self.assertEqual(st.score, expected_score(s.runs[a]))
        self.assertEqual(s.story.chapter3.records[str(a)]['final'], 'failed')

    def test_wrong_response_keeps_the_mission_open_while_chances_remain(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        s.respond('ignore')
        self.assertEqual(s.runs[a].state.phase, 'paused')
        self.assertTrue(s.runs[a].state.allocated)
        self.assertIsNone(s.story.chapter3.records[str(a)]['final'])

    def test_respond_requires_opening_the_diagnosis_first(self):
        s, a = incident_a()
        st = s.runs[a].state
        self.assertTrue(s.chapter3_response_locked(s.runs[a]))
        with self.assertRaises(ValueError):
            s.respond('reroute')
        self.assertEqual((st.phase, st.response_attempts, st.response_log, st.cost_penalty), ('incident', 0, [], 0))
        s.view_network_diagnosis(a)
        self.assertFalse(s.chapter3_response_locked(s.runs[a]))


class FailureRulesTests(unittest.TestCase):
    def test_no_response_follows_the_existing_60_minute_rule(self):
        s, a = incident_a()
        st = s.runs[a].state
        for index in range(5):
            s.advance_time(10)
            self.assertEqual(st.phase, 'incident', index)
        s.advance_time(10)
        self.assertEqual((st.phase, st.succeeded, st.downtime), ('finished', False, 60))
        self.assertIn('60분', st.result_text)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))
        self.assertEqual(st.score, expected_score(s.runs[a]))
        self.assertEqual(s.runs[a].request['status'], 'completed')
        self.assertFalse(s.runs[a].followup_closed)                  # 후속 대응(재처리/최종 보고)은 기존 규칙대로 남습니다.

    def test_retry_after_failure_keeps_the_incident_record_and_scenario(self):
        s, a = incident_a()
        for _ in range(6):
            s.advance_time(10)
        run = s.runs[a]
        s.retry('performance')
        self.assertEqual(run.state.scenario, 'ch3_path')
        self.assertIsNone(run.state.incident_at)                      # 재처리에서는 같은 장애를 재현하지 않습니다.
        self.assertEqual(s.story.chapter3.records[str(a)]['final'], 'failed')
        self.assertEqual(s.story.chapter3.records[str(a)]['responses'], [])
        finish_job(s, a)
        self.assertTrue(run.state.succeeded)
        self.assertEqual(s.story.chapter3.records[str(a)]['final'], 'failed')     # 기록은 지워지지 않습니다.
        self.assertEqual(len(s.story.chapter3.request_ids), 2)                     # 재처리 후 완료하면 다음 미션이 열립니다.

    def test_resources_are_held_during_the_job_and_returned_after(self):
        s = practice3()
        a = start_a(s)
        plan = s.runs[a].state.plans['performance']
        self.assertEqual((s.center.gpu_used, s.center.power_used), (plan['gpu'], plan['power']))
        self.assertTrue(ledger_matches_center(s))
        to_incident(s, a)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (plan['gpu'], plan['power']))   # 장애 중에도 점유
        self.assertTrue(ledger_matches_center(s))
        s.view_network_diagnosis(a); s.respond('reroute')
        finish_job(s, a)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))
        self.assertEqual(s.servers.allocations, {})
        self.assertTrue(ledger_matches_center(s))

    def test_report_failure_is_still_the_existing_final_report(self):
        s, a = incident_a()
        s.report_failure()
        self.assertTrue(s.runs[a].followup_closed)
        self.assertEqual(s.center.gpu_used, 0)


class StoryFlowTests(unittest.TestCase):
    def test_steps_advance_only_with_real_actions(self):
        s = practice3()
        c3 = s.story.chapter3
        self.assertEqual(c3.step, 'briefing')
        a = c3.request_ids[0]
        s.read_conversation(a); s.selected_id = a
        s.choose_plan('performance')                                  # 브리핑 확인 전 시작해도 단계는 앞서가지 않습니다.
        self.assertEqual(c3.step, 'briefing')
        s.confirm_chapter3_briefing()
        self.assertEqual(c3.step, 'a_incident')                       # 이미 시작했으므로 start는 사실로 통과
        to_incident(s, a)
        self.assertEqual(c3.step, 'a_diagnose')                       # 장애가 났다고 진단한 것은 아닙니다.
        s.view_network_diagnosis(a)
        self.assertEqual(c3.step, 'a_respond')                        # 진단했다고 대응한 것은 아닙니다.
        s.respond('compress')
        self.assertEqual(c3.step, 'a_finish')
        s.view_network_diagnosis(a)
        s.respond('reroute')
        self.assertEqual(c3.step, 'a_finish')                         # 복구했어도 작업이 끝나기 전에는 미션 완료 아님
        finish_job(s, a)
        self.assertEqual(c3.step, 'b_start')
        self.assertEqual(len(c3.request_ids), 2)

    def test_briefing_and_dialogue_alone_do_not_start_anything(self):
        s = practice3()
        s.confirm_chapter3_briefing()
        s.mark_story_dialogue(s.story.dialogue_event)
        self.assertEqual(s.story.chapter3.step, 'a_start')
        self.assertIsNone(s.runs[s.story.chapter3.request_ids[0]].playthrough_id)
        self.assertEqual(s.center.gpu_used, 0)

    def test_mission_b_request_is_opened_only_after_mission_a_ends(self):
        s = practice3()
        a = start_a(s)
        self.assertEqual(len(s.story.chapter3.request_ids), 1)
        to_incident(s, a)
        self.assertEqual(len(s.story.chapter3.request_ids), 1)
        s.view_network_diagnosis(a); s.respond('reroute')
        self.assertEqual(len(s.story.chapter3.request_ids), 1)
        finish_job(s, a)
        b = s.story.chapter3.request_ids[1]
        self.assertEqual((s.runs[b].mission['country'], s.runs[b].state.scenario), ('미국', 'ch3_bw'))
        self.assertEqual(s.selected_id, b)
        with self.assertRaises(ValueError):
            s.view_network_diagnosis(b)                               # 아직 장애가 없습니다.

    def test_chapter_completes_only_after_both_missions_end(self):
        s, b = incident_b()
        c3 = s.story.chapter3
        self.assertFalse(c3.completed)
        with self.assertRaises(ValueError):
            s.chapter3_result()
        s.view_network_diagnosis(b); s.respond('compress')
        self.assertFalse(c3.completed)
        finish_job(s, b)
        self.assertTrue(c3.completed)
        self.assertEqual(c3.completed_steps, list(STEPS3))
        result = s.chapter3_result()
        self.assertEqual(result['mission'], 'success')
        self.assertEqual([j['kind'] for j in result['jobs']], ['path_down', 'bandwidth'])
        self.assertEqual([j['responses'] for j in result['jobs']], [['백업 경로 우회'], ['전송 데이터 압축']])
        self.assertTrue(result['released'])
        rows = dict(result['summary']['rows'][0])
        self.assertEqual((rows['복구 결과'], rows['선택 대응']), ('성공', '백업 경로 우회'))
        self.assertEqual(rows['운영 점수'], f'{s.runs[c3.request_ids[0]].state.score}점')

    def test_failed_mission_is_reported_as_failed_not_forced_to_success(self):
        s, b = incident_b()
        s.view_network_diagnosis(b)
        for _ in range(3):
            s.respond('reroute')
        s.report_failure()
        result = s.chapter3_result()
        self.assertEqual(result['mission'], 'failed')
        row = dict(result['summary']['rows'][1])
        self.assertEqual((row['복구 결과'], row['선택 대응']), ('실패', '백업 경로 우회 → 백업 경로 우회 → 백업 경로 우회'))
        self.assertIn('확정 점수 없음', row['운영 점수'])

    def test_unopened_diagnosis_is_reported_honestly(self):
        s, a = incident_a()
        for _ in range(6):
            s.advance_time(10)
        s.report_failure()
        self.assertEqual(s.story.chapter3.diagnosed, [])
        b = s.story.chapter3.request_ids[1]
        s.read_conversation(b); s.selected_id = b
        start_with_consent(s, 'performance')
        to_incident(s, b)
        s.view_network_diagnosis(b); s.respond('compress')
        finish_job(s, b)
        result = s.chapter3_result()
        rows = dict(result['summary']['rows'][0])
        self.assertIn('진단창을 열지 않음', rows['진단'])
        self.assertEqual((rows['선택 대응'], rows['복구 결과']), ('대응 없음', '실패'))
        self.assertEqual(result['mission'], 'failed')

    def test_mentor_guides_never_name_the_answer_before_the_result(self):
        for key, (_, lines) in GUIDES3.items():
            for line in lines:
                self.assertNotIn('우회', line.text, key)
                self.assertNotIn('압축', line.text, key)

    def test_feedback_describes_only_what_the_player_actually_did(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        s.respond('compress')
        key, kind, record = s.chapter3_pending_feedback()
        self.assertEqual((key, kind), (f'{a}:fail1', 'fail'))
        text = ' '.join(p.text for p in chapter3_feedback_pages(kind, record))
        self.assertIn('전송 데이터 압축', text)
        self.assertNotIn('우회', text)
        s.mark_chapter3_feedback_seen(key)
        self.assertIsNone(s.chapter3_pending_feedback())
        with self.assertRaises(ValueError):
            s.mark_chapter3_feedback_seen(key)
        s.respond('reroute')
        key2, kind2, record2 = s.chapter3_pending_feedback()
        self.assertEqual(kind2, 'recovered')
        text = ' '.join(p.text for p in chapter3_feedback_pages(kind2, record2))
        self.assertIn('앞서 시도한 압축', text)

    def test_recovery_feedback_does_not_invent_a_failed_compression(self):
        s, a = incident_a()
        s.view_network_diagnosis(a); s.respond('reroute')
        _, kind, record = s.chapter3_pending_feedback()
        text = ' '.join(p.text for p in chapter3_feedback_pages(kind, record))
        self.assertNotIn('압축', text)
        self.assertIn('교육용 구성', text)                            # 실제 네트워크로 일반화하지 않습니다.


def open_db(case, path):
    """테스트가 끝나면 연결을 닫아 Windows에서도 임시 폴더를 지울 수 있게 합니다."""
    db = Database(path)
    case.addCleanup(db.close)
    return db


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'ch3.db'

    def reopen(self, s):
        s.close()
        return GameSession(open_db(self, self.path), mode='story')

    def test_resume_mid_incident_keeps_kind_and_response_record(self):
        s = practice3(open_db(self, self.path))
        a = start_a(s)
        to_incident(s, a)
        s.view_network_diagnosis(a)
        s.respond('compress')
        before = vars(s.runs[a].state).copy()
        records = deepcopy(s.story.chapter3.records)
        s = self.reopen(s)
        st = s.runs[a].state
        self.assertEqual((st.incident_kind, st.response_log, st.response_attempts, st.phase, st.cost_penalty),
                         ('path_down', ['compress'], 1, 'paused', 10))
        for key in ('primary_up', 'rerouted', 'network_needed', 'network_available', 'backup_capacity', 'downtime'):
            self.assertEqual(getattr(st, key), before[key], key)
        self.assertEqual(s.story.chapter3.records, records)
        self.assertEqual(s.story.chapter3.diagnosed, [a])
        self.assertTrue(ledger_matches_center(s))
        self.assertFalse(s.chapter3_response_locked(s.runs[a]))       # 진단 기록도 유지
        s.respond('reroute')                                          # 이어서 올바르게 복구
        self.assertEqual(st.recovered_by, 'reroute')
        s = self.reopen(s)
        self.assertEqual(s.runs[a].state.response_log, ['compress', 'reroute'])
        self.assertEqual(s.story.chapter3.records[str(a)]['recovered_by'], 'reroute')

    def test_resume_between_missions_and_in_mission_b(self):
        s = practice3(open_db(self, self.path))
        a = start_a(s)
        play_a_correctly(s, a)
        s = self.reopen(s)
        c3 = s.story.chapter3
        self.assertEqual((c3.step, len(c3.request_ids)), ('b_start', 2))
        b = c3.request_ids[1]
        s.read_conversation(b); s.selected_id = b
        start_with_consent(s, 'economy')
        to_incident(s, b)
        s.view_network_diagnosis(b); s.respond('reroute')
        s = self.reopen(s)
        st = s.runs[b].state
        self.assertEqual((st.incident_kind, st.response_log, st.phase), ('bandwidth', ['reroute'], 'paused'))
        s.respond('compress')
        finish_job(s, b)
        self.assertTrue(s.story.chapter3.completed)
        s = self.reopen(s)
        self.assertEqual(s.chapter3_result()['mission'], 'success')

    def test_pending_feedback_survives_resume_and_is_shown_once(self):
        s = practice3(open_db(self, self.path))
        a = start_a(s)
        to_incident(s, a)
        s.view_network_diagnosis(a); s.respond('ignore')
        s = self.reopen(s)
        key, kind, _ = s.chapter3_pending_feedback()
        s.mark_chapter3_feedback_seen(key)
        s = self.reopen(s)
        self.assertIsNone(s.chapter3_pending_feedback())

    def test_save_failure_rolls_back_response_and_resources(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        st = s.runs[a].state
        snapshot = (vars(st).copy(), list(st.response_log), s.center.gpu_used, s.center.power_used,
                    deepcopy(s.story.chapter3.records), dict(s.servers.allocations), s.minute)
        with patch.object(Database, 'save_runtime', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                s.respond('reroute')
        self.assertEqual(vars(s.runs[a].state), snapshot[0])
        self.assertEqual((s.runs[a].state.response_log, s.center.gpu_used, s.center.power_used), snapshot[1:4])
        self.assertEqual(s.story.chapter3.records, snapshot[4])
        self.assertEqual(s.servers.allocations, snapshot[5])
        s.respond('reroute')                                          # 실패 후에도 정상적으로 다시 시도할 수 있습니다.
        self.assertEqual(s.runs[a].state.recovered_by, 'reroute')

    def test_save_failure_during_time_and_diagnosis_rolls_back(self):
        s, a = incident_a()
        with patch.object(Database, 'save_runtime', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                s.view_network_diagnosis(a)
            with self.assertRaises(RuntimeError):
                s.advance_time(10)
        self.assertEqual(s.story.chapter3.diagnosed, [])
        self.assertEqual(s.runs[a].state.downtime, 0)
        self.assertTrue(s.chapter3_response_locked(s.runs[a]))

    def test_save_failure_when_opening_mission_b_rolls_back_mission_a_finish(self):
        s, a = incident_a()
        s.view_network_diagnosis(a); s.respond('reroute')
        st = s.runs[a].state
        while st.remaining_minutes > 10:
            s.advance_time(10)
        minute, work = s.minute, st.work_done
        with patch.object(GameSession, '_receive', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                s.advance_time(10)
        self.assertEqual((s.minute, st.phase, st.work_done), (minute, 'running', work))      # 시간/작업/완료 모두 롤백
        self.assertEqual((len(s.runs), len(s.story.chapter3.request_ids)), (1, 1))
        self.assertGreater(s.center.gpu_used, 0)                                              # 자원은 아직 점유
        self.assertTrue(ledger_matches_center(s))
        s.advance_time(10)
        self.assertEqual((st.phase, len(s.story.chapter3.request_ids)), ('finished', 2))
        self.assertEqual(s.center.gpu_used, 0)

    def test_old_saves_without_chapter3_fields_still_load(self):
        s = practice3(open_db(self, self.path))
        s.close()
        db = open_db(self, self.path)
        saved = db.get_simulation()
        saved['story'].pop('practice_chapter', None)
        data = dict(saved['story'])
        self.assertNotIn('chapter2', data)
        db.close()
        # 이전 Chapter 2 연습 형식(practice_chapter/chapter3 필드 없음)은 그대로 읽혀야 합니다.
        legacy = StoryProgress.from_payload({'practice': True}, None, False)
        self.assertEqual((legacy.practice, legacy.practice_chapter, legacy.chapter3), (True, 2, None))
        self.assertNotIn('practice_chapter', legacy.payload())
        self.assertNotIn('chapter3', legacy.payload())

    def test_invalid_chapter3_payloads_are_rejected(self):
        with self.assertRaises(ValueError):
            StoryProgress(chapter3=Chapter3Progress([1]))                          # Chapter 2 없이 연습도 아닌 슬롯
        with self.assertRaises(ValueError):
            StoryProgress(practice=True, practice_chapter=3, chapter3=Chapter3Progress([1, 1]))
        with self.assertRaises(ValueError):
            Chapter3Progress([1], completed_steps=['a_start'])
        with self.assertRaises(ValueError):
            Chapter3Progress([1], completed_steps=list(STEPS3[:8]))               # 두 번째 요청 없이 B 단계
        ok = StoryProgress(practice=True, practice_chapter=3, chapter3=Chapter3Progress([1]))
        self.assertEqual(StoryProgress(**ok.payload()).chapter3.request_ids, [1])


class UnlockAndRetryTests(unittest.TestCase):
    def test_practice_slot_records_no_false_earlier_progress(self):
        s = practice3()
        st = s.story
        self.assertTrue(st.practice and st.practice_chapter == 3)
        self.assertIsNone(st.chapter2)
        self.assertFalse(st.chapter_completed or st.first_work_completed or st.tutorial_completed)
        self.assertEqual(st.completed_steps, [])
        self.assertEqual(len(s.runs), 1)
        self.assertEqual(s.chapter3_unlock_reason(), 'Chapter 2를 완료한 뒤 Chapter 3을 시작할 수 있습니다.')
        with self.assertRaises(ValueError):
            s.start_chapter3()
        with self.assertRaises(ValueError):
            s.start_chapter2()

    def test_chapter3_continues_only_from_a_successful_chapter2(self):
        s, jp, us = ready()
        start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
        self.assertEqual(s.chapter2_evaluation()['mission'], 'success')
        result = s.chapter2_result()
        before = deepcopy((result['jobs'], result['overall'], result['mission']))
        self.assertEqual(s.chapter3_unlock_reason(), '')
        a = s.start_chapter3()
        self.assertEqual(s.story.chapter3.request_ids, [a])
        self.assertEqual(s.runs[a].state.scenario, 'ch3_path')
        result = s.chapter2_result()
        self.assertEqual(before, deepcopy((result['jobs'], result['overall'], result['mission'])))   # Chapter 2 결과/점수 보존
        with self.assertRaises(ValueError):
            s.start_chapter3()
        s.confirm_chapter3_briefing(); s.read_conversation(a); s.selected_id = a
        s.choose_plan('performance')
        play_a_correctly(s, a)
        self.assertEqual(len(s.story.chapter3.request_ids), 2)

    def test_full_chain_from_chapter1_saves_and_resumes(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'chain.db'
        db = open_db(self, path)
        s = after_chapter1(db)
        s.start_chapter2()
        jp, us = s.story.chapter2.request_ids
        s.confirm_chapter2_briefing()
        start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
        a = s.start_chapter3()
        s.close()
        s = GameSession(open_db(self, path), mode='story')
        self.assertEqual((s.story.chapter3.request_ids, s.story.chapter2.completed, s.story.chapter_completed), ([a], True, True))
        self.assertEqual(s.chapter2_evaluation()['mission'], 'success')

    def test_failed_chapter2_never_unlocks_chapter3(self):
        s, jp, us = ready()
        s.selected_id = jp; s.reject_request('테스트 거절 사유')
        s.selected_id = us; s.reject_request('테스트 거절 사유')
        self.assertTrue(s.story.chapter2.completed)
        self.assertEqual(s.chapter2_evaluation()['mission'], 'failed')
        reason = s.chapter3_unlock_reason()
        self.assertIn('성공', reason)
        runs = len(s.runs)
        with self.assertRaises(ValueError):
            s.start_chapter3()
        self.assertIsNone(s.story.chapter3)
        self.assertEqual(len(s.runs), runs)

    def test_unfinished_chapter2_does_not_unlock(self):
        s, jp, us = ready()
        self.assertIn('완료', s.chapter3_unlock_reason())

    def test_new_attempt_uses_a_new_slot_and_preserves_the_old_one(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        slots = StorySlots(folder.name)
        first = slots.reserve_new()
        s = practice3(open_db(self, first))
        a = start_a(s)
        to_incident(s, a)
        s.view_network_diagnosis(a); s.respond('compress')
        s.close()
        digest = hashlib.sha256(first.read_bytes()).hexdigest()
        self.assertIn('Chapter 3 연습 진행 중', slots.describe(first))
        self.assertEqual(slots.chapter3_in_progress(), [first])
        second = slots.reserve_new()
        self.assertNotEqual(first, second)
        t = practice3(open_db(self, second), seed=7)
        self.assertEqual(len(t.runs), 1)
        self.assertEqual(t.story.chapter3.records, {})                              # 새 시도에는 이전 기록이 없습니다.
        t.close()
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), digest)   # 이전 슬롯은 그대로
        s = GameSession(open_db(self, first), mode='story')
        self.assertEqual(s.runs[a].state.response_log, ['compress'])
        self.assertEqual(set(slots.chapter3_in_progress()), {first, second})


class ExistingBehaviorTests(unittest.TestCase):
    def test_free_mode_incident_rules_are_unchanged(self):
        st = GameState(country='싱가포르')
        st.choose_plan('performance')
        st.trigger_incident()
        self.assertEqual((st.network_available, st.incident_kind, st.primary_up), (NETWORK_DURING_INCIDENT, None, True))
        st.resolve('reroute')                                     # 기존 규칙: 가용 +4, 필요량 이하이면 복구
        self.assertEqual((st.network_available, st.phase, st.recovered_by), (6, 'recovering', 'reroute'))
        other = GameState(country='싱가포르'); other.choose_plan('performance'); other.trigger_incident()
        other.resolve('compress')                                 # 기존 규칙: 필요량 -2 (5→3), 가용 2이므로 미복구
        self.assertEqual((other.network_needed, other.phase), (3, 'paused'))
        other.resolve('compress')
        self.assertEqual((other.network_needed, other.phase), (1, 'recovering'))   # 자유 운영은 압축만으로도 복구되던 기존 규칙
        self.assertEqual(other.link_ok, True)

    def test_free_mode_session_incident_is_random_and_not_diagnosed(self):
        s = GameSession(Database(':memory:'), mode='free', seed=3, incident_chance=1)
        run = s.current
        start_with_consent(s, 'performance')
        for _ in range(12):
            if run.state.phase == 'incident':
                break
            s.advance_time(10)
        self.assertEqual(run.state.phase, 'incident')
        self.assertIsNone(run.state.incident_kind)
        self.assertEqual(run.state.network_available, NETWORK_DURING_INCIDENT)
        s.advance_time(60)                                         # 자유 운영은 장애 뒤에도 시간 버튼이 끝까지 진행됩니다.
        self.assertEqual(run.state.phase, 'finished')
        self.assertIsNone(s.story)
        with self.assertRaises(ValueError):
            s.view_network_diagnosis()

    def test_chapter1_and_chapter2_never_get_scripted_incidents(self):
        s, jp, us = ready()
        start(s, jp, 'performance'); start(s, us, 'economy')
        self.assertTrue(all(r.state.incident_at is None for r in s.runs.values()))
        finish_all(s)
        self.assertTrue(all(r.state.incident_kind is None and not r.state.incident_occurred for r in s.runs.values()))

    def test_earlier_scenarios_are_not_changed(self):
        self.assertEqual(SCENARIOS['ch2_jp']['work'], 40)
        self.assertEqual(SCENARIOS['ch2_us_v2']['window'], ("우선 · 데이터 분석", 10, 100, 120))
        self.assertEqual(SCENARIOS['ch2_us']['window'], ("우선 · 데이터 분석", 40, 150, 240))
        self.assertNotIn('incident', SCENARIOS['ch2_jp'])

    def test_chapter3_scenarios_define_the_two_causes(self):
        self.assertEqual(SCENARIOS['ch3_path']['incident']['kind'], 'path_down')
        self.assertEqual(SCENARIOS['ch3_path']['incident']['available'], 0)
        bandwidth = SCENARIOS['ch3_bw']['incident']
        for plan in SCENARIOS['ch3_bw']['plans'].values():
            self.assertGreater(plan['network'], bandwidth['available'])           # 병목: 모든 모드의 필요량이 가용보다 큼
            self.assertLessEqual(plan['network']-2, bandwidth['available'])        # 한 번의 압축으로 해결 가능
        self.assertEqual(bandwidth['backup'], bandwidth['available'])             # 백업 경로는 용량을 더하지 못함
        for scenario in ('ch3_path', 'ch3_bw'):
            work, at = SCENARIOS[scenario]['work'], SCENARIOS[scenario]['incident']['at']
            self.assertTrue(0 < work*at < work)

    def test_resolving_without_incident_or_in_other_phases_is_still_rejected(self):
        st = GameState(); st.choose_plan('performance')
        with self.assertRaises(ValueError):
            st.resolve('reroute')


if __name__ == '__main__':
    unittest.main()
