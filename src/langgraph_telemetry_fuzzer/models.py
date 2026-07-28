"""Core data model: the telemetry an agent sees, the golden scenario it's
tested against, and the structured verdict it must return.

The whole harness hinges on AgentVerdict being a fixed shape. If agents could
answer in free text, grading "did it hallucinate a root cause" would require
another LLM judge and a pile of ambiguity. Forcing a structured verdict makes
grading mechanical.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Severity(str, Enum):
    """How badly a scenario's telemetry has been corrupted."""

    NONE = "none"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class MetricPoint(BaseModel):
    timestamp: datetime
    name: str
    value: float
    unit: str | None = None


class LogEntry(BaseModel):
    timestamp: datetime
    level: str
    message: str
    source: str | None = None


class Telemetry(BaseModel):
    """A bundle of observability signal for one incident window.

    This is the thing injectors corrupt: they drop metrics, skew timestamps,
    rename fields, or truncate the window before it reaches the agent.
    """

    schema_version: str = "1.0"
    metrics: list[MetricPoint] = Field(default_factory=list)
    logs: list[LogEntry] = Field(default_factory=list)
    traces: list[dict[str, Any]] = Field(default_factory=list)

    def clone(self) -> Telemetry:
        """Deep copy so injectors never mutate the scenario's golden fixture."""
        return self.model_copy(deep=True)


class ToleranceSpec(BaseModel):
    """How much corruption, per axis, a scenario's ground truth can survive.

    Defaults to NONE on every axis -- fail-closed. A scenario author has to
    explicitly declare "the answer is still recoverable up to this severity"
    for the grader to expect a committed answer under any corruption at all.
    Silently assuming corrupted telemetry is still fully answerable would
    undermine the whole point of this harness.
    """

    missing: Severity = Severity.NONE
    delay: Severity = Severity.NONE
    drift: Severity = Severity.NONE
    truncate: Severity = Severity.NONE


class Scenario(BaseModel):
    """A golden test case: clean telemetry plus the ground-truth answer.

    Injectors are applied to `telemetry` at run time; `true_root_cause` and
    `id` stay fixed so the grader always knows what "correct" means.
    `tolerant_up_to` tells the grader how much corruption still leaves
    enough signal to expect a committed (not abstained) answer.

    `accepted_root_causes` lists every phrasing that counts as naming the
    right cause. `true_root_cause` is always included automatically -- the
    extras exist so a differently-worded but correct answer isn't graded
    WRONG_ANSWER purely over phrasing. Aliases should be genuine restatements
    of the same cause, not near-misses: accepting "database is slow" for
    "connection pool exhaustion" would quietly inflate the agent's score.
    """

    id: str
    description: str
    telemetry: Telemetry
    true_root_cause: str
    system: str | None = None
    tolerant_up_to: ToleranceSpec = Field(default_factory=ToleranceSpec)
    accepted_root_causes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _always_accept_the_true_root_cause(self) -> Scenario:
        canonical = self.true_root_cause.strip().lower()
        already_listed = any(
            alias.strip().lower() == canonical for alias in self.accepted_root_causes
        )
        if not already_listed:
            self.accepted_root_causes = [
                self.true_root_cause,
                *self.accepted_root_causes,
            ]
        return self


class CorruptionSpec(BaseModel):
    """Which injectors to run against a scenario's telemetry, and how hard.

    `seed` makes a run reproducible: the same spec against the same scenario
    always produces byte-identical corrupted telemetry.
    """

    seed: int = 0
    missing: Severity = Severity.NONE
    delay: Severity = Severity.NONE
    drift: Severity = Severity.NONE
    truncate: Severity = Severity.NONE


class AgentVerdict(BaseModel):
    """The required shape of an agent's answer.

    Agents under test must resolve to this shape (directly, or via an
    adapter that parses their native output into it) so the grader can
    check pass/fail without interpreting free text.
    """

    root_cause: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    insufficient_signal: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    raw_output: Any | None = None
