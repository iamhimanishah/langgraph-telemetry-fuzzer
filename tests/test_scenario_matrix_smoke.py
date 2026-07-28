"""Runs every scenario against the full corruption matrix to prove the
suite and the matrix actually compose -- not just that each scenario is
individually well-formed, and not just that the matrix has the right shape.
"""

from langgraph_telemetry_fuzzer import (
    AgentVerdict,
    CorruptionSpec,
    apply_corruptions,
    grade,
    is_signal_sufficient,
)
from scenarios import ALL_SCENARIOS, single_axis_matrix


def test_every_scenario_survives_every_corruption_spec_without_error():
    specs = single_axis_matrix()

    for scenario in ALL_SCENARIOS:
        for spec in specs:
            corrupted = apply_corruptions(scenario.telemetry, spec)
            assert corrupted is not None


def test_every_scenario_and_spec_combination_is_gradeable():
    """grade() should never raise, no matter what the agent claimed --
    even a maximally unhelpful verdict has a defined outcome.
    """
    specs = single_axis_matrix()
    placeholder = AgentVerdict()

    for scenario in ALL_SCENARIOS:
        for spec in specs:
            result = grade(scenario, spec, placeholder)
            assert result.outcome is not None


def test_clean_spec_never_requires_abstention():
    """The clean baseline in the matrix should always count as sufficient
    signal, regardless of a scenario's declared tolerance.
    """
    clean = CorruptionSpec()
    for scenario in ALL_SCENARIOS:
        assert is_signal_sufficient(scenario, clean) is True
