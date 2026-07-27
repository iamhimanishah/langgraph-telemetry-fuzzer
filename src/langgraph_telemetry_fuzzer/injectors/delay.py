"""Skews telemetry timestamps to simulate delayed or jittered delivery."""

from __future__ import annotations

import random
from datetime import timedelta

from langgraph_telemetry_fuzzer.models import Severity, Telemetry

_MAX_SKEW_SECONDS = {
    Severity.NONE: 0,
    Severity.MILD: 120,
    Severity.MODERATE: 900,
    Severity.SEVERE: 7200,
}


def apply(telemetry: Telemetry, severity: Severity, rng: random.Random) -> Telemetry:
    """Shifts each metric/log timestamp by an independent random offset,
    bounded by the severity's max skew window. This can also reorder events
    relative to each other, not just shift the whole window uniformly.
    """
    max_skew = _MAX_SKEW_SECONDS[severity]
    if max_skew == 0:
        return telemetry

    corrupted = telemetry.clone()
    for metric in corrupted.metrics:
        metric.timestamp += timedelta(seconds=rng.uniform(-max_skew, max_skew))
    for entry in corrupted.logs:
        entry.timestamp += timedelta(seconds=rng.uniform(-max_skew, max_skew))
    return corrupted
