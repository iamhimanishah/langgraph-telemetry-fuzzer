# langgraph-telemetry-fuzzer

Eval harness that feeds corrupted, incomplete, or drifted telemetry to LangGraph agents and checks whether they say "insufficient signal" instead of hallucinating a confident root cause.

## Why

Agents that do root-cause analysis over observability data are only trustworthy if they know when the data can't support an answer. In practice, telemetry is often missing fields, delayed, or drifted in schema — and an agent that confidently blames the wrong thing sends humans chasing the wrong fix. This harness makes that failure mode testable: take a golden incident scenario with a known root cause, corrupt its telemetry on purpose, and grade whether the agent abstains when it should and commits when it should.

## Status

Early scaffolding. Core data model is in place (`Telemetry`, `Scenario`, `AgentVerdict`). Corruption injectors, the grader, and the CLI runner are next — see the roadmap below.

## Core model

- **`Telemetry`** — metrics, logs, and traces for one incident window. This is what gets corrupted.
- **`Scenario`** — a golden telemetry bundle plus its ground-truth root cause.
- **`AgentVerdict`** — the fixed shape an agent under test must answer in: `root_cause`, `confidence`, `insufficient_signal`, `evidence_refs`. Grading is mechanical because the output shape is fixed.

## Install (dev)

```bash
pip install -e ".[dev]"
pytest
```

## Roadmap

1. ~~Repo skeleton + core data model~~
2. Corruption injectors: missing data, delayed timestamps, schema drift, truncation
3. Reference LangGraph agent adapter + example agent
4. Rule-based grader (hallucination vs. correct abstention vs. over-caution)
5. Scenario suite with a corruption severity matrix
6. CLI runner + report
7. Docs and contribution guide

## License

MIT
