"""GET /leaderboard/results — same JSON as web/server.py."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from api._bootstrap import ROOT

RESULTS_DIR = ROOT / "leaderboard" / "results"


def _rows():
    rows = []
    if RESULTS_DIR.is_dir():
        for path in sorted(RESULTS_DIR.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    row = json.load(fh)
            except (ValueError, OSError):
                continue
            if not isinstance(row, dict) or row.get("stub") is True:
                continue
            rows.append(row)
    rows.sort(key=lambda r: str(r.get("run_date_utc", r.get("run_date", ""))), reverse=True)
    return {"rows": rows}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps(_rows()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return
