"""A real LLM-driven RCA agent, as a LangGraph graph with tool calling.

Unlike `rca_agent.py` -- a rule table with hardcoded thresholds -- this one
hands the telemetry to a model and lets it reason. Two tools are exposed:
`get_telemetry` to fetch the incident window, and `submit_verdict` to
return a structured answer.

The graph is built against either the guarded or the raw telemetry tool.
That single switch is the whole experiment: identical model, identical
prompt, identical data, differing only in whether a `trust_metadata` block
comes back with the telemetry.

Works with LangGraphAdapter unmodified -- state goes in under "telemetry"
and the verdict comes out under "verdict".

Requires: pip install -e ".[llm,langgraph]" and an ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_telemetry_fuzzer.guardrail import compute_trust_metadata
from langgraph_telemetry_fuzzer.models import AgentVerdict, Telemetry

DEFAULT_MODEL = "claude-opus-5"
EXPECTED_INTERVAL_SECONDS = 1.0
EXPECTED_SCHEMA_VERSION = "1.0"
MAX_TOOL_ROUNDS = 6

# Shared reasoning instructions. Identical across both variants so the only
# difference between them is the guardrail itself.
_DIAGNOSIS_RULES = """\
- Identify the metric that moved and when, and name the underlying cause
  rather than the symptom. "Database connection pool exhaustion" is a
  cause; "the API returned errors" is a symptom.
- If several metrics moved, the one that moved FIRST is the likely cause
  and the later ones are downstream effects.
- Set `insufficient_signal: true` if the data genuinely cannot support a
  conclusion.
- Otherwise give `root_cause` as a short noun phrase and a `confidence`
  between 0 and 1.\
"""

_PREAMBLE = """\
You are an incident root-cause analyst. You have two tools: `get_telemetry`
to fetch the incident window, and `submit_verdict` to answer. Always fetch
telemetry before answering, and always answer via `submit_verdict`.\
"""

# Unguarded baseline. Deliberately says nothing about trust metadata --
# an agent with no guardrail should have no concept of one, rather than
# being told about a signal that never arrives. Mentioning it here caused
# the baseline to abstain purely because metadata was absent, which would
# have made the comparison measure nothing.
RAW_SYSTEM_PROMPT = f"""{_PREAMBLE}

Diagnose the incident from the telemetry:

{_DIAGNOSIS_RULES}"""

# Guarded variant. The abstention rule is stated as a hard precondition
# rather than advice, and placed before the reasoning instructions so it is
# not read as one consideration among several.
GUARDED_SYSTEM_PROMPT = f"""{_PREAMBLE}

ABSOLUTE RULE, checked before anything else:

If the `get_telemetry` response contains a `trust_metadata` object whose
`confidence` field equals "low", you MUST call `submit_verdict` with
`insufficient_signal: true`, `root_cause: null`, and `confidence: 0`. This
is not a judgement call and it does not matter how clear the underlying
data looks -- low-confidence metadata means the data cannot support any
conclusion, including one you feel certain about. State the metadata's
`reason` verbatim in your `evidence` field. Do not diagnose. Do not
speculate about what the cause might have been. Do not caveat and answer
anyway.

If `trust_metadata.confidence` is "high", proceed to diagnose normally:

{_DIAGNOSIS_RULES}"""

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_telemetry",
        "description": "Fetch the telemetry window for the incident under analysis.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "submit_verdict",
        "description": "Submit the final root-cause verdict. Call exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "insufficient_signal": {
                    "type": "boolean",
                    "description": "True if the data cannot support a conclusion.",
                },
                "root_cause": {
                    "type": ["string", "null"],
                    "description": "Short noun phrase, or null when abstaining.",
                },
                "confidence": {"type": "number", "description": "0 to 1."},
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "What supports this, or why you abstained.",
                },
            },
            "required": ["insufficient_signal", "confidence"],
        },
    },
]


class LLMRCAState(TypedDict, total=False):
    telemetry: Telemetry
    verdict: AgentVerdict


def _telemetry_payload(
    telemetry: Telemetry,
    guarded: bool,
    query_time: datetime | None,
    expected_interval_seconds: float = EXPECTED_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Serves the tool call from the telemetry already in state.

    The guarded variant runs the same `compute_trust_metadata` the MCP
    server does -- telemetry plus a clock, never the CorruptionSpec.
    """
    payload: dict[str, Any] = {"telemetry": telemetry.model_dump(mode="json")}
    if not guarded:
        return payload

    stamps = [m.timestamp for m in telemetry.metrics]
    stamps += [entry.timestamp for entry in telemetry.logs]
    effective_query_time = query_time or (max(stamps) if stamps else datetime.now())
    trust = compute_trust_metadata(
        telemetry,
        query_time=effective_query_time,
        expected_interval_seconds=expected_interval_seconds,
        expected_schema_version=EXPECTED_SCHEMA_VERSION,
    )
    payload["trust_metadata"] = trust.to_dict()
    return payload


def _to_verdict(tool_input: dict[str, Any]) -> AgentVerdict:
    raw_confidence = tool_input.get("confidence", 0.0) or 0.0
    return AgentVerdict(
        root_cause=tool_input.get("root_cause"),
        confidence=min(max(float(raw_confidence), 0.0), 1.0),
        insufficient_signal=bool(tool_input.get("insufficient_signal", False)),
        evidence_refs=list(tool_input.get("evidence") or []),
        raw_output=tool_input,
    )


def build_graph(
    guarded: bool = True,
    query_time: datetime | None = None,
    model: str = DEFAULT_MODEL,
    client: Any | None = None,
    expected_interval_seconds: float = EXPECTED_INTERVAL_SECONDS,
):
    """Returns a compiled single-node graph driving a real tool-use loop.

    `guarded=True` attaches trust metadata to the telemetry tool response;
    `guarded=False` is the unguarded baseline.
    """

    def diagnose(state: LLMRCAState) -> dict:
        active_client = client
        if active_client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on extras
                raise ImportError(
                    "examples/llm_rca_agent.py needs the 'anthropic' package. "
                    'Install it with: pip install -e ".[llm]"'
                ) from exc
            active_client = anthropic.Anthropic()

        telemetry = state["telemetry"]
        system_prompt = GUARDED_SYSTEM_PROMPT if guarded else RAW_SYSTEM_PROMPT
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    "Diagnose this incident. Fetch the telemetry first, then "
                    "submit your verdict."
                ),
            }
        ]

        for _ in range(MAX_TOOL_ROUNDS):
            response = active_client.messages.create(
                model=model,
                max_tokens=16000,
                system=system_prompt,
                tools=_TOOLS,
                messages=messages,
            )

            if response.stop_reason == "refusal":
                return {
                    "verdict": AgentVerdict(
                        insufficient_signal=True,
                        confidence=0.0,
                        evidence_refs=["Model declined to answer."],
                    )
                }

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in tool_uses:
                if block.name == "submit_verdict":
                    return {"verdict": _to_verdict(block.input)}
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(
                            _telemetry_payload(
                                telemetry,
                                guarded,
                                query_time,
                                expected_interval_seconds,
                            )
                        ),
                    }
                )
            messages.append({"role": "user", "content": results})

        # Never submitted a verdict -- treat as an abstention rather than
        # inventing an answer on the agent's behalf.
        return {
            "verdict": AgentVerdict(
                insufficient_signal=True,
                confidence=0.0,
                evidence_refs=["Agent did not submit a verdict."],
            )
        }

    graph = StateGraph(LLMRCAState)
    graph.add_node("diagnose", diagnose)
    graph.add_edge(START, "diagnose")
    graph.add_edge("diagnose", END)
    return graph.compile()


def build_guarded_graph():
    """Entry point for `ltf run --agent examples.llm_rca_agent:build_guarded_graph`."""
    return build_graph(guarded=True)


def build_raw_graph():
    """Entry point for `ltf run --agent examples.llm_rca_agent:build_raw_graph`."""
    return build_graph(guarded=False)
