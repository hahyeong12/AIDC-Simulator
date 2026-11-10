"""v0.9-3a-2: 네트워크 장애 복구 후 정상 운영 복귀. Tk 창을 만들지 않는 검증.

장애 해결(복구 준비 → 정상 실행)과 고객 작업 완료는 별개의 사건이며, 복구 준비는 가상 시간으로만 백그라운드 진행됩니다.
"""
from copy import deepcopy
from pathlib import Path
import re
import tempfile
import unittest

from database import Database
from session import GameSession
from tests.support import start_with_consent
from tests.test_chapter3 import (practice3, start_a, to_incident, finish_job, incident_a, incident_b,
                                 open_db, ledger_matches_center)

ROOT = Path(__file__).resolve().parent.parent


def recovered_a():
    s, a = incident_a()
    s.view_network_diagnosis(a)
    s.respond('reroute')
    return s, a


def free_with_two_customers():
    s = GameSession(Database(':memory:'), mode='free', seed=3, incident_chance=0)
    first = s.selected_id
    second = s.deliver_next_request()
    return s, first, second


class StateSeparationTests(unittest.TestCase):
    def test_four_states_are_distinguished(self):
        s, a = incident_a()
        st = s.runs[a].state
        self.assertEqual(st.phase, 'incident')                                  # ① 장애 · 작업 중단
        self.assertEqual(s.recovery_status_lines(s.runs[a]), [])
        s.view_network_diagnosis(a); s.respond('reroute')
        lines = s.recovery_status_lines(s.runs[a])                              # ② 대응 성공 · 복구 준비 중
        self.assertEqual((st.phase, st.recovery_left), ('recovering', 10))
        self.assertEqual(lines[0], f'{s.runs[a].mission["company_name"]} | 복구 준비 중')
        self.assertIn('복구 준비: 10분 남음', lines); self.assertTrue(any('네트워크 조치: 성공' in l for l in lines))
        self.assertIn(f'작업 진행률: {st.progress:.0f}%', lines)
        s.advance_time(10)                                                      # ③ 정상 실행 중
        lines = s.recovery_status_lines(s.runs[a])
        self.assertEqual(st.phase, 'running')
        self.assertTrue(lines[0].endswith('정상 실행 중')); self.assertIn('네트워크: 정상', lines)
        self.assertNotIn('복구 준비: 0분 남음', lines)
        finish_job(s, a)                                                        # ④ 고객 작업 완료는 별개
        self.assertEqual(s.recovery_status_lines(s.runs[a]), [])
        self.assertTrue(st.succeeded)

    def test_failed_response_stays_in_incident_state(self):
        s, a = incident_a()
        s.view_network_diagnosis(a); s.respond('compress')
        st = s.runs[a].state
        self.assertEqual((st.phase, st.recovered_by), ('paused', None))
        self.assertEqual(s.recovery_status_lines(s.runs[a]), [])
        self.assertEqual(s.story_objective(), s.story.objective)               # 복구 목표로 바뀌지 않음
        self.assertFalse(s.chapter3_card(a)['can_advance'])

    def test_recovery_does_not_complete_the_customer_job_or_open_mission_b(self):
        s, a = recovered_a()
        self.assertEqual(len(s.story.chapter3.request_ids), 1)
        s.advance_time(10)
        self.assertEqual(len(s.story.chapter3.request_ids), 1)                  # 네트워크만 복구됐다고 B가 시작되지 않음
        self.assertEqual((s.runs[a].state.phase, s.runs[a].request['status']), ('running', 'operating'))
        finish_job(s, a)
        self.assertEqual(len(s.story.chapter3.request_ids), 2)


class ReturnToOperationsTests(unittest.TestCase):
    def test_card_and_status_are_read_only_so_player_can_leave_without_advancing(self):
        s, a = recovered_a()
        st = s.runs[a].state
        before = (s.minute, st.work_done, st.recovery_left, st.score, st.cost_penalty, s.center.gpu_used, s.center.power_used)
        card = s.chapter3_card(a)
        s.recovery_status_lines(s.runs[a]); s.story_objective()
        self.assertEqual(dict(card['rows'])['상태'], '복구 준비 중 · 10분')
        self.assertTrue(card['can_advance'])                                    # 선택 기능일 뿐
        self.assertEqual(before, (s.minute, st.work_done, st.recovery_left, st.score, st.cost_penalty,
                                  s.center.gpu_used, s.center.power_used))
        s.select(a)                                                            # 다른 화면 조작도 자유
        self.assertEqual(st.phase, 'recovering')

    def test_optional_ten_minute_button_uses_the_normal_engine(self):
        s, a = recovered_a()
        st = s.runs[a].state
        work, penalty = st.work_done, st.cost_penalty
        s.advance_time(10)
        self.assertEqual((st.phase, st.work_done, st.cost_penalty), ('running', work, penalty))   # 점수 요소 불변
        self.assertEqual(dict(s.chapter3_card(a)['rows'])['상태'], '정상 실행 중')
        self.assertFalse(s.chapter3_card(a)['can_advance'])

    def test_objective_follows_recovery_then_running(self):
        s, a = recovered_a()
        self.assertIn('복구 준비(10분 남음)', s.story_objective())
        self.assertNotIn('복구 준비 10분 버튼', s.story_objective())
        s.advance_time(10)
        self.assertIn('남은 고객 작업', s.story_objective())
        self.assertNotIn('복구 준비', s.story_objective())
        finish_job(s, a)
        self.assertEqual(s.story_objective(), s.story.objective)

    def test_time_buttons_of_any_size_work_during_recovery(self):
        for step in (10, 30, 60):
            with self.subTest(step=step):
                s, a = recovered_a()
                st = s.runs[a].state
                work = st.work_done
                s.advance_time(step)
                self.assertEqual(st.work_done, min(st.work_total, work + (step-10)))   # 복구 10분 + 나머지는 실제 작업
                self.assertEqual(st.phase, 'finished' if st.work_done >= st.work_total else 'running')

    def test_delay_notice_is_not_required_when_no_real_delay_risk(self):
        s, a = recovered_a()
        self.assertEqual(s.delay_reason(s.runs[a]), '')
        self.assertFalse(s.can_notify_delay(s.runs[a]))

    def test_source_no_longer_offers_network_diagnosis_while_running_or_recovering(self):
        src = (ROOT / 'main.py').read_text(encoding='utf-8')
        branch = src[src.index("elif s.phase in ('running','recovering'):"):src.index("elif s.phase == 'finished' and not s.succeeded")]
        self.assertNotIn('diagnose', branch)
        incident = src[src.index("elif s.phase in ('incident','paused'):\n            options"):src.index("elif s.phase in ('running','recovering'):")]
        self.assertIn("'diagnose'", incident)                                   # 장애/재시도 가능 상태에서는 유지
        self.assertIn('recovery_status_lines', src)

    def test_resolved_incident_is_still_in_the_event_log(self):
        s, a = recovered_a()
        log = '\n'.join(s.runs[a].messages)
        self.assertIn('네트워크 진단 확인: 주 경로 DOWN', log)
        self.assertIn('백업 경로로 우회', log)
        s.advance_time(10); finish_job(s, a)
        self.assertIn('네트워크 진단 확인', '\n'.join(s.runs[a].messages))


class BackgroundRecoveryTests(unittest.TestCase):
    def test_other_customer_can_be_started_and_progress_during_recovery(self):
        s, first, second = free_with_two_customers()
        self.assertEqual({s.runs[first].mission['country'], s.runs[second].mission['country']}, {'싱가포르', '일본'})
        s.select(first)
        start_with_consent(s, 'economy')
        run1 = s.runs[first]
        run1.state.trigger_incident()
        s.respond('reroute')
        st1 = run1.state
        self.assertEqual((st1.phase, st1.recovery_left), ('recovering', 10))
        held = (st1.gpu_used, st1.power_used)
        usage = (s.center.gpu_used, s.center.power_used)
        self.assertEqual(usage, held)
        s.select(second)                                                       # 새 요청 확인/선택
        s.read_conversation(second)
        start_with_consent(s, 'performance')                                   # 남은 자원으로 신규 배정
        run2 = s.runs[second]
        self.assertTrue(run2.state.allocated)
        self.assertEqual(s.center.gpu_used, held[0]+run2.state.gpu_used)
        self.assertTrue(ledger_matches_center(s))
        work1, work2 = st1.work_done, run2.state.work_done
        s.advance_time(10)
        self.assertEqual((st1.phase, st1.work_done), ('running', work1))        # 복구 준비 종료 → 자동 재개(가상 시간)
        self.assertGreater(run2.state.work_done, work2)                         # 다른 고객은 같은 시간에 정상 진행
        self.assertEqual((st1.gpu_used, st1.power_used), held)                  # 이중 점유/임의 반환 없음
        self.assertTrue(ledger_matches_center(s))
        for _ in range(40):
            if st1.phase == 'finished' and run2.state.phase == 'finished':
                break
            s.advance_time(10)
        self.assertTrue(st1.succeeded and run2.state.succeeded)
        self.assertEqual((s.center.gpu_used, s.center.power_used), (0, 0))
        self.assertEqual(s.servers.allocations, {})

    def test_recovery_does_not_advance_game_time_by_itself(self):
        s, a = recovered_a()
        minute = s.minute
        for _ in range(3):
            s.recovery_status_lines(s.runs[a]); s.chapter3_card(a); s.story_objective()
        self.assertEqual((s.minute, s.runs[a].state.recovery_left), (minute, 10))

    def test_new_request_check_does_not_touch_the_recovering_ledger(self):
        s, a = recovered_a()
        usage = (s.center.gpu_used, s.center.power_used)
        allocations = dict(s.servers.allocations)
        s.read_conversation(a)
        self.assertEqual((s.center.gpu_used, s.center.power_used), usage)
        self.assertEqual(s.servers.allocations, allocations)

    def test_story_mode_has_no_random_new_requests(self):
        s, a = recovered_a()
        for _ in range(8):
            s.advance_time(30)
        self.assertEqual(len(s.runs), 1 if len(s.story.chapter3.request_ids) == 1 else 2)


class PersistenceAndFailureTests(unittest.TestCase):
    def test_resume_during_recovery_keeps_state_progress_and_display(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'r.db'
        s = practice3(open_db(self, path))
        a = start_a(s); to_incident(s, a)
        s.view_network_diagnosis(a); s.respond('reroute')
        work, lines, objective = s.runs[a].state.work_done, s.recovery_status_lines(s.runs[a]), s.story_objective()
        s.close()
        s = GameSession(open_db(self, path), mode='story')
        st = s.runs[a].state
        self.assertEqual((st.phase, st.recovery_left, st.work_done, st.recovered_by), ('recovering', 10, work, 'reroute'))
        self.assertEqual((s.recovery_status_lines(s.runs[a]), s.story_objective()), (lines, objective))
        self.assertTrue(ledger_matches_center(s))
        s.advance_time(10)
        self.assertEqual(st.phase, 'running')
        s.close()
        s = GameSession(open_db(self, path), mode='story')
        self.assertTrue(s.recovery_status_lines(s.runs[a])[0].endswith('정상 실행 중'))
        self.assertEqual(s.runs[a].state.work_done, work)

    def test_failure_paths_are_unchanged(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        for _ in range(3):
            s.respond('compress')
        st = s.runs[a].state
        self.assertEqual((st.phase, st.succeeded), ('finished', False))
        self.assertEqual(s.recovery_status_lines(s.runs[a]), [])
        self.assertEqual(s.chapter3_card(a)['kind'], 'failed')
        s2, a2 = incident_a()
        for _ in range(6):
            s2.advance_time(10)
        self.assertEqual(s2.runs[a2].state.phase, 'finished')                   # 60분 중단 실패 유지

    def test_mission_b_recovery_shows_status_too(self):
        s, b = incident_b()
        s.view_network_diagnosis(b); s.respond('compress')
        lines = s.recovery_status_lines(s.runs[b])
        self.assertIn('복구 준비: 10분 남음', lines)
        self.assertIn('복구 준비(10분 남음)', s.story_objective())
        finish_job(s, b)
        self.assertTrue(s.story.chapter3.completed)


if __name__ == '__main__':
    unittest.main()
