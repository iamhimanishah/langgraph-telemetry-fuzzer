"""Cuts the telemetry window short, simulating an agent that had to answer
before all the data for the incident had arrived.
"""

from __future__ import annotations

import random
from typing import TypeVar

from langgraph_telemetry_fuzzer.models import LogEntry, MetricPoint, Severity, Telemetry

_KEEP_FRACTION = {
    Severity.NONE: 1.0,
    Severity.MILD: 0.7,
    Severity.MODERATE: 0.4,
    Severity.SEVERE: 0.15,
}

_Timestamped = TypeVar("_Timestamped", MetricPoint, LogEntry)


def apply(telemetry: Telemetry, severity: Severity, rng: random.Random) -> Telemetry:
    """Keeps only the earliest `keep_fraction` of metrics/logs, by timestamp."""
    keep_fraction = _KEEP_FRACTION[severity]
    if keep_fraction >= 1.0:
        return telemetry

    corrupted = telemetry.clone()
    corrupted.metrics = _keep_earliest(corrupted.metrics, keep_fraction)
    corrupted.logs = _keep_earliest(corrupted.logs, keep_fraction)
    return corrupted


def _keep_earliest(
    items: list[_Timestamped], keep_fraction: float
) -> list[_Timestamped]:
    ordered = sorted(items, key=lambda item: item.timestamp)
    cutoff = round(len(ordered) * keep_fraction)
    return ordered[:cutoff]
