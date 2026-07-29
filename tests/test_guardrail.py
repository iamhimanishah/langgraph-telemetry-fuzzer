from datetime import timedelta

import pytest
from helpers import BASE_TIME, build_spiking_telemetry, build_telemetry

from langgraph_telemetry_fuzzer import (
    CorruptionSpec,
    MetricPoint,
    Severity,
    Telemetry,
    apply_corruptions,
)
from langgraph_telemetry_fuzzer.guardrail import compute_trust_metadata
from langgraph_telemetry_fuzzer.scenarios import ALL_SCENARIOS

# The synthetic fixtures sample once per second, and a realistic query lands
# at the end of the incident window rather than at wall-clock "now".
INTERVAL = 1.0


def query_time_for(telemetry: Telemetry):
    return max(m.timestamp for m in telemetry.metrics)


# -- clean telemetry ---------------------------------------------------------


def test_clean_telemetry_is_trusted():
    telemetry = build_telemetry()

    trust = compute_trust_metadata(telemetry, query_time_for(telemetry), INTERVAL)

    assert trust.confidence == "high"
    assert trust.monotonic is True
    assert trust.completeness == 1.0
    assert trust.reason == "All trust checks passed."


def test_multi_series_telemetry_is_not_a_false_positive():
    """Two metric series concatenated restart the clock at the boundary.
    Checking ordering across the flat list would flag this clean bundle;
    grouping by series is what keeps it honest.
    """
    first = build_spiking_telemetry(n_points=10).metrics
    second = [
        MetricPoint(timestamp=m.timestamp, name="db_latency_ms", value=m.value * 100)
        for m in first
    ]
    telemetry = Telemetry(metrics=first + second)

    trust = compute_trust_metadata(telemetry, query_time_for(telemetry), INTERVAL)

    assert trust.monotonic is True
    assert trust.confidence == "high"


# -- delay: the blind spot this exists to close ------------------------------


DELAY_SEVERITIES = [Severity.MILD, Severity.MODERATE, Severity.SEVERE]


@pytest.mark.parametrize("severity", DELAY_SEVERITIES)
def test_monotonic_fires_on_delay_at_every_severity(severity):
    """The reference agent scores 0% grounding across all three delay
    severities because it never inspects timestamps. The ordering check is
    what catches exactly those runs.
    """
    telemetry = build_telemetry()
    spec = CorruptionSpec(seed=0, delay=severity)
    corrupted = apply_corruptions(telemetry, spec)

    trust = compute_trust_metadata(corrupted, query_time_for(telemetry), INTERVAL)

    assert trust.monotonic is False
    assert trust.confidence == "low"
    assert "out of order" in trust.reason


@pytest.mark.parametrize("severity", DELAY_SEVERITIES)
def test_delay_is_caught_on_every_bundled_scenario(severity):
    """Same claim, but against the real scenario suite rather than a
    hand-built fixture -- these are the fixtures the published 0% came from.
    """
    spec = CorruptionSpec(seed=0, delay=severity)

    for scenario in ALL_SCENARIOS:
        corrupted = apply_corruptions(scenario.telemetry, spec)
        trust = compute_trust_metadata(
            corrupted, query_time_for(scenario.telemetry), INTERVAL
        )

        assert trust.monotonic is False, scenario.id
        assert trust.confidence == "low", scenario.id


def test_every_bundled_scenario_is_trusted_when_clean():
    """The counterpart guarantee: the guardrail must not force abstention on
    good data, or it just trades hallucination for over-caution.
    """
    for scenario in ALL_SCENARIOS:
        trust = compute_trust_metadata(
            scenario.telemetry, query_time_for(scenario.telemetry), INTERVAL
        )

        assert trust.confidence == "high", f"{scenario.id}: {trust.reason}"


# -- completeness ------------------------------------------------------------


def test_severe_missing_drops_completeness_below_the_floor():
    telemetry = build_telemetry()
    spec = CorruptionSpec(seed=0, missing=Severity.SEVERE)
    corrupted = apply_corruptions(telemetry, spec)

    trust = compute_trust_metadata(corrupted, query_time_for(telemetry), INTERVAL)

    assert trust.completeness < 0.8
    assert trust.confidence == "low"
    assert "expected points" in trust.reason


def test_missing_does_not_disturb_ordering():
    """Dropped points leave the survivors in order -- completeness and
    monotonicity are independent signals, not two views of one.
    """
    telemetry = build_telemetry()
    spec = CorruptionSpec(seed=0, missing=Severity.SEVERE)
    corrupted = apply_corruptions(telemetry, spec)

    trust = compute_trust_metadata(corrupted, query_time_for(telemetry), INTERVAL)

    assert trust.monotonic is True


def test_completeness_rejects_a_non_positive_interval():
    with pytest.raises(ValueError, match="must be positive"):
        compute_trust_metadata(build_telemetry(), BASE_TIME, 0)


# -- staleness ---------------------------------------------------------------


def test_stale_window_is_flagged():
    telemetry = build_telemetry()
    late_query = query_time_for(telemetry) + timedelta(minutes=10)

    trust = compute_trust_metadata(telemetry, late_query, INTERVAL)

    assert trust.staleness_seconds == pytest.approx(600.0)
    assert trust.confidence == "low"
    assert "old" in trust.reason


def test_future_dated_telemetry_is_flagged():
    """Delay can skew a timestamp past the query. Data from the future is
    impossible, so it is its own trust signal.
    """
    telemetry = build_telemetry()
    early_query = query_time_for(telemetry) - timedelta(minutes=5)

    trust = compute_trust_metadata(telemetry, early_query, INTERVAL)

    assert trust.staleness_seconds < 0
    assert trust.confidence == "low"
    assert "future" in trust.reason


# -- degenerate input --------------------------------------------------------


def test_empty_telemetry_is_untrusted():
    trust = compute_trust_metadata(Telemetry(), BASE_TIME, INTERVAL)

    assert trust.confidence == "low"
    assert trust.completeness == 0.0
    assert "no timestamped points" in trust.reason


def test_to_dict_is_tool_boundary_safe():
    telemetry = build_telemetry()

    payload = compute_trust_metadata(
        telemetry, query_time_for(telemetry), INTERVAL
    ).to_dict()

    assert set(payload) == {
        "completeness",
        "monotonic",
        "staleness_seconds",
        "confidence",
        "reason",
    }
    assert isinstance(payload["monotonic"], bool)
