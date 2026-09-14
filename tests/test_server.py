import os
import atexit
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path


TEST_DATA = tempfile.mkdtemp(prefix="freetify-tests-")
os.environ["XDG_DATA_HOME"] = TEST_DATA
atexit.register(shutil.rmtree, TEST_DATA, ignore_errors=True)

import server
from server import analyze, event_ticks, valid_steam_return


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
            "weapon_fire": [{"tick": 47, "user_name": "Alpha", "weapon": "ak47"}, {"tick": 48, "user_name": "Alpha", "weapon": "ak47"}],
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
        self.assertEqual(result["primary_team"], 3)
        self.assertEqual(players["Alpha"]["team_num"], 3)
        self.assertEqual(result["match_result"], "WIN")
        self.assertEqual(set(players), {"Alpha", "Bravo", "Charlie"})
        self.assertEqual(players["Alpha"]["kills"], 1)
        self.assertEqual(players["Charlie"]["assists"], 1)
        self.assertEqual(players["Alpha"]["utility_damage"], 42)
        self.assertEqual(players["Alpha"]["adr"], 42.0)
        self.assertEqual(players["Alpha"]["impact_score"], 42.0)
        self.assertEqual(players["Alpha"]["accuracy"], 50.0)
        self.assertGreater(players["Alpha"]["aim_rating"], 0)
        self.assertGreaterEqual(players["Alpha"]["utility_rating"], 0)
        self.assertGreater(players["Alpha"]["impact"], 0)
        self.assertTrue(result["positions"])

    def test_event_ticks_ignores_invalid_values(self):
        self.assertEqual(event_ticks([{"tick": "64"}, {"tick": "bad"}, {"tick": None}]), [64])

    def test_steam_return_accepts_query_and_rejects_other_host(self):
        expected = "http://127.0.0.1:4321/auth/steam/callback"
        self.assertTrue(valid_steam_return(expected + "?openid.mode=id_res", expected))
        self.assertFalse(valid_steam_return("http://evil.example/auth/steam/callback", expected))

    def test_steam_state_persists_locally(self):
        original_file = server.STATE_FILE
        original_session = server.STEAM_SESSION
        original_config = server.STEAM_CONFIG
        original_refresh_token = server.STEAM_GC_REFRESH_TOKEN
        state_file = Path(TEST_DATA) / "persisted-state.json"
        try:
            server.STATE_FILE = state_file
            server.STEAM_SESSION = {"steamid": "76561198000000001"}
            server.STEAM_CONFIG = {"api_key": "test-api-key-123456", "auth_code": "ABCD-EFGH-IJKL", "share_code": "CSGO-AbCdE-FgHiJ-KlMnO-PqRsT-UvWxY"}
            server.STEAM_GC_REFRESH_TOKEN = "test-local-refresh-token"
            server.save_state()
            server.STEAM_SESSION = None
            server.STEAM_CONFIG = {}
            server.STEAM_GC_REFRESH_TOKEN = None
            session, config, refresh_token = server.load_state()
            self.assertEqual(session, {"steamid": "76561198000000001"})
            self.assertEqual(config["auth_code"], "ABCD-EFGH-IJKL")
            self.assertEqual(config["share_code"], "CSGO-AbCdE-FgHiJ-KlMnO-PqRsT-UvWxY")
            self.assertEqual(refresh_token, "test-local-refresh-token")
        finally:
            server.STATE_FILE = original_file
            server.STEAM_SESSION = original_session
            server.STEAM_CONFIG = original_config
            server.STEAM_GC_REFRESH_TOKEN = original_refresh_token

    def test_library_replaces_reports_with_the_same_match_identity(self):
        original_file = server.LIBRARY_FILE
        library_file = Path(TEST_DATA) / "library.json"
        try:
            server.LIBRARY_FILE = library_file
            server.store_analysis({"stored_file": "first.dem", "demo_hash": "same-demo", "match_id": "match-1", "value": "old"})
            server.store_analysis({"stored_file": "renamed.dem", "demo_hash": "same-demo", "match_id": "match-1", "value": "new"})
            library = server.load_library()
            self.assertEqual(len(library), 1)
            self.assertEqual(library[0]["value"], "new")
            self.assertTrue(library[0]["saved_at"])
        finally:
            server.LIBRARY_FILE = original_file


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TEST_DATA, ignore_errors=True)
