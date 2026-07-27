# langgraph-telemetry-fuzzer

Eval harness that feeds corrupted, incomplete, or drifted telemetry to LangGraph agents and checks whether they say "insufficient signal" instead of hallucinating a confident root cause.

## Why

Agents that do root-cause analysis over observability data are only trustworthy if they know when the data can't support an answer. In practice, telemetry is often missing fields, delayed, or drifted in schema — and an agent that confidently blames the wrong thing sends humans chasing the wrong fix. This harness makes that failure mode testable: take a golden incident scenario with a known root cause, corrupt its telemetry on purpose, and grade whether the agent abstains when it should and commits when it should.

## Status

Core data model and corruption injectors are in place. The agent adapter, grader, and CLI runner are next — see the roadmap below.

## Core model

- **`Telemetry`** — metrics, logs, and traces for one incident window. This is what gets corrupted.
- **`Scenario`** — a golden telemetry bundle plus its ground-truth root cause.
- **`AgentVerdict`** — the fixed shape an agent under test must answer in: `root_cause`, `confidence`, `insufficient_signal`, `evidence_refs`. Grading is mechanical because the output shape is fixed.
- **`CorruptionSpec`** — which injectors to run against a scenario's telemetry, at what severity (`none`/`mild`/`moderate`/`severe`), and a seed for reproducibility.

## Corruption injectors

Four independent injectors, applied in a fixed order via `apply_corruptions(telemetry, spec)`:

- **`missing`** — independently drops each metric/log entry at a rate set by severity.
- **`delay`** — shifts timestamps by a random offset within a severity-scaled window (can reorder events, not just shift the whole window).
- **`drift`** — renames a fraction of metric names and bumps `schema_version`, without telling the agent — it has to notice.
- **`truncate`** — keeps only the earliest fraction of the telemetry window, simulating an agent that answered before all the data arrived.

```python
from langgraph_telemetry_fuzzer import CorruptionSpec, Severity, apply_corruptions

spec = CorruptionSpec(seed=42, missing=Severity.MODERATE, truncate=Severity.SEVERE)
corrupted = apply_corruptions(scenario.telemetry, spec)
```

Same telemetry + same spec always produces identical output — corruption is deterministic, not just random noise.

## Install (dev)

```bash
pip install -e ".[dev]"
pytest
```

## Roadmap

1. ~~Repo skeleton + core data model~~
2. ~~Corruption injectors: missing data, delayed timestamps, schema drift, truncation~~
3. Reference LangGraph agent adapter + example agent
4. Rule-based grader (hallucination vs. correct abstention vs. over-caution)
5. Scenario suite with a corruption severity matrix
6. CLI runner + report
7. Docs and contribution guide

## License

MIT
