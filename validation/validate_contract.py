#!/usr/bin/env python3
"""The validation registry for span-contract.

Three kinds of point, and the difference between them is the whole document:

``calibrated``
    Pinned to a figure published somewhere other than this repository. The
    check fails if the code drifts from the world.

``emergent``
    Nothing here was tuned to make these come out. They are orderings and
    invariants that fall out of the rule structure, stated as orderings rather
    than as magnitudes, because the magnitudes would be an artifact of the
    example envelopes.

``sanity``
    The contract's own structure, checked against the specification. Reference
    is always "-", because there is nothing external to cite: a sanity point
    that carried a citation would be claiming outside support it does not have.

There is exactly one calibrated point, and that is the honest count rather
than a disappointing one. **This repository's thresholds have no external
anchor.** No published figure says a path measurement goes stale at 300
seconds or that 20 dB is the right loss budget; those are operator choices,
and a registry that dressed them up as calibrated would be the exact failure
this format exists to prevent. The DECLINED list below names every one of
them. Read it before reading the passes.

What this registry can establish is that the contract is internally consistent,
that its refusals are reachable, that its structure matches the specification,
and that deleting any of its machinery is detectable. What it cannot establish
is that the thresholds are right for any particular plant. Nothing here should
be read as evidence that they are.
"""

from __future__ import annotations

import itertools
import json
import math
import random
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spancontract import (  # noqa: E402
    FAIL_CLOSED_RULE_IDS,
    RULES,
    SPAN_MODES,
    SPEC_FIELDS,
    TENANT_RULE_IDS,
    CompileCache,
    CoTenant,
    Decision,
    LambdaSharing,
    Plant,
    Policy,
    ScaleOut,
    SliceQuota,
    SliceRect,
    SpanEnvelope,
    SpanGraph,
    Stitch,
    Tenancy,
    audit_record,
    blast_radius,
    compile_cache_key,
    latency_regime,
    validate,
    verify_chain,
)
from spancontract.adapters import DelayNode, EmulatedController, apply_measurement  # noqa: E402
from spancontract.schema import envelope_schema  # noqa: E402

SEED = 20260901

# --------------------------------------------------------------------------
# external anchors
# --------------------------------------------------------------------------

#: Published rule of thumb for signal propagation in single-mode fibre: light
#: covers a kilometre of glass in about five microseconds one way. Quoted in
#: transmission-planning literature independently of any group-index constant,
#: which is what makes it usable as an anchor for code that computes latency
#: from a group index. See SOURCES.md S1.
PUBLISHED_US_PER_KM_ONE_WAY = 5.0
#: The published figure carries one significant figure, so the check is that
#: the model rounds to it. Writing the band as [4.5, 5.5) rather than picking a
#: percentage keeps the acceptance criterion a property of how the anchor was
#: published rather than a number chosen once the model's answer was known ---
#: which is the failure mode this registry format exists to catch.
PROPAGATION_BAND = (4.5, 5.5)

#: Sweep widths. Fixed before any result was looked at.
DISTANCE_SWEEP_KM = (0.1, 1.0, 5.0, 20.0, 50.0, 100.0, 300.0, 1000.0)
JOB_SIZES = (2, 3, 4, 6, 8)
POPULATION = 400


@dataclass
class Point:
    name: str
    kind: str
    passed: bool
    detail: str
    reference: str = "-"


DECLINED: Tuple[Tuple[str, str], ...] = (
    (
        "every policy threshold",
        "measurement_ttl_s=300, max_insertion_loss_db=20, max_bit_error_rate=1e-9, "
        "sync_training_max_rtt_us=2000 and max_autonomous_blast_radius=1 are operator "
        "choices. No published figure fixes any of them. They are checked for effect, "
        "never for correctness.",
    ),
    (
        "fibre attenuation of 0.2 dB/km",
        "It is a published figure for G.652 fibre at 1550 nm, but the emulator uses it "
        "as a constant, so a check would confirm the code reproduces its own input. "
        "Circular, therefore declined.",
    ),
    (
        "whether an amplified path is healthy",
        "The delay node models amplifier gain and not the optical signal-to-noise cost "
        "that comes with it, and OSNR is what sets the error rate on a long span. The "
        "emulator can show a refusal; it cannot support a claim of health.",
    ),
    (
        "whether the twenty-one fields are sufficient",
        "This registry can show the set is internally consistent and matches the "
        "specification. Whether it is everything a real admission decision needs is a "
        "question only a plant can answer.",
    ),
    (
        "whether any verdict is right for a real cluster",
        "Every envelope here is constructed. No verdict in this registry has been "
        "checked against a job that actually ran.",
    ),
    (
        "the capacity consequence of spanning",
        "What a job retains across a cut is measured by the atlas in "
        "network-vs-more-gpus. This repository decides admission and deliberately holds "
        "no second opinion on capacity.",
    ),
    (
        "the L0/L1 cap on training stitches as a safety property",
        "It is a policy the specification states, implemented as written. That it "
        "reduces incidents is not something this repository has evidence for.",
    ),
    (
        "the blast-radius graph as a model of physical failure",
        "load_bearing_stitches sees the circuits an operator declared, not the ducts "
        "they run through. Two circuits sharing a trench are one failure and this "
        "registry cannot see it.",
    ),
    (
        "netem reproduction fidelity",
        "netem_command is emitted, never executed here. Whether the kernel reproduces "
        "the modelled path is untested in this repository.",
    ),
    (
        "any organization's slice quota",
        "held and quota are declared on the envelope by the caller. No published figure "
        "fixes how many slices an organization may take in a hall, and the contract does "
        "not fetch the count. The quota rule is checked for effect, never for correctness.",
    ),
    (
        "whether the declared wavelength occupancy is true",
        "co_tenants is a list the caller supplies; the contract cannot see the wavelength. "
        "An occupancy that is wrong on the envelope is wrong in the verdict. The audit "
        "record carries the declaration so the error is findable afterwards, not so it "
        "is caught at admission.",
    ),
)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

GRAPH_HASH = "a3f1" + "0" * 60
TOPOLOGY_HASH = "b7c2" + "0" * 60


def clean_envelope(**kw: Any) -> SpanEnvelope:
    """An envelope every rule clears, so a refusal is always one edit away."""
    base: Dict[str, Any] = dict(
        scale_out=ScaleOut.OCS_STITCHED,
        span_mode="span",
        span_rtt_us=412.0,
        span_bw_gbps=800.0,
        span_failure_domain="metro-ring-north",
        slice_rect=SliceRect("hall-a", (0, 0, 0), (8, 8, 8)),
        stitch_id="stitch-ab",
        stitch_api="https://ocs.plant.example/v1",
        topology_hash=TOPOLOGY_HASH,
        measured_il_db=10.0,
        measured_ber=1e-12,
        checkpoint_window_s=120.0,
        collective_window_s=300.0,
        ingest_budget_GBps=40.0,
        thermal_headroom_k=3.0,
        ride_through_s=180.0,
        power_headroom_kw=250.0,
        compile_cache_key="",
        blast_radius=1,
        autonomy_level="L1",
        requested_action="train",
        measured_age_s=30.0,
        stitch_api_reachable=True,
        labels={"graph_hash": GRAPH_HASH, "cut": "pp"},
    )
    base.update(kw)
    env = SpanEnvelope(**base)
    if not base["compile_cache_key"]:
        env = env.replace(compile_cache_key=env.expected_compile_cache_key(GRAPH_HASH))
    return env


def clean_tenancy(**kw: Any) -> Tenancy:
    """A tenancy block every tenant predicate clears.

    Room under the quota in both halls, and a wavelength shared only with the
    organization's own other job, so each predicate is one edit away.
    """
    base: Dict[str, Any] = dict(
        org_id="org-blue",
        tenancy_class="shared",
        slices=(SliceQuota("hall-a", held=2, quota=4), SliceQuota("hall-b", held=1, quota=4)),
        lambda_sharing=LambdaSharing("ch-33", co_tenants=(CoTenant("org-blue", "job-1"),)),
    )
    base.update(kw)
    return Tenancy(**base)


#: The jobs a random wavelength may already carry. One belongs to another
#: organization, so the population reaches TN2; two belong to the job's own,
#: so it reaches TN3 and TN4 without reaching TN2.
CO_TENANT_POOL = (
    CoTenant("org-blue", "job-1"),
    CoTenant("org-red", "job-7"),
    CoTenant("org-blue", "job-9"),
)


def random_tenancy(rng: random.Random) -> Tenancy:
    """A randomly declared tenancy block: sometimes within quota, sometimes not."""
    slices = [SliceQuota("hall-a", held=rng.choice([0, 2, 3, 4]), quota=rng.choice([0, 2, 4]))]
    if rng.random() < 0.5:
        slices.append(SliceQuota("hall-b", held=rng.choice([0, 2, 3, 4]), quota=rng.choice([0, 2, 4])))
    sharing: Optional[LambdaSharing] = None
    if rng.random() >= 0.25:
        pool = list(CO_TENANT_POOL)
        rng.shuffle(pool)
        co_tenants = tuple(pool[: rng.choice([0, 1, 2])])
        bans = tuple(job for job in ("job-1", "job-7", "job-9") if rng.random() < 0.25)
        sharing = LambdaSharing("ch-33", co_tenants=co_tenants, must_not_share_with=bans)
    return Tenancy(
        org_id=rng.choice(["org-blue", "org-red"]),
        tenancy_class=rng.choice(["dedicated", "shared"]),
        slices=tuple(slices),
        lambda_sharing=sharing,
    )


def random_envelope(rng: random.Random) -> SpanEnvelope:
    """A randomly damaged envelope, for population-level orderings.

    Half the population declares a tenancy block and half does not, so every
    population point sees both the checked and the taken-on-trust path.
    """
    env = clean_envelope(
        span_mode=rng.choice(SPAN_MODES),
        span_rtt_us=rng.choice([0.5, 3.0, 40.0, 400.0, 1_500.0, 9_000.0, 40_000.0]),
        measured_il_db=rng.choice([2.0, 10.0, 19.0, 25.0, 40.0]),
        measured_ber=rng.choice([1e-15, 1e-12, 1e-10, 1e-8, 1e-5]),
        thermal_headroom_k=rng.choice([-0.0, 0.0, 1.0, 5.0]),
        power_headroom_kw=rng.choice([0.0, 10.0, 400.0]),
        ride_through_s=rng.choice([10.0, 100.0, 180.0, 600.0]),
        checkpoint_window_s=rng.choice([30.0, 120.0, 400.0]),
        collective_window_s=rng.choice([60.0, 300.0, 900.0]),
        blast_radius=rng.choice([1, 2, 4]),
        autonomy_level=rng.choice(["L0", "L1", "L2", "L3"]),
        requested_action=rng.choice(["train", "infer", "finetune", "evaluate"]),
        labels={"graph_hash": GRAPH_HASH, "cut": rng.choice(["dp", "pp", "tp", "ep"])},
    )
    if rng.random() < 0.25:
        env = env.replace(stitch_api_reachable=rng.choice([False, None]))
    if rng.random() < 0.25:
        env = env.replace(measured_age_s=rng.choice([None, 10.0, 6_000.0]))
    if rng.random() < 0.5:
        env = env.replace(tenancy=random_tenancy(rng))
    return env


# --------------------------------------------------------------------------
# calibrated
# --------------------------------------------------------------------------


def point_propagation_matches_published_rule_of_thumb() -> Point:
    """The emulator's latency must round to the published five microseconds a kilometre."""
    low, high = PROPAGATION_BAND
    rates = []
    for km in DISTANCE_SWEEP_KM:
        node = DelayNode("s", distance_km=km, equipment_latency_us=0.0)
        rates.append((node.rtt_us / 2.0) / km)
    inside = all(low <= r < high for r in rates)
    return Point(
        "fibre-latency-rounds-to-the-published-rule-of-thumb",
        "calibrated",
        inside,
        f"model gives {min(rates):.3f} us/km one way at every distance from "
        f"{min(DISTANCE_SWEEP_KM)} to {max(DISTANCE_SWEEP_KM)} km, which rounds to the "
        f"published {PUBLISHED_US_PER_KM_ONE_WAY:.0f}; acceptance band "
        f"[{low}, {high}) is the width of one significant figure, not a fitted tolerance",
        "S1",
    )


# --------------------------------------------------------------------------
# emergent
# --------------------------------------------------------------------------


def point_refusal_is_monotone_in_distance() -> Point:
    """Moving a job further away never makes the contract more permissive."""
    worst = ""
    ok = True
    seen: Dict[str, set] = {}
    for action in ("train", "infer"):
        previous = -1
        seen[action] = set()
        for rtt in (0.5, 3.0, 40.0, 400.0, 1_500.0, 3_000.0, 20_000.0, 100_000.0):
            decision = validate(clean_envelope(span_rtt_us=rtt, requested_action=action)).decision
            seen[action].add(decision)
            if decision.severity < previous:
                ok = False
                worst = f"{action} became more permissive at {rtt} us"
            previous = max(previous, decision.severity)
    # A constant sweep is monotone too. Requiring the training job's verdict to
    # actually move makes this a check on the distance rule rather than on the
    # definition of monotone, which a deleted rule would otherwise still satisfy.
    moved = len(seen["train"]) >= 2
    if not moved:
        worst = worst or "the training verdict never changed across the sweep, so this "\
                         "point could not distinguish a live distance rule from a dead one"
    return Point(
        "refusal-is-monotone-in-distance",
        "emergent",
        ok and moved,
        worst or "over 8 distances from 0.5 us to 100 ms the verdict never relaxes; the "
        f"training job passes through {len(seen['train'])} distinct verdicts and the "
        f"inference job through {len(seen['infer'])}, so the ordering is doing work",
    )


def point_redundancy_collapses_blast_radius_in_one_step() -> Point:
    """A parallel circuit takes the blast radius from n straight to 1, never between."""
    observed: List[Tuple[int, int, int]] = []
    ok = True
    for n in JOB_SIZES:
        halls = [f"hall-{i}" for i in range(n)]
        chain = tuple(
            Stitch(f"s{i}", frozenset({halls[i], halls[i + 1]})) for i in range(n - 1)
        )
        single = SpanGraph(frozenset(halls), chain)
        doubled = SpanGraph(frozenset(halls), chain + tuple(
            Stitch(f"s{i}b", frozenset({halls[i], halls[i + 1]})) for i in range(n - 1)
        ))
        before = blast_radius(single, "s0", halls, halls[0])
        after = blast_radius(doubled, "s0", halls, halls[0])
        observed.append((n, before, after))
        if before != n or after != 1:
            ok = False
    return Point(
        "redundancy-collapses-blast-radius-in-one-step",
        "emergent",
        ok,
        "job sizes " + ", ".join(f"{n}: {b}->{a}" for n, b, a in observed)
        + "; no intermediate value appears, because a synchronous job survives no partition",
    )


def point_every_fail_closed_condition_is_one_edit_away() -> Point:
    """Each of the three specified conditions turns a clean SPAN into a DENY alone."""
    base = clean_envelope()
    baseline = validate(base).decision
    if baseline is not Decision.SPAN:
        return Point(
            "every-fail-closed-condition-is-one-edit-away",
            "emergent",
            False,
            f"the reference envelope no longer clears every rule (it returns {baseline.value}), "
            "so 'one edit away from a refusal' cannot be measured from it",
        )
    edits = {
        "FC1": base.replace(stitch_api_reachable=False),
        "FC2": base.replace(measured_age_s=10_000.0),
        "FC3": base.replace(compile_cache_key="0" * 64),
    }
    fired: Dict[str, bool] = {}
    for rule_id, env in edits.items():
        verdict = validate(env)
        ids = {f.rule_id for f in verdict.findings}
        fired[rule_id] = verdict.decision is Decision.DENY and ids == {rule_id}
    return Point(
        "every-fail-closed-condition-is-one-edit-away",
        "emergent",
        all(fired.values()),
        "from a clean SPAN, one field change reaches each condition in isolation: "
        + ", ".join(f"{k} {'yes' if v else 'NO'}" for k, v in fired.items()),
    )


def point_rule_order_does_not_change_the_verdict() -> Point:
    """Shuffling the rule list leaves every verdict in a random population identical."""
    rng = random.Random(SEED)
    mismatches = 0
    declared = 0
    for _ in range(POPULATION):
        env = random_envelope(rng)
        declared += env.tenancy is not None
        reference = validate(env).decision
        shuffled = list(RULES)
        rng.shuffle(shuffled)
        if validate(env, rules=shuffled).decision is not reference:
            mismatches += 1
    return Point(
        "rule-order-does-not-change-the-verdict",
        "emergent",
        mismatches == 0,
        f"{POPULATION} random envelopes, {declared} of them carrying a tenancy block, each "
        f"evaluated against a shuffled list of {len(RULES)} rules; {mismatches} disagreements",
    )


def point_adding_a_rule_never_permits_more() -> Point:
    """No subset of the rules is more restrictive than the whole set."""
    rng = random.Random(SEED + 1)
    violations = 0
    relaxed = 0
    for _ in range(POPULATION):
        env = random_envelope(rng)
        full = validate(env).decision.severity
        subset = list(RULES)
        subset.pop(rng.randrange(len(subset)))
        smaller = validate(env, rules=subset).decision.severity
        if smaller > full:
            violations += 1
        if smaller < full:
            relaxed += 1
    # Without the second count this point would pass on a rule set where every
    # rule is dead, since a smaller set of dead rules is also never harsher.
    return Point(
        "adding-a-rule-never-permits-more",
        "emergent",
        violations == 0 and relaxed > 0,
        f"{POPULATION} random envelopes, each evaluated with one rule dropped; the "
        f"smaller set was never harsher ({violations} violations) and was more "
        f"permissive {relaxed} times, so the rules that were dropped were carrying weight",
    )


def point_a_hall_local_job_answers_to_no_circuit_rule() -> Point:
    """A job that does not cross is untouched by every circuit and plant rule."""
    rng = random.Random(SEED + 2)
    contaminated = 0
    for _ in range(POPULATION):
        env = random_envelope(rng).replace(span_mode="local")
        verdict = validate(env)
        if verdict.findings or verdict.decision is not Decision.LOCAL:
            contaminated += 1
    return Point(
        "a-hall-local-job-answers-to-no-circuit-rule",
        "emergent",
        contaminated == 0,
        f"{POPULATION} randomly damaged envelopes set to span_mode=local; all returned "
        f"LOCAL with no findings ({contaminated} exceptions). A dark controller and a "
        "rotten circuit are irrelevant to a job that never leaves its hall",
    )


def point_severity_ladder_dominates_by_construction() -> Point:
    """Where several rules fire, the verdict is the harshest of them, every time."""
    rng = random.Random(SEED + 3)
    multi = 0
    wrong = 0
    disagreeing = 0
    for _ in range(POPULATION):
        env = random_envelope(rng)
        verdict = validate(env)
        if len(verdict.findings) < 2:
            continue
        multi += 1
        severities = {f.decision.severity for f in verdict.findings}
        if len(severities) > 1:
            disagreeing += 1
        if verdict.decision.severity != max(severities):
            wrong += 1
    # Cases where the findings all agree prove nothing about dominance: the
    # maximum of one value is that value. The point only means something on the
    # envelopes where two rules asked for different outcomes.
    return Point(
        "severity-ladder-dominates-by-construction",
        "emergent",
        wrong == 0 and disagreeing > 0,
        f"{multi} of {POPULATION} random envelopes tripped two or more rules, and on "
        f"{disagreeing} of those the rules asked for different outcomes; in every case "
        f"the verdict equalled the harshest finding ({wrong} exceptions)",
    )


def point_each_tenant_predicate_is_one_edit_away() -> Point:
    """Each of the four tenant predicates turns a clean SPAN into a DENY alone.

    The tenancy counterpart of the fail-closed point above, from a reference
    envelope that declares its tenancy and clears every predicate.
    """
    base = clean_envelope(tenancy=clean_tenancy())
    baseline = validate(base)
    if baseline.decision is not Decision.SPAN or any(
        line.startswith("TN") for line in baseline.not_checked
    ):
        return Point(
            "each-tenant-predicate-is-one-edit-away",
            "emergent",
            False,
            f"the reference tenancy block no longer clears every predicate (verdict "
            f"{baseline.decision.value}, gaps {[l[:7] for l in baseline.not_checked]}), so "
            "'one edit away from a refusal' cannot be measured from it",
        )
    room = (SliceQuota("hall-a", held=2, quota=4), SliceQuota("hall-b", held=1, quota=4))
    edits = {
        "TN1": base.replace(tenancy=clean_tenancy(
            slices=(SliceQuota("hall-a", held=4, quota=4),) + room[1:])),
        "TN2": base.replace(tenancy=clean_tenancy(
            lambda_sharing=LambdaSharing("ch-33", co_tenants=(CoTenant("org-red", "job-7"),)))),
        "TN3": base.replace(tenancy=clean_tenancy(tenancy_class="dedicated")),
        "TN4": base.replace(tenancy=clean_tenancy(
            lambda_sharing=LambdaSharing("ch-33", co_tenants=(CoTenant("org-blue", "job-1"),),
                                         must_not_share_with=("job-1",)))),
    }
    fired: Dict[str, bool] = {}
    for rule_id, env in edits.items():
        verdict = validate(env)
        ids = {f.rule_id for f in verdict.findings}
        fired[rule_id] = verdict.decision is Decision.DENY and ids == {rule_id}
    return Point(
        "each-tenant-predicate-is-one-edit-away",
        "emergent",
        all(fired.values()) and set(fired) == set(TENANT_RULE_IDS),
        "from a clean SPAN with a declared tenancy, one edit reaches each predicate in "
        "isolation: " + ", ".join(f"{k} {'yes' if v else 'NO'}" for k, v in fired.items()),
    )


def point_refusal_is_monotone_in_slices_held() -> Point:
    """Holding more slices in a hall never makes the contract more permissive."""
    quota = 4
    sweep = tuple(range(0, 7))
    seen: List[Decision] = []
    previous = -1
    ok = True
    worst = ""
    for held in sweep:
        tenancy = clean_tenancy(slices=(SliceQuota("hall-a", held=held, quota=quota),))
        decision = validate(clean_envelope(tenancy=tenancy)).decision
        seen.append(decision)
        if decision.severity < previous:
            ok = False
            worst = f"the verdict relaxed at held={held}"
        previous = max(previous, decision.severity)
    # As with distance: a constant sweep is monotone, so the verdict must move
    # for this to be a check on the quota rule rather than on the word.
    moved = len(set(seen)) >= 2
    if not moved:
        worst = worst or "the verdict never changed as held rose past the quota, so this " \
                         "point could not distinguish a live quota rule from a dead one"
    first = next((h for h, d in zip(sweep, seen) if d is not Decision.SPAN), None)
    return Point(
        "refusal-is-monotone-in-slices-held",
        "emergent",
        ok and moved,
        worst or f"held swept {sweep[0]}..{sweep[-1]} against a quota of {quota}: "
        + ", ".join(f"{h}:{d.value}" for h, d in zip(sweep, seen))
        + f"; the verdict never relaxes, and the first refusal is at held={first}",
    )


def point_adding_a_co_tenant_never_permits_more() -> Point:
    """Another job on the wavelength never relaxes the verdict, and sometimes hardens it.

    Drawn from clean envelopes with a random tenancy block rather than from the
    randomly damaged population: the join is a maximum, so damage elsewhere
    only raises the floor and would leave the second count near zero, which
    is the count that makes this a check on the sharing rules and not on the
    definition of monotone.
    """
    rng = random.Random(SEED + 4)
    considered = violations = harsher = 0
    for _ in range(POPULATION):
        env = clean_envelope(tenancy=random_tenancy(rng))
        tenancy = env.tenancy
        if tenancy is None or tenancy.lambda_sharing is None:
            continue
        sharing = tenancy.lambda_sharing
        present = {c.job_id for c in sharing.co_tenants}
        candidates = [c for c in CO_TENANT_POOL if c.job_id not in present]
        if not candidates:
            continue
        extra = rng.choice(candidates)
        fuller = replace(sharing, co_tenants=sharing.co_tenants + (extra,))
        more = env.replace(tenancy=replace(tenancy, lambda_sharing=fuller))
        before = validate(env).decision.severity
        after = validate(more).decision.severity
        considered += 1
        if after < before:
            violations += 1
        if after > before:
            harsher += 1
    return Point(
        "adding-a-co-tenant-never-permits-more",
        "emergent",
        violations == 0 and harsher > 0,
        f"{considered} of {POPULATION} clean envelopes with a random tenancy declared a "
        f"wavelength with room for one more job; adding it never relaxed the verdict "
        f"({violations} violations) and hardened it {harsher} times, so the sharing rules "
        "were carrying weight",
    )


def point_removing_the_tenancy_block_never_refuses_more() -> Point:
    """Withholding the declaration is never harsher than making it.

    The other half of DECISIONS.md D13. If an absent block could refuse a job
    that a declared block admits, the block would be mandatory in all but
    name; the sanity point below checks that the absence is printed.
    """
    rng = random.Random(SEED + 5)
    considered = violations = relaxed = 0
    for _ in range(POPULATION):
        env = clean_envelope(tenancy=random_tenancy(rng))
        considered += 1
        declared = validate(env).decision.severity
        withheld = validate(env.replace(tenancy=None)).decision.severity
        if withheld > declared:
            violations += 1
        if withheld < declared:
            relaxed += 1
    return Point(
        "removing-the-tenancy-block-never-refuses-more",
        "emergent",
        violations == 0 and relaxed > 0,
        f"{considered} clean envelopes with a random tenancy block; with the block removed "
        f"the verdict was never harsher ({violations} violations) and was more permissive "
        f"{relaxed} times, which is the cost of taking a declaration on trust",
    )


# --------------------------------------------------------------------------
# sanity
# --------------------------------------------------------------------------


def point_twenty_one_fields() -> Point:
    n = len(SPEC_FIELDS)
    declared = set(SpanEnvelope.__dataclass_fields__)
    return Point(
        "the-envelope-has-the-twenty-one-specified-fields",
        "sanity",
        n == 21 and set(SPEC_FIELDS) <= declared,
        f"{n} specification fields, all present on the dataclass; "
        f"{len(declared) - n} further fields carry provenance or an optional declaration",
    )


def point_an_absent_tenancy_block_is_listed_as_unchecked_not_refused() -> Point:
    """DECISIONS.md D13: no tenancy block is a gap in the verdict, never a finding."""
    reference = validate(clean_envelope())
    ids = [line.split()[0] for line in reference.not_checked]
    listed = "TN1" in ids and "TN2-TN4" in ids
    reference_clean = reference.decision is Decision.SPAN and not any(
        f.rule_id in TENANT_RULE_IDS for f in reference.findings
    )
    local = validate(clean_envelope(span_mode="local")).not_checked
    local_silent = not any(line.startswith("TN") for line in local)
    rng = random.Random(SEED + 6)
    crossing = silent = refused = 0
    for _ in range(POPULATION):
        env = random_envelope(rng).replace(tenancy=None)
        verdict = validate(env)
        if any(f.rule_id in TENANT_RULE_IDS for f in verdict.findings):
            refused += 1
        if env.spans_halls:
            crossing += 1
            got = {line.split()[0] for line in verdict.not_checked}
            if not {"TN1", "TN2-TN4"} <= got:
                silent += 1
    return Point(
        "an-absent-tenancy-block-is-listed-as-unchecked-not-refused",
        "sanity",
        reference_clean and listed and local_silent and refused == 0 and silent == 0,
        f"the reference envelope declares no tenancy, is admitted ({reference.decision.value}) "
        "and lists TN1 and TN2-TN4 as not checked; across "
        f"{POPULATION} random envelopes with the block removed no tenant predicate fired "
        f"({refused} did) and every one of the {crossing} crossing jobs had both gaps listed "
        f"({silent} silent); a hall-local job lists neither",
    )


def point_the_tenancy_block_is_optional_in_the_schema_and_round_trips() -> Point:
    schema = envelope_schema()
    prop = schema["properties"].get("tenancy")
    optional = (
        prop is not None
        and "tenancy" not in schema["required"]
        and "null" in prop["type"]
    )
    closed = (
        prop is not None
        and prop.get("additionalProperties") is False
        and prop["required"] == ["org_id", "tenancy_class"]
    )
    declared = clean_envelope(tenancy=clean_tenancy(
        lambda_sharing=LambdaSharing("ch-33", co_tenants=(CoTenant("org-blue", "job-1"),),
                                     must_not_share_with=("job-7",))))
    restored = SpanEnvelope.from_dict(json.loads(json.dumps(declared.to_dict())))
    bare = SpanEnvelope.from_dict(json.loads(json.dumps(clean_envelope().to_dict())))
    try:
        Tenancy.from_dict({"org_id": "org-blue", "tenancy_class": "shared", "quota": 4})
        misspelt_refused = False
    except ValueError:
        misspelt_refused = True
    return Point(
        "the-tenancy-block-is-optional-in-the-schema-and-round-trips",
        "sanity",
        optional and closed and restored == declared and bare.tenancy is None and misspelt_refused,
        "the schema lists tenancy as nullable and not required and closes it to unknown "
        "keys; a declared block reconstructs identically from JSON, an envelope without "
        "one reconstructs without one, and a misspelt key is refused rather than dropped",
    )


def point_six_decisions() -> Point:
    values = [d.value for d in Decision]
    severities = [d.severity for d in Decision]
    return Point(
        "there-are-six-decisions-on-a-total-order",
        "sanity",
        len(values) == 6 and len(set(severities)) == 6,
        f"{', '.join(values)}; six distinct severities, so the join is well defined",
    )


def point_three_fail_closed_conditions() -> Point:
    """Each condition raises a flagged finding *and* the verdict is a refusal.

    Checking the flag alone would not be checking anything: a finding can carry
    ``fail_closed=True`` while the join lets the job run. "Fails closed" means
    the job does not run, so the verdict is part of the check.
    """
    fired = set()
    refused = set()
    base = clean_envelope()
    for env in (
        base.replace(stitch_api_reachable=False),
        base.replace(measured_age_s=10_000.0),
        base.replace(compile_cache_key="0" * 64),
    ):
        verdict = validate(env)
        for finding in verdict.findings:
            if finding.fail_closed:
                fired.add(finding.rule_id)
                if verdict.decision is Decision.DENY and not verdict.allowed:
                    refused.add(finding.rule_id)
    expected = set(FAIL_CLOSED_RULE_IDS)
    return Point(
        "the-three-specified-conditions-fail-closed",
        "sanity",
        fired == expected and refused == expected,
        f"conditions flagged and reachable: {sorted(fired)}; of those, the ones whose "
        f"verdict was actually DENY: {sorted(refused)}; specification names "
        f"{list(FAIL_CLOSED_RULE_IDS)}",
    )


def point_span_mode_omits_escalate() -> Point:
    """The specification's own discrepancy, asserted rather than smoothed away."""
    decisions = {d.value for d in Decision}
    missing = decisions - set(SPAN_MODES)
    return Point(
        "span-mode-omits-escalate-as-the-specification-does",
        "sanity",
        missing == {"escalate"},
        f"span_mode enumerates {len(SPAN_MODES)} of the {len(decisions)} decisions; "
        f"missing: {sorted(missing)}. Section 4.2 lists escalate as a decision and "
        "section 4.3 leaves it out of the field. Carried, not reconciled (DECISIONS.md D3)",
    )


def point_schema_round_trips() -> Point:
    schema = envelope_schema()
    env = clean_envelope()
    restored = SpanEnvelope.from_dict(json.loads(json.dumps(env.to_dict())))
    required = set(schema["required"])
    return Point(
        "the-schema-matches-the-code-and-an-envelope-round-trips",
        "sanity",
        required == set(SPEC_FIELDS) and restored == env,
        f"schema requires the same {len(required)} fields the code declares, and a "
        "serialised envelope reconstructs identically",
    )


def point_compile_cache_key_is_its_three_inputs() -> Point:
    rect = SliceRect("hall-a", (0, 0, 0), (8, 8, 8))
    other = SliceRect("hall-a", (0, 0, 8), (8, 8, 8))
    base = compile_cache_key(GRAPH_HASH, rect, "stitch-ab")
    variants = {
        "graph": compile_cache_key(GRAPH_HASH[:-1] + "1", rect, "stitch-ab"),
        "slice_rect": compile_cache_key(GRAPH_HASH, other, "stitch-ab"),
        "stitch_id": compile_cache_key(GRAPH_HASH, rect, "stitch-cd"),
    }
    all_differ = all(v != base for v in variants.values())
    all_distinct = len(set(variants.values())) == 3
    return Point(
        "the-compile-cache-key-moves-with-each-of-its-three-inputs",
        "sanity",
        all_differ and all_distinct,
        "changing the graph, the slice rectangle, or the stitch each produces a "
        "different key, and the three differ from one another",
    )


def point_stale_entry_is_refused_not_evicted() -> Point:
    cache = CompileCache()
    key = compile_cache_key(GRAPH_HASH, SliceRect("hall-a", (0,), (8,)), "stitch-ab")
    cache.put(key, TOPOLOGY_HASH, artifact="plan-v1")
    hit = cache.get(key, TOPOLOGY_HASH)
    stale = cache.get(key, "c9d4" + "0" * 60)
    return Point(
        "a-stale-cache-entry-is-refused-and-kept",
        "sanity",
        hit.usable and not stale.usable and stale.entry is not None
        and key in cache.entries and len(cache.refusals) == 1,
        "the entry survives its refusal so an operator can see what was rejected and "
        "which topology it was stamped with; one refusal recorded",
    )


def point_audit_chain_detects_an_edit() -> Point:
    env = clean_envelope()
    first = audit_record(env, validate(env))
    second = audit_record(
        clean_envelope(span_rtt_us=40_000.0),
        validate(clean_envelope(span_rtt_us=40_000.0)),
        previous_hash=first["chain"],
    )
    intact = verify_chain([first, second])
    tampered = json.loads(json.dumps(second))
    # Edit a recorded measurement rather than the verdict. Rewriting the verdict
    # is only an edit when the verdict was not already the value written, which
    # made an earlier version of this point pass or fail depending on which
    # rules were live --- a dependency a tamper-detection check must not have.
    original = tampered["envelope"]["span_rtt_us"]
    tampered["envelope"]["span_rtt_us"] = original + 1.0
    detected = not verify_chain([first, tampered])
    return Point(
        "the-audit-chain-detects-a-single-edited-field",
        "sanity",
        intact and detected,
        f"a two-record chain verifies, and moving one recorded round-trip time from "
        f"{original:.0f} to {original + 1.0:.0f} us breaks it",
    )


def point_dark_probe_invents_nothing() -> Point:
    env = clean_envelope()
    node = DelayNode("stitch-ab", distance_km=40.0)
    dark = EmulatedController((node.go_dark(),)).probe("stitch-ab")
    after = apply_measurement(env, dark)
    untouched = (
        after.span_rtt_us == env.span_rtt_us
        and after.measured_il_db == env.measured_il_db
        and after.measured_ber == env.measured_ber
        and after.span_bw_gbps == env.span_bw_gbps
    )
    return Point(
        "a-dark-probe-changes-no-measured-value",
        "sanity",
        untouched and after.stitch_api_reachable is False
        and validate(after).decision is Decision.DENY,
        "the declared numbers survive and only stitch_api_reachable moves, so the audit "
        "record shows what was claimed alongside the fact that nobody could confirm it",
    )


def point_regimes_partition_the_line() -> Point:
    from spancontract.envelope import REGIME_BOUNDS

    names = [n for n, _ in REGIME_BOUNDS]
    bounds = [b for _, b in REGIME_BOUNDS]
    ascending = all(a < b for a, b in zip(bounds, bounds[1:]))
    covers = latency_regime(0.0) == names[0] and latency_regime(1e9) == names[-1]
    edges_ok = all(
        latency_regime(bounds[i]) == names[i] for i in range(len(bounds) - 1)
    )
    return Point(
        "the-latency-regimes-partition-the-line-with-no-gap",
        "sanity",
        ascending and covers and edges_ok,
        f"{len(names)} regimes, strictly ascending bounds, every boundary value falls in "
        "the lower regime, and every round-trip time from zero to a second lands in one",
    )



def point_the_emulated_stitch_flips_the_verdict_across_a_regime() -> Point:
    """Section 9, item 7, to the letter: the flip comes out of the delay node.

    The monotone sweep above drives the envelope directly; this point drives it
    through the emulated controller instead, so the demonstrated path is probe
    -> measurement -> envelope -> verdict, with nothing hand-set but the
    distance. Same job, two lengths of glass, opposite answers.
    """
    near_node = DelayNode("stitch-ab", distance_km=40.0)
    far_node = DelayNode("stitch-ab", distance_km=400.0)
    near = validate(apply_measurement(
        clean_envelope(), EmulatedController((near_node,)).probe("stitch-ab")))
    far = validate(apply_measurement(
        clean_envelope(), EmulatedController((far_node,)).probe("stitch-ab")))
    ok = (near.decision is Decision.SPAN
          and far.decision in (Decision.DENY, Decision.ESCALATE)
          and near.decision is not far.decision)
    return Point(
        "the-emulated-stitch-flips-the-verdict-across-a-regime",
        "emergent",
        ok,
        f"40 km of emulated glass measures {near_node.rtt_us:.0f} us and the job "
        f"may span; 400 km measures {far_node.rtt_us:.0f} us, crosses the "
        f"synchronous-training regime bound, and the same job is refused "
        f"({far.decision.value}) --- the flip the delay node exists to prove",
    )


REGISTRY: Tuple[Callable[[], Point], ...] = (
    point_propagation_matches_published_rule_of_thumb,
    point_refusal_is_monotone_in_distance,
    point_the_emulated_stitch_flips_the_verdict_across_a_regime,
    point_redundancy_collapses_blast_radius_in_one_step,
    point_every_fail_closed_condition_is_one_edit_away,
    point_rule_order_does_not_change_the_verdict,
    point_adding_a_rule_never_permits_more,
    point_a_hall_local_job_answers_to_no_circuit_rule,
    point_severity_ladder_dominates_by_construction,
    point_each_tenant_predicate_is_one_edit_away,
    point_refusal_is_monotone_in_slices_held,
    point_adding_a_co_tenant_never_permits_more,
    point_removing_the_tenancy_block_never_refuses_more,
    point_twenty_one_fields,
    point_six_decisions,
    point_three_fail_closed_conditions,
    point_span_mode_omits_escalate,
    point_schema_round_trips,
    point_compile_cache_key_is_its_three_inputs,
    point_stale_entry_is_refused_not_evicted,
    point_audit_chain_detects_an_edit,
    point_dark_probe_invents_nothing,
    point_regimes_partition_the_line,
    point_an_absent_tenancy_block_is_listed_as_unchecked_not_refused,
    point_the_tenancy_block_is_optional_in_the_schema_and_round_trips,
)


def run_registry() -> List[Point]:
    """Every point, in registry order. Imported by the mutation tests.

    A point that raises is reported as failed rather than allowed to abort the
    run. Under mutation a check will sometimes hit a state its author did not
    anticipate, and a traceback there would hide every point after it --- which
    is the same as a registry that stops looking once it finds a problem.
    """
    points: List[Point] = []
    for check in REGISTRY:
        try:
            points.append(check())
        except Exception as exc:  # noqa: BLE001 - a raising check is a failing check
            points.append(
                Point(
                    getattr(check, "__name__", "unnamed").replace("point_", "").replace("_", "-"),
                    "sanity",
                    False,
                    f"the check raised {type(exc).__name__}: {exc}",
                )
            )
    return points


def main() -> int:
    points = run_registry()
    width = max(len(p.name) for p in points)
    print("span-contract validation registry")
    print("=" * (width + 34))
    for kind in ("calibrated", "emergent", "sanity"):
        selected = [p for p in points if p.kind == kind]
        print(f"\n{kind.upper()}  ({len(selected)})")
        for point in selected:
            mark = "PASS" if point.passed else "FAIL"
            print(f"  {mark}  {point.name:<{width}}  ref {point.reference}")
            print(f"        {point.detail}")

    print(f"\nDECLINED  ({len(DECLINED)})")
    print("  What this registry does not check, and why:")
    for title, reason in DECLINED:
        print(f"  - {title}\n      {reason}")

    passed = sum(1 for p in points if p.passed)
    counts = {k: sum(1 for p in points if p.kind == k) for k in ("calibrated", "emergent", "sanity")}
    print(
        f"\n{passed} of {len(points)} points pass "
        f"({counts['calibrated']} calibrated / {counts['emergent']} emergent / "
        f"{counts['sanity']} sanity, {len(DECLINED)} declined)"
    )
    if counts["calibrated"] == 1:
        print(
            "\nOne calibrated point is not an oversight. The thresholds in this "
            "repository are operator choices with no published anchor, and the DECLINED "
            "list above says so rather than dressing them up."
        )
    return 0 if passed == len(points) else 1


if __name__ == "__main__":
    raise SystemExit(main())
