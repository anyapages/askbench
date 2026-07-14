"""AskBench evaluation: does the Skeptic actually catch bad science?

Both synthetic datasets ship with known ground truth. Some findings are real, and
some are planted traps: an effect on too few cells, an effect that varies too much
across populations to pool, evidence too thin to trust, a near-null dressed up as a
signal. A trustworthy reviewer must FLAG every trap and PASS the real findings.

This measures exactly that, deterministically, with no model and no credits, so the
number is reproducible by anyone who clones the repo. Run:

    python eval.py
"""
from __future__ import annotations

from askbench.data import make_synthetic
from askbench.toolkit import rank_perturbations_by_effect, skeptic_flags
from askbench.clinical import (make_synthetic_vte, rank_factors_by_pooled_effect,
                               meta_skeptic_flags)
from askbench.heldout import make_heldout_single_cell, make_heldout_vte


def _line(name, ok):
    return f"  [{'PASS' if ok else 'MISS'}]  {name}"


def single_cell_checks(seed=0):
    """Perturb-seq screen. Planted: KO_0/KO_1 genuinely raise GENE7 on full cell
    counts (must pass clean); KO_3 raises it too but on only 6 cells (a trap the
    Skeptic must flag as underpowered)."""
    data, truth = make_synthetic(seed=seed)
    ranked = rank_perturbations_by_effect(data, truth["target"])["results"]
    by = {r["perturbation"]: r for r in ranked}
    checks = []

    trap = by.get("KO_3")
    caught = bool(trap and any("cells" in f for f in skeptic_flags(trap)))
    checks.append(("trap", "underpowered KO_3 (6 cells) flagged", caught))

    for ko in ("KO_0", "KO_1"):
        r = by.get(ko)
        clean = bool(r and not skeptic_flags(r))
        checks.append(("real", f"{ko} raises GENE7, passes clean", clean))

    nulls = [p for p in by if p not in truth["effects"]]
    false_pos = [p for p in nulls if not skeptic_flags(by[p])]
    checks.append(("info", f"{len(false_pos)}/{len(nulls)} null perturbations slipped "
                           f"past the Skeptic", len(false_pos) == 0))
    return checks


def clinical_checks(seed=0):
    """VTE meta-analysis. Planted: previous_VTE and thrombophilia are strong and
    consistent (must pass clean); immobility is real but wildly heterogeneous across
    populations, IVF_ART has only 2 studies, maternal_height is near-null. The last
    three are traps the Skeptic must flag."""
    data, _ = make_synthetic_vte(seed=seed)
    ranked = rank_factors_by_pooled_effect(data)
    by = {r["factor"]: r for r in ranked}
    checks = []

    imm = by["immobility"]
    checks.append(("trap", "immobility flagged as too heterogeneous to pool",
                   any("heterogeneity" in f for f in meta_skeptic_flags(imm))))
    ivf = by["IVF_ART"]
    checks.append(("trap", "IVF_ART flagged as too few studies",
                   any("studies" in f for f in meta_skeptic_flags(ivf))))
    mh = by["maternal_height"]
    checks.append(("trap", "maternal_height (near-null) flagged",
                   bool(meta_skeptic_flags(mh))))

    for factor in ("previous_VTE", "thrombophilia"):
        r = by[factor]
        checks.append(("real", f"{factor} pools cleanly, passes",
                       not meta_skeptic_flags(r)))
    return checks


def operating_characteristic(n_seeds=200):
    """Run both tracks across many seeds so the headline is not one lucky seed.
    Structural traps (fixed cell and study counts) hold by construction; the
    near-null and heterogeneity traps and the null false-positive rate are where
    the Skeptic's discrimination is actually tested. This is the honest number."""
    from collections import defaultdict
    traps = defaultdict(int)
    reals = defaultdict(int)
    null_slipped = null_total = 0

    for seed in range(n_seeds):
        data, truth = make_synthetic(seed=seed)
        by = {r["perturbation"]: r
              for r in rank_perturbations_by_effect(data, truth["target"])["results"]}
        t = by.get("KO_3")
        traps["single-cell: KO_3 underpowered (6 cells)"] += bool(
            t and any("cells" in f for f in skeptic_flags(t)))
        for ko in ("KO_0", "KO_1"):
            r = by.get(ko)
            reals[f"single-cell: {ko} real effect"] += bool(r and not skeptic_flags(r))
        nulls = [p for p in by if p not in truth["effects"]]
        null_total += len(nulls)
        null_slipped += sum(1 for p in nulls if not skeptic_flags(by[p]))

        cby = {r["factor"]: r
               for r in rank_factors_by_pooled_effect(make_synthetic_vte(seed=seed)[0])}
        traps["clinical: immobility too heterogeneous"] += bool(
            any("heterogeneity" in f for f in meta_skeptic_flags(cby["immobility"])))
        traps["clinical: IVF_ART too few studies"] += bool(
            any("studies" in f for f in meta_skeptic_flags(cby["IVF_ART"])))
        traps["clinical: maternal_height near-null"] += bool(
            meta_skeptic_flags(cby["maternal_height"]))
        for factor in ("previous_VTE", "thrombophilia"):
            reals[f"clinical: {factor}"] += bool(not meta_skeptic_flags(cby[factor]))

    print(f"Operating characteristic over {n_seeds} seeds (not one cherry-picked run)\n")
    print("  Trap catch rate:")
    for name, hits in traps.items():
        print(f"    {hits:>4}/{n_seeds}  ({100.0 * hits / n_seeds:5.1f}%)  {name}")
    print("\n  Real-finding pass rate:")
    for name, hits in reals.items():
        print(f"    {hits:>4}/{n_seeds}  ({100.0 * hits / n_seeds:5.1f}%)  {name}")
    fp = 100.0 * null_slipped / null_total if null_total else 0.0
    print(f"\n  Null false-positive rate: {null_slipped}/{null_total} nulls slipped "
          f"past the Skeptic ({fp:.2f}%), reported honestly, never hidden.\n")

    # Structured summary for the figure, so the plot draws these exact numbers
    # instead of anything hand-typed. Structural traps (fixed cell and study
    # counts) hold by construction; the heterogeneity and near-null traps are the
    # statistical ones. Short display labels keep the bar chart readable.
    def _rate(hits):
        return round(100.0 * hits / n_seeds, 1)

    STRUCTURAL = {
        "single-cell: KO_3 underpowered (6 cells)": "Structural · KO_3 (6 cells)",
        "clinical: IVF_ART too few studies": "Structural · IVF_ART (2 studies)",
    }
    STATISTICAL = {
        "clinical: immobility too heterogeneous": "Statistical · immobility heterogeneity",
        "clinical: maternal_height near-null": "Statistical · maternal_height near-null",
    }
    REAL_LABELS = {
        "single-cell: KO_0 real effect": "Real · KO_0 effect",
        "single-cell: KO_1 real effect": "Real · KO_1 effect",
        "clinical: previous_VTE": "Real · previous_VTE",
        "clinical: thrombophilia": "Real · thrombophilia",
    }
    bars = []
    for name, disp in STRUCTURAL.items():
        bars.append((disp, _rate(traps[name]), "structural"))
    for name, disp in STATISTICAL.items():
        bars.append((disp, _rate(traps[name]), "statistical"))
    for name, disp in REAL_LABELS.items():
        bars.append((disp, _rate(reals[name]), "real"))
    return {
        "n_seeds": n_seeds,
        "bars": bars,
        "null_slipped": null_slipped,
        "null_total": null_total,
        "null_fp_rate": round(fp, 2),
    }


def heldout_operating_characteristic(n_seeds=200):
    """The unseen-operating-points test. The Skeptic's thresholds are fixed rules,
    not a learned model, so the honest question is not "did it generalise" but "do
    the same fixed checks still fire at operating points they were never set against"
    (a real effect on 12 cells, a negligible effect, a CI that crosses 1, a
    single-study pool; see askbench/heldout.py). Reported separately so the primary
    round cannot flatter it. Deterministic and model-free, like the rest."""
    from collections import defaultdict
    traps = defaultdict(int)
    reals = defaultdict(int)

    for seed in range(n_seeds):
        data, truth = make_heldout_single_cell(seed=seed)
        by = {r["perturbation"]: r
              for r in rank_perturbations_by_effect(data, truth["target"])["results"]}
        # HO_POWER must be flagged for underpower; HO_TINY for a negligible or
        # non-significant effect; each only counts when caught for the RIGHT reason.
        traps["held-out single-cell: HO_POWER underpowered (12 cells)"] += bool(
            "HO_POWER" in by and any("cells" in f for f in skeptic_flags(by["HO_POWER"])))
        traps["held-out single-cell: HO_TINY negligible effect"] += bool(
            "HO_TINY" in by and any(("effect size" in f or "significant" in f)
                                    for f in skeptic_flags(by["HO_TINY"])))
        reals["held-out single-cell: HO_REAL strong effect"] += bool(
            "HO_REAL" in by and not skeptic_flags(by["HO_REAL"]))

        cby = {r["factor"]: r
               for r in rank_factors_by_pooled_effect(make_heldout_vte(seed=seed)[0])}
        traps["held-out clinical: HO_nonsig CI crosses null"] += bool(
            any("crosses no-effect" in f for f in meta_skeptic_flags(cby["HO_nonsig"])))
        traps["held-out clinical: HO_single single study"] += bool(
            any("studies" in f for f in meta_skeptic_flags(cby["HO_single"])))
        reals["held-out clinical: HO_real strong pooled effect"] += bool(
            not meta_skeptic_flags(cby["HO_real"]))

    print("HELD-OUT round: same Skeptic, new traps it was never calibrated on "
          f"({n_seeds} seeds)\n")
    print("  Trap catch rate (same fixed checks, new operating points):")
    for name, hits in traps.items():
        print(f"    {hits:>4}/{n_seeds}  ({100.0 * hits / n_seeds:5.1f}%)  {name}")
    print("\n  Real-finding pass rate (no over-flagging on unseen reals):")
    for name, hits in reals.items():
        print(f"    {hits:>4}/{n_seeds}  ({100.0 * hits / n_seeds:5.1f}%)  {name}")
    print("\n  The Skeptic's thresholds were NOT changed for this round; these are "
          "new failure\n  modes at new operating points, caught by the same checks.\n")
    return {"traps": dict(traps), "reals": dict(reals), "n_seeds": n_seeds}


def main():
    sections = [("Single-cell Perturb-seq screen", single_cell_checks(seed=0)),
                ("Clinical VTE meta-analysis", clinical_checks(seed=0))]

    traps = traps_ok = reals = reals_ok = 0
    print("\nAskBench evaluation  ---  can the Skeptic tell real from noise?")
    print("Example run (seed 0), shown in full detail:\n")
    for title, checks in sections:
        print(title)
        for kind, name, ok in checks:
            if kind == "trap":
                traps += 1; traps_ok += ok
            elif kind == "real":
                reals += 1; reals_ok += ok
            print(_line(name, ok) if kind != "info" else f"  [info]  {name}")
        print()

    catch = 100.0 * traps_ok / traps if traps else 0.0
    recall = 100.0 * reals_ok / reals if reals else 0.0
    print(f"Skeptic trap-catch rate:     {traps_ok}/{traps}  ({catch:.0f}%)")
    print(f"Real-finding pass rate:      {reals_ok}/{reals}  ({recall:.0f}%)")
    ok = (traps_ok == traps) and (reals_ok == reals)
    print("RESULT (seed 0):", "all planted traps caught, all real findings passed."
          if ok else "some checks failed (see above).")
    print("\n" + "-" * 68 + "\n")
    operating_characteristic(n_seeds=200)
    print("-" * 68 + "\n")
    heldout_operating_characteristic(n_seeds=200)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
