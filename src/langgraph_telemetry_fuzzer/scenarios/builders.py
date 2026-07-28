"""Shared helpers for building synthetic telemetry for scenario fixtures.

Numeric pattern generators return plain float lists, decoupled from any
particular metric name or timestamp, so the same pattern (a step, a ramp,
a burst) can be reused across differently-named metrics. build_metric_series
zips a pattern with timestamps into MetricPoint objects.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from langgraph_telemetry_fuzzer import LogEntry, MetricPoint

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


def step(
    n_points: int, baseline: float, spike: float, spike_at_fraction: float = 0.5
) -> list[float]:
    """Low, then high -- switching at spike_at_fraction through the window."""
    cutover = round(n_points * spike_at_fraction)
    return [baseline] * cutover + [spike] * (n_points - cutover)


def ramp(n_points: int, start: float, end: float) -> list[float]:
    """A linear rise (or fall) from start to end across the window."""
    if n_points <= 1:
        return [end] * n_points
    step_size = (end - start) / (n_points - 1)
    return [start + step_size * i for i in range(n_points)]


def bursty(n_points: int, baseline: float, burst: float, seed: int = 0) -> list[float]:
    """Mostly baseline, with intermittent bursts -- noisier than a clean
    step, so a corrupted sample is more likely to hide the pattern entirely.
    """
    rng = random.Random(seed)
    return [burst if rng.random() < 0.3 else baseline for _ in range(n_points)]


def build_metric_series(
    name: str,
    values: list[float],
    start: datetime = BASE_TIME,
    interval: timedelta = timedelta(seconds=1),
) -> list[MetricPoint]:
    return [
        MetricPoint(timestamp=start + interval * i, name=name, value=value)
        for i, value in enumerate(values)
    ]


def build_log_series(
    messages: list[str],
    start: datetime = BASE_TIME,
    interval: timedelta = timedelta(seconds=1),
    level: str = "INFO",
) -> list[LogEntry]:
    return [
        LogEntry(timestamp=start + interval * i, level=level, message=message)
        for i, message in enumerate(messages)
    ]
