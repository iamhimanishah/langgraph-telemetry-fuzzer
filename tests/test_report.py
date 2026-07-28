from langgraph_telemetry_fuzzer import AgentVerdict, CorruptionSpec, Severity
from langgraph_telemetry_fuzzer.grader import (
    PASSING_OUTCOMES,
    Grade,
    MatchMethod,
    Outcome,
)
from langgraph_telemetry_fuzzer.report import render_markdown
from langgraph_telemetry_fuzzer.runner import Report, RunResult


def make_result(
    outcome: Outcome,
    spec: CorruptionSpec | None = None,
    match_method: MatchMethod | None = None,
) -> RunResult:
    return RunResult(
        scenario_id="s1",
        spec=spec or CorruptionSpec(),
        verdict=AgentVerdict(),
        grade=Grade(
            outcome=outcome,
            passed=outcome in PASSING_OUTCOMES,
            reason="test",
            match_method=match_method,
        ),
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
    assert "Strict pass rate (grounded *and* accurate): 50%" in markdown
    assert "correct_answer" in markdown
    assert "hallucination" in markdown
    assert "| delay | severe |" in markdown


def test_render_markdown_separates_grounding_from_accuracy():
    report = Report(
        results=[
            make_result(Outcome.CORRECT_ANSWER),
            make_result(Outcome.WRONG_ANSWER),
        ]
    )

    markdown = render_markdown(report)

    # Both answers were grounded; only one was accurate.
    assert "**Grounding score: 100%**" in markdown
    assert "Accuracy rate (of answers committed on sufficient signal): 50%" in markdown


def test_render_markdown_flags_alias_matched_answers():
    report = Report(
        results=[make_result(Outcome.CORRECT_ANSWER, match_method=MatchMethod.ALIAS)]
    )

    markdown = render_markdown(report)

    assert "1 correct answer(s) matched via a scenario alias" in markdown


def test_render_markdown_omits_alias_note_when_there_are_none():
    report = Report(
        results=[make_result(Outcome.CORRECT_ANSWER, match_method=MatchMethod.EXACT)]
    )

    markdown = render_markdown(report)

    assert "alias" not in markdown.lower()


def test_render_markdown_handles_empty_report():
    markdown = render_markdown(Report(results=[]))
    assert "Total runs: 0" in markdown
