"""POST /ask — panel on Vercel serverless (Claude narrates when ANTHROPIC_API_KEY is set)."""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler

from api._bootstrap import ROOT  # noqa: F401
from askbench.agents import lab_meeting, make_llm
from askbench.clinical import clinical_lab_meeting, make_bcg_meta, make_synthetic_vte, parse_meta_csv
from askbench.data import make_synthetic
from askbench.prompt_log import log_prompt

_DATA, _ = make_synthetic()
_VTE, _ = make_synthetic_vte()
_BCG, _ = make_bcg_meta()

_STUB = lambda system, user, model=None: "[offline] biological context unavailable without a model"
_LIVE = (not os.environ.get("ASKBENCH_STUB_LLM")) and bool(os.environ.get("ANTHROPIC_API_KEY"))
_REAL_LLM = make_llm() if _LIVE else None

_LIVE_BUDGET = int(os.environ.get("ASKBENCH_LIVE_BUDGET", "400"))
_budget = {"day": None, "used": 0}
_budget_lock = threading.Lock()
_RATE_MAX = 8
_RATE_WINDOW = 60.0
_ip_hits: dict[str, list[float]] = {}
_ip_lock = threading.Lock()


def _budget_ok() -> bool:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with _budget_lock:
        if _budget["day"] != day:
            _budget["day"], _budget["used"] = day, 0
        if _budget["used"] >= _LIVE_BUDGET:
            return False
        _budget["used"] += 1
        return True


def _rate_ok(ip: str) -> bool:
    now = time.time()
    with _ip_lock:
        hits = [t for t in _ip_hits.get(ip, ()) if now - t < _RATE_WINDOW]
        if len(hits) >= _RATE_MAX:
            _ip_hits[ip] = hits
            return False
        hits.append(now)
        _ip_hits[ip] = hits
        return True


def _pick_llm(ip: str):
    if not (_LIVE and _rate_ok(ip) and _budget_ok()):
        return _STUB, "offline"

    def guarded(system, user, model="claude-haiku-4-5-20251001"):
        try:
            return _REAL_LLM(system, user, model=model)
        except Exception:
            return _STUB(system, user, model=model)

    return guarded, "live"


def _run(question: str, mode: str, ip: str = "unknown",
         csv_text: str = "", outcome: str = "outcome") -> tuple[dict, int]:
    question = question.strip()
    if not question:
        return {"error": "Please enter a question."}, 400
    log_prompt(question, mode, ip)
    chosen_llm, narration = _pick_llm(ip)
    try:
        if mode == "clinical":
            result = clinical_lab_meeting(question, _VTE, llm=chosen_llm)
        elif mode == "clinical_real":
            result = clinical_lab_meeting(question, _BCG, llm=chosen_llm)
        elif mode == "clinical_yours":
            data, err = parse_meta_csv(csv_text, outcome=outcome)
            if err:
                return {"error": err, "question": question}, 422
            result = clinical_lab_meeting(question, data, llm=chosen_llm)
        else:
            result = lab_meeting(question, _DATA, llm=chosen_llm)
    except Exception:
        return {"error": "The panel could not analyse that question."}, 500
    if "findings" not in result:
        return result, 422
    if isinstance(result, dict):
        result["narration"] = narration
    return result, 200


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            payload = {}
        q = payload.get("question")
        m = payload.get("mode")
        question = q.strip() if isinstance(q, str) else ""
        mode = m.strip() if isinstance(m, str) else "single_cell"
        csv_raw = payload.get("csv")
        csv_text = csv_raw if isinstance(csv_raw, str) else ""
        out_raw = payload.get("outcome")
        outcome = out_raw.strip() if isinstance(out_raw, str) and out_raw.strip() else "outcome"
        fwd = self.headers.get("X-Forwarded-For", "")
        ip = fwd.split(",")[0].strip() if fwd else "vercel"
        body, status = _run(question, mode, ip[:64], csv_text=csv_text, outcome=outcome)
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return
