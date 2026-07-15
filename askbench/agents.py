"""The virtual lab meeting. Analyst runs the analysis on the tested toolkit,
Skeptic attacks it with deterministic statistical checks, Contextualist grounds
the survivors, and a synthesis returns a vetted finding.

The LLM is injected, so the orchestration runs offline with a stub and flips to
Claude the moment a key is present. Critically, the *analysis* is deterministic
(the toolkit), so the answer is correct with or without the model; the model only
interprets and explains."""
from __future__ import annotations

import os
import re

from .toolkit import rank_perturbations_by_effect, skeptic_flags


def make_llm():
    """Return an llm(system, user, model=None) -> str callable. Real Claude when a
    key and the SDK are available, otherwise a deterministic stub. ASKBENCH_STUB_LLM
    forces the stub even when a key is present, so the offline switch is honoured by a
    direct lab_meeting() call, not only by the web server, and spends no credits."""

    def stub(system, user, model=None):
        return "[offline] biological context unavailable without a model"

    if os.environ.get("ASKBENCH_STUB_LLM"):
        return stub
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)

            def llm(system, user, model="claude-haiku-4-5-20251001"):
                msg = client.messages.create(
                    model=model, max_tokens=400, system=system,
                    messages=[{"role": "user", "content": user}])
                text = "".join(getattr(b, "text", "") for b in msg.content
                               if getattr(b, "type", None) == "text").strip()
                return text or "(no biological context available)"
            return llm
        except ImportError:
            pass

    return stub


def parse_question(question: str, data) -> dict:
    """Deterministic first-pass parse: find a gene named in the question and the
    direction asked. Claude refines this when present, but the pipeline never
    depends on it to produce a correct answer."""
    lower_map = {g.lower(): g for g in data.genes}
    gene = None
    for tok in re.findall(r"[A-Za-z0-9]+", question):
        if tok.lower() in lower_map:
            gene = lower_map[tok.lower()]
            break
    direction = ("down" if re.search(r"\b(lower|reduce|decrease|down|suppress\w*|inhibit\w*)\b",
                                     question, re.I) else "up")
    return {"gene": gene, "direction": direction}


def resolve_intent(question, data, llm) -> dict:
    """The model's one load-bearing job. When a question does not name a gene outright,
    Claude interprets the intent: it decides WHICH gene in the screen the scientist means
    and the direction, or asks one short clarifying question. This is deliberately scoped
    to WHAT gets analysed. Claude never computes, estimates, or touches a number, the
    deterministic toolkit runs the analysis and the Skeptic vets it exactly as before.
    Returns {"gene": <name in data.genes or None>, "direction": "up"|"down",
    "clarify": <question or None>}."""
    import json as _json
    fallback = {"gene": None, "direction": "up",
                "clarify": "Which gene should I focus on? For example GENE7."}
    target = "GENE7" if data.has_gene("GENE7") else (data.genes[0] if data.genes else "")
    sample = ", ".join(data.genes[:12]) + (", ..." if len(data.genes) > 12 else "")
    try:
        raw = llm(
            system=("You are the intake step of a single-cell screen analysis panel. Your "
                    "only job is to decide WHICH gene the scientist wants analysed and the "
                    "direction (up or down). You never compute, estimate, or invent any "
                    "number, a deterministic toolkit does all of that. The screen's primary "
                    f"readout gene is {target}. Genes include: {sample}. Reply with ONLY "
                    'compact JSON: {"gene":"GENEx","direction":"up"} when a gene is clear, '
                    'or {"clarify":"one short question"} when it is too vague.'),
            user=question)
    except Exception:
        return fallback
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return fallback
    try:
        obj = _json.loads(m.group(0))
    except ValueError:
        return fallback
    gene = obj.get("gene")
    if isinstance(gene, str) and data.has_gene(gene):
        direction = "down" if str(obj.get("direction", "up")).lower().startswith("d") else "up"
        return {"gene": gene, "direction": direction, "clarify": None}
    return {"gene": None, "direction": "up",
            "clarify": obj.get("clarify") or fallback["clarify"]}


# Data dimensions this single-cell perturbation screen does not measure. A question that
# asks for one of these names a dimension the screen cannot answer, even when it also names
# a gene, so the panel refuses rather than answer the in-scope part and imply it addressed
# the whole question. This is a deterministic Skeptic-style guard, not a model judgment, so
# it stays reproducible and needs no key. It runs before the parser, closing the gap where a
# gene-named but unanswerable question ("raise GENE7 in liver tissue") used to be answered.
_OUT_OF_SCOPE = {
    "tissue or anatomy": r"\b(tissue|liver|kidney|brain|lung|heart|organ|in\s?vivo|anatom\w+)\b",
    "clinical outcome, survival or treatment": (
        r"\b(surviv\w+|mortalit\w+|prognos\w+|patient\w*|clinical\w*|"
        r"cure[sd]?|curing|treat\w+|therap\w+|disease|cancer|tumou?r\w*)\b"),
    "dose or time course": r"\b(dose|dosage|time.?course|kinetic\w*|over\s+time)\b",
}


def scope_check(question: str):
    """Deterministic guard: refuse a question that asks for a data dimension this screen
    does not measure. Returns a specific refusal string, or None when the question is in
    scope. Reproducible, model-free, and precise about exactly what data is missing."""
    for dimension, pattern in _OUT_OF_SCOPE.items():
        if re.search(pattern, question, re.I):
            return (f"This is a single-cell perturbation screen: it measures effect size, "
                    f"significance and cell counts per knockout, not {dimension}. That is "
                    f"not answerable from this data. Ask which perturbations move a named gene.")
    return None


def analyst(question, data, llm) -> dict:
    refusal = scope_check(question)
    if refusal:
        return {"error": refusal}
    parsed = parse_question(question, data)
    gene, direction, resolved = parsed["gene"], parsed["direction"], False
    if not gene:
        # Ambiguous question: Claude resolves the intent (which gene, which direction)
        # or asks one clarifying question. It chooses WHAT to analyse; the toolkit below
        # still computes every number and the Skeptic still vets it.
        intent = resolve_intent(question, data, llm)
        gene, direction, resolved = intent["gene"], intent["direction"], True
        if not gene:
            return {"error": intent["clarify"]}
    res = rank_perturbations_by_effect(data, gene)
    rows = res["results"]
    if direction == "down":
        rows = list(reversed(rows))
    return {"gene": gene, "direction": direction, "top": rows[:5],
            "intent_by_model": resolved}


def skeptic(finding, llm) -> list:
    """Attack each candidate with deterministic checks. A finding survives only
    with zero flags."""
    out = []
    for row in finding["top"]:
        flags = skeptic_flags(row)
        out.append({**row, "flags": flags,
                    "verdict": "solid" if not flags else "flagged"})
    return out


# The screen's gene and knockout labels are anonymised placeholders, so a model
# asked to name the real gene can only fail. Any reply that gropes for the gene's
# identity is dropped rather than rendered as self-doubt beside a SOLID verdict.
_NON_ANSWER_MARKERS = (
    "[offline]", "no biological context available",
    "don't have enough", "do not have enough", "not able to determine",
    "cannot determine", "can't determine", "i'm unsure", "i am unsure",
    "would need to know", "unclear which", "could you clarify",
    "i'm not able", "i am not able", "no information about", "not familiar with",
)


def _usable_context(text):
    """The model's sentence, or None when it is a non-answer."""
    if not text:
        return None
    stripped = text.strip()
    if any(marker in stripped.lower() for marker in _NON_ANSWER_MARKERS):
        return None
    return stripped


def contextualist(vetted, gene, llm) -> list:
    """Ground the survivors in biology. Only the solid ones earn a model call.
    A model error never sinks the deterministic answer: context degrades to None
    and the panel still returns its vetted finding."""
    for v in vetted:
        if v["verdict"] == "solid":
            try:
                c = llm(
                    system="You are a cell biologist reading a perturbation screen "
                           "whose gene and knockout labels are anonymised placeholders. "
                           "Never guess which real gene it is and never ask which gene "
                           "it is. In one sentence, say what an effect of this size and "
                           "direction implies mechanistically and what you would check "
                           "next.",
                    user=f"Knockout {v['perturbation']} shifts {gene} by "
                         f"{v['effect']:+.2f} in log-normalised expression across "
                         f"{v['n_cells']} cells. One sentence.")
                v["context"] = _usable_context(c)
            except Exception:
                v["context"] = None
        else:
            v["context"] = None
    return vetted


def synthesize(gene, direction, vetted) -> str:
    verb = "raise" if direction == "up" else "lower"
    solid = [v for v in vetted if v["verdict"] == "solid"]
    parts = []
    if solid:
        named = ", ".join(
            f"{v['perturbation']} (effect {v['effect']:+.2f}, p={v['p_value']}, "
            f"n={v['n_cells']})" for v in solid)
        parts.append(f"The best-supported perturbations that {verb} {gene}: {named}.")
    else:
        parts.append(f"No perturbation cleanly passes the checks for {verb}-ing {gene}.")
    traps = [v for v in vetted if v["verdict"] == "flagged"
             and any("cells" in f for f in v["flags"])]
    if traps:
        t = traps[0]
        parts.append(f"The panel flags {t['perturbation']}: a large-looking effect "
                     f"on only {t['n_cells']} cells, so it does not trust it yet.")
    return " ".join(parts)


def lab_meeting(question, data, llm=None) -> dict:
    """Run the full panel and return a vetted finding."""
    llm = llm or make_llm()
    finding = analyst(question, data, llm)
    if "error" in finding:
        return finding
    vetted = contextualist(skeptic(finding, llm), finding["gene"], llm)
    from .plots import perturbation_effect_plot, perturbation_caption
    from .debate import panel_debate
    caption, methods = perturbation_caption(finding["gene"], vetted)
    answer = synthesize(finding["gene"], finding["direction"], vetted)
    return {
        "question": question,
        "gene": finding["gene"],
        "findings": vetted,
        "vetted_answer": answer,
        "debate": panel_debate(question, vetted, answer, llm, domain="single_cell"),
        "figure": perturbation_effect_plot(finding["gene"], vetted),
        "caption": caption,
        "methods": methods,
        "intent_by_model": finding.get("intent_by_model", False),
        "intent_note": (
            f"You did not name a gene, so Claude read your question as being about "
            f"{finding['gene']} ({finding['direction']}). Claude chose the target; the "
            f"toolkit computed every number below."
        ) if finding.get("intent_by_model") else None,
    }
