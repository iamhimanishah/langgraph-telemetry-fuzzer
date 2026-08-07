"""Renders a Report as a human-readable markdown summary.

The report deliberately keeps two verdicts apart, because collapsing them
into one pass/fail misleads readers. "Did the agent answer when it should
have?" is a judgement question; "was the answer right?" is a knowledge
question. An earlier version printed outcomes with a single tick or cross,
which rendered a wrong-but-reasonable answer as `WRONG_ANSWER ✅` -- read by
every first-time reader as "wrong is good". Each outcome now states both
verdicts in words.
"""

from __future__ import annotations

from langgraph_telemetry_fuzzer.grader import Outcome
from langgraph_telemetry_fuzzer.runner import Report

# (what happened, was the decision to answer/refuse sound?)
_OUTCOME_MEANING: dict[Outcome, tuple[str, str]] = {
    Outcome.CORRECT_ANSWER: ("Answered, and was right", "sound"),
    Outcome.WRONG_ANSWER: ("Answered, but named the wrong cause", "sound"),
    Outcome.CORRECT_ABSTENTION: ("Refused, and the data was indeed unusable", "sound"),
    Outcome.HALLUCINATION: ("Answered from data that couldn't support it", "UNSOUND"),
    Outcome.OVER_CAUTION: ("Refused, but the data was fine", "UNSOUND"),
}


def render_markdown(report: Report) -> str:
    hallucination_pct = report.hallucination_rate()
    over_caution_pct = report.over_caution_rate()
    lines = [
        "# langgraph-telemetry-fuzzer report",
        "",
        f"- Total runs: {report.total}",
        "",
        "## Judgement — did the agent answer only when it should have?",
        "",
        "This is the headline. It asks whether the agent's decision to answer",
        "or refuse matched what the data could actually support. Naming the",
        "wrong cause from good data still counts as sound judgement: that is a",
        "knowledge failure, not a judgement one.",
        "",
        f"- **Sound judgement: {report.grounding_score():.0%} of runs**",
        f"- Answered anyway on unusable data: {hallucination_pct:.0%} "
        "(of runs where the data was unusable)",
        f"- Refused perfectly usable data: {over_caution_pct:.0%} "
        "(of runs where the data was fine)",
        "",
        "## Accuracy — when it did answer, was the answer right?",
        "",
        "Tracked separately on purpose. A low score here means the agent needs",
        "to get smarter; a low score above means it cannot be trusted.",
        "",
        f"- Named the right cause: {report.accuracy_rate():.0%} "
        "(of answers given on usable data)",
        f"- Both sound and correct: {report.pass_rate():.0%}",
    ]

    alias_matched = report.alias_matched_count()
    if alias_matched:
        lines.append(
            f"- Note: {alias_matched} answer(s) counted as correct via a "
            "scenario alias rather than its exact wording."
        )

    blocked = report.guardrail_blocked_count()
    if blocked:
        lines.append(
            f"- Guardrail gated {blocked} of {report.total} run(s) before the "
            "agent was consulted."
        )

    judge_matched = report.judge_matched_count()
    if judge_matched:
        lines.append(
            f"- Note: {judge_matched} answer(s) counted as correct only because "
            "an LLM judge called them equivalent — discount accordingly."
        )

    lines += [
        "",
        "## What happened, run by run",
        "",
        "| What the agent did | Judgement | Count |",
        "| --- | --- | --- |",
    ]
    for outcome in Outcome:
        what, judgement = _OUTCOME_MEANING[outcome]
        lines.append(f"| {what} | {judgement} | {report.count(outcome)} |")

    lines += [
        "",
        "## By corruption type and severity",
        "",
        "| Damage applied | Severity | Sound *and* correct |",
        "| --- | --- | --- |",
    ]
    for (axis, severity), (passed, total) in sorted(report.by_axis_severity().items()):
        rate = passed / total if total else 0.0
        lines.append(f"| {axis} | {severity} | {rate:.0%} ({passed}/{total}) |")

    return "\n".join(lines)
