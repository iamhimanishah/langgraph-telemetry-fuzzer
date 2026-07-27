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
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    unit: Optional[str] = None


class LogEntry(BaseModel):
    timestamp: datetime
    level: str
    message: str
    source: Optional[str] = None


class Telemetry(BaseModel):
    """A bundle of observability signal for one incident window.

    This is the thing injectors corrupt: they drop metrics, skew timestamps,
    rename fields, or truncate the window before it reaches the agent.
    """

    schema_version: str = "1.0"
    metrics: List[MetricPoint] = Field(default_factory=list)
    logs: List[LogEntry] = Field(default_factory=list)
    traces: List[Dict[str, Any]] = Field(default_factory=list)

    def clone(self) -> Telemetry:
        """Deep copy so injectors never mutate the scenario's golden fixture."""
        return self.model_copy(deep=True)


class Scenario(BaseModel):
    """A golden test case: clean telemetry plus the ground-truth answer.

    Injectors are applied to `telemetry` at run time; `true_root_cause` and
    `id` stay fixed so the grader always knows what "correct" means.
    """

    id: str
    description: str
    telemetry: Telemetry
    true_root_cause: str
    system: Optional[str] = None


class AgentVerdict(BaseModel):
    """The required shape of an agent's answer.

    Agents under test must resolve to this shape (directly, or via an
    adapter that parses their native output into it) so the grader can
    check pass/fail without interpreting free text.
    """

    root_cause: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    insufficient_signal: bool = False
    evidence_refs: List[str] = Field(default_factory=list)
    raw_output: Optional[Any] = None
