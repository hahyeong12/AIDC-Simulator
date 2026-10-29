"""동일한 가상 일정과 시드에서 운영 전략을 반복 비교합니다."""
import json
import unittest

from database import Database
from session import GameSession


SCENARIOS = {
    '분산 접수': [(0,1),(30,2),(30,3),(240,1),(270,2),(270,3)],
    '긴급 동시 접수': [(0,1),(0,2),(0,3)],
}


def simulate(strategy, scenario='분산 접수'):
    """자동 추첨 대신 고정 접수 일정 사용, 장애 없음, 모든 전략 시드 9."""
    db = Database(':memory:')
    try:
        s = GameSession(db, seed=9, incident_chance=0)
        # 자동 접수와 시나리오 접수가 겹치지 않게 테스트의 공급 일정만 교체합니다.
        s.next_arrival_minute = 100000
        schedule = SCENARIOS[scenario]
        gpu_minutes = 0
        horizon = 660
        for elapsed in range(0,horizon,10):
            for minute,mid in schedule:
                if minute == elapsed and (minute,mid) != (0,1):
                    with s._atomic(): s._receive(mid,f'scenario:{minute}:{mid}')
            pending = [r for r in s.runs.values() if r.request['status'] in ('new','review','waiting')]
            # 절약형 순차 전략은 먼저 접수한 요청을 하나씩 처리합니다.
            # 병행 전략 B/C는 같은 완료 기한 순서로 자원 배정을 시도합니다.
            pending.sort(key=lambda r: r.terms['received'] if strategy=='A' else r.terms['due'])
            for run in pending:
                if strategy=='A' and s.center.gpu_used:
                    break
                mode = 'economy' if strategy=='A' or (strategy=='B' and run.terms['priority'].startswith('일반')) else 'performance'
                s.select(run.request['id'])
                try:
                    s.choose_plan(mode)
                except ValueError:
                    s.wait_request()
            gpu_minutes += s.center.gpu_used*10
            s.advance_time(10)
        runs = list(s.runs.values())
        done = [r for r in runs if r.state.succeeded]
        scores = [r.terms.get('evaluation',0) for r in runs]
        return {'completed':len(done),
                'on_time':sum(r.terms['late_minutes']==0 for r in done),
                'delayed':sum(r.terms.get('late_minutes',0)>0 or r.terms.get('expired',False) for r in runs),
                'average_score':round(sum(scores)/len(scores),1),
                'gpu_utilization':round(gpu_minutes/(10*horizon)*100,1),
                'unprocessed':sum(r.terms.get('expired',False) or r.request['status'] in ('new','review','waiting') for r in runs)}
    finally:
        db.close()


class BalanceTests(unittest.TestCase):
    def test_fixed_schedule_results_are_reproducible(self):
        for scenario in SCENARIOS:
            for strategy in 'ABC':
                self.assertEqual(simulate(strategy,scenario), simulate(strategy,scenario))

    def test_mixed_parallel_strategy_beats_sequential_economy_on_distributed_arrivals(self):
        a,b,c = (simulate(strategy) for strategy in 'ABC')
        self.assertGreater(b['on_time'], a['on_time'])
        self.assertGreater(b['average_score'], a['average_score'])
        self.assertLess(b['unprocessed'], a['unprocessed'])
        self.assertGreater(b['on_time'], c['on_time'])

    def test_economy_allows_training_and_urgent_inference_to_share_capacity(self):
        db = Database(':memory:')
        try:
            s = GameSession(db, seed=9, incident_chance=0)
            s.deliver_next_request(); s.select(2); s.choose_plan('performance')
            s.select(1)
            with self.assertRaisesRegex(ValueError,'전력 1단위'): s.choose_plan('performance')
            s.choose_plan('economy')
            self.assertEqual((s.center.gpu_used,s.center.power_used), (7,8))
            for _ in range(3): s.advance_time(60)
            for rid in (1,2):
                self.assertTrue(s.runs[rid].state.succeeded)
                self.assertEqual(s.runs[rid].terms['late_minutes'], 0)
            self.assertEqual((s.center.gpu_used,s.center.power_used), (0,0))
        finally: db.close()

    def test_all_performance_can_win_when_urgent_requests_arrive_together(self):
        b,c = (simulate(strategy,'긴급 동시 접수') for strategy in 'BC')
        self.assertGreater(c['average_score'], b['average_score'])
        self.assertEqual(c['on_time'], b['on_time'])


if __name__ == '__main__':
    print(json.dumps({scenario:{strategy:simulate(strategy,scenario) for strategy in 'ABC'}
                      for scenario in SCENARIOS}, ensure_ascii=False, indent=2))
