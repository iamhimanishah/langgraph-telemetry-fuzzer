# langgraph-telemetry-fuzzer

**A test for whether your incident-diagnosis agent knows when to shut up.**

## The problem this solves

Your monitoring pipeline hiccups at 3am. Half the datapoints are missing and
timestamps are skewed. Your AI agent still reports *"the payment service timed
out, 90% confident."* Someone pages the payments team. Payments was fine.

This is hard to catch in testing, because agents look great on healthy data.
The failure only appears when the data is degraded — which is exactly when
you are least able to check the answer by hand.

This tool deliberately breaks telemetry — drops datapoints, scrambles
timestamps, renames fields, cuts the window short — and checks whether your
agent says **"I can't tell from this"** or invents an answer anyway.

## What data it accepts

Time-series numbers and log lines. That is the whole input:

```python
from langgraph_telemetry_fuzzer import Telemetry, MetricPoint, LogEntry

Telemetry(
    metrics=[MetricPoint(timestamp=..., name="cpu_percent", value=85.0)],
    logs=[LogEntry(timestamp=..., level="ERROR", message="connection refused")],
)
```

If you can flatten your data into *"at this time, this thing had this value"*
or *"at this time, this line was logged"*, it fits — Prometheus, CloudWatch,
Datadog exports, or a CSV. Converting usually takes about twenty lines; see
`scripts/run_real_incident.py` for a real one.

**What it does not do:** query your monitoring system (you hand it a fixed
window), or anything meaningful with distributed traces.

## The two scores, and why there are two

Every run produces **two separate verdicts**. Keeping them apart is the whole
design, so it is worth thirty seconds.

Think of a doctor reading an X-ray:

| Situation | What the doctor does | Verdict |
|---|---|---|
| Clear X-ray, says "broken tibia" — it was the fibula | Reasonable call, wrong bone | Bad diagnosis, **sound judgement** |
| **Blank X-ray, confidently says "broken tibia"** | Made it up | **Unsound judgement** — this is the dangerous one |
| Blank X-ray, says "I need a rescan" | Refused | **Sound judgement** |

So:

- **Judgement** — did it answer only when the data could support an answer?
  This is the headline. Unsound judgement means the agent cannot be trusted.
- **Accuracy** — when it did answer, was the answer right? A low score here
  means it needs to get smarter, which is a normal, visible, fixable problem.

A wrong answer from good data is a *knowledge* failure. A confident answer
from ruined data is a *judgement* failure. The second is far worse, and only
the second is invisible without a tool like this.

## Quick start

```bash
pip install -e ".[dev,langgraph]"

# Score your agent's judgement: 6 incidents x 13 damage levels = 78 runs
ltf run --agent your_package.your_agent:build_graph

# Add the guardrail: refuse on the agent's behalf when data is untrustworthy
ltf run --agent your_package.your_agent:build_graph --guardrail \
    --expected-interval 1.0 --expected-schema-version 1.0
```

Your agent needs to accept telemetry and return a verdict — see
[Agent adapter](#agent-adapter). Exit code is non-zero if judgement was
unsound anywhere, so it drops into CI.

## Worked example on real data

`scripts/run_real_incident.py` runs one real, labelled incident from
[RCAEval](https://zenodo.org/records/14590730) (Google's Online Boutique under
fault injection) through the whole pipeline. Same incident, twice:

| | Clean data | Same data, timestamps scrambled |
|---|---|---|
| Guardrail | usable | **unusable** — 27% complete, out of order |
| Agent said | *"cartservice memory exhaustion against its 500 MiB container limit"* | *"I can't tell"* |
| Truth | *"memory saturation in cartservice"* | — |
| Judgement | **sound** | **sound** |

The agent found the real cause — including the container limit, which the
label does not even mention. Then, given the same incident with its evidence
destroyed, it refused to repeat the answer it had already found. That refusal
is the product working.

(Scored strictly, run one counts as a wrong answer: the wording differs from
the label. That is the scoring being literal, not the agent being wrong — see
[Matching root causes](#matching-root-causes).)

## Caveats — read before trusting any number here

1. **Test data is unrealistically tidy.** Both public benchmarks I could find
   are pre-cleaned — perfectly even intervals, no gaps, no duplicates. Real
   ingestion is messier. **The completeness check has never met genuinely
   ragged data**, and that is the biggest untested assumption in this repo.
2. **Scoring is literal.** It marks a correct answer wrong when the wording
   differs. Aliases and an optional `--judge` mode soften this, but the raw
   accuracy number understates a good agent.
3. **You must declare your sampling rate.** Get `--expected-interval` wrong
   and the guardrail refuses *everything* while citing convincing-looking
   completeness figures. This bit me during development.
4. **It measures judgement, not expertise.** It will not tell you whether your
   agent is clever. It tells you whether it is honest.
5. **The real-data evidence is one incident.** It demonstrates the mechanism;
   it is not a benchmark result.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). It covers setup and the common
extensions — adding a corruption injector, a scenario, or a trust signal —
plus the five rules that keep the measurements honest, each of which exists
because breaking it produces numbers that look better and mean less.

## Who this is for

Worth your time if you run an agent over observability data and would be
embarrassed by it confidently blaming the wrong service at 3am. The guardrail
is about 150 lines, needs no ground truth, and works in production rather than
only on benchmarks — so it is adoptable on its own even if you skip the
harness.

Not worth your time if you want to measure how *accurate* your RCA agent is.
That is a different question, and this tool deliberately does not answer it.

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

### Judgement vs. accuracy in the report

The report keeps the two verdicts from [The two scores](#the-two-scores-and-why-there-are-two) apart, and never collapses them into a single tick. `--fail-on grounding` (the default) gates CI on judgement alone, so a merely-wrong answer doesn't fail the build while an untrustworthy one does.

The report also breaks results down by corruption type and severity.

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

Four deliberately orthogonal signals, one per corruption axis:

| Signal | Catches | How |
|---|---|---|
| `completeness` | `missing` | Observed points vs. what each series' own span implies at the expected interval |
| `monotonic` | `delay` | Timestamps non-decreasing **as delivered**, checked **per series** |
| `staleness_seconds` | `truncate` | Gap between `query_time` and the newest point; negative means future-dated |
| `schema_match` | `drift` | Declared `schema_version` vs. the one the consumer was built to read |

`confidence` is `"low"` if any check fails, `"high"` otherwise. `reason`
records which ones.

`expected_schema_version`, like `query_time`, is **configuration rather
than ground truth** — a real consumer knows which schema its parsing code
targets, independently of what arrives. Leave it `None` to skip the check.

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
| `rca_agent` + guardrail | 100% | 89% | **100%** | **100%** | 94% | **96%** |

| Variant | correct_answer | correct_abstention | hallucination | wrong_answer | over_caution |
|---|---|---|---|---|---|
| baseline | 10 | 12 | 53 | 3 | 0 |
| + guardrail | 9 | 64 | **1** | 2 | 2 |

`delay` goes 0% → 100% and `drift` 33% → 100%, with hallucinations falling
53 → 1. `over_caution` rises only 0 → 2, so the grounding is not bought by
making the agent uniformly timid.

### Why the remaining axes don't reach 100%

`missing` (83%) and `truncate` (94%) leave four ungrounded runs, and they
are **not** missing signals — they are a global heuristic meeting
per-scenario hand-set tolerances. `third-party-outage` declares zero
tolerance for missing data, but dropping 15% of points leaves completeness
at 0.85, above the 0.8 floor. `disk-saturation` *tolerates*
`truncate=mild`, but the guardrail flags it anyway. The guardrail cannot
reconcile these, because `tolerant_up_to` is ground truth it is forbidden
to read.

Sweeping the thresholds shows the trade-off is irreducible:

| completeness floor | hallucinations | over-caution | grounding |
|---|---|---|---|
| **0.8** (default) | 1 | 2 | 96% |
| 0.9 | 1 | 2 | 96% |
| 0.99 | 1 | 5 | 92% |

Tightening trades hallucinations for over-caution and peaks at 96%. The
default stays at 0.8: the gain is a single run, and choosing a threshold
after seeing which scores best is fitting to this scenario suite rather
than to the problem. Both `completeness_floor` and `staleness_limit_seconds`
are parameters if a caller's cost asymmetry differs.

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

### Fixture derivability

The fixtures originally encoded causes their own telemetry could not
support: `checkout-error-spike` shipped a lone `error_rate` curve while
claiming "downstream payment API timeout". A reasoning agent abstained —
correctly — and was graded `OVER_CAUTION`, while `rca_agent` scored well
only because its lookup table *is* the answer key.

Each scenario now carries corroborating evidence, and the difference is
measurable. On clean telemetry, unguarded, before and after:

| Scenario | Before enrichment | After enrichment |
|---|---|---|
| `checkout-error-spike` | *abstained* — cause not derivable | "Unresponsive **payment-api** upstream dependency causing **30s request timeouts**" |
| `disk-saturation` | "runaway writer (**specific writer unidentifiable**)" | "**Disabled log rotation on /var/log/app** causing unbounded log growth" |

Two conventions make this work with the guardrail: every series stays dense
at 1Hz (a sparse event stream reads as 55% complete and would flag clean
data), and corroborating metrics *lead* the symptom so `delay` has real
causal structure to destroy.

**Derivability and matching are separate problems.** The answers above are
substantively correct but phrased differently from `true_root_cause`, so
exact matching still scores them `WRONG_ANSWER`. That is what the alias and
judge tiers are for — with `--judge`, both grade `CORRECT_ANSWER` tagged
`MatchMethod.JUDGE`. Enrichment fixed derivability; matching was already
handled.

### Using it from the CLI

The guardrail is opt-in on `ltf run`. It gates the agent: when the trust
checks fail it abstains on the agent's behalf, and otherwise hands the
telemetry through untouched.

```bash
ltf run --agent your.agent:build_graph --guardrail \
    --expected-interval 1.0 --expected-schema-version 1.0
```

| Flag | Meaning |
|---|---|
| `--guardrail` | Turn the gate on. Off by default; without it nothing changes. |
| `--expected-interval` | Seconds between samples in your feed. Drives the completeness and staleness checks. Default `1.0`. |
| `--expected-schema-version` | The schema your consumer parses. Omit to skip the schema check. |

Both expectations are **configuration you already have**, not ground truth
— your feed's cadence and the schema your parsing code targets are known
independently of what any given query returns.

Against the bundled reference agent the flag moves grounding from **32% to
96%**, and the report says how many runs it gated:

```
- **Grounding score: 96%**
- Guardrail gated 66 of 78 run(s) before the agent was consulted.
```

Use `--fail-on grounding` (the default) to make an ungrounded run fail CI.

### Running the comparison experiment

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
8. ~~Enrich scenario fixtures so each `true_root_cause` is derivable from its
   own telemetry~~
9. ~~Docs and contribution guide~~ — see [CONTRIBUTING.md](CONTRIBUTING.md)
10. Validate `completeness` against deliberately ragged data (see caveat 1)

## License

MIT
