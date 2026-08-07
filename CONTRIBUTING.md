# Contributing

Thanks for looking. This guide covers the mechanics (setup, tests, style)
and — more importantly — the **five rules** that keep the harness honest.
Those rules are not style preferences. Each one exists because breaking it
silently produces numbers that look better and mean less.

## Setup

```bash
git clone https://github.com/iamhimanishah/langgraph-telemetry-fuzzer
cd langgraph-telemetry-fuzzer
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,langgraph]"

pytest                                      # 137 tests, ~0.3s
ruff check src tests examples scripts mcp_guardrail
```

Python 3.10+. Optional extras: `[llm]` and `[judge]` need an
`ANTHROPIC_API_KEY`; `[mcp]` is only for the MCP server. Everything in the
default test suite runs offline, and CI covers 3.10 and 3.12.

---

## The five rules

### 1. The guardrail never sees ground truth

`compute_trust_metadata()` may read the `Telemetry` and a clock. It may
**not** read `CorruptionSpec`, `true_root_cause`, or `tolerant_up_to`.

A guardrail allowed to see which corruption was applied scores perfectly
and measures nothing. If a new trust signal needs ground truth to work, it
isn't a trust signal — it's the answer key.

The bar for what may be passed in: *would a real consumer know this
independently of the query?* `expected_interval_seconds` and
`expected_schema_version` pass — you know your own feed's cadence and the
schema your parser targets. "Which corruption was applied" does not.

### 2. Scenarios must be derivable

A scenario's `true_root_cause` has to be reachable **from its own
telemetry**, by someone who has not seen the label.

This was violated in an early revision: `checkout-error-spike` shipped a
lone `error_rate` curve while claiming `"downstream payment API timeout"`.
Nothing in twenty numbers identifies *payment*. The result was a suite that
punished honest reasoning — an agent that correctly abstained scored
`OVER_CAUTION`, while a lookup table hardcoding the answer scored well
without reasoning at all.

Before adding a scenario, ask: *if I deleted the label, could a competent
engineer recover it from this data?* If not, add the corroborating metric
or log line that makes it recoverable.

### 3. Every series stays dense

The completeness check compares observed points against what each series'
own time span implies. A sparse event stream — two entries across a
20-second window — reads as **55% complete** and flags clean telemetry as
untrustworthy.

So event-shaped facts (a deploy marker, a rotation warning) ride inside a
per-second log stream rather than being emitted only when they occur. See
`scenarios/definitions.py` for the pattern.

This is a real coupling between fixture shape and guardrail design. If you
change one, check the other — `test_every_bundled_scenario_is_trusted_when_clean`
is the guard.

### 4. Don't tune thresholds after seeing the score

Picking `completeness_floor` because 0.9 scored better than 0.8 on *this*
suite is fitting to the fixtures, not to the problem. The default stays at
0.8 even though a sweep showed 0.9 scoring one run higher, for exactly this
reason.

If you want to change a threshold, justify it on its own terms — "a 1Hz
feed 17s stale has missed 17 consecutive samples" is a reason; "it scores
better" is not. Publish the sweep either way, so readers can see the
trade-off rather than just the chosen point.

Same rule for `accepted_root_causes`. Aliases exist so a
correct-but-differently-worded answer isn't marked wrong. They are **not**
for pasting in whatever your agent happened to say. Aliases must be genuine
restatements of the same cause — accepting "database is slow" for
"connection pool exhaustion" quietly inflates every score that follows.

### 5. Report judgement and accuracy separately

Never collapse them into one pass/fail. A wrong answer from good data is a
knowledge failure; a confident answer from ruined data is a judgement
failure. Only the second is what this project exists to catch.

Concretely: no ticks next to outcome names. An earlier report rendered a
wrong-but-reasonable answer as `WRONG_ANSWER ✅`, which two readers in a row
parsed as "wrong is good". State both verdicts in words.

---

## Common contributions

### Add a corruption injector

Injectors live in `src/langgraph_telemetry_fuzzer/injectors/`. Each is a
module exposing:

```python
def apply(telemetry: Telemetry, severity: Severity, rng: random.Random) -> Telemetry:
    ...
```

Rules: return a **new** `Telemetry` (use `.clone()`), never mutate the
input, take all randomness from `rng` so `seed` stays reproducible, and
return the input unchanged at `Severity.NONE`.

Register it in `compose.py`'s `_PIPELINE`. **Order matters** — `truncate`
slices by timestamp, so it must run after `delay` has already skewed them.

Add the axis to `CorruptionSpec` and to `AXES` in
`scenarios/matrix.py`. Tests should cover: no-op at `NONE`, real
degradation at `SEVERE`, and that the original telemetry is untouched.

### Add a scenario

In `scenarios/definitions.py`. Read rules 2 and 3 first — they are the
whole job. A scenario needs:

- A distinct failure signature (don't duplicate an existing shape)
- Corroborating evidence making the cause derivable
- Dense 1Hz series
- A `tolerant_up_to` reasoned from *that scenario's* data shape, with the
  reasoning in the docstring. A sudden sustained spike survives data loss
  differently than a gradual ramp; a cause that depends on event ordering
  should declare zero tolerance for `delay`.

Append to `ALL_SCENARIOS`. The smoke test runs every scenario against the
full corruption matrix automatically.

### Add a trust signal to the guardrail

In `guardrail.py`. Add the field to `TrustMetadata`, compute it in
`compute_trust_metadata()`, append a human-readable string to `reasons`
when it fails, and add it to `to_dict()`.

Signals should be **orthogonal** — each catching a corruption axis the
others miss. The existing four map one-to-one onto the four injectors.
Before adding one, check whether an existing signal already catches the
case incidentally, and prefer a designed signal over an accidental one:
`drift` sat at 72% for a while, caught only as a side effect of renaming
perturbing completeness, until `schema_match` closed it properly.

Test the false-positive direction too. `test_every_bundled_scenario_is_trusted_when_clean`
matters as much as the detection test — a signal that fires on good data
trades hallucination for over-caution and nets nothing.

### Plug in your own agent

You don't need to modify the harness. Expose a function returning a
compiled LangGraph graph whose state accepts telemetry under `"telemetry"`
and returns a verdict under `"verdict"`:

```bash
ltf run --agent your_package.your_agent:build_graph
```

See `examples/rca_agent.py` (rule-based, offline) and
`examples/llm_rca_agent.py` (real model, tool-calling) for both shapes.

---

## Style

- Ruff enforces `E`, `F`, `I`, `UP` at 88 columns. `ruff check --fix` for
  imports.
- Type hints on public functions. Modern syntax (`X | None`, `list[str]`) —
  the project targets 3.10+.
- Comments explain *why*, not *what*. The codebase leans on module
  docstrings to record reasoning that would otherwise be lost — especially
  where a naive implementation looks correct but isn't (see `_is_monotonic`
  on why sorting first would detect nothing).
- Tests read as claims: `test_monotonic_fires_on_delay_at_every_severity`,
  not `test_monotonic_2`.

## Pull requests

Say what broke and why the fix is right, not just what changed. If you
measured something, include the numbers — and include the ones that didn't
improve. A PR that reports "delay 0% → 100%, but truncate unchanged at 39%
because the staleness limit exceeds the window" is far more useful than one
reporting only the win.

CI runs lint and tests on 3.10 and 3.12; both must pass.

If you find a limitation you can't fix, document it rather than leaving it
implicit. The README's caveats section exists because several such findings
were worth more than the features they qualified — most of all the fact
that every public benchmark available is pre-cleaned, so the completeness
check has never met genuinely ragged data.
