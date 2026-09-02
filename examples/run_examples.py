#!/usr/bin/env python3
"""Run every example envelope and check it reaches its documented verdict.

The manifest below is the documentation. Each row names a file, the decision
the contract should return, and the rule that should produce it. If an example
starts returning something else, this script fails --- which is the point: a
README that drifts from the code is worse than no README, and the examples are
the part of a repository people actually read.

Run with ``make examples`` or ``python examples/run_examples.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spancontract import Plant, SpanEnvelope, SpanGraph, Stitch, validate  # noqa: E402

#: (file, expected decision, expected rule ids, what the example is for)
MANIFEST: Tuple[Tuple[str, str, Tuple[str, ...], str], ...] = (
    (
        "hall-local-training.json", "local", (),
        "The default posture. Training stays in one hall and no circuit rule applies.",
    ),
    (
        "campus-stitch-pipeline.json", "span", (),
        "The case the contract exists to permit: a pipeline cut across a short "
        "campus stitch, measured, fresh, and inside every plant limit.",
    ),
    (
        "long-haul-training-too-far.json", "deny", ("LR1",),
        "Synchronous training across 300 km of amplified fibre. The distance, not the "
        "bandwidth, is what refuses it: the circuit is 800G and in perfect health. "
        "Compare with campus-stitch-pipeline.json, which differs only in length.",
    ),
    (
        "tensor-parallel-across-glass.json", "shrink", ("LR2",),
        "A tensor-parallel cut across a stitch. No circuit width rescues it, so the "
        "contract asks for a different cut rather than a bigger pipe.",
    ),
    (
        "dark-controller.json", "deny", ("FC1",),
        "Fail-closed condition one. The circuit controller did not answer, so the "
        "state of the stitch is unknown, and unknown is not healthy.",
    ),
    (
        "stale-measurement.json", "deny", ("FC2",),
        "Fail-closed condition two. The path was measured two hours ago. A declared "
        "topology is a claim; only a fresh measurement is an observation.",
    ),
    (
        "recompiled-elsewhere.json", "deny", ("FC3",),
        "Fail-closed condition three. The compiled plan was keyed on a different "
        "placement, so running it would execute a binary built for another topology.",
    ),
    (
        "degraded-fibre.json", "deny", ("CH1",),
        "The path is measurably worse than the loss budget. Nothing about the job is "
        "wrong; the glass is.",
    ),
    (
        "two-hall-blast-radius.json", "escalate", ("GV1",),
        "One circuit failure would stop the job in both halls. The envelope declares "
        "that honestly, so the plant cross-check clears and the governance limit is "
        "what stops it --- the specification's own example of a human decision.",
    ),
    (
        "unattended-training.json", "escalate", ("GV2",),
        "A production training stitch requested at L3. Section 4.1 caps these at "
        "L0/L1, so the contract stops and asks.",
    ),
    (
        "checkpoint-outlives-ride-through.json", "shrink", ("PL1",),
        "The checkpoint takes longer to write than the hall can ride through a power "
        "event, so a badly timed event leaves nothing usable.",
    ),
)


def main() -> int:
    directory = Path(__file__).resolve().parent
    plant_file = directory / "plant.json"
    plant_spec = json.loads(plant_file.read_text())
    plant = Plant(
        graph=SpanGraph(
            frozenset(plant_spec["halls"]),
            tuple(Stitch(s["stitch_id"], frozenset(s["halls"]))
                  for s in plant_spec["stitches"]),
        ),
        job_halls=tuple(plant_spec["job_halls"]),
        anchor=plant_spec["anchor"],
        current_topology_hash=plant_spec["current_topology_hash"],
    )

    width = max(len(name) for name, *_ in MANIFEST)
    failures = 0
    print("example envelopes\n" + "=" * (width + 24))
    for name, expected, expected_rules, why in MANIFEST:
        env = SpanEnvelope.from_dict(json.loads((directory / name).read_text()))
        # The plant is supplied only where the example is about the plant; the
        # rest run bare so the reader sees the rule in isolation.
        verdict = validate(env, plant=plant if name == "two-hall-blast-radius.json" else None)
        actual_rules = tuple(sorted(f.rule_id for f in verdict.findings))
        ok = verdict.decision.value == expected and actual_rules == tuple(sorted(expected_rules))
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {verdict.decision.value.upper()}"
              f"  {', '.join(actual_rules) or '-'}")
        print(f"        {why}")
        if not ok:
            print(f"        expected {expected.upper()} from {expected_rules or '-'}")

    print(f"\n{len(MANIFEST) - failures} of {len(MANIFEST)} examples reach their "
          "documented verdict")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
