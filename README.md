# langgraph-telemetry-fuzzer

Eval harness that feeds corrupted, incomplete, or drifted telemetry to LangGraph agents and checks whether they say "insufficient signal" instead of hallucinating a confident root cause.

## Why

Agents that do root-cause analysis over observability data are only trustworthy if they know when the data can't support an answer. In practice, telemetry is often missing fields, delayed, or drifted in schema — and an agent that confidently blames the wrong thing sends humans chasing the wrong fix. This harness makes that failure mode testable: take a golden incident scenario with a known root cause, corrupt its telemetry on purpose, and grade whether the agent abstains when it should and commits when it should.

## Status

Core data model, corruption injectors, the LangGraph agent adapter, the rule-based grader, and a hand-crafted scenario suite are all in place. The CLI runner is next — see the roadmap below.

## Core model

- **`Telemetry`** — metrics, logs, and traces for one incident window. This is what gets corrupted.
- **`Scenario`** — a golden telemetry bundle plus its ground-truth root cause.
- **`AgentVerdict`** — the fixed shape an agent under test must answer in: `root_cause`, `confidence`, `insufficient_signal`, `evidence_refs`. Grading is mechanical because the output shape is fixed.
- **`CorruptionSpec`** — which injectors to run against a scenario's telemetry, at what severity (`none`/`mild`/`moderate`/`severe`), and a seed for reproducibility.
- **`ToleranceSpec`** — how much corruption, per axis, a scenario's ground truth can survive. Defaults to `NONE` on every axis (fail-closed): a scenario has to explicitly declare "the answer is still recoverable up to this severity," rather than silently assuming corrupted telemetry stays fully answerable.

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

## Agent adapter

`LangGraphAdapter` wraps any compiled LangGraph graph so the harness can run it uniformly. It doesn't import `langgraph` itself — it only needs an object with an `.invoke(state: dict) -> dict` method, so `langgraph` stays an optional dependency (`pip install -e ".[langgraph]"`) needed only to run the example agent.

Your graph's state must accept telemetry under `telemetry_key` (default `"telemetry"`) and return a verdict — an `AgentVerdict` or a plain dict with its fields — under `verdict_key` (default `"verdict"`):

```python
from langgraph_telemetry_fuzzer.adapter import LangGraphAdapter
from examples.rca_agent import build_graph

adapter = LangGraphAdapter(build_graph())
verdict = adapter.run(scenario.telemetry)
```

**`examples/rca_agent.py`** is a small, offline, rule-based reference agent (two LangGraph nodes: `analyze` → `decide`) used to dogfood the injectors — no LLM calls or API keys needed. It's deliberately naive in one specific way: it checks how many matching metric points survived, but never checks whether their timestamps make sense. That blind spot shows up under the `delay` injector, where it confidently repeats its clean-data answer even after severe timestamp skew — exactly the overconfidence failure mode this whole project exists to catch. See `tests/test_rca_agent.py` for that behavior demonstrated against real corrupted telemetry.

## Grader

`grade(scenario, spec, verdict)` turns a graded run into one of five outcomes, based on whether the corrupted telemetry still supported the scenario's `true_root_cause` (per its `tolerant_up_to`) and whether the agent's `AgentVerdict` matched that:

| Signal was... | Agent said "insufficient"? | Agent committed and was right? | Outcome | Pass? |
|---|---|---|---|---|
| sufficient | no | yes | `CORRECT_ANSWER` | ✅ |
| sufficient | no | no | `WRONG_ANSWER` | ❌ |
| sufficient | yes | — | `OVER_CAUTION` | ❌ |
| insufficient | yes | — | `CORRECT_ABSTENTION` | ✅ |
| insufficient | no | — | `HALLUCINATION` | ❌ |

Being right for the wrong reason still fails: a confident, *correct* answer reached from telemetry the scenario declares insufficient is still graded `HALLUCINATION`, not `CORRECT_ANSWER` — the point is whether the answer was grounded, not whether it happened to land right.

```python
from langgraph_telemetry_fuzzer import grade

result = grade(scenario, spec, verdict)
print(result.outcome, result.passed, result.reason)
```

This is rule-based, not an LLM judge — because `AgentVerdict` is a fixed shape, grading is just comparing a few fields, no free-text interpretation needed. See `tests/test_grader_integration.py` for the full pipeline (scenario → corrupt → real agent → grade) run end to end, including the naive `rca_agent`'s `delay` blind spot caught as an actual `HALLUCINATION` grade.

## Scenario suite

`scenarios/definitions.py` ships 6 hand-crafted incident fixtures, each a distinct failure signature with its own `tolerant_up_to` reasoned from that scenario's actual data shape (a sudden spike tolerates data loss differently than a gradual ramp, or a pattern whose causal story depends on event ordering):

- **`checkout-error-spike`** — a sudden, sustained `error_rate` spike with plenty of redundant signal (tolerates moderate `missing`).
- **`api-latency-degradation`** — `p99_latency_ms` climbs steadily; the signal is the *trend*, so it's sensitive to truncation.
- **`cascading-dependency-failure`** — `db_latency_ms` spikes, then `api_error_rate` follows; identifying which caused which depends on event ordering, so it declares zero tolerance for `delay`.
- **`disk-saturation`** — a declining metric plus ENOSPC log lines carrying the specific evidence a metric alone wouldn't explain.
- **`deployment-regression`** — an `error_rate` step tied to a deploy marker log line; again ordering-sensitive.
- **`third-party-outage`** — a bursty, intermittent pattern rather than a clean step; the noisiest and least tolerant scenario in the suite.

```python
from scenarios import ALL_SCENARIOS, single_axis_matrix

for scenario in ALL_SCENARIOS:
    for spec in single_axis_matrix(seed=0):
        ...  # apply_corruptions -> run agent -> grade
```

`single_axis_matrix()` generates the standard eval surface: one clean baseline, plus every (corruption axis, severity) pair swept independently — 13 specs total per scenario, rather than the full 256-combination cross product across all 4 axes at once.

## Install (dev)

```bash
pip install -e ".[dev,langgraph]"
pytest
```

## Roadmap

1. ~~Repo skeleton + core data model~~
2. ~~Corruption injectors: missing data, delayed timestamps, schema drift, truncation~~
3. ~~Reference LangGraph agent adapter + example agent~~
4. ~~Rule-based grader (hallucination vs. correct abstention vs. over-caution)~~
5. ~~Scenario suite with a corruption severity matrix~~
6. CLI runner + report
7. Docs and contribution guide

## License

MIT
