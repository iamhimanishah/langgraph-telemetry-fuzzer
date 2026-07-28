import json

import pytest

langgraph = pytest.importorskip("langgraph")

from langgraph_telemetry_fuzzer.cli import (  # noqa: E402
    _load_adapter,
    build_parser,
    main,
)


def test_build_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["run", "--agent", "examples.rca_agent:build_graph"])

    assert args.command == "run"
    assert args.agent == "examples.rca_agent:build_graph"
    assert args.seed == 0
    assert args.json_out is None
    assert args.fail_on == "grounding"
    assert args.judge is False


def test_judge_is_opt_in_and_takes_a_model():
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--agent", "a:b", "--judge", "--judge-model", "claude-sonnet-5"]
    )

    assert args.judge is True
    assert args.judge_model == "claude-sonnet-5"


def test_fail_on_accepts_strict():
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--agent", "a:b", "--fail-on", "strict"],
    )

    assert args.fail_on == "strict"


def test_fail_on_rejects_unknown_values():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--agent", "a:b", "--fail-on", "vibes"])


def test_run_requires_agent_argument():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])


def test_load_adapter_rejects_spec_without_colon():
    with pytest.raises(ValueError, match="module:function"):
        _load_adapter("examples.rca_agent")


def test_load_adapter_rejects_missing_attribute():
    with pytest.raises(ValueError, match="no attribute"):
        _load_adapter("examples.rca_agent:does_not_exist")


def test_main_runs_the_full_suite_and_prints_a_report(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv", ["ltf", "run", "--agent", "examples.rca_agent:build_graph"]
    )

    exit_code = main()

    captured = capsys.readouterr()
    assert "langgraph-telemetry-fuzzer report" in captured.out
    assert "Total runs:" in captured.out
    # The naive rca_agent is known to fail under severe delay corruption
    # (see test_rca_agent.py), so a fully passing run isn't expected here --
    # this just proves the CLI wires everything together end to end.
    assert exit_code in (0, 1)


def test_main_writes_json_report(monkeypatch, tmp_path):
    json_path = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "ltf",
            "run",
            "--agent",
            "examples.rca_agent:build_graph",
            "--json-out",
            str(json_path),
        ],
    )

    main()

    data = json.loads(json_path.read_text())
    assert "summary" in data
    assert "results" in data
    assert data["summary"]["total"] > 0
