"""Curated, tested bioinformatics primitives. The agents call these, so
correctness lives here, not in free-form model output. Every function returns
plain dicts the agent layer can reason over and the Skeptic can challenge."""
from __future__ import annotations

import numpy as np
from scipy import stats

from .data import CellData, normalize


def dataset_summary(data: CellData) -> dict:
    return {
        "n_cells": int(data.n_cells),
        "n_genes": int(data.n_genes),
        "n_perturbations": len(data.perturbation_labels()),
        "control_label": data.control,
        "n_control_cells": int(data.mask(data.control).sum()),
    }


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR q-values, aligned to the input order. A screen
    runs one test per perturbation against a shared control, so raw p-values
    overstate significance across ~30 comparisons; the Skeptic thresholds on
    these q-values instead."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * m / rank)
        q[i] = min(running, 1.0)
    return q


def rank_perturbations_by_effect(data: CellData, gene: str, normalise=True) -> dict:
    """Rank perturbations by their effect on `gene` versus control. Each row
    carries the effect size (mean difference in log-normalised expression), a
    two-sided Welch t-test p-value, and the cell count behind it (the Skeptic's
    ammunition)."""
    if not data.has_gene(gene):
        return {"gene": gene, "error": f"gene '{gene}' not found", "results": []}
    d = normalize(data) if normalise else data
    expr = d.gene_expr(gene)
    ctrl = expr[d.mask(d.control)]
    rows = []
    raw_p = []
    for p in d.perturbation_labels():
        vals = expr[d.mask(p)]
        if len(vals) < 2:
            continue
        _, pval = stats.ttest_ind(vals, ctrl, equal_var=False)
        rows.append({
            "perturbation": p,
            "effect": round(float(vals.mean() - ctrl.mean()), 4),
            "p_value": float(f"{pval:.3g}"),
            "n_cells": int(len(vals)),
            "mean_perturbed": round(float(vals.mean()), 4),
            "mean_control": round(float(ctrl.mean()), 4),
        })
        raw_p.append(float(pval))
    # Multiple-testing correction across the whole screen. The Skeptic judges
    # significance on the FDR-adjusted q-value, not the raw per-test p.
    for r, q in zip(rows, benjamini_hochberg(raw_p)):
        r["q_value"] = float(f"{q:.3g}")
    rows.sort(key=lambda r: r["effect"], reverse=True)
    return {"gene": gene, "control_cells": int(len(ctrl)), "results": rows}


def skeptic_flags(row: dict, min_cells=20, alpha=0.05) -> list:
    """The Skeptic agent's deterministic checks on a single finding. Significance
    is judged on the FDR-adjusted q-value across the screen, so a raw p under
    0.05 that does not survive multiple-testing correction is still flagged."""
    flags = []
    if row["n_cells"] < min_cells:
        flags.append(f"only {row['n_cells']} cells behind this perturbation "
                     f"(under {min_cells}); the effect may be noise")
    q = row.get("q_value", row["p_value"])
    if q > alpha:
        flags.append(f"not significant after FDR correction (q={q} > {alpha})")
    if abs(row["effect"]) < 0.1:
        flags.append("effect size is small in log-normalised space")
    return flags


def differential_expression(data: CellData, perturbation: str, top=10,
                            normalise=True) -> dict:
    """Top genes up and down in a perturbation versus control, by mean effect."""
    d = normalize(data) if normalise else data
    if d.mask(perturbation).sum() < 2:
        return {"perturbation": perturbation, "error": "too few cells",
                "up": [], "down": []}
    diff = d.X[d.mask(perturbation)].mean(0) - d.X[d.mask(d.control)].mean(0)
    order = np.argsort(diff)
    return {
        "perturbation": perturbation,
        "up": [{"gene": d.genes[i], "effect": round(float(diff[i]), 4)}
               for i in order[::-1][:top]],
        "down": [{"gene": d.genes[i], "effect": round(float(diff[i]), 4)}
                 for i in order[:top]],
    }
