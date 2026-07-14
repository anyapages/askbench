"""AskBench as an MCP server: make Claude call the panel as a tool.

The scientist never has to leave Claude. They ask a question in plain English;
Claude calls one of these tools; AskBench runs the deterministic analysis, lets
the Skeptic attack it, and returns a vetted answer with the caveats in front, not
buried. Every number is computed by the tested toolkit, so Claude cannot fabricate
a result, it can only report what the analysis actually found.

This is the same panel as the web app, exposed over the Model Context Protocol, so
it drops into Claude Code, Claude Desktop, the Agent SDK / API, and any workbench
that accepts a custom MCP connector.

    pip install "mcp[cli]"
    python askbench_mcp.py                 # runs over stdio

Register it with Claude Code:

    claude mcp add --transport stdio askbench -- python /abs/path/to/askbench_mcp.py

It needs no API key and spends no credits: the analysis and the Skeptic's checks
are deterministic. Claude supplies the biological interpretation on top of the
vetted numbers.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import askbench  # noqa: F401  loads .env if present; not required (tools run offline)
from askbench.data import make_synthetic
from askbench.agents import lab_meeting
from askbench.clinical import make_synthetic_vte, clinical_lab_meeting

mcp = FastMCP("askbench")

# Deterministic datasets with planted ground truth, built once. Swap these for a
# real Perturb-seq / extracted meta-analysis when wiring live data.
_CELLS, _ = make_synthetic()
_VTE, _ = make_synthetic_vte()


def _stub(system=None, user=None, model=None):
    """No nested model calls inside the tool: the caller (Claude) is the model.
    AskBench returns the rigorous, deterministic analysis; Claude interprets it."""
    return "[interpretation left to the calling model]"


def _verdict_counts(findings):
    solid = sum(1 for f in findings if f.get("verdict") == "solid")
    return solid, len(findings) - solid


def _format_single_cell(res: dict) -> str:
    if "findings" not in res:
        return ("AskBench could not act on that question: "
                + res.get("error", "no gene identified.")
                + "\nName a gene present in the screen, e.g. \"Which knockouts most raise GENE7?\"")
    findings = res["findings"]
    solid, flagged = _verdict_counts(findings)
    lines = [f"## Vetted answer (single-cell Perturb-seq)\n{res['vetted_answer']}\n",
             f"Target gene: {res.get('gene', '?')}  |  "
             f"{len(findings)} ranked, {solid} solid, {flagged} flagged by the Skeptic\n",
             "| perturbation | effect | p-value | cells | verdict |",
             "|---|---:|---:|---:|---|"]
    for f in findings:
        lines.append(f"| {f['perturbation']} | {f['effect']:+.3f} | {f['p_value']} "
                     f"| {f['n_cells']} | {f['verdict'].upper()} |")
    flagged_rows = [f for f in findings if f.get("flags")]
    if flagged_rows:
        lines.append("\n### Why the Skeptic flagged findings")
        for f in flagged_rows:
            lines.append(f"- {f['perturbation']}: " + "; ".join(f["flags"]))
    if res.get("methods"):
        lines.append(f"\nMethods. {res['methods']}")
    lines.append("\nA publication-quality figure of these findings is available in the "
                 "AskBench web app for the same question.")
    return "\n".join(lines)


def _format_clinical(res: dict) -> str:
    findings = res["findings"]
    solid, flagged = _verdict_counts(findings)
    lines = [f"## Vetted answer (clinical meta-analysis)\n{res['vetted_answer']}\n",
             f"Outcome: {res.get('outcome', '?')}  |  "
             f"{len(findings)} factors pooled, {solid} solid, {flagged} flagged\n",
             "| risk factor | pooled RR (95% CI) | studies | I² | verdict |",
             "|---|---|---:|---:|---|"]
    for f in findings:
        ci = f"{f['rr']:.2f} ({f['ci_low']:.2f} to {f['ci_high']:.2f})"
        lines.append(f"| {f['factor']} | {ci} | {f['k']} | {f['i2']:.0f}% "
                     f"| {f['verdict'].upper()} |")
    flagged_rows = [f for f in findings if f.get("flags")]
    if flagged_rows:
        lines.append("\n### Why the Skeptic flagged findings")
        for f in flagged_rows:
            lines.append(f"- {f['factor']}: " + "; ".join(f["flags"]))
    if res.get("methods"):
        lines.append(f"\nMethods. {res['methods']}")
    if res.get("data_note"):
        lines.append(f"\nNote. {res['data_note']}")
    return "\n".join(lines)


@mcp.tool()
def ask_perturbation_screen(question: str) -> str:
    """Ask a single-cell Perturb-seq screen which perturbations move a gene, in plain
    English (e.g. "Which knockouts most raise GENE7?"). Returns a vetted answer plus a
    table of the ranked perturbations with effect size, two-sided Welch t-test p-value,
    the cell count behind each, and a SOLID or FLAGGED verdict. FLAGGED findings list
    the exact statistical reason the Skeptic distrusts them (too few cells, not
    significant, effect too small). Numbers are computed by a tested toolkit and cannot
    be fabricated."""
    return _format_single_cell(lab_meeting(question, _CELLS, llm=_stub))


@mcp.tool()
def ask_meta_analysis(question: str) -> str:
    """Ask a clinical meta-analysis which risk factors most affect an outcome, in plain
    English (e.g. "Which maternal risk factors most raise pregnancy VTE across
    populations?"). Returns a vetted answer plus a table of each factor's random-effects
    pooled risk ratio with 95% CI, the number of studies, the I² heterogeneity, and a
    SOLID or FLAGGED verdict. FLAGGED factors list why the Skeptic distrusts them (too
    heterogeneous to pool, too few studies, or not significant). It refuses to report a
    single combined absolute risk when multiplying pooled ratios would be implausible."""
    return _format_clinical(clinical_lab_meeting(question, _VTE, llm=_stub))


@mcp.tool()
def datasets() -> str:
    """List the datasets AskBench can currently answer questions about, and what kind of
    question each one takes."""
    return (
        "AskBench has two synthetic datasets with planted ground truth, so answers are "
        "reproducible and the Skeptic's checks can be validated:\n\n"
        "1. Single-cell Perturb-seq screen  ->  ask_perturbation_screen\n"
        "   Which perturbations raise or lower a named gene. Try: "
        "\"Which knockouts most raise GENE7?\"\n\n"
        "2. Clinical VTE meta-analysis  ->  ask_meta_analysis\n"
        "   Which risk factors most affect an outcome across populations. Try: "
        "\"Which maternal risk factors most raise pregnancy VTE across populations?\"\n\n"
        "Both run deterministically with no model call and no credits; the calling model "
        "supplies the biological interpretation on top of the vetted numbers."
    )


if __name__ == "__main__":
    mcp.run()
