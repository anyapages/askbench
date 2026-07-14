"""BCG real-data tab: vague prompts clarify; on-topic prompts get question-shaped answers."""
from askbench.clinical import make_bcg_meta, clinical_lab_meeting, clinical_question_guard


def _stub(system, user, model=None):
    return "[stub]"


def test_bcg_guard_rejects_hi():
    data, _ = make_bcg_meta()
    assert clinical_question_guard("hi", data)
    out = clinical_lab_meeting("hi", data, llm=_stub)
    assert "error" in out
    assert "findings" not in out


def test_bcg_guard_accepts_efficacy_question():
    data, _ = make_bcg_meta()
    assert clinical_question_guard("Does BCG vaccine prevent tuberculosis?", data) is None


def test_bcg_answer_varies_by_question_focus():
    data, _ = make_bcg_meta()
    eff = clinical_lab_meeting("Does BCG vaccine prevent tuberculosis across trials?", data, llm=_stub)
    het = clinical_lab_meeting("How heterogeneous are the BCG trials?", data, llm=_stub)
    assert eff["vetted_answer"] != het["vetted_answer"]
    assert "risk ratio" in eff["vetted_answer"].lower()
    assert "pooled estimate" in het["vetted_answer"].lower()


if __name__ == "__main__":
    test_bcg_guard_rejects_hi()
    test_bcg_guard_accepts_efficacy_question()
    test_bcg_answer_varies_by_question_focus()
    print("bcg guard tests passed")
