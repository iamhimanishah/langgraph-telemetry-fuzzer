# 4. Match root causes in tiers, with the LLM judge opt-in and matching-only

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

Separating judgement from accuracy ([ADR-0003](0003-score-judgement-and-accuracy-separately.md))
stopped phrasing mismatches from polluting the grounding score, but it
did not make the accuracy number correct. An agent answering
"connection pool exhaustion" against a fixture labelled "database
connection pool exhausted" is *right*, and exact matching still calls it
wrong.

Two obvious fixes are both traps. Fuzzy string matching makes every
score depend on a similarity threshold nobody can defend. Handing all
grading to an LLM judge makes the eval nondeterministic, costly, and
circular — a language model grading a language model, with no fixed
point to check either against.

## Decision

Match in **three tiers**, stopping at the first hit, and record which
tier fired as `Grade.match_method`.

1. **Exact** — case- and whitespace-insensitive against
   `true_root_cause`.
2. **Alias** — the same exact comparison against
   `Scenario.accepted_root_causes`, a hand-written list of genuine
   restatements. `true_root_cause` is always included automatically.
   Aliases widen *what counts as correct*; they do not make the match
   fuzzy.
3. **Judge** — an LLM, consulted only via `ltf run --judge` (extra:
   `pip install -e ".[judge]"`).

Four constraints on the judge, each with a test behind it:

- **Tiered, not substituted.** The deterministic tiers run first, so the
  judge only ever sees claims they already rejected. This bounds cost
  and keeps every other run reproducible.
- **Matching only.** The judge cannot touch the grounding decision. A
  judge that agreed with literally everything still could not turn a
  `HALLUCINATION` into a pass. There is a test asserting exactly that.
- **Fails closed.** A safety refusal, a timeout, or an unparseable reply
  counts as *no match* — never as agreement.
- **Never a CI default.** Off unless asked for, and judge-matched passes
  are tagged `MatchMethod.JUDGE` and called out in the report so readers
  can discount them.

## Consequences

Default runs stay fully deterministic and free. The judge is a debugging
aid for "is my agent actually wrong, or just phrased differently?", not
part of the standard measurement.

Because `match_method` is recorded per grade, a skeptical reader can
recompute the accuracy score while ignoring every alias- or
judge-matched pass. The generosity of the matching is visible data
rather than a hidden assumption.

Confining the judge to matching is what makes it safe to include at all.
The grounding score — the number this project exists to produce — is
untouchable by the LLM, so the headline metric cannot drift with a model
version.

The cost is a real maintenance burden on alias lists, and a standing
temptation to abuse them. `accepted_root_causes` is one edit away from
"paste in whatever the agent said", which would inflate every score
that follows. [CONTRIBUTING.md](../../CONTRIBUTING.md) makes that an
explicit rule: aliases must be genuine restatements of the same cause,
and accepting "database is slow" for "connection pool exhaustion" is
prohibited.

Enrichment and matching also stayed separate concerns, which took a
round of confusion to see. When fixtures encoded causes their own data
could not support ([ADR-0008](0008-scenario-causes-must-be-derivable.md)),
no amount of alias or judge tiering could fix it — the agent's abstention
was correct, and nothing was there to match.

## Alternatives rejected

**Fuzzy/embedding similarity.** Converts a grading question into a
threshold nobody can justify, and quietly accepts near-miss causes that
share vocabulary while naming different failures.

**LLM judge as the only matcher.** Nondeterministic, costs money on
every run, and re-grades the whole suite when the model changes.

**Aliases only, no judge.** Nearly right — it covers most cases and
stays deterministic. But it silently caps what the harness can tell you
about a genuinely novel phrasing, and diagnosing that case by hand is
exactly the toil the judge tier removes.
