"""v0.9-4a Engineering Lab(Prototype): 공통 관찰 모델 · 가상 터미널 · 객관식/블록 연결. Tk 창을 만들지 않는 검증.

같은 Chapter 3a 미션 A(ch3_path) 상태를 관찰 모델·구조도 구간·터미널 출력이 일관되게 보여 주는지,
관찰/명령이 게임 시간·점수·원장·DB를 바꾸지 않는지, 기존 복구 흐름과 저장 호환이 유지되는지 확인합니다.
"""
import ast
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database import Database
from lab_model import LAB_NETWORK, LabLearningTrace, lab_support, observe
from lab_terminal import (CHOICE_FIT, COMMAND_SPECS, CommandError, assemble, block_feedback, choice_command,
                          interpret, parse_command, run_command)
from session import GameSession
from tests.test_chapter3 import (practice3, start_a, to_incident, finish_job, incident_a, incident_b, open_db,
                                 ledger_matches_center)

ROOT = Path(__file__).resolve().parents[1]


def snapshot(s):
    """게임 상태 비교용 스냅샷(시간·요청·작업·원장·하드웨어·스토리·DB)."""
    runs = {rid: (deepcopy(vars(r.state) | {'center': None}), dict(r.request), list(r.messages), r.playthrough_id,
                  deepcopy(r.proposals), deepcopy(r.conditions), deepcopy(r.terms), list(r.server_allocations))
            for rid, r in s.runs.items()}
    db = (s.db.get_simulation(), {rid: s.db.get_runtime(rid) for rid in s.runs},
          {rid: len(s.db.get_request_events(rid)) for rid in s.runs})
    return (s.minute, s.roll_index, s.selected_id, s.center.gpu_used, s.center.power_used, dict(s.servers.allocations),
            dict(s.servers.hardware), s.story.payload() if s.story else None, runs, db)


def exercise_lab(s, rid):
    """Lab의 모든 읽기 경로(관찰·객관식·블록·터미널)를 실행합니다."""
    o = observe(s, rid)
    lines = [choice_command(name, o) for name in ('ping', 'ip route', 'ip addr')]
    lines += [assemble('ping', '-c 1', LAB_NETWORK['routers']['backup']['address']), 'help', 'ip addr show eth1',
              'ping -c 2 10.0.0.99', 'ls', 'foo', 'ip route add 10.0.0.0/24 via 192.168.20.1', 'ping', 'clear']
    results = [run_command(line, observe(s, rid)) for line in lines]
    for result in results:
        interpret(result, o)
    return results


class ObservationModelTests(unittest.TestCase):
    def test_observation_matches_game_state_before_and_during_incident(self):
        s = practice3()
        a = start_a(s)
        o = observe(s, a)
        st = s.runs[a].state
        self.assertEqual((o.minute, o.time_label, o.request_id, o.scenario), (s.minute, s.time_label, a, 'ch3_path'))
        self.assertEqual((o.phase, o.tone, o.network.primary_up, o.network.link_ok), ('running', 'ok', True, True))
        self.assertEqual(o.network.segments['primary-wan'], 'up')
        self.assertEqual((o.gpu_used, o.power_used), (st.gpu_used, st.power_used))
        allocation = s.servers.allocations[s.runs[a].playthrough_id]
        self.assertEqual(o.job_servers, tuple(p.server_id for p in allocation.slices))
        self.assertEqual(sum(v.job_gpu for v in o.servers), allocation.gpu)
        self.assertEqual(sum(v.job_power for v in o.servers), allocation.power)
        to_incident(s, a)
        o = observe(s, a)
        self.assertEqual((o.phase, o.tone, o.network.incident_kind), ('incident', 'fault', 'path_down'))
        self.assertEqual((o.network.primary_up, o.network.link_ok, o.network.rerouted), (False, False, False))
        self.assertEqual(o.network.segments, {'edge-primary': 'up', 'primary-wan': 'down', 'edge-backup': 'up',
                                              'backup-wan': 'standby', 'gateway-servers': 'up'})
        self.assertEqual((o.network.needed, o.network.available, o.network.backup_capacity),
                         (s.runs[a].state.network_needed, s.runs[a].state.network_available, s.runs[a].state.backup_capacity))
        self.assertIn('DOWN', o.incident_label)
        # 장애 중에도 GPU 점유는 유지됩니다(원장과 같은 값).
        self.assertEqual(o.gpu_used, s.runs[a].state.gpu_used)
        self.assertTrue(o.transferring)

    def test_slot_view_matches_ledger_slots(self):
        s, a = incident_a()
        o = observe(s, a)
        allocation = s.servers.allocations[s.runs[a].playthrough_id]
        for part in allocation.slices:
            server = o.server(part.server_id)
            mine = tuple(slot.index for slot in server.slots if slot.this_job)
            self.assertEqual(mine, part.gpu_slots)
            self.assertTrue(all(slot.owner == 'sg' for slot in server.slots if slot.this_job))
        self.assertEqual(o.target_address, LAB_NETWORK['servers'][o.job_servers[0]])

    def test_before_allocation_has_no_transfer_and_targets_server_a(self):
        s = practice3()
        s.confirm_chapter3_briefing()
        a = s.story.chapter3.request_ids[0]
        o = observe(s, a)
        self.assertFalse(o.transferring)
        self.assertEqual((o.job_servers, o.gpu_used, o.target_address), ((), 0, '10.0.0.20'))

    def test_lab_is_supported_only_for_chapter3a_mission_a(self):
        s, a = incident_a()
        self.assertEqual(lab_support(s, a), '')
        self.assertEqual(lab_support(s), '')          # 선택된 요청 기준
        free = GameSession(Database(':memory:'), seed=3)
        self.assertIn('자유 운영', lab_support(free))
        for chapter in (1, 2, '3b'):
            kwargs = {} if chapter == 1 else {'start_chapter': chapter}
            story = GameSession(Database(':memory:'), mode='story', seed=3, **kwargs)
            self.assertIn('Chapter 3a', lab_support(story), chapter)

    def test_mission_b_is_not_supported_and_points_to_mission_a(self):
        s, b = incident_b()
        a = s.story.chapter3.request_ids[0]
        reason = lab_support(s, b)
        self.assertIn('미션 A', reason)
        self.assertIn(f'#{a}', reason)
        self.assertEqual(lab_support(s, a), '')


class TerminalSharesObservationTests(unittest.TestCase):
    def test_ping_route_and_diagram_agree_during_and_after_recovery(self):
        s, a = incident_a()
        o = observe(s, a)
        target = o.target_address
        down = run_command(f'ping -c 3 {target}', o)
        self.assertEqual((down.ok, down.facts['received'], down.facts['kind']), (True, 0, 'timeout'))
        self.assertIn('3 packets transmitted, 0 received, 100% packet loss', down.output)
        route = run_command('ip route', o)
        # 경로 설정은 남아 있지만 통신은 실패합니다(라우팅 테이블과 실제 연결 성공은 별개).
        self.assertIn('10.0.0.0/24 via 192.168.10.1 dev eth0', route.output)
        self.assertEqual(route.facts['path'], o.network.active_path)
        gateway = run_command('ping -c 2 192.168.10.1', o)
        self.assertEqual(gateway.facts['received'], 2)             # 가까운 구간은 정상
        addr = run_command('ip addr', o)
        self.assertNotIn('DOWN', addr.output)                      # 먼 구간 단절은 ip addr로 보이지 않음
        s.view_network_diagnosis(a)
        s.respond('reroute')
        after = observe(s, a)
        self.assertEqual((after.network.link_ok, after.network.segments['backup-wan'], after.phase),
                         (True, 'active', 'recovering'))
        up = run_command(f'ping -c 3 {target}', after)
        self.assertEqual((up.facts['received'], up.facts['path']), (3, 'backup'))
        self.assertIn('0% packet loss', up.output)
        self.assertNotEqual(down.output, up.output)
        self.assertIn('10.0.0.0/24 via 192.168.20.1 dev eth1', run_command('ip route', after).output)
        self.assertNotEqual(route.output, run_command('ip route', after).output)
        self.assertEqual(after.network.segments['primary-wan'], 'down')   # 주 경로 자체는 여전히 DOWN

    def test_terminal_reflects_normal_state_before_incident(self):
        s = practice3()
        a = start_a(s)
        o = observe(s, a)
        result = run_command(f'ping -c 1 {o.target_address}', o)
        self.assertEqual((result.facts['received'], result.facts['path']), (1, 'primary'))
        self.assertIn('ttl=62', result.output)

    def test_ping_output_follows_observed_link_flag(self):
        s, a = incident_a()
        o = observe(s, a)
        for line in ('ping -c 2 10.0.0.20', 'ping -c 2 10.0.0.21', 'ping -c 2 10.0.0.1'):
            self.assertEqual(run_command(line, o).facts['received'] > 0, o.network.link_ok, line)

    def test_same_time_label_is_shared(self):
        s, a = incident_a()
        o = observe(s, a)
        self.assertEqual(run_command('ip route', o).time_label, s.time_label)


class CommandParsingTests(unittest.TestCase):
    def setUp(self):
        self.s, self.a = incident_a()
        self.o = observe(self.s, self.a)

    def error(self, line):
        result = run_command(line, self.o)
        self.assertEqual((result.ok, result.kind), (False, 'error'), line)
        return result

    def test_invalid_syntax_is_reported_without_crashing(self):
        self.assertIn("requires an argument -- 'c'", self.error('ping -c').output)
        self.assertIn("invalid argument: 'abc'", self.error('ping -c abc 10.0.0.20').output)
        self.assertIn("invalid argument: '0'", self.error('ping -c 0 10.0.0.20').output)
        self.assertIn("invalid option -- 'x'", self.error('ping -x 10.0.0.20').output)
        self.assertIn('Destination address required', self.error('ping').output)
        self.assertIn('하나만', self.error('ping 10.0.0.20 10.0.0.21').output)
        self.assertIn('따옴표', self.error('ping "10.0.0.20').output)
        self.assertIn('Object "foo" is unknown', self.error('ip foo').output)
        self.assertIn('Usage: ip', self.error('ip').output)
        self.assertIn('Command "-c" is unknown', self.error('ip addr -c 3').output)
        self.assertIn('Command "10.0.0.20" is unknown', self.error('ip route 10.0.0.20').output)
        self.assertIn('Device "eth9" does not exist', self.error('ip addr show eth9').output)

    def test_shell_features_are_rejected(self):
        for line in ('ping -c 1 10.0.0.20 | grep ttl', 'ip route; ip addr', 'ip addr > out.txt', 'echo $(whoami)',
                     'ping -c 1 10.0.0.20 && ls', 'ip route `ls`'):
            self.assertIn('지원하지 않습니다', self.error(line).output, line)

    def test_unsupported_and_unknown_commands_are_distinguished(self):
        self.assertEqual(self.error('foo').output, 'bash: foo: command not found')
        self.assertIn('아직 지원하지 않습니다', self.error('ss -lnt').output)
        self.assertIn('아직 지원하지 않습니다', self.error('traceroute 10.0.0.20').output)
        self.assertIn('읽기 명령만', self.error('rm -rf /').output)
        self.assertIn('실행할 수 없습니다', self.error('ip route add 10.0.0.0/24 via 192.168.20.1').output)
        self.assertIn('실행할 수 없습니다', self.error('sudo ip link set eth0 down').output)

    def test_valid_variants(self):
        for line in ('ip a', 'ip address show', 'ip addr show dev eth0', 'ip r', 'ip route show', 'ping -c3 10.0.0.20',
                     'help', '   ', 'clear'):
            self.assertTrue(run_command(line, self.o).ok, line)
        self.assertEqual(run_command('', self.o).kind, 'empty')
        self.assertEqual(run_command('clear', self.o).kind, 'clear')
        default = run_command('ping 192.168.20.1', self.o)
        self.assertEqual((default.facts['transmitted'], default.facts['default_count']), (4, True))
        self.assertIn('Ctrl+C', default.output)

    def test_destination_kinds(self):
        self.assertIn('Network is unreachable', run_command('ping -c 1 8.8.8.8', self.o).output)
        self.assertIn('Name or service not known', run_command('ping -c 1 aidc-gw', self.o).output)
        self.assertIn('Destination Host Unreachable', run_command('ping -c 1 192.168.10.77', self.o).output)
        self.assertEqual(run_command('ping -c 1 127.0.0.1', self.o).facts['received'], 1)

    def test_terminal_never_executes_host_commands(self):
        tree = ast.parse((ROOT / 'lab_terminal.py').read_text(encoding='utf-8'))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names} | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imported & {'os', 'subprocess', 'sys', 'shutil', 'socket'})
        calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertFalse(calls & {'eval', 'exec', 'compile', '__import__', 'open'})
        for name in ('lab_model.py', 'lab_terminal.py'):
            self.assertNotIn('tkinter', (ROOT / name).read_text(encoding='utf-8'), name)

    def test_parse_command_returns_structured_command(self):
        parsed = parse_command('ping -c 3 10.0.0.20')
        self.assertEqual((parsed.name, parsed.count, parsed.target), ('ping', 3, '10.0.0.20'))
        with self.assertRaises(CommandError):
            parse_command('ping -c')


class SharedGeneratorTests(unittest.TestCase):
    def test_blocks_choice_and_terminal_use_the_same_result(self):
        s, a = incident_a()
        o = observe(s, a)
        target = o.target_address
        typed = run_command(f'ping -c 3 {target}', o)
        built = run_command(assemble('ping', '-c 3', target), o)
        chosen = run_command(choice_command('ping', o), o)
        self.assertEqual(typed.output, built.output)
        self.assertEqual(typed.output, chosen.output)
        self.assertEqual(typed.facts, built.facts)
        for name in ('ip route', 'ip addr'):
            self.assertEqual(run_command(choice_command(name, o), o).output, run_command(assemble(name), o).output)

    def test_wrong_block_combinations_use_parser_errors(self):
        line, roles, errors = block_feedback('ip addr', '-c 3', '10.0.0.20')
        self.assertEqual(line, 'ip addr -c 3 10.0.0.20')
        self.assertTrue(errors and 'Command "-c" is unknown' in errors[0])
        self.assertEqual(len(roles), 3)
        self.assertIn('Destination address required', block_feedback('ping', '-c 3')[2][0])
        self.assertEqual(block_feedback('ping', '-c 1', '10.0.0.20')[2], [])
        self.assertEqual(block_feedback('ip route')[2], [])
        self.assertIn('명령 블록이 비어', block_feedback(None, '-c 3')[1][0])
        # 같은 잘못된 줄을 터미널에 입력해도 같은 오류가 나옵니다.
        s, a = incident_a()
        self.assertIn(run_command('ip addr -c 3 10.0.0.20', observe(s, a)).output, errors[0])

    def test_choice_feedback_never_fails_the_mission(self):
        s, a = incident_a()
        before = snapshot(s)
        o = observe(s, a)
        self.assertEqual(CHOICE_FIT['ping'][0], 'best')
        for name in ('ip route', 'ip addr'):
            self.assertEqual(CHOICE_FIT[name][0], 'partial')
            run_command(choice_command(name, o), o)
            for key in ('purpose', 'can', 'cannot'):
                self.assertTrue(COMMAND_SPECS[name][key])
        self.assertEqual(snapshot(s), before)

    def test_interpretation_does_not_conclude_from_ping_failure(self):
        s, a = incident_a()
        o = observe(s, a)
        text = interpret(run_command(f'ping -c 3 {o.target_address}', o), o)
        self.assertIn('단정하지', text)
        for cause in ('경로 단절', '장비', 'ICMP'):        # 한 원인으로 단정하지 않고 여러 가능성을 함께 말합니다.
            self.assertIn(cause, text)


class ReadOnlyTests(unittest.TestCase):
    def test_observing_and_commands_do_not_change_time_score_ledger_or_db(self):
        s, a = incident_a()
        before = snapshot(s)
        with patch.object(s.db, 'save_simulation', side_effect=AssertionError('Lab이 저장했습니다')), \
             patch.object(s.db, 'save_runtime', side_effect=AssertionError('Lab이 저장했습니다')):
            for _ in range(3):
                exercise_lab(s, a)
        self.assertEqual(snapshot(s), before)
        self.assertTrue(ledger_matches_center(s))

    def test_learning_trace_is_memory_only_and_separate_from_score(self):
        s, a = incident_a()
        before = snapshot(s)
        trace = LabLearningTrace()
        trace.level = 'intermediate'
        trace.record('blocks', 'ping -c 3 10.0.0.20', True, s.time_label)
        self.assertEqual(trace.entries[0]['level'], 'intermediate')
        self.assertEqual(snapshot(s), before)
        self.assertNotIn('lab', s.story.payload())

    def test_disk_slot_is_byte_identical_after_lab_reads(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'lab.db'
        s = practice3(open_db(self, path))
        a = start_a(s)
        to_incident(s, a)
        s.save()
        data = path.read_bytes()
        exercise_lab(s, a)
        self.assertEqual(path.read_bytes(), data)


class Chapter3FlowPreservedTests(unittest.TestCase):
    def play(self, use_lab):
        s = practice3(seed=11)
        a = start_a(s)
        if use_lab:
            exercise_lab(s, a)
        to_incident(s, a)
        if use_lab:
            exercise_lab(s, a)
        s.view_network_diagnosis(a)
        if use_lab:
            exercise_lab(s, a)
        s.respond('reroute')
        if use_lab:
            exercise_lab(s, a)
        st = finish_job(s, a)
        if use_lab:
            exercise_lab(s, a)
        return s, a, st

    def test_full_mission_a_result_is_identical_with_and_without_lab(self):
        plain, a1, st1 = self.play(False)
        lab, a2, st2 = self.play(True)
        self.assertEqual((st1.phase, st1.succeeded, st1.score, st1.recovered_by, st1.downtime),
                         (st2.phase, st2.succeeded, st2.score, st2.recovered_by, st2.downtime))
        self.assertEqual((plain.minute, plain.story.payload()), (lab.minute, lab.story.payload()))
        self.assertTrue(st2.succeeded)
        self.assertEqual(lab.story.chapter3.step, 'b_start')
        self.assertTrue(ledger_matches_center(lab))
        # 작업이 끝난 뒤에도 Lab은 마지막 상태(백업 경로 사용, 전송 없음)를 일관되게 보여 줍니다.
        o = observe(lab, a2)
        self.assertEqual((o.phase, o.tone, o.transferring, o.network.active_path), ('finished', 'done', False, 'backup'))
        self.assertEqual(run_command(f'ping -c 1 {o.target_address}', o).facts['received'], 1)

    def test_failed_responses_are_reflected_and_unchanged(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        s.respond('compress')
        o = observe(s, a)
        self.assertEqual((o.phase, o.network.link_ok, o.network.attempts, o.network.responses), ('paused', False, 1, ('compress',)))
        self.assertEqual(run_command(f'ping -c 1 {o.target_address}', o).facts['received'], 0)

    def test_retry_after_final_failure_shows_new_attempt_state(self):
        s, a = incident_a()
        s.view_network_diagnosis(a)
        for _ in range(3):
            s.respond('compress')
        self.assertEqual(observe(s, a).tone, 'failed')
        s.retry('performance')
        o = observe(s, a)
        # 재처리는 장애를 재현하지 않으므로 새 수행은 주 경로 정상으로 보입니다(같은 게임 상태).
        self.assertEqual((o.phase, o.network.primary_up, o.playthrough_id), ('recovering', True, s.runs[a].playthrough_id))
        self.assertTrue(ledger_matches_center(s))


class CompatibilityTests(unittest.TestCase):
    def test_resume_after_lab_use_keeps_progress(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'resume.db'
        s = practice3(open_db(self, path))
        a = start_a(s)
        to_incident(s, a)
        exercise_lab(s, a)
        expected = observe(s, a)
        payload = s.story.payload()
        s.close()
        s = GameSession(open_db(self, path), mode='story')
        self.assertEqual(s.story.payload(), payload)
        self.assertEqual(observe(s, a), expected)
        s.view_network_diagnosis(a)
        s.respond('reroute')
        self.assertTrue(observe(s, a).network.link_ok)

    def test_other_chapters_and_free_mode_are_untouched(self):
        for kwargs in ({'mode': 'free'}, {'mode': 'story'}, {'mode': 'story', 'start_chapter': 2},
                       {'mode': 'story', 'start_chapter': '3b'}):
            s = GameSession(Database(':memory:'), seed=4, **kwargs)
            before = snapshot(s)
            self.assertTrue(lab_support(s))
            self.assertEqual(snapshot(s), before)
        free = GameSession(Database(':memory:'), seed=4, incident_chance=0)
        free.choose_plan('performance')
        free.advance_time(30)
        self.assertEqual(free.current.state.phase, 'running')
        self.assertTrue(lab_support(free))

    def test_main_wires_lab_as_read_only_entry(self):
        main = (ROOT / 'main.py').read_text(encoding='utf-8')
        self.assertIn("ActionButton(tools, 'Engineering Lab (Prototype)', self.open_engineering_lab", main)
        body = main.split('def open_engineering_lab', 1)[1].split('\n    def ', 1)[0]
        self.assertIn('lab_support(self.session, rid)', body)
        self.assertNotIn('_perform', body)          # 여는 동작은 세션 작업을 실행하지 않습니다.
        lab = (ROOT / 'engineering_lab.py').read_text(encoding='utf-8')
        for forbidden in ('advance_time', 'respond(', 'choose_plan', '_atomic', 'save(', 'view_network_diagnosis'):
            self.assertNotIn(forbidden, lab, forbidden)

    def test_highlight_is_deferred_until_story_popup_on_step_change(self):
        """Chapter 1 GPU·전력 확인 직후 다음 대상 강조가 순간적으로 나타났다 사라지던 문제의 수정 위치."""
        main = (ROOT / 'main.py').read_text(encoding='utf-8')
        perform = main.split('    def _perform(self, action):', 1)[1].split('\n    def ', 1)[0]
        self.assertLess(perform.index('self.highlight_deferred = bool('), perform.index('self.refresh()'))
        self.assertLess(perform.index('self.show_story_event()'), perform.rindex('self.update_tutorial_highlight()'))
        highlight = main.split('    def update_tutorial_highlight(self):', 1)[1].split('\n    def ', 1)[0]
        self.assertIn("if getattr(self, 'highlight_deferred', False):", highlight)


if __name__ == '__main__':
    unittest.main()
