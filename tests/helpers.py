from datetime import datetime, timedelta

from langgraph_telemetry_fuzzer import LogEntry, MetricPoint, Telemetry

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


def build_telemetry(n_metrics: int = 20, n_logs: int = 10) -> Telemetry:
    """A synthetic incident window: N metric points and N log lines, one
    second apart, so ordering and truncation are easy to reason about.
    """
    return Telemetry(
        metrics=[
            MetricPoint(
                timestamp=BASE_TIME + timedelta(seconds=i),
                name="error_rate",
                value=0.01 * i,
            )
            for i in range(n_metrics)
        ],
        logs=[
            LogEntry(
                timestamp=BASE_TIME + timedelta(seconds=i),
                level="INFO",
                message=f"event {i}",
            )
            for i in range(n_logs)
        ],
    )


def build_spiking_telemetry(n_points: int = 20) -> Telemetry:
    """A synthetic incident window where `error_rate` clearly spikes partway
    through: low and flat for the first half, then a sustained jump above
    the rca_agent example's SPIKE_THRESHOLD (0.5) for the second half.
    """
    return Telemetry(
        metrics=[
            MetricPoint(
                timestamp=BASE_TIME + timedelta(seconds=i),
                name="error_rate",
                value=0.02 if i < n_points // 2 else 0.9,
            )
            for i in range(n_points)
        ]
    )
