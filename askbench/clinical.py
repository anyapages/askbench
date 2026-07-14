"""Clinical meta-analysis track: the same virtual lab meeting, run over pooled
study data instead of single cells. It answers questions a clinician actually
asks their own meta-analysis, for example "which combination of maternal risk
factors contributes most to absolute VTE risk across different populations",
without them writing a line of code.

The data here is SYNTHETIC with planted structure: the effect sizes are
plausible but are not drawn from real published studies, so the toolkit can be
built and validated before a real extracted dataset is wired in. Effects are on
the log risk-ratio scale, the way a meta-analyst records them.

The pooling, heterogeneity and absolute-risk maths are deterministic and
standard (DerSimonian-Laird random effects, Cochran's Q, I²), so the numbers are
correct with or without a model. Claude is used only to interpret and explain.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass
class Study:
    """One study's estimate for one risk factor, on the log risk-ratio scale."""
    factor: str
    log_rr: float
    se: float
    n: int
    population: str


class MetaData:
    """A small meta-analysis: many studies, each reporting one risk factor's
    effect on the outcome, plus the outcome's baseline absolute incidence."""

    def __init__(self, studies, outcome="pregnancy-associated VTE",
                 baseline_per_1000=1.2):
        self.studies = list(studies)
        self.outcome = outcome
        self.baseline_per_1000 = float(baseline_per_1000)

    def factors(self):
        return list(dict.fromkeys(s.factor for s in self.studies))

    def for_factor(self, factor):
        return [s for s in self.studies if s.factor == factor]


# ---------------------------------------------------------------------------
# Toolkit primitives (deterministic; the Skeptic's ammunition lives here)
# ---------------------------------------------------------------------------

def pool_random_effects(studies) -> dict:
    """DerSimonian-Laird random-effects pool of log risk ratios. Returns the
    pooled RR with a 95% CI, plus the heterogeneity a reviewer would demand
    (Cochran's Q, tau-squared, I²) and the study count behind it."""
    k = len(studies)
    if k == 0:
        return {"k": 0, "error": "no studies"}
    ys = [s.log_rr for s in studies]
    vs = [s.se ** 2 for s in studies]
    ws = [1.0 / v for v in vs]
    sw = sum(ws)
    y_fixed = sum(w * y for w, y in zip(ws, ys)) / sw
    q = sum(w * (y - y_fixed) ** 2 for w, y in zip(ws, ys))
    df = k - 1
    c = sw - sum(w * w for w in ws) / sw
    tau2 = max(0.0, (q - df) / c) if c > 0 else 0.0
    ws_star = [1.0 / (v + tau2) for v in vs]
    sw_star = sum(ws_star)
    y_pooled = sum(w * y for w, y in zip(ws_star, ys)) / sw_star
    se_pooled = math.sqrt(1.0 / sw_star)
    lo, hi = y_pooled - 1.96 * se_pooled, y_pooled + 1.96 * se_pooled
    i2 = max(0.0, (q - df) / q) * 100 if q > 0 else 0.0
    return {
        "k": k,
        "rr": round(math.exp(y_pooled), 3),
        "ci_low": round(math.exp(lo), 3),
        "ci_high": round(math.exp(hi), 3),
        "i2": round(i2, 1),
        "q": round(q, 3),
        "tau2": round(tau2, 4),
        "n_total": int(sum(s.n for s in studies)),
        "significant": bool(lo > 0.0 or hi < 0.0),   # CI excludes RR = 1
    }


def rank_factors_by_pooled_effect(data: MetaData) -> list:
    """Pool every factor and rank by pooled RR, largest first."""
    rows = []
    for f in data.factors():
        pooled = pool_random_effects(data.for_factor(f))
        pooled["factor"] = f
        rows.append(pooled)
    rows.sort(key=lambda r: r.get("rr", 0.0), reverse=True)
    return rows


def study_sources(data) -> list:
    """The individual source studies behind a meta-analysis, each with the risk ratio
    and 95% CI recomputed from its own reported estimate. Lets a reader see exactly
    which studies were pooled, not just the pooled number. Used for real datasets so
    the sources are auditable against the citation."""
    out = []
    for s in data.studies:
        out.append({
            "study": s.population,
            "factor": s.factor,
            "rr": round(math.exp(s.log_rr), 2),
            "ci_low": round(math.exp(s.log_rr - 1.96 * s.se), 2),
            "ci_high": round(math.exp(s.log_rr + 1.96 * s.se), 2),
            "n": s.n,
        })
    return out


def meta_skeptic_flags(row: dict, max_i2=75.0, min_studies=3) -> list:
    """The Skeptic's deterministic checks on one pooled factor."""
    flags = []
    if row.get("k", 0) == 0 or "error" in row:
        return ["no studies to pool"]  # defensive: a real dataset could yield an empty factor
    if row["k"] < min_studies:
        flags.append(f"pooled from only {row['k']} studies (under {min_studies}); "
                     f"the estimate is fragile")
    if row["i2"] > max_i2:
        flags.append(f"high heterogeneity (I²={row['i2']}%); the effect varies too "
                     f"much across populations to trust as one pooled number")
    if not row["significant"]:
        flags.append(f"confidence interval crosses no-effect "
                     f"(RR {row['ci_low']} to {row['ci_high']}); not significant")
    elif 0.90 <= row["rr"] <= 1.11:
        flags.append(f"effect is clinically negligible (pooled RR {row['rr']} sits "
                     f"inside the null band 0.90 to 1.11); statistically significant "
                     f"but too small to act on")
    return flags


def absolute_risk_for_combination(rows, baseline_per_1000: float) -> dict:
    """Approximate the absolute risk of carrying several factors at once by
    multiplying their pooled risk ratios onto the baseline incidence. This
    assumes the factors act independently and multiplicatively, which is a
    screening approximation, not a validated joint model. When the naive product
    implies an implausible absolute risk, that is surfaced rather than reported
    as if it were credible."""
    combined_rr = 1.0
    for r in rows:
        combined_rr *= r["rr"]
    abs_risk = baseline_per_1000 * combined_rr
    return {
        "factors": [r["factor"] for r in rows],
        "combined_rr": round(combined_rr, 2),
        "baseline_per_1000": baseline_per_1000,
        "absolute_risk_per_1000": round(abs_risk, 2),
        "implausible": abs_risk > 100.0,   # > 10% per pregnancy is not credible
        "assumption": "factors multiplied as if independent; a screening estimate, "
                      "not a joint model fitted on individuals",
    }


# ---------------------------------------------------------------------------
# The panel (mirrors agents.lab_meeting, over meta-analysis data)
# ---------------------------------------------------------------------------

_BCG_TERMS = re.compile(
    r"\b(bcg|tuberculosis|tb\b|vaccine|trial|heterogen|pool|meta|efficacy|"
    r"prevent|effect|colditz|latitude)\b",
    re.I,
)
_GENE_TERMS = re.compile(r"\b(gene|knockout|perturb|screen|crispr|ko_)\b", re.I)
_GREETING = re.compile(
    r"^\s*(hi|hello|hey|hiya|yo|sup|test|thanks?|ok|help)\b[\s!.?]*$",
    re.I,
)


def _is_real_bcg(data: MetaData) -> bool:
    src = getattr(data, "source", None) or ""
    return "bcg" in src.lower() or "colditz" in src.lower()


def clinical_question_guard(question: str, data: MetaData) -> str | None:
    """Refuse vague or off-dataset questions on the fixed real BCG tab."""
    if not _is_real_bcg(data):
        return None
    q = question.strip()
    if _GENE_TERMS.search(q):
        return (
            "This tab is the BCG tuberculosis trials only — no gene screen. "
            "Switch to Single-cell screen for GENE7, or tap a BCG example below."
        )
    if len(q) < 8 or _GREETING.match(q):
        return "Tap one of the BCG examples below — this tab only runs the 13 published trials."
    if not _BCG_TERMS.search(q):
        return (
            "Ask about BCG efficacy, pooling, or heterogeneity, or tap an example below. "
            "For maternal VTE factors, switch to Clinical meta-analysis."
        )
    return None


def _bcg_focused_answer(question: str, vetted: list, data: MetaData) -> str | None:
    """One real dataset, one factor: shape the headline to match the question asked."""
    if not _is_real_bcg(data) or len(vetted) != 1:
        return None
    h = vetted[0]
    if h.get("verdict") != "flagged":
        return None
    q = question.lower()
    if re.search(r"heterogen|i²|i2|varies|population|pool|trustworthy|one number", q):
        return (
            f"The panel does not report a single pooled estimate for {h['factor']}: "
            f"its effect varies too much across populations (I²={h['i2']}%) to trust "
            f"as one number. Pooling here would hide the disagreement, not resolve it."
        )
    if re.search(r"prevent|efficacy|effect|work|reduce|tuberculosis", q):
        return (
            f"Pooled across {h['k']} trials, {h['factor']} associates with tuberculosis "
            f"risk ratio {h['rr']} (95% CI {h['ci_low']} to {h['ci_high']}). "
            f"The panel still does not treat that as one trustworthy number: "
            f"I²={h['i2']}% is too high to pool honestly."
        )
    return None


def clinical_analyst(question: str, data: MetaData) -> dict:
    return {"question": question, "outcome": data.outcome,
            "ranked": rank_factors_by_pooled_effect(data)}


def clinical_skeptic(ranked) -> list:
    out = []
    for r in ranked:
        flags = meta_skeptic_flags(r)
        out.append({**r, "flags": flags,
                    "verdict": "solid" if not flags else "flagged"})
    return out


def clinical_contextualist(vetted, outcome, llm) -> list:
    """Ground the survivors in biology. Only solid factors earn a model call."""
    for v in vetted:
        if v["verdict"] == "solid":
            try:
                c = llm(
                    system="You are a haematologist. One sentence on the plausible "
                           "mechanism by which this factor raises the stated outcome. "
                           "If unsure, say so plainly.",
                    user=f"Factor: {v['factor']}, pooled RR {v['rr']}, outcome "
                         f"{outcome}. One sentence on the mechanism.")
                # A non-answer (offline stub or empty reply) must not render as a hedge
                # beside a SOLID verdict, so drop it rather than show self-doubt.
                v["context"] = c if (c and not c.startswith("[offline]")) else None
            except Exception:
                # A model error never sinks the deterministic answer.
                v["context"] = None
        else:
            v["context"] = None
    return vetted


def clinical_synthesize(vetted, data: MetaData) -> str:
    solid = sorted([v for v in vetted if v["verdict"] == "solid"],
                   key=lambda r: r["rr"], reverse=True)
    parts = []
    if solid:
        named = ", ".join(
            f"{v['factor']} (RR {v['rr']}, 95% CI {v['ci_low']} to {v['ci_high']}, "
            f"{v['k']} studies)" for v in solid)
        parts.append(f"The maternal risk factors with the strongest, most "
                     f"consistent effect on {data.outcome} are {named}.")
        combo = absolute_risk_for_combination(solid[:3], data.baseline_per_1000)
        if combo["implausible"]:
            lead = (f"Ranked individually, {solid[0]['factor']} and "
                    f"{solid[1]['factor']} contribute most."
                    if len(solid) >= 2 else
                    f"The single factor that passes is {solid[0]['factor']}.")
            parts.append(
                lead + " The panel does not report a single combined absolute risk "
                f"here: multiplying pooled ratios of this size implies about "
                f"{combo['absolute_risk_per_1000']} per 1000, which is not credible. "
                f"A joint absolute risk should come from a model fitted on individuals "
                f"who carry these factors together, not from multiplying marginal "
                f"pooled ratios.")
        else:
            parts.append(
                f"Together they raise the absolute risk from about "
                f"{combo['baseline_per_1000']} to about "
                f"{combo['absolute_risk_per_1000']} per 1000 pregnancies "
                f"(combined RR {combo['combined_rr']}), assuming they act "
                f"independently. Treat this as a screening estimate.")
    else:
        parts.append("No single factor passes the panel's checks cleanly.")
    het = [v for v in vetted if v["verdict"] == "flagged"
           and any("heterogeneity" in f for f in v["flags"])]
    if het:
        h = het[0]
        parts.append(
            f"The panel does not report a single pooled estimate for {h['factor']}: "
            f"its effect varies too much across populations (I²={h['i2']}%) to trust "
            f"as one number. Pooling here would hide the disagreement, not resolve it.")
    return " ".join(parts)


def clinical_refusal(vetted, data: MetaData) -> dict | None:
    """If multiplying the top solid factors' pooled ratios implies an absolute risk
    that is not credible, the panel declines to report a single combined number.
    Return that decision as a structured field (reason + the implied value it
    refused to stand behind), or None when a combined estimate is safe to give.
    This mirrors the prose in clinical_synthesize so the UI can surface the refusal
    as its own callout, not bury it in a paragraph."""
    solid = sorted([v for v in vetted if v["verdict"] == "solid"],
                   key=lambda r: r["rr"], reverse=True)
    if len(solid) < 2:
        return None
    combo = absolute_risk_for_combination(solid[:3], data.baseline_per_1000)
    if not combo["implausible"]:
        return None
    factors = combo["factors"]
    return {
        "declined": True,
        "factors": factors,
        "combined_rr": combo["combined_rr"],
        "implied_value": f"about {combo['absolute_risk_per_1000']} per 1000 pregnancies",
        "reason": (
            f"Multiplying the pooled ratios of {', '.join(factors)} as if they were "
            f"independent implies {combo['absolute_risk_per_1000']} per 1000 "
            f"pregnancies, which is not credible. A joint absolute risk should come "
            f"from a model fitted on individuals who carry these factors together, "
            f"not from multiplying marginal pooled ratios."),
    }


def clinical_lab_meeting(question: str, data: MetaData, llm=None) -> dict:
    """Run the full clinical panel and return a vetted finding."""
    guard = clinical_question_guard(question, data)
    if guard:
        return {"error": guard, "question": question.strip()}
    from .agents import make_llm
    llm = llm or make_llm()
    finding = clinical_analyst(question, data)
    vetted = clinical_contextualist(
        clinical_skeptic(finding["ranked"]), data.outcome, llm)
    from .plots import forest_plot, forest_caption
    from .debate import panel_debate
    caption, methods = forest_caption(data.outcome, vetted,
                                      source=getattr(data, "source", None))
    answer = _bcg_focused_answer(question, vetted, data) or clinical_synthesize(vetted, data)
    return {
        "question": question,
        "outcome": data.outcome,
        "findings": vetted,
        "vetted_answer": answer,
        "debate": panel_debate(question, vetted, answer, llm, domain="clinical"),
        "refusal": clinical_refusal(vetted, data),
        "figure": forest_plot(data.outcome, vetted),
        "caption": caption,
        "methods": methods,
        "data_note": getattr(data, "source", None) or
                     ("Synthetic illustrative meta-analysis. Effect sizes are "
                      "plausible but are not drawn from real published studies."),
        "sources": study_sources(data) if getattr(data, "source", None) else [],
    }


# ---------------------------------------------------------------------------
# Synthetic pregnancy-VTE meta-analysis with planted ground truth
# ---------------------------------------------------------------------------

def make_synthetic_vte(seed=0):
    """A synthetic pregnancy-associated VTE meta-analysis with planted structure:
    two strong and consistent factors, several moderate ones, one strong factor
    whose effect varies wildly across populations (the heterogeneity trap), one
    factor with too few studies to trust, and one near-null factor. Returns
    (MetaData, truth_dict)."""
    import numpy as np
    rng = np.random.default_rng(seed)

    # factor: (true log RR, n studies, mean cohort n, between-study effect sd)
    plan = {
        "previous_VTE":         (math.log(24.0), 6, 900, 0.06),
        "thrombophilia":        (math.log(9.0),  5, 700, 0.08),
        "immobility":           (math.log(7.5),  6, 800, 0.75),   # trap: high I²
        "obesity_bmi_over_30":  (math.log(2.1),  7, 1200, 0.06),
        "age_over_35":          (math.log(1.6),  6, 1500, 0.05),
        "multiple_pregnancy":   (math.log(1.9),  5, 600, 0.06),
        "emergency_caesarean":  (math.log(2.2),  5, 1000, 0.07),
        "IVF_ART":              (math.log(2.4),  2, 220, 0.10),   # too few studies
        "maternal_height":      (math.log(1.03), 5, 1400, 0.04),  # near-null
    }
    pops = ["Nordic cohort", "US claims", "UK Biobank", "Asian registry",
            "French cohort", "Dutch registry", "Australian cohort"]
    studies = []
    for factor, (mu, k, n_mean, het_sd) in plan.items():
        for j in range(k):
            true_eff = rng.normal(mu, het_sd)
            n = int(max(60, rng.normal(n_mean, n_mean * 0.25)))
            se = round(float(rng.uniform(0.12, 0.30)), 4)
            obs = round(float(rng.normal(true_eff, se)), 4)
            studies.append(Study(factor, obs, se, n, pops[j % len(pops)]))
    truth = {
        "outcome": "pregnancy-associated VTE",
        "strong_consistent": ["previous_VTE", "thrombophilia"],
        "high_heterogeneity_trap": "immobility",
        "underpowered": "IVF_ART",
        "near_null": "maternal_height",
        "baseline_per_1000": 1.2,
    }
    return MetaData(studies, outcome=truth["outcome"], baseline_per_1000=1.2), truth


def make_bcg_meta():
    """REAL published meta-analysis (not synthetic): the 13 randomized trials of BCG
    vaccination against tuberculosis from Colditz et al., JAMA 1994 (the canonical
    metafor `dat.bcg`). Each trial's log risk ratio and standard error are computed
    here from its real 2x2 table, so the numbers are verifiable against the source.
    This is the textbook example of between-study heterogeneity, so it is a real test
    of whether the Skeptic refuses a naive pooled number the field itself does not
    trust as one estimate. Returns (MetaData, source_citation)."""
    # (author year, TB+ vaccinated, TB- vaccinated, TB+ control, TB- control)
    trials = [
        ("Aronson 1948", 4, 119, 11, 128),
        ("Ferguson & Simes 1949", 6, 300, 29, 274),
        ("Rosenthal 1960", 3, 228, 11, 209),
        ("Hart & Sutherland 1977", 62, 13536, 248, 12619),
        ("Frimodt-Moller 1973", 33, 5036, 47, 5761),
        ("Stein & Aronson 1953", 180, 1361, 372, 1079),
        ("Vandiviere 1973", 8, 2537, 10, 619),
        ("TPT Madras 1980", 505, 87886, 499, 87892),
        ("Coetzee & Berjak 1968", 29, 7470, 45, 7232),
        ("Rosenthal 1961", 17, 1699, 65, 1600),
        ("Comstock 1974", 186, 50448, 141, 27197),
        ("Comstock & Webster 1969", 5, 2493, 3, 2338),
        ("Comstock 1976", 27, 16886, 29, 17825),
    ]
    studies = []
    for name, tpos, tneg, cpos, cneg in trials:
        n_t, n_c = tpos + tneg, cpos + cneg
        rr = (tpos / n_t) / (cpos / n_c)
        log_rr = math.log(rr)
        se = math.sqrt(1.0 / tpos - 1.0 / n_t + 1.0 / cpos - 1.0 / n_c)
        studies.append(Study("BCG vaccination", round(log_rr, 4), round(se, 4),
                             n_t + n_c, name))
    source = ("Colditz GA, Brewer TF, Berkey CS, et al. Efficacy of BCG vaccine in the "
              "prevention of tuberculosis: meta-analysis of the published literature. "
              "JAMA 1994;271(9):698-702. Real per-trial 2x2 data (metafor dat.bcg).")
    md = MetaData(studies, outcome="tuberculosis", baseline_per_1000=0.0)
    md.source = source
    return md, source
