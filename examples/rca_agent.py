"""A toy incident root-cause-analysis agent, built as a LangGraph graph.

Intentionally simple, rule-based, and offline (no LLM calls, no API keys)
so it can run in CI and be dogfooded against the injectors directly. The
design mirrors a runbook-driven RCA tool: a table of known metric
signatures, each mapped to the cause it usually indicates.

Two limitations are deliberate, and both show up when you run the suite:

1. **No timestamp sanity check.** `decide` checks *how many* matching
   points survived, but never *how stale* they are, so severe `delay`
   corruption produces the same confident answer as clean data. This is
   the overconfidence failure mode the harness exists to catch.
2. **No log correlation.** It reads metrics only. `error_rate` spikes in
   both the checkout-error-spike and deployment-regression scenarios, and
   telling those apart requires noticing the deploy marker in the logs --
   so it necessarily gets one of them wrong. That's a genuine capability
   gap, visible as an accuracy failure rather than a grounding one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_telemetry_fuzzer.models import AgentVerdict, Telemetry

MIN_POINTS = 5


@dataclass(frozen=True)
class MetricRule:
    """A known metric signature and the cause it's taken to indicate."""

    metric: str
    threshold: float
    direction: Literal["above", "below"]
    cause: str

    def is_anomalous(self, value: float) -> bool:
        if self.direction == "above":
            return value > self.threshold
        return value < self.threshold

    def worst(self, values: list[float]) -> float:
        return max(values) if self.direction == "above" else min(values)


# Order matters: the first matching rule wins. `db_latency_ms` is listed
# before `error_rate` so the cascading-failure scenario resolves to the
# database cause rather than the API-layer symptom it triggers downstream.
RULES: tuple[MetricRule, ...] = (
    MetricRule(
        metric="db_latency_ms",
        threshold=500.0,
        direction="above",
        cause="database connection pool exhaustion cascading to API layer",
    ),
    MetricRule(
        metric="disk_free_percent",
        threshold=5.0,
        direction="below",
        cause="log directory filling the disk due to disabled log rotation",
    ),
    MetricRule(
        metric="upstream_success_rate",
        threshold=0.5,
        direction="below",
        cause="intermittent outage at a third-party upstream API",
    ),
    MetricRule(
        metric="p99_latency_ms",
        threshold=1000.0,
        direction="above",
        cause="memory leak causing GC pressure in the application pool",
    ),
    MetricRule(
        metric="error_rate",
        threshold=0.5,
        direction="above",
        cause="downstream payment API timeout",
    ),
)


class RCAState(TypedDict, total=False):
    telemetry: Telemetry
    analysis: dict
    verdict: dict


def analyze(state: RCAState) -> dict:
    """Finds the first known metric present in the telemetry and summarizes
    it. Note what this does *not* look at: timestamps, or logs.
    """
    telemetry = state["telemetry"]
    for rule in RULES:
        values = [m.value for m in telemetry.metrics if m.name == rule.metric]
        if values:
            return {
                "analysis": {
                    "metric": rule.metric,
                    "count": len(values),
                    "worst_value": rule.worst(values),
                    "cause": rule.cause,
                    "anomalous": rule.is_anomalous(rule.worst(values)),
                }
            }
    return {"analysis": {"metric": None, "count": 0}}


def decide(state: RCAState) -> dict:
    """Commits to a root cause once enough matching points exist -- without
    checking whether those points are fresh or badly delayed.
    """
    analysis = state["analysis"]
    count = analysis["count"]

    if count < MIN_POINTS:
        return {"verdict": AgentVerdict(insufficient_signal=True, confidence=0.0)}

    metric = analysis["metric"]
    worst = analysis["worst_value"]

    if analysis["anomalous"]:
        evidence = f"{metric} reached {worst:.2f} across {count} points"
        return {
            "verdict": AgentVerdict(
                root_cause=analysis["cause"],
                confidence=0.9,
                evidence_refs=[evidence],
            )
        }

    evidence = f"{metric} stayed within normal range across {count} points"
    return {
        "verdict": AgentVerdict(
            root_cause="no anomaly detected",
            confidence=0.6,
            evidence_refs=[evidence],
        )
    }


def build_graph():
    """Returns a compiled two-node graph: analyze -> decide."""
    graph = StateGraph(RCAState)
    graph.add_node("analyze", analyze)
    graph.add_node("decide", decide)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "decide")
    graph.add_edge("decide", END)
    return graph.compile()
