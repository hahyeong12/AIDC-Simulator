"""python -m unittest discover -s tests -v"""
import unittest
from game import GameState
from database import Database


class GameTests(unittest.TestCase):
    def test_high_performance_reroute_success(self):
        state = GameState()
        state.choose_plan("performance")
        self.assertEqual(state.network_available, 2)
        state.resolve("reroute")
        self.assertTrue(state.succeeded)
        self.assertEqual(state.score, 90)

    def test_high_performance_compress_failure(self):
        state = GameState()
        state.choose_plan("performance")
        state.resolve("compress")
        self.assertFalse(state.succeeded)
        self.assertEqual((state.network_needed, state.network_available), (3, 2))

    def test_economy_compress_success(self):
        state = GameState()
        state.choose_plan("economy")
        state.resolve("compress")
        self.assertTrue(state.succeeded)
        self.assertEqual(state.score, 85)

    def test_invalid_phase(self):
        with self.assertRaises(ValueError):
            GameState().resolve("reroute")

    def test_database_roundtrip(self):
        db = Database(":memory:")
        mission = db.get_mission()
        run_id = db.create_playthrough(mission["id"], "economy")
        db.add_log(run_id, "테스트 이벤트")
        db.save_result(run_id, "compress", True, 85, "성공")
        history = db.get_recent_results()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["score"], 85)
        self.assertEqual(db.get_logs(run_id)[0]["message"], "테스트 이벤트")
        db.close()


if __name__ == "__main__":
    unittest.main()
