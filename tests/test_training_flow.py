"""v0.9-4a-2 Stage 진행 흐름·실습 준비 안내. Tk 창을 만들지 않는 검증.

Stage가 요구하는 상황(끊어진 구간)과 실제 시뮬레이션 상태가 일치해야 합니다.
- 미배정: '실습 준비 필요 · 고객 작업을 먼저 시작하세요.'
- 실행 중 · 장애 전: '작업 진행 중 · 장애 발생 후 진단을 시작합니다.'
- 장애 중: 'Stage 1 · 끊어진 네트워크 구간을 찾으세요.'
조회(준비 판정·상태·목표)는 배정·시간 진행·기록을 하지 않고, 실제 배정과 시간 진행은 기존 GameSession이 합니다.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database import Database
from lab_model import job_symptom, observe
from session import GameSession
from training import STAGES, BADGES
from tests.test_chapter3 import open_db, to_incident, finish_job
from tests.test_training import (regular_after_3b, lab_practice, to_training_incident, pass_stage1, pass_stage2,
                                 pass_stage3, pass_stage4, stage5_evidence, finish_stage5, game_snapshot, SERVER, NEAR)

SETUP = '실습 준비 필요 · 고객 작업을 먼저 시작하세요.'
WAITING = '작업 진행 중 · 장애 발생 후 진단을 시작합니다.'
STAGE1 = 'Stage 1 · 끊어진 네트워크 구간을 찾으세요.'
STAGE5_CTA = '지금까지 배운 방법을 이용해 직접 장애를 해결해 보세요.'


def allocate(s):
    rid = s.training.rid
    s.read_conversation(rid); s.selected_id = rid
    s.choose_plan('performance')
    return rid


def badges(s):
    return {item['key']: item['badge'] for item in s.training_status()['stages']}


def look(s):
    """화면이 하는 모든 조회를 여러 번 반복합니다(상태를 바꾸면 안 됨)."""
    for _ in range(3):
        s.training_readiness()
        for key in STAGES:
            s.training_readiness(key)
        s.training_status()
        s.training_objective()
        s.story_objective()


class ReadinessMatchesSimulationTests(unittest.TestCase):
    """연습 슬롯에 막 들어온 상태(D1 09:00, 미배정, 진행률 0%, 네트워크 정상)부터 장애까지."""

    def setUp(self):
        self.s = lab_practice()

    def test_unassigned_job_needs_setup_and_stage1_cannot_complete(self):
        s = self.s
        rid = s.training.rid
        r = s.training_readiness()
        self.assertEqual((r['key'], r['ready'], r['title'], r['action']), ('setup', False, SETUP, 'control'))
        self.assertIn(f'#{rid}', r['detail'])
        self.assertIn('실습 준비 필요', s.training_objective())
        payload, snapshot = deepcopy(s.story.payload()), game_snapshot(s)
        correct, text = s.training_select_segment('primary-wan')
        self.assertFalse(correct)
        self.assertIn(SETUP, text)
        with self.assertRaises(ValueError):
            s.training_answer('structure', 'impact', 'blocked')
        # 존재하지 않는 장애는 오답 시도로도 기록하지 않고, 조회·선택이 배정이나 시간 진행을 일으키지 않습니다.
        self.assertEqual(s.story.payload(), payload)
        self.assertEqual(game_snapshot(s), snapshot)
        self.assertFalse(s.runs[rid].state.allocated)
        self.assertEqual(s.minute, 9*60)                    # 시작 시각 D1 09:00 그대로
        self.assertEqual(s.training.completed, [])

    def test_running_without_fault_waits_for_incident(self):
        s = self.s
        rid = allocate(s)
        self.assertTrue(s.runs[rid].state.allocated)
        r = s.training_readiness()
        self.assertEqual((r['key'], r['ready'], r['title']), ('waiting', False, WAITING))
        self.assertIn('작업 진행 중', s.training_objective())
        s.advance_time(10)
        self.assertEqual(s.training_readiness()['key'], 'waiting')
        payload = deepcopy(s.story.payload())
        for segment in ('primary-wan', 'backup-wan', 'edge-primary'):
            correct, text = s.training_select_segment(segment)
            self.assertFalse(correct)
            self.assertIn(WAITING, text)
        self.assertEqual(s.story.payload(), payload)
        self.assertIsNone(s.training.answer('structure', 'segment'))

    def test_real_fault_opens_stage1_and_only_the_down_segment_passes(self):
        s = self.s
        rid = to_training_incident(s)
        r = s.training_readiness()
        self.assertEqual((r['key'], r['ready'], r['title'], r['action']), ('ready', True, STAGE1, 'tab'))
        self.assertIn('끊어진 네트워크 구간', s.training_objective())
        self.assertTrue(s.training_status()['structure_ready'])
        for wrong in ('backup-wan', 'edge-primary', 'edge-backup', 'gateway-servers'):
            correct, _ = s.training_select_segment(wrong)
            self.assertFalse(correct, wrong)
            self.assertFalse(s.training.answered('structure', 'segment'))
            self.assertNotIn('structure', s.training.completed)
        self.assertEqual(s.training.answer('structure', 'segment')['attempts'], 4)    # 실제 장애 중 오답만 시도로 기록
        # 서버 → 고객 작업 표시는 작업 배정(논리 관계)이지 네트워크 구간이 아닙니다. 고를 수도, 시도로 기록되지도 않습니다.
        with self.assertRaises(ValueError):
            s.training_select_segment('job-link')
        self.assertEqual(s.training.answer('structure', 'segment')['attempts'], 4)
        self.assertTrue(s.training_select_segment('primary-wan')[0])
        self.assertNotIn('structure', s.training.completed)                           # 영향 질문까지 답해야 통과
        self.assertTrue(s.training_answer('structure', 'impact', 'blocked')[0])
        self.assertIn('structure', s.training.completed)
        self.assertEqual(s.runs[rid].state.phase, 'incident')                         # 학습 행동은 장애를 고치지 않음

    def test_wrong_segment_feedback_does_not_name_the_answer(self):
        s = self.s
        to_training_incident(s)
        for segment in ('backup-wan', 'edge-primary'):
            _, text = s.training_select_segment(segment)
            self.assertNotIn('192.168.10.1', text)          # 정답 구간(주 경로 라우터 너머)을 말하지 않음
            self.assertNotIn('✕', text)

    def test_queries_never_assign_advance_or_record(self):
        s = self.s
        for prepare in (lambda: None, lambda: allocate(s), lambda: to_training_incident(s)):
            prepare()
            payload, snapshot = deepcopy(s.story.payload()), game_snapshot(s)
            look(s)
            self.assertEqual(s.story.payload(), payload)
            self.assertEqual(game_snapshot(s), snapshot)

    def test_finished_incident_needs_new_incident_not_stage1(self):
        s = self.s
        rid = to_training_incident(s)
        for _ in range(6):
            s.advance_time(10)                               # 대응 없이 60분 → 기존 규칙으로 실패
        self.assertEqual(s.runs[rid].state.phase, 'finished')
        r = s.training_readiness('structure')
        self.assertFalse(r['ready'])
        self.assertEqual(r['key'], 'restart')
        self.assertFalse(s.training_select_segment('primary-wan')[0])
        new = s.restart_training_incident()
        self.assertEqual(s.training_readiness()['key'], 'setup')
        to_training_incident(s)
        self.assertEqual(s.training.rid, new)
        self.assertTrue(s.training_select_segment('primary-wan')[0])


class StageMapAndNextStageTests(unittest.TestCase):
    """정규 연수: 준비 필요 → 진행 중 → 통과 완료 → 다음 Stage 진행 가능 → … → Stage 5 → 결과."""

    def setUp(self):
        self.s = regular_after_3b()
        self.s.start_training()

    def test_stage_map_states_and_unlock_hints(self):
        s = self.s
        self.assertEqual(badges(s), {'structure': 'setup', 'tool': 'locked', 'assemble': 'locked',
                                     'terminal': 'locked', 'independent': 'locked'})
        stages = {item['key']: item for item in s.training_status()['stages']}
        self.assertEqual(stages['tool']['badge_text'], '잠금 · Stage 1 통과 후')
        self.assertEqual(stages['independent']['hint'], 'Stage 4 통과 후')
        self.assertEqual(stages['structure']['badge_text'], BADGES['setup'])
        allocate(s)
        self.assertEqual(badges(s)['structure'], 'setup')
        to_incident(s, s.training.rid)
        self.assertEqual(badges(s)['structure'], 'active')
        pass_stage1(s)
        self.assertEqual(badges(s), {'structure': 'passed', 'tool': 'next', 'assemble': 'locked',
                                     'terminal': 'locked', 'independent': 'locked'})
        head = s.training_status()['headline']
        self.assertEqual((head['action'], head['stage'], head['chip']), ('next', 'tool', '진행 가능'))
        self.assertEqual(head['title'], 'Stage 2 · 진단 도구 선택')
        self.assertIn('[다음 Stage 시작]', s.training_objective())
        # '진행 가능' 표시만으로 열리지 않습니다. 잠금 규칙은 그대로이며 [다음 Stage 시작]이 실제로 엽니다.
        self.assertEqual(s.training.stage_state('tool'), 'locked')
        with self.assertRaises(ValueError):
            s.training_command('choice', 'ping', 'tool')
        self.assertEqual(s.start_next_stage(), 'tool')
        self.assertEqual(badges(s)['tool'], 'active')
        self.assertEqual(badges(s)['structure'], 'passed')

    def test_stage5_is_shown_as_available_after_stage4(self):
        s = self.s
        to_training_incident(s)
        for step in (pass_stage1, pass_stage2, pass_stage3):
            step(s); s.start_next_stage()
        pass_stage4(s)
        st = s.training_status()
        head = st['headline']
        self.assertEqual(head['title'], 'Stage 5 · 독립 진단')
        self.assertEqual(head['chip'], '진행 가능')
        self.assertIn(STAGE5_CTA, head['detail'])
        self.assertEqual(head['action'], 'next')
        five = next(item for item in st['stages'] if item['key'] == 'independent')
        self.assertEqual((five['badge'], five['badge_text']), ('next', '▶ 진행 가능'))
        self.assertIn('Stage 5 · 독립 진단', s.training_objective())
        self.assertEqual(s.start_next_stage(), 'independent')
        r = s.training_readiness()
        self.assertTrue(r['ready'])
        self.assertIn(STAGE5_CTA, r['title'])

    def test_stages_1_to_5_connect_without_gaps_and_end_in_result(self):
        s = self.s
        rid = to_training_incident(s)
        steps = (pass_stage1, pass_stage2, pass_stage3, pass_stage4)
        for index, step in enumerate(steps):
            self.assertEqual(s.training_status()['headline']['action'], 'tab')      # 지금 할 일: 해당 탭에서 진행
            step(s)
            self.assertEqual(s.training_status()['headline']['action'], 'next')
            self.assertEqual(s.start_next_stage(), STAGES[index+1])
        stage5_evidence(s)
        self.assertTrue(s.training_answer('independent', 'cause', 'path_down')[0])
        r = s.training_readiness()
        self.assertEqual((r['key'], r['action']), ('act', 'control'))              # 조치는 관제실 기존 대응
        self.assertEqual(s.training_response_locked(s.runs[rid]), '')
        s.selected_id = rid
        s.respond('reroute')
        self.assertEqual(s.training_readiness()['key'], 'verify')
        self.assertFalse(s.training.done)
        s.training_command('terminal', f'ping -c 3 {SERVER}', 'independent')
        st = s.training_status()
        self.assertTrue(st['done'])
        self.assertEqual((st['headline']['action'], st['headline']['chip']), ('result', '연수 완료'))
        self.assertTrue(all(badge == 'passed' for badge in badges(s).values()))
        self.assertTrue(s.story.ui_done)
        self.assertEqual(len(s.training_result()['rows']), 5)

    def test_stage1_review_cannot_reveal_the_fault_during_stage5(self):
        s = self.s
        to_training_incident(s)
        for step in (pass_stage1, pass_stage2, pass_stage3, pass_stage4):
            step(s); s.start_next_stage()
        payload = deepcopy(s.story.payload())
        correct, text = s.training_select_segment('primary-wan')
        self.assertFalse(correct)
        self.assertIn('Stage 5', text)
        self.assertNotIn('DOWN', text)
        self.assertEqual(s.story.payload(), payload)
        finish_stage5(s)
        self.assertTrue(s.training.done)
        self.assertTrue(s.training_select_segment('primary-wan')[0])   # 완료 뒤 복습은 다시 가능(우회 후에도 주 경로 DOWN)

    def test_regular_locks_are_kept(self):
        s = self.s
        to_training_incident(s)
        with self.assertRaises(ValueError):
            s.start_next_stage()
        with self.assertRaises(ValueError):
            s.focus_training_stage('terminal')
        for stage in ('tool', 'assemble', 'terminal', 'independent'):
            self.assertEqual(badges(s)[stage], 'locked')
        self.assertTrue(s.training_response_locked(s.runs[s.training.rid]))


class Stage5VerificationOrderTests(unittest.TestCase):
    def test_reply_before_the_fault_is_not_a_post_fix_verification(self):
        s = lab_practice()
        rid = allocate(s)
        s.focus_training_stage('independent')
        self.assertEqual(s.training_readiness()['key'], 'waiting')
        before = s.training_command('terminal', f'ping -c 3 {SERVER}', 'independent')
        self.assertEqual(before.facts['received'], 3)                  # 장애 전에는 응답이 옴
        to_incident(s, rid)
        stage5_evidence(s)
        self.assertTrue(s.training_answer('independent', 'cause', 'path_down')[0])
        s.selected_id = rid
        s.respond('reroute')
        self.assertFalse(s.training.stage5_verified(rid))              # 장애 전 응답은 재확인이 아님
        self.assertNotIn('independent', s.training.completed)
        s.training_command('terminal', f'ping -c 3 {SERVER}', 'independent')
        self.assertTrue(s.training.stage5_verified(rid))
        self.assertIn('independent', s.training.completed)

    def test_existing_regular_stage5_flow_still_passes(self):
        s = regular_after_3b()
        s.start_training()
        to_training_incident(s)
        for step in (pass_stage1, pass_stage2, pass_stage3, pass_stage4):
            step(s); s.start_next_stage()
        finish_stage5(s)
        self.assertTrue(s.training.done)


class PracticeFlowTests(unittest.TestCase):
    def test_practice_guides_to_next_unpractised_stage_without_regular_records(self):
        s = lab_practice()
        to_training_incident(s)
        pass_stage1(s)
        st = s.training_status()
        head = st['headline']
        self.assertEqual((head['action'], head['stage']), ('focus', 'tool'))
        self.assertIn('다음 연습', head['title'])
        self.assertEqual(badges(s), {'structure': 'passed', 'tool': 'open', 'assemble': 'open',
                                     'terminal': 'open', 'independent': 'open'})
        self.assertNotIn('next', badges(s).values())                   # 연습에는 정규 진급 표시가 없음
        with self.assertRaises(ValueError):
            s.start_next_stage()
        s.focus_training_stage('terminal'); pass_stage4(s)
        self.assertEqual(s.training_status()['headline']['stage'], 'independent')   # 현재 다음의 미체험 Stage
        s.focus_training_stage('independent')
        self.assertEqual(s.training.next_open(), 'tool')                            # 끝까지 가면 앞쪽부터 순환
        s.focus_training_stage('tool'); pass_stage2(s)
        s.focus_training_stage('assemble'); pass_stage3(s)
        s.focus_training_stage('independent'); finish_stage5(s)
        st = s.training_status()
        self.assertTrue(st['done'])
        self.assertEqual(st['headline']['chip'], '연습 완료')
        self.assertTrue(s.training.practice and s.story.practice)
        self.assertIn('독립 연습', s.training_unlock_reason())           # 연습 결과로 정규 연수가 열리지 않음
        self.assertIsNone(s.story.chapter3b)

    def test_practice_tool_stages_say_when_output_is_normal_state(self):
        s = lab_practice()
        s.focus_training_stage('tool')
        r = s.training_readiness()
        self.assertTrue(r['ready'])
        self.assertIn('정상 상태의 결과', r['detail'])
        to_training_incident(s)
        self.assertNotIn('정상 상태의 결과', s.training_readiness()['detail'])


class PersistenceAndRollbackTests(unittest.TestCase):
    def test_states_survive_resume(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'flow.db'
        s = regular_after_3b(open_db(self, path))
        s.start_training()

        def reopen(s):
            payload, status = s.story.payload(), s.training_status()
            s.close()
            s = GameSession(open_db(self, path), mode='story')
            self.assertEqual(s.story.payload(), payload)
            again = s.training_status()
            for key in ('readiness', 'headline', 'stages'):
                self.assertEqual(again[key], status[key], key)
            return s

        s = reopen(s)
        self.assertEqual(s.training_readiness()['key'], 'setup')
        allocate(s); s = reopen(s)
        self.assertEqual(s.training_readiness()['key'], 'waiting')
        to_incident(s, s.training.rid); s = reopen(s)
        self.assertEqual(s.training_readiness()['key'], 'ready')
        pass_stage1(s); s = reopen(s)
        self.assertEqual(badges(s)['tool'], 'next')
        s.start_next_stage(); s = reopen(s)
        self.assertEqual(badges(s)['tool'], 'active')
        s.close()

    def test_save_failure_rolls_back_and_not_ready_selection_never_saves(self):
        s = lab_practice()
        allocate(s)
        payload = deepcopy(s.story.payload())
        with patch.object(Database, 'save_simulation', side_effect=RuntimeError('disk full')):
            self.assertFalse(s.training_select_segment('primary-wan')[0])     # 장애 전: 저장 시도 자체가 없음
            look(s)
        self.assertEqual(s.story.payload(), payload)
        to_incident(s, s.training.rid)
        payload = deepcopy(s.story.payload())
        with patch.object(Database, 'save_simulation', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                s.training_select_segment('primary-wan')
        self.assertEqual(s.story.payload(), payload)
        self.assertIsNone(s.training.answer('structure', 'segment'))
        self.assertTrue(s.training_select_segment('primary-wan')[0])


class SituationTextMatchesSessionTests(unittest.TestCase):
    """수동 플레이 반영: 작업이 이미 끝났는데 '고객 작업이 멈췄습니다'라고 안내하지 않습니다."""

    def test_job_symptom_follows_the_real_job_state(self):
        s = lab_practice()
        rid = s.training.rid
        self.assertIn('아직 배정되지 않았습니다', job_symptom(observe(s, rid)))
        allocate(s)
        self.assertIn('정상 실행 중', job_symptom(observe(s, rid)))
        to_incident(s, rid)
        self.assertIn('멈췄습니다', job_symptom(observe(s, rid)))
        s.selected_id = rid
        s.respond('reroute')
        self.assertNotIn('멈췄', job_symptom(observe(s, rid)))
        finish_job(s, rid)
        self.assertTrue(s.runs[rid].state.succeeded)
        text = job_symptom(observe(s, rid))
        self.assertIn('정상 완료', text)
        self.assertNotIn('멈췄', text)

    def test_stage4_after_completed_job_says_completed_and_still_judges_real_actions(self):
        s = lab_practice()
        rid = to_training_incident(s)
        s.selected_id = rid
        s.respond('reroute')
        finish_job(s, rid)
        s.focus_training_stage('terminal')
        r = s.training_readiness()
        self.assertTrue(r['ready'])
        self.assertIn('정상 완료', r['detail'])
        self.assertIn('백업 경로로 우회', r['detail'])
        self.assertNotIn('멈췄', r['detail'] + r['title'])
        self.assertNotIn('terminal', s.training.completed)                 # 안내만으로는 완료되지 않음
        pass_stage4(s)                                                      # 실제 관측·분류를 해야 통과
        self.assertIn('terminal', s.training.completed)

    def test_lab_screen_uses_state_text_instead_of_fixed_stop_message(self):
        lab = (Path(__file__).resolve().parents[1] / 'engineering_lab.py').read_text(encoding='utf-8')
        self.assertNotIn("'고객 작업이 멈췄습니다.", lab)
        self.assertNotIn("'증상: 싱가포르 고객의 작업이 멈췄습니다.", lab)
        self.assertIn('job_symptom(self.obs)', lab)


class Stage5NewIncidentGuidanceTests(unittest.TestCase):
    def test_completed_incident_explains_why_and_points_to_existing_restart(self):
        s = lab_practice()
        rid = to_training_incident(s)
        s.selected_id = rid
        s.respond('reroute')                                                # 증거를 모으기 전에 조치
        s.focus_training_stage('independent')
        r = s.training_readiness()
        self.assertEqual((r['key'], r['action']), ('finish', 'control'))    # 요청이 아직 열려 있음
        self.assertIn('이미 조치', r['reason'])
        self.assertIn('현재 요청을 마친 뒤', r['detail'])
        finish_job(s, rid)
        completed = list(s.training.completed)
        r = s.training_readiness()
        self.assertEqual((r['key'], r['ready'], r['action']), ('restart', False, 'restart'))
        self.assertIn('정상 완료', r['reason'])
        self.assertIn('Stage 5는 경로가 끊긴 상태', r['reason'])
        self.assertIn('[연수 사건 다시 받기]', r['detail'])
        self.assertIn('정상 완료', s.training_objective())
        head = s.training_status()['headline']
        self.assertEqual(head['action'], 'restart')                         # 하단 주요 행동 = 기존 [연수 사건 다시 받기]
        self.assertEqual(s.training.completed, completed)
        new = s.restart_training_incident()                                 # 기존 기능 재사용
        self.assertEqual(s.training.request_ids, [rid, new])
        self.assertEqual(s.training.completed, completed)                   # 다시 받는 것만으로 완료되는 Stage 없음
        self.assertNotIn('independent', s.training.completed)
        self.assertEqual(s.training_readiness()['key'], 'setup')
        to_incident(s, (allocate(s)))
        self.assertTrue(s.training_readiness()['ready'])

    def test_regular_stage5_after_failed_incident(self):
        s = regular_after_3b()
        s.start_training()
        to_training_incident(s)
        for step in (pass_stage1, pass_stage2, pass_stage3, pass_stage4):
            step(s); s.start_next_stage()
        rid = s.training.rid
        s.selected_id = rid
        for _ in range(6):
            s.advance_time(10)                                              # 기존 규칙: 대응 없이 60분 → 실패
        r = s.training_readiness()
        self.assertEqual(r['key'], 'restart')
        self.assertIn('실패로 종료', r['reason'])
        self.assertIn('Stage 5', r['reason'])
        self.assertEqual(s.training.current, 'independent')                 # 정규 순서·잠금은 그대로
        self.assertEqual(s.training.completed, list(STAGES[:4]))


class WiringTests(unittest.TestCase):
    def test_job_relation_is_not_a_network_link(self):
        lab = (Path(__file__).resolve().parents[1] / 'engineering_lab.py').read_text(encoding='utf-8')
        self.assertNotIn("'job-link'", lab)                                  # 선택 가능한 네트워크 구간 아님
        self.assertIn("tags=('job-relation',)", lab)                         # 'link' 태그·pick 태그 없음
        self.assertIn('logical=True', lab)                                   # 고객 작업 상자는 점선 테두리(논리 대상)
        self.assertNotIn("nodes['job']]", lab)                               # 흐름 점은 서버까지만


    def test_lab_screen_uses_readiness_and_segment_pick_tags(self):
        root = Path(__file__).resolve().parents[1]
        lab = (root / 'engineering_lab.py').read_text(encoding='utf-8')
        for text in ("'pick:'+seg_id", "PICKABLE = ('edge-primary', 'primary-wan'", "state='disabled', tags=('packet',)",
                     "st['structure_ready']", "def conceal_break", "self.on_result()", "strong=True",
                     "st['headline']", "def _task_prepare"):
            self.assertIn(text, lab)
        # 화면은 세션의 상태 변경 메서드로 배정·시간 진행을 하지 않습니다(관제실에서만).
        for call in ('advance_time(', 'choose_plan(', 'respond(', '.save('):
            self.assertNotIn('self.session.'+call, lab)


if __name__ == '__main__':
    unittest.main()
