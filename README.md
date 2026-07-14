# AskBench

**AskBench lets a bench scientist ask their own data a question in plain English and get an
answer a careful reviewer would sign off on, with every caveat put in front of the answer
instead of buried.**

A construct-validity harness for AI that asks the sceptic's questions before answering: does the
analysis hold, or should it refuse?

**The sharpest proof is on real published data.** Shown the 13 real BCG-vaccine trials
(Colditz et al., JAMA 1994, the canonical `dat.bcg`), AskBench computes the pooled effect and
then refuses to report it as one number, because the trials are too heterogeneous to pool
honestly (I2 = 92.1%). No model in the loop, one command, reproducible against the source. See
[A real finding, on real published data](#a-real-finding-on-real-published-data) below.

**Try it live:** [askbench-weld.vercel.app](https://askbench-weld.vercel.app) — canonical demo URL
(no sign-up, runs model-free by default). The frontend is static on Vercel; `/ask` runs as a Python
function on the same deployment (set `ANTHROPIC_API_KEY` in Vercel for live narration).

## Can it tell a real finding from noise? Yes, and it is measured

The numbers below come straight from `eval.py`, run deterministically over 200 seeds, no
model, no credits, reproducible by anyone who clones the repo. This is the honest headline,
not one cherry-picked run:

```
Trap catch rate:
  100.0%  single-cell: KO_3 underpowered (6 cells)   <- structural, holds by construction
  100.0%  clinical: IVF_ART too few studies          <- structural, holds by construction
   92.5%  clinical: immobility too heterogeneous     <- statistical, honestly not perfect
   91.5%  clinical: maternal_height near-null         <- statistical, honestly not perfect
Real-finding pass rate:    95.5-100%
Null false-positive rate:  1.58% (82/5200), after Benjamini-Hochberg FDR, disclosed not hidden
```

The structural traps hold at 100% on every seed; the statistical traps sit in the low 90s,
and the residual false-positive rate after Benjamini-Hochberg FDR correction is disclosed, not buried. This measures
construct validity on synthetic data with planted ground truth; generalisation to real
datasets is the next step.

### The same checks hold at operating points they were never set on

The Skeptic's thresholds are fixed rules, not a learned model, so there is nothing to overfit.
The fair question is whether those same rules still fire at operating points they were never
set against. So the Skeptic, thresholds unchanged, runs over a held-out round: a real effect on
12 cells (not the primary set's 6), a negligible effect dressed as a signal, a pooled result
whose 95% CI crosses 1, a factor from a single study.

```
Held-out catch rate (Skeptic thresholds unchanged, operating points it was never set against):
  100.0%  single-cell: real effect on only 12 cells (underpowered)   <- structural, holds by construction
   97.0%  single-cell: negligible effect dressed as a signal          <- statistical
   86.0%  clinical: pooled 95% CI crosses no-effect                   <- statistical, a genuinely new check
  100.0%  clinical: pooled from a single study                        <- structural, holds by construction
Held-out real findings still pass: 99.5-100% (no over-flagging)
```

Two of these are structural and hold by construction, like the primary structural traps: 12
cells is below the 20-cell floor and one study is below the three-study floor, so they always
fire. The genuine test is the two statistical cases: 97% on a near-null dressed as a signal, and
86% on a pooled CI that crosses no-effect, which is the one genuinely new check category. That
86% sits just below the primary statistical band (91.5 to 92.5%) and is the weakest number here,
reported not hidden. The point is not a higher score; it is that the same fixed thresholds still
fire at operating points they were never set against.

```bash
python3 eval.py
```

## The verdict card

Every question comes back as a single card: the vetted answer on top, then a table of
findings each marked `SOLID` or `FLAGGED`, with the Skeptic's reason under every flagged row.

![AskBench on the real BCG meta-analysis: 13 published tuberculosis-vaccine trials, the deterministic headline numbers (200 eval seeds, a 1.58% false-positive rate after Benjamini-Hochberg, BCG pooled at I-squared 92.1% and FLAGGED, byte-identical on replay), and a worklist where each question is marked SOLID or FLAGGED with the Skeptic's one-line reason.](assets/verdict-card.png)

---

## A real finding, on real published data

Beyond the synthetic benchmark, AskBench runs on a real published meta-analysis: the 13
randomized trials of BCG vaccine against tuberculosis (Colditz et al., JAMA 1994), the
canonical `dat.bcg`. Each trial's risk ratio is computed from its real 2x2 table, so every
number is verifiable against the source. No model, one command:

```bash
python3 real_data.py
```

```
13 real randomized trials (357,347 participants), DerSimonian-Laird random effects:
  pooled risk ratio  0.49   (95% CI 0.345 to 0.695)   <- BCG roughly halves TB risk
  heterogeneity      I2 = 92.1%   Cochran Q = 152.3
  Skeptic verdict:   FLAGGED  <- too heterogeneous to report as one pooled number
```

BCG lowers TB risk, but the Skeptic refuses to hand you the pooled number as one trustworthy
estimate: the effect varies far too much across trials (the famous latitude heterogeneity of
this literature). The original authors report the random-effects estimate but foreground the
same heterogeneity caveat and explore latitude as its cause; AskBench reaches that caution
deterministically,
with no model in the loop. The live demo carries it too, under the "Real data (BCG trials)" tab.

---

## What AskBench is for

Built for the bench scientist who has a single-cell screen or a stack of studies and no
statistician on the team. Frontier AI can now do a week of analysis in an afternoon, but the
person closest to the science still often can't touch their own data without waiting on
someone who codes. AskBench closes that gap without lowering the bar for rigour: it will not
hand you a confident answer it can't defend.

## What it does

A question goes to a panel, not a single model:

- **Analyst** runs the analysis on a tested bioinformatics toolkit.
- **Skeptic** attacks each candidate with deterministic statistical checks (cell counts,
  p-values with Benjamini-Hochberg FDR correction, effect size, heterogeneity, thin evidence).
- **Contextualist** grounds the survivors in biology.
- **Chair** states a vetted answer, and refuses claims the numbers don't support.

The analysis is deterministic, so the numbers are correct with or without a model. Every number
in the verdict card and findings table comes from the toolkit, never the model; Claude only
narrates and explains on top of them. It works over two datasets today:

- a single-cell **Perturb-seq** screen (effect size, Welch t-test, cell counts), and
- a clinical **meta-analysis** (random-effects pooled risk ratio, 95% CI, I² heterogeneity).

## How the score is built

Both datasets ship with planted ground truth: some findings are real, and some are traps
(an effect on too few cells, an effect too heterogeneous to pool, evidence too thin to
trust, a near-null dressed up as a signal). A trustworthy reviewer must flag every trap and
pass every real finding. `eval.py` measures exactly that over 200 seeds, deterministically,
no model, no credits, reproducible by anyone who clones the repo, and prints the per-check
operating characteristic shown above the fold.

## Leaderboard: the Skeptic layer is load-bearing

A single honest table lives at [`web/leaderboard.html`](web/leaderboard.html) (served at
`/leaderboard` when the web server is running, linked from the demo header). It hands a model
the same vetted findings the deterministic Skeptic already checked, then measures whether the
model's final answer respects those checks. A row appears only when a real run has written
`leaderboard/results/<id>.json`, with N (seeds and questions) disclosed on every row. There is
no fabricated row: no file, no row.

The bottom row is the control: the same panel with the **Skeptic removed**. Strip the Skeptic
and flag deference collapses to **0%** (it asserts every flagged finding as settled), while
every Claude tier holds it at **98 to 100%**. That gap is the point: the table measures
deference to the checks, and it can tell a panel that respects them apart from one that ignores
them. The control is a constructed ablation, scored through the same `score_run` as every model
row, so its numbers are computed the same way, not hand-typed.

```bash
python3 leaderboard.py                   # offline by default, no key, no credits, writes the stub
python3 leaderboard.py --baseline        # the Skeptic-off control (offline): the row that fails
python3 leaderboard.py --model <id> --live   # a real, paid model row; writes results/<id>.json
```

Three metrics, each honest about where it is not perfect:

- **Flag deference** (higher is better). When the Skeptic flags a finding as unsafe to trust,
  this is the share of those flagged findings the model's final answer does not present as
  settled. A model with low deference overrides the checks and asserts the finding anyway.
- **Unsupported-claim rate** (lower is better). The share of claims in the model's final answer
  that go beyond what the vetted numbers support. A claim counts as unsupported when no number
  from the toolkit backs it, so this catches confident language the data did not earn.
- **Real-finding pass-through** (higher is better). When a finding is genuinely real and the
  Skeptic passes it, this is the share the model still carries through to its answer. It is the
  counterweight to deference: refusing everything would look cautious but would drop real signal,
  and this column catches that.

Apertus is queued, not run: a row for it appears only when the run exists, not before.

## Quick start

```bash
pip3 install -r requirements.txt
ASKBENCH_STUB_LLM=1 python3 web/server.py     # offline, spends no credits
# open the URL it prints -> http://localhost:5050
```

The server prints the URL it actually binds. It defaults to port 5050; set `PORT`
to change it (`PORT=8000 python3 web/server.py`), and if the chosen port is busy
it walks forward to the next free one and prints that instead of crashing.

Type a question, watch the panel review it, and read the vetted answer over a table of
findings, each `SOLID` or `FLAGGED`, with the Skeptic's reasons under every flagged row, a
4-turn "lab meeting" transcript, and a publication-style figure you can download.

For live Claude interpretation instead of the offline stub, put a key in a gitignored `.env`
and drop the flag:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
python3 web/server.py
```

## Call it from Claude (MCP)

AskBench is also a **Model Context Protocol server**, so Claude can call the panel as a tool.
The scientist never leaves Claude: they ask a question, Claude calls AskBench, and gets back
a vetted answer it cannot fabricate, because every number comes from the tested toolkit. It
drops into **Claude Code, Claude Desktop, the Agent SDK / API, and any workbench that accepts
a custom MCP connector** (an open standard, so it is not tied to any one product).

The MCP dependency (`mcp>=1.9`) is already installed by `pip3 install -r
requirements.txt` from the quick start, so registering the server is a single
step:

```bash
claude mcp add --transport stdio askbench -- python3 /absolute/path/to/askbench_mcp.py
```

Or paste the config directly:

```json
{
  "mcpServers": {
    "askbench": {
      "command": "python3",
      "args": ["/absolute/path/to/askbench_mcp.py"]
    }
  }
}
```

Tools exposed: `ask_perturbation_screen`, `ask_meta_analysis`, `datasets`. The server needs
no API key and spends no credits: the analysis and the Skeptic's checks are deterministic;
the calling model supplies the biological interpretation on top of the vetted numbers.

## Use it as a package

```python
import askbench
from askbench.data import make_synthetic
from askbench.agents import lab_meeting

data, truth = make_synthetic()               # synthetic Perturb-seq with planted truth
result = lab_meeting("Which knockouts most raise GENE7?", data)
# -> {question, gene, vetted_answer, findings: [{perturbation, effect, p_value, n_cells,
#     verdict: 'solid' | 'flagged', flags: [...], context}], debate, figure, caption, methods}
```

## The data is synthetic, on purpose

The datasets carry known ground truth so the toolkit and the Skeptic can be built and
validated before real data is wired in. Swap `make_synthetic` for `anndata` / `scanpy`, and
`make_synthetic_vte` for an extracted meta-analysis. The toolkit only touches a small data
surface, so nothing downstream changes. Effect sizes in the clinical set are plausible but
are not drawn from specific published studies.

## Tests

```bash
python3 test_toolkit.py      # toolkit primitives
python3 test_agents.py       # end-to-end panel (stubbed model), asserts the trap is refused
python3 eval.py              # Skeptic catch-rate against planted ground truth
```

## Acknowledgements

AskBench stands on open-source scientific Python: NumPy and SciPy for the statistics,
Matplotlib for the figures, Flask for the demo server, and the Model Context Protocol SDK for
the tool interface. The panel's biological narration runs on Claude; every number in the
verdict card and the benchmark is computed deterministically by the toolkit, never by the
model.

## Licence

MIT. See `LICENSE`. Copyright Anya Chueayen.
