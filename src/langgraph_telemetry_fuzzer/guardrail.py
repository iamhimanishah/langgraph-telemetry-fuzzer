"""Trust signals computed from telemetry alone.

This is the production-shaped half of the harness. Everything here derives
from the `Telemetry` object as delivered plus an exogenous `query_time` --
the caller's clock. It never sees `CorruptionSpec`, `true_root_cause`, or
`tolerant_up_to`, because a real guardrail sitting in front of an agent
never learns which corruption (if any) its data went through. Peeking at
the spec would let the guardrail score perfectly and measure nothing.

The four signals are deliberately orthogonal:

- `completeness`  catches dropped points  (the `missing` axis)
- `monotonic`     catches scrambled ordering  (the `delay` axis)
- `staleness`     catches windows that stop short of the query
- `schema_match`  catches an unrecognised schema  (the `drift` axis)

`monotonic` is the one that closes the documented blind spot: the reference
agent counts surviving points but never inspects timestamps, so it scores
0% grounding on `delay` at every severity.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from langgraph_telemetry_fuzzer.models import Telemetry

# Staleness is judged relative to the feed's own cadence rather than as an
# absolute wall-clock figure. A 1Hz feed whose newest point is 17s old has
# missed 17 consecutive samples and is plainly stale; a 1/hour feed 17s old
# is perfectly fresh. An absolute default cannot serve both, and one large
# enough for minute-scale feeds silently never fires on short windows.
STALENESS_LIMIT_INTERVALS = 3.0

# Below this fraction of expected points, the window is too sparse to trust.
DEFAULT_COMPLETENESS_FLOOR = 0.8


@dataclass(frozen=True)
class TrustMetadata:
    """Whether the telemetry in hand can support a confident conclusion."""

    completeness: float
    monotonic: bool
    staleness_seconds: float
    confidence: str  # "low" | "high"
    schema_match: bool = True
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        """Human-readable summary of which checks failed."""
        if not self.reasons:
            return "All trust checks passed."
        return " ".join(self.reasons)

    def to_dict(self) -> dict:
        """Plain dict for handing across a tool boundary (e.g. MCP)."""
        return {
            "completeness": round(self.completeness, 4),
            "monotonic": self.monotonic,
            "staleness_seconds": round(self.staleness_seconds, 3),
            "schema_match": self.schema_match,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def window_end(telemetry: Telemetry) -> datetime | None:
    """The newest timestamp in the bundle, or None if it carries none.

    Callers use this on *uncorrupted* telemetry to stand in for "now" --
    when the question was asked. That is exogenous information: a real
    caller knows the clock independently of what the query returns.
    """
    stamps = [m.timestamp for m in telemetry.metrics]
    stamps += [entry.timestamp for entry in telemetry.logs]
    return max(stamps) if stamps else None


def _timestamps_by_series(telemetry: Telemetry) -> dict[str, list[datetime]]:
    """Groups timestamps by their source series, in delivery order.

    Grouping matters. A bundle carrying two metrics concatenated
    (db_latency_ms then api_error_rate) restarts its clock at the boundary,
    so checking ordering across the flat list reports a false positive on
    perfectly clean telemetry. Ordering is only meaningful *within* a series.
    """
    series: dict[str, list[datetime]] = defaultdict(list)
    for metric in telemetry.metrics:
        series[f"metric:{metric.name}"].append(metric.timestamp)
    for entry in telemetry.logs:
        series[f"log:{entry.source or 'default'}"].append(entry.timestamp)
    return dict(series)


def _is_monotonic(series: dict[str, list[datetime]]) -> bool:
    """True if every series' timestamps are non-decreasing as delivered.

    Deliberately checks delivery order rather than sorted order -- sorting
    first would make this trivially true and detect nothing. The `delay`
    injector skews timestamps while leaving list position untouched, so the
    disagreement between the two orderings is precisely the signal.
    """
    for timestamps in series.values():
        if any(a > b for a, b in zip(timestamps, timestamps[1:])):
            return False
    return True


def _completeness(
    series: dict[str, list[datetime]], expected_interval_seconds: float
) -> float:
    """Observed points as a fraction of what the window implies should exist.

    The expected count comes from each series' own span: a 20-second window
    sampled every second should hold 20 points. Dropping interior points
    leaves the span intact while shrinking the count, so `missing` shows up
    here. Truncation shrinks span and count together and largely does not --
    that is what `staleness` is for.
    """
    if expected_interval_seconds <= 0:
        raise ValueError("expected_interval_seconds must be positive")

    observed = 0
    expected = 0.0
    for timestamps in series.values():
        if not timestamps:
            continue
        observed += len(timestamps)
        span = (max(timestamps) - min(timestamps)).total_seconds()
        expected += span / expected_interval_seconds + 1

    if expected <= 0:
        return 0.0
    # A series can exceed its implied count when delay collapses points
    # together; clamp so completeness stays a fraction.
    return min(observed / expected, 1.0)


def compute_trust_metadata(
    telemetry: Telemetry,
    query_time: datetime,
    expected_interval_seconds: float,
    completeness_floor: float = DEFAULT_COMPLETENESS_FLOOR,
    staleness_limit_seconds: float | None = None,
    expected_schema_version: str | None = None,
) -> TrustMetadata:
    """Scores how far the given telemetry can be trusted.

    `query_time` is the caller's clock -- when the data was asked for. It is
    exogenous on purpose: it carries no information about what corruption
    was applied, only about when the question was posed.

    `staleness_limit_seconds` defaults to STALENESS_LIMIT_INTERVALS times the
    expected interval, so the threshold scales with the feed's cadence.

    `expected_schema_version` is the schema the caller was built to read. It
    is configuration, not ground truth -- a real consumer knows which schema
    its parsing code targets, independently of what arrives. Leave it None to
    skip the check.
    """
    if staleness_limit_seconds is None:
        staleness_limit_seconds = STALENESS_LIMIT_INTERVALS * expected_interval_seconds
    series = _timestamps_by_series(telemetry)
    all_timestamps = [ts for group in series.values() for ts in group]

    if not all_timestamps:
        return TrustMetadata(
            completeness=0.0,
            monotonic=True,
            staleness_seconds=float("inf"),
            confidence="low",
            schema_match=True,
            reasons=["Telemetry contains no timestamped points."],
        )

    completeness = _completeness(series, expected_interval_seconds)
    monotonic = _is_monotonic(series)
    newest = max(all_timestamps)
    staleness_seconds = (query_time - newest).total_seconds()

    schema_match = (
        expected_schema_version is None
        or telemetry.schema_version == expected_schema_version
    )

    reasons: list[str] = []
    if not schema_match:
        reasons.append(
            f"Telemetry declares schema {telemetry.schema_version!r}, but this "
            f"consumer reads {expected_schema_version!r}; field meanings cannot "
            "be assumed to carry over."
        )
    if completeness < completeness_floor:
        reasons.append(
            f"Only {completeness:.0%} of expected points present "
            f"(floor {completeness_floor:.0%})."
        )
    if not monotonic:
        reasons.append(
            "Timestamps are out of order within a series, so event ordering "
            "cannot be trusted."
        )
    if staleness_seconds > staleness_limit_seconds:
        reasons.append(
            f"Newest point is {staleness_seconds:.0f}s old "
            f"(limit {staleness_limit_seconds:.0f}s)."
        )
    if staleness_seconds < 0:
        # Future-dated telemetry is impossible; something skewed the clock.
        reasons.append(
            f"Newest point is {abs(staleness_seconds):.0f}s in the future, "
            "which indicates skewed timestamps."
        )

    return TrustMetadata(
        completeness=completeness,
        monotonic=monotonic,
        staleness_seconds=staleness_seconds,
        confidence="low" if reasons else "high",
        schema_match=schema_match,
        reasons=reasons,
    )


@dataclass(frozen=True)
class GuardrailGate:
    """Bundles the caller-side configuration the trust checks need.

    A gate is the reusable form of the guardrail: construct one with your
    feed's cadence and schema, then evaluate any telemetry against it. All
    four fields are configuration a real consumer already has -- none of
    them says anything about which corruption was applied.
    """

    expected_interval_seconds: float
    expected_schema_version: str | None = None
    completeness_floor: float = DEFAULT_COMPLETENESS_FLOOR
    staleness_limit_seconds: float | None = None

    def evaluate(
        self, telemetry: Telemetry, query_time: datetime
    ) -> TrustMetadata:
        return compute_trust_metadata(
            telemetry,
            query_time=query_time,
            expected_interval_seconds=self.expected_interval_seconds,
            completeness_floor=self.completeness_floor,
            staleness_limit_seconds=self.staleness_limit_seconds,
            expected_schema_version=self.expected_schema_version,
        )
