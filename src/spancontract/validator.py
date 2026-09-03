"""The reference validator: envelope in, decision out, with the reasons.

The validator is small on purpose. It runs every rule, joins their findings
with :meth:`Decision.max`, and writes an audit record. It contains no
thresholds and no judgement of its own; everything it decides is traceable to a
rule id and a policy field.

Two checks live here rather than in :mod:`spancontract.rules` because they need
something the envelope does not carry --- the plant itself. A rule can only see
what the job declared. Comparing a declaration against the plant is a different
kind of check, and keeping the two apart means the rule set stays runnable with
no plant model at all, which is the state most callers will be in first.

The record this emits is a plain dictionary with a SHA-256 chain field. It is
not tied to any particular audit system, and this repository does not ship one;
:doc:`docs/integration` describes the surface an existing policy engine would
bind to.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .plant import SpanGraph, blast_radius, load_bearing_stitches
from .decisions import Decision
from .envelope import SpanEnvelope
from .rules import FAIL_CLOSED_RULE_IDS, RULES, Finding, Policy


@dataclass(frozen=True)
class Plant:
    """What the validator knows about the plant, as opposed to the job.

    Every field is optional. A caller with no plant model still gets every
    rule; it simply cannot get the cross-checks, and the verdict says so rather
    than implying the checks passed.
    """

    graph: Optional[SpanGraph] = None
    job_halls: Sequence[str] = ()
    anchor: Optional[str] = None
    #: The topology hash live in the plant right now.
    current_topology_hash: Optional[str] = None

    @property
    def can_check_blast_radius(self) -> bool:
        return bool(self.graph is not None and self.job_halls and self.anchor)


def check_declared_blast_radius(
    env: SpanEnvelope, policy: Policy, plant: Plant
) -> Optional[Finding]:
    """XP1. The declared blast radius must not understate the plant's.

    Understating it is the interesting direction: it is how a job is admitted
    at an autonomy level the plant does not support. Overstating it is
    conservative, and the validator says so in the record without objecting.
    """
    if not env.spans_halls or not plant.can_check_blast_radius:
        return None
    assert plant.graph is not None and plant.anchor is not None
    try:
        computed = blast_radius(plant.graph, env.stitch_id, plant.job_halls, plant.anchor)
    except KeyError:
        return Finding(
            "XP1", Decision.DENY,
            f"stitch {env.stitch_id!r} is not a circuit this plant has",
        )
    if env.blast_radius < computed:
        return Finding(
            "XP1", Decision.DENY,
            f"envelope declares blast radius {env.blast_radius}, the plant computes "
            f"{computed}; the job was sized against a plant that does not exist",
        )
    return None


def check_topology_current(
    env: SpanEnvelope, policy: Policy, plant: Plant
) -> Optional[Finding]:
    """XP2. The topology the envelope names must be the one the plant has.

    This is the plant-side half of the specification's third fail-closed
    condition. FC3 catches a compile cache key that does not match its own
    placement; this catches a key that matches a placement the plant retuned
    away from.
    """
    if not env.spans_halls or plant.current_topology_hash is None:
        return None
    if env.topology_hash != plant.current_topology_hash:
        return Finding(
            "XP2", Decision.DENY,
            f"envelope names topology {env.topology_hash[:12]}..., the plant is on "
            f"{plant.current_topology_hash[:12]}...; the topology it was planned "
            "against no longer exists",
            fail_closed=True,
        )
    return None


PLANT_RULES = (check_declared_blast_radius, check_topology_current)


def tenancy_gaps(env: SpanEnvelope, plant: Plant) -> List[str]:
    """What the tenant predicates could not check, by name.

    The taken-on-trust pattern of XP1 and XP2, applied to a block that is
    optional by design. A missing block, a block with no quota state, a block
    with no wavelength declaration, a hall the plant says the job occupies but
    the block does not cover, and a block that declares only the home hall of
    a crossing job when no plant model names the far hall, each produce a line
    here. None of them produces a finding; DECISIONS.md D13 says why.
    """
    if not env.spans_halls:
        return []
    tenancy = env.tenancy
    home = env.slice_rect.hall_id
    if tenancy is None:
        return [
            "TN1 organization slice quota: no tenancy block on the envelope, so the "
            f"organization's slice count in {home!r} was taken on trust",
            "TN2-TN4 wavelength sharing: no tenancy block on the envelope, so whatever "
            "else is on the stitch's wavelength was taken on trust",
        ]
    gaps: List[str] = []
    if not tenancy.slices:
        gaps.append(
            f"TN1 organization slice quota: tenancy block for {tenancy.org_id!r} declares "
            f"no quota state, so its slice count in {home!r} was taken on trust"
        )
    else:
        undeclared = [h for h in plant.job_halls if h not in tenancy.declared_halls]
        if undeclared:
            halls = ", ".join(repr(h) for h in undeclared)
            these = "this hall" if len(undeclared) == 1 else "these halls"
            gaps.append(
                f"TN1 organization slice quota in {halls}: the plant says the job "
                f"occupies {these} and the tenancy block declares no quota state "
                "there, so the organization's slice count there was taken on trust"
            )
        elif not plant.job_halls and set(tenancy.declared_halls) <= {home}:
            # A crossing job occupies at least one hall beyond its own, so a
            # home-only declaration is known to be incomplete even with no
            # plant to say which hall is missing.
            gaps.append(
                f"TN1 organization slice quota beyond {home!r}: the job crosses a hall, "
                "the tenancy block declares a slice only in its home hall, and no plant "
                "model names the far hall, so the organization's slice count there was "
                "taken on trust"
            )
    if tenancy.lambda_sharing is None:
        gaps.append(
            f"TN2-TN4 wavelength sharing: tenancy block for {tenancy.org_id!r} declares "
            "no wavelength, so whatever else is on the stitch's wavelength was taken "
            "on trust"
        )
    return gaps


@dataclass(frozen=True)
class Verdict:
    """What the validator decided, and everything needed to argue with it."""

    decision: Decision
    findings: tuple
    #: Checks that were not run, and why. Printed rather than omitted, so a
    #: caller can never read a clean verdict as a complete one.
    not_checked: tuple = ()

    @property
    def allowed(self) -> bool:
        """True only for LOCAL and SPAN. SHRINK and MOVE are not this job."""
        return self.decision in (Decision.LOCAL, Decision.SPAN)

    @property
    def fail_closed_findings(self) -> tuple:
        return tuple(f for f in self.findings if f.fail_closed)

    def reasons(self) -> List[str]:
        return [f"[{f.rule_id}] {f.message}" for f in self.findings]


def validate(
    env: SpanEnvelope,
    policy: Optional[Policy] = None,
    plant: Optional[Plant] = None,
    *,
    rules: Optional[Iterable] = None,
) -> Verdict:
    """Run every rule and return the joined verdict.

    ``rules`` exists so the test suite can shuffle them and prove the order
    does not matter. Production callers should leave it alone.
    """
    policy = policy or Policy()
    plant = plant or Plant()
    active = tuple(rules) if rules is not None else RULES

    findings: List[Finding] = [
        f for f in (rule(env, policy) for rule in active) if f is not None
    ]
    findings += [
        f for f in (rule(env, policy, plant) for rule in PLANT_RULES) if f is not None
    ]

    not_checked: List[str] = []
    if env.spans_halls:
        if not plant.can_check_blast_radius:
            not_checked.append(
                "XP1 declared-vs-computed blast radius: no plant graph supplied, so the "
                "envelope's blast_radius was taken on trust"
            )
        if plant.current_topology_hash is None:
            not_checked.append(
                "XP2 topology currency: no live topology hash supplied, so the envelope's "
                "topology_hash was taken on trust"
            )
    not_checked += tenancy_gaps(env, plant)

    # A job that never leaves its hall is LOCAL. One that clears every rule and
    # asked to cross gets SPAN. Anything a rule objected to takes the most
    # severe objection.
    base = Decision.LOCAL if not env.spans_halls else Decision.SPAN
    decision = Decision.max([base] + [f.decision for f in findings])

    return Verdict(
        decision=decision,
        findings=tuple(findings),
        not_checked=tuple(not_checked),
    )


def audit_record(
    env: SpanEnvelope,
    verdict: Verdict,
    policy: Optional[Policy] = None,
    *,
    previous_hash: str = "",
) -> Dict[str, Any]:
    """A hash-chained record of one decision.

    The chain field is the SHA-256 of the previous record's chain field
    concatenated with this record's canonical body, which makes a truncated or
    edited log detectable without a signing key. It is a shape, not a product:
    a caller with an existing audit system should map these fields onto it
    rather than run two.
    """
    policy = policy or Policy()
    body = {
        "envelope": env.to_dict(),
        "decision": verdict.decision.value,
        "findings": [asdict(f) | {"decision": f.decision.value} for f in verdict.findings],
        "not_checked": list(verdict.not_checked),
        "policy": {k: (list(v) if isinstance(v, tuple) else v)
                   for k, v in asdict(policy).items()},
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    body["chain"] = hashlib.sha256((previous_hash + canonical).encode()).hexdigest()
    return body


def verify_chain(records: Sequence[Dict[str, Any]]) -> bool:
    """True when every record's chain field follows from the one before it."""
    previous = ""
    for record in records:
        body = {k: v for k, v in record.items() if k != "chain"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        expected = hashlib.sha256((previous + canonical).encode()).hexdigest()
        if record.get("chain") != expected:
            return False
        previous = expected
    return True
