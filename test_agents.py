"""End-to-end test of the virtual lab meeting, offline via a stub LLM.
Run from the repo root: python3 test_agents.py"""
from askbench.data import make_synthetic
from askbench.agents import lab_meeting


def test_agents():
    data, truth = make_synthetic()

    # stub llm keeps this offline and deterministic; real runs use Claude
    stub = lambda system, user, model=None: "known immune-regulatory gene (offline note)"

    out = lab_meeting("Which knockouts most raise GENE7 in these cells?", data, llm=stub)

    print("Q:", out["question"])
    print("gene:", out["gene"])
    for f in out["findings"]:
        print(f"  {f['perturbation']:6} effect={f['effect']:+.3f} n={f['n_cells']:<4} "
              f"{f['verdict']:8} {f['flags']}")
    print("\nVETTED ANSWER:\n ", out["vetted_answer"])

    solid = [f["perturbation"] for f in out["findings"] if f["verdict"] == "solid"]
    assert "KO_0" in solid and "KO_1" in solid, f"true positives not solid: {solid}"

    ko3 = next(f for f in out["findings"] if f["perturbation"] == "KO_3")
    assert ko3["verdict"] == "flagged" and any("cells" in x for x in ko3["flags"]), \
        "Skeptic failed to flag the underpowered trap"

    assert "KO_0" in out["vetted_answer"] and "does not trust" in out["vetted_answer"]


if __name__ == "__main__":
    test_agents()
    print("\nALL CHECKS PASSED: panel returns a vetted answer and refuses the trap.")
