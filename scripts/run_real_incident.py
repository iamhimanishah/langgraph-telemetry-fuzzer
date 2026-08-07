"""Run one real, labelled incident end to end through the harness.

Data: RCAEval RE1-OB (Zenodo 14590730) -- Google's Online Boutique demo
under controlled fault injection. Each case directory is named
`<service>_<fault>`, which is the ground-truth root cause, and
`inject_time.txt` records when the fault started.

This is the whole pipeline on real telemetry rather than fixtures:

    real CSV -> Telemetry -> [corrupt] -> [guardrail] -> agent -> grade

Usage:
  python scripts/run_real_incident.py --data-root /tmp/rcaeval/RE1-OB \\
      --case cartservice_mem --run 1
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph_telemetry_fuzzer import (  # noqa: E402
    CorruptionSpec,
    MetricPoint,
    Scenario,
    Severity,
    Telemetry,
    ToleranceSpec,
    apply_corruptions,
    grade,
)
from langgraph_telemetry_fuzzer.adapter import LangGraphAdapter  # noqa: E402
from langgraph_telemetry_fuzzer.guardrail import (  # noqa: E402
    GuardrailGate,
    window_end,
)

# One sample per DOWNSAMPLE seconds. The raw feed is 1Hz across 50 series --
# 210k points, far more than any agent should be handed. Downsampling is
# time-uniform and keeps every series, so it thins the data without
# choosing which metrics matter.
DOWNSAMPLE_SECONDS = 120

FAULT_WORDS = {
    "cpu": "CPU saturation",
    "mem": "memory saturation",
    "disk": "disk I/O saturation",
    "delay": "injected network latency",
    "loss": "network packet loss",
}


def load_case(case_dir: Path, downsample: int) -> tuple[Telemetry, datetime, str, str]:
    """Reads one run into Telemetry plus its ground truth."""
    service, fault = case_dir.parent.name.rsplit("_", 1)
    rows = list(csv.DictReader((case_dir / "data.csv").open()))
    inject_epoch = int((case_dir / "inject_time.txt").read_text().strip())

    metrics: list[MetricPoint] = []
    for row in rows:
        epoch = int(float(row["time"]))
        if epoch % downsample:
            continue
        stamp = datetime.fromtimestamp(epoch)
        for name, raw in row.items():
            if name == "time" or raw in ("", None):
                continue
            try:
                metrics.append(
                    MetricPoint(timestamp=stamp, name=name, value=float(raw))
                )
            except ValueError:
                continue
    # Series must be contiguous per name for the ordering check to mean
    # anything; CSV rows interleave them.
    metrics.sort(key=lambda m: (m.name, m.timestamp))
    return (
        Telemetry(metrics=metrics),
        datetime.fromtimestamp(inject_epoch),
        service,
        fault,
    )


def build_scenario(
    telemetry: Telemetry, service: str, fault: str, case_id: str
) -> Scenario:
    phrase = FAULT_WORDS.get(fault, fault)
    return Scenario(
        id=case_id,
        description=f"Fault injected into {service} ({fault}) in Online Boutique",
        telemetry=telemetry,
        true_root_cause=f"{phrase} in {service}",
        # Mechanical restatements of the same label -- not tuned to any
        # particular agent's output.
        accepted_root_causes=[
            f"{service} {phrase}",
            f"{service}_{fault}",
            f"{fault} saturation in {service}",
        ],
        tolerant_up_to=ToleranceSpec(missing=Severity.MILD),
    )


def describe(label: str, telemetry: Telemetry) -> None:
    series = sorted({m.name for m in telemetry.metrics})
    n = len(telemetry.metrics)
    print(f"  {label:22} {n:6,} points / {len(series)} series")


def main() -> int:
    ap = argparse.ArgumentParser(prog="run_real_incident")
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--case", default="cartservice_mem")
    ap.add_argument("--run", default="1")
    ap.add_argument("--downsample", type=int, default=DOWNSAMPLE_SECONDS)
    ap.add_argument("--agent", default="examples.llm_rca_agent:build_graph")
    ap.add_argument(
        "--corrupt",
        default="delay",
        choices=("none", "missing", "delay", "drift", "truncate"),
    )
    ap.add_argument("--severity", default="severe")
    args = ap.parse_args()

    case_dir = args.data_root / args.case / args.run
    if not case_dir.exists():
        print(f"no such case: {case_dir}", file=sys.stderr)
        return 2

    telemetry, inject_at, service, fault = load_case(case_dir, args.downsample)
    scenario = build_scenario(telemetry, service, fault, f"{args.case}/{args.run}")
    clock = window_end(telemetry)

    print("=" * 68)
    print("STAGE 1  Real incident loaded")
    print("=" * 68)
    print(f"  case                   {args.case}/{args.run}")
    print(f"  ground truth           {scenario.true_root_cause!r}")
    print(f"  fault injected at      {inject_at:%H:%M:%S}")
    describe("telemetry", telemetry)
    print(f"  downsampled to         1 sample / {args.downsample}s")

    from examples.llm_rca_agent import build_graph

    gate = GuardrailGate(expected_interval_seconds=float(args.downsample))

    for label, spec in [
        ("CLEAN", CorruptionSpec(seed=0)),
        (
            f"{args.corrupt.upper()}={args.severity}",
            CorruptionSpec(seed=0, **{args.corrupt: Severity(args.severity)})
            if args.corrupt != "none"
            else CorruptionSpec(seed=0),
        ),
    ]:
        corrupted = apply_corruptions(telemetry, spec)
        trust = gate.evaluate(corrupted, clock)

        print()
        print("=" * 68)
        print(f"STAGE 2  Guardrail on {label} telemetry")
        print("=" * 68)
        describe("after corruption", corrupted)
        print(f"  completeness           {trust.completeness:.2f}")
        print(f"  monotonic              {trust.monotonic}")
        print(f"  staleness_seconds      {trust.staleness_seconds:.0f}")
        print(f"  -> confidence          {trust.confidence.upper()}")
        print(f"  reason                 {trust.reason[:100]}")

        print()
        print(f"STAGE 3  Agent verdict ({label})")
        verdict = LangGraphAdapter(
            build_graph(
                guarded=True,
                query_time=clock,
                expected_interval_seconds=float(args.downsample),
            )
        ).run(corrupted)
        print(f"  abstained              {verdict.insufficient_signal}")
        print(f"  root_cause             {verdict.root_cause!r}")
        print(f"  confidence             {verdict.confidence}")

        print()
        print(f"STAGE 4  Grade ({label})")
        result = grade(scenario, spec, verdict)
        ungrounded = {"hallucination", "over_caution"}
        print(f"  outcome                {result.outcome.value.upper()}")
        print(f"  grounded               {result.outcome.value not in ungrounded}")
        print(f"  reason                 {result.reason[:100]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
