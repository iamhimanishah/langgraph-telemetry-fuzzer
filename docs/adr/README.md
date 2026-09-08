# Architecture Decision Records

Why this harness is built the way it is.

Most of these decisions turn on the same tension: the version that
scores higher is usually the version that measures less. An eval tool is
unusually easy to make look good — read the answer key, tune the
threshold, weaken the grader — and each of those moves improves the
headline number while destroying the thing the number is supposed to
mean. Several ADRs here document a *declined* improvement, and record
what it would have cost.

| # | Decision | Turns on |
|---|---|---|
| [1](0001-structural-adapter-instead-of-importing-langgraph.md) | Adapt to agents structurally, rather than importing LangGraph | Coupling |
| [2](0002-single-axis-corruption-matrix-deterministically-seeded.md) | Sweep one corruption axis at a time, deterministically seeded | Attribution vs. coverage |
| [3](0003-score-judgement-and-accuracy-separately.md) | Score judgement and accuracy separately | What the number means |
| [4](0004-tiered-root-cause-matching-with-optional-judge.md) | Match root causes in tiers; the judge is opt-in and matching-only | Determinism |
| [5](0005-the-guardrail-never-sees-ground-truth.md) | The guardrail never sees ground truth | Eval integrity |
| [6](0006-check-timestamp-ordering-as-delivered-per-series.md) | Check timestamp ordering as delivered, grouped per series | A check that can actually fail |
| [7](0007-keep-the-completeness-floor-at-0.8.md) | Keep the completeness floor at 0.8, despite a better-scoring alternative | Overfitting to fixtures |
| [8](0008-scenario-causes-must-be-derivable.md) | Scenario causes must be derivable from their own telemetry | Fixture honesty |

## Reading order

For the core argument, read **5 → 7 → 3**. Those three explain why the
headline grounding score is 96% rather than 100%, and why 100% would be
worse.

**6** and **8** are the two places where a naive implementation looked
correct and wasn't — worth reading before changing the guardrail or
adding a scenario.

## Format

Loosely [MADR](https://adr.github.io/madr/): status, date, context,
decision, consequences, alternatives rejected. Two local conventions:

- **Consequences include the costs**, not just the wins. If a decision
  left a known false positive or an unmeasured case, it is named there.
- **Numbers are measured, not estimated.** Every percentage in these
  records came from an actual run.

Superseding an ADR: add a new one, and mark the old one
`Superseded by ADR-NNNN` rather than editing it. The reasoning that
turned out to be wrong is usually the most useful part of the record.
