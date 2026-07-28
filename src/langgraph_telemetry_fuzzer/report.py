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
        f"- Pass rate: {report.pass_rate():.0%}",
        f"- Hallucination rate (of insufficient-signal runs): {hallucination_pct:.0%}",
        f"- Over-caution rate (of sufficient-signal runs): {over_caution_pct:.0%}",
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
