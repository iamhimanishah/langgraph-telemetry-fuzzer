"""Generates the standard corruption matrix: a single-axis severity sweep
across all four injector types, plus a clean baseline.

A full cross product across 4 axes x 4 severities would be 256 combinations
per scenario -- useful for deep stress-testing, but too expensive to run
routinely and too noisy to reason about. The default matrix instead sweeps
one axis at a time, holding the others at NONE: 1 clean spec, plus 3
non-none severities x 4 axes = 13 specs. Combined-axis corruption is still
possible by hand-building a CorruptionSpec directly; this is just the
practical default eval surface.
"""

from __future__ import annotations

from langgraph_telemetry_fuzzer import CorruptionSpec, Severity

AXES = ("missing", "delay", "drift", "truncate")
NON_CLEAN_SEVERITIES = (Severity.MILD, Severity.MODERATE, Severity.SEVERE)


def single_axis_matrix(seed: int = 0) -> list[CorruptionSpec]:
    """One clean spec, plus every (axis, non-none severity) pair with
    every other axis held at NONE.
    """
    specs = [CorruptionSpec(seed=seed)]
    for axis in AXES:
        for severity in NON_CLEAN_SEVERITIES:
            specs.append(CorruptionSpec(seed=seed, **{axis: severity}))
    return specs
