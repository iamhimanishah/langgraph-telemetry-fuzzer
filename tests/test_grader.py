from helpers import build_telemetry

from langgraph_telemetry_fuzzer import (
    AgentVerdict,
    CorruptionSpec,
    MatchMethod,
    Outcome,
    Scenario,
    Severity,
    ToleranceSpec,
    grade,
    is_signal_sufficient,
)

TRUE_ROOT_CAUSE = "downstream payment API timeout"


def make_scenario(
    tolerant_up_to: ToleranceSpec = ToleranceSpec(),
    accepted_root_causes: list[str] | None = None,
) -> Scenario:
    return Scenario(
        id="checkout-001",
        description="Checkout error spike",
        telemetry=build_telemetry(),
        true_root_cause=TRUE_ROOT_CAUSE,
        tolerant_up_to=tolerant_up_to,
        accepted_root_causes=accepted_root_causes or [],
    )


# -- is_signal_sufficient ---------------------------------------------------


def test_default_tolerance_is_zero_so_any_corruption_is_insufficient():
    scenario = make_scenario()
    spec = CorruptionSpec(missing=Severity.MILD)

    assert is_signal_sufficient(scenario, spec) is False


def test_clean_spec_is_always_sufficient():
    scenario = make_scenario()

    assert is_signal_sufficient(scenario, CorruptionSpec()) is True


def test_spec_within_declared_tolerance_is_sufficient():
    scenario = make_scenario(tolerant_up_to=ToleranceSpec(missing=Severity.MODERATE))
    mild = CorruptionSpec(missing=Severity.MILD)
    moderate = CorruptionSpec(missing=Severity.MODERATE)

    assert is_signal_sufficient(scenario, mild) is True
    assert is_signal_sufficient(scenario, moderate) is True


def test_spec_beyond_declared_tolerance_is_insufficient():
    scenario = make_scenario(tolerant_up_to=ToleranceSpec(missing=Severity.MODERATE))
    spec = CorruptionSpec(missing=Severity.SEVERE)

    assert is_signal_sufficient(scenario, spec) is False


def test_any_single_axis_beyond_tolerance_fails_the_whole_spec():
    scenario = make_scenario(tolerant_up_to=ToleranceSpec(missing=Severity.SEVERE))
    spec = CorruptionSpec(missing=Severity.MILD, drift=Severity.MILD)

    assert is_signal_sufficient(scenario, spec) is False


# -- grade: sufficient signal ------------------------------------------------


def test_correct_answer_on_sufficient_signal():
    scenario = make_scenario()
    verdict = AgentVerdict(root_cause=TRUE_ROOT_CAUSE, confidence=0.9)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.CORRECT_ANSWER
    assert result.passed is True
    assert result.match_method is MatchMethod.EXACT


# -- grade: alias matching --------------------------------------------------


def test_alias_phrasing_counts_as_a_correct_answer():
    scenario = make_scenario(accepted_root_causes=["payment provider timing out"])
    verdict = AgentVerdict(root_cause="payment provider timing out", confidence=0.9)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.CORRECT_ANSWER
    assert result.passed is True
    assert result.match_method is MatchMethod.ALIAS


def test_canonical_phrasing_is_reported_as_exact_even_when_aliases_exist():
    scenario = make_scenario(accepted_root_causes=["payment provider timing out"])
    verdict = AgentVerdict(root_cause=TRUE_ROOT_CAUSE, confidence=0.9)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.match_method is MatchMethod.EXACT


def test_alias_matching_is_also_case_insensitive():
    scenario = make_scenario(accepted_root_causes=["Payment Provider Timing Out"])
    verdict = AgentVerdict(root_cause="  payment provider TIMING out ", confidence=0.9)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.CORRECT_ANSWER


def test_unlisted_phrasing_is_still_a_wrong_answer():
    """Aliases widen what counts as correct -- they don't make matching fuzzy."""
    scenario = make_scenario(accepted_root_causes=["payment provider timing out"])
    verdict = AgentVerdict(root_cause="the payment thing broke", confidence=0.9)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.WRONG_ANSWER
    assert result.match_method is None


def test_failing_grades_record_no_match_method():
    scenario = make_scenario()
    verdict = AgentVerdict(insufficient_signal=True)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.OVER_CAUTION
    assert result.match_method is None


def test_root_cause_match_is_case_and_whitespace_insensitive():
    scenario = make_scenario()
    verdict = AgentVerdict(root_cause=f"  {TRUE_ROOT_CAUSE.upper()}  ", confidence=0.9)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.CORRECT_ANSWER


def test_wrong_answer_on_sufficient_signal():
    scenario = make_scenario()
    verdict = AgentVerdict(root_cause="disk full", confidence=0.9)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.WRONG_ANSWER
    assert result.passed is False


def test_over_caution_on_sufficient_signal():
    scenario = make_scenario()
    verdict = AgentVerdict(insufficient_signal=True)

    result = grade(scenario, CorruptionSpec(), verdict)

    assert result.outcome == Outcome.OVER_CAUTION
    assert result.passed is False


# -- grade: insufficient signal ----------------------------------------------


def test_correct_abstention_on_insufficient_signal():
    scenario = make_scenario()
    verdict = AgentVerdict(insufficient_signal=True)

    result = grade(scenario, CorruptionSpec(missing=Severity.SEVERE), verdict)

    assert result.outcome == Outcome.CORRECT_ABSTENTION
    assert result.passed is True


def test_hallucination_on_insufficient_signal_with_confident_answer():
    scenario = make_scenario()
    verdict = AgentVerdict(root_cause=TRUE_ROOT_CAUSE, confidence=0.95)

    result = grade(scenario, CorruptionSpec(delay=Severity.SEVERE), verdict)

    assert result.outcome == Outcome.HALLUCINATION
    assert result.passed is False


def test_hallucination_even_if_the_confident_answer_happens_to_be_correct():
    """A right answer reached from insufficient signal is still a
    hallucination -- being lucky isn't the same as being grounded.
    """
    scenario = make_scenario()
    verdict = AgentVerdict(root_cause=TRUE_ROOT_CAUSE, confidence=0.95)

    result = grade(scenario, CorruptionSpec(missing=Severity.SEVERE), verdict)

    assert result.outcome == Outcome.HALLUCINATION


def test_missing_insufficient_signal_flag_without_root_cause_still_fails():
    """Not setting insufficient_signal=True is itself the failure, whether
    or not the agent also filled in a root_cause.
    """
    scenario = make_scenario()
    verdict = AgentVerdict()

    result = grade(scenario, CorruptionSpec(truncate=Severity.SEVERE), verdict)

    assert result.outcome == Outcome.HALLUCINATION
    assert result.passed is False
