#!/usr/bin/env python3
"""Local-only Freetify server and CS2 demo analysis endpoint."""
import json
import math
import os
import tempfile
import threading
import webbrowser
from email.parser import BytesParser
from email.policy import default
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


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


def analyze(path, filename):
    from demoparser2 import DemoParser

    parser = DemoParser(path)
    header = clean(parser.parse_header())
    deaths = records(parser.parse_event("player_death"))
    rounds = records(parser.parse_event("round_end"))
    players = records(parser.parse_player_info())
    by_player = {}
    for death in deaths:
        attacker = death.get("attacker_name") or death.get("attacker")
        victim = death.get("user_name") or death.get("userid") or death.get("victim_name")
        weapon = death.get("weapon") or "unknown"
        if attacker:
            item = by_player.setdefault(attacker, {"player": attacker, "kills": 0, "deaths": 0, "headshots": 0, "weapons": {}})
            item["kills"] += 1
            item["headshots"] += int(bool(death.get("headshot")))
            item["weapons"][weapon] = item["weapons"].get(weapon, 0) + 1
        if victim:
            item = by_player.setdefault(victim, {"player": victim, "kills": 0, "deaths": 0, "headshots": 0, "weapons": {}})
            item["deaths"] += 1
    for player in by_player.values():
        player["kd"] = round(player["kills"] / max(player["deaths"], 1), 2)
        player["headshot_rate"] = round(player["headshots"] / max(player["kills"], 1) * 100, 1)
    return clean({"file": filename, "header": header, "rounds": rounds, "deaths": deaths, "players": list(by_player.values()), "player_info": players, "capabilities": ["kills", "deaths", "headshots", "rounds", "player roster"]})


class Handler(SimpleHTTPRequestHandler):
    def end_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
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
            with tempfile.NamedTemporaryFile(suffix=".dem", delete=False) as temp:
                temp.write(upload.get_payload(decode=True) or b"")
                temp_path = temp.name
            try:
                results.append(analyze(temp_path, os.path.basename(filename)))
            except Exception as exc:
                results.append({"file": os.path.basename(filename), "error": str(exc)})
            finally:
                os.unlink(temp_path)
        self.end_json(200, {"results": results})


if __name__ == "__main__":
    print("Freetify running at http://127.0.0.1:8000")
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    server.serve_forever()
