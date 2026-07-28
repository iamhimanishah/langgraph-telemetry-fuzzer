# langgraph-telemetry-fuzzer

Eval harness that feeds corrupted, incomplete, or drifted telemetry to LangGraph agents and checks whether they say "insufficient signal" instead of hallucinating a confident root cause.

## Why

Agents that do root-cause analysis over observability data are only trustworthy if they know when the data can't support an answer. In practice, telemetry is often missing fields, delayed, or drifted in schema — and an agent that confidently blames the wrong thing sends humans chasing the wrong fix. This harness makes that failure mode testable: take a golden incident scenario with a known root cause, corrupt its telemetry on purpose, and grade whether the agent abstains when it should and commits when it should.

## Status

All core pieces are in place: data model, corruption injectors, the LangGraph agent adapter, the rule-based grader, the scenario suite, and the `ltf` CLI runner. Docs/contribution polish is next — see the roadmap below.

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

### Matching root causes

Comparing a free-text `root_cause` against ground truth is the grader's one genuinely fuzzy judgment, so it's kept deliberately narrow: matching is case- and whitespace-insensitive **exact equality** against any of the scenario's `accepted_root_causes` (which always includes `true_root_cause`). Aliases let a correct-but-differently-worded answer pass without making matching loose — "the payment thing broke" still fails.

Every `Grade` records *how* it matched via `match_method` (`exact` or `alias`), and the report surfaces the alias-matched count, so a reader can discount passes that only cleared the bar because a scenario author was generous with phrasings.

```python
from langgraph_telemetry_fuzzer import grade

result = grade(scenario, spec, verdict)
print(result.outcome, result.passed, result.reason)
```

This is rule-based, not an LLM judge — because `AgentVerdict` is a fixed shape, grading is just comparing a few fields, no free-text interpretation needed. See `tests/test_grader_integration.py` for the full pipeline (scenario → corrupt → real agent → grade) run end to end, including the naive `rca_agent`'s `delay` blind spot caught as an actual `HALLUCINATION` grade.

## Scenario suite

`langgraph_telemetry_fuzzer.scenarios` ships 6 hand-crafted incident fixtures, each a distinct failure signature with its own `tolerant_up_to` reasoned from that scenario's actual data shape (a sudden spike tolerates data loss differently than a gradual ramp, or a pattern whose causal story depends on event ordering). It's part of the installed package (not a dev-only fixture directory), so it's available out of the box after `pip install`.

- **`checkout-error-spike`** — a sudden, sustained `error_rate` spike with plenty of redundant signal (tolerates moderate `missing`).
- **`api-latency-degradation`** — `p99_latency_ms` climbs steadily; the signal is the *trend*, so it's sensitive to truncation.
- **`cascading-dependency-failure`** — `db_latency_ms` spikes, then `api_error_rate` follows; identifying which caused which depends on event ordering, so it declares zero tolerance for `delay`.
- **`disk-saturation`** — a declining metric plus ENOSPC log lines carrying the specific evidence a metric alone wouldn't explain.
- **`deployment-regression`** — an `error_rate` step tied to a deploy marker log line; again ordering-sensitive.
- **`third-party-outage`** — a bursty, intermittent pattern rather than a clean step; the noisiest and least tolerant scenario in the suite.

```python
from langgraph_telemetry_fuzzer.scenarios import ALL_SCENARIOS, single_axis_matrix

for scenario in ALL_SCENARIOS:
    for spec in single_axis_matrix(seed=0):
        ...  # apply_corruptions -> run agent -> grade
```

`single_axis_matrix()` generates the standard eval surface: one clean baseline, plus every (corruption axis, severity) pair swept independently — 13 specs total per scenario, rather than the full 256-combination cross product across all 4 axes at once.

## CLI runner

`ltf run --agent module:function` runs `ALL_SCENARIOS` × `single_axis_matrix()` against a LangGraph agent, prints a markdown report, and exits non-zero if anything failed (like a test runner):

```bash
ltf run --agent your_package.your_agent:build_graph --seed 0 --json-out report.json
```

- `--agent` is `module:function` — the function takes no arguments and returns a compiled LangGraph graph.
- `--seed` (default `0`) is passed through to the corruption matrix for reproducibility.
- `--json-out` optionally writes the full per-run results, plus the computed summary metrics, as JSON.
- `--fail-on` controls the exit code: `grounding` (default) fails only on ungrounded runs, `strict` fails on any imperfect run including wrong-but-grounded answers.

### Grounding vs. accuracy

The report separates two questions that are easy to conflate:

- **Grounding score** (headline) — did the agent's *commit-vs-abstain decision* match what the telemetry could support? Naming the wrong cause while correctly choosing to commit still counts as grounded, because being wrong is an accuracy problem, not a calibration one.
- **Accuracy rate** — of the answers it did commit on sufficient signal, how many named the right cause?

This split matters because the harness exists to measure calibration. If a phrasing mismatch or a plain wrong answer dragged down the same number that reports hallucination behavior, the metric that actually matters would be buried in unrelated noise. `pass_rate` is still reported as the strict both-must-hold number, and `--fail-on grounding` is the default gate for the same reason.

The report also breaks down pass rate by corruption axis and severity.

To try it against the bundled reference agent from the repo root:

```bash
python -m langgraph_telemetry_fuzzer.cli run --agent examples.rca_agent:build_graph
```

(`examples/` isn't part of the installed package — it's a dev-only demo directory — so it needs the repo root on `sys.path`, which `python -m` provides automatically. A real agent installed as part of your own package works with plain `ltf run --agent ...`.)

Running that command reports roughly **68% grounding, 0% accuracy** for the bundled reference agent — and the gap between those two numbers is the point of separating them. `rca_agent` still hardcodes root-cause strings written for a single ad hoc scenario that predates the suite, so it names the wrong cause essentially everywhere. That's a real limitation of the demo agent, now correctly isolated as an *accuracy* failure instead of contaminating the grounding number that measures what this harness is actually for.

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
6. ~~CLI runner + report~~
7. Docs and contribution guide

## License

MIT
