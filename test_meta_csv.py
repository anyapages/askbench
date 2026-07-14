"""Tests for paste-your-own meta-analysis CSV parsing."""
from askbench.clinical import parse_meta_csv, clinical_lab_meeting


def _stub(system, user, model=None):
    return "[stub]"


def test_parse_log_rr_se():
    csv = """factor,study,log_rr,se,n
Drug A,Study 1,-0.3,0.15,200
Drug A,Study 2,-0.5,0.2,180
Drug B,Study 1,0.1,0.12,300
"""
    data, err = parse_meta_csv(csv, outcome="relapse")
    assert err is None, err
    assert data is not None
    assert data.outcome == "relapse"
    assert data.user_uploaded is True
    assert len(data.studies) == 3
    assert set(data.factors()) == {"Drug A", "Drug B"}


def test_parse_rr_ci():
    csv = """factor,rr,ci_low,ci_high,n
intervention,0.6,0.4,0.9,500
"""
    data, err = parse_meta_csv(csv)
    assert err is None, err
    assert len(data.studies) == 1
    assert abs(data.studies[0].log_rr - __import__("math").log(0.6)) < 1e-6


def test_parse_errors():
    _, err = parse_meta_csv("")
    assert err is not None
    _, err = parse_meta_csv("factor,log_rr,se\nfoo,,")
    assert err is not None


def test_panel_runs_on_user_csv():
    csv = """factor,study,log_rr,se,n
intervention,Alpha,-0.7,0.2,500
intervention,Beta,0.1,0.18,400
intervention,Gamma,-0.9,0.25,600
"""
    data, err = parse_meta_csv(csv, outcome="event")
    assert err is None
    result = clinical_lab_meeting(
        "Which factors are too heterogeneous to pool?", data, llm=_stub)
    assert "findings" in result
    assert "Your pasted table" in result["data_note"]


if __name__ == "__main__":
    test_parse_log_rr_se()
    test_parse_rr_ci()
    test_parse_errors()
    test_panel_runs_on_user_csv()
    print("test_meta_csv passed")
