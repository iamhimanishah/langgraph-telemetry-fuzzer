"""CLI entry point.

`ltf run --agent module:function` runs the built-in scenario suite (see
langgraph_telemetry_fuzzer.scenarios) against a LangGraph agent across the
standard corruption matrix, prints a markdown summary, and optionally
writes the full per-run results as JSON.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from langgraph_telemetry_fuzzer.adapter import LangGraphAdapter
from langgraph_telemetry_fuzzer.guardrail import GuardrailGate
from langgraph_telemetry_fuzzer.judge import DEFAULT_MODEL as JUDGE_DEFAULT_MODEL
from langgraph_telemetry_fuzzer.report import render_markdown
from langgraph_telemetry_fuzzer.runner import run_suite
from langgraph_telemetry_fuzzer.scenarios import ALL_SCENARIOS, single_axis_matrix


def _load_adapter(agent_spec: str) -> LangGraphAdapter:
    """`agent_spec` is "module.path:function_name" -- the function takes no
    arguments and returns a compiled LangGraph graph, e.g.
    "examples.rca_agent:build_graph".
    """
    module_name, sep, func_name = agent_spec.partition(":")
    if not sep:
        raise ValueError(f"--agent must be 'module:function', got {agent_spec!r}")
    module = importlib.import_module(module_name)
    try:
        build_graph = getattr(module, func_name)
    except AttributeError as exc:
        raise ValueError(f"{module_name!r} has no attribute {func_name!r}") from exc
    return LangGraphAdapter(build_graph())


def _run(args: argparse.Namespace) -> int:
    try:
        adapter = _load_adapter(args.agent)
    except (ImportError, ValueError) as exc:
        print(f"ltf: {exc}", file=sys.stderr)
        return 2

    judge = None
    if args.judge:
        from langgraph_telemetry_fuzzer.judge import LLMJudge

        try:
            judge = LLMJudge(model=args.judge_model)
        except ImportError as exc:
            print(f"ltf: {exc}", file=sys.stderr)
            return 2

    guardrail = None
    if args.guardrail:
        guardrail = GuardrailGate(
            expected_interval_seconds=args.expected_interval,
            expected_schema_version=args.expected_schema_version,
        )

    specs = single_axis_matrix(seed=args.seed)
    report = run_suite(
        ALL_SCENARIOS, specs, adapter, judge=judge, guardrail=guardrail
    )

    print(render_markdown(report))

    if args.json_out:
        args.json_out.write_text(json.dumps(report.to_json_dict(), indent=2))
        print(f"\nFull report written to {args.json_out}")

    if args.fail_on == "strict":
        return 0 if report.pass_rate() == 1.0 else 1
    return 0 if report.grounding_score() == 1.0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ltf")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run the scenario suite against a LangGraph agent"
    )
    run_parser.add_argument(
        "--agent",
        required=True,
        help="module:function returning a compiled LangGraph graph, "
        "e.g. examples.rca_agent:build_graph",
    )
    run_parser.add_argument(
        "--seed", type=int, default=0, help="Corruption seed (default: 0)"
    )
    run_parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write the full report as JSON to this path",
    )
    run_parser.add_argument(
        "--fail-on",
        choices=("grounding", "strict"),
        default="grounding",
        help="Exit non-zero on any ungrounded run (default), or on any "
        "failure at all including wrong-but-grounded answers ('strict')",
    )
    run_parser.add_argument(
        "--guardrail",
        action="store_true",
        help="Gate the agent behind trust signals computed from the telemetry "
        "alone: abstain on its behalf when the data can't support a conclusion",
    )
    run_parser.add_argument(
        "--expected-interval",
        type=float,
        default=1.0,
        help="Seconds between samples in your feed, used for the completeness "
        "and staleness checks (default: 1.0)",
    )
    run_parser.add_argument(
        "--expected-schema-version",
        default=None,
        help="The telemetry schema your consumer parses. Omit to skip the "
        "schema check entirely",
    )
    run_parser.add_argument(
        "--judge",
        action="store_true",
        help="Opt in to an LLM judge as a fallback when exact and alias "
        "root-cause matching both miss. Costs API calls, is nondeterministic, "
        "and should not be used in CI — see the README",
    )
    run_parser.add_argument(
        "--judge-model",
        default=JUDGE_DEFAULT_MODEL,
        help=f"Model for --judge (default: {JUDGE_DEFAULT_MODEL})",
    )
    run_parser.set_defaults(func=_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
