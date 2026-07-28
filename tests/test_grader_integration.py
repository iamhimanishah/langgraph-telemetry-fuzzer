"""Runs the full pipeline -- Scenario -> corrupt -> real LangGraph agent ->
grade -- to prove the pieces from all four milestones actually fit together,
not just that each one passes its own unit tests in isolation.
"""

import pytest
from helpers import build_spiking_telemetry

from langgraph_telemetry_fuzzer import (
    CorruptionSpec,
    Outcome,
    Scenario,
    Severity,
    ToleranceSpec,
    apply_corruptions,
    grade,
)
from langgraph_telemetry_fuzzer.adapter import LangGraphAdapter

langgraph = pytest.importorskip("langgraph")

from examples.rca_agent import build_graph  # noqa: E402

TRUE_ROOT_CAUSE = "downstream payment API timeout"


@pytest.fixture
def scenario():
    return Scenario(
        id="checkout-error-spike",
        description="error_rate spikes partway through the incident window",
        telemetry=build_spiking_telemetry(),
        true_root_cause=TRUE_ROOT_CAUSE,
        # rca_agent's own MIN_POINTS check tracks missing-data severity
        # reasonably well, so this scenario tolerates up to moderate drops.
        # It declares zero tolerance for delay, since skewed timestamps
        # break the causal ordering RCA depends on -- see the note below.
        tolerant_up_to=ToleranceSpec(missing=Severity.MODERATE),
    )


@pytest.fixture
def adapter():
    return LangGraphAdapter(build_graph())


def test_clean_telemetry_is_graded_a_correct_answer(scenario, adapter):
    verdict = adapter.run(scenario.telemetry)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.CORRECT_ANSWER


def test_moderate_missing_within_tolerance_still_grades_correct(scenario, adapter):
    spec = CorruptionSpec(seed=0, missing=Severity.MODERATE)
    corrupted = apply_corruptions(scenario.telemetry, spec)

    verdict = adapter.run(corrupted)
    result = grade(scenario, spec, verdict)

    assert result.outcome == Outcome.CORRECT_ANSWER


def test_severe_missing_beyond_tolerance_grades_correct_abstention(scenario, adapter):
    # Small telemetry so a 75% drop reliably pushes survivors below the
    # agent's own MIN_POINTS threshold (see test_rca_agent.py for the math).
    scenario.telemetry = build_spiking_telemetry(n_points=8)
    spec = CorruptionSpec(seed=0, missing=Severity.SEVERE)
    corrupted = apply_corruptions(scenario.telemetry, spec)

    verdict = adapter.run(corrupted)
    result = grade(scenario, spec, verdict)

    assert result.outcome == Outcome.CORRECT_ABSTENTION


def test_severe_delay_beyond_tolerance_grades_a_hallucination(scenario, adapter):
    """This is the demo the whole project is about: the naive rca_agent
    doesn't check timestamp sanity, so severe delay corruption -- which
    this scenario declares as breaking sufficiency entirely -- still gets
    a confident answer out of it. The grader correctly flags that as a
    hallucination instead of letting it slide.
    """
    spec = CorruptionSpec(seed=0, delay=Severity.SEVERE)
    corrupted = apply_corruptions(scenario.telemetry, spec)

    verdict = adapter.run(corrupted)
    result = grade(scenario, spec, verdict)

    assert result.outcome == Outcome.HALLUCINATION
    assert result.passed is False
