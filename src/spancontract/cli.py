"""``spancontract`` --- validate an envelope from the command line.

Four subcommands, each of which prints something an operator could paste into
a ticket:

``validate``   run every rule against an envelope file and print the verdict
``example``    write a filled-in envelope to stdout, to edit rather than author
``probe``      ask the emulated delay node what a given distance looks like
``schema``     print the JSON Schema for the envelope

``validate`` exits 0 when the verdict permits the job to run, 1 when it does
not, and 2 when the envelope could not be read. The distinction matters in a
pipeline: a malformed envelope is a different failure from a refused one, and
a script that treats them alike will retry the wrong thing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .adapters import DelayNode
from .plant import SpanGraph, Stitch
from .decisions import Decision, ScaleOut
from .envelope import SliceRect, SpanEnvelope
from .rules import Policy
from .schema import envelope_schema
from .validator import Plant, audit_record, validate


def _load(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _plant_from(d: Dict[str, Any]) -> Plant:
    graph = None
    if "halls" in d:
        graph = SpanGraph(
            frozenset(d["halls"]),
            tuple(Stitch(s["stitch_id"], frozenset(s["halls"])) for s in d.get("stitches", [])),
        )
    return Plant(
        graph=graph,
        job_halls=tuple(d.get("job_halls", ())),
        anchor=d.get("anchor"),
        current_topology_hash=d.get("current_topology_hash"),
    )


def _example_envelope() -> SpanEnvelope:
    graph_hash = "a3f1" + "0" * 60
    env = SpanEnvelope(
        scale_out=ScaleOut.OCS_STITCHED,
        span_mode="span",
        span_rtt_us=412.0,
        span_bw_gbps=800.0,
        span_failure_domain="metro-ring-north",
        slice_rect=SliceRect("hall-a", (0, 0, 0), (8, 8, 8)),
        stitch_id="stitch-ab",
        stitch_api="https://ocs.plant.example/v1",
        topology_hash="b7c2" + "0" * 60,
        measured_il_db=10.0,
        measured_ber=1e-12,
        checkpoint_window_s=120.0,
        collective_window_s=300.0,
        ingest_budget_GBps=40.0,
        thermal_headroom_k=3.0,
        ride_through_s=180.0,
        power_headroom_kw=250.0,
        compile_cache_key="",
        blast_radius=2,
        autonomy_level="L1",
        requested_action="train",
        measured_age_s=30.0,
        stitch_api_reachable=True,
        labels={"graph_hash": graph_hash, "cut": "pp", "job": "example-405b"},
    )
    return env.replace(compile_cache_key=env.expected_compile_cache_key(graph_hash))


def _print_verdict(env: SpanEnvelope, verdict, policy: Policy, as_json: bool) -> None:
    if as_json:
        print(json.dumps(audit_record(env, verdict, policy), indent=2, default=str))
        return
    print(f"decision: {verdict.decision.value.upper()}")
    print(f"regime:   {env.regime} ({env.span_rtt_us:.0f} us RTT)")
    if verdict.findings:
        print("\nfindings:")
        for finding in verdict.findings:
            mark = "!" if finding.fail_closed else "-"
            print(f"  {mark} [{finding.rule_id}] {finding.message}")
    else:
        print("\nfindings: none; every rule cleared")
    if verdict.not_checked:
        print("\nnot checked:")
        for item in verdict.not_checked:
            print(f"  ? {item}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spancontract",
        description="Decide whether a job may cross a hall boundary.",
    )
    parser.add_argument("--version", action="version", version=f"span-contract {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="run every rule against an envelope file")
    p_val.add_argument("envelope", help="path to an envelope JSON file")
    p_val.add_argument("--policy", help="path to a policy JSON file", default=None)
    p_val.add_argument("--plant", help="path to a plant JSON file", default=None)
    p_val.add_argument("--json", action="store_true", help="print the audit record")

    sub.add_parser("example", help="print a filled-in envelope to edit")
    sub.add_parser("schema", help="print the envelope JSON Schema")

    p_probe = sub.add_parser("probe", help="what the emulated delay node reports")
    p_probe.add_argument("--distance-km", type=float, required=True)
    p_probe.add_argument("--bandwidth-gbps", type=float, default=800.0)
    p_probe.add_argument("--amplifier-gain-db", type=float, default=0.0)
    p_probe.add_argument("--interface", default="eth0")

    args = parser.parse_args(argv)

    if args.command == "example":
        print(json.dumps(_example_envelope().to_dict(), indent=2))
        return 0

    if args.command == "schema":
        print(json.dumps(envelope_schema(), indent=2))
        return 0

    if args.command == "probe":
        node = DelayNode(
            "probe",
            distance_km=args.distance_km,
            bandwidth_gbps=args.bandwidth_gbps,
            amplifier_gain_db=args.amplifier_gain_db,
        )
        measurement = node.measure()
        print(f"rtt:     {measurement.rtt_us:.1f} us")
        print(f"regime:  {measurement.regime}")
        print(f"loss:    {measurement.insertion_loss_db:.2f} dB")
        print(f"netem:   {node.netem_command(args.interface)}")
        return 0

    try:
        env = SpanEnvelope.from_dict(_load(args.envelope))
    except (OSError, ValueError, KeyError) as exc:
        print(f"could not read envelope: {exc}", file=sys.stderr)
        return 2

    policy = Policy(**_load(args.policy)) if args.policy else Policy()
    plant = _plant_from(_load(args.plant)) if args.plant else Plant()

    verdict = validate(env, policy, plant)
    _print_verdict(env, verdict, policy, args.json)
    return 0 if verdict.allowed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
