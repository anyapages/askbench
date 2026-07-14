"""Append-only prompt log for the public demo (mode + question, IP hashed)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_LOG = Path(__file__).resolve().parent.parent / "logs" / "prompts.jsonl"


def log_prompt(question: str, mode: str, ip: str = "unknown") -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "question": question.strip()[:500],
            "ip_hash": hashlib.sha256(ip.encode()).hexdigest()[:12],
        }
        with _LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
