#!/usr/bin/env python3
"""Local-only Freetify server and CS2 demo analysis endpoint."""
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import re
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
STEAM_SESSION = None
STEAM_CONFIG = {}
STEAM_CALLBACK = ""


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
    rounds = safe_event(parser, "round_end")
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
            sample_step = max(64, max_tick // 240)
            sample_ticks = list(range(0, max_tick + 1, sample_step))
            positions = records(parser.parse_ticks(["X", "Y", "player_name", "team_num", "game_time"], ticks=sample_ticks))
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
    for hurt in hurts:
        attacker = hurt.get("attacker_name") or hurt.get("attacker")
        if attacker:
            item = by_player.setdefault(attacker, {"player": attacker, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
            item["damage"] += int(hurt.get("dmg_health") or hurt.get("damage") or 0)
            if str(hurt.get("weapon", "")).lower() in ("hegrenade", "molotov", "incgrenade", "inferno", "firecrackerblast"):
                item["utility_damage"] = item.get("utility_damage", 0) + int(hurt.get("dmg_health") or hurt.get("damage") or 0)
    for blind in blinds:
        attacker = blind.get("attacker_name") or blind.get("attacker")
        if attacker:
            item = by_player.setdefault(attacker, {"player": attacker, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
            item["flashes"] = item.get("flashes", 0) + 1
    aggregate_fields = {"kills_total": "kills", "deaths_total": "deaths", "assists_total": "assists", "headshot_kills_total": "headshots", "damage_total": "damage", "utility_damage_total": "utility_damage", "enemies_flashed_total": "flashes"}
    for snapshot in snapshots:
        name = snapshot.get("player_name") or snapshot.get("name")
        if not name:
            continue
        item = by_player.setdefault(name, {"player": name, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0, "damage": 0, "weapons": {}})
        for source, target in aggregate_fields.items():
            if snapshot.get(source) is not None:
                item[target] = max(item.get(target, 0), int(snapshot[source] or 0))
    snapshot_teams = {(snapshot.get("player_name") or snapshot.get("name")): snapshot.get("team_num") for snapshot in snapshots if snapshot.get("player_name") or snapshot.get("name")}
    reference = max(by_player.values(), key=lambda player: player.get("kills", 0), default=None)
    reference_team = snapshot_teams.get(reference.get("player")) if reference else None
    round_wins = round_losses = 0
    for round_event in rounds:
        winner = str(round_event.get("winner", "")).upper()
        winner_team = 3 if "CT" in winner else 2 if winner in ("T", "TERRORIST") else None
        if winner_team and reference_team:
            try:
                same_team = int(reference_team) == winner_team
            except (TypeError, ValueError):
                same_team = False
            if same_team:
                round_wins += 1
            else:
                round_losses += 1
    match_result = "WIN" if round_wins > round_losses else "LOSS" if round_losses > round_wins else "TIE" if rounds else "UNKNOWN"
    for player in by_player.values():
        player["kd"] = round(player["kills"] / max(player["deaths"], 1), 2)
        player["headshot_rate"] = round(player["headshots"] / max(player["kills"], 1) * 100, 1)
        rounds_seen = max(len(rounds), 1)
        player["impact"] = round(0.8 + (player["kills"] / rounds_seen) * 0.7 + (player.get("damage", 0) / rounds_seen / 100) * 0.3 + (player.get("assists", 0) / rounds_seen) * 0.15 - (player["deaths"] / rounds_seen) * 0.25, 2)
    primary_player = None
    if preferred_steamid:
        matching_info = next((info for info in players if str(info.get("player_steamid") or info.get("steamid") or info.get("steam_id")) == str(preferred_steamid)), None)
        if matching_info:
            primary_player = matching_info.get("player_name") or matching_info.get("name")
    if not primary_player and reference:
        primary_player = reference.get("player")
    return clean({"file": filename, "primary_player": primary_player, "header": header, "rounds": rounds, "round_wins": round_wins, "round_losses": round_losses, "match_result": match_result, "positions": positions, "deaths": deaths, "players": list(by_player.values()), "capabilities": ["kills", "deaths", "assists", "headshots", "damage", "utility damage", "flashes", "rounds", "player roster", "event positions"]})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_ROOT), **kwargs)

    def do_GET(self):
        global STEAM_SESSION
        if self.path == "/auth/steam":
            realm = STEAM_CALLBACK.rsplit("/auth/", 1)[0] + "/"
            query = urllib.parse.urlencode({"openid.ns": "http://specs.openid.net/auth/2.0", "openid.mode": "checkid_setup", "openid.return_to": STEAM_CALLBACK, "openid.realm": realm, "openid.identity": "http://specs.openid.net/auth/2.0/identifier", "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier"})
            self.send_response(302); self.send_header("Location", f"https://steamcommunity.com/openid/login?{query}"); self.end_headers(); return
        if self.path.startswith("/auth/steam/callback"):
            params = {key: values[-1] for key, values in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}
            claimed = params.get("openid.claimed_id", "")
            valid_return = params.get("openid.return_to", "") == STEAM_CALLBACK
            valid_id = re.fullmatch(r"https://steamcommunity\.com/openid/id/[0-9]+", claimed)
            if valid_return and valid_id:
                check_data = urllib.parse.urlencode({**params, "openid.mode": "check_authentication"}).encode()
                try:
                    with urllib.request.urlopen("https://steamcommunity.com/openid/login", check_data, timeout=15) as response:
                        verified = b"is_valid:true" in response.read().replace(b" ", b"")
                    if verified:
                        STEAM_SESSION = {"steamid": claimed.rsplit("/", 1)[-1]}
                except Exception:
                    pass
            self.send_response(302); self.send_header("Location", "/?steam=connected" if STEAM_SESSION else "/?steam=error"); self.end_headers(); return
        if self.path == "/api/steam":
            self.end_json(200, {"connected": STEAM_SESSION is not None, "sync_ready": bool(STEAM_CONFIG), **(STEAM_SESSION or {})}); return
        if self.path == "/api/steam/sync":
            if not STEAM_SESSION or not STEAM_CONFIG:
                self.end_json(400, {"error": "Connect Steam and provide a Game Authentication Code plus recent match-sharing code first."}); return
            known = STEAM_CONFIG["share_code"].upper()
            new_codes = []
            try:
                for _ in range(20):
                    query = urllib.parse.urlencode({"key": STEAM_CONFIG["api_key"], "steamid": STEAM_SESSION["steamid"], "steamidkey": STEAM_CONFIG["auth_code"], "knowncode": known})
                    with urllib.request.urlopen(f"https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1/?{query}", timeout=15) as response:
                        payload = json.loads(response.read())
                    data = payload.get("result", payload)
                    next_code = str(data.get("nextcode", "")).upper()
                    if not next_code or next_code == known:
                        break
                    new_codes.append(next_code); known = next_code
                download_codes = [STEAM_CONFIG["share_code"].upper(), *new_codes]
                self.end_json(200, {"ok": True, "codes": download_codes, "launched": 0})
            except Exception as exc:
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
        uri = f"steam://rungame/730/0/+csgo_download_match%20{urllib.parse.quote(code.upper())}"
        return open_uri(uri)

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

    def do_POST(self):
        global STEAM_CONFIG
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
        webview.start()
    except ImportError:
        print("Freetify could not start its native desktop window. Install the dependencies from requirements.txt and try again.", file=sys.stderr)
        server.shutdown()
        raise
