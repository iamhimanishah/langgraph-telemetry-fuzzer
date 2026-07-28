"""Judge tests run against a fake client — no API key, no network, no cost."""

from types import SimpleNamespace

import pytest
from helpers import build_telemetry

from langgraph_telemetry_fuzzer import (
    AgentVerdict,
    CorruptionSpec,
    MatchMethod,
    Outcome,
    Scenario,
    Severity,
    grade,
)
from langgraph_telemetry_fuzzer.judge import JudgeDecision, LLMJudge

TRUE_ROOT_CAUSE = "downstream payment API timeout"


def make_scenario(accepted_root_causes: list[str] | None = None) -> Scenario:
    return Scenario(
        id="s1",
        description="test scenario",
        telemetry=build_telemetry(),
        true_root_cause=TRUE_ROOT_CAUSE,
        accepted_root_causes=accepted_root_causes or [],
    )


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return self.response


class FakeClient:
    """Stands in for anthropic.Anthropic — same `.messages.parse` surface."""

    def __init__(self, *, same: bool = True, stop_reason: str = "end_turn"):
        parsed = (
            JudgeDecision(same_root_cause=same, reasoning="test") if same is not None
            else None
        )
        self.messages = FakeMessages(
            SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason)
        )


# -- LLMJudge ---------------------------------------------------------------


def test_judge_returns_true_when_model_says_equivalent():
    judge = LLMJudge(client=FakeClient(same=True))

    assert judge("payment provider timed out", make_scenario()) is True


def test_judge_returns_false_when_model_says_different():
    judge = LLMJudge(client=FakeClient(same=False))

    assert judge("disk full", make_scenario()) is False


def test_judge_sends_both_causes_to_the_model():
    client = FakeClient()
    judge = LLMJudge(client=client)

    judge("payment provider timed out", make_scenario())

    prompt = client.messages.last_kwargs["messages"][0]["content"]
    assert TRUE_ROOT_CAUSE in prompt
    assert "payment provider timed out" in prompt


def test_judge_fails_closed_on_refusal():
    """A safety refusal must not be read as agreement."""
    judge = LLMJudge(client=FakeClient(same=True, stop_reason="refusal"))

    assert judge("anything", make_scenario()) is False


def test_judge_fails_closed_on_unparseable_response():
    judge = LLMJudge(client=FakeClient(same=None))

    assert judge("anything", make_scenario()) is False


def test_judge_counts_its_calls():
    judge = LLMJudge(client=FakeClient())
    scenario = make_scenario()

    judge("a", scenario)
    judge("b", scenario)

    assert judge.calls == 2


def test_judge_without_anthropic_installed_raises_a_helpful_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)

    with pytest.raises(ImportError, match=r'pip install -e ".\[judge\]"'):
        LLMJudge()("anything", make_scenario())


# -- grade() integration ----------------------------------------------------


def test_grade_does_not_consult_the_judge_by_default():
    """The deterministic path must stay deterministic unless opted into."""
    judge = LLMJudge(client=FakeClient(same=True))
    verdict = AgentVerdict(root_cause="a differently worded cause")

    result = grade(make_scenario(), CorruptionSpec(), verdict)

    assert result.outcome == Outcome.WRONG_ANSWER
    assert judge.calls == 0


def test_judge_can_rescue_a_wrong_answer():
    judge = LLMJudge(client=FakeClient(same=True))
    verdict = AgentVerdict(root_cause="the payment provider timed out")

    result = grade(make_scenario(), CorruptionSpec(), verdict, judge=judge)

    assert result.outcome == Outcome.CORRECT_ANSWER
    assert result.match_method is MatchMethod.JUDGE
    assert judge.calls == 1


def test_judge_is_not_consulted_when_exact_match_already_wins():
    """Tiering keeps judge calls bounded to the runs that need them."""
    judge = LLMJudge(client=FakeClient(same=True))
    verdict = AgentVerdict(root_cause=TRUE_ROOT_CAUSE)

    result = grade(make_scenario(), CorruptionSpec(), verdict, judge=judge)

    assert result.match_method is MatchMethod.EXACT
    assert judge.calls == 0


def test_judge_is_not_consulted_when_an_alias_already_wins():
    judge = LLMJudge(client=FakeClient(same=True))
    scenario = make_scenario(accepted_root_causes=["payment provider timing out"])
    verdict = AgentVerdict(root_cause="payment provider timing out")

    result = grade(scenario, CorruptionSpec(), verdict, judge=judge)

    assert result.match_method is MatchMethod.ALIAS
    assert judge.calls == 0


def test_judge_rejection_leaves_the_answer_wrong():
    judge = LLMJudge(client=FakeClient(same=False))
    verdict = AgentVerdict(root_cause="disk full")

    result = grade(make_scenario(), CorruptionSpec(), verdict, judge=judge)

    assert result.outcome == Outcome.WRONG_ANSWER
    assert result.match_method is None


def test_judge_never_affects_the_grounding_decision():
    """A judge that says yes to everything still can't turn a hallucination
    into a pass -- grounding is decided before matching is ever consulted.
    """
    judge = LLMJudge(client=FakeClient(same=True))
    verdict = AgentVerdict(root_cause=TRUE_ROOT_CAUSE, confidence=0.9)
    insufficient = CorruptionSpec(delay=Severity.SEVERE)

    result = grade(make_scenario(), insufficient, verdict, judge=judge)

    assert result.outcome == Outcome.HALLUCINATION
    assert judge.calls == 0
