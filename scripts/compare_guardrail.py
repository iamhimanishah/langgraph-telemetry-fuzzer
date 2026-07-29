"""Three-way (plus baseline) comparison of guardrail impact.

Runs single_axis_matrix against ALL_SCENARIOS for each agent variant and
reports grounding score per corruption axis. Uses grade() unmodified.

Variants:
  1   rca_agent                      the published baseline
  1g  rca_agent + guardrail gate     isolates the trust signal, no model
  2   llm_rca_agent + raw tool       needs ANTHROPIC_API_KEY
  3   llm_rca_agent + guarded tool   needs ANTHROPIC_API_KEY

1g holds the reasoning constant and changes only whether the agent is told
the data is untrustworthy, so any movement is attributable to the guardrail
rather than to a model's willingness to follow a prompt. 2 and 3 then
measure whether a real model actually honours that signal.

Usage:
  python scripts/compare_guardrail.py [--seed 0] [--json-out report.json]
  python scripts/compare_guardrail.py --variants 1,1g     # skip LLM runs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# examples/ is a dev-only directory, not part of the installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph_telemetry_fuzzer import (  # noqa: E402
    AgentVerdict,
    CorruptionSpec,
    Scenario,
    Severity,
    Telemetry,
    apply_corruptions,
    grade,
)
from langgraph_telemetry_fuzzer.adapter import LangGraphAdapter  # noqa: E402
from langgraph_telemetry_fuzzer.grader import Outcome  # noqa: E402
from langgraph_telemetry_fuzzer.guardrail import compute_trust_metadata  # noqa: E402
from langgraph_telemetry_fuzzer.scenarios import (  # noqa: E402
    ALL_SCENARIOS,
    single_axis_matrix,
)

EXPECTED_INTERVAL_SECONDS = 1.0
AXES = ("missing", "delay", "drift", "truncate")
UNGROUNDED = {Outcome.HALLUCINATION, Outcome.OVER_CAUTION}


def axis_label(spec: CorruptionSpec) -> str:
    for axis in AXES:
        severity = getattr(spec, axis)
        if severity != Severity.NONE:
            return axis
    return "clean"


def query_window_end(scenario: Scenario) -> datetime:
    stamps = [m.timestamp for m in scenario.telemetry.metrics]
    stamps += [entry.timestamp for entry in scenario.telemetry.logs]
    return max(stamps)


# -- variants ----------------------------------------------------------------


def make_baseline():
    from examples.rca_agent import build_graph

    adapter = LangGraphAdapter(build_graph())

    def run(telemetry: Telemetry, scenario: Scenario) -> AgentVerdict:
        return adapter.run(telemetry)

    return run


def make_guarded_baseline():
    """rca_agent behind a guardrail gate.

    The gate sees only the telemetry and the clock. When trust is low it
    abstains outright; otherwise the underlying agent answers exactly as it
    would have.
    """
    from examples.rca_agent import build_graph

    adapter = LangGraphAdapter(build_graph())

    def run(telemetry: Telemetry, scenario: Scenario) -> AgentVerdict:
        trust = compute_trust_metadata(
            telemetry,
            query_time=query_window_end(scenario),
            expected_interval_seconds=EXPECTED_INTERVAL_SECONDS,
        )
        if trust.confidence == "low":
            return AgentVerdict(
                insufficient_signal=True,
                confidence=0.0,
                evidence_refs=[trust.reason],
            )
        return adapter.run(telemetry)

    return run


def make_llm(guarded: bool):
    from examples.llm_rca_agent import build_graph

    def run(telemetry: Telemetry, scenario: Scenario) -> AgentVerdict:
        graph = build_graph(guarded=guarded, query_time=query_window_end(scenario))
        return LangGraphAdapter(graph).run(telemetry)

    return run


VARIANTS = {
    "1": ("rca_agent (baseline)", make_baseline, False),
    "1g": ("rca_agent + guardrail", make_guarded_baseline, False),
    "2": ("llm_rca_agent + raw", lambda: make_llm(False), True),
    "3": ("llm_rca_agent + guarded", lambda: make_llm(True), True),
}


# -- run ---------------------------------------------------------------------


def run_variant(runner, specs, scenarios=None) -> dict:
    per_axis: dict[str, list[bool]] = defaultdict(list)
    outcomes: dict[str, int] = defaultdict(int)

    for scenario in scenarios or ALL_SCENARIOS:
        for spec in specs:
            corrupted = apply_corruptions(scenario.telemetry, spec)
            verdict = runner(corrupted, scenario)
            result = grade(scenario, spec, verdict)
            per_axis[axis_label(spec)].append(result.outcome not in UNGROUNDED)
            outcomes[result.outcome.value] += 1

    grounding = {
        axis: sum(flags) / len(flags) for axis, flags in sorted(per_axis.items())
    }
    all_flags = [f for flags in per_axis.values() for f in flags]
    return {
        "grounding_by_axis": grounding,
        "grounding_overall": sum(all_flags) / len(all_flags),
        "outcome_counts": dict(outcomes),
        "total": len(all_flags),
    }


def render_markdown(results: dict[str, dict], skipped: dict[str, str]) -> str:
    axes = ["clean", *AXES]
    header = "| Variant | " + " | ".join(axes) + " | **overall** |"
    sep = "|" + "---|" * (len(axes) + 2)
    lines = ["## Grounding score by corruption axis", "", header, sep]

    for key, (label, _, _) in VARIANTS.items():
        if key in skipped:
            cells = " | ".join("—" for _ in axes)
            lines.append(f"| {label} | {cells} | _{skipped[key]}_ |")
            continue
        if key not in results:
            continue
        data = results[key]
        # An axis with no runs is "not measured", not "scored zero".
        cells = " | ".join(
            f"{data['grounding_by_axis'][a]:.0%}"
            if a in data["grounding_by_axis"]
            else "—"
            for a in axes
        )
        lines.append(f"| {label} | {cells} | **{data['grounding_overall']:.0%}** |")

    lines += ["", "## Outcome counts", "", "| Variant | " + " | ".join(
        o.value for o in Outcome
    ) + " |", "|" + "---|" * (len(Outcome) + 1)]
    for key, (label, _, _) in VARIANTS.items():
        if key not in results:
            continue
        counts = results[key]["outcome_counts"]
        cells = " | ".join(str(counts.get(o.value, 0)) for o in Outcome)
        lines.append(f"| {label} | {cells} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="compare_guardrail")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument(
        "--axes",
        default="",
        help="Restrict to these corruption axes, e.g. 'delay' (default: all)",
    )
    parser.add_argument(
        "--scenarios",
        default="",
        help="Restrict to these scenario ids, comma-separated (default: all)",
    )
    parser.add_argument(
        "--variants",
        default=",".join(VARIANTS),
        help=f"Comma-separated subset of: {', '.join(VARIANTS)}",
    )
    args = parser.parse_args()

    specs = single_axis_matrix(seed=args.seed)
    if args.axes:
        wanted = {a.strip() for a in args.axes.split(",") if a.strip()}
        specs = [sp for sp in specs if axis_label(sp) in wanted]
    scenarios = None
    if args.scenarios:
        ids = {i.strip() for i in args.scenarios.split(",") if i.strip()}
        scenarios = [s for s in ALL_SCENARIOS if s.id in ids]

    requested = [v.strip() for v in args.variants.split(",") if v.strip()]
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    results: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for key in requested:
        if key not in VARIANTS:
            print(f"unknown variant {key!r}", file=sys.stderr)
            return 2
        label, factory, needs_key = VARIANTS[key]
        if needs_key and not has_key:
            skipped[key] = "not run — no ANTHROPIC_API_KEY"
            print(f"[skip] {label}: no ANTHROPIC_API_KEY", file=sys.stderr)
            continue
        print(f"[run ] {label} ...", file=sys.stderr)
        results[key] = run_variant(factory(), specs, scenarios)

    print(render_markdown(results, skipped))

    if args.json_out:
        args.json_out.write_text(
            json.dumps({"seed": args.seed, "results": results}, indent=2)
        )
        print(f"\nFull results written to {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
