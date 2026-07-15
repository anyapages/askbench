"""Bake offline verdicts for VTE and Screen benchmark tabs."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from askbench.agents import lab_meeting
from askbench.clinical import clinical_lab_meeting, make_synthetic_vte
from askbench.data import make_synthetic

_DATA, _ = make_synthetic()
_VTE, _ = make_synthetic_vte()

QUESTIONS = {
    "single_cell": [
        "Which knockouts most raise GENE7?",
        "Which perturbations lower GENE7?",
        "Show me the top hits that raise the main readout gene",
        "What raises GENE7 the most, and can I trust it?",
    ],
    "clinical": [
        "Which risk factors are too heterogeneous to pool?",
        "Which combination drives most VTE risk?",
        "Rank risk factors by pooled effect",
    ],
}


def main() -> None:
    stub = lambda s, u, m=None: "[stub] offline narration"
    baked: dict[str, dict] = {}
    for q in QUESTIONS["single_cell"]:
        r = lab_meeting(q, _DATA, llm=stub)
        r["narration"] = "offline"
        baked.setdefault("single_cell", {})[q] = r
    for q in QUESTIONS["clinical"]:
        r = clinical_lab_meeting(q, _VTE, llm=stub)
        r["narration"] = "offline"
        baked.setdefault("clinical", {})[q] = r
    out = ROOT / "web" / "baked_benchmarks.json"
    out.write_text(json.dumps(baked, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
