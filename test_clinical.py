"""Offline self-test for the clinical meta-analysis track. Stubs the model, so it
spends no credits, and asserts the panel refuses the traps (high heterogeneity,
too few studies, near-null) exactly as a careful reviewer would."""
from askbench.clinical import make_synthetic_vte, clinical_lab_meeting


def _stub(system, user, model=None):
    return "[stub] mechanism note unavailable offline"


def test_clinical():
    data, truth = make_synthetic_vte(seed=0)
    q = ("Which combination of maternal risk factors contributes most to "
         "absolute VTE risk across different populations?")
    result = clinical_lab_meeting(q, data, llm=_stub)
    by_factor = {f["factor"]: f for f in result["findings"]}

    # Strong, consistent factors survive the panel.
    for f in truth["strong_consistent"]:
        assert by_factor[f]["verdict"] == "solid", (f, by_factor[f])

    # The heterogeneity trap is refused, for the right reason.
    trap = by_factor[truth["high_heterogeneity_trap"]]
    assert trap["verdict"] == "flagged", trap
    assert any("heterogeneity" in fl for fl in trap["flags"]), trap["flags"]

    # Too-few-studies factor is refused.
    under = by_factor[truth["underpowered"]]
    assert under["verdict"] == "flagged", under
    assert any("studies" in fl for fl in under["flags"]), under["flags"]

    # Near-null factor is refused as non-significant.
    null = by_factor[truth["near_null"]]
    assert null["verdict"] == "flagged", null

    # The answer surfaces the across-populations caveat, not a fabricated number.
    ans = result["vetted_answer"].lower()
    assert "populations" in ans, ans

    print("Q:", q)
    print("A:", result["vetted_answer"])
    print()
    print("data note:", result["data_note"])


if __name__ == "__main__":
    test_clinical()
    print()
    print("clinical panel self-test passed")
