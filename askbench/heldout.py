"""Held-out adversarial trap round: does the Skeptic generalise, or did it just
memorise its own traps?

The Skeptic's thresholds (cell count, FDR q-value, effect floor, I-squared,
study count, CI-crosses-null) were set while looking at the primary datasets. A
fair evaluation asks whether those SAME checks, completely unchanged, also catch
NEW planted failure modes at operating points they were never calibrated on:

  held-out single-cell   HO_POWER   a real effect on 12 cells (underpowered, but
                                     not the primary set's 6-cell case)
                         HO_TINY    a negligible effect on full cells (the
                                     near-null trap, ported to single-cell, a
                                     failure mode the single-cell set never had)
                         HO_REAL    a strong clean effect that must still pass
  held-out clinical      HO_nonsig  a pooled effect whose 95% CI crosses 1
                         HO_single  a factor pooled from a single study
                         HO_real    a strong, consistent factor that must pass

Nothing here tunes the Skeptic. `eval.py` imports the primary toolkit and skeptic
functions and runs them exactly as the primary round does, then reports the
catch rate on this set SEPARATELY. The generators live in a disjoint seed space
so the primary operating characteristic is unaffected. Like everything in the
benchmark, this round is deterministic and model-free.
"""
from __future__ import annotations

import math

import numpy as np

from .data import CellData
from .clinical import Study, MetaData


def make_heldout_single_cell(seed=0, n_genes=200, n_null=27, cells_per=120):
    """Held-out Perturb-seq screen. Planted: HO_POWER (real effect, only 12 cells),
    HO_TINY (a real but clinically negligible effect on full cells), HO_REAL (a
    strong clean effect that must pass), plus null perturbations so the FDR
    correction sees a realistic screen. Returns (CellData, truth)."""
    rng = np.random.default_rng(10_000 + seed)   # disjoint from make_synthetic
    genes = [f"GENE{i}" for i in range(n_genes)]
    target = "GENE7"
    tgt_i = genes.index(target)
    base = rng.gamma(2.0, 1.0, size=n_genes) + 0.2

    # perturbation: (target multiplier, n_cells)
    planted = {
        "HO_POWER": (1.9, 12),          # real effect, underpowered
        "HO_TINY": (1.06, cells_per),   # negligible effect, dressed as a signal
        "HO_REAL": (2.5, cells_per),    # strong, clean, must pass
    }
    perts = ["NTC"] + list(planted) + [f"N_{i}" for i in range(n_null)]
    rows, labels = [], []
    for p in perts:
        mult, n = planted.get(p, (1.0, cells_per))
        lam = np.tile(base, (n, 1))
        lam[:, tgt_i] *= mult
        rows.append(rng.poisson(lam))
        labels += [p] * n
    truth = {"target": target, "traps": ["HO_POWER", "HO_TINY"], "reals": ["HO_REAL"]}
    return CellData(np.vstack(rows), genes, np.array(labels), "NTC"), truth


def make_heldout_vte(seed=0):
    """Held-out VTE meta-analysis. Planted: HO_nonsig (a modest effect with wide
    standard errors so the pooled 95% CI crosses 1), HO_single (a factor with only
    one study), HO_real (strong and consistent, must pass), plus a moderate factor
    for realism. Returns (MetaData, truth)."""
    rng = np.random.default_rng(20_000 + seed)   # disjoint from make_synthetic_vte
    pops = ["Nordic cohort", "US claims", "UK Biobank", "Asian registry",
            "French cohort", "Dutch registry", "Australian cohort"]
    # factor: (true log RR, k studies, mean cohort n, het sd, se low, se high)
    plan = {
        "HO_nonsig":   (math.log(1.25), 4, 500, 0.05, 0.35, 0.48),   # CI crosses 1
        "HO_single":   (math.log(2.0),  1, 400, 0.05, 0.15, 0.25),   # single study
        "HO_real":     (math.log(5.0),  6, 900, 0.06, 0.12, 0.22),   # strong, clean
        "moderate_ref":(math.log(2.0),  5, 800, 0.07, 0.12, 0.25),   # realism only
    }
    studies = []
    for factor, (mu, k, n_mean, het_sd, se_lo, se_hi) in plan.items():
        for j in range(k):
            true_eff = rng.normal(mu, het_sd)
            n = int(max(60, rng.normal(n_mean, n_mean * 0.25)))
            se = round(float(rng.uniform(se_lo, se_hi)), 4)
            obs = round(float(rng.normal(true_eff, se)), 4)
            studies.append(Study(factor, obs, se, n, pops[j % len(pops)]))
    truth = {"traps": ["HO_nonsig", "HO_single"], "reals": ["HO_real"]}
    return MetaData(studies, outcome="pregnancy-associated VTE",
                    baseline_per_1000=1.2), truth
