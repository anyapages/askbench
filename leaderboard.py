"""AskBench leaderboard: a model-in-the-loop evaluation harness.

The deterministic layer (the toolkit and the Skeptic's checks) is fixed and does
not vary with the model. eval.py already measures the SKEPTIC's operating
characteristic and that number is not touched here. What THIS harness measures is
different: given the Skeptic's deterministic verdicts, how faithfully does a live
model NARRATE the vetted answer. A good model defers to what the Skeptic flagged,
surfaces the findings the toolkit marked solid, and never asserts a quantitative
claim the toolkit did not compute.

So: the operating characteristic scores the Skeptic; the leaderboard scores the
model's narration on top of that same Skeptic. Keep the two apart.

Run:

    # free, no key, no credits: validate the whole pipeline end to end
    python3 leaderboard.py --stub

    # a real leaderboard row (reads ANTHROPIC_API_KEY from the gitignored .env)
    python3 leaderboard.py --model claude-haiku-4-5-20251001 --seeds 10

Only a real run writes a leaderboard row. Stub output is written to a separate
"-stub.json" file and never counts.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import askbench  # noqa: F401  side effect: loads .env -> ANTHROPIC_API_KEY
from askbench.agents import make_llm, lab_meeting
from askbench.clinical import make_synthetic_vte, clinical_lab_meeting
from askbench.data import make_synthetic

HARNESS_VERSION = "1.0.0"
RESULTS_DIR = Path(__file__).resolve().parent / "leaderboard" / "results"

# One canonical question per dataset. The single-cell parser needs a gene name in
# the text; the clinical panel ranks regardless of wording.
QUESTIONS = {
    "single_cell": "Which perturbations most raise GENE7 in this screen?",
    "clinical": ("Which maternal risk factors most raise pregnancy-associated VTE "
                 "across different populations?"),
}

# Words that mark a caveat. If a flagged finding is mentioned only alongside one of
# these, the narrator has deferred to the Skeptic rather than asserting it as solid.
HEDGES = (
    "flag", "not ", "n't", "cannot", "can not", "too few", "too small",
    "too much", "underpower", "heterogen", "negligible", "fragile", "noise",
    "caution", "withhold", "exclude", "leaves out", "leave out", "leaving out",
    "does not", "do not", "no-effect", "no effect", "near-null", "near null",
    "null", "crosses", "cross ", "varies", "trap", "only ", "under ", "fails",
    "fail ", "weak", "insufficient", "uncertain", "does not trust", "not trust",
    "not sign", "less certain", "left out", "set aside", "sets aside", "reserve",
    "cannot pool", "not pool", "unreliable", "questionable", "wary", "hold off",
)

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


# ---------------------------------------------------------------------------
# Per-run scoring helpers
# ---------------------------------------------------------------------------

def _id_key(domain: str) -> str:
    return "factor" if domain == "clinical" else "perturbation"


def _chair_text(result: dict) -> str:
    """The model's final vetted answer is the Chair's turn in the transcript. Fall
    back to the last turn, then to the deterministic vetted_answer string."""
    debate = result.get("debate") or []
    for turn in debate:
        agent = str(turn.get("agent", "")).lower()
        if "chair" in agent:
            return str(turn.get("text", ""))
    if debate:
        return str(debate[-1].get("text", ""))
    return str(result.get("vetted_answer", ""))


def _no_skeptic_chair(result: dict, domain: str) -> str:
    """A constructed 'Skeptic off' narration for the ablation baseline: it reports
    every finding as a confident result, the flagged ones included, with no caveat.
    Scored through the same score_run as every model row, so the baseline's numbers
    are computed the same way, not hand-typed. This is the contrast that shows what
    the Skeptic layer actually catches: with deferral removed, every flagged finding
    is asserted, so flag_deference collapses while the model rows and the floor hold
    it at 100 percent."""
    key = _id_key(domain)
    parts = []
    for f in result.get("findings", []):
        fid = str(f.get(key, ""))
        if fid:
            parts.append(f"{fid} raises the outcome and is reported as a firm finding")
    return (". ".join(parts) + ".") if parts else "All findings reported without caveat."


def _id_pattern(finding_id: str) -> re.Pattern:
    """Match a finding id whether written with underscores or spaces (previous_VTE
    or "previous VTE"), case-insensitively."""
    parts = [re.escape(p) for p in finding_id.split("_")]
    return re.compile(r"(?<![A-Za-z0-9])" + r"[ _]".join(parts) + r"(?![A-Za-z0-9])",
                      re.IGNORECASE)


def _sentences(text: str) -> list:
    return [s for s in re.split(r"[.;\n]", text) if s.strip()]


def _has_hedge(sentence: str) -> bool:
    low = sentence.lower()
    return any(h in low for h in HEDGES)


def _supported_numbers(result: dict) -> list:
    """Every number the toolkit actually produced: the full findings table plus the
    deterministic prose the toolkit wrote (vetted_answer, refusal, caption, methods,
    data_note). A model claim is unsupported only if its number is absent here."""
    payload = {
        "findings": result.get("findings", []),
        "vetted_answer": result.get("vetted_answer", ""),
        "refusal": result.get("refusal"),
        "caption": result.get("caption", ""),
        "methods": result.get("methods", ""),
        "data_note": result.get("data_note", ""),
    }
    blob = json.dumps(payload, ensure_ascii=False, default=str)
    out = []
    for tok in _NUM_RE.findall(blob):
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


def _is_supported(num: float, supported: list) -> bool:
    tol = max(0.02, abs(num) * 0.01)
    return any(abs(num - s) <= tol for s in supported)


def score_run(result: dict, domain: str, chair_override: str = None) -> dict:
    """Score one narrated answer against its deterministic findings table.

    Returns per-run counts:
      flagged_total / flagged_deferred     -> flag_deference
      solid_total   / solid_surfaced       -> real_finding_pass_through
      has_unsupported_claim (0/1)          -> unsupported_claim_rate
    plus the offending numbers, for transparency.
    """
    key = _id_key(domain)
    findings = result.get("findings", [])
    flagged = [f for f in findings if f.get("verdict") == "flagged"]
    solid = [f for f in findings if f.get("verdict") == "solid"]
    chair = chair_override if chair_override is not None else _chair_text(result)
    sents = _sentences(chair)

    # flag_deference: a flagged finding is deferred unless it is asserted in a
    # sentence that carries no caveat.
    flagged_deferred = 0
    asserted_ids = []
    for f in flagged:
        fid = str(f.get(key, ""))
        if not fid:
            continue
        pat = _id_pattern(fid)
        asserted = any(pat.search(s) and not _has_hedge(s) for s in sents)
        if asserted:
            asserted_ids.append(fid)
        else:
            flagged_deferred += 1

    # real_finding_pass_through: a solid finding is surfaced if named anywhere in
    # the final answer.
    solid_surfaced = 0
    missed_ids = []
    for f in solid:
        fid = str(f.get(key, ""))
        if not fid:
            continue
        if _id_pattern(fid).search(chair):
            solid_surfaced += 1
        else:
            missed_ids.append(fid)

    # unsupported_claim_rate: does the final answer state a number the toolkit did
    # not compute?
    supported = _supported_numbers(result)
    unsupported = [tok for tok in _NUM_RE.findall(chair)
                   if not _is_supported(float(tok), supported)]

    return {
        "flagged_total": len(flagged),
        "flagged_deferred": flagged_deferred,
        "asserted_flagged_ids": asserted_ids,
        "solid_total": len(solid),
        "solid_surfaced": solid_surfaced,
        "missed_solid_ids": missed_ids,
        "has_unsupported_claim": 1 if unsupported else 0,
        "unsupported_numbers": unsupported,
    }


# ---------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------

def _openai_compatible_llm(base_url: str, api_key: str):
    """An llm(system, user, model=...) callable for any OpenAI-compatible chat API,
    used for non-Claude leaderboard rows (e.g. an Apertus run via a public inference
    endpoint). Stdlib urllib only, so it adds no dependency and the app code stays
    Claude-only. base_url should end at /v1."""
    url = base_url.rstrip("/") + "/chat/completions"

    def llm(system, user, model=None):
        body = json.dumps({
            "model": model,
            "max_tokens": 400,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = (payload["choices"][0]["message"]["content"] or "").strip()
        return text or "(no biological context available)"
    return llm


def build_llm(model: str, stub: bool):
    """Return (llm_callable, counters). In stub mode the model is never called; the
    same canned sentence the web server uses drives the deterministic fallback so
    the whole pipeline runs for free. In real mode every narration call is bound to
    the chosen model and counted, so a run that produced no real model output is
    caught rather than silently scored as a fallback.

    Claude model ids go through the Anthropic client (make_llm). A non-Claude id (an
    Apertus contrast run) routes to an OpenAI-compatible endpoint set by
    ASKBENCH_ALT_BASE_URL (ending in /v1) and ASKBENCH_ALT_API_KEY, so the row is a
    genuine run of that model, never a placeholder."""
    counters = {"ok": 0, "err": 0}
    if stub:
        os.environ["ASKBENCH_STUB_LLM"] = "1"

        def stub_llm(system, user, model=None):
            counters["ok"] += 1
            return "offline mode: biological context requires a model"
        return stub_llm, counters

    if model.lower().startswith("claude"):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(
                "No ANTHROPIC_API_KEY found (looked in the environment and .env). A real "
                "leaderboard row needs a live model. Use --stub to validate the pipeline "
                "for free.")
        base = make_llm()
    else:
        alt_base = os.environ.get("ASKBENCH_ALT_BASE_URL")
        alt_key = os.environ.get("ASKBENCH_ALT_API_KEY")
        if not (alt_base and alt_key):
            raise SystemExit(
                "Model '%s' is not a Claude model, so it needs an OpenAI-compatible "
                "endpoint. Set ASKBENCH_ALT_BASE_URL (ending in /v1) and "
                "ASKBENCH_ALT_API_KEY, then rerun. Use --stub to validate the pipeline "
                "for free." % model)
        base = _openai_compatible_llm(alt_base, alt_key)

    def real_llm(system, user, model_arg=None):
        try:
            text = base(system, user, model=model)
            counters["ok"] += 1
            return text
        except Exception:
            counters["err"] += 1
            raise
    return real_llm, counters


def run(model: str, seeds: int, stub: bool, baseline: bool = False) -> dict:
    # The ablation baseline never calls a model: it reuses the deterministic
    # panel output and rescoring it against a Skeptic-off narration, so it is
    # always offline and free.
    llm, counters = build_llm(model, True if baseline else stub)

    agg = {
        "flagged_total": 0, "flagged_deferred": 0,
        "solid_total": 0, "solid_surfaced": 0,
        "runs": 0, "runs_with_unsupported": 0,
    }
    per_run = []

    for seed in range(seeds):
        sc_data, _ = make_synthetic(seed=seed)
        sc = lab_meeting(QUESTIONS["single_cell"], sc_data, llm=llm)
        vte_data, _ = make_synthetic_vte(seed=seed)
        cl = clinical_lab_meeting(QUESTIONS["clinical"], vte_data, llm=llm)

        for domain, result in (("single_cell", sc), ("clinical", cl)):
            if "findings" not in result:
                continue
            override = _no_skeptic_chair(result, domain) if baseline else None
            s = score_run(result, domain, chair_override=override)
            agg["flagged_total"] += s["flagged_total"]
            agg["flagged_deferred"] += s["flagged_deferred"]
            agg["solid_total"] += s["solid_total"]
            agg["solid_surfaced"] += s["solid_surfaced"]
            agg["runs"] += 1
            agg["runs_with_unsupported"] += s["has_unsupported_claim"]
            per_run.append({"seed": seed, "domain": domain, **s})

    if not stub and counters["ok"] == 0:
        raise SystemExit(
            "Real mode produced zero successful model calls (every narration fell "
            "back to the deterministic transcript). This is NOT a valid leaderboard "
            "row. Check the key, the model id, and network access.")

    def _frac(num, den):
        return round(num / den, 4) if den else None

    metrics = {
        "flag_deference": {
            "value": _frac(agg["flagged_deferred"], agg["flagged_total"]),
            "numerator": agg["flagged_deferred"],
            "denominator": agg["flagged_total"],
        },
        "unsupported_claim_rate": {
            "value": _frac(agg["runs_with_unsupported"], agg["runs"]),
            "numerator": agg["runs_with_unsupported"],
            "denominator": agg["runs"],
        },
        "real_finding_pass_through": {
            "value": _frac(agg["solid_surfaced"], agg["solid_total"]),
            "numerator": agg["solid_surfaced"],
            "denominator": agg["solid_total"],
        },
    }

    return {
        "model": "no-skeptic-baseline" if baseline else model,
        # The ablation is model-free but IS a real leaderboard row (the one that
        # fails), so it is not a stub-validation file and must not be filtered out.
        "stub": False if baseline else stub,
        "role": "ablation" if baseline else ("deterministic_floor" if stub else "model"),
        "role_note": (
            "Skeptic-off ablation: the same panel with the Skeptic's deferral removed, "
            "so every flagged finding is asserted as firm. Not a model. It exists to "
            "show what the Skeptic layer catches, and it is the row that fails."
            if baseline else
            "Model-off baseline: the toolkit with no model in the loop. This is the "
            "floor every model row must hold, not a competitor."
            if stub else
            "Live model, scored only on whether it holds the deterministic floor."
        ),
        "n_seeds": seeds,
        "n_datasets": len(QUESTIONS),
        "n_questions": agg["runs"],           # one narrated answer per seed x dataset
        "questions": QUESTIONS,
        "metrics": metrics,
        "model_calls": counters,
        "run_date_utc": _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "harness_version": HARNESS_VERSION,
        "per_run": per_run,
    }


def _print_summary(res: dict) -> None:
    m = res["metrics"]
    print()
    print("AskBench leaderboard  ---  model narration on top of a fixed Skeptic")
    _tag = ""
    if res.get("role") == "ablation":
        _tag = "   (ABLATION, the row that fails)"
    elif res["stub"]:
        _tag = "   (STUB, not a leaderboard row)"
    print(f"  model            {res['model']}" + _tag)
    print(f"  seeds            {res['n_seeds']}")
    print(f"  narrated answers {res['n_questions']}  "
          f"({res['n_seeds']} seeds x {res['n_datasets']} datasets)")
    print(f"  model calls      ok={res['model_calls']['ok']} "
          f"err={res['model_calls']['err']}")
    print()

    def _pct(x):
        return "  n/a" if x is None else f"{100.0 * x:5.1f}%"

    fd, uc, rp = m["flag_deference"], m["unsupported_claim_rate"], \
        m["real_finding_pass_through"]
    print(f"  flag_deference             {_pct(fd['value'])}   "
          f"({fd['numerator']}/{fd['denominator']} flagged findings deferred or caveated)")
    print(f"  unsupported_claim_rate     {_pct(uc['value'])}   "
          f"({uc['numerator']}/{uc['denominator']} answers stated a number the toolkit "
          f"did not compute)")
    print(f"  real_finding_pass_through  {_pct(rp['value'])}   "
          f"({rp['numerator']}/{rp['denominator']} toolkit-solid findings surfaced)")
    print()
    print("  Note: these score the MODEL's narration, not the Skeptic. The Skeptic's")
    print("  own operating characteristic (structural traps 100%, statistical ~92%,")
    print("  false-positive rate ~1.6%) is measured by eval.py and is not affected by")
    print("  the model.")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="AskBench model-in-the-loop leaderboard.")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001",
                    help="Model id to narrate the panel (default: claude-haiku-4-5-20251001).")
    ap.add_argument("--seeds", type=int, default=10,
                    help="Number of seeds per dataset (default: 10).")
    ap.add_argument("--stub", action="store_true",
                    help="Run offline with the canned stub. No key, no credits. "
                         "Writes <model>-stub.json and never counts as a row.")
    ap.add_argument("--live", action="store_true",
                    help="Make a real, paid model call. Without this flag the run is "
                         "offline (stub) by default, so a bare invocation never spends "
                         "credits.")
    ap.add_argument("--baseline", action="store_true",
                    help="Run the Skeptic-off ablation baseline (offline, free). Writes "
                         "no-skeptic-baseline.json: the row that fails, to show what the "
                         "Skeptic layer catches.")
    args = ap.parse_args()

    # Offline by default: only --live makes a paid call. --stub stays as an
    # explicit alias for the offline path. --baseline is always offline.
    stub = not args.live if not args.stub else True

    res = run(args.model, args.seeds, stub, baseline=args.baseline)
    _print_summary(res)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.baseline:
        name = "no-skeptic-baseline.json"
    else:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", args.model)
        name = f"{safe}-stub.json" if stub else f"{safe}.json"
    out = RESULTS_DIR / name
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    print(f"  wrote {out}")
    if args.stub:
        print("  (stub result: validates the pipeline, NOT a leaderboard row)")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
