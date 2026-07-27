"""Renames metric fields and bumps schema_version to simulate schema drift.

The agent isn't told about the rename -- that's the point. A brittle agent
that pattern-matches on a hardcoded metric name will silently stop seeing
that signal instead of noticing its schema changed.
"""

from __future__ import annotations

import random

from langgraph_telemetry_fuzzer.models import Severity, Telemetry

_RENAME_RATE = {
    Severity.NONE: 0.0,
    Severity.MILD: 0.2,
    Severity.MODERATE: 0.5,
    Severity.SEVERE: 1.0,
}

_DRIFT_SUFFIX = "_v2"


def apply(telemetry: Telemetry, severity: Severity, rng: random.Random) -> Telemetry:
    """Renames a fraction of metric names (by suffix) and bumps schema_version."""
    rename_rate = _RENAME_RATE[severity]
    if rename_rate == 0.0:
        return telemetry

    corrupted = telemetry.clone()
    corrupted.schema_version = f"{corrupted.schema_version}{_DRIFT_SUFFIX}"
    for metric in corrupted.metrics:
        if rng.random() < rename_rate:
            metric.name = f"{metric.name}{_DRIFT_SUFFIX}"
    return corrupted
