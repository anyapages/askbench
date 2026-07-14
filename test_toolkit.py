"""Validates the toolkit recovers planted ground truth and the Skeptic catches
the underpowered trap. Run from the repo root: python3 test_toolkit.py"""
from askbench.data import make_synthetic
from askbench.toolkit import (
    dataset_summary, rank_perturbations_by_effect, skeptic_flags,
)


def test_toolkit():
    data, truth = make_synthetic()
    print("summary:", dataset_summary(data))

    target = truth["target"]
    res = rank_perturbations_by_effect(data, target)
    names = [r["perturbation"] for r in res["results"]]

    print(f"\nTop 5 perturbations raising {target}:")
    for r in res["results"][:5]:
        print(f"  {r['perturbation']:6} effect={r['effect']:+.3f} "
              f"p={r['p_value']:<9} n={r['n_cells']:<4} skeptic={skeptic_flags(r)}")

    # planted-up should rise, planted-down should sink
    assert "KO_0" in names[:3], f"strong planted-up missing from top 3: {names[:3]}"
    assert "KO_1" in names[:5], f"planted-up missing from top 5: {names[:5]}"
    assert "KO_2" in names[-3:], f"planted-down not near bottom: {names[-3:]}"

    # the Skeptic must flag KO_3 (real-looking effect, only 6 cells)
    ko3 = next(r for r in res["results"] if r["perturbation"] == "KO_3")
    assert any("cells" in f for f in skeptic_flags(ko3)), "Skeptic missed the low-n trap"
    print(f"\nKO_3 (the trap): effect={ko3['effect']:+.3f} n={ko3['n_cells']} "
          f"-> {skeptic_flags(ko3)}")


if __name__ == "__main__":
    test_toolkit()
    print("\nALL CHECKS PASSED: toolkit recovers planted truth, Skeptic catches the trap.")
