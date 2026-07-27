from helpers import build_telemetry

from langgraph_telemetry_fuzzer import CorruptionSpec, Severity, apply_corruptions


def test_default_spec_is_a_noop():
    telemetry = build_telemetry()
    corrupted = apply_corruptions(telemetry, CorruptionSpec())

    assert corrupted.model_dump() == telemetry.model_dump()


def test_same_seed_is_reproducible():
    spec = CorruptionSpec(seed=42, missing=Severity.MODERATE, delay=Severity.MILD)

    first = apply_corruptions(build_telemetry(), spec)
    second = apply_corruptions(build_telemetry(), spec)

    assert first.model_dump() == second.model_dump()


def test_different_seeds_diverge():
    telemetry = build_telemetry()
    spec_a = CorruptionSpec(seed=1, missing=Severity.MODERATE)
    spec_b = CorruptionSpec(seed=2, missing=Severity.MODERATE)

    result_a = apply_corruptions(telemetry, spec_a)
    result_b = apply_corruptions(telemetry, spec_b)

    assert result_a.model_dump() != result_b.model_dump()


def test_full_pipeline_combines_all_injectors():
    telemetry = build_telemetry(n_metrics=20, n_logs=20)
    spec = CorruptionSpec(
        seed=0,
        missing=Severity.MILD,
        delay=Severity.MILD,
        drift=Severity.MILD,
        truncate=Severity.MODERATE,
    )

    corrupted = apply_corruptions(telemetry, spec)

    assert corrupted.schema_version != telemetry.schema_version
    assert len(corrupted.metrics) <= round(20 * 0.4)


def test_original_telemetry_is_never_mutated():
    telemetry = build_telemetry()
    original_count = len(telemetry.metrics)
    original_schema = telemetry.schema_version

    apply_corruptions(
        telemetry,
        CorruptionSpec(
            missing=Severity.SEVERE,
            delay=Severity.SEVERE,
            drift=Severity.SEVERE,
            truncate=Severity.SEVERE,
        ),
    )

    assert len(telemetry.metrics) == original_count
    assert telemetry.schema_version == original_schema
