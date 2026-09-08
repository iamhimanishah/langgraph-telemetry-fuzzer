# 8. Scenario causes must be derivable from their own telemetry

- **Status:** Accepted
- **Date:** 2026-08-05

## Context

Running the suite against a real LLM agent surfaced something the
rule-based agent had concealed for weeks.

`checkout-error-spike` shipped twenty points of `error_rate`, no logs,
and claimed a `true_root_cause` of **"downstream payment API timeout"**.
Nothing in twenty numbers identifies *payment*. The cause was not
derivable from the data; it existed only in the label.

The grading consequence is perverse. A reasoning agent looks at the
data, correctly concludes it cannot identify the failing component,
abstains — and is graded `OVER_CAUTION`. Meanwhile the rule-based
`rca_agent` scores well, because its lookup table *is* the answer key.

The suite was rewarding a hardcoded answer and punishing honest
reasoning. Any measurement built on it would have been backwards, and
the LLM's "failure" was actually the most correct behaviour in the repo.

## Decision

**A scenario's `true_root_cause` must be reachable from its own
telemetry, by someone who has not seen the label.** Rule 2 in
[CONTRIBUTING.md](../../CONTRIBUTING.md).

All six scenarios were enriched with corroborating evidence and a log
stream naming the failing component: payment-api latency leading the
error step with 504s; heap growth and GC pauses under the latency ramp;
pool connections draining to zero before the cascade; `log_dir_bytes`
plus logrotate reporting rotation disabled; a deploy marker preceding
the regression; a named third-party provider returning intermittent
503s.

Two conventions keep this compatible with the guardrail:

**Every series stays dense at 1Hz.** Completeness compares observed
points against each series' own span, so a sparse event stream — two
entries across a 20-second window — reads as **55% complete** and would
flag clean telemetry as untrustworthy. Event-shaped facts (a deploy
marker, a rotation warning) therefore ride inside a per-second log
stream rather than being emitted only when they occur.

**Corroborating metrics lead their symptom.** The cause appears in the
data *before* the effect, so `delay` corruption has real causal
structure to destroy rather than just noise to add. A scenario with no
temporal ordering is not testing the `delay` axis at all.

The review question for any new scenario: *if I deleted the label, could
a competent engineer recover it from this data?*

## Consequences

Measured on clean telemetry with the unguarded LLM agent:
`checkout-error-spike` went from abstaining to naming the payment-api
timeout, and `disk-saturation` from "specific writer unidentifiable" to
naming the disabled rotation on `/var/log/app`.

Guardrail numbers shifted 95% → 96%, hallucinations 3 → 1, over-caution
1 → 2. The baseline stayed at 32% because `rca_agent`'s rule table does
not match the new series — which is the correct outcome. A lookup table
should not benefit from the data becoming more informative.

Derivability and matching are separate concerns, and this is where that
became clear. Both enriched answers are substantively right but worded
differently, so exact matching still called them wrong; with `--judge`
both grade `CORRECT_ANSWER`. Enrichment fixed *derivability*, which the
alias and judge tiers of
[ADR-0004](0004-tiered-root-cause-matching-with-optional-judge.md) could
not have fixed — there was nothing to match against.

The density convention is a real coupling between fixture shape and
guardrail design. If you change one, check the other;
`test_every_bundled_scenario_is_trusted_when_clean` is the guard.

The cost is that scenarios are now substantially more work to write. A
fixture is no longer a curve and a label — it is a small, internally
consistent incident. That is the right price, but it is a price.

There is also a limit worth naming: derivability is enforced by review,
not by a test. Nothing mechanically proves a cause is recoverable from
its data. The rule is only as good as the person applying it.

## Alternatives rejected

**Weaken the grader so abstention isn't penalised.** Hides the defect
and destroys `OVER_CAUTION`, which is what stops "abstain always" from
being the winning strategy ([ADR-0003](0003-score-judgement-and-accuracy-separately.md)).

**Keep the thin fixtures and treat them as an abstention test.** They
would have been reasonable as such, if labelled that way. But they were
labelled with causes and graded as answerable, which is the opposite.

**Emit event-shaped facts only when they occur.** The natural data
model, and it reads as 55% complete. Rejected in favour of dense log
streams — see the density convention above.
