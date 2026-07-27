from datetime import datetime

from langgraph_telemetry_fuzzer import AgentVerdict, MetricPoint, Scenario, Telemetry


def make_telemetry() -> Telemetry:
    return Telemetry(
        metrics=[
            MetricPoint(
                timestamp=datetime(2026, 1, 1, 12, 0, 0), name="error_rate", value=0.02
            ),
            MetricPoint(
                timestamp=datetime(2026, 1, 1, 12, 1, 0), name="error_rate", value=0.87
            ),
        ],
    )


def test_telemetry_clone_is_deep_and_independent():
    original = make_telemetry()
    clone = original.clone()

    clone.metrics[0].value = 999.0

    assert original.metrics[0].value == 0.02
    assert clone.metrics[0].value == 999.0


def test_scenario_holds_ground_truth():
    scenario = Scenario(
        id="error-spike-001",
        description="Sudden error rate spike on checkout service",
        telemetry=make_telemetry(),
        true_root_cause="downstream payment API timeout",
        system="checkout",
    )

    assert scenario.true_root_cause == "downstream payment API timeout"
    assert len(scenario.telemetry.metrics) == 2


def test_agent_verdict_defaults_to_uncommitted():
    verdict = AgentVerdict()

    assert verdict.root_cause is None
    assert verdict.confidence == 0.0
    assert verdict.insufficient_signal is False


def test_agent_verdict_confidence_bounds():
    verdict = AgentVerdict(confidence=1.0, insufficient_signal=True)
    assert verdict.confidence == 1.0
