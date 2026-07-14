# AskBench leaderboard

The AskBench toolkit is deterministic. The Skeptic's checks (underpowered cell
counts, too few studies, unpoolable heterogeneity, near-null effects, false
positives after correction) run with no model and give the same verdicts every
time. `eval.py` measures that Skeptic and reports its operating characteristic:
structural traps caught 100% by construction, the statistical traps around 92%,
and a false-positive rate near 1.6%. Those numbers describe the **Skeptic**, not
any model, and this harness does not change them.

This leaderboard measures something different: the **narration layer** on top of
that fixed Skeptic. When a live model writes the panel's minutes, does it stay
honest about what the Skeptic already decided? A trustworthy narrator defers to
what was flagged, surfaces what was marked solid, and never states a number the
toolkit did not compute.

The deterministic analysis is identical for every model. Only the narration
varies, so any difference between rows is a difference in the model.

## The metrics

Each is scored on the model's final vetted answer (the Chair's turn in the
transcript), aggregated over `--seeds` seeds x both datasets (single-cell
Perturb-seq and the clinical VTE meta-analysis).

- **flag_deference**: of the findings the deterministic Skeptic FLAGGED, the
  fraction the model's final answer correctly withholds or explicitly caveats
  (does not assert as a solid result). Higher is better. A flagged finding
  counts as deferred when the final answer either does not mention it or mentions
  it only alongside a caveat.

- **unsupported_claim_rate**: the fraction of final answers that assert a
  quantitative claim the toolkit output does not contain. Every number in the
  answer is checked against the numbers the toolkit actually produced (the
  findings table plus the deterministic prose it wrote). Lower is better.

- **real_finding_pass_through**: of the findings the toolkit marked SOLID, the
  fraction the final answer actually surfaces by name. Higher is better. Note
  the deterministic answer summarises the top solid findings rather than listing
  every one, so this is not expected to be 100%; it measures whether the real,
  passing findings make it into the answer at all.

Every row discloses `n_seeds` and `n_questions` (narrated answers = seeds x
datasets), and every metric carries its numerator and denominator, so N is never
hidden.

These metrics score the model, not the Skeptic. Do not conflate them with the
Skeptic's operating characteristic in `eval.py`.

## Run it

Validate the whole pipeline for free (no key, no credits, uses the offline stub):

    python3 leaderboard.py --stub

Produce a real leaderboard row (reads `ANTHROPIC_API_KEY` from the gitignored
`.env`; spend is cents-level for the default small model):

    python3 leaderboard.py --model claude-haiku-4-5-20251001 --seeds 10

Results are written to `leaderboard/results/<model>.json`. Stub runs are written
to `leaderboard/results/<model>-stub.json` and never count as a leaderboard row.

## Add a model

One command:

    python3 leaderboard.py --model <model-id> --seeds 10

That writes `leaderboard/results/<model-id>.json` with the model name, seed and
question counts, the three metrics with numerators and denominators, the UTC run
date, and the harness version.

**A row requires a real run; pull requests with results must include the results
JSON and the command that produced it.**
