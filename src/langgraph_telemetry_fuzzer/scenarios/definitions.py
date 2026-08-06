"""Hand-crafted incident scenarios covering distinct failure signatures.

Each scenario pairs a synthetic telemetry window with a known root cause
and a ToleranceSpec declaring how much corruption, per axis, still leaves
that root cause recoverable. Per the roadmap, these thresholds are
hand-judged from each scenario's actual data shape, not a universal rule --
see the docstring on each one for the reasoning.

Every fixture aims to be *derivable*: the telemetry carries the evidence a
competent engineer would need to reach `true_root_cause` without being told
it. An earlier revision failed this -- `checkout-error-spike` shipped a lone
`error_rate` curve while claiming "downstream payment API timeout", a cause
no amount of reasoning could extract from twenty numbers. That made the
suite unfair in a specific way: an honest agent abstains and is graded
OVER_CAUTION, while a lookup table that hardcodes the answer scores well
without reasoning at all. Each scenario now carries a corroborating series
and a log stream that names the failing component.

Two conventions keep the fixtures compatible with the guardrail:

- **Every series is dense at 1Hz.** The guardrail's completeness check
  compares observed points against what each series' own span implies, so a
  sparse event stream (two entries across a 20s window) reads as 55%
  complete and would flag clean telemetry as untrustworthy. Event-shaped
  facts -- a deploy marker, a rotation warning -- ride inside a per-second
  log stream instead of being emitted only when they occur.
- **Corroborating metrics lead the symptom.** Where a cause precedes its
  effect in reality, the fixture reflects that ordering, so the `delay`
  injector has real causal structure to destroy.
"""

from __future__ import annotations

from langgraph_telemetry_fuzzer import Scenario, Severity, Telemetry, ToleranceSpec

from .builders import build_log_series, build_metric_series, bursty, ramp, step

N_POINTS = 20


def checkout_error_spike() -> Scenario:
    """error_rate jumps sharply at the midpoint and stays elevated.

    Derivable because `payment_api_latency_ms` saturates one step *before*
    the error rate moves, and the log stream names the upstream and the 504
    status -- so "payment API timeout" is readable off the data rather than
    assumed.

    Plenty of redundant post-spike signal survives moderate data loss.
    """
    errors = build_metric_series("error_rate", step(N_POINTS, baseline=0.02, spike=0.9))
    # Leads the symptom by one sample: cause before effect.
    payment_latency = build_metric_series(
        "payment_api_latency_ms",
        step(N_POINTS, baseline=45.0, spike=30000.0, spike_at_fraction=0.45),
    )
    cutover = round(N_POINTS * 0.45)
    logs = build_log_series(
        ["checkout ok upstream=payment-api status=200"] * cutover
        + [
            "checkout failed upstream=payment-api status=504 "
            "error=gateway_timeout after=30000ms"
        ]
        * (N_POINTS - cutover)
    )
    return Scenario(
        id="checkout-error-spike",
        description="error_rate spikes after payment-api starts timing out",
        telemetry=Telemetry(metrics=errors + payment_latency, logs=logs),
        true_root_cause="downstream payment API timeout",
        tolerant_up_to=ToleranceSpec(missing=Severity.MODERATE),
    )


def api_latency_degradation() -> Scenario:
    """p99_latency_ms climbs steadily rather than spiking.

    Derivable because `heap_used_mb` grows monotonically without ever being
    reclaimed -- the signature of a leak rather than ordinary load -- and
    `gc_pause_ms` grows with it, so the latency is attributable to GC
    pressure rather than to a slow downstream.

    The signal is the *trend*, so truncation that cuts the worst, latest
    values hides how bad it got. Missing individual points is more
    tolerable, since the ramp is still visible from a partial sample.
    """
    latency = build_metric_series("p99_latency_ms", ramp(N_POINTS, start=120, end=2500))
    heap = build_metric_series("heap_used_mb", ramp(N_POINTS, start=410, end=3960))
    gc_pause = build_metric_series("gc_pause_ms", ramp(N_POINTS, start=5, end=900))
    logs = build_log_series(
        [
            f"gc full collection reclaimed=2mb heap_after={410 + i * 187}mb "
            "pool=application"
            for i in range(N_POINTS)
        ],
        level="WARN",
    )
    return Scenario(
        id="api-latency-degradation",
        description="p99_latency_ms ramps as heap grows and GC pauses lengthen",
        telemetry=Telemetry(metrics=latency + heap + gc_pause, logs=logs),
        true_root_cause="memory leak causing GC pressure in the application pool",
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD),
    )


def cascading_dependency_failure() -> Scenario:
    """db_latency_ms spikes first; api_error_rate follows a few points later.

    Derivable because `db_pool_available_connections` drains to zero right
    as the latency climbs, which distinguishes *pool exhaustion*
    specifically from a generically slow database, and the logs report
    waiters queuing on an empty pool.

    Telling "DB caused API errors" from "API errors happened to co-occur
    with DB latency" depends entirely on which metric moved first -- so this
    scenario declares zero tolerance for timestamp delay.
    """
    db_latency = build_metric_series(
        "db_latency_ms", step(N_POINTS, baseline=15, spike=800, spike_at_fraction=0.3)
    )
    api_error_values = step(N_POINTS, baseline=0.01, spike=0.75, spike_at_fraction=0.45)
    api_errors = build_metric_series("api_error_rate", api_error_values)
    # Drains to zero exactly where db latency turns.
    pool_free = build_metric_series(
        "db_pool_available_connections",
        step(N_POINTS, baseline=50, spike=0, spike_at_fraction=0.3),
    )
    cutover = round(N_POINTS * 0.3)
    logs = build_log_series(
        ["db checkout ok pool_available=50/50"] * cutover
        + ["db connection pool exhausted pool_available=0/50 waiters=37 wait_ms=800"]
        * (N_POINTS - cutover),
        level="ERROR",
    )
    return Scenario(
        id="cascading-dependency-failure",
        description="db pool drains to zero, db latency spikes, api errors follow",
        telemetry=Telemetry(metrics=db_latency + api_errors + pool_free, logs=logs),
        true_root_cause="database connection pool exhaustion cascading to API layer",
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD),
    )


def disk_saturation() -> Scenario:
    """disk_free_percent declines steadily to near zero.

    Derivable because `log_dir_bytes` grows in lockstep with the disk
    shrinking -- identifying *which* writer consumes the space -- and the
    log stream reports logrotate skipping the directory because rotation is
    disabled, which supplies the "why".

    Losing the log lines should break sufficiency even if the metric trend
    survives, since the rotation detail lives only there.
    """
    disk_free = build_metric_series(
        "disk_free_percent", ramp(N_POINTS, start=40, end=1)
    )
    log_dir = build_metric_series(
        "log_dir_bytes", ramp(N_POINTS, start=31_000_000_000, end=48_000_000_000)
    )
    logs = build_log_series(
        [
            "logrotate skipped /var/log/app reason=rotation_disabled "
            f"dir_bytes={31_000_000_000 + i * 894_736_842}"
            for i in range(N_POINTS - 3)
        ]
        + [
            "WARN disk usage above 95% mount=/ largest_dir=/var/log/app",
            "ERROR ENOSPC: no space left on device path=/var/log/app/app.log",
            "ERROR write failed path=/var/log/app/app.log errno=28",
        ],
        level="WARN",
    )
    return Scenario(
        id="disk-saturation",
        description="disk_free_percent falls as /var/log/app grows unrotated",
        telemetry=Telemetry(metrics=disk_free + log_dir, logs=logs),
        true_root_cause="log directory filling the disk due to disabled log rotation",
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD, truncate=Severity.MILD),
    )


def deployment_regression() -> Scenario:
    """error_rate steps up right after a deploy marker log line.

    Derivable because `build_version_2_4_1_active` flips from 0 to 1 one
    sample before the errors begin, the deploy is announced in the log
    stream, and the subsequent error lines carry the new version -- so the
    deploy is attributable rather than merely coincident.

    The causal link depends on the deploy and the metric step lining up in
    time, so delay corruption that reorders them breaks sufficiency.
    """
    marker_index = round(N_POINTS * 0.4)
    errors = build_metric_series(
        "error_rate", step(N_POINTS, baseline=0.015, spike=0.6, spike_at_fraction=0.4)
    )
    # Flips one sample before the errors start.
    deployed = build_metric_series(
        "build_version_2_4_1_active",
        step(N_POINTS, baseline=0, spike=1, spike_at_fraction=0.35),
    )
    logs = build_log_series(
        ["heartbeat ok version=2.4.0"] * marker_index
        + ["Deployed version 2.4.1 rollout=complete previous=2.4.0"]
        + [
            "request failed version=2.4.1 handler=checkout error=NullPointerException"
        ]
        * (N_POINTS - marker_index - 1)
    )
    return Scenario(
        id="deployment-regression",
        description="error_rate steps up immediately after the 2.4.1 rollout",
        telemetry=Telemetry(metrics=errors + deployed, logs=logs),
        true_root_cause="regression introduced in the version 2.4.1 deploy",
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD),
    )


def third_party_outage() -> Scenario:
    """upstream_success_rate drops intermittently rather than cleanly.

    Derivable because the log stream names an external provider and reports
    503s from it on exactly the failing samples, and
    `upstream_provider_5xx_rate` moves inversely -- so the failure is
    attributable to a third party rather than to local capacity.

    The noisy baseline means even mild data loss can hide the pattern, so
    this is the least tolerant scenario in the suite.
    """
    success_values = bursty(N_POINTS, baseline=0.98, burst=0.4, seed=7)
    success = build_metric_series("upstream_success_rate", success_values)
    provider_5xx = build_metric_series(
        "upstream_provider_5xx_rate", [round(1.0 - v, 4) for v in success_values]
    )
    logs = build_log_series(
        [
            "upstream call provider=acme-payments-api host=api.acme.io "
            + ("status=503 error=service_unavailable" if v < 0.9 else "status=200")
            for v in success_values
        ],
        level="WARN",
    )
    return Scenario(
        id="third-party-outage",
        description="acme-payments-api returns intermittent 503s, not a clean failure",
        telemetry=Telemetry(metrics=success + provider_5xx, logs=logs),
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
