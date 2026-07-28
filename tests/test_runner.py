from helpers import build_telemetry

from langgraph_telemetry_fuzzer import AgentVerdict, CorruptionSpec, Scenario, Severity
from langgraph_telemetry_fuzzer.grader import PASSING_OUTCOMES, Grade, Outcome
from langgraph_telemetry_fuzzer.runner import Report, RunResult, run_suite


class FakeAdapter:
    """Returns a fixed AgentVerdict regardless of input telemetry."""

    def __init__(self, verdict: AgentVerdict):
        self.verdict = verdict
        self.calls = 0

    def run(self, telemetry):
        self.calls += 1
        return self.verdict


def make_scenario(scenario_id: str = "s1") -> Scenario:
    return Scenario(
        id=scenario_id,
        description="test scenario",
        telemetry=build_telemetry(),
        true_root_cause="disk full",
    )


def make_result(outcome: Outcome, spec: CorruptionSpec | None = None) -> RunResult:
    return RunResult(
        scenario_id="s1",
        spec=spec or CorruptionSpec(),
        verdict=AgentVerdict(),
        grade=Grade(outcome=outcome, passed=outcome in PASSING_OUTCOMES, reason="test"),
    )


# -- run_suite ----------------------------------------------------------


def test_run_suite_produces_one_result_per_scenario_spec_pair():
    scenarios = [make_scenario("s1"), make_scenario("s2")]
    specs = [
        CorruptionSpec(),
        CorruptionSpec(missing=Severity.MILD),
        CorruptionSpec(delay=Severity.SEVERE),
    ]
    adapter = FakeAdapter(AgentVerdict(insufficient_signal=True))

    report = run_suite(scenarios, specs, adapter)

    assert report.total == len(scenarios) * len(specs)
    assert adapter.calls == len(scenarios) * len(specs)


# -- Report.pass_rate ----------------------------------------------------


def test_pass_rate():
    report = Report(
        results=[
            make_result(Outcome.CORRECT_ANSWER),
            make_result(Outcome.WRONG_ANSWER),
            make_result(Outcome.CORRECT_ABSTENTION),
            make_result(Outcome.HALLUCINATION),
        ]
    )
    assert report.pass_rate() == 0.5


def test_pass_rate_of_empty_report_is_zero():
    assert Report(results=[]).pass_rate() == 0.0


# -- Report.hallucination_rate / over_caution_rate ------------------------


def test_hallucination_rate_only_considers_insufficient_signal_runs():
    report = Report(
        results=[
            make_result(Outcome.CORRECT_ANSWER),  # sufficient signal, excluded
            make_result(Outcome.HALLUCINATION),
            make_result(Outcome.CORRECT_ABSTENTION),
            make_result(Outcome.CORRECT_ABSTENTION),
        ]
    )
    assert report.hallucination_rate() == 1 / 3


def test_hallucination_rate_is_zero_with_no_insufficient_signal_runs():
    report = Report(results=[make_result(Outcome.CORRECT_ANSWER)])
    assert report.hallucination_rate() == 0.0


def test_over_caution_rate_only_considers_sufficient_signal_runs():
    report = Report(
        results=[
            make_result(Outcome.CORRECT_ABSTENTION),  # insufficient signal, excluded
            make_result(Outcome.OVER_CAUTION),
            make_result(Outcome.CORRECT_ANSWER),
            make_result(Outcome.WRONG_ANSWER),
        ]
    )
    assert report.over_caution_rate() == 1 / 3


# -- Report.by_axis_severity ----------------------------------------------


def test_by_axis_severity_groups_by_dominant_axis():
    mild_missing = CorruptionSpec(missing=Severity.MILD)
    report = Report(
        results=[
            make_result(Outcome.CORRECT_ANSWER, spec=CorruptionSpec()),
            make_result(Outcome.HALLUCINATION, spec=mild_missing),
            make_result(Outcome.CORRECT_ABSTENTION, spec=mild_missing),
        ]
    )
    buckets = report.by_axis_severity()

    assert buckets[("clean", "none")] == (1, 1)
    assert buckets[("missing", "mild")] == (1, 2)


# -- Report.to_json_dict ---------------------------------------------------


def test_to_json_dict_has_summary_and_results():
    report = Report(results=[make_result(Outcome.CORRECT_ANSWER)])
    data = report.to_json_dict()

    assert data["summary"]["total"] == 1
    assert data["summary"]["pass_rate"] == 1.0
    assert len(data["results"]) == 1
