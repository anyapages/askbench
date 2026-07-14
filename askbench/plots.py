"""Publication-style figures for a vetted finding. Every panel result can ship a
publication-style figure, a caption, and a one-sentence methods line, so the answer
is ready to drop into a paper, not just a table on screen.

Rendering is deterministic (matplotlib, Agg backend, no display) and returns a
base64 data URI the web UI drops straight into an <img>. If matplotlib is not
installed the callers degrade gracefully: figure is None, the text answer still
stands.
"""
from __future__ import annotations

import base64
import io

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _HAVE_MPL = True
except Exception:                      # matplotlib optional; text answer still works
    _HAVE_MPL = False

# A calm, journal-friendly palette. Solid findings in ink, flagged ones in amber.
_INK = "#1f2933"
_SOLID = "#2f6f4f"
_FLAG = "#c07a1f"
_ACCENT = "#2c62c8"
_MUTED = "#9aa0aa"
_GRID = "#e6e8ec"


def _to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


# ---------------------------------------------------------------------------
# Single-cell: effect of each perturbation on the target gene
# ---------------------------------------------------------------------------

def perturbation_effect_plot(gene: str, vetted: list) -> str | None:
    """Horizontal effect plot: each perturbation's effect on `gene`, solid
    findings in ink, panel-flagged ones in amber. Returns a data URI or None."""
    if not _HAVE_MPL or not vetted:
        return None
    rows = list(reversed(vetted[:6]))          # largest effect on top
    labels = [r["perturbation"] for r in rows]
    effects = [r["effect"] for r in rows]
    colours = [_SOLID if r["verdict"] == "solid" else _FLAG for r in rows]

    fig, ax = plt.subplots(figsize=(6.4, 0.55 * len(rows) + 1.2))
    y = range(len(rows))
    ax.axvline(0, color=_MUTED, lw=1, zorder=1)
    ax.barh(list(y), effects, color=colours, height=0.6, zorder=2)
    for yi, r in zip(y, rows):
        ax.text(r["effect"] + (0.004 if r["effect"] >= 0 else -0.004), yi,
                f"n={r['n_cells']}", va="center",
                ha="left" if r["effect"] >= 0 else "right",
                fontsize=8, color=_MUTED)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel(f"Effect on {gene} (mean difference, log-normalised)", fontsize=9)
    ax.set_title(f"Perturbation effect on {gene}", fontsize=11, color=_INK,
                 loc="left", pad=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(length=0)
    ax.xaxis.grid(True, color=_GRID, lw=0.8)
    ax.set_axisbelow(True)
    return _to_data_uri(fig)


def perturbation_caption(gene: str, vetted: list) -> tuple[str, str]:
    """(caption, methods_sentence) for the single-cell effect plot."""
    solid = [v for v in vetted if v["verdict"] == "solid"]
    caption = (
        f"Effect of each perturbation on {gene}, as the mean difference in "
        f"log-normalised expression versus non-targeting control. "
        f"{len(solid)} of {len(vetted)} shown perturbations pass the panel's "
        f"checks (green); those flagged for low cell count or non-significance "
        f"are shown in amber. Synthetic illustrative Perturb-seq data.")
    methods = (
        "Per-perturbation effects were computed on total-count-normalised, "
        "log1p-transformed expression and tested against control with a "
        "two-sided Welch t-test; findings under 20 cells, or with q > 0.05 after "
        "Benjamini-Hochberg FDR correction across the screen, were flagged. Cells "
        "from one condition are treated here as a screen, not as "
        "independent biological replicates: on a real Perturb-seq screen this "
        "must be pseudobulk per biological replicate (Squair et al. 2021), so "
        "these p-values rank candidates rather than settle differential expression.")
    return caption, methods


# ---------------------------------------------------------------------------
# Clinical: forest plot of pooled risk ratios
# ---------------------------------------------------------------------------

def forest_plot(outcome: str, vetted: list) -> str | None:
    """Forest plot: pooled RR with 95% CI per factor on a log scale, solid
    findings in ink, panel-flagged ones in amber. Returns a data URI or None."""
    if not _HAVE_MPL or not vetted:
        return None
    rows = sorted(vetted, key=lambda r: r["rr"])   # smallest RR at the bottom
    labels = [r["factor"] for r in rows]
    rr = [r["rr"] for r in rows]
    lo = [r["ci_low"] for r in rows]
    hi = [r["ci_high"] for r in rows]
    colours = [_SOLID if r["verdict"] == "solid" else _FLAG for r in rows]

    fig, ax = plt.subplots(figsize=(6.8, 0.55 * len(rows) + 1.3))
    y = range(len(rows))
    ax.axvline(1.0, color=_MUTED, lw=1, ls="--", zorder=1)   # RR = 1, no effect
    for yi, r, l, h, c in zip(y, rr, lo, hi, colours):
        ax.plot([l, h], [yi, yi], color=c, lw=1.8, zorder=2)
        ax.plot(r, yi, "o", color=c, ms=7, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("Pooled risk ratio (95% CI, log scale)", fontsize=9)
    ax.set_title(f"Pooled risk factors: {outcome}", fontsize=11, color=_INK,
                 loc="left", pad=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(length=0)
    ax.xaxis.grid(True, color=_GRID, lw=0.8, which="both")
    ax.set_axisbelow(True)
    return _to_data_uri(fig)


def forest_caption(outcome: str, vetted: list, source=None) -> tuple[str, str]:
    """(caption, methods_sentence) for the clinical forest plot. `source` is the real
    citation when the data is a real published meta-analysis, so the caption never
    labels real data as synthetic."""
    solid = [v for v in vetted if v["verdict"] == "solid"]
    provenance = ("Real published data, computed from each trial's reported estimate "
                  "(source cited above)." if source else "Synthetic illustrative data.")
    caption = (
        f"Random-effects pooled risk ratios for {outcome}. Points are pooled "
        f"RR, bars are 95% confidence intervals; the dashed line marks no effect "
        f"(RR = 1). {len(solid)} of {len(vetted)} factors pass the panel's checks "
        f"(green); those flagged for high heterogeneity, too few studies, or "
        f"non-significance are shown in amber. {provenance}")
    methods = (
        "Risk ratios were pooled per factor with a DerSimonian-Laird "
        "random-effects model; between-study heterogeneity was assessed with "
        "Cochran's Q and I², and factors with I² > 75%, fewer than three "
        "studies, or a CI crossing 1 were flagged.")
    return caption, methods


# ---------------------------------------------------------------------------
# Operating characteristic: how the Skeptic does across many seeds, not one run
# ---------------------------------------------------------------------------

_CATEGORY_COLOUR = {"structural": _ACCENT, "statistical": _ACCENT, "real": _SOLID}


def operating_characteristic_plot(oc: dict) -> str | None:
    """Horizontal bars of the Skeptic's operating characteristic over many seeds:
    each planted trap's catch rate and each real finding's pass rate, with the
    null false-positive rate drawn as a labelled reference line.

    Every number is read from `oc`, the dict returned by
    `eval.operating_characteristic()`; nothing here is hard-coded, so the figure
    only ever shows what a fresh `python eval.py` run actually produced. Returns a
    base64 data URI or None when matplotlib is missing or `oc` is empty.
    """
    if not _HAVE_MPL or not oc or not oc.get("bars"):
        return None
    bars = list(oc["bars"])                       # (label, rate, category)
    n_seeds = oc.get("n_seeds")
    fp_rate = oc.get("null_fp_rate")

    rows = list(reversed(bars))                   # first listed bar sits on top
    labels = [b[0] for b in rows]
    rates = [float(b[1]) for b in rows]
    colours = [_CATEGORY_COLOUR.get(b[2], _MUTED) for b in rows]
    y = range(len(rows))

    fig, ax = plt.subplots(figsize=(7.2, 0.52 * len(rows) + 1.7))
    ax.barh(list(y), rates, color=colours, height=0.62, zorder=3)
    for yi, rate in zip(y, rates):
        # label inside long bars, outside short ones, so it never clips the frame
        inside = rate > 12
        ax.text(rate - 1.4 if inside else rate + 1.4, yi, f"{rate:.1f}%",
                va="center", ha="right" if inside else "left", fontsize=8.5,
                color="white" if inside else _INK, zorder=4,
                fontweight="600" if inside else "normal")

    if fp_rate is not None:
        ax.axvline(float(fp_rate), color=_FLAG, lw=1.6, ls="--", zorder=2)
        # Park the label in the white gap between the top two bars, clear of both
        # the title above and the value labels at the bar ends.
        ax.text(float(fp_rate) + 1.0, len(rows) - 1.5,
                f"null false-positive {fp_rate:.2f}%", color=_FLAG, fontsize=8.5,
                ha="left", va="center",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=_FLAG, lw=0.8))

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.set_xlim(0, 105)
    ax.set_xlabel(
        f"Correct-verdict rate over {n_seeds} seeds (%)" if n_seeds
        else "Correct-verdict rate (%)", fontsize=9)
    ax.set_title("How we measure this: Skeptic operating characteristic",
                 fontsize=11, color=_INK, loc="left", pad=12)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(length=0)
    ax.xaxis.grid(True, color=_GRID, lw=0.8)
    ax.set_axisbelow(True)

    # A three-entry legend below the axes so bar identity is never colour-alone
    # and nothing sits on top of the bars.
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    ax.legend(handles=[
        Patch(facecolor=_ACCENT, label="Planted trap caught"),
        Patch(facecolor=_SOLID, label="Real finding passed"),
        Line2D([0], [0], color=_FLAG, ls="--", lw=1.6,
               label="Null false-positive rate"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3,
        frameon=False, fontsize=8, handlelength=1.4, columnspacing=1.6)
    return _to_data_uri(fig)


def operating_characteristic_caption(oc: dict) -> tuple[str, str]:
    """(caption, methods_sentence) for the operating-characteristic figure. Reads
    the summary numbers straight from `oc` so the words match the bars."""
    n = oc.get("n_seeds")
    fp = oc.get("null_fp_rate")
    slipped = oc.get("null_slipped")
    total = oc.get("null_total")
    reals = [b[1] for b in oc.get("bars", []) if b[2] == "real"]
    low_real = min(reals) if reals else 0.0
    caption = (
        f"Each bar is the share of {n} random seeds on which the Skeptic reached "
        f"the correct verdict. Structural traps (fixed cell and study counts) are "
        f"caught by construction; the statistical traps (heterogeneity, near-null) "
        f"sit in the low nineties; real findings pass from {low_real:.1f}% to 100%. "
        f"The amber line marks the null false-positive rate ({fp:.2f}%, "
        f"{slipped}/{total} null candidates that slipped past), reported not hidden. "
        f"Synthetic illustrative data.")
    methods = (
        f"Both tracks were re-run across {n} seeds; each bar is the fraction of "
        f"seeds on which the Skeptic's deterministic checks reached the planted "
        f"ground-truth verdict, computed with no model.")
    return caption, methods
