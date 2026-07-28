from langgraph_telemetry_fuzzer import Severity
from scenarios.matrix import AXES, NON_CLEAN_SEVERITIES, single_axis_matrix


def test_matrix_size_is_one_clean_plus_axes_times_severities():
    specs = single_axis_matrix()
    assert len(specs) == 1 + len(AXES) * len(NON_CLEAN_SEVERITIES)


def test_first_spec_is_the_clean_baseline():
    specs = single_axis_matrix()
    clean = specs[0]

    assert all(getattr(clean, axis) == Severity.NONE for axis in AXES)


def test_every_axis_severity_pair_appears_exactly_once():
    specs = single_axis_matrix()
    non_clean = specs[1:]

    seen = set()
    for spec in non_clean:
        touched = [axis for axis in AXES if getattr(spec, axis) != Severity.NONE]
        assert len(touched) == 1, "each non-clean spec should corrupt exactly one axis"
        axis = touched[0]
        severity = getattr(spec, axis)
        seen.add((axis, severity))

    expected = {(axis, severity) for axis in AXES for severity in NON_CLEAN_SEVERITIES}
    assert seen == expected


def test_seed_propagates_to_every_spec():
    specs = single_axis_matrix(seed=99)
    assert all(spec.seed == 99 for spec in specs)
