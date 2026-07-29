# langgraph-telemetry-fuzzer

Eval harness that feeds corrupted, incomplete, or drifted telemetry to LangGraph agents and checks whether they say "insufficient signal" instead of hallucinating a confident root cause.

## Why

Agents that do root-cause analysis over observability data are only trustworthy if they know when the data can't support an answer. In practice, telemetry is often missing fields, delayed, or drifted in schema — and an agent that confidently blames the wrong thing sends humans chasing the wrong fix. This harness makes that failure mode testable: take a golden incident scenario with a known root cause, corrupt its telemetry on purpose, and grade whether the agent abstains when it should and commits when it should.

## Status

All core pieces are in place: data model, corruption injectors, the LangGraph agent adapter, the rule-based grader, the scenario suite, the `ltf` CLI runner, and a guardrail layer that closes the reference agent's `delay` blind spot. Docs/contribution polish is next — see the roadmap below.

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

**`examples/rca_agent.py`** is a small, offline, rule-based reference agent (two LangGraph nodes: `analyze` → `decide`) used to dogfood the injectors — no LLM calls or API keys needed. It works like a runbook-driven RCA tool: a table of known metric signatures, each mapped to the cause it usually indicates.

Two limitations are deliberate:

1. **No timestamp sanity check** — it counts how many matching points survived, never how stale they are, so severe `delay` corruption yields the same confident answer as clean data. This is the overconfidence failure mode the whole project exists to catch.
2. **No log correlation** — it reads metrics only, so it can't distinguish the two scenarios that both spike `error_rate` and necessarily gets one wrong.

See `tests/test_rca_agent.py` for both behaviors demonstrated against real corrupted telemetry.

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

Every `Grade` records *how* it matched via `match_method` (`exact`, `alias`, or `judge`), and the report surfaces the alias- and judge-matched counts, so a reader can discount passes that only cleared the bar because a scenario author was generous with phrasings — or because a model said so.

### LLM judge (opt-in, never in CI)

When exact and alias matching both miss, an optional LLM judge can be consulted as a **third tier**:

```bash
pip install -e ".[judge]"
ltf run --agent your.agent:build_graph --judge
```

It is deliberately a fallback, not a replacement. The deterministic checks run first, so the judge only ever sees the handful of claims they rejected — that bounds cost and keeps every other run reproducible. It also only affects **root-cause matching**, never the grounding decision: a judge that agreed with everything still could not turn a hallucination into a pass.

**Don't enable it in CI.** It costs API calls, it isn't deterministic, and — most importantly — it introduces a second model whose own failure modes contaminate the measurement. A lenient judge quietly inflates the score of the exact harness built to catch overconfidence. Judge-matched passes are tagged `MatchMethod.JUDGE` and called out in the report so they can be discounted, and the judge fails closed: a refusal or an unparseable reply counts as *no match*, never as agreement.

```python
from langgraph_telemetry_fuzzer import grade

result = grade(scenario, spec, verdict)
print(result.outcome, result.passed, result.reason)
```

Grounding is always rule-based — because `AgentVerdict` is a fixed shape, deciding whether the agent should have committed or abstained is just comparing a few fields, with no free-text interpretation and no model in the loop. (Root-cause *matching* has an opt-in LLM fallback; see below.) See `tests/test_grader_integration.py` for the full pipeline (scenario → corrupt → real agent → grade) run end to end, including the naive `rca_agent`'s `delay` blind spot caught as an actual `HALLUCINATION` grade.

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
- `--judge` / `--judge-model` opt in to the LLM judge described above (off by default).

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

### What the reference agent actually scores

Running that command reports roughly **32% grounding, 77% accuracy** — and the shape of that result is the most useful thing in this repo.

The per-axis table makes the diagnosis legible:

| Axis | Pass rate | Why |
| --- | --- | --- |
| `delay` (all severities) | 0% | Timestamps are skewed, but counts and values are untouched — so the agent answers exactly as confidently as it would on clean data. This is its documented blind spot, reproduced 18 times over. |
| `drift` severe | 100% | Every metric is renamed, the agent finds nothing it recognizes, and abstains. |
| `truncate` severe | 100% | Only 15% of the window survives, dropping below `MIN_POINTS`, so it abstains. |
| `drift`/`truncate` mild–moderate | 0% | Enough points survive to clear `MIN_POINTS`, so it commits anyway. |
| clean | 83% | The one miss is `deployment-regression`: distinguishing it from `checkout-error-spike` needs the deploy marker in the logs, and this agent reads metrics only. |

Note the pattern: the agent abstains only when it *cannot see data at all*, never because it judged the data untrustworthy. Those are very different behaviors that look identical from the outside until you corrupt the input in a way that degrades trustworthiness without degrading volume — which is exactly what the `delay` injector does.

## Guardrail layer

The reference agent's worst axis is `delay`: **0% grounding at every
severity**, because it counts surviving datapoints but never inspects
timestamps. `guardrail.py` closes that gap by computing trust signals from
the telemetry itself, before any reasoning happens.

### The no-ground-truth constraint

`compute_trust_metadata(telemetry, query_time, expected_interval_seconds)`
sees **only** the possibly-corrupted `Telemetry` and a clock. It never
receives the `CorruptionSpec`, `true_root_cause`, or `tolerant_up_to` —
exactly like a production guardrail, which never learns which corruption
(if any) its data went through. A guardrail allowed to read the spec would
score perfectly and measure nothing.

`query_time` is exogenous: it says *when the question was asked*, not what
was done to the data. The MCP server supplies the scenario's own incident
window end, which is the faithful stand-in for "now".

### Detection logic

Three deliberately orthogonal signals:

| Signal | Catches | How |
|---|---|---|
| `completeness` | `missing` | Observed points vs. what each series' own span implies at the expected interval |
| `monotonic` | `delay` | Timestamps non-decreasing **as delivered**, checked **per series** |
| `staleness_seconds` | `truncate` | Gap between `query_time` and the newest point; negative means future-dated |

`confidence` is `"low"` if completeness is below the floor (0.8), ordering
is broken, or the window is stale; `"high"` otherwise. `reason` records
which checks failed.

Two details in `monotonic` are load-bearing:

- **As-delivered, not sorted.** Sorting first makes the check trivially
  true and detects nothing. The `delay` injector skews timestamps while
  leaving list position intact, so the disagreement between arrival order
  and timestamp order *is* the signal.
- **Per series, not across the flat list.** A bundle carrying two metrics
  concatenated restarts its clock at the boundary, so a flat-list check
  reports a false positive on perfectly clean telemetry.

Staleness scales with the feed's cadence (`3 x expected_interval_seconds`)
rather than an absolute wall-clock figure — a 1Hz feed 17s stale has missed
17 consecutive samples, while a 1/hour feed 17s old is fresh.

### Results

`python scripts/compare_guardrail.py --seed 0`, over `single_axis_matrix`
against `ALL_SCENARIOS`, graded with `grade()` unmodified:

| Variant | clean | missing | delay | drift | truncate | **overall** |
|---|---|---|---|---|---|---|
| `rca_agent` (baseline) | 100% | 33% | **0%** | 33% | 39% | **32%** |
| `rca_agent` + guardrail | 100% | 83% | **100%** | 72% | 94% | **88%** |

| Variant | correct_answer | correct_abstention | hallucination | wrong_answer | over_caution |
|---|---|---|---|---|---|
| baseline | 10 | 12 | 53 | 3 | 0 |
| + guardrail | 10 | 57 | **8** | 2 | 1 |

`delay` goes 0% → 100%. The quality of that matters more than the number:
`correct_answer` stays at 10 and `over_caution` rises only from 0 to 1, so
45 hallucinations became correct abstentions at the cost of a single false
one. The guardrail is not buying grounding by making the agent timid.

### Does a real LLM honour the signal?

`examples/llm_rca_agent.py` is a tool-calling agent on a real model, run
against the guarded and raw MCP tools. Measured on the `delay` axis over
two scenarios (6 runs each) — a deliberately scoped run, see caveat below:

| Variant | delay grounding | hallucinations |
|---|---|---|
| `llm_rca_agent` + raw | 83% | 1 |
| `llm_rca_agent` + guarded | **100%** | **0** |

Worth reading carefully: the *unguarded* LLM already scores 83%, far above
`rca_agent`'s 0%, because a capable reasoner can notice scrambled
timestamps unaided. The guardrail's value is therefore largest for agents
that cannot self-assess (0% → 100%) and smaller but still real as a
deterministic backstop for ones that can (83% → 100%).

### Known limitation: the fixtures under-determine their own answers

The LLM variants are reported on `delay` only, not the full matrix, because
the scenario fixtures confound the rest. Two observed examples:

- On `checkout-error-spike` the telemetry is a single `error_rate` series
  with no logs or traces. The model abstains, correctly noting that "bad
  deploy, upstream dependency failure, connection pool exhaustion, and
  credential expiry all remain equally consistent with the data" — and is
  graded `OVER_CAUTION`.
- On `disk-saturation` it answers "disk space exhaustion from a
  constant-rate runaway writer (specific writer unidentifiable from
  available telemetry)" — substantively right — and is graded
  `WRONG_ANSWER` against "log directory filling the disk due to disabled
  log rotation", which names the very detail the model correctly said the
  data does not contain.

`rca_agent` scores well on these because its lookup table *is* the answer
key, not because it reasons. A real reasoner is penalised for the honesty
this harness exists to reward. Fixing it means enriching the fixtures so
each `true_root_cause` is actually derivable from its telemetry — out of
scope here, since the scenario suite was to be left unmodified.

### Running it

```bash
pip install -e ".[dev,langgraph,llm,mcp]"

# deterministic variants, no API key needed
python scripts/compare_guardrail.py --variants 1,1g --seed 0

# LLM variants (needs ANTHROPIC_API_KEY); scope to keep cost down
python scripts/compare_guardrail.py --variants 2,3 --axes delay \
    --scenarios cascading-dependency-failure --seed 0 --json-out report.json

# MCP server exposing query_telemetry / query_telemetry_raw
python -m mcp_guardrail.server
```

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
7. ~~Guardrail layer: trust signals that close the `delay` blind spot~~
8. Enrich scenario fixtures so each `true_root_cause` is derivable from its
   own telemetry (see the known limitation under Guardrail layer)
9. Docs and contribution guide

## License

MIT
