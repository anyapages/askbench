"""AskBench web backend.

Import askbench first: that loads ANTHROPIC_API_KEY from the gitignored .env, so
Claude is available to the contextualist agent without touching the shell.

    pip install flask
    python web/server.py
    # open the URL it prints (http://localhost:5050)

Set ASKBENCH_STUB_LLM=1 to run fully offline (no model calls, no credits spent).
"""
import socket
import sys
from pathlib import Path

# Make `python web/server.py` work from the repo root: put the repo root (which
# holds the askbench/ package) on the path before importing it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import askbench  # noqa: E402,F401  side effect: loads .env -> ANTHROPIC_API_KEY
from askbench.data import make_synthetic
from askbench.agents import lab_meeting, make_llm
from askbench.clinical import make_synthetic_vte, clinical_lab_meeting, make_bcg_meta, parse_meta_csv
from askbench.prompt_log import log_prompt

import json
import os
import time
import threading

from flask import Flask, jsonify, request, send_from_directory

WEB_DIR = Path(__file__).resolve().parent
# leaderboard runs are written by `python3 leaderboard.py --model <id>` into
# leaderboard/results/*.json at the repo root. The page reads them through the
# route below; a row only ever exists when a real run has produced a file.
RESULTS_DIR = WEB_DIR.parent / "leaderboard" / "results"
app = Flask(__name__, static_folder=None)

# Both synthetic datasets are deterministic (seed=0), so build them once at
# startup rather than regenerating on every request. Single-cell is the default
# panel; the clinical meta-analysis panel runs the same review over pooled study
# data and is selected with mode="clinical".
_DATA, _TRUTH = make_synthetic()
_VTE, _VTE_TRUTH = make_synthetic_vte()
_BCG, _BCG_SOURCE = make_bcg_meta()   # REAL data: 13 BCG-vs-TB trials, Colditz JAMA 1994

# Live narration with guardrails.
# The statistics are always deterministic (the toolkit). Only the narration
# sentence uses the model, so the demo can run live Claude narration when a key
# is present and degrade gracefully to the canned sentence under a model error,
# a per-IP rate limit, or a daily budget cap. The verdict card stays fully
# correct either way, so a public link can never break, and it can never drain
# the key. Live is on only when a key is set AND the offline switch is not; make
# a bare deploy safe by default.

def _stub_llm(system, user, model=None):
    return "[offline] biological context unavailable without a model"


_LIVE = (not os.environ.get("ASKBENCH_STUB_LLM")) and bool(os.environ.get("ANTHROPIC_API_KEY"))
_REAL_LLM = make_llm() if _LIVE else None   # real Claude, built only when live is enabled

# Daily global cap on live model calls, so a public URL cannot run up the bill.
# Set ASKBENCH_LIVE_BUDGET in the dashboard to raise or lower it.
_LIVE_BUDGET = int(os.environ.get("ASKBENCH_LIVE_BUDGET", "400"))
_budget = {"day": None, "used": 0}
_budget_lock = threading.Lock()

# Per-IP sliding-window rate limit on live calls.
_RATE_MAX = 8
_RATE_WINDOW = 60.0
_ip_hits = {}
_ip_lock = threading.Lock()


def _budget_ok():
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with _budget_lock:
        if _budget["day"] != day:
            _budget["day"], _budget["used"] = day, 0
        if _budget["used"] >= _LIVE_BUDGET:
            return False
        _budget["used"] += 1
        return True


def _rate_ok(ip):
    now = time.time()
    with _ip_lock:
        hits = [t for t in _ip_hits.get(ip, ()) if now - t < _RATE_WINDOW]
        if len(hits) >= _RATE_MAX:
            _ip_hits[ip] = hits
            return False
        hits.append(now)
        _ip_hits[ip] = hits
        return True


def _pick_llm(ip):
    """Live Claude when it is enabled, the caller is under the per-IP rate limit,
    and the daily budget has room; otherwise the deterministic stub. A live call
    that raises falls back to the stub inside the wrapper, so the panel never
    breaks and never leaks an error to the browser."""
    if not (_LIVE and _rate_ok(ip) and _budget_ok()):
        return _stub_llm, "offline"

    def guarded(system, user, model="claude-haiku-4-5-20251001"):
        try:
            return _REAL_LLM(system, user, model=model)
        except Exception:
            return _stub_llm(system, user, model=model)

    return guarded, "live"


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/leaderboard")
@app.route("/leaderboard.html")
def leaderboard_page():
    return send_from_directory(WEB_DIR, "leaderboard.html")


@app.get("/leaderboard/results")
def leaderboard_results():
    """Return every real leaderboard run found on disk, newest run first.

    A row exists only when a real run wrote it. Stub validation files (stub:true,
    written to <model>-stub.json by `leaderboard.py --stub`) never count as a
    leaderboard row, matching leaderboard/README.md, so they are filtered out
    here. No real files means no runs yet: the page shows an honest empty state
    rather than inventing a row. Any file that cannot be parsed is skipped, never
    faked. This route is additive and read-only; it touches nothing else.
    """
    rows = []
    if RESULTS_DIR.is_dir():
        for path in sorted(RESULTS_DIR.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    row = json.load(fh)
            except (ValueError, OSError):
                continue  # skip unreadable/corrupt files, do not fabricate
            if not isinstance(row, dict):
                continue
            if row.get("stub") is True:
                continue  # stub runs are not a leaderboard row
            rows.append(row)
    rows.sort(key=lambda r: str(r.get("run_date_utc", r.get("run_date", ""))), reverse=True)
    return jsonify({"rows": rows})


@app.post("/ask")
def ask():
    payload = request.get_json(silent=True) or {}
    q = payload.get("question")
    question = q.strip() if isinstance(q, str) else ""
    m = payload.get("mode")
    mode = m.strip() if isinstance(m, str) else "single_cell"
    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    fwd = request.headers.get("X-Forwarded-For", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")
    log_prompt(question, mode, ip)
    chosen_llm, narration = _pick_llm(ip)

    try:
        if mode == "clinical":
            result = clinical_lab_meeting(question, _VTE, llm=chosen_llm)
        elif mode == "clinical_real":
            result = clinical_lab_meeting(question, _BCG, llm=chosen_llm)
        elif mode == "clinical_yours":
            csv_text = payload.get("csv") or ""
            outcome = payload.get("outcome") or "outcome"
            data, err = parse_meta_csv(csv_text, outcome=outcome if isinstance(outcome, str) else "outcome")
            if err:
                return jsonify({"error": err, "question": question}), 422
            result = clinical_lab_meeting(question, data, llm=chosen_llm)
        else:
            result = lab_meeting(question, _DATA, llm=chosen_llm)
    except Exception:  # never leak a stack trace to the browser
        return jsonify({"error": "The panel could not analyse that question."}), 500

    # A panel returns {error: ...} when it cannot act on the question (for the
    # single-cell panel, when no gene is named). The clinical panel always ranks.
    if "findings" not in result:
        return jsonify(result), 422
    # Tell the client whether the narration was written live by Claude or is the
    # deterministic fallback. The numbers are identical either way.
    if isinstance(result, dict):
        result["narration"] = narration
    return jsonify(result), 200


def _free_port(host, start, tries=20):
    """Return the first bindable port at or after `start`.

    Set PORT to pick the starting point (5050 by default: on macOS port 5000 is
    usually taken by AirPlay Receiver). If that port is busy we walk forward
    rather than crashing with 'Address already in use', so a second run or a
    stray process never blocks the demo.
    """
    for candidate in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, candidate))
                return candidate
            except OSError:
                continue
    # Nothing free in the window: fall back to an OS-assigned ephemeral port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


if __name__ == "__main__":
    host = "127.0.0.1"
    requested = int(os.environ.get("PORT", 5050))
    port = _free_port(host, requested)
    if port != requested:
        print(f"\n  Port {requested} was busy, using {port} instead.")
    print(f"\n  AskBench is running.  Open  ->  http://localhost:{port}\n")
    app.run(host=host, port=port, debug=False)
