"""Runs a set of scenarios against an agent, across a set of corruption
specs, and aggregates the resulting grades into a Report.
"""

from __future__ import annotations

from pydantic import BaseModel

from langgraph_telemetry_fuzzer.adapter import LangGraphAdapter
from langgraph_telemetry_fuzzer.grader import Grade, MatchMethod, Outcome, grade
from langgraph_telemetry_fuzzer.injectors.compose import apply_corruptions
from langgraph_telemetry_fuzzer.models import (
    AgentVerdict,
    CorruptionSpec,
    Scenario,
    Severity,
)

_AXES = ("missing", "delay", "drift", "truncate")


class RunResult(BaseModel):
    """The outcome of running one agent against one (scenario, spec) pair."""

    scenario_id: str
    spec: CorruptionSpec
    verdict: AgentVerdict
    grade: Grade


def _dominant_axis_severity(spec: CorruptionSpec) -> tuple[str, str]:
    """single_axis_matrix() only ever corrupts one axis at a time (or none
    at all) -- this identifies which, for grouping results in a report.
    """
    for axis in _AXES:
        severity = getattr(spec, axis)
        if severity != Severity.NONE:
            return axis, severity.value
    return "clean", Severity.NONE.value


class Report(BaseModel):
    """Aggregates a batch of RunResults into pass/fail rates.

    Two distinct questions are tracked separately, because conflating them
    hides the one this harness exists to measure:

    - `grounding_score` -- did the agent's commit-vs-abstain decision match
      what the telemetry could actually support? This is the headline metric.
      Naming the wrong cause while correctly choosing to commit still counts
      as grounded: being wrong is an accuracy problem, not a calibration one.
    - `accuracy_rate` -- when it did commit on sufficient signal, was the
      named cause right?

    `pass_rate` remains the strict both-must-hold number.
    """

    results: list[RunResult]

    @property
    def total(self) -> int:
        return len(self.results)

    def count(self, outcome: Outcome) -> int:
        return sum(1 for r in self.results if r.grade.outcome == outcome)

    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.grade.passed) / self.total

    def grounding_score(self) -> float:
        """The fraction of runs where the agent's decision to commit or
        abstain matched what the signal supported -- i.e. everything except
        hallucinations and over-caution.
        """
        if not self.results:
            return 0.0
        ungrounded = self.count(Outcome.HALLUCINATION) + self.count(
            Outcome.OVER_CAUTION
        )
        return (self.total - ungrounded) / self.total

    def accuracy_rate(self) -> float:
        """Of runs where the agent committed to an answer on sufficient
        signal, the fraction that named the right cause.
        """
        committed = self.count(Outcome.CORRECT_ANSWER) + self.count(
            Outcome.WRONG_ANSWER
        )
        if committed == 0:
            return 0.0
        return self.count(Outcome.CORRECT_ANSWER) / committed

    def alias_matched_count(self) -> int:
        """How many correct answers matched via an alias rather than the
        scenario's canonical `true_root_cause`.
        """
        return sum(
            1 for r in self.results if r.grade.match_method is MatchMethod.ALIAS
        )

    def hallucination_rate(self) -> float:
        """Of runs where the signal was insufficient, the fraction where
        the agent hallucinated instead of correctly abstaining.
        """
        insufficient = self.count(Outcome.HALLUCINATION) + self.count(
            Outcome.CORRECT_ABSTENTION
        )
        if insufficient == 0:
            return 0.0
        return self.count(Outcome.HALLUCINATION) / insufficient

    def over_caution_rate(self) -> float:
        """Of runs where the signal was sufficient, the fraction where the
        agent abstained anyway instead of committing to an answer.
        """
        sufficient = (
            self.count(Outcome.CORRECT_ANSWER)
            + self.count(Outcome.WRONG_ANSWER)
            + self.count(Outcome.OVER_CAUTION)
        )
        if sufficient == 0:
            return 0.0
        return self.count(Outcome.OVER_CAUTION) / sufficient

    def by_axis_severity(self) -> dict[tuple[str, str], tuple[int, int]]:
        """(axis, severity) -> (passed, total), for a per-corruption-type
        breakdown of pass rate.
        """
        buckets: dict[tuple[str, str], list[int]] = {}
        for result in self.results:
            key = _dominant_axis_severity(result.spec)
            bucket = buckets.setdefault(key, [0, 0])
            bucket[1] += 1
            if result.grade.passed:
                bucket[0] += 1
        return {key: (passed, total) for key, (passed, total) in buckets.items()}

    def to_json_dict(self) -> dict:
        """A plain-dict form (summary + raw results) suitable for
        `json.dumps` -- computed metrics are included so a saved report
        doesn't need to be re-parsed through this class to read them.
        """
        return {
            "summary": {
                "total": self.total,
                "grounding_score": self.grounding_score(),
                "accuracy_rate": self.accuracy_rate(),
                "pass_rate": self.pass_rate(),
                "hallucination_rate": self.hallucination_rate(),
                "over_caution_rate": self.over_caution_rate(),
                "alias_matched": self.alias_matched_count(),
                "outcome_counts": {o.value: self.count(o) for o in Outcome},
            },
            "results": [r.model_dump(mode="json") for r in self.results],
        }


def run_suite(
    scenarios: list[Scenario], specs: list[CorruptionSpec], adapter: LangGraphAdapter
) -> Report:
    """Runs every (scenario, spec) pair through `adapter` and grades it."""
    results = []
    for scenario in scenarios:
        for spec in specs:
            corrupted = apply_corruptions(scenario.telemetry, spec)
            verdict = adapter.run(corrupted)
            results.append(
                RunResult(
                    scenario_id=scenario.id,
                    spec=spec,
                    verdict=verdict,
                    grade=grade(scenario, spec, verdict),
                )
            )
    return Report(results=results)
