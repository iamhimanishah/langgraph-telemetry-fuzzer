"""Renders a Report as a human-readable markdown summary."""

from __future__ import annotations

from langgraph_telemetry_fuzzer.grader import Outcome
from langgraph_telemetry_fuzzer.runner import Report


def render_markdown(report: Report) -> str:
    hallucination_pct = report.hallucination_rate()
    over_caution_pct = report.over_caution_rate()
    lines = [
        "# langgraph-telemetry-fuzzer report",
        "",
        f"- Total runs: {report.total}",
        "",
        "## Grounding (the headline metric)",
        "",
        "Did the agent commit or abstain in line with what the telemetry",
        "supported? Independent of whether the named cause was right.",
        "",
        f"- **Grounding score: {report.grounding_score():.0%}**",
        f"- Hallucination rate (of insufficient-signal runs): {hallucination_pct:.0%}",
        f"- Over-caution rate (of sufficient-signal runs): {over_caution_pct:.0%}",
        "",
        "## Accuracy (tracked separately)",
        "",
        f"- Accuracy rate (of answers committed on sufficient signal): "
        f"{report.accuracy_rate():.0%}",
        f"- Strict pass rate (grounded *and* accurate): {report.pass_rate():.0%}",
    ]

    alias_matched = report.alias_matched_count()
    if alias_matched:
        lines.append(
            f"- Note: {alias_matched} correct answer(s) matched via a scenario "
            "alias rather than its canonical phrasing."
        )

    judge_matched = report.judge_matched_count()
    if judge_matched:
        lines.append(
            f"- Note: {judge_matched} correct answer(s) passed only because an "
            "LLM judge called them equivalent — discount accordingly."
        )

    lines += [
        "",
        "## Outcome breakdown",
        "",
        "| Outcome | Count |",
        "| --- | --- |",
    ]
    for outcome in Outcome:
        lines.append(f"| {outcome.value} | {report.count(outcome)} |")

    lines += [
        "",
        "## By corruption axis and severity",
        "",
        "| Axis | Severity | Pass rate |",
        "| --- | --- | --- |",
    ]
    for (axis, severity), (passed, total) in sorted(report.by_axis_severity().items()):
        rate = passed / total if total else 0.0
        lines.append(f"| {axis} | {severity} | {rate:.0%} ({passed}/{total}) |")

    return "\n".join(lines)
