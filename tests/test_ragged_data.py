"""Does the guardrail cry wolf on realistically messy telemetry?

Every scenario in the suite -- and every public benchmark available -- is
perfectly regular: even intervals, no gaps, no duplicates. Real ingestion
is not. If `completeness` or `monotonic` fire on data that is merely
ragged rather than corrupted, the guardrail trades hallucination for
over-caution and nets nothing.

These tests synthesize the four ways production data actually goes ragged
and pin down which are tolerated and which are not. Two genuine false
positives are documented here rather than hidden: out-of-order delivery
beyond a sample interval, and mixed-cadence feeds.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest

from langgraph_telemetry_fuzzer import MetricPoint, Telemetry
from langgraph_telemetry_fuzzer.guardrail import compute_trust_metadata

BASE = datetime(2026, 1, 1, 12, 0, 0)
INTERVAL = 1.0
N = 60


def series(offsets: list[float]) -> Telemetry:
    return Telemetry(
        metrics=[
            MetricPoint(timestamp=BASE + timedelta(seconds=o), name="cpu", value=1.0)
            for o in offsets
        ]
    )


def confidence(telemetry: Telemetry, **kwargs) -> str:
    newest = max(m.timestamp for m in telemetry.metrics)
    return compute_trust_metadata(telemetry, newest, INTERVAL, **kwargs).confidence


# -- tolerated: the common kinds of raggedness -------------------------------


@pytest.mark.parametrize("jitter", [0.1, 0.2, 0.3, 0.45, 0.6])
def test_scrape_jitter_is_tolerated(jitter):
    """Collectors rarely fire exactly on the tick. A store returns points in
    timestamp order, so jitter shifts spacing without disturbing sequence.
    """
    rnd = random.Random(0)
    offsets = sorted(i + rnd.uniform(-jitter, jitter) for i in range(N))

    assert confidence(series(offsets)) == "high"


@pytest.mark.parametrize("drop_rate", [0.05, 0.1, 0.2, 0.3])
def test_occasional_failed_scrapes_are_tolerated(drop_rate):
    """Losing up to 30% of scrapes leaves completeness at or above the 0.8
    floor -- it degrades smoothly rather than falling off a cliff.
    """
    rnd = random.Random(0)
    offsets = [float(i) for i in range(N) if rnd.random() > drop_rate]

    assert confidence(series(offsets)) == "high"


@pytest.mark.parametrize("dup_rate", [0.05, 0.2])
def test_duplicate_timestamps_are_tolerated(dup_rate):
    """Retries and double-writes repeat a timestamp. That inflates the count
    without breaking ordering, and completeness is clamped at 1.0.
    """
    rnd = random.Random(0)
    offsets: list[float] = []
    for i in range(N):
        offsets.append(float(i))
        if rnd.random() < dup_rate:
            offsets.append(float(i))

    assert confidence(series(sorted(offsets))) == "high"


# -- not tolerated: documented false positives -------------------------------


def test_out_of_order_delivery_is_flagged_a_known_false_positive():
    """Asynchronous ingestion -- several collectors, partitioned queues --
    can deliver points out of sequence for entirely benign reasons. Beyond
    roughly a sample interval the ordering check cannot tell that from
    clock skew, and flags it.

    This is a real limitation, not a bug: the two are indistinguishable
    from the data alone. `disorder_tolerance_seconds` is the escape hatch.
    """
    rnd = random.Random(0)
    offsets = [i + rnd.uniform(-1.5, 1.5) for i in range(N)]  # arrival order

    assert confidence(series(offsets)) == "low"
    # Declaring the pipeline asynchronous restores trust.
    assert confidence(series(offsets), disorder_tolerance_seconds=4.0) == "high"


def test_disorder_tolerance_still_catches_real_clock_skew():
    """The escape hatch must not blunt the signal it sits next to. Even the
    mildest `delay` severity skews by +/-120s, two orders of magnitude past
    any plausible arrival jitter.
    """
    rnd = random.Random(0)
    skewed = [i + rnd.uniform(-120, 120) for i in range(N)]

    assert confidence(series(skewed), disorder_tolerance_seconds=4.0) == "low"


def test_mixed_cadence_is_flagged_a_known_false_positive():
    """A feed that samples every 60s normally and every 1s during an
    incident has no single `expected_interval_seconds`. Declaring 1.0 makes
    the quiet stretches look overwhelmingly incomplete.

    Per-series interval inference would fix this; declaring the interval
    per feed is the current workaround.
    """
    offsets = (
        [float(i * 60) for i in range(20)]
        + [1200.0 + i for i in range(60)]
        + [1260.0 + i * 60 for i in range(20)]
    )

    assert confidence(series(sorted(offsets))) == "low"


def test_a_long_collector_outage_is_flagged_and_should_be():
    """Not a false positive. A ten-minute hole inside the window is a real
    reason to distrust a conclusion drawn across it.
    """
    offsets = [float(i) for i in range(60)] + [float(660 + i) for i in range(60)]

    assert confidence(series(offsets)) == "low"
