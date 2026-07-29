"""MCP server serving the bundled scenario suite over two tools.

`query_telemetry` attaches trust metadata computed by the guardrail;
`query_telemetry_raw` returns the same telemetry with no metadata at all.
The pair exists so the same agent can be pointed at either one and the
difference attributed to the guardrail rather than to the model.

No new fixtures are defined here. Scenarios come from ALL_SCENARIOS and
corruption goes through apply_corruptions exactly as the rest of the
harness uses them.

Note which side of the boundary knows what. This module has the
CorruptionSpec -- it has to, since it applies it -- but it never passes it
to `compute_trust_metadata`, and it never puts ground truth
(`true_root_cause`, `tolerant_up_to`) into a tool response. The guardrail
and the agent both see telemetry and a clock, nothing more.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langgraph_telemetry_fuzzer import (
    CorruptionSpec,
    Scenario,
    Severity,
    Telemetry,
    apply_corruptions,
)
from langgraph_telemetry_fuzzer.guardrail import compute_trust_metadata
from langgraph_telemetry_fuzzer.scenarios import ALL_SCENARIOS

# The bundled fixtures are all sampled once per second.
EXPECTED_INTERVAL_SECONDS = 1.0

_SCENARIOS_BY_ID: dict[str, Scenario] = {s.id: s for s in ALL_SCENARIOS}


def _lookup(scenario_id: str) -> Scenario:
    try:
        return _SCENARIOS_BY_ID[scenario_id]
    except KeyError:
        known = ", ".join(sorted(_SCENARIOS_BY_ID))
        raise ValueError(
            f"Unknown scenario {scenario_id!r}. Available: {known}"
        ) from None


def _build_spec(
    seed: int,
    missing: str,
    delay: str,
    drift: str,
    truncate: str,
) -> CorruptionSpec:
    return CorruptionSpec(
        seed=seed,
        missing=Severity(missing),
        delay=Severity(delay),
        drift=Severity(drift),
        truncate=Severity(truncate),
    )


def query_window_end(scenario: Scenario) -> datetime:
    """The clock reading a caller would have when querying this incident.

    Taken from the scenario's own (uncorrupted) window end, which is the
    faithful stand-in for "now" -- in production you know what time it is
    independently of what the query returns. It carries no information
    about which corruption was applied.
    """
    stamps = [m.timestamp for m in scenario.telemetry.metrics]
    stamps += [entry.timestamp for entry in scenario.telemetry.logs]
    return max(stamps)


def _serialize(telemetry: Telemetry) -> dict[str, Any]:
    return telemetry.model_dump(mode="json")


def query_telemetry(
    scenario_id: str,
    seed: int = 0,
    missing: str = "none",
    delay: str = "none",
    drift: str = "none",
    truncate: str = "none",
) -> dict[str, Any]:
    """Fetch an incident's telemetry along with guardrail trust metadata.

    Returns `telemetry` plus a `trust_metadata` block carrying
    completeness, monotonic, staleness_seconds, confidence, and reason.
    """
    scenario = _lookup(scenario_id)
    spec = _build_spec(seed, missing, delay, drift, truncate)
    corrupted = apply_corruptions(scenario.telemetry, spec)
    trust = compute_trust_metadata(
        corrupted,
        query_time=query_window_end(scenario),
        expected_interval_seconds=EXPECTED_INTERVAL_SECONDS,
    )
    return {
        "scenario_id": scenario.id,
        "description": scenario.description,
        "telemetry": _serialize(corrupted),
        "trust_metadata": trust.to_dict(),
    }


def query_telemetry_raw(
    scenario_id: str,
    seed: int = 0,
    missing: str = "none",
    delay: str = "none",
    drift: str = "none",
    truncate: str = "none",
) -> dict[str, Any]:
    """Fetch an incident's telemetry with no trust metadata attached.

    The unguarded baseline: identical data, no signal about whether it can
    be trusted.
    """
    scenario = _lookup(scenario_id)
    spec = _build_spec(seed, missing, delay, drift, truncate)
    corrupted = apply_corruptions(scenario.telemetry, spec)
    return {
        "scenario_id": scenario.id,
        "description": scenario.description,
        "telemetry": _serialize(corrupted),
    }


def build_server():
    """Registers both tools on an MCPServer and returns it."""
    from mcp.server import MCPServer

    server = MCPServer(
        name="telemetry-guardrail",
        instructions=(
            "Serves incident telemetry from the langgraph-telemetry-fuzzer "
            "scenario suite. Use query_telemetry to receive trust metadata "
            "alongside the data, or query_telemetry_raw for the data alone."
        ),
    )
    server.tool(name="query_telemetry")(query_telemetry)
    server.tool(name="query_telemetry_raw")(query_telemetry_raw)
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
