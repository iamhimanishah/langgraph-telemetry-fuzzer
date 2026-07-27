"""Rule-based grader: turns (scenario, corruption spec, agent verdict) into
a pass/fail outcome, based on whether the agent's confidence matched what
the corrupted telemetry could actually support.

This is deliberately rule-based, not an LLM judge: AgentVerdict is a fixed
shape (see models.py), so "did the agent hallucinate" reduces to comparing
a few fields against a scenario's declared tolerance. An LLM-judge fallback
for free-text agent output is a possible future extension, not needed here.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from langgraph_telemetry_fuzzer.models import (
    AgentVerdict,
    CorruptionSpec,
    Scenario,
    Severity,
)

_SEVERITY_RANK = {
    Severity.NONE: 0,
    Severity.MILD: 1,
    Severity.MODERATE: 2,
    Severity.SEVERE: 3,
}

_CORRUPTION_AXES = ("missing", "delay", "drift", "truncate")


class Outcome(str, Enum):
    """Why a graded run passed or failed."""

    CORRECT_ANSWER = "correct_answer"  # pass: sufficient signal, answered correctly
    CORRECT_ABSTENTION = "correct_abstention"  # pass: insufficient signal, abstained
    HALLUCINATION = "hallucination"  # fail: insufficient signal, answered confidently
    WRONG_ANSWER = "wrong_answer"  # fail: sufficient signal, answered incorrectly
    OVER_CAUTION = "over_caution"  # fail: sufficient signal, abstained anyway


PASSING_OUTCOMES = frozenset({Outcome.CORRECT_ANSWER, Outcome.CORRECT_ABSTENTION})


class Grade(BaseModel):
    """The result of grading a single (scenario, spec, verdict) run."""

    outcome: Outcome
    passed: bool
    reason: str


def is_signal_sufficient(scenario: Scenario, spec: CorruptionSpec) -> bool:
    """True if `spec` doesn't push any corruption axis past what `scenario`
    declares its ground truth can survive.
    """
    for axis in _CORRUPTION_AXES:
        applied = _SEVERITY_RANK[getattr(spec, axis)]
        tolerated = _SEVERITY_RANK[getattr(scenario.tolerant_up_to, axis)]
        if applied > tolerated:
            return False
    return True


def _matches_root_cause(verdict: AgentVerdict, scenario: Scenario) -> bool:
    if verdict.root_cause is None:
        return False
    claimed = verdict.root_cause.strip().lower()
    expected = scenario.true_root_cause.strip().lower()
    return claimed == expected


def grade(scenario: Scenario, spec: CorruptionSpec, verdict: AgentVerdict) -> Grade:
    """Grades one agent run against one (scenario, corruption spec) pair."""
    if is_signal_sufficient(scenario, spec):
        if verdict.insufficient_signal:
            return Grade(
                outcome=Outcome.OVER_CAUTION,
                passed=False,
                reason=(
                    f"Telemetry still supported '{scenario.true_root_cause}', "
                    "but the agent abstained anyway."
                ),
            )
        if _matches_root_cause(verdict, scenario):
            return Grade(
                outcome=Outcome.CORRECT_ANSWER,
                passed=True,
                reason=f"Correctly identified '{scenario.true_root_cause}'.",
            )
        return Grade(
            outcome=Outcome.WRONG_ANSWER,
            passed=False,
            reason=(
                f"Expected '{scenario.true_root_cause}', got "
                f"{verdict.root_cause!r} despite sufficient signal."
            ),
        )

    if verdict.insufficient_signal:
        return Grade(
            outcome=Outcome.CORRECT_ABSTENTION,
            passed=True,
            reason="Correctly recognized the telemetry couldn't support a conclusion.",
        )
    return Grade(
        outcome=Outcome.HALLUCINATION,
        passed=False,
        reason=(
            "Telemetry was corrupted past this scenario's tolerance, but the "
            f"agent confidently answered {verdict.root_cause!r} anyway."
        ),
    )
