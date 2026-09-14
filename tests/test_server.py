import os
import atexit
import shutil
import sys
import tempfile
import types
import unittest


TEST_DATA = tempfile.mkdtemp(prefix="freetify-tests-")
os.environ["XDG_DATA_HOME"] = TEST_DATA
atexit.register(shutil.rmtree, TEST_DATA, ignore_errors=True)

from server import analyze, event_ticks


class FakeParser:
    def __init__(self, path):
        self.path = path

    def parse_header(self):
        return {"map_name": "de_mirage", "playback_ticks": 128}

    def parse_event(self, name):
        return {
            "player_death": [{"tick": 64, "attacker_name": "Alpha", "user_name": "Bravo", "weapon": "ak47", "headshot": True, "assister_name": "Charlie"}],
            "player_hurt": [{"tick": 48, "attacker_name": "Alpha", "dmg_health": 42, "weapon": "hegrenade"}],
            "player_blind": [{"tick": 32, "attacker_name": "Charlie"}],
            "round_end": [{"tick": 96, "winner": "CT"}],
        }.get(name, [])

    def parse_player_info(self):
        return [{"player_name": "Alpha", "player_steamid": "76561198000000001"}, {"player_name": "Bravo"}, {"player_name": "Charlie"}]

    def parse_ticks(self, fields, ticks=None):
        if "kills_total" in fields:
            return [{"player_name": "Alpha", "kills_total": 1, "deaths_total": 0, "assists_total": 0, "headshot_kills_total": 1, "damage_total": 42, "utility_damage_total": 42, "enemies_flashed_total": 0, "team_num": 3}]
        return [{"X": 100, "Y": 200, "player_name": "Alpha", "team_num": 3, "game_time": 1.0}]


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        fake_module = types.ModuleType("demoparser2")
        fake_module.DemoParser = FakeParser
        self.previous = sys.modules.get("demoparser2")
        sys.modules["demoparser2"] = fake_module

    def tearDown(self):
        if self.previous is None:
            sys.modules.pop("demoparser2", None)
        else:
            sys.modules["demoparser2"] = self.previous

    def test_analysis_builds_report_from_events_and_ticks(self):
        result = analyze("fake.dem", "fake.dem", preferred_steamid="76561198000000001")
        players = {player["player"]: player for player in result["players"]}
        self.assertEqual(result["primary_player"], "Alpha")
        self.assertEqual(result["match_result"], "WIN")
        self.assertEqual(set(players), {"Alpha", "Bravo", "Charlie"})
        self.assertEqual(players["Alpha"]["kills"], 1)
        self.assertEqual(players["Charlie"]["assists"], 1)
        self.assertEqual(players["Alpha"]["utility_damage"], 42)
        self.assertGreater(players["Alpha"]["impact"], 0)
        self.assertTrue(result["positions"])

    def test_event_ticks_ignores_invalid_values(self):
        self.assertEqual(event_ticks([{"tick": "64"}, {"tick": "bad"}, {"tick": None}]), [64])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TEST_DATA, ignore_errors=True)
