"""Adapter that lets any LangGraph agent be run through this harness.

The harness never imports `langgraph` itself -- it only needs an object with
an `.invoke(state: dict) -> dict` method, which is the shape of every
compiled LangGraph graph. That keeps `langgraph` an optional dependency:
you only need it installed to run one of the agents in `examples/`.

To plug your own graph in, its state must accept telemetry under
`telemetry_key` (default `"telemetry"`) and return a verdict -- either an
`AgentVerdict` or a plain dict with its fields -- under `verdict_key`
(default `"verdict"`).
"""

from __future__ import annotations

from typing import Any, Protocol

from langgraph_telemetry_fuzzer.models import AgentVerdict, Telemetry


class InvocableGraph(Protocol):
    """Structural type for a compiled LangGraph graph, or anything that
    quacks like one."""

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]: ...


class LangGraphAdapter:
    """Wraps a compiled graph so the harness can run it uniformly."""

    def __init__(
        self,
        graph: InvocableGraph,
        telemetry_key: str = "telemetry",
        verdict_key: str = "verdict",
    ) -> None:
        self.graph = graph
        self.telemetry_key = telemetry_key
        self.verdict_key = verdict_key

    def run(self, telemetry: Telemetry) -> AgentVerdict:
        result = self.graph.invoke({self.telemetry_key: telemetry})
        return self._coerce(result.get(self.verdict_key))

    def _coerce(self, raw: Any) -> AgentVerdict:
        if isinstance(raw, AgentVerdict):
            return raw
        if isinstance(raw, dict):
            return AgentVerdict(**raw)
        raise TypeError(
            f"Expected an AgentVerdict or dict under '{self.verdict_key}', "
            f"got {type(raw).__name__} instead"
        )
