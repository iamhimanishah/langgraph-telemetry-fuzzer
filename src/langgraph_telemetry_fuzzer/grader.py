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


class MatchMethod(str, Enum):
    """How an agent's root_cause was matched against the scenario's.

    Recorded so a report reader can discount alias-matched passes: an EXACT
    match is unambiguous, while an ALIAS match is only as trustworthy as the
    scenario author's alias list.
    """

    EXACT = "exact"  # matched true_root_cause itself
    ALIAS = "alias"  # matched one of the scenario's other accepted phrasings


class Grade(BaseModel):
    """The result of grading a single (scenario, spec, verdict) run."""

    outcome: Outcome
    passed: bool
    reason: str
    match_method: MatchMethod | None = None


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


def _match_root_cause(
    verdict: AgentVerdict, scenario: Scenario
) -> MatchMethod | None:
    """Returns how the claimed root cause matched, or None if it didn't."""
    if verdict.root_cause is None:
        return None
    claimed = verdict.root_cause.strip().lower()
    if claimed == scenario.true_root_cause.strip().lower():
        return MatchMethod.EXACT
    for alias in scenario.accepted_root_causes:
        if claimed == alias.strip().lower():
            return MatchMethod.ALIAS
    return None


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
        match_method = _match_root_cause(verdict, scenario)
        if match_method is not None:
            if match_method is MatchMethod.EXACT:
                reason = f"Correctly identified '{scenario.true_root_cause}'."
            else:
                reason = (
                    f"Matched an accepted phrasing of "
                    f"'{scenario.true_root_cause}' ({verdict.root_cause!r})."
                )
            return Grade(
                outcome=Outcome.CORRECT_ANSWER,
                passed=True,
                reason=reason,
                match_method=match_method,
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
