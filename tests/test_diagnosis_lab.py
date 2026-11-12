"""v0.9-4a-2 [네트워크 진단] 결과창 → Engineering Lab [네트워크 구조] 이동. Tk 창을 만들지 않는 검증.

이동 버튼은 Lab에서 관찰할 수 있는 장애일 때만 보이고(diagnosis_lab_target), 이동은 화면 전환일 뿐
게임 시간·자원·점수·학습 진도·고객 동의를 바꾸지 않습니다. Lab 모드(미리보기/연수/연습)와 Stage 권한은 기존 규칙 그대로입니다.
"""
from copy import deepcopy
from pathlib import Path
import ast
import unittest

from database import Database
from lab_model import LAB_NETWORK_TAB, diagnosis_lab_target, lab_mode
from session import GameSession
from tests.test_chapter3 import practice3, start_a, to_incident, incident_b
from tests.test_training import regular_after_3b, lab_practice, to_training_incident, game_snapshot

ROOT = Path(__file__).resolve().parents[1]


def frozen(s):
    return game_snapshot(s), deepcopy(s.story.payload()) if s.story else None


class TargetTests(unittest.TestCase):
    def test_chapter3a_mission_a_opens_preview_network_tab_without_changing_anything(self):
        s = practice3()
        a = start_a(s)
        to_incident(s, a)
        s.view_network_diagnosis(a)                     # 기존 진단 확인(기존 동작)
        before = frozen(s)
        for _ in range(3):
            self.assertEqual(diagnosis_lab_target(s, a), ('preview', LAB_NETWORK_TAB))
        self.assertEqual(frozen(s), before)             # 조회만: 시간·자원·점수·동의·스토리 기록 불변
        # 미리보기에서는 심화 명령어 잠금이 그대로입니다.
        with self.assertRaises(ValueError):
            s.training_command('terminal', 'ip route', 'terminal')
        self.assertEqual(lab_mode(s, a)[0], 'preview')

    def test_unsupported_requests_get_no_move_button(self):
        s, b = incident_b()                              # 미션 B(대역폭 부족)는 Lab 미지원
        s.view_network_diagnosis(b)
        self.assertIsNone(diagnosis_lab_target(s, b))
        free = GameSession(Database(':memory:'), seed=2)
        self.assertIsNone(diagnosis_lab_target(free, free.selected_id))

    def test_training_and_practice_follow_existing_lab_modes(self):
        s = regular_after_3b()
        old_a = s.story.chapter3.request_ids[0]
        rid = s.start_training()
        to_training_incident(s)
        self.assertEqual(diagnosis_lab_target(s, rid), ('training', LAB_NETWORK_TAB))
        self.assertIsNone(diagnosis_lab_target(s, old_a))   # Lab이 열 요청(연수 요청)과 다르면 버튼 없음
        before = frozen(s)
        diagnosis_lab_target(s, rid)
        self.assertEqual(frozen(s), before)
        with self.assertRaises(ValueError):                  # 정규 연수 Stage 잠금은 그대로
            s.training_command('terminal', 'ip route', 'terminal')
        p = lab_practice()
        prid = to_training_incident(p)
        self.assertEqual(diagnosis_lab_target(p, prid), ('practice', LAB_NETWORK_TAB))


class WiringTests(unittest.TestCase):
    def test_dialog_keeps_close_button_and_adds_lab_button_only_when_given(self):
        text = (ROOT / 'network_dialog.py').read_text(encoding='utf-8')
        tree = ast.parse(text)
        dialog = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'NetworkDiagnosisDialog')
        body = ast.get_source_segment(text, dialog)
        self.assertIn("def __init__(self, parent, diagnosis, on_open_lab=None)", body)
        self.assertIn("if on_open_lab is not None:", body)
        self.assertIn("'네트워크 구조 자세히 보기'", body)
        self.assertIn("ActionButton(bottom, '진단 확인 · 대응 선택', self.destroy)", body)   # [확인]은 닫기만
        open_lab = body[body.index('def open_lab'):]
        self.assertLess(open_lab.index('self.destroy()'), open_lab.index('after_idle(callback)'))   # 먼저 닫고 다음에 엶
        self.assertIn('self.on_open_lab = None', open_lab)                                       # 중복 실행 방지
        self.assertNotIn('grab_set', text)
        hardware = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'HardwareDiagnosisDialog')
        self.assertNotIn('on_open_lab', ast.get_source_segment(text, hardware))                 # 서버 장애 진단은 그대로

    def test_main_passes_button_only_for_supported_incidents_and_opens_network_tab(self):
        main = (ROOT / 'main.py').read_text(encoding='utf-8')
        self.assertIn("target = diagnosis_lab_target(self.session, rid)", main)
        self.assertIn("on_open_lab = (lambda r=rid: self.open_lab_network(r)) if target else None", main)
        segment = main[main.index('    def open_lab_network'):main.index('    def open_engineering_lab')]
        self.assertIn('self.open_engineering_lab(rid)', segment)
        self.assertIn('lab.show_tab(target[1])', segment)
        for call in ('_perform(', 'advance_time(', 'choose_plan(', 'respond(', 'select(', '.save('):
            self.assertNotIn(call, segment)                  # 이동은 세션 작업을 실행하지 않음


if __name__ == '__main__':
    unittest.main()
