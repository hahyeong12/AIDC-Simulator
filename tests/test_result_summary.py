"""v0.9-2b: 결과 요약·고객 반응. Tk 창을 만들지 않는 규칙/저장 검증.

원칙: 결과는 요약표로 먼저, 설명은 아래에, 고객 반응은 실제 결과에 맞게.
모든 값은 실제 세션 엔진을 돌려 얻은 기록에서만 확인합니다(성공/실패를 고정하지 않습니다).
"""
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import chapter2
from database import Database
from result_summary import customer_reaction, free_result_lines, job_summary, outcome_key, chapter2_strategy
from session import GameSession
from tests.test_chapter2 import ready, start, finish_all, after_chapter1
from tests.test_chapter2_balance import until_finished


def events(s, rid, kind):
    return [e for e in s.db.get_request_events(rid) if e['kind'] == kind]


def success_run():
    s, jp, us = ready()
    start(s, jp, 'performance'); start(s, us, 'economy')
    finish_all(s)
    return s, jp, us


def jp_then_us_high():
    s, jp, us = ready()
    start(s, jp, 'performance')
    until_finished(s, jp)
    start(s, us, 'performance')
    finish_all(s)
    return s, jp, us


class Chapter2SummaryTests(unittest.TestCase):
    def test_success_summary_is_built_from_real_records(self):
        s, jp, us = success_run()
        r = s.chapter2_result()
        sm = r['summary']
        self.assertEqual(r['mission'], 'success')
        self.assertEqual((sm['ok'], sm['total']), (2, 2))
        self.assertEqual(sm['strategy'], '일본 고성능 + 미국 절약형')
        self.assertEqual(sm['arrangement'], '두 작업 동시 실행')
        self.assertIn('GPU 8개 / 전력 8단위', sm['resources'])
        self.assertEqual([j['deadline'] for j in r['jobs']], ['준수', '준수'])
        self.assertEqual([j['mode'] for j in r['jobs']], ['고성능 모드', '절약형 모드'])
        self.assertEqual(r['overall'], sum(j['eval_score'] for j in r['jobs'])/2)
        self.assertTrue(r['highlights'])

    def test_failed_mission_with_high_overall_is_not_success(self):
        """한 고객이 100점이어도 다른 고객이 기한을 넘기면 종합 점수가 높아도 미션은 실패입니다."""
        s, jp, us = jp_then_us_high()
        r = s.chapter2_result()
        self.assertEqual(r['mission'], 'failed')
        self.assertGreaterEqual(r['overall'], 90)
        self.assertEqual(r['summary']['ok'], 1)
        self.assertEqual(r['summary']['verdict'], '2명 중 1명만 기한 내 정상 완료')
        jp_job, us_job = r['jobs']
        self.assertEqual(jp_job['state'], 'success')
        self.assertEqual(jp_job['eval_score'], 100)
        self.assertEqual(us_job['state'], 'failed')
        self.assertEqual(us_job['deadline'], '초과 10분')
        self.assertEqual(r['summary']['strategy'], '일본 고성능 → 미국 고성능')
        self.assertEqual(r['summary']['arrangement'], '순차 실행 · 먼저 끝난 자원 반환 후 시작')
        self.assertEqual(r['highlights'], [])

    def test_late_completion_never_reads_as_success(self):
        s, jp, us = jp_then_us_high()
        us_run = s.runs[us]
        self.assertEqual(outcome_key(us_run), 'late')
        self.assertEqual(job_summary(us_run)['label'], '정상 완료 · 기한 초과')
        self.assertNotEqual(s.chapter2_evaluation()['mission'], 'success')

    def test_unprocessed_request_gets_no_invented_score_or_resources(self):
        s, jp, us = ready()
        start(s, us, 'performance')
        finish_all(s)
        r = s.chapter2_result()
        jp_job = r['jobs'][0]
        self.assertEqual(jp_job['outcome'], '기한 만료 · 미처리')
        self.assertEqual((jp_job['gpu'], jp_job['power']), (0, 0))
        self.assertEqual(jp_job['mode'], '미배정')
        summary = job_summary(s.runs[jp])
        self.assertEqual(summary['key'], 'expired')
        self.assertIsNone(summary['score'])
        self.assertEqual((summary['gpu'], summary['power'], summary['deadline']), (0, 0, '해당 없음'))
        self.assertEqual(r['summary']['strategy'], '미국 고성능')
        self.assertEqual(jp_job['eval_score'], 0)       # 기존 종합 평가 규칙(미처리 0점)은 그대로
        self.assertEqual(r['mission'], 'failed')

    def test_overall_and_job_scores_match_existing_formula(self):
        s, jp, us = jp_then_us_high()
        r = s.chapter2_result()
        self.assertEqual(r['overall'], s.chapter2_evaluation()['overall'])
        self.assertEqual(r['overall'], sum(j['eval_score'] for j in r['jobs'])/2)

    def test_result_building_does_not_change_the_saved_game(self):
        s, jp, us = success_run()
        before = json.dumps(s.db.get_simulation(), sort_keys=True, default=str)
        s.chapter2_result(); s.chapter2_result()
        self.assertEqual(before, json.dumps(s.db.get_simulation(), sort_keys=True, default=str))

    def test_old_chapter2_slot_still_gets_a_summary(self):
        with patch.dict(chapter2.CHAPTER2_SCENARIOS, {'미국': 'ch2_us'}):
            s, jp, us = ready()
            start(s, jp, 'performance'); until_finished(s, jp)
            start(s, us, 'performance'); finish_all(s)
            r = s.chapter2_result()
        self.assertEqual(r['mission'], 'success')
        self.assertEqual(r['summary']['strategy'], '일본 고성능 → 미국 고성능')
        self.assertEqual(r['summary']['ok'], 2)

    def test_strategy_label_with_no_started_job(self):
        self.assertEqual(chapter2_strategy([{'country': '일본', 'mode': '고성능 모드', 'started': None}], False), '배정한 작업 없음')


class CustomerReactionTests(unittest.TestCase):
    def free_session(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, seed=9, incident_chance=0)
        s.deliver_next_request(); s.select(2)
        return s

    def test_on_time_completion_thanks_the_customer(self):
        s = self.free_session()
        run = s.current
        s.choose_plan('performance')
        s.advance_time(60)
        self.assertEqual(outcome_key(run), 'on_time')
        self.assertIn('감사', run.last_feedback)
        self.assertNotIn('아쉬', run.last_feedback)
        self.assertEqual(len(events(s, run.request['id'], 'customer_complete')), 1)

    def test_late_completion_acknowledges_but_regrets_delay(self):
        s = self.free_session()
        run = s.current
        s.advance_time(30)
        s.choose_plan('performance')
        s.advance_time(60)
        self.assertEqual(outcome_key(run), 'late')
        self.assertIn('감사', run.last_feedback)
        self.assertIn('아쉬', run.last_feedback)
        self.assertIn('지연', run.last_feedback)

    def test_rejected_request_gets_a_matching_reply_without_score(self):
        s = self.free_session()
        run = s.current
        s.reject_request('현재 GPU 자원 부족')
        self.assertEqual(outcome_key(run), 'rejected')
        self.assertIn('아쉽', run.last_feedback)
        lines = free_result_lines(run)
        self.assertIn('작업 결과: 요청 거절', lines)
        self.assertTrue(any('부여하지 않음' in line for line in lines))
        self.assertFalse(any(line.startswith('사용 자원') for line in lines))

    def test_expired_request_is_unprocessed_not_failed(self):
        s = self.free_session()
        run = s.current
        for _ in range(30):
            if run.terms.get('expired'):
                break
            s.advance_time(60)
        self.assertEqual(outcome_key(run), 'expired')
        self.assertIn('철회', run.last_feedback)
        self.assertEqual(len(events(s, run.request['id'], 'customer_expired')), 1)
        self.assertEqual(job_summary(run)['mode'], '배정 없음')

    def test_failure_and_agreed_conditions_are_reflected(self):
        run = SimpleNamespace(mission={'country': '일본'}, proposals=[{'status': 'accepted'}])
        self.assertIn('유감', customer_reaction(run, 'failed'))
        self.assertIn('원인과 복구 계획', customer_reaction(run, 'failed'))
        self.assertIn('협의한 운영 조건', customer_reaction(run, 'on_time'))
        plain = SimpleNamespace(mission={'country': '미국'}, proposals=[])
        self.assertNotIn('협의', customer_reaction(plain, 'on_time'))
        self.assertIn('협의했던', customer_reaction(run, 'expired'))
        for country in ('일본', '미국', '싱가포르'):
            r = SimpleNamespace(mission={'country': country}, proposals=[])
            for key in ('on_time', 'late', 'failed', 'rejected', 'expired'):
                text = customer_reaction(r, key)
                self.assertTrue(text and '!' not in text)
        with self.assertRaises(ValueError):
            customer_reaction(plain, 'in_progress')
        # 동의한 대안은 실제로 그 모드로 운영했을 때만 언급합니다.
        agreed = {'status': 'accepted', 'proposed': {'mode': 'economy'}}
        used = SimpleNamespace(mission={'country': '일본'}, proposals=[agreed], state=SimpleNamespace(plan='economy'))
        other = SimpleNamespace(mission={'country': '일본'}, proposals=[agreed], state=SimpleNamespace(plan='performance'))
        self.assertIn('협의한 운영 조건', customer_reaction(used, 'on_time'))
        self.assertNotIn('협의', customer_reaction(other, 'on_time'))

    def test_reading_the_conversation_does_not_create_more_reactions(self):
        s = self.free_session()
        run = s.current
        rid = run.request['id']
        s.choose_plan('performance'); s.advance_time(60)
        count = len(s.db.get_request_events(rid))
        for _ in range(3):
            s.read_conversation(rid); s.conversation(rid, history=True); free_result_lines(run)
        self.assertEqual(count, len(s.db.get_request_events(rid)))
        self.assertEqual(len(events(s, rid, 'customer_complete')), 1)


class FreeAndStoryModeTests(unittest.TestCase):
    def test_in_progress_request_has_no_result_summary(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, seed=9, incident_chance=0)
        s.deliver_next_request(); s.select(2)
        self.assertEqual(free_result_lines(s.current), [])
        s.choose_plan('performance')
        self.assertEqual(free_result_lines(s.current), [])
        self.assertEqual(job_summary(s.current)['label'], '진행 중')
        self.assertIsNone(job_summary(s.current)['score'])

    def test_completed_free_request_summary_lists_real_values(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, seed=9, incident_chance=0)
        s.deliver_next_request(); s.select(2)
        run = s.current
        s.choose_plan('performance'); s.advance_time(60)
        lines = free_result_lines(run)
        self.assertEqual(lines[0], '작업 결과: 정상 완료 · 기한 준수')
        self.assertIn(f'고객: {run.mission["company_name"]}', lines)
        self.assertIn('운영 모드: 고성능 모드', lines)
        self.assertIn(f'점수: {run.state.score}점', lines)
        self.assertTrue(any(line.startswith('기한: 준수') for line in lines))

    def test_chapter1_summary_rows_in_story_mode(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = after_chapter1(db)
        result = s.chapter_result()
        rows = dict(result['summary'])
        self.assertEqual(rows['운영 점수'], f'{result["score"]}점')
        self.assertEqual(rows['고객'], result['company'])
        self.assertIn('반환', rows['반환 자원'])
        self.assertIn('GPU', rows['사용 자원'])
        self.assertIn('/', rows['완료 / 기한'])
        self.assertEqual(s.mode, 'story')

    def test_saved_chapter_one_completion_keeps_its_result_after_resume(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, 'temp.db')
        db = Database(path)
        s = after_chapter1(db)
        before = s.chapter_result()
        s.close()
        db2 = Database(path); self.addCleanup(db2.close)
        again = GameSession(db2, mode='story').chapter_result()
        self.assertEqual(before['score'], again['score'])
        self.assertEqual(before['summary'], again['summary'])


class SchemaSafetyTests(unittest.TestCase):
    def test_no_new_saved_fields(self):
        db = Database(':memory:'); self.addCleanup(db.close)
        s = GameSession(db, mode='story', seed=9)
        s.save()
        saved = json.dumps(db.get_simulation(), default=str)
        for word in ('summary', 'reaction'):
            self.assertNotIn(word, saved)


if __name__ == '__main__':
    unittest.main()
