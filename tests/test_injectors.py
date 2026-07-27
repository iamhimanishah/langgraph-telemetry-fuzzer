import random
from datetime import timedelta

from helpers import BASE_TIME, build_telemetry

from langgraph_telemetry_fuzzer.injectors import delay, drift, missing, truncate
from langgraph_telemetry_fuzzer.models import Severity


def rng() -> random.Random:
    return random.Random(0)


# -- missing --------------------------------------------------------------


def test_missing_none_severity_is_a_noop(telemetry):
    corrupted = missing.apply(telemetry, Severity.NONE, rng())
    assert corrupted is telemetry


def test_missing_severe_drops_most_points(telemetry):
    corrupted = missing.apply(telemetry, Severity.SEVERE, rng())
    assert len(corrupted.metrics) < len(telemetry.metrics)
    assert len(corrupted.logs) < len(telemetry.logs)


def test_missing_does_not_mutate_original(telemetry):
    original_count = len(telemetry.metrics)
    missing.apply(telemetry, Severity.SEVERE, rng())
    assert len(telemetry.metrics) == original_count


# -- delay ------------------------------------------------------------------


def test_delay_none_severity_is_a_noop(telemetry):
    corrupted = delay.apply(telemetry, Severity.NONE, rng())
    assert corrupted is telemetry


def test_delay_severe_shifts_timestamps_within_bound(telemetry):
    corrupted = delay.apply(telemetry, Severity.SEVERE, rng())
    max_skew = timedelta(hours=2)

    shifted = 0
    for original, corrupted_metric in zip(telemetry.metrics, corrupted.metrics):
        drift_amount = corrupted_metric.timestamp - original.timestamp
        assert abs(drift_amount) <= max_skew
        if drift_amount != timedelta(0):
            shifted += 1
    assert shifted > 0


# -- drift --------------------------------------------------------------


def test_drift_none_severity_is_a_noop(telemetry):
    corrupted = drift.apply(telemetry, Severity.NONE, rng())
    assert corrupted is telemetry
    assert corrupted.schema_version == "1.0"


def test_drift_severe_renames_every_metric_and_bumps_schema(telemetry):
    corrupted = drift.apply(telemetry, Severity.SEVERE, rng())
    assert corrupted.schema_version != telemetry.schema_version
    assert all(m.name.endswith("_v2") for m in corrupted.metrics)


def test_drift_does_not_mutate_original(telemetry):
    drift.apply(telemetry, Severity.SEVERE, rng())
    assert telemetry.schema_version == "1.0"
    assert all(not m.name.endswith("_v2") for m in telemetry.metrics)


# -- truncate -----------------------------------------------------------


def test_truncate_none_severity_is_a_noop(telemetry):
    corrupted = truncate.apply(telemetry, Severity.NONE, rng())
    assert corrupted is telemetry


def test_truncate_severe_keeps_only_earliest_fraction():
    original = build_telemetry(n_metrics=20, n_logs=20)
    corrupted = truncate.apply(original, Severity.SEVERE, rng())

    assert len(corrupted.metrics) == round(20 * 0.15)
    cutoff = BASE_TIME + timedelta(seconds=5)
    assert all(m.timestamp < cutoff for m in corrupted.metrics)


def test_truncate_keeps_earliest_even_if_input_is_unsorted():
    original = build_telemetry(n_metrics=10, n_logs=0)
    original.metrics.reverse()

    corrupted = truncate.apply(original, Severity.MILD, rng())

    timestamps = [m.timestamp for m in corrupted.metrics]
    assert timestamps == sorted(timestamps)
    assert timestamps[0] == BASE_TIME
