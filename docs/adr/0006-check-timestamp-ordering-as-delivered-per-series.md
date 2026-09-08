# 6. Check timestamp ordering as delivered, grouped per series

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

The `monotonic` signal is the one that catches clock skew — the axis the
baseline agent scored 0% on. Its implementation looks trivial, and two
plausible-looking versions of it are silently broken. Both were written
before the working one.

The written spec for this signal said it should check that the
timestamps are ordered "when the points are sorted."

## Decision

Check ordering **as delivered**, and group timestamps **per series**.

```python
def _is_monotonic(series, tolerance_seconds: float = 0.0) -> bool:
    """... Deliberately checks delivery order rather than sorted order --
    sorting first would make this trivially true and detect nothing."""
    for timestamps in series.values():
        for earlier, later in zip(timestamps, timestamps[1:]):
            if (earlier - later).total_seconds() > tolerance_seconds:
                return False
    return True
```

### Why not sorted

Sorted timestamps are monotonic by construction. The check would return
`True` on every input, including maximally skewed ones, and the signal
would report perfect health while detecting nothing.

This was verified empirically rather than argued: instrumenting the
check to report `after-sort` alongside the real result gave
`after-sort=True` in **every single case**, clean and corrupted alike.

The spec was wrong and the implementation deviates from it deliberately.
That deviation was flagged rather than quietly made, because a spec that
asks for a self-defeating check is worth correcting out loud.

### Why per series

A flat check across the whole bundle **false-positives on clean data**.
A `Telemetry` bundle carrying two concatenated metrics restarts its clock
at the boundary — series A runs 12:00:00→12:00:19, then series B starts
again at 12:00:00. Read as one flat list, that backward jump looks like
skew.

This was not hypothetical: `cascading-dependency-failure` was flagged
untrustworthy on perfectly clean telemetry until timestamps were grouped
by series name.

### Tolerance

`disorder_tolerance_seconds` (CLI: `--disorder-tolerance`, default
`0.0`) forgives out-of-order delivery up to N seconds, for pipelines that
are legitimately asynchronous. See the consequences below for why the
default is strict.

## Consequences

`delay` went from 0% to 100% grounding at every severity.

The per-series grouping is a permanent coupling between the guardrail
and the shape of the data it reads.
`test_every_bundled_scenario_is_trusted_when_clean` is the regression
guard, and it earns its keep — it is the test that catches a
false-positive-on-clean-data change, which is the expensive kind.

Checking delivery order means the signal is measuring something real
about the pipeline, not about the data. That has a genuine limit:
**asynchronous ingestion and clock skew are indistinguishable from the
data alone.** Several collectors writing to partitioned queues can
deliver benign points out of sequence, and beyond roughly one sample
interval this check cannot tell that from a broken clock. It flags both.

That is a documented false positive, not a bug — it is the same property
that makes the check work. `disorder_tolerance_seconds` is the escape
hatch, and it is an operator declaration ("my pipeline is async") rather
than an inference, because no inference is available.

The escape hatch must not blunt the signal beside it, so that is
asserted directly. At `disorder_tolerance_seconds=4.0`, benign ±1.5s
arrival jitter passes, while the *mildest* `delay` severity — ±120s —
is still caught. Two orders of magnitude of separation, which is what
makes the tolerance safe to offer.

The default stays at `0.0`. A tolerance that ships on by default would
weaken the signal for every user in order to spare some of them a
configuration flag.

## Alternatives rejected

**Sort, then check.** Returns `True` always. Verified empirically.

**Flat check across the bundle.** False-positives on clean multi-series
telemetry.

**Infer async-ness from the disorder distribution.** Attractive — you
could argue that small, symmetric, zero-centred disorder is jitter while
large excursions are skew. But it is a heuristic layered on a heuristic,
and getting it wrong means silently forgiving real clock skew. An
explicit operator declaration is honest about what is being assumed.
