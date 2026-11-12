"""v0.9-4a-1 심화 연수(Stage 1~5) 진행 엔진. Tk 창을 만들지 않는 검증.

정규 연수는 Chapter 3b를 성공한 정규 슬롯에서만 시작하고, Stage는 실제 학습 행동(구간 선택·명령 실행·답변)과
실제 게임 상태(복구)로만 통과합니다. 연습 슬롯은 정규 기록과 분리되고, 관찰·학습 행동은 시간·점수·자원을 바꾸지 않습니다.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database import Database
from lab_model import LAB_NETWORK, lab_mode, lab_support, observe
from session import GameSession
from story import StoryProgress
from story_slots import StorySlots
from training import STAGES, TrainingProgress, fact_statements
from tests.support import start_with_consent
from tests.test_chapter2 import after_chapter1, start, finish_all
from tests.test_chapter3 import open_db, to_incident, finish_job, play_a_correctly, practice3, ledger_matches_center
from tests.test_chapter3b import practice3b, start_job, to_fault, migrate_now, finish

SERVER = LAB_NETWORK['servers']['A']
NEAR = LAB_NETWORK['routers']['primary']['address']


def regular_after_3b(db=None, b3_choice='repair'):
    """Chapter 1 → 2 → 3a → 3b를 정규 슬롯에서 성공으로 마칩니다."""
    s = after_chapter1(db or Database(':memory:'))
    s.start_chapter2()
    jp, us = s.story.chapter2.request_ids
    s.confirm_chapter2_briefing()
    start(s, jp, 'performance'); start(s, us, 'economy'); finish_all(s)
    a = s.start_chapter3()
    s.confirm_chapter3_briefing()
    s.read_conversation(a); s.selected_id = a; s.choose_plan('performance')
    play_a_correctly(s, a)
    b = s.story.chapter3.request_ids[1]
    s.read_conversation(b); s.selected_id = b
    start_with_consent(s, 'performance')
    to_incident(s, b); s.view_network_diagnosis(b); s.respond('compress'); finish_job(s, b)
    assert s.chapter3_result()['mission'] == 'success'
    s.start_chapter3b()
    a3 = start_job(s)
    run = to_fault(s, a3)
    migrate_now(s, run); finish(s, a3)
    b3 = start_job(s, 1)
    runb = to_fault(s, b3)
    s.view_hardware_diagnosis(b3); s.begin_server_repair('A'); finish(s, b3)
    assert s.story.chapter3b.completed and s.chapter3b_result()['mission'] == 'success'
    return s


def lab_practice(db=None, seed=5):
    return GameSession(db or Database(':memory:'), mode='story', start_chapter='lab', seed=seed)


def to_training_incident(s):
    rid = s.training.rid
    s.read_conversation(rid); s.selected_id = rid
    if not s.runs[rid].state.allocated:
        s.choose_plan('performance')
    to_incident(s, rid)
    return rid


def pass_stage1(s):
    s.training_select_segment('primary-wan')
    s.training_answer('structure', 'impact', 'blocked')


def pass_stage2(s):
    s.training_command('choice', 'ping', 'tool')
    s.training_answer('tool', 'limit', 'icmp')


def pass_stage3(s):
    result = s.training_command('blocks', ('ping', '-c 3', SERVER), 'assemble')
    s.training_answer('assemble', 'received', result.facts['received'])


def pass_stage4(s):
    for line in (f'ping -c 2 {NEAR}', f'ping -c 3 {SERVER}', 'ip route'):
        s.training_command('terminal', line, 'terminal')
    answer = {key: truth for key, _, truth in fact_statements(s.training)}
    s.training_answer('terminal', 'facts', answer)


def stage5_evidence(s):
    s.training_command('terminal', f'ping -c 3 {SERVER}', 'independent')
    s.training_command('terminal', f'ping -c 2 {NEAR}', 'independent')


def finish_stage5(s):
    rid = s.training.rid
    stage5_evidence(s)
    s.training_answer('independent', 'cause', 'path_down')
    s.selected_id = rid
    s.respond('reroute')
    s.training_command('terminal', f'ping -c 3 {SERVER}', 'independent')


def play_regular(s, until=5):
    to_training_incident(s)
    steps = (pass_stage1, pass_stage2, pass_stage3, pass_stage4, finish_stage5)
    for index in range(until):
        steps[index](s)
        if index < 4 and index < until-1:
            s.start_next_stage()


def game_snapshot(s):
    return (s.minute, s.center.gpu_used, s.center.power_used, dict(s.servers.allocations), dict(s.servers.hardware),
            {rid: (deepcopy(vars(r.state) | {'center': None}), dict(r.request), deepcopy(r.proposals), deepcopy(r.terms))
             for rid, r in s.runs.items()})


class UnlockTests(unittest.TestCase):
    def test_successful_3b_regular_slot_unlocks_training_and_keeps_records(self):
        s = regular_after_3b()
        before = deepcopy(s.chapter3b_result()['summary']['table'])
        records = deepcopy((s.story.chapter3.records, s.story.chapter3b.records))
        self.assertEqual(s.training_unlock_reason(), '')
        rid = s.start_training()
        t = s.training
        self.assertEqual((t.request_ids, t.practice, t.current, t.completed), ([rid], False, 'structure', []))
        self.assertEqual((s.runs[rid].state.scenario, s.runs[rid].mission['country']), ('ch3_path', '싱가포르'))
        self.assertEqual(s.chapter3b_result()['summary']['table'], before)
        self.assertEqual((s.story.chapter3.records, s.story.chapter3b.records), records)
        self.assertEqual((s.story.ui_step, s.story.chapter_label, s.story.ui_done), ('t_structure', '심화 연수', False))
        with self.assertRaises(ValueError):
            s.start_training()

    def test_incomplete_failed_or_practice_chapters_never_unlock_regular_training(self):
        cases = [GameSession(Database(':memory:'), mode='story', seed=2), after_chapter1(Database(':memory:')),
                 practice3(), practice3b(), GameSession(Database(':memory:'), seed=2)]
        for s in cases:
            self.assertTrue(s.training_unlock_reason())
            runs = len(s.runs)
            with self.assertRaises(ValueError):
                s.start_training()
            self.assertEqual(len(s.runs), runs)
        # 3b 연습 슬롯을 성공해도 정규 연수는 열리지 않습니다(연습 결과를 정규 진급으로 인정하지 않음).
        s = practice3b()
        a = start_job(s); run = to_fault(s, a); migrate_now(s, run); finish(s, a)
        b = start_job(s, 1); to_fault(s, b); s.view_hardware_diagnosis(b); s.begin_server_repair('A'); finish(s, b)
        self.assertTrue(s.story.chapter3b.completed)
        self.assertIn('Engineering Lab 연습', s.training_unlock_reason())

    def test_failed_3b_does_not_unlock(self):
        s = regular_after_3b()
        with patch.object(GameSession, 'chapter3b_result', return_value={'mission': 'failed'}):
            self.assertIn('성공', s.training_unlock_reason())


class SequentialStageTests(unittest.TestCase):
    def setUp(self):
        self.s = regular_after_3b()
        self.s.start_training()

    def test_stages_unlock_in_order_only_after_real_actions(self):
        s = self.s
        t = s.training
        self.assertEqual([t.stage_state(k) for k in STAGES], ['current', 'locked', 'locked', 'locked', 'locked'])
        # 장애 전에는 끊어진 구간이 없어 Stage 1을 통과할 수 없습니다.
        rid = s.training.rid
        s.read_conversation(rid); s.selected_id = rid; s.choose_plan('performance')
        self.assertFalse(s.training_select_segment('primary-wan')[0])
        to_incident(s, rid)
        with self.assertRaises(ValueError):
            s.start_next_stage()
        with self.assertRaises(ValueError):
            s.training_answer('structure', 'impact', 'blocked')       # 구간 선택이 먼저
        self.assertFalse(s.training_select_segment('backup-wan')[0])
        self.assertTrue(s.training_select_segment('primary-wan')[0])
        self.assertFalse(t.current_passed())
        self.assertFalse(s.training_answer('structure', 'impact', 'gpu')[0])
        self.assertTrue(s.training_answer('structure', 'impact', 'blocked')[0])
        self.assertEqual((t.completed, t.current, t.can_advance()), (['structure'], 'structure', True))
        self.assertEqual(t.stage_state('tool'), 'locked')            # [다음 Stage 시작] 전에는 열리지 않음
        self.assertEqual(s.start_next_stage(), 'tool')
        self.assertEqual([t.stage_state(k) for k in STAGES], ['completed', 'current', 'locked', 'locked', 'locked'])
        pass_stage2(s); s.start_next_stage()
        pass_stage3(s); s.start_next_stage()
        pass_stage4(s); s.start_next_stage()
        self.assertEqual(t.completed, list(STAGES[:4]))
        finish_stage5(s)
        self.assertTrue(t.done)
        self.assertTrue(s.story.ui_done)
        result = s.training_result()
        self.assertEqual(len(result['rows']), 5)
        self.assertIn('숙련도 인증이 아닙니다', result['notice'])

    def test_locked_stage_actions_are_rejected_by_the_engine(self):
        s = self.s
        to_training_incident(s)
        before = deepcopy(s.story.payload())
        for action in (lambda: s.training_command('choice', 'ping', 'tool'),
                       lambda: s.training_command('blocks', ('ping', '-c 3', SERVER), 'assemble'),
                       lambda: s.training_command('terminal', 'ip route', 'terminal'),
                       lambda: s.training_command('terminal', 'ip route', 'independent'),
                       lambda: s.training_answer('tool', 'limit', 'icmp'),
                       lambda: s.training_answer('independent', 'cause', 'path_down'),
                       lambda: s.focus_training_stage('independent')):
            with self.assertRaises(ValueError):
                action()
        # 입력 방식이 Stage와 맞지 않아도 거부합니다(예: Stage 2에서 터미널 입력).
        with self.assertRaises(ValueError):
            s.training_command('terminal', 'ip route', 'tool')
        self.assertEqual(s.story.payload(), before)

    def test_viewing_or_opening_does_not_complete_a_stage(self):
        s = self.s
        rid = to_training_incident(s)
        before = deepcopy(s.story.payload())
        for _ in range(3):
            observe(s, rid)
            s.training_status()
            s.training_objective()
            lab_support(s, rid)
            s.save()
        self.assertEqual(s.story.payload(), before)
        self.assertEqual(s.training.completed, [])

    def test_wrong_choice_is_retryable_and_does_not_fail_the_mission(self):
        s = self.s
        rid = to_training_incident(s)
        pass_stage1(s); s.start_next_stage()
        phase = s.runs[rid].state.phase
        result = s.training_command('choice', 'ip addr', 'tool')
        self.assertTrue(result.ok)
        with self.assertRaises(ValueError):
            s.training_answer('tool', 'limit', 'icmp')                 # 목적에 맞는 도구부터
        s.training_command('choice', 'ip route', 'tool')
        self.assertFalse(s.training.answered('tool', 'choice'))
        s.training_command('choice', 'ping', 'tool')
        self.assertFalse(s.training_answer('tool', 'limit', 'cause')[0])
        self.assertTrue(s.training_answer('tool', 'limit', 'icmp')[0])
        self.assertEqual(s.training.completed, ['structure', 'tool'])
        self.assertEqual(s.runs[rid].state.phase, phase)
        self.assertGreaterEqual(s.training.answer('tool', 'choice')['attempts'], 3)

    def test_assembly_errors_and_valid_assembly(self):
        s = self.s
        to_training_incident(s)
        pass_stage1(s); s.start_next_stage(); pass_stage2(s); s.start_next_stage()
        bad = s.training_command('blocks', ('ip addr', '-c 3', SERVER), 'assemble')
        self.assertFalse(bad.ok)
        self.assertIn('Command "-c" is unknown', bad.output)
        missing = s.training_command('blocks', ('ping', '-c 3', None), 'assemble')
        self.assertIn('Destination address required', missing.output)
        no_count = s.training_command('blocks', ('ping', None, SERVER), 'assemble')
        self.assertTrue(no_count.ok)
        router = s.training_command('blocks', ('ping', '-c 1', NEAR), 'assemble')
        self.assertTrue(router.ok)
        self.assertIsNone(s.training.valid_assembly())               # 횟수 옵션 + 서버 주소가 필요
        with self.assertRaises(ValueError):
            s.training_answer('assemble', 'received', 0)
        good = s.training_command('blocks', ('ping', '-c 3', SERVER), 'assemble')
        self.assertEqual(good.facts['received'], 0)
        self.assertFalse(s.training_answer('assemble', 'received', 3)[0])
        self.assertTrue(s.training_answer('assemble', 'received', 0)[0])
        self.assertIn('assemble', s.training.completed)

    def test_terminal_inputs_are_recorded_and_facts_must_be_sorted(self):
        s = self.s
        to_training_incident(s)
        for step in (pass_stage1, pass_stage2, pass_stage3):
            step(s); s.start_next_stage()
        error = s.training_command('terminal', 'ping -c', 'terminal')
        self.assertFalse(error.ok)
        unknown = s.training_command('terminal', 'traceroute 10.0.0.20', 'terminal')
        self.assertFalse(unknown.ok)
        self.assertEqual(s.training_status()['statements'], [])
        with self.assertRaises(ValueError):
            s.training_answer('terminal', 'facts', {})
        s.training_command('terminal', f'ping -c 2 {NEAR}', 'terminal')
        s.training_command('terminal', f'ping -c 3 {SERVER}', 'terminal')
        self.assertEqual(s.training.terminal_evidence(), {'near': True, 'remote': True, 'route': False})
        s.training_command('terminal', 'ip route', 'terminal')
        lines = [r['line'] for r in s.training.records('terminal')]
        self.assertEqual(lines, ['ping -c', 'traceroute 10.0.0.20', f'ping -c 2 {NEAR}', f'ping -c 3 {SERVER}', 'ip route'])
        statements = fact_statements(s.training)
        self.assertEqual({truth for _, _, truth in statements}, {'confirmed', 'unknown'})
        self.assertTrue(all(len(item) == 2 for item in s.training_status()['statements']))   # 화면에는 정답을 주지 않음
        wrong = {key: 'confirmed' for key, _, _ in statements}
        self.assertFalse(s.training_answer('terminal', 'facts', wrong)[0])
        self.assertNotIn('terminal', s.training.completed)
        right = {key: truth for key, _, truth in statements}
        self.assertTrue(s.training_answer('terminal', 'facts', right)[0])
        self.assertIn('terminal', s.training.completed)

    def test_completed_stage_can_be_reviewed_without_changing_progress(self):
        s = self.s
        to_training_incident(s)
        pass_stage1(s); s.start_next_stage(); pass_stage2(s); s.start_next_stage()
        records = deepcopy(s.training.actions)
        review = s.training_command('choice', 'ip route', 'tool')       # 완료한 Stage 2 복습
        self.assertTrue(review.ok)
        self.assertEqual(s.training.actions, records)
        self.assertTrue(s.training.answered('tool', 'choice'))
        self.assertEqual(s.training.current, 'assemble')
        self.assertTrue(s.training_select_segment('primary-wan')[0])   # Stage 1 복습

    def test_stage5_requires_evidence_before_cause_and_action(self):
        s = self.s
        play_regular(s, until=4)
        s.start_next_stage()
        rid = s.training.rid
        s.selected_id = rid
        self.assertTrue(s.training_response_locked(s.runs[rid]))
        with self.assertRaises(ValueError):
            s.respond('reroute')                                        # 관측·판단 전 조치 차단(엔진)
        with self.assertRaises(ValueError):
            s.training_answer('independent', 'cause', 'path_down')     # 증거 전 판단 차단
        s.training_command('terminal', f'ping -c 3 {SERVER}', 'independent')
        self.assertFalse(s.training.stage5_evidence(rid)[0])            # 원격 관측 하나만으로는 부족
        s.training_command('terminal', 'ip route', 'independent')
        self.assertTrue(s.training.stage5_evidence(rid)[0])
        self.assertFalse(s.training_answer('independent', 'cause', 'server')[0])
        with self.assertRaises(ValueError):
            s.respond('reroute')
        self.assertTrue(s.training_answer('independent', 'cause', 'path_down')[0])
        self.assertEqual(s.training_response_locked(s.runs[rid]), '')
        s.respond('compress')                                           # 틀린 조치도 기존 엔진 규칙 그대로
        self.assertEqual(s.runs[rid].state.phase, 'paused')
        s.respond('reroute')
        self.assertEqual(s.runs[rid].state.recovered_by, 'reroute')
        self.assertNotIn('independent', s.training.completed)           # 재확인 전에는 통과 아님
        s.training_command('terminal', f'ping -c 3 {SERVER}', 'independent')
        self.assertTrue(s.training.stage5_verified(rid))
        self.assertTrue(s.training.done)

    def test_restart_incident_after_loss_keeps_passed_stages(self):
        s = self.s
        play_regular(s, until=4)
        s.start_next_stage()
        old = s.training.rid
        s.selected_id = old
        for _ in range(6):
            s.advance_time(10)                                          # 대응 없이 60분 → 기존 규칙으로 실패
        self.assertEqual(s.runs[old].state.phase, 'finished')
        self.assertEqual(s.training_incident(), 'lost')
        self.assertTrue(s.training_can_restart())
        rid = s.restart_training_incident()
        self.assertNotEqual(rid, old)
        self.assertEqual(s.training.completed, list(STAGES[:4]))
        self.assertIn(old, s.runs)
        to_training_incident(s)
        finish_stage5(s)
        self.assertTrue(s.training.done)


class ReadOnlyAndRollbackTests(unittest.TestCase):
    def test_learning_actions_do_not_change_time_score_or_resources(self):
        s = regular_after_3b()
        s.start_training()
        to_training_incident(s)
        before = game_snapshot(s)
        pass_stage1(s); s.start_next_stage(); pass_stage2(s); s.start_next_stage()
        pass_stage3(s); s.start_next_stage(); pass_stage4(s); s.start_next_stage()
        stage5_evidence(s)
        s.training_answer('independent', 'cause', 'path_down')
        self.assertEqual(game_snapshot(s), before)
        self.assertTrue(ledger_matches_center(s))

    def test_save_failure_rolls_back_stage_progress(self):
        s = regular_after_3b()
        s.start_training()
        to_training_incident(s)
        s.training_select_segment('primary-wan')
        before = deepcopy(s.story.payload())
        with patch.object(Database, 'save_simulation', side_effect=RuntimeError('disk full')):
            for action in (lambda: s.training_answer('structure', 'impact', 'blocked'),
                           lambda: s.training_select_segment('primary-wan')):
                with self.assertRaises(RuntimeError):
                    action()
        self.assertEqual(s.story.payload(), before)
        self.assertNotIn('structure', s.training.completed)
        s.training_answer('structure', 'impact', 'blocked')
        with patch.object(Database, 'save_simulation', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                s.start_next_stage()
        self.assertEqual(s.training.current, 'structure')
        s.start_next_stage()
        self.assertEqual(s.training.current, 'tool')

    def test_start_training_failure_leaves_slot_unchanged(self):
        s = regular_after_3b()
        runs = len(s.runs)
        with patch.object(Database, 'save_simulation', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                s.start_training()
        self.assertIsNone(s.story.training)
        self.assertEqual(len(s.runs), runs)


class PersistenceTests(unittest.TestCase):
    def test_progress_persists_across_resume_at_every_stage(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'train.db'
        s = regular_after_3b(open_db(self, path))
        s.start_training()
        to_training_incident(s)
        steps = (pass_stage1, pass_stage2, pass_stage3, pass_stage4)
        for step in steps:
            step(s)
            payload = s.story.payload()
            s.close()
            s = GameSession(open_db(self, path), mode='story')
            self.assertEqual(s.story.payload(), payload)
            s.start_next_stage()
        s.close()
        s = GameSession(open_db(self, path), mode='story')
        self.assertEqual((s.training.current, s.training.completed), ('independent', list(STAGES[:4])))
        self.assertTrue(s.training_response_locked(s.runs[s.training.rid]))
        finish_stage5(s)
        s.close()
        s = GameSession(open_db(self, path), mode='story')
        self.assertTrue(s.training.done and s.story.ui_done)
        self.assertEqual(s.story.chapter3b.completed, True)
        self.assertIn('심화 연수', StorySlots(folder.name).describe(path))

    def test_old_slots_without_training_field_load_unchanged(self):
        s = regular_after_3b()
        payload = s.story.payload()
        self.assertNotIn('training', payload)
        story = StoryProgress.from_payload(deepcopy(payload), s.runs[s.story.request_id], True)
        self.assertIsNone(story.training)
        self.assertEqual(story.payload(), payload)
        for maker in (practice3, practice3b, lambda: GameSession(Database(':memory:'), mode='story', start_chapter=2, seed=3)):
            self.assertNotIn('training', maker().story.payload())

    def test_invalid_training_payloads_are_rejected(self):
        with self.assertRaises(ValueError):
            TrainingProgress([1], current='tool')                        # 정규: Stage 1 통과 전 Stage 2 불가
        with self.assertRaises(ValueError):
            TrainingProgress([1], completed=['tool'])
        TrainingProgress([1], practice=True, current='independent', completed=['tool'])
        s = practice3b()
        data = s.story.payload()
        data['training'] = {'request_ids': [1]}
        with self.assertRaises(ValueError):
            StoryProgress(**data)                                        # 3b를 마치지 않은 슬롯에는 정규 연수가 없음


class PracticeTests(unittest.TestCase):
    def test_practice_slot_is_separate_and_open(self):
        s = lab_practice()
        st = s.story
        t = s.training
        self.assertTrue(st.practice and st.practice_chapter == 'lab' and t.practice)
        self.assertIsNone(st.chapter2 or st.chapter3 or st.chapter3b)
        self.assertFalse(st.chapter_completed or st.tutorial_completed)
        self.assertEqual(len(s.runs), 1)
        self.assertEqual(st.chapter_label, 'Engineering Lab 연습')
        self.assertTrue(all(t.stage_state(k) in ('current', 'open') for k in STAGES))
        self.assertEqual(lab_mode(s, t.rid)[0], 'practice')
        self.assertIn('독립 연습', s.training_unlock_reason())

    def test_practice_can_jump_but_records_only_practice(self):
        s = lab_practice()
        rid = to_training_incident(s)
        s.focus_training_stage('terminal')
        pass_stage4(s)
        self.assertEqual(s.training.completed, ['terminal'])
        self.assertTrue(s.training.practice)
        self.assertEqual(s.training_response_locked(s.runs[rid]), '')    # 연습은 조치 잠금 없음(자유 탐색)
        s.focus_training_stage('structure'); pass_stage1(s)
        self.assertEqual(s.training.completed, ['structure', 'terminal'])
        with self.assertRaises(ValueError):
            s.start_next_stage()                                         # 연습에는 정규 진급 버튼이 없음

    def test_practice_payload_cannot_masquerade_as_regular(self):
        s = lab_practice()
        data = s.story.payload()
        data['training'] = {**data['training'], 'practice': False}
        with self.assertRaises(ValueError):
            StoryProgress(**data)
        data = regular_after_3b().story.payload()
        data['training'] = {'request_ids': [99], 'practice': True}
        with self.assertRaises(ValueError):
            StoryProgress(**data)

    def test_practice_slot_resume(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'lab.db'
        s = lab_practice(open_db(self, path))
        to_training_incident(s)
        s.focus_training_stage('tool'); pass_stage2(s)
        payload = s.story.payload()
        s.close()
        s = GameSession(open_db(self, path), mode='story')
        self.assertEqual(s.story.payload(), payload)
        self.assertIn('Engineering Lab 연습', StorySlots(folder.name).describe(path))

    def test_early_recovery_in_practice_allows_new_incident(self):
        s = lab_practice()
        rid = to_training_incident(s)
        s.selected_id = rid
        s.respond('reroute')
        self.assertEqual(s.training_incident(), 'recovered')
        self.assertFalse(s.training_can_restart())              # 같은 고객의 열린 요청은 하나뿐: 작업을 먼저 마칩니다.
        # v0.9-4a-2: 우회 뒤에도 주 경로는 DOWN이므로 Stage 1은 이 사건으로 계속 진행할 수 있습니다.
        self.assertTrue(s.training_readiness('structure')['ready'])
        # 조치 전 증거가 필요한 Stage 5만 새 사건이 필요하고, 그 안내를 보여 줍니다.
        s.focus_training_stage('independent')
        self.assertEqual(s.training_readiness()['key'], 'finish')
        self.assertIn('작업 완료', s.training_objective())
        with self.assertRaises(ValueError):
            s.restart_training_incident()
        finish_job(s, rid)
        self.assertTrue(s.training_can_restart())
        new = s.restart_training_incident()
        self.assertEqual(s.training.request_ids, [rid, new])


class LabModeTests(unittest.TestCase):
    def test_lab_modes(self):
        s = practice3()
        a = s.story.chapter3.request_ids[0]
        self.assertEqual(lab_mode(s, a)[0], 'preview')
        s = regular_after_3b()
        old_a = s.story.chapter3.request_ids[0]
        self.assertTrue(lab_support(s, old_a))                            # 연수 전: 3b 슬롯은 미지원
        rid = s.start_training()
        self.assertEqual(lab_mode(s, rid)[0], 'training')
        reason = lab_support(s, old_a)
        self.assertIn(f'#{rid}', reason)
        self.assertTrue(lab_support(GameSession(Database(':memory:'), seed=1)))

    def test_preview_mode_cannot_run_learning_commands(self):
        s = practice3()
        with self.assertRaises(ValueError):
            s.training_command('terminal', 'ip route', 'terminal')


class StorylineAndWiringTests(unittest.TestCase):
    def test_storyline_dialogue_for_every_stage_uses_existing_characters(self):
        s = lab_practice()
        for key in STAGES:
            s.focus_training_stage(key)
            pages = [line.page() for line in s.story.dialogue]          # 알 수 없는 화자가 있으면 KeyError
            self.assertTrue(1 <= len(pages) <= 5)
            self.assertEqual(s.story.ui_step, 't_'+key)
            self.assertIn(f'Stage {STAGES.index(key)+1}', s.story.objective)
        s = regular_after_3b()
        s.start_training()
        self.assertEqual(s.story.dialogue_event, 't_structure')
        self.assertIn('기초 교육', s.story.dialogue[0].text)            # 기초 교육 종료 → 심화 연수 시작
        s.mark_story_dialogue('t_structure')
        self.assertIn('t_structure', s.story.dialogue_seen)

    def test_main_wires_training_entry_lock_and_menu(self):
        root = Path(__file__).resolve().parents[1]
        main = (root / 'main.py').read_text(encoding='utf-8')
        self.assertIn("start_next=self.begin_training if not self.session.training_unlock_reason() else None", main)
        self.assertIn("self.session.training_response_locked(self.session.current)", main)
        self.assertIn("lambda:self.new_story('lab')", main)
        self.assertIn("chapter in (2, 3, '3b', 'lab')", main)
        self.assertIn("and r['id'] in self.session.story.chapter3.request_ids", main)   # 연수 사건에는 3a 진단창을 쓰지 않음
        lab = (root / 'engineering_lab.py').read_text(encoding='utf-8')
        for call in ('training_command(', 'training_answer(', 'training_select_segment(', 'start_next_stage(',
                     'focus_training_stage('):
            self.assertIn(call, lab)
        # Lab의 학습 실행 경로는 엔진(training_command)을 거칩니다. 표시용 재계산만 run_command를 씁니다.
        self.assertNotIn("result = run_command(choice_command(name", lab)


if __name__ == '__main__':
    unittest.main()
