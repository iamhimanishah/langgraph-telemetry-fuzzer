"""Optional LLM-backed fallback for matching a claimed root cause against a
scenario's ground truth.

This is deliberately a *fallback*, not a replacement. `grade()` still tries
exact and alias matching first and only consults a judge when both miss, so
the deterministic path stays deterministic and the judge is bounded to the
handful of runs that actually need semantic comparison.

Never enable this in CI by default. A judge introduces a second model whose
own failure modes contaminate the measurement -- a lenient judge quietly
inflates the pass rate of exactly the harness that exists to catch
overconfidence. Grades it produces are tagged MatchMethod.JUDGE so a report
reader can discount them.

Requires the optional extra: pip install -e ".[judge]"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langgraph_telemetry_fuzzer.models import Scenario

DEFAULT_MODEL = "claude-opus-5"

_SYSTEM_PROMPT = """\
You are grading an incident root-cause analysis benchmark.

You will be given the true root cause of an incident and a claim made by an
agent under test. Decide whether the claim identifies the SAME underlying
cause -- not merely a related, adjacent, or downstream one.

Be strict. This benchmark measures whether agents are grounded, so a lenient
judgment corrupts the result it is meant to check:

- Different wording for the same cause is a match.
  "payment API timed out" vs "downstream payment API timeout" -> match.
- A symptom rather than a cause is NOT a match.
  "the API returned errors" for "database connection pool exhaustion" -> no.
- A vaguer statement that merely contains the cause is NOT a match.
  "something in the database" for "connection pool exhaustion" -> no.
- The right component with the wrong failure mode is NOT a match.
  "database is slow" for "connection pool exhaustion" -> no.

When genuinely uncertain, answer false.\
"""


class JudgeDecision(BaseModel):
    """The judge's structured answer."""

    same_root_cause: bool = Field(
        description="True only if the claim names the same underlying cause."
    )
    reasoning: str = Field(description="One sentence explaining the decision.")


class LLMJudge:
    """Callable that asks Claude whether two root-cause statements match.

    Instantiating this does not import `anthropic` until first use is
    attempted, so the harness still imports cleanly without the extra.
    """

    def __init__(self, model: str = DEFAULT_MODEL, client: object | None = None):
        self.model = model
        self._client = client
        self.calls = 0

    def _ensure_client(self) -> object:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on extras
                raise ImportError(
                    "The LLM judge needs the optional 'anthropic' dependency. "
                    'Install it with: pip install -e ".[judge]"'
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def __call__(self, claimed: str, scenario: Scenario) -> bool:
        """Returns True if the judge considers `claimed` the same cause."""
        client = self._ensure_client()
        self.calls += 1

        response = client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"True root cause: {scenario.true_root_cause}\n"
                        f"Agent's claim: {claimed}"
                    ),
                }
            ],
            output_format=JudgeDecision,
        )

        # A safety refusal or an unparseable reply must not silently count as
        # a pass -- fail closed, consistent with the rest of the harness.
        if getattr(response, "stop_reason", None) == "refusal":
            return False
        decision = response.parsed_output
        if decision is None:
            return False
        return decision.same_root_cause
