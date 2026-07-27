"""Drops metric points and log entries to simulate missing telemetry."""

from __future__ import annotations

import random

from langgraph_telemetry_fuzzer.models import Severity, Telemetry

_DROP_RATE = {
    Severity.NONE: 0.0,
    Severity.MILD: 0.15,
    Severity.MODERATE: 0.4,
    Severity.SEVERE: 0.75,
}


def apply(telemetry: Telemetry, severity: Severity, rng: random.Random) -> Telemetry:
    """Independently drops each metric/log entry with probability = drop rate."""
    drop_rate = _DROP_RATE[severity]
    if drop_rate == 0.0:
        return telemetry

    corrupted = telemetry.clone()
    corrupted.metrics = [m for m in corrupted.metrics if rng.random() >= drop_rate]
    corrupted.logs = [entry for entry in corrupted.logs if rng.random() >= drop_rate]
    return corrupted
