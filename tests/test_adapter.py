import pytest
from helpers import build_telemetry

from langgraph_telemetry_fuzzer import AgentVerdict
from langgraph_telemetry_fuzzer.adapter import LangGraphAdapter


class FakeGraph:
    """Stands in for a compiled LangGraph graph: same `.invoke` shape,
    no langgraph dependency needed to test the adapter itself.
    """

    def __init__(self, response):
        self.response = response
        self.last_state = None

    def invoke(self, state):
        self.last_state = state
        return self.response


def test_run_passes_telemetry_under_the_configured_key():
    telemetry = build_telemetry()
    graph = FakeGraph({"verdict": {"insufficient_signal": True}})

    LangGraphAdapter(graph).run(telemetry)

    assert graph.last_state == {"telemetry": telemetry}


def test_run_accepts_a_dict_verdict():
    graph = FakeGraph({"verdict": {"root_cause": "disk full", "confidence": 0.9}})

    verdict = LangGraphAdapter(graph).run(build_telemetry())

    assert verdict == AgentVerdict(root_cause="disk full", confidence=0.9)


def test_run_accepts_an_agent_verdict_instance_directly():
    expected = AgentVerdict(insufficient_signal=True)
    graph = FakeGraph({"verdict": expected})

    verdict = LangGraphAdapter(graph).run(build_telemetry())

    assert verdict is expected


def test_run_respects_custom_keys():
    graph = FakeGraph({"result": {"insufficient_signal": True}})
    adapter = LangGraphAdapter(graph, telemetry_key="signal", verdict_key="result")

    telemetry = build_telemetry()
    adapter.run(telemetry)

    assert graph.last_state == {"signal": telemetry}


def test_run_raises_on_unrecognized_verdict_shape():
    graph = FakeGraph({"verdict": "just say no"})

    with pytest.raises(TypeError, match="Expected an AgentVerdict or dict"):
        LangGraphAdapter(graph).run(build_telemetry())


def test_run_raises_when_verdict_key_missing():
    graph = FakeGraph({"something_else": {}})

    with pytest.raises(TypeError):
        LangGraphAdapter(graph).run(build_telemetry())
