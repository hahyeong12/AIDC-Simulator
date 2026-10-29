"""고객별 요구량과 선택에 따른 실제 결과를 검증합니다."""
import unittest

from game import CUSTOMER_PLANS, DataCenter, GameState, plans_for


class CustomerProfileTests(unittest.TestCase):
    def test_customer_allocations_and_exact_release(self):
        expected = {
            "싱가포르": [(7, 7, 5), (4, 4, 3)],
            "일본": [(3, 4, 3), (2, 2, 2)],
            "미국": [(6, 6, 6), (4, 3, 5)],
        }
        for country, requirements in expected.items():
            for mode, values in zip(("performance", "economy"), requirements):
                with self.subTest(country=country, mode=mode):
                    center = DataCenter()
                    center.allocate(1, 1)
                    state = GameState(center=center, country=country)
                    state.choose_plan(mode)
                    self.assertEqual((state.gpu_used, state.power_used, state.network_needed), values)
                    state.resolve("reroute")
                    self.assertEqual((center.gpu_used, center.power_used), (1, 1))

    def test_same_response_has_customer_specific_outcome(self):
        results = []
        for country in CUSTOMER_PLANS:
            state = GameState(country=country)
            state.choose_plan("economy")
            state.resolve("compress")
            results.append(state.succeeded)
        self.assertEqual(results, [True, True, False])

    def test_all_combinations_score_range_and_no_resource_leaks(self):
        for country in CUSTOMER_PLANS:
            for mode in ("performance", "economy"):
                for response in ("reroute", "compress", "ignore"):
                    with self.subTest(country=country, mode=mode, response=response):
                        state = GameState(country=country)
                        state.choose_plan(mode)
                        state.resolve(response)
                        self.assertTrue(0 <= state.score <= 100)
                        self.assertEqual((state.center.gpu_used, state.center.power_used), (0, 0))

    def test_insufficient_gpu_or_power_is_atomic_for_every_profile(self):
        for country in CUSTOMER_PLANS:
            plan = plans_for(country)["economy"]
            for center in (DataCenter(gpu_total=plan["gpu"] - 1),
                           DataCenter(power_total=plan["power"] - 1)):
                state = GameState(center=center, country=country)
                with self.assertRaises(ValueError):
                    state.choose_plan("economy")
                self.assertEqual((center.gpu_used, center.power_used), (0, 0))
                self.assertEqual(state.phase, "ready")

    def test_unknown_legacy_customer_uses_default_rules(self):
        self.assertEqual(plans_for("한국"), plans_for("싱가포르"))
