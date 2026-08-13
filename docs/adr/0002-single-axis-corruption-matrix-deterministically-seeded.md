# 2. Sweep one corruption axis at a time, deterministically seeded

- **Status:** Accepted
- **Date:** 2026-07-27

## Context

There are four corruption axes (`missing`, `delay`, `drift`,
`truncate`) and four severities (`none`, `mild`, `moderate`, `severe`).
The complete cross product is 4⁴ = 256 specs per scenario. Across six
scenarios that is 1,536 agent invocations per run — minutes of wall
clock for a rule-based agent, and real money for an LLM one.

Cost is the lesser problem. The bigger one is attribution. If an agent
hallucinates on a bundle that is simultaneously 40% dropped, clock-skewed,
renamed, and truncated, the result says only "it broke somewhere." You
cannot tell which blind spot you just found, so you cannot fix one.

Separately, corruption is random by nature, and a randomised eval whose
number moves between runs is not a measurement.

## Decision

The default matrix, `single_axis_matrix(seed=0)`, sweeps **one axis at a
time** with every other axis held at `NONE`: one clean baseline plus
3 non-none severities × 4 axes = **13 specs** per scenario.

All randomness is drawn from a single `random.Random(spec.seed)` threaded
through the injector pipeline. Same telemetry plus same spec always
produces byte-identical output.

Injectors run in a **fixed order** regardless of which severities are
set — `missing`, `delay`, `drift`, `truncate`. Order is load-bearing:
`truncate` slices by timestamp, so it has to run *after* `delay` has
already skewed them, otherwise the two corruptions silently commute into
something neither one describes.

Multi-axis corruption remains available by constructing a
`CorruptionSpec` by hand. It is not the default eval surface.

## Consequences

The per-axis report table is the direct payoff. `delay 0%` against
`missing 33%` in the baseline run named the blind spot precisely: the
reference agent counted surviving datapoints and never looked at
timestamps. A combined-axis run would have shown one bad aggregate score
and no direction to walk in.

13 specs × 6 scenarios = 78 runs completes in well under a second
offline, which keeps the suite usable in CI and cheap enough to run
against a real model.

The honest limitation: **interaction effects go unmeasured.** Real
outages corrupt several axes at once, and an agent could plausibly be
robust to each axis alone while failing on `delay` + `truncate`
together. This suite would not catch that. Nothing here claims otherwise;
the cross product is one `CorruptionSpec` away for anyone who wants it.

## Alternatives rejected

**Full cross product as the default.** 20× the cost to obscure the one
signal — which axis broke — that makes results actionable.

**Random sampling from the cross product.** Cheap and covers interactions,
but a different sample each run makes scores incomparable across commits,
and a fixed sample is just an arbitrary subset with worse attribution
than the axis sweep.

**Reseeding per injector.** Would make each injector independently
reproducible, but then `spec.seed` no longer identifies the whole run,
which is the property that actually matters.
