from scenarios import ALL_SCENARIOS


def test_suite_has_at_least_five_scenarios():
    assert len(ALL_SCENARIOS) >= 5


def test_scenario_ids_are_unique():
    ids = [scenario.id for scenario in ALL_SCENARIOS]
    assert len(ids) == len(set(ids))


def test_every_scenario_has_telemetry_and_a_root_cause():
    for scenario in ALL_SCENARIOS:
        assert len(scenario.telemetry.metrics) > 0
        assert scenario.true_root_cause.strip() != ""
        assert scenario.description.strip() != ""


def test_every_scenario_has_a_distinct_root_cause():
    # checkout-error-spike and deployment-regression legitimately share a
    # metric name (error_rate) -- what makes them distinct failure
    # signatures is the correlated log evidence, not the metric name alone.
    root_causes = [scenario.true_root_cause for scenario in ALL_SCENARIOS]
    assert len(root_causes) == len(set(root_causes))
