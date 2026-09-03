#!/usr/bin/env python3
"""Run every example envelope and check it reaches its documented verdict.

The manifest below is the documentation. Each row names a file, the decision
the contract should return, and the rule that should produce it. If an example
starts returning something else, this script fails --- which is the point: a
README that drifts from the code is worse than no README, and the examples are
the part of a repository people actually read.

A row may also name the gaps the example exists to show: the ``not_checked``
lines a verdict carries when the envelope declared less than the contract can
check. The runner prints them and fails if one goes missing, because a gap
that stops being printed is a check that quietly started being skipped.

Run with ``make examples`` or ``python examples/run_examples.py``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spancontract import Plant, SpanEnvelope, SpanGraph, Stitch, validate  # noqa: E402


@dataclass(frozen=True)
class Example:
    file: str
    #: The decision the contract should return.
    decision: str
    #: The rules that should produce it. Empty when the job is admitted.
    rule_ids: Tuple[str, ...]
    #: What the example is for.
    why: str
    #: Prefixes of the ``not_checked`` lines the example exists to show.
    gaps: Tuple[str, ...] = ()


MANIFEST: Tuple[Example, ...] = (
    Example(
        "hall-local-training.json", "local", (),
        "The default posture. Training stays in one hall and no circuit rule applies.",
    ),
    Example(
        "campus-stitch-pipeline.json", "span", (),
        "The case the contract exists to permit: a pipeline cut across a short "
        "campus stitch, measured, fresh, and inside every plant limit.",
    ),
    Example(
        "long-haul-training-too-far.json", "deny", ("LR1",),
        "Synchronous training across 300 km of amplified fibre. The distance, not the "
        "bandwidth, is what refuses it: the circuit is 800G and in perfect health. "
        "Compare with campus-stitch-pipeline.json, which differs only in length.",
    ),
    Example(
        "tensor-parallel-across-glass.json", "shrink", ("LR2",),
        "A tensor-parallel cut across a stitch. No circuit width rescues it, so the "
        "contract asks for a different cut rather than a bigger pipe.",
    ),
    Example(
        "dark-controller.json", "deny", ("FC1",),
        "Fail-closed condition one. The circuit controller did not answer, so the "
        "state of the stitch is unknown, and unknown is not healthy.",
    ),
    Example(
        "stale-measurement.json", "deny", ("FC2",),
        "Fail-closed condition two. The path was measured two hours ago. A declared "
        "topology is a claim; only a fresh measurement is an observation.",
    ),
    Example(
        "recompiled-elsewhere.json", "deny", ("FC3",),
        "Fail-closed condition three. The compiled plan was keyed on a different "
        "placement, so running it would execute a binary built for another topology.",
    ),
    Example(
        "degraded-fibre.json", "deny", ("CH1",),
        "The path is measurably worse than the loss budget. Nothing about the job is "
        "wrong; the glass is.",
    ),
    Example(
        "two-hall-blast-radius.json", "escalate", ("GV1",),
        "One circuit failure would stop the job in both halls. The envelope declares "
        "that honestly, so the plant cross-check clears and the governance limit is "
        "what stops it --- the specification's own example of a human decision.",
    ),
    Example(
        "unattended-training.json", "escalate", ("GV2",),
        "A production training stitch requested at L3. Section 4.1 caps these at "
        "L0/L1, so the contract stops and asks.",
    ),
    Example(
        "checkpoint-outlives-ride-through.json", "shrink", ("PL1",),
        "The checkpoint takes longer to write than the hall can ride through a power "
        "event, so a badly timed event leaves nothing usable.",
    ),
    Example(
        "org-over-quota.json", "deny", ("TN1",),
        "Tenant predicate one. The organization already holds every slice it may hold "
        "in hall-a, so its next slice is refused at admission rather than discovered "
        "by the slice packer once the circuit is up. The quota is declared on the "
        "envelope, not fetched: the contract stays inert.",
    ),
    Example(
        "lambda-shared-with-another-org.json", "deny", ("TN2",),
        "The wavelength this stitch would use already carries another organization's "
        "job. Isolation on a raw inter-chip mesh is geometry and optics, so two "
        "organizations on one wavelength are two tenants with nothing between them.",
    ),
    Example(
        "dedicated-wavelength-already-shared.json", "deny", ("TN3",),
        "A job that asked for a dedicated wavelength, and a wavelength that already "
        "carries its own organization's other job. Same owner is not the same as alone.",
    ),
    Example(
        "must-not-share-with.json", "deny", ("TN4",),
        "The specification's sentence to the letter: this job may not share a "
        "wavelength with that job. The other job is the organization's own, and the "
        "ban holds anyway.",
    ),
    Example(
        "tenancy-taken-on-trust.json", "span", (),
        "The campus stitch again with no tenancy block at all. It is admitted, and the "
        "verdict says what it did not check --- the taken-on-trust pattern rather than "
        "a refusal, because an absent declaration is a caller that has not wired its "
        "bookkeeping, not a plant that failed to answer.",
        gaps=("TN1", "TN2-TN4"),
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

    width = max(len(ex.file) for ex in MANIFEST)
    failures = 0
    print("example envelopes\n" + "=" * (width + 24))
    for ex in MANIFEST:
        env = SpanEnvelope.from_dict(json.loads((directory / ex.file).read_text()))
        # The plant is supplied only where the example is about the plant; the
        # rest run bare so the reader sees the rule in isolation.
        verdict = validate(env, plant=plant if ex.file == "two-hall-blast-radius.json" else None)
        actual_rules = tuple(sorted(f.rule_id for f in verdict.findings))
        ok = verdict.decision.value == ex.decision and actual_rules == tuple(sorted(ex.rule_ids))
        # Every declared gap must be printed. A crossing envelope with no
        # tenancy block must list both tenancy gaps whether or not the manifest
        # says so, and no other envelope may have a tenancy check listed as
        # skipped: a declared tenancy leaves none, a hall-local job has none.
        expected = set(ex.gaps)
        if env.tenancy is None and env.spans_halls:
            expected |= {"TN1 ", "TN2-TN4 "}
        shown = []
        for prefix in sorted(expected):
            lines = [n for n in verdict.not_checked if n.startswith(prefix)]
            ok = ok and bool(lines)
            if prefix in ex.gaps:
                shown += lines
        stray = [n for n in verdict.not_checked if n.startswith("TN")
                 and not any(n.startswith(g) for g in expected)]
        ok = ok and not stray
        shown += stray
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {ex.file:<{width}}  {verdict.decision.value.upper()}"
              f"  {', '.join(actual_rules) or '-'}")
        print(f"        {ex.why}")
        for line in shown:
            print(f"        not checked: {line}")
        if not ok:
            print(f"        expected {ex.decision.upper()} from {ex.rule_ids or '-'}"
                  + (f" with gaps {ex.gaps}" if ex.gaps else ""))

    print(f"\n{len(MANIFEST) - failures} of {len(MANIFEST)} examples reach their "
          "documented verdict")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
