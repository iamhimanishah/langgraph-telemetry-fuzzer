"""Applies a CorruptionSpec to a Telemetry bundle, deterministically."""

from __future__ import annotations

import random

from langgraph_telemetry_fuzzer.injectors import delay, drift, missing, truncate
from langgraph_telemetry_fuzzer.models import CorruptionSpec, Telemetry

# Fixed order so results are reproducible regardless of which severities are
# set: e.g. truncate slices by timestamp, so it must run after delay has
# already skewed them, not before.
_PIPELINE = (
    ("missing", missing.apply),
    ("delay", delay.apply),
    ("drift", drift.apply),
    ("truncate", truncate.apply),
)


def apply_corruptions(telemetry: Telemetry, spec: CorruptionSpec) -> Telemetry:
    """Runs each injector in `_PIPELINE`, seeded by `spec.seed`.

    Same telemetry + same spec always produces byte-identical output.
    """
    rng = random.Random(spec.seed)
    corrupted = telemetry
    for field_name, injector in _PIPELINE:
        severity = getattr(spec, field_name)
        corrupted = injector(corrupted, severity, rng)
    return corrupted
