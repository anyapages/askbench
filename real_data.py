"""AskBench on REAL data, not synthetic.

Runs the deterministic clinical panel over a real published meta-analysis: the 13
randomized trials of BCG vaccine against tuberculosis from Colditz et al., JAMA 1994
(the canonical `dat.bcg`). Every log risk ratio is computed from the trial's real 2x2
table, so the result is verifiable against the source. No model, no credits, one command:

    python3 real_data.py
"""
from __future__ import annotations

from askbench.clinical import (make_bcg_meta, rank_factors_by_pooled_effect,
                               meta_skeptic_flags)


def main():
    data, source = make_bcg_meta()
    row = rank_factors_by_pooled_effect(data)[0]
    flags = meta_skeptic_flags(row)

    print("\nAskBench on REAL data  ---  does BCG vaccine prevent tuberculosis?")
    print(f"Source: {source}\n")
    print(f"  {row['k']} real randomized trials, pooled with DerSimonian-Laird "
          f"random effects:")
    print(f"    pooled risk ratio  {row['rr']}   (95% CI {row['ci_low']} to {row['ci_high']})")
    print(f"    heterogeneity      I2 = {row['i2']}%   Cochran Q = {row['q']}   "
          f"tau2 = {row['tau2']}")
    print(f"    total participants {row['n_total']:,}\n")

    if flags:
        print("  Skeptic verdict:  FLAGGED")
        for f in flags:
            print(f"    - {f}")
        print("\n  The real finding: pooled across all 13 trials, BCG lowers TB risk, but")
        print("  the panel refuses to report the pooled ratio as one trustworthy number.")
        print("  The effect varies far too much across trials to pool honestly (this is")
        print("  the famous latitude heterogeneity of the BCG literature). The Skeptic")
        print("  reproduces the field's own caution, on real data, deterministically,")
        print("  with no model in the loop.")
    else:
        print("  Skeptic verdict:  SOLID")
        print("  The pooled estimate survives every check.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
