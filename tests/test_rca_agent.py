import pytest
from helpers import build_spiking_telemetry

from langgraph_telemetry_fuzzer import CorruptionSpec, Severity, apply_corruptions
from langgraph_telemetry_fuzzer.adapter import LangGraphAdapter

langgraph = pytest.importorskip("langgraph")

from examples.rca_agent import build_graph  # noqa: E402


@pytest.fixture
def adapter():
    return LangGraphAdapter(build_graph())


def test_agent_commits_to_a_root_cause_on_clean_telemetry(adapter):
    verdict = adapter.run(build_spiking_telemetry())

    assert verdict.insufficient_signal is False
    assert verdict.root_cause == "downstream payment API timeout"
    assert verdict.confidence > 0


def test_agent_abstains_when_missing_corruption_is_severe(adapter):
    # Small n so a 75% drop rate reliably pushes survivors below MIN_POINTS;
    # a large n keeps too much margin above the threshold to be a solid check.
    telemetry = build_spiking_telemetry(n_points=8)
    spec = CorruptionSpec(seed=0, missing=Severity.SEVERE)
    corrupted = apply_corruptions(telemetry, spec)

    verdict = adapter.run(corrupted)

    assert verdict.insufficient_signal is True
    assert verdict.root_cause is None


def test_agent_still_answers_under_mild_missing_corruption(adapter):
    telemetry = build_spiking_telemetry()
    spec = CorruptionSpec(seed=0, missing=Severity.MILD)
    corrupted = apply_corruptions(telemetry, spec)

    verdict = adapter.run(corrupted)

    assert verdict.insufficient_signal is False
    assert verdict.root_cause == "downstream payment API timeout"


def test_agent_abstains_when_drift_renames_the_metric_it_looks_for(adapter):
    telemetry = build_spiking_telemetry()
    spec = CorruptionSpec(seed=0, drift=Severity.SEVERE)
    corrupted = apply_corruptions(telemetry, spec)

    verdict = adapter.run(corrupted)

    assert verdict.insufficient_signal is True


def test_agent_is_naive_about_severe_delay(adapter):
    """Documents a known blind spot: the agent checks how many matching
    points it has, but never checks whether their timestamps make sense.
    Severe timestamp skew doesn't remove or change any values, so the
    naive agent confidently gives the *same* answer as on clean data --
    exactly the overconfidence failure mode this harness exists to catch.
    """
    telemetry = build_spiking_telemetry()
    spec = CorruptionSpec(seed=0, delay=Severity.SEVERE)
    corrupted = apply_corruptions(telemetry, spec)

    verdict = adapter.run(corrupted)

    assert verdict.insufficient_signal is False
    assert verdict.root_cause == "downstream payment API timeout"
