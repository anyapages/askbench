"""Bake leaderboard/results/*.json into public/leaderboard/results.json for Vercel."""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "leaderboard" / "results"
OUT = ROOT / "public" / "leaderboard" / "results.json"

rows = []
for path in sorted(SRC.glob("*.json")):
    row = json.loads(path.read_text(encoding="utf-8"))
    if row.get("stub"):
        continue
    rows.append(row)
rows.sort(key=lambda r: str(r.get("run_date_utc", r.get("run_date", ""))), reverse=True)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"rows": rows}), encoding="utf-8")
print(f"wrote {OUT} ({len(rows)} rows)")
