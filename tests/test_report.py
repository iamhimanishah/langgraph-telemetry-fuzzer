from langgraph_telemetry_fuzzer import AgentVerdict, CorruptionSpec, Severity
from langgraph_telemetry_fuzzer.grader import PASSING_OUTCOMES, Grade, Outcome
from langgraph_telemetry_fuzzer.report import render_markdown
from langgraph_telemetry_fuzzer.runner import Report, RunResult


def make_result(outcome: Outcome, spec: CorruptionSpec | None = None) -> RunResult:
    return RunResult(
        scenario_id="s1",
        spec=spec or CorruptionSpec(),
        verdict=AgentVerdict(),
        grade=Grade(outcome=outcome, passed=outcome in PASSING_OUTCOMES, reason="test"),
    )


def test_render_markdown_includes_summary_numbers():
    severe_delay = CorruptionSpec(delay=Severity.SEVERE)
    report = Report(
        results=[
            make_result(Outcome.CORRECT_ANSWER),
            make_result(Outcome.HALLUCINATION, spec=severe_delay),
        ]
    )

    markdown = render_markdown(report)

    assert "Total runs: 2" in markdown
    assert "Pass rate: 50%" in markdown
    assert "correct_answer" in markdown
    assert "hallucination" in markdown
    assert "| delay | severe |" in markdown


def test_render_markdown_handles_empty_report():
    markdown = render_markdown(Report(results=[]))
    assert "Total runs: 0" in markdown
