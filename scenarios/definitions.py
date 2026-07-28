"""Hand-crafted incident scenarios covering distinct failure signatures.

Each scenario pairs a synthetic telemetry window with a known root cause
and a ToleranceSpec declaring how much corruption, per axis, still leaves
that root cause recoverable. Per the roadmap, these thresholds are
hand-judged from each scenario's actual data shape, not a universal rule --
see the docstring on each one for the reasoning.
"""

from __future__ import annotations

from langgraph_telemetry_fuzzer import Scenario, Severity, Telemetry, ToleranceSpec

from .builders import build_log_series, build_metric_series, bursty, ramp, step

N_POINTS = 20


def checkout_error_spike() -> Scenario:
    """error_rate jumps sharply at the midpoint and stays elevated through
    the rest of the window -- plenty of redundant post-spike signal
    survives moderate data loss.
    """
    values = step(N_POINTS, baseline=0.02, spike=0.9)
    metrics = build_metric_series("error_rate", values)
    return Scenario(
        id="checkout-error-spike",
        description="error_rate spikes and stays elevated from the midpoint onward",
        telemetry=Telemetry(metrics=metrics),
        true_root_cause="downstream payment API timeout",
        tolerant_up_to=ToleranceSpec(missing=Severity.MODERATE),
    )


def api_latency_degradation() -> Scenario:
    """p99_latency_ms climbs steadily rather than spiking -- the signal is
    the *trend*, so even mild truncation (cutting off the worst, latest
    values) can hide how bad it got. Missing individual points is more
    tolerable, since the ramp is still visible from a partial sample.
    """
    metrics = build_metric_series("p99_latency_ms", ramp(N_POINTS, start=120, end=2500))
    return Scenario(
        id="api-latency-degradation",
        description="p99_latency_ms ramps up steadily over the incident window",
        telemetry=Telemetry(metrics=metrics),
        true_root_cause="memory leak causing GC pressure in the application pool",
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD),
    )


def cascading_dependency_failure() -> Scenario:
    """db_latency_ms spikes first; api_error_rate follows a few points
    later. Telling "DB caused API errors" from "API errors happened to
    co-occur with DB latency" depends entirely on which metric moved
    first -- so this scenario declares zero tolerance for timestamp delay.
    """
    db_latency = build_metric_series(
        "db_latency_ms", step(N_POINTS, baseline=15, spike=800, spike_at_fraction=0.3)
    )
    api_error_values = step(N_POINTS, baseline=0.01, spike=0.75, spike_at_fraction=0.45)
    api_errors = build_metric_series("api_error_rate", api_error_values)
    return Scenario(
        id="cascading-dependency-failure",
        description="db_latency_ms spikes, then api_error_rate follows shortly after",
        telemetry=Telemetry(metrics=db_latency + api_errors),
        true_root_cause="database connection pool exhaustion cascading to API layer",
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD),
    )


def disk_saturation() -> Scenario:
    """disk_free_percent declines steadily; the log lines carry the
    specific evidence (ENOSPC) that a metrics-only view wouldn't clearly
    explain. Losing those log lines should break sufficiency even if the
    metric trend survives.
    """
    metrics = build_metric_series("disk_free_percent", ramp(N_POINTS, start=40, end=1))
    log_messages = (
        ["disk usage nominal"] * (N_POINTS - 3)
        + ["WARN: disk usage above 95%"]
        + ["ERROR: ENOSPC: no space left on device"]
        + ["ERROR: write failed"]
    )
    logs = build_log_series(log_messages, level="WARN")
    return Scenario(
        id="disk-saturation",
        description="disk_free_percent declines to near zero, ENOSPC in the logs",
        telemetry=Telemetry(metrics=metrics, logs=logs),
        true_root_cause="log directory filling the disk due to disabled log rotation",
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD, truncate=Severity.MILD),
    )


def deployment_regression() -> Scenario:
    """error_rate steps up right after a deploy marker log line. The
    causal link depends on the deploy log and the metric step lining up
    in time -- delay corruption that reorders them should break
    sufficiency entirely.
    """
    metrics = build_metric_series(
        "error_rate", step(N_POINTS, baseline=0.015, spike=0.6, spike_at_fraction=0.4)
    )
    marker_index = round(N_POINTS * 0.4)
    log_messages = (
        ["heartbeat ok"] * marker_index
        + ["Deployed version 2.4.1"]
        + ["heartbeat ok"] * (N_POINTS - marker_index - 1)
    )
    logs = build_log_series(log_messages)
    return Scenario(
        id="deployment-regression",
        description="error_rate steps up right after a version 2.4.1 deploy marker",
        telemetry=Telemetry(metrics=metrics, logs=logs),
        true_root_cause="regression introduced in the version 2.4.1 deploy",
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD),
    )


def third_party_outage() -> Scenario:
    """upstream_success_rate is bursty/intermittent rather than a clean
    step -- realistic for a flaky third-party dependency. The noisy
    baseline means even mild data loss can hide the pattern, so this is
    the least tolerant scenario in the suite.
    """
    metrics = build_metric_series(
        "upstream_success_rate", bursty(N_POINTS, baseline=0.98, burst=0.4, seed=7)
    )
    return Scenario(
        id="third-party-outage",
        description="upstream_success_rate drops intermittently, not cleanly",
        telemetry=Telemetry(metrics=metrics),
        true_root_cause="intermittent outage at a third-party upstream API",
        tolerant_up_to=ToleranceSpec(),  # noisy signal is fragile by nature
    )


ALL_SCENARIOS: list[Scenario] = [
    checkout_error_spike(),
    api_latency_degradation(),
    cascading_dependency_failure(),
    disk_saturation(),
    deployment_regression(),
    third_party_outage(),
]
