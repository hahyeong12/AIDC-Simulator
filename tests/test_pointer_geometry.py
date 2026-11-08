"""v0.9-1f: 안내 문구 위치의 순수 좌표 계산. Tk 창을 만들지 않습니다."""
import unittest

from tutorial_highlight import pointer_geometry


class PointerGeometryTests(unittest.TestCase):
    def test_pointer_is_centered_above_target_and_arrow_hits_center(self):
        # 오른쪽 좁은 탭: 패널 왼쪽 끝이 아니라 탭 중심 위에 놓입니다.
        rect = (860, 150, 80, 24)
        x, y, below, arrow = pointer_geometry(rect, (1000, 650), (110, 36))
        self.assertFalse(below)
        self.assertEqual(y, 150-36-3)
        self.assertEqual(x+arrow, 860+40)

    def test_sits_over_target_not_neighbour_tab(self):
        inspector, preview = (750, 150, 90, 24), (845, 150, 90, 24)
        px, _, _, pa = pointer_geometry(preview, (1000, 650), (110, 36))
        self.assertGreater(px+pa, inspector[0]+inspector[2])
        self.assertTrue(preview[0] <= px+pa <= preview[0]+preview[2])

    def test_below_when_no_room_above_and_arrow_flips(self):
        x, y, below, arrow = pointer_geometry((100, 5, 80, 24), (1000, 650), (110, 36))
        self.assertTrue(below)
        self.assertEqual(y, 5+24+3)

    def test_clamped_to_container_but_arrow_still_points_at_target(self):
        x, y, below, arrow = pointer_geometry((960, 300, 40, 24), (1000, 650), (150, 36))
        self.assertEqual(x, 1000-150)
        self.assertEqual(x+arrow, 980)
        x, _, _, arrow = pointer_geometry((0, 300, 30, 24), (1000, 650), (150, 36))
        self.assertEqual(x, 0)
        self.assertEqual(x+arrow, 15)

    def test_recomputes_for_new_rectangle_without_fixed_offsets(self):
        a = pointer_geometry((100, 300, 80, 24), (1000, 650), (110, 36))
        b = pointer_geometry((400, 400, 120, 30), (1000, 650), (110, 36))
        self.assertEqual((a[0]+a[3], b[0]+b[3]), (140, 460))
        self.assertEqual((a[1], b[1]), (300-39, 400-39))


if __name__ == '__main__':
    unittest.main()
