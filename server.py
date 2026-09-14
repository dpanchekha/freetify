#!/usr/bin/env python3
"""Local-only Freetify server and CS2 demo analysis endpoint."""
import bz2
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import uuid
import urllib.parse
import urllib.request
import urllib.error
import re
from datetime import datetime, timezone
from pathlib import Path
from email.parser import BytesParser
from email.policy import default
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def app_data_root():
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Freetify"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Freetify"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Freetify"


DATA_ROOT = app_data_root()
DEMO_ROOT = DATA_ROOT / "demos"
DEMO_ROOT.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_ROOT / "state.json"
LIBRARY_FILE = DATA_ROOT / "library.json"
REPORT_ROOT = DATA_ROOT / "reports"
REPORT_ROOT.mkdir(parents=True, exist_ok=True)
LIBRARY_LOCK = threading.Lock()
STEAM_SESSION = None
STEAM_CONFIG = {}
STEAM_GC_REFRESH_TOKEN = None
STEAM_ERROR = None
STEAM_CALLBACK = ""
DOWNLOAD_JOBS = {}
DOWNLOAD_JOBS_LOCK = threading.Lock()


def load_state():
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return state.get("steam_session"), state.get("steam_config", {}), state.get("steam_gc_refresh_token")
    except (OSError, ValueError, TypeError):
        return None, {}, None


def save_state():
    state = {
        "steam_session": STEAM_SESSION,
        "steam_config": STEAM_CONFIG,
        "steam_gc_refresh_token": STEAM_GC_REFRESH_TOKEN,
    }
    temporary = STATE_FILE.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(state), encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, STATE_FILE)
        try:
            STATE_FILE.chmod(0o600)
        except OSError:
            pass
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_library():
    try:
        library = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
        if not isinstance(library, list):
            return []
        unique, seen, migrated = [], set(), False
        for item in library:
            if not isinstance(item, dict):
                continue
            key = analysis_key(item)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            if item.get("report_file"):
                unique.append(item)
            else:
                report_file = hashlib.sha256(key.encode()).hexdigest() + ".json"
                try:
                    (REPORT_ROOT / report_file).write_text(json.dumps(item), encoding="utf-8")
                    migrated = True
                except OSError:
                    pass
                summary = analysis_summary(item)
                summary["report_file"] = report_file
                unique.append(summary)
        if migrated:
            try:
                LIBRARY_FILE.write_text(json.dumps(unique[:100]), encoding="utf-8")
            except OSError:
                pass
        return sorted(unique, key=lambda item: str(item.get("saved_at") or ""), reverse=True)
    except (OSError, ValueError, TypeError):
        return []


def store_analysis(result):
    """Keep local analysis reports independent of browser localStorage."""
    stored = clean(result)
    stored["saved_at"] = datetime.now(timezone.utc).isoformat()
    result["saved_at"] = stored["saved_at"]
    key = analysis_key(stored)
    if not key:
        return
    with LIBRARY_LOCK:
        report_file = hashlib.sha256(key.encode()).hexdigest() + ".json"
        (REPORT_ROOT / report_file).write_text(json.dumps(stored), encoding="utf-8")
        library = [item for item in load_library() if analysis_key(item) != key]
        summary = analysis_summary(stored)
        summary["report_file"] = report_file
        library.insert(0, summary)
        temporary = LIBRARY_FILE.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(library[:100]), encoding="utf-8")
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            os.replace(temporary, LIBRARY_FILE)
            try:
                LIBRARY_FILE.chmod(0o600)
            except OSError:
                pass
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def update_gc_match_times(matches):
    """Backfill the actual CS2 match time for locally saved GC downloads."""
    times = {}
    for match in matches if isinstance(matches, list) else []:
        if not isinstance(match, dict):
            continue
        match_id = str(match.get("matchid") or match.get("match_id") or match.get("id") or "").strip()
        try:
            match_time = int(float(match.get("matchtime")) * 1000)
        except (TypeError, ValueError):
            continue
        if match_id and 946684800000 <= match_time <= 4102444800000:
            times[match_id] = match_time
    if not times:
        return
    with LIBRARY_LOCK:
        library, changed = load_library(), False
        for summary in library:
            match_time = times.get(str(summary.get("match_id") or ""))
            if not match_time or summary.get("match_time") == match_time:
                continue
            summary["match_time"] = match_time
            report_file = Path(str(summary.get("report_file") or "")).name
            if report_file:
                try:
                    report_path = REPORT_ROOT / report_file
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    report["match_time"] = match_time
                    report_path.write_text(json.dumps(report), encoding="utf-8")
                except (OSError, ValueError, TypeError):
                    pass
            changed = True
        if changed:
            temporary = LIBRARY_FILE.with_suffix(".tmp")
            temporary.write_text(json.dumps(library[:100]), encoding="utf-8")
            os.replace(temporary, LIBRARY_FILE)


def analysis_key(result):
    """Stable identity: a Steam match id wins, then content hash, then filename."""
    if not isinstance(result, dict):
        return ""
    for field in ("match_id", "demo_hash", "stored_file", "file"):
        value = str(result.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return ""


def demo_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analysis_summary(result):
    """Small download response; the full report remains in the local library."""
    fields = ("file", "stored_file", "match_id", "demo_hash", "match_time", "saved_at", "metric_model", "primary_player", "primary_team", "header", "round_wins", "round_losses", "match_result", "players", "rounds", "report_file", "value")
    summary = {field: result.get(field) for field in fields if field in result}
    summary["summary_only"] = True
    return clean(summary)


STEAM_SESSION, STEAM_CONFIG, STEAM_GC_REFRESH_TOKEN = load_state()


class SteamGameCoordinator:
    """Run the Node Steam/CS2 helper as a private JSON-lines child process."""

    def __init__(self):
        self.process = None
        self.lock = threading.Lock()
        self.state = "disconnected"
        self.detail = "Not connected to CS2 match history."
        self.steamid = None
        self.qr_image = None
        self.matches = []
        self.started_with_token = False

    def node_command(self):
        packaged = APP_ROOT / ("node.exe" if sys.platform.startswith("win") else "node")
        if packaged.is_file():
            return str(packaged)
        return shutil.which("node")

    def ensure_process(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return True
            node = self.node_command()
            script = APP_ROOT / "steam_gc_sidecar.js"
            if not node or not script.is_file():
                self.state = "unavailable"
                self.detail = "The local Steam bridge is missing. Reinstall Freetify."
                return False
            try:
                env = os.environ.copy()
                env["NODE_PATH"] = str(APP_ROOT / "node_modules")
                self.process = subprocess.Popen(
                    [node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1, cwd=str(APP_ROOT), env=env,
                )
            except OSError as exc:
                self.state = "unavailable"
                self.detail = f"Could not start the local Steam bridge: {exc}"
                return False
            threading.Thread(target=self._read_output, args=(self.process.stdout,), daemon=True).start()
            threading.Thread(target=self._read_errors, args=(self.process.stderr,), daemon=True).start()
            return True

    def _read_errors(self, stream):
        for line in stream:
            print(f"Steam GC bridge: {line.rstrip()}", file=sys.stderr, flush=True)

    def _read_output(self, stream):
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                print(f"Steam GC bridge sent invalid JSON: {line.rstrip()}", file=sys.stderr, flush=True)
                continue
            self._handle_event(event)

    def _handle_event(self, event):
        global STEAM_GC_REFRESH_TOKEN, STEAM_SESSION
        event_type = event.get("type")
        with self.lock:
            if event.get("state"):
                self.state = event["state"]
            if event.get("detail"):
                self.detail = str(event["detail"])
            if event.get("steamid"):
                self.steamid = str(event["steamid"])
            if event_type == "qr":
                self.qr_image = event.get("image")
            elif event_type == "matches":
                self.matches = event.get("matches") or []
                update_gc_match_times(self.matches)
                self.state = "ready"
                self.detail = f"Found {len(self.matches)} recent CS2 match{'es' if len(self.matches) != 1 else ''}."
            elif event_type == "refresh_token":
                token = event.get("refresh_token")
                if isinstance(token, str) and token:
                    STEAM_GC_REFRESH_TOKEN = token
                    self.started_with_token = True
                    if self.steamid:
                        STEAM_SESSION = {"steamid": self.steamid}
                    save_state()
            elif event_type == "error":
                self.state = "error"
                print(f"Steam GC bridge error: {self.detail}", file=sys.stderr, flush=True)

    def send(self, payload):
        if not self.ensure_process():
            return False
        try:
            with self.lock:
                self.process.stdin.write(json.dumps(payload) + "\n")
                self.process.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            self.state = "error"
            self.detail = "The local Steam bridge stopped unexpectedly."
            return False

    def start_saved_session(self):
        global STEAM_GC_REFRESH_TOKEN
        if STEAM_GC_REFRESH_TOKEN and not self.started_with_token:
            self.started_with_token = self.send({"type": "connect", "refresh_token": STEAM_GC_REFRESH_TOKEN})
        return self.status()

    def start_qr(self):
        self.qr_image = None
        self.matches = []
        return self.send({"type": "start_qr"})

    def request_recent_matches(self):
        return self.send({"type": "recent_matches"})

    def status(self):
        with self.lock:
            return {
                "available": self.state != "unavailable",
                "connected": self.state in ("ready", "loading_matches"),
                "state": self.state,
                "detail": self.detail,
                "steamid": self.steamid,
                "qr_image": self.qr_image,
                "match_count": len(self.matches),
            }

    def shutdown(self):
        with self.lock:
            process = self.process
        if not process or process.poll() is not None:
            return
        try:
            process.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
            process.stdin.flush()
            process.wait(timeout=3)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            try:
                process.terminate()
            except OSError:
                pass


STEAM_GC = SteamGameCoordinator()


def valid_steam_return(returned, expected):
    """Check the OpenID return URL without requiring one exact URL spelling."""
    try:
        actual_url = urllib.parse.urlsplit(returned)
        expected_url = urllib.parse.urlsplit(expected)
        return bool(
            actual_url.scheme
            and actual_url.hostname
            and actual_url.scheme.lower() == expected_url.scheme.lower()
            and actual_url.hostname.lower() == expected_url.hostname.lower()
            and actual_url.port == expected_url.port
            and actual_url.path == expected_url.path
            and not actual_url.username
            and not actual_url.password
        )
    except ValueError:
        return False


def steam_demo_dirs():
    if sys.platform == "darwin":
        roots = [Path.home() / "Library/Application Support/Steam"]
    elif sys.platform.startswith("win"):
        roots = [Path(root) / "Steam" for root in filter(None, [os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")])]
    else:
        roots = [Path.home() / ".steam/steam", Path.home() / ".steam/root", Path.home() / ".local/share/Steam"]
    libraries = set(roots)
    for steam_root in roots:
        config = steam_root / "steamapps/libraryfolders.vdf"
        if config.is_file():
            try:
                text = config.read_text(encoding="utf-8", errors="ignore")
                libraries.update(Path(path.replace("\\\\", "\\")) for path in re.findall(r'"path"\s+"([^"]+)"', text))
            except OSError:
                pass
    locations = []
    for library in libraries:
        locations.extend([library / "steamapps/common/Counter-Strike Global Offensive/game/csgo", library / "steamapps/common/Counter-Strike Global Offensive/game/csgo/replays"])
    return [path for path in locations if path.is_dir()]


def open_uri(uri):
    try:
        if sys.platform.startswith("win"):
            os.startfile(uri)
        elif sys.platform == "darwin":
            if not shutil.which("open"):
                return False
            subprocess.Popen(["open", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            if not shutil.which("xdg-open"):
                return False
            subprocess.Popen(["xdg-open", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def clean(value):
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def records(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return clean(frame.to_dict(orient="records"))
    return clean(frame)


def safe_event(parser, name):
    try:
        return records(parser.parse_event(name))
    except Exception:
        return []


def event_ticks(events):
    ticks = set()
    for event in events:
        try:
            if event.get("tick") is not None:
                ticks.add(int(event["tick"]))
        except (TypeError, ValueError):
            continue
    return sorted(ticks)


def analyze(path, filename, preferred_steamid=None):
    from demoparser2 import DemoParser

    parser = DemoParser(path)
    header = clean(parser.parse_header())
    deaths = safe_event(parser, "player_death")
    hurts = safe_event(parser, "player_hurt")
    blinds = safe_event(parser, "player_blind")
    shots = safe_event(parser, "weapon_fire")
    rounds = safe_event(parser, "round_end")
    round_starts = safe_event(parser, "round_start")
    round_freeze_ends = safe_event(parser, "round_freeze_end")
    bomb_plants = safe_event(parser, "bomb_planted")
    bomb_defuses = safe_event(parser, "bomb_defused")
    bomb_drops = safe_event(parser, "bomb_dropped")
    bomb_pickups = safe_event(parser, "bomb_pickup")
    smoke_detonates = safe_event(parser, "smokegrenade_detonate")
    smoke_expires = safe_event(parser, "smokegrenade_expired")
    inferno_starts = safe_event(parser, "inferno_startburn")
    inferno_expires = safe_event(parser, "inferno_expire")
    flash_detonates = safe_event(parser, "flashbang_detonate")
    he_detonates = safe_event(parser, "hegrenade_detonate")
    decoys = safe_event(parser, "decoy_started")
    players = records(parser.parse_player_info())
    snapshots = []
    round_ticks = event_ticks(rounds)
    if round_ticks:
        try:
            snapshots = records(parser.parse_ticks(["player_name", "kills_total", "deaths_total", "assists_total", "headshot_kills_total", "damage_total", "utility_damage_total", "enemies_flashed_total", "team_num"], ticks=[round_ticks[-1]]))
        except Exception:
            snapshots = []
    positions = []
    max_tick = max(round_ticks, default=0)
    if not max_tick:
        try:
            max_tick = int(header.get("playback_ticks") or header.get("ticks") or 0)
        except (TypeError, ValueError):
            max_tick = 0
    if max_tick:
        try:
            # A demo used to be reduced to roughly 240 snapshots.  That was
            # enough for a static heatmap but made the playback appear to jump
            # between locations. Keep up to ~30,000 real game snapshots; this
            # gives long 64-tick matches roughly 20 position updates/sec.
            sample_step = max(2, max_tick // 30000)
            sample_ticks = list(range(0, max_tick + 1, sample_step))
            positions = records(parser.parse_ticks(["X", "Y", "yaw", "health", "armor_value", "helmet", "has_defuser", "has_bomb", "active_weapon_name", "player_name", "team_num", "game_time"], ticks=sample_ticks))
        except Exception:
            positions = []
    by_player = {}
    for info in players:
        name = info.get("player_name") or info.get("name")
        if name:
            by_player.setdefault(name, {"player": name, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
    for death in deaths:
        attacker = death.get("attacker_name") or death.get("attacker")
        victim = death.get("user_name") or death.get("userid") or death.get("victim_name")
        weapon = death.get("weapon") or "unknown"
        if attacker:
            item = by_player.setdefault(attacker, {"player": attacker, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
            item["kills"] += 1
            item["headshots"] += int(bool(death.get("headshot")))
            item["weapons"][weapon] = item["weapons"].get(weapon, 0) + 1
        if victim:
            item = by_player.setdefault(victim, {"player": victim, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
            item["deaths"] += 1
        assister = death.get("assister_name") or death.get("assister")
        if assister:
            item = by_player.setdefault(assister, {"player": assister, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
            item["assists"] += 1
    for shot in shots:
        shooter = shot.get("user_name") or shot.get("player_name") or shot.get("user") or shot.get("userid")
        if shooter:
            item = by_player.setdefault(shooter, {"player": shooter, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
            item["shots"] = item.get("shots", 0) + 1
    for hurt in hurts:
        attacker = hurt.get("attacker_name") or hurt.get("attacker")
        if attacker:
            item = by_player.setdefault(attacker, {"player": attacker, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
            item["damage"] += int(hurt.get("dmg_health") or hurt.get("damage") or 0)
            item["hits"] = item.get("hits", 0) + 1
            if str(hurt.get("weapon", "")).lower() in ("hegrenade", "molotov", "incgrenade", "inferno", "firecrackerblast"):
                item["utility_damage"] = item.get("utility_damage", 0) + int(hurt.get("dmg_health") or hurt.get("damage") or 0)
    for blind in blinds:
        attacker = blind.get("attacker_name") or blind.get("attacker")
        attacker_team = blind.get("attacker_team") or blind.get("attacker_team_num")
        victim_team = blind.get("user_team") or blind.get("user_team_num")
        if attacker and (attacker_team is None or victim_team is None or str(attacker_team) != str(victim_team)):
            item = by_player.setdefault(attacker, {"player": attacker, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
            item["flashes"] = item.get("flashes", 0) + 1
            item["flash_seconds"] = round(item.get("flash_seconds", 0) + float(blind.get("blind_duration") or blind.get("blind_time") or 0), 2)
    aggregate_fields = {"kills_total": "kills", "deaths_total": "deaths", "assists_total": "assists", "headshot_kills_total": "headshots", "damage_total": "damage", "utility_damage_total": "utility_damage", "enemies_flashed_total": "flashes"}
    for snapshot in snapshots:
        name = snapshot.get("player_name") or snapshot.get("name")
        if not name:
            continue
        item = by_player.setdefault(name, {"player": name, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
        if snapshot.get("team_num") is not None:
            item["team_num"] = snapshot.get("team_num")
        for source, target in aggregate_fields.items():
            if snapshot.get(source) is not None:
                item[target] = max(item.get(target, 0), int(snapshot[source] or 0))
    snapshot_teams = {(snapshot.get("player_name") or snapshot.get("name")): snapshot.get("team_num") for snapshot in snapshots if snapshot.get("player_name") or snapshot.get("name")}
    start_ticks = event_ticks(round_starts)
    for player in by_player.values():
        player.update({"opening_kills": 0, "opening_deaths": 0, "trade_kills": 0, "trade_deaths": 0, "clutches": 0, "rounds_played": 0, "objective_events": 0})
    def round_number(tick):
        return sum(1 for start in start_ticks if start <= tick) if start_ticks else 1
    opening_rounds = set()
    for death in sorted(deaths, key=lambda event: int(event.get("tick") or 0)):
        try:
            death_tick = int(death.get("tick") or 0)
        except (TypeError, ValueError):
            continue
        attacker = death.get("attacker_name") or death.get("attacker")
        victim = death.get("user_name") or death.get("victim_name")
        current_round = round_number(death_tick)
        if current_round not in opening_rounds:
            if attacker in by_player:
                by_player[attacker]["opening_kills"] += 1
            if victim in by_player:
                by_player[victim]["opening_deaths"] += 1
            opening_rounds.add(current_round)
    for index, death in enumerate(sorted(deaths, key=lambda event: int(event.get("tick") or 0))):
        try:
            death_tick = int(death.get("tick") or 0)
        except (TypeError, ValueError):
            continue
        attacker = death.get("attacker_name") or death.get("attacker")
        victim = death.get("user_name") or death.get("victim_name")
        for previous in sorted(deaths, key=lambda event: int(event.get("tick") or 0))[:index][::-1]:
            try:
                previous_tick = int(previous.get("tick") or 0)
            except (TypeError, ValueError):
                continue
            if death_tick - previous_tick > 320:
                break
            previous_attacker = previous.get("attacker_name") or previous.get("attacker")
            previous_victim = previous.get("user_name") or previous.get("victim_name")
            if attacker == previous_victim and victim != previous_attacker and attacker in by_player:
                by_player[attacker]["trade_kills"] += 1
                if victim in by_player:
                    by_player[victim]["trade_deaths"] += 1
                break
    for event in bomb_plants + bomb_defuses:
        player_name = event.get("user_name") or event.get("player_name") or event.get("userid")
        if player_name in by_player:
            by_player[player_name]["objective_events"] += 1
    reference = max(by_player.values(), key=lambda player: player.get("kills", 0), default=None)
    reference_team = snapshot_teams.get(reference.get("player")) if reference else None
    teams_by_round_tick = {}
    if reference and round_ticks:
        try:
            for team_sample in records(parser.parse_ticks(["player_name", "team_num"], ticks=round_ticks)):
                if (team_sample.get("player_name") or team_sample.get("name")) == reference.get("player") and team_sample.get("tick") is not None:
                    teams_by_round_tick[int(team_sample["tick"])] = team_sample.get("team_num")
        except Exception:
            pass
    round_wins = round_losses = 0
    for round_event in rounds:
        winner = str(round_event.get("winner", "")).upper()
        winner_team = 3 if "CT" in winner else 2 if winner in ("T", "TERRORIST") else None
        try:
            round_tick = int(round_event.get("tick"))
        except (TypeError, ValueError):
            round_tick = -1
        round_team = teams_by_round_tick.get(round_tick, reference_team)
        if winner_team and round_team:
            try:
                same_team = int(round_team) == winner_team
            except (TypeError, ValueError):
                same_team = False
            if same_team:
                round_wins += 1
            else:
                round_losses += 1
    match_result = "WIN" if round_wins > round_losses else "LOSS" if round_losses > round_wins else "TIE" if rounds else "UNKNOWN"
    rounds_seen = max(len(rounds), 1)
    for player in by_player.values():
        player["kd"] = round(player["kills"] / max(player["deaths"], 1), 2)
        player["headshot_rate"] = round(player["headshots"] / max(player["kills"], 1) * 100, 1)
        player["adr"] = round(player.get("damage", 0) / rounds_seen, 2)
        player["shots"] = player.get("shots", 0)
        player["hits"] = player.get("hits", 0)
        player["accuracy"] = round(player["hits"] / max(player["shots"], 1) * 100, 1) if player["shots"] else None
        # Legacy compatibility fields. The UI presents the raw measurements
        # rather than treating these convenience blends as skill ratings.
        accuracy_component = (player["accuracy"] or 0) / 100
        headshot_component = player["headshot_rate"] / 100
        player["aim_rating"] = round(100 * (0.65 * accuracy_component + 0.35 * headshot_component), 1)
        utility_per_round = player.get("utility_damage", 0) / rounds_seen
        flashes_per_round = player.get("flashes", 0) / rounds_seen
        player["utility_rating"] = round(min(100, 100 * (0.7 * min(utility_per_round / 20, 1) + 0.3 * min(flashes_per_round / 1.5, 1))), 1)
        player["kast"] = round((player["kills"] + player["assists"] + (rounds_seen - player["deaths"])) / max(rounds_seen, 1) * 100, 1)
        player["opening_diff"] = player["opening_kills"] - player["opening_deaths"]
        player["trade_diff"] = player["trade_kills"] - player["trade_deaths"]
        # A deliberately transparent combat-output measure, kept separate from
        # the broader event-based rating below.
        player["damage_impact"] = round(player["kd"] * player["adr"], 2)
        player["impact_score"] = round((player["kills"] + 0.5 * player["assists"] + player.get("damage", 0) / 100 + 0.6 * player["opening_kills"] + 0.4 * player["trade_kills"] + player.get("utility_damage", 0) / 100 + 0.15 * player.get("flashes", 0) + 0.8 * player["objective_events"]) / rounds_seen, 2)
    for player in by_player.values():
        # Rating is the raw holistic event score per round, not a fabricated
        # 0–100 rank. Scoreboards sort players by this number.
        player["rating"] = player["impact_score"]
        player["match_rating"] = player["rating"]  # Backward-compatible saved reports.
        player["impact"] = player["impact_score"]
    primary_player = None
    if preferred_steamid:
        matching_info = next((info for info in players if str(info.get("player_steamid") or info.get("steamid") or info.get("steam_id")) == str(preferred_steamid)), None)
        if matching_info:
            primary_player = matching_info.get("player_name") or matching_info.get("name")
    if not primary_player and reference:
        primary_player = reference.get("player")
    return clean({"file": filename, "metric_model": "event-impact-v2", "primary_player": primary_player, "primary_team": snapshot_teams.get(primary_player), "header": header, "rounds": rounds, "round_starts": round_starts, "round_freeze_ends": round_freeze_ends, "round_wins": round_wins, "round_losses": round_losses, "match_result": match_result, "positions": positions, "deaths": deaths, "blinds": blinds, "shots": shots, "bomb_plants": bomb_plants, "bomb_defuses": bomb_defuses, "bomb_drops": bomb_drops, "bomb_pickups": bomb_pickups, "smoke_detonates": smoke_detonates, "smoke_expires": smoke_expires, "inferno_starts": inferno_starts, "inferno_expires": inferno_expires, "flash_detonates": flash_detonates, "he_detonates": he_detonates, "decoys": decoys, "players": list(by_player.values()), "capabilities": ["kills", "deaths", "assists", "headshots", "opening duels", "trade kills", "KAST", "objectives", "weapon shots", "weapon hits", "damage", "utility damage", "flashes", "rounds", "player roster", "event positions"]})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_ROOT), **kwargs)

    def do_GET(self):
        global STEAM_SESSION, STEAM_ERROR
        if self.path == "/auth/steam":
            STEAM_ERROR = None
            realm = STEAM_CALLBACK.rsplit("/auth/", 1)[0] + "/"
            identifier_select = "http://specs.openid.net/auth/2.0/identifier_select"
            query = urllib.parse.urlencode({"openid.ns": "http://specs.openid.net/auth/2.0", "openid.mode": "checkid_setup", "openid.return_to": STEAM_CALLBACK, "openid.realm": realm, "openid.identity": identifier_select, "openid.claimed_id": identifier_select})
            self.send_response(302); self.send_header("Location", f"https://steamcommunity.com/openid/login?{query}"); self.end_headers(); return
        if self.path.startswith("/auth/steam/callback"):
            params = {key: values[-1] for key, values in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}
            claimed = params.get("openid.claimed_id", "")
            returned = params.get("openid.return_to", "")
            valid_return = valid_steam_return(returned, STEAM_CALLBACK)
            valid_id = re.fullmatch(r"https?://steamcommunity\.com/openid/id/[0-9]+", claimed, re.IGNORECASE)
            authenticated = False
            if valid_return and valid_id:
                check_data = urllib.parse.urlencode({**params, "openid.mode": "check_authentication"}).encode()
                try:
                    request = urllib.request.Request(
                        "https://steamcommunity.com/openid/login",
                        data=check_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Freetify/1.0"},
                    )
                    with urllib.request.urlopen(request, timeout=15) as response:
                        verification = response.read().decode("utf-8", errors="replace")
                        verified = any(line.strip().lower() == "is_valid:true" for line in verification.splitlines())
                    if verified:
                        STEAM_SESSION = {"steamid": claimed.rsplit("/", 1)[-1]}
                        STEAM_ERROR = None
                        save_state()
                        authenticated = True
                    else:
                        STEAM_ERROR = "Steam rejected the sign-in verification."
                except Exception as exc:
                    STEAM_ERROR = f"Steam verification failed: {exc}"
            else:
                STEAM_ERROR = "Steam returned an invalid sign-in response (callback or identity mismatch)."
            self.send_response(302); self.send_header("Location", "/?steam=connected" if authenticated else "/?steam=error"); self.end_headers(); return
        if self.path == "/api/steam":
            gc_status = STEAM_GC.start_saved_session()
            self.end_json(200, {
                "connected": STEAM_SESSION is not None,
                "sync_ready": bool(STEAM_CONFIG),
                "gc_saved": bool(STEAM_GC_REFRESH_TOKEN),
                "gc": gc_status,
                "error": STEAM_ERROR,
                **(STEAM_SESSION or {}),
            }); return
        if self.path == "/api/steam/gc/status":
            self.end_json(200, STEAM_GC.start_saved_session()); return
        if self.path == "/api/steam/gc/matches":
            status = STEAM_GC.start_saved_session()
            if not status["available"]:
                self.end_json(503, {"error": status["detail"]}); return
            if status["state"] != "ready":
                self.end_json(409, {"error": status["detail"], "state": status["state"]}); return
            if not STEAM_GC.request_recent_matches():
                self.end_json(502, {"error": "Could not ask the local Steam bridge for matches."}); return
            self.end_json(202, {"ok": True, "detail": "Requesting recent matches from CS2."}); return
        if self.path == "/api/steam/gc/results":
            status = STEAM_GC.status()
            self.end_json(200, {**status, "matches": STEAM_GC.matches}); return
        if self.path.startswith("/api/steam/gc/download/status"):
            job_id = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("job", [""])[-1]
            with DOWNLOAD_JOBS_LOCK:
                job = DOWNLOAD_JOBS.get(job_id)
            if not job:
                self.end_json(404, {"error": "Replay download job was not found."}); return
            self.end_json(200, {"job": job_id, **job}); return
        if self.path == "/api/library":
            self.end_json(200, {"results": load_library()}); return
        if self.path.startswith("/api/library/report"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            requested = query.get("key", [""])[-1]
            entry = next((item for item in load_library() if requested and (requested == analysis_key(item) or requested in {str(item.get(field) or "") for field in ("match_id", "demo_hash", "stored_file", "file")})), None)
            report = None
            if entry and entry.get("report_file"):
                try:
                    report = json.loads((REPORT_ROOT / Path(str(entry["report_file"])).name).read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    report = None
            if not report:
                self.end_json(404, {"error": "Match report was not found."}); return
            self.end_json(200, report); return
        if self.path == "/api/steam/sync":
            if not STEAM_SESSION or not STEAM_CONFIG:
                self.end_json(400, {"error": "Connect Steam and provide a Game Authentication Code plus recent match-sharing code first."}); return
            # Share-code characters are case-sensitive; preserve the exact code
            # copied from Steam while using uppercase only for format checks.
            known = STEAM_CONFIG["share_code"]
            new_codes = []
            try:
                for _ in range(20):
                    query = urllib.parse.urlencode({"key": STEAM_CONFIG["api_key"], "steamid": STEAM_SESSION["steamid"], "steamidkey": STEAM_CONFIG["auth_code"], "knowncode": known})
                    request = urllib.request.Request(f"https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1/?{query}")
                    with urllib.request.urlopen(request, timeout=15) as response:
                        payload = json.loads(response.read())
                    data = payload.get("result", payload)
                    next_code = str(data.get("nextcode", "")).strip()
                    if not next_code or next_code == known:
                        break
                    new_codes.append(next_code); known = next_code
                download_codes = [STEAM_CONFIG["share_code"], *new_codes]
                self.end_json(200, {"ok": True, "codes": download_codes, "launched": 0})
            except urllib.error.HTTPError as exc:
                try:
                    response_body = exc.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    response_body = ""
                response_body = response_body[:500] or "(empty response)"
                print(
                    "Steam sync HTTP error: "
                    f"status={exc.code} reason={exc.reason!s} "
                    f"steamid={STEAM_SESSION.get('steamid')} "
                    f"share_prefix={STEAM_CONFIG['share_code'][:5]} "
                    f"share_length={len(STEAM_CONFIG['share_code'])} "
                    f"api_key_query={bool(STEAM_CONFIG.get('api_key'))} "
                    f"body={response_body}",
                    file=sys.stderr,
                    flush=True,
                )
                self.end_json(502, {"error": f"Steam sync failed ({exc.code}): {response_body}"})
            except Exception as exc:
                print(f"Steam sync error: {exc!r}", file=sys.stderr, flush=True)
                self.end_json(502, {"error": f"Steam sync failed: {exc}"})
            return
        if self.path == "/api/scan":
            results = []
            folders = [DEMO_ROOT, *steam_demo_dirs()]
            files = sorted({file for folder in folders for file in folder.glob("*.dem") if file.is_file()}, key=lambda file: file.stat().st_mtime, reverse=True)[:50]
            for source in files:
                destination = DEMO_ROOT / source.name
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                try:
                    result = analyze(str(destination), source.name, STEAM_SESSION.get("steamid") if STEAM_SESSION else None)
                    result["stored"] = True
                    result["stored_file"] = destination.name
                    result["demo_hash"] = demo_digest(destination)
                    store_analysis(result)
                    results.append(result)
                except Exception as exc:
                    results.append({"file": source.name, "error": str(exc)})
            self.end_json(200, {"results": results, "folders": [str(folder) for folder in folders]})
            return
        if self.path in ("", "/"):
            self.path = "/index.html"
        return super().do_GET()

    def launch_steam_demo(self, code):
        if not re.fullmatch(r"CSGO-[A-Z0-9-]+", code.upper()):
            return False
        uri = f"steam://rungame/730/0/+csgo_download_match%20{urllib.parse.quote(code)}"
        return open_uri(uri)

    def open_steam_match_history(self):
        if not STEAM_SESSION or not STEAM_SESSION.get("steamid"):
            return False
        steamid = urllib.parse.quote(str(STEAM_SESSION["steamid"]), safe="")
        return open_uri(f"https://steamcommunity.com/profiles/{steamid}/gcpd/730?tab=matchmaking")

    def download_gc_replay(self, replay_url, match_id="", match_time=None, progress=None):
        """Download a Valve replay URL returned by the authenticated CS2 GC."""
        parsed = urllib.parse.urlsplit(str(replay_url))
        if (
            parsed.scheme not in ("http", "https")
            or not re.fullmatch(r"replay[0-9]+\.valve\.net", parsed.hostname or "", re.IGNORECASE)
            or not parsed.path.startswith("/730/")
            or not parsed.path.lower().endswith(".dem.bz2")
        ):
            raise ValueError("CS2 did not provide a valid Valve replay URL.")
        compressed = DEMO_ROOT / f".{abs(hash(replay_url))}.dem.bz2.part"
        filename = Path(urllib.parse.unquote(parsed.path)).name[:-4]
        if not filename.lower().endswith(".dem"):
            raise ValueError("CS2 replay URL did not contain a demo file.")
        destination = DEMO_ROOT / filename
        try:
            if progress:
                progress("Downloading replay from Valve…")
            request = urllib.request.Request(str(replay_url), headers={"User-Agent": "Freetify/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response, compressed.open("wb") as output:
                final = urllib.parse.urlsplit(response.geturl())
                if not re.fullmatch(r"replay[0-9]+\.valve\.net", final.hostname or "", re.IGNORECASE):
                    raise ValueError("Valve replay download redirected to an unexpected host.")
                size = int(response.headers.get("Content-Length") or 0)
                if size > 2 * 1024 * 1024 * 1024:
                    raise ValueError("The replay is too large to download safely.")
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 2 * 1024 * 1024 * 1024:
                        raise ValueError("The replay is too large to download safely.")
                    output.write(chunk)
            if progress:
                progress("Decompressing replay…")
            with bz2.open(compressed, "rb") as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if progress:
                progress("Analyzing demo locally…")
            result = analyze(str(destination), destination.name, STEAM_SESSION.get("steamid") if STEAM_SESSION else None)
            result["stored"] = True
            result["stored_file"] = destination.name
            result["match_id"] = str(match_id or "")
            try:
                timestamp = int(match_time)
                if 946684800000 <= timestamp <= 4102444800000:
                    result["match_time"] = timestamp
            except (TypeError, ValueError):
                pass
            result["demo_hash"] = demo_digest(destination)
            if progress:
                progress("Saving local match report…")
            store_analysis(result)
            return result
        finally:
            try:
                compressed.unlink(missing_ok=True)
            except OSError:
                pass

    def launch_local_demo(self, filename):
        raw_name = str(filename)
        if not raw_name or "/" in raw_name or "\\" in raw_name or raw_name in (".", ".."):
            return False
        safe_name = Path(raw_name).name
        path = (DEMO_ROOT / safe_name).resolve()
        if path.parent != DEMO_ROOT.resolve() or not path.is_file() or path.suffix.lower() != ".dem":
            return False
        encoded_path = urllib.parse.quote(str(path), safe="")
        uri = f"steam://rungame/730/0/+playdemo%20{encoded_path}"
        return open_uri(uri)

    def end_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def start_download_job(self, replay_url, match_id, match_time=None):
        job_id = uuid.uuid4().hex
        with DOWNLOAD_JOBS_LOCK:
            DOWNLOAD_JOBS[job_id] = {"state": "queued", "detail": "Queued for local download…"}
        def update(detail):
            with DOWNLOAD_JOBS_LOCK:
                DOWNLOAD_JOBS[job_id].update({"state": "working", "detail": detail})
        def run():
            try:
                result = self.download_gc_replay(replay_url, match_id, match_time, update)
                with DOWNLOAD_JOBS_LOCK:
                    DOWNLOAD_JOBS[job_id].update({"state": "complete", "detail": "Downloaded and analyzed.", "result": analysis_summary(result)})
            except Exception as exc:
                print(f"CS2 replay download error: {exc!r}", file=sys.stderr, flush=True)
                with DOWNLOAD_JOBS_LOCK:
                    DOWNLOAD_JOBS[job_id].update({"state": "failed", "detail": f"Could not download this CS2 replay: {exc}"})
        threading.Thread(target=run, daemon=True).start()
        return job_id

    def do_POST(self):
        global STEAM_CONFIG
        if self.path == "/api/library/reanalyze":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                requested = str(payload.get("key") or "").strip()
                entry = next((item for item in load_library() if requested and (requested == analysis_key(item) or requested in {str(item.get(field) or "") for field in ("match_id", "demo_hash", "stored_file", "file")})), None)
                stored_file = Path(str(entry.get("stored_file") or "")).name if entry else ""
                demo = (DEMO_ROOT / stored_file).resolve()
                if not stored_file or demo.parent != DEMO_ROOT.resolve() or not demo.is_file() or demo.suffix.lower() != ".dem":
                    self.end_json(404, {"error": "The local demo file was not found."}); return
                result = analyze(str(demo), stored_file)
                result["stored_file"] = stored_file
                for field in ("match_id", "demo_hash", "match_time"):
                    if entry.get(field):
                        result[field] = entry[field]
                store_analysis(result)
                self.end_json(200, {"ok": True, "result": result}); return
            except (ValueError, TypeError, OSError) as exc:
                self.end_json(400, {"error": f"Could not reanalyze the local demo: {exc}"}); return
            except Exception as exc:
                self.end_json(500, {"error": f"Could not reanalyze the local demo: {exc}"}); return
        if self.path == "/api/library/delete":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                requested = str(payload.get("key") or "").strip()
                with LIBRARY_LOCK:
                    library = load_library()
                    removed = next((item for item in library if requested and requested in {str(item.get(field) or "") for field in ("match_id", "demo_hash", "stored_file", "file")}), None)
                    if not removed:
                        self.end_json(404, {"error": "Match was not found in the local library."}); return
                    library = [item for item in library if item is not removed]
                    temporary = LIBRARY_FILE.with_suffix(".tmp")
                    temporary.write_text(json.dumps(library[:100]), encoding="utf-8")
                    os.replace(temporary, LIBRARY_FILE)
                stored_file = Path(str(removed.get("stored_file") or "")).name
                demo = DEMO_ROOT / stored_file
                if stored_file and demo.parent == DEMO_ROOT and demo.suffix.lower() == ".dem":
                    demo.unlink(missing_ok=True)
                report_file = Path(str(removed.get("report_file") or "")).name
                report = REPORT_ROOT / report_file
                if report_file and report.parent == REPORT_ROOT and report.suffix.lower() == ".json":
                    report.unlink(missing_ok=True)
                self.end_json(200, {"ok": True}); return
            except (ValueError, TypeError, OSError) as exc:
                self.end_json(400, {"error": f"Could not delete the local match: {exc}"}); return
        if self.path == "/api/library/import":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                imported = 0
                for result in payload.get("results", []):
                    if isinstance(result, dict) and result.get("stored_file"):
                        store_analysis(result)
                        imported += 1
                self.end_json(200, {"ok": True, "imported": imported}); return
            except (ValueError, TypeError):
                self.end_json(400, {"error": "Invalid local library import."}); return
        if self.path == "/api/steam/gc/qr":
            if not STEAM_GC.start_qr():
                self.end_json(503, {"error": STEAM_GC.status()["detail"]}); return
            self.end_json(202, {"ok": True, "detail": "Generating a Steam QR code…"}); return
        if self.path == "/api/steam/match-history":
            if self.open_steam_match_history():
                self.end_json(200, {"ok": True}); return
            self.end_json(400, {"error": "Connect a Steam account first."}); return
        if self.path == "/api/steam/gc/download":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                job = self.start_download_job(payload.get("replay_url", ""), payload.get("match_id", ""), payload.get("match_time"))
                self.end_json(202, {"ok": True, "job": job, "detail": "Queued for local download…"}); return
            except (ValueError, TypeError) as exc:
                self.end_json(400, {"error": f"Could not start this CS2 replay download: {exc}"}); return
            except Exception as exc:
                print(f"CS2 replay download error: {exc!r}", file=sys.stderr, flush=True)
                self.end_json(500, {"error": "Freetify downloaded the replay but could not analyze it."}); return
        if self.path == "/api/open-demo":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                filename = str(json.loads(self.rfile.read(length)).get("file", "")).strip()
                if self.launch_local_demo(filename):
                    self.end_json(200, {"ok": True})
                else:
                    self.end_json(400, {"error": "No Steam/CS2 URI handler is available on this platform, or the demo is not stored."})
            except Exception as exc:
                self.end_json(400, {"error": f"Could not open the replay: {exc}"})
            return
        if self.path == "/api/steam/download":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                code = str(json.loads(self.rfile.read(length)).get("share_code", "")).strip()
                if self.launch_steam_demo(code):
                    self.end_json(200, {"ok": True})
                else:
                    self.end_json(400, {"error": "Steam demo launch is available in the Windows build only."})
            except Exception as exc:
                self.end_json(400, {"error": f"Could not launch the Steam demo: {exc}"})
            return
        if self.path == "/api/steam/config":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                auth_code = str(payload.get("auth_code", "")).strip()
                share_code = str(payload.get("share_code", "")).strip()
                api_key = str(payload.get("api_key", "")).strip()
                if len(api_key) < 16 or len(auth_code) < 8 or not share_code.upper().startswith("CSGO-"):
                    self.end_json(400, {"error": "Enter a Steam Web API key, Game Authentication Code, and CSGO match-sharing code."}); return
                STEAM_CONFIG = {"api_key": api_key, "auth_code": auth_code, "share_code": share_code}
                save_state()
                self.end_json(200, {"ok": True}); return
            except Exception:
                self.end_json(400, {"error": "Invalid sync settings."}); return
        if self.path != "/api/analyze":
            self.end_json(404, {"error": "Not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        message = BytesParser(policy=default).parsebytes((f"Content-Type: {self.headers.get('Content-Type', '')}\r\n\r\n").encode() + body)
        files = [part for part in message.iter_attachments() if part.get_param("name", header="content-disposition") == "demos"]
        results = []
        for upload in files:
            filename = upload.get_filename() or ""
            if not filename.lower().endswith(".dem"):
                continue
            safe_name = os.path.basename(filename)
            destination = DEMO_ROOT / safe_name
            if destination.exists():
                destination = DEMO_ROOT / f"{Path(safe_name).stem}-{abs(hash(safe_name))}{Path(safe_name).suffix}"
            destination.write_bytes(upload.get_payload(decode=True) or b"")
            temp_path = str(destination)
            try:
                result = analyze(temp_path, safe_name, STEAM_SESSION.get("steamid") if STEAM_SESSION else None)
                result["stored"] = True
                result["stored_file"] = destination.name
                result["demo_hash"] = demo_digest(destination)
                store_analysis(result)
                results.append(result)
            except Exception as exc:
                results.append({"file": safe_name, "error": str(exc)})
        self.end_json(200, {"results": results})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    STEAM_CALLBACK = f"http://127.0.0.1:{server.server_port}/auth/steam/callback"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        import webview
        print("Freetify desktop app running")
        webview.create_window("Freetify — CS2 Demo Insights", f"http://127.0.0.1:{server.server_port}", width=1440, height=950, min_size=(900, 650))
        webview.start(gui="qt" if sys.platform.startswith("linux") else None)
    except ImportError:
        print("Freetify could not start its native desktop window. Install the dependencies from requirements.txt and try again.", file=sys.stderr)
        server.shutdown()
        raise
    finally:
        STEAM_GC.shutdown()
        server.shutdown()
