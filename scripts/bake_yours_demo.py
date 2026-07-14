"""Bake offline demo verdicts for the example CSV (Your table tab)."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from askbench.clinical import clinical_lab_meeting, parse_meta_csv
EXAMPLE = """factor,study,log_rr,se,n
intervention,Alpha trial,-0.7,0.2,500
intervention,Beta trial,0.1,0.18,400
intervention,Gamma trial,-0.9,0.25,600
placebo_arm,Study A,0.05,0.12,300"""

QUESTIONS = [
    "Which factors are too heterogeneous to pool?",
    "What is the strongest pooled effect?",
    "Can I report one combined number?",
]


def main() -> None:
    data, err = parse_meta_csv(EXAMPLE, "relapse")
    if err:
        raise SystemExit(err)
    stub = lambda s, u, m=None: "[stub] offline narration"
    baked = {}
    for q in QUESTIONS:
        r = clinical_lab_meeting(q, data, llm=stub)
        r["narration"] = "offline"
        baked[q] = r
    out = ROOT / "web" / "baked_yours.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baked, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(QUESTIONS)} questions)")


if __name__ == "__main__":
    main()
