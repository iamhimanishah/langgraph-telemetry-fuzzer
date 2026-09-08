# 5. The guardrail never sees ground truth

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

The baseline reference agent scored **0% grounding on the `delay` axis
at every severity**. It counted surviving datapoints and never once
looked at a timestamp, so skewed clocks were invisible to it. The fix is
a trust layer that inspects the telemetry itself before any reasoning
happens.

The layer sits inside the same repo as the fixtures. `CorruptionSpec`
says exactly which corruption was applied and how severely.
`Scenario.true_root_cause` and `tolerant_up_to` say exactly what the
right answer is. All of it is one import away, and reading any of it
would improve the score.

That is the trap. A guardrail allowed to see which corruption was
applied scores perfectly and measures nothing — it is an answer key
wearing a trust layer's clothes. The number it produces would be
unfalsifiable and worthless, and worse, it would *look* like the best
result in the repo.

## Decision

`compute_trust_metadata()` may read the (possibly corrupted) `Telemetry`
and an exogenous clock. It may **not** read `CorruptionSpec`,
`true_root_cause`, or `tolerant_up_to`. This is a hard constraint, not a
guideline — it is rule 1 in [CONTRIBUTING.md](../../CONTRIBUTING.md).

Four orthogonal trust signals, each mapping to one corruption axis:

| Signal | Catches | Computed from |
|---|---|---|
| `completeness` | `missing` | observed points vs. each series' own span |
| `monotonic` | `delay` | timestamp ordering as delivered |
| `staleness_seconds` | `truncate` | newest point vs. query time |
| `schema_match` | `drift` | declared version vs. the version the consumer parses |

The test for whether an input is admissible: **would a real consumer
know this independently of the query?** `expected_interval_seconds` and
`expected_schema_version` pass — you know your own feed's cadence, and
you know what schema your parsing code targets. "Which corruption was
applied" does not. Callers who don't know their schema pass `None` and
the check is skipped.

`staleness_seconds` scales with the feed's cadence
(`STALENESS_LIMIT_INTERVALS = 3.0`) rather than using an absolute
figure. An absolute 60s default silently never fires on a 19s window —
a threshold that cannot trigger is not a check.

## Consequences

Measured against `examples.rca_agent` over `single_axis_matrix()` (78
runs), graded with `grade()` unmodified. These are current figures,
re-measured after [ADR-0008](0008-scenario-causes-must-be-derivable.md):

| | baseline | guardrail |
|---|---|---|
| **overall grounding** | **32%** | **96%** |
| `delay` | 0% | 100% |
| `drift` | 33% | 100% |
| `truncate` | 39% | 94% |
| `missing` | 33% | 89% |
| clean | 100% | 100% |
| hallucinations | 53 | 1 |
| over-caution | 0 | 2 |

Fifty-two hallucinations became correct abstentions while over-caution
rose by two, so the grounding was not bought by making the agent
uniformly timid — which is the failure mode this constraint exists to
keep visible.

(Per-axis figures here are *grounding*. The per-axis column in the CLI
report is the stricter `pass_rate`, which also requires the named cause
to be right, so its numbers run lower. Two different questions.)

Because the guardrail only ever sees data, the same code runs unchanged
in production. There is nothing to strip out, no eval-only branch. The
MCP server exposes it directly.

The constraint has a real cost, and the last four ungrounded runs show
it exactly. They are not missing signals — they are a global heuristic
meeting per-scenario hand-set tolerances. `third-party-outage` tolerates
no missing data at all, but 15% dropped points leaves completeness above
the floor. `disk-saturation` tolerates `truncate=mild` and is flagged
anyway. Reconciling those requires reading `tolerant_up_to`, which is
ground truth. **So they stay unreconciled.** 96% with an honest
guardrail beats 100% with a compromised one.

The `drift` axis is a cautionary example of why signals must be
*designed* rather than *discovered*. It sat at 72% for a while, caught
only incidentally — renaming metrics splits series, which perturbs
completeness enough to sometimes trip the floor. Nothing was actually
looking for schema change, so `drift=mild`, which renames only a fifth of
metric names, went undetected on five scenarios. Adding `schema_match`
took it to 100% at every severity, and overall 88% → 95%.

## Alternatives rejected

**Let the guardrail read `tolerant_up_to`.** Reaches 100%, measures
nothing. This is the whole ADR.

**Have the agent self-assess data quality in its prompt.** That is the
thing being tested. An agent that hallucinates a root cause will just as
happily hallucinate that its data was fine.

**One composite trust score instead of four signals.** Loses the axis
attribution that made the `drift` gap findable at all — a single number
sitting at 72% says nothing about *which* corruption is slipping through.
