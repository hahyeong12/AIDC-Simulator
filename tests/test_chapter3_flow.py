"""v0.9-3a-1: Chapter 3 교육 안내·결과 카드·실패 후 흐름·결과표. Tk 창을 만들지 않는 검증."""
import tempfile
import unittest
from pathlib import Path

from database import Database
from game import RESPONSES
from session import GameSession
from story import GUIDES3, chapter3_card, chapter3_response_text
from tests.support import start_with_consent
from tests.test_chapter3 import (practice3, start_a, to_incident, finish_job, incident_a, incident_b,
                                 play_a_correctly, open_db, ledger_matches_center)

ROOT = Path(__file__).resolve().parent.parent


class DiagnoseGuideTests(unittest.TestCase):
    def test_guide_items_are_separate_lines_with_emphasis_and_no_answer(self):
        for key in ('a_diagnose', 'b_diagnose'):
            lines = GUIDES3[key][1]
            self.assertEqual(len(lines), 1, key)                       # 한 화면(한 페이지)
            text = lines[0].text
            rows = text.split('\n')
            for number, term in (('①', '주 통신 경로'), ('②', '필요 대역폭'), ('③', '백업 경로'), ('④', 'GPU·서버 상태')):
                row = [r for r in rows if r.startswith(number)]
                self.assertEqual(len(row), 1, (key, number))           # 항목마다 별도 행
                self.assertIn(f'【{term}】', row[0])                   # 용어 강조
            self.assertTrue(text.rstrip().endswith('확인한 정보를 바탕으로 대응 방법을 선택해 보세요.'))
            self.assertNotIn('우회', text); self.assertNotIn('압축', text)
            self.assertLess(len(text), 260)

    def test_dialog_title_uses_the_current_chapter(self):
        source = (ROOT / 'story_dialog.py').read_text(encoding='utf-8')
        self.assertIn("chapter_label='Chapter 1'", source)
        self.assertNotIn("교육 담당자 · Chapter 1')", source)
        main = (ROOT / 'main.py').read_text(encoding='utf-8')
        self.assertIn('chapter_label=story.chapter_label', main)
        self.assertIn("chapter_label='Chapter 2'", main)
        from story import StoryProgress
        s = practice3()
        self.assertEqual(s.story.chapter_label, 'Chapter 3')
        self.assertEqual(StoryProgress().chapter_label, 'Chapter 1')


class ResultCardTests(unittest.TestCase):
    def test_success_card_is_based_on_the_real_diagnosis_and_response(self):
        s, a = incident_a()
        s.view_network_diagnosis(a); s.respond('compress'); s.respond('reroute')
        card = s.chapter3_card(a)
        self.assertEqual((card['kind'], card['title']), ('recovered', '네트워크 복구 성공'))
        rows = dict(card['rows'])
        self.assertEqual(rows, {'원인': '주 통신 경로 단절', '선택 대응': '압축 실패 → 우회 성공', '실제 결과': '통신 경로 복구', '상태': '복구 준비 중 · 10분'})
        self.assertIn('끊어진 경로는 압축만으로 복구할 수 없습니다', card['mentor'])
        self.assertLess(len(card['mentor']), 120)
        s2, b = incident_b()
        s2.view_network_diagnosis(b); s2.respond('compress')
        rows = dict(s2.chapter3_card(b)['rows'])
        self.assertEqual((rows['원인'], rows['선택 대응']), ('가용 대역폭 부족', '압축 성공'))
        self.assertIn('≤', rows['실제 결과'])

    def test_intermediate_failure_card_does_not_reveal_the_answer(self):
        s, a = incident_a()
        s.view_network_diagnosis(a); s.respond('compress')
        card = s.chapter3_card(a)
        self.assertEqual((card['kind'], card['can_advance'], card['can_retry']), ('fail', False, False))
        text = card['title']+' '.join(v for _, v in card['rows'])+card['mentor']
        self.assertNotIn('백업', text.replace('백업 경로 사용', ''))
        self.assertIn('압축 실패', text)
        self.assertEqual(dict(card['rows'])['선택 대응'], '압축 실패')

    def test_failed_card_uses_only_recorded_attempts(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        for key in ('compress', 'ignore', 'compress'):
            s.respond(key)
        card = s.chapter3_card(a)
        self.assertEqual((card['kind'], card['title'], card['tone']), ('failed', 'NETWORK RECOVERY FAILED', 'fail'))
        rows = dict(card['rows'])
        self.assertEqual(rows['시도한 대응'], '압축 실패 → 유지 실패 → 압축 실패')
        self.assertEqual((rows['복구 결과'], rows['작업 상태'], rows['원인']), ('실패', '실패 · 후속 처리 필요', '주 통신 경로 단절'))
        self.assertTrue(card['can_retry'])
        self.assertIn('다시 살펴보세요', card['mentor'])
        s.report_failure()
        self.assertEqual(dict(s.chapter3_card(a)['rows'])['작업 상태'], '실패 · 최종 보고 완료')

    def test_timeout_failure_card_says_no_response_was_attempted(self):
        s, a = incident_a()
        for _ in range(6):
            s.advance_time(10)
        card = s.chapter3_card(a)
        self.assertEqual((card['kind'], dict(card['rows'])['시도한 대응']), ('failed', '대응 없음'))

    def test_card_is_none_without_incident_record_and_pure_function_matches(self):
        s = practice3(); a = start_a(s)
        self.assertIsNone(s.chapter3_card(a))
        record = {'kind': 'bandwidth', 'responses': ['reroute', 'compress'], 'attempts': 2, 'recovered_by': 'compress',
                  'primary_up': True, 'rerouted': True, 'needed': 4, 'available': 4}
        self.assertEqual(chapter3_response_text(record), '우회 실패 → 압축 성공')
        self.assertEqual(chapter3_card('recovered', record)['rows'][0], ('원인', '가용 대역폭 부족'))


class RecoveryTimeTests(unittest.TestCase):
    def test_advance_option_exists_only_while_recovery_prep_remains(self):
        s, a = incident_a()
        s.view_network_diagnosis(a); s.respond('reroute')
        st = s.runs[a].state
        self.assertTrue(s.chapter3_card(a)['can_advance'])
        self.assertEqual((st.phase, st.recovery_left), ('recovering', 10))
        work, score = st.work_done, st.score
        s.advance_time(10)                                           # 기존 가상 시간 엔진으로 실제 진행
        self.assertEqual((st.phase, st.recovery_left, st.work_done), ('running', 0, work))   # 복구 10분엔 작업량이 늘지 않음
        self.assertFalse(s.chapter3_card(a)['can_advance'])
        self.assertIsNone(score)
        finish_job(s, a)
        self.assertEqual(st.score, 80+15-RESPONSES['reroute']['penalty']+10-(s.runs[a].terms.get('penalty') or 0))

    def test_no_advance_option_after_failure(self):
        s, a = incident_a()
        s.view_network_diagnosis(a); s.respond('compress')
        self.assertFalse(s.chapter3_card(a)['can_advance'])


class FailureFlowTests(unittest.TestCase):
    def three_failures(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        for _ in range(3):
            s.respond('compress')
        return s, a

    def test_third_failure_does_not_open_the_next_mission(self):
        s, a = self.three_failures()
        c3 = s.story.chapter3
        self.assertEqual((s.runs[a].state.phase, s.runs[a].state.succeeded), ('finished', False))
        self.assertEqual(len(c3.request_ids), 1)                       # 다음 장애 미션 자동 이동 없음
        self.assertEqual((c3.step, s.selected_id), ('a_finish', a))
        self.assertFalse(c3.completed)
        self.assertEqual(len(s.runs), 1)
        self.assertEqual(s.chapter3_pending_feedback()[1], 'failed')   # 실패 결과가 즉시 보임
        self.assertTrue(s.chapter3_retry_available)

    def test_player_can_reopen_the_result_and_retry_button_stays_available(self):
        s, a = self.three_failures()
        key = s.chapter3_pending_feedback()[0]
        s.mark_chapter3_feedback_seen(key)
        self.assertIsNone(s.chapter3_pending_feedback())               # 같은 안내는 다시 자동으로 뜨지 않음
        for _ in range(2):
            card = s.chapter3_card(a)                                  # 닫았다 다시 열어도 같은 기록
            self.assertEqual(card['kind'], 'failed')
        self.assertTrue(s.chapter3_retry_available)
        src = (ROOT / 'main.py').read_text(encoding='utf-8')
        self.assertIn("'후속 처리로 돌아가기'", src)
        self.assertIn("'장애 결과 보기'", src)

    def test_follow_up_retry_and_final_report_still_work(self):
        s, a = self.three_failures()
        s.retry('performance')                                         # 기존 재처리 규칙(준비 20분)
        st = s.runs[a].state
        self.assertEqual((st.retry_count, st.phase, st.recovery_left), (1, 'recovering', 20))
        self.assertEqual(len(s.story.chapter3.request_ids), 1)
        finish_job(s, a)
        self.assertTrue(st.succeeded)
        self.assertEqual(len(s.story.chapter3.request_ids), 2)
        self.assertEqual(s.story.chapter3.records[str(a)]['final'], 'failed')   # 최초 실패 기록은 지워지지 않음
        s2, a2 = self.three_failures()
        s2.report_failure()
        self.assertTrue(s2.runs[a2].followup_closed)
        self.assertEqual(len(s2.story.chapter3.request_ids), 2)
        self.assertTrue(ledger_matches_center(s2))

    def test_failure_is_reflected_in_the_chapter_result(self):
        s, a = self.three_failures()
        s.report_failure()
        b = s.story.chapter3.request_ids[1]
        s.read_conversation(b); s.selected_id = b
        start_with_consent(s, 'performance')
        to_incident(s, b)
        s.view_network_diagnosis(b); s.respond('compress')
        finish_job(s, b)
        result = s.chapter3_result()
        self.assertEqual(result['mission'], 'failed')
        self.assertEqual(result['summary']['ok'], 1)
        table = result['summary']['table']
        self.assertEqual(table[0][:4], ('A', '경로 단절', '압축 실패 → 압축 실패 → 압축 실패 · 3회', '실패'))
        self.assertEqual(table[1][:4], ('B', '대역폭 부족', '압축 성공 · 1회', '성공'))
        self.assertEqual(table[0][4], '확정 점수 없음')
        self.assertFalse(s.runs[a].state.succeeded)                    # 실패를 성공으로 바꾸지 않음

    def test_no_slot_is_created_or_progress_erased_without_player_choice(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'f.db'
        s = practice3(open_db(self, path))
        a = start_a(s); to_incident(s, a)
        s.view_network_diagnosis(a)
        for _ in range(3):
            s.respond('ignore')
        s.close()
        self.assertEqual([p.name for p in Path(folder.name).glob('*.db')], ['f.db'])
        s = GameSession(open_db(self, path), mode='story')              # 이어하기에서 기록 유지, 안내 중복 없음
        self.assertEqual(s.runs[a].state.response_log, ['ignore']*3)
        self.assertEqual(s.chapter3_pending_feedback()[1], 'failed')
        s.mark_chapter3_feedback_seen(s.chapter3_pending_feedback()[0])
        s.close()
        s = GameSession(open_db(self, path), mode='story')
        self.assertIsNone(s.chapter3_pending_feedback())
        self.assertEqual(s.chapter3_card(a)['kind'], 'failed')


class ResultTableTests(unittest.TestCase):
    def test_success_table_shows_attempts_and_actual_score(self):
        s, b = incident_b()
        s.view_network_diagnosis(b); s.respond('reroute'); s.respond('compress')
        finish_job(s, b)
        result = s.chapter3_result()
        self.assertEqual(result['mission'], 'success')
        self.assertEqual(result['summary']['ok'], 2)
        a_id, b_id = s.story.chapter3.request_ids
        table = result['summary']['table']
        self.assertEqual(table[0], ('A', '경로 단절', '우회 성공 · 1회', '성공', f'{s.runs[a_id].state.score}점'))
        self.assertEqual(table[1], ('B', '대역폭 부족', '우회 실패 → 압축 성공 · 2회', '성공', f'{s.runs[b_id].state.score}점'))
        self.assertLessEqual(len(result['mentor']), 3)
        self.assertTrue(all(len(line) < 80 for line in result['mentor']))
        self.assertIn('2개', result['mentor'][-1])

    def test_dialog_source_keeps_buttons_outside_the_scroll_area_and_detail_collapsed(self):
        src = (ROOT / 'chapter_dialog.py').read_text(encoding='utf-8')
        tail = src[src.index('class Chapter3CompleteDialog'):]
        self.assertIn("buttons.grid(row=2", tail)
        self.assertIn("'Chapter 3 다시 도전'", tail)
        self.assertIn("('modes', '모드 선택'", tail)
        self.assertIn("('status', '진행 현황'", tail)
        self.assertIn('상세 기록 보기', tail)


class UnchangedRulesTests(unittest.TestCase):
    def test_diagnosis_values_and_gating_are_unchanged(self):
        s, a = incident_a()
        self.assertTrue(s.chapter3_response_locked(s.runs[a]))
        d = s.view_network_diagnosis(a)
        self.assertEqual((d['primary'], d['available'], d['summary']), ('DOWN', 0, '통신 경로 이상 · 전송률 0'))
        self.assertFalse(s.chapter3_response_locked(s.runs[a]))
        s2, b = incident_b()
        self.assertEqual(s2.view_network_diagnosis(b)['summary'], '대역폭 한계 · 전송 지연')

    def test_diagnosis_dialog_source_is_compact_two_column(self):
        src = (ROOT / 'network_dialog.py').read_text(encoding='utf-8')
        for text in ('NETWORK DIAGNOSIS', '장애 관측: ', '현재 진단 정보를 확인했습니다.', '진단 확인 · 대응 선택'):
            self.assertIn(text, src)
        self.assertIn('ScrollArea', src)                                # 내용이 넘칠 때만 스크롤바가 나타나는 공통 위젯


if __name__ == '__main__':
    unittest.main()
