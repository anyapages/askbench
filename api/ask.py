"""POST /ask — same panel logic as web/server.py, Vercel serverless."""
from __future__ import annotations

import json
import os
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
_LLM = make_llm() if _LIVE else _STUB


def _run(question: str, mode: str, ip: str = "unknown",
         csv_text: str = "", outcome: str = "outcome") -> tuple[dict, int]:
    question = question.strip()
    if not question:
        return {"error": "Please enter a question."}, 400
    log_prompt(question, mode, ip)
    try:
        if mode == "clinical":
            result = clinical_lab_meeting(question, _VTE, llm=_LLM)
        elif mode == "clinical_real":
            result = clinical_lab_meeting(question, _BCG, llm=_LLM)
        elif mode == "clinical_yours":
            data, err = parse_meta_csv(csv_text, outcome=outcome)
            if err:
                return {"error": err, "question": question}, 422
            result = clinical_lab_meeting(question, data, llm=_LLM)
        else:
            result = lab_meeting(question, _DATA, llm=_LLM)
    except Exception:
        return {"error": "The panel could not analyse that question."}, 500
    if "findings" not in result:
        return result, 422
    if isinstance(result, dict):
        result["narration"] = "live" if _LIVE else "offline"
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
        body, status = _run(question, mode, self.headers.get("X-Forwarded-For", "vercel")[:64],
                            csv_text=csv_text, outcome=outcome)
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return  # quiet on Vercel
