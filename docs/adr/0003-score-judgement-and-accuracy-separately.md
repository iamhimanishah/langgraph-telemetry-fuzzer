# 3. Score judgement and accuracy separately

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

The first grader returned pass/fail. An agent passed if it named the
right cause when the data supported one, and abstained when it didn't.

That collapses two unrelated questions onto one axis:

1. **Judgement** — was the decision to commit or abstain calibrated to
   how much signal was actually there?
2. **Accuracy** — was the named cause correct?

They fail for different reasons and mean different things. An agent that
reads good telemetry and names the wrong cause has a knowledge problem.
An agent that reads ruined telemetry and confidently names *any* cause
has a judgement problem — and only the second is what this project
exists to catch.

The conflation produced a concrete absurdity. An agent would reason
correctly from good data, say "connection pool exhaustion" where the
fixture said "database connection pool exhausted", and score `FAIL` —
dragging down the exact metric the harness is meant to measure, because
of a phrasing mismatch that has nothing to do with judgement.

## Decision

Grade every run into one of **five outcomes**, and report **two scores**.

| Outcome | Committed? | Data supported it? | Sound? |
|---|---|---|---|
| `CORRECT_ANSWER` | yes | yes | sound |
| `WRONG_ANSWER` | yes | yes | sound |
| `CORRECT_ABSTENTION` | no | no | sound |
| `HALLUCINATION` | yes | **no** | **unsound** |
| `OVER_CAUTION` | no | **yes** | **unsound** |

- **`grounding_score()`** is the headline: everything except
  `HALLUCINATION` and `OVER_CAUTION`. It measures judgement only.
- **`accuracy_rate()`** measures correctness, over committed answers
  only.
- `pass_rate()` remains the strict both-must-hold number.

`ltf run --fail-on {grounding,strict}` gates the exit code, defaulting
to `grounding` so phrasing noise cannot fail a CI run.

Note that `WRONG_ANSWER` counts as **sound**. That is deliberate and it
is the whole idea: being wrong from good data is a normal, respectable
failure. Being confident from unusable data is not.

## Consequences

The two scores move independently, which is the point — you can see a
guardrail lift grounding from 32% to 96% while accuracy stays flat,
and correctly read that as "it learned when to shut up", not "it got
smarter."

`OVER_CAUTION` being counted as unsound is what keeps the harness
honest in the other direction. Without it, the winning strategy is an
agent that abstains unconditionally. Every guardrail change in this
repo reports both hallucinations *and* over-caution for that reason.

The cost is that the report is harder to skim. There is no single number
to put on a badge, and users have twice as much to read.

An early renderer tried to solve that by tagging outcomes with ticks,
producing `WRONG_ANSWER ✅`. Two readers in a row parsed it as "wrong is
good." Ticks are now banned in the report — both verdicts are stated in
words. Presenting two scores means actually presenting two scores.

## Alternatives rejected

**Weighted single score.** Any weighting is a claim about the relative
cost of a wrong answer versus a hallucination, which depends entirely on
the deployment. Publishing the weights as data lets the reader apply
their own.

**Drop accuracy, measure only judgement.** Tempting, since judgement is
the thesis. But an agent can be perfectly calibrated and useless, and
without accuracy nothing in the report would reveal it.

**Fuzzy string matching to fix the phrasing problem.** Treats a grading
defect as a string-similarity problem, and makes every score depend on a
threshold nobody can justify. See [ADR-0004](0004-tiered-root-cause-matching-with-optional-judge.md).
