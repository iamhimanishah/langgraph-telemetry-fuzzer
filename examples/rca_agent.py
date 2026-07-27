"""A toy incident root-cause-analysis agent, built as a LangGraph graph.

Intentionally simple, rule-based, and offline (no LLM calls, no API keys)
so it can run in CI and be dogfooded against the injectors directly.

It's also intentionally naive in one specific way: `decide` checks *how
many* matching metric points survived, but never checks *how stale* they
are. That blind spot is expected to surface under the `delay` injector --
the agent will confidently answer using data whose timestamps have been
shifted hours away from reality, because nothing here compares timestamps
against a reference point in time.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_telemetry_fuzzer.models import AgentVerdict, Telemetry

METRIC_NAME = "error_rate"
MIN_POINTS = 5
SPIKE_THRESHOLD = 0.5


class RCAState(TypedDict, total=False):
    telemetry: Telemetry
    analysis: dict
    verdict: dict


def analyze(state: RCAState) -> dict:
    """Pulls out every point named METRIC_NAME, however many survived."""
    telemetry = state["telemetry"]
    values = [m.value for m in telemetry.metrics if m.name == METRIC_NAME]
    return {"analysis": {"count": len(values), "max_value": max(values, default=0.0)}}


def decide(state: RCAState) -> dict:
    """Commits to a root cause once enough matching points exist -- without
    checking whether those points are fresh or badly delayed.
    """
    analysis = state["analysis"]
    count = analysis["count"]
    max_value = analysis["max_value"]

    if count < MIN_POINTS:
        verdict = AgentVerdict(insufficient_signal=True, confidence=0.0)
    elif max_value > SPIKE_THRESHOLD:
        evidence = f"{METRIC_NAME} peaked at {max_value:.2f} across {count} points"
        verdict = AgentVerdict(
            root_cause="downstream dependency timeout",
            confidence=min(max_value, 1.0),
            evidence_refs=[evidence],
        )
    else:
        evidence = f"{METRIC_NAME} stayed below {SPIKE_THRESHOLD} across {count} points"
        verdict = AgentVerdict(
            root_cause="no anomaly detected",
            confidence=0.6,
            evidence_refs=[evidence],
        )
    return {"verdict": verdict}


def build_graph():
    """Returns a compiled two-node graph: analyze -> decide."""
    graph = StateGraph(RCAState)
    graph.add_node("analyze", analyze)
    graph.add_node("decide", decide)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "decide")
    graph.add_edge("decide", END)
    return graph.compile()
