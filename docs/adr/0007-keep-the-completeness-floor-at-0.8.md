# 7. Keep the completeness floor at 0.8, despite a better-scoring alternative

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

With all four trust signals in place, the guardrail left four ungrounded
runs. The natural next move is to tune `DEFAULT_COMPLETENESS_FLOOR`.

So the thresholds were swept. The result:

- Tightening the floor trades hallucinations for over-caution, roughly
  one for one.
- The curve **peaks at 96%** and then gets worse.
- A floor of **0.9 scored one run higher** than 0.8 on this suite.

There is a free point of grounding score sitting on the table.

## Decision

**Keep the default at 0.8.** Do not take the point.

Choosing a threshold *because it scored highest on the scenario suite*
fits the fixtures rather than the problem. The suite is six scenarios
written by the same person who wrote the guardrail; its quirks are not
the world's quirks. A 0.9 that exists only because 0.9 won a sweep would
be reported as a property of the guardrail when it is really a property
of the fixtures.

0.8 is defensible on its own terms — losing a fifth of a feed is a
reasonable place to stop trusting conclusions drawn from it — and that
is the standard a threshold has to meet.

Both thresholds remain parameters, so anyone with different data can set
their own.

The general rule is now rule 4 in [CONTRIBUTING.md](../../CONTRIBUTING.md):
justify a threshold on its own terms, and *publish the sweep either way*
so readers see the trade-off rather than just the chosen point.

## Consequences

The headline number is 96% rather than the 97% that was available. That
gap is the cost of the decision, and it is the point of the decision.

The sweep is published, so a reader can see both the shape of the
trade-off and the fact that a higher number was declined. That is
strictly more informative than a tuned 97% with no sweep shown.

The remaining ungrounded runs are now understood rather than optimised
away. They are not a missing signal — they are a global heuristic
meeting per-scenario hand-set tolerances. `third-party-outage` tolerates
no missing data at all, but 15% dropped points leaves completeness above
the floor; `disk-saturation` tolerates `truncate=mild` and is flagged
regardless. Closing that gap requires reading `tolerant_up_to`, which is
ground truth and therefore prohibited by
[ADR-0005](0005-the-guardrail-never-sees-ground-truth.md).

There were four such runs when this decision was made. Fixture
enrichment ([ADR-0008](0008-scenario-causes-must-be-derivable.md)) later
took it to three — one hallucination and two over-caution — without the
floor moving. Worth noting because it is the pattern this ADR predicts:
the residue shrank by making the *data* more honest, not by tuning the
threshold against it.

This also establishes that **100% is unreachable by design**, and that
this is a feature. A harness whose reference guardrail scores 100% has
either leaked the answer key or written fixtures too easy to be
informative.

## Alternatives rejected

**Move the floor to 0.9.** One more point, bought by fitting to six
fixtures.

**Per-scenario thresholds.** Would clear the remaining four runs, and is
precisely the prohibited move — a per-scenario threshold *is*
`tolerant_up_to` with a different name.

**Learn the threshold from the data.** Same objection with more
machinery. Fitting to this suite is fitting to this suite whether it is
done by hand or by optimiser.
