"""The rules that turn an envelope into a decision.

Every rule is a pure function from ``(envelope, policy)`` to zero or one
:class:`Finding`. A rule may only push the verdict *toward* refusal, so the
order they run in cannot change the answer --- the validator joins them with
:meth:`Decision.max`. That property is asserted directly in the test suite by
shuffling the rule list.

Every threshold lives in :class:`Policy`. None is written inline. An operator
who disagrees with a number changes one field and can see in the audit record
which policy produced a verdict, which is the difference between a contract and
an opinion.

Three of these rules are the specification's fail-closed conditions and are not
negotiable by policy: a dark circuit API, a stale path measurement, and a
compile cache keyed on a topology that no longer exists. Each of the three
describes a state in which the contract *does not know* something it needs, and
in each case not knowing is a refusal. A validator that treated silence as
health would be worse than no validator, because it would be trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .decisions import Decision
from .envelope import SpanEnvelope


@dataclass(frozen=True)
class Finding:
    """One rule's objection, with the rule that raised it."""

    rule_id: str
    decision: Decision
    message: str
    #: Set when the rule is one of the specification's fail-closed conditions,
    #: which no policy may relax.
    fail_closed: bool = False


@dataclass(frozen=True)
class Policy:
    """Every threshold the rules use. No rule contains a bare number.

    The defaults are stated as *conservative starting points*, not as measured
    values. Two of them are traceable to the latency-regime atlas in the
    ``network-vs-more-gpus`` repository; the rest are operator choices that this
    repository does not claim to have validated. ASSUMPTIONS.md records which
    is which, and ``validation/validate_contract.py`` declines to calibrate the
    ones with no external anchor.
    """

    #: Path measurements older than this are stale. Fail-closed condition 2.
    measurement_ttl_s: float = 300.0
    #: Round-trip time above which synchronous training must not span.
    #: Anchored to the atlas: the pipeline cut's retention falls away in the
    #: metro band and no cut survives beyond it.
    sync_training_max_rtt_us: float = 2_000.0
    #: Round-trip time above which a tensor-parallel cut must not span at all.
    #: The atlas puts tensor-parallel retention at 0.004 in every regime tested,
    #: so this is effectively "never", written as a number for auditability.
    tensor_parallel_max_rtt_us: float = 0.0
    #: Insertion loss budget for a healthy circuit, in dB.
    max_insertion_loss_db: float = 20.0
    #: Pre-FEC bit error rate above which a circuit is not fit to carry a job.
    max_bit_error_rate: float = 1e-9
    #: Halls one stitch failure may take down before a human is required.
    max_autonomous_blast_radius: int = 1
    #: Autonomy levels at which a production training stitch may be automated.
    #: Section 4.1: "Production training stitches stay at L0/L1."
    training_autonomy_levels: Tuple[str, ...] = ("L0", "L1")
    #: Actions treated as production training for the rule above.
    training_actions: Tuple[str, ...] = ("train", "pretrain", "finetune", "continue_pretrain")
    #: A checkpoint must finish inside the ride-through of the hall it lands in,
    #: or a power event during the write leaves no usable checkpoint.
    require_checkpoint_within_ride_through: bool = True
    #: Minimum plant headroom before a hall may accept a spanned job.
    min_thermal_headroom_k: float = 0.0
    min_power_headroom_kw: float = 0.0


# --------------------------------------------------------------------------
# fail-closed conditions, section 4.3
# --------------------------------------------------------------------------


def rule_circuit_api_dark(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """FC1. The circuit controller did not answer, so its state is unknown."""
    if not env.spans_halls:
        return None
    if env.stitch_api_reachable is True:
        return None
    detail = ("was never polled" if env.stitch_api_reachable is None else "did not answer")
    return Finding(
        "FC1", Decision.DENY,
        f"circuit API {env.stitch_api!r} {detail}; the state of stitch "
        f"{env.stitch_id!r} is unknown and unknown is not healthy",
        fail_closed=True,
    )


def rule_measurement_stale(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """FC2. The declared path has not been measured recently enough to trust."""
    if not env.spans_halls:
        return None
    if env.measured_age_s is None:
        return Finding(
            "FC2", Decision.DENY,
            f"path for stitch {env.stitch_id!r} has never been measured; a declared "
            "topology is a claim, not an observation",
            fail_closed=True,
        )
    if env.measured_age_s > policy.measurement_ttl_s:
        return Finding(
            "FC2", Decision.DENY,
            f"path measurement is {env.measured_age_s:.0f}s old, past the "
            f"{policy.measurement_ttl_s:.0f}s TTL",
            fail_closed=True,
        )
    return None


def rule_compile_cache_stale(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """FC3. The cached plan was keyed on a topology that no longer exists.

    Checked by recomputing the key from the envelope's own ``slice_rect`` and
    ``stitch_id``. If the carried key does not match, the compiled artifact
    belongs to a different placement, and running it is the failure mode this
    field exists to prevent.
    """
    if not env.spans_halls:
        return None
    if not env.compile_cache_key:
        return Finding(
            "FC3", Decision.DENY,
            "compile_cache_key is empty; a spanned job must name the plan it "
            "intends to run", fail_closed=True,
        )
    graph = env.labels.get("graph_hash")
    if graph is None:
        return Finding(
            "FC3", Decision.DENY,
            "no graph_hash supplied, so compile_cache_key cannot be checked "
            "against the placement it claims to describe", fail_closed=True,
        )
    expected = env.expected_compile_cache_key(str(graph))
    if expected != env.compile_cache_key:
        return Finding(
            "FC3", Decision.DENY,
            "compile_cache_key was keyed on a different (graph, slice_rect, stitch_id): "
            f"carried {env.compile_cache_key[:12]}..., placement implies {expected[:12]}...",
            fail_closed=True,
        )
    return None


# --------------------------------------------------------------------------
# latency regime, section 2
# --------------------------------------------------------------------------


def rule_synchronous_training_regime(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """LR1. Synchronous training does not cross a contended metro or worse."""
    if not env.spans_halls or env.requested_action not in policy.training_actions:
        return None
    if env.span_rtt_us > policy.sync_training_max_rtt_us:
        return Finding(
            "LR1", Decision.DENY,
            f"synchronous {env.requested_action} at {env.span_rtt_us:.0f} us RTT "
            f"({env.regime}) exceeds the {policy.sync_training_max_rtt_us:.0f} us limit; "
            "the default policy is that training stays hall-local",
        )
    return None


def rule_tensor_parallel_never_spans(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """LR2. A tensor-parallel cut may not cross a stitch.

    The atlas measures tensor-parallel retention at 0.004 in every regime it
    tests, including the shortest. This is not a distance judgement: tensor
    parallelism pays the stitch once per layer per micro-batch, so no circuit
    width rescues it.
    """
    cut = str(env.labels.get("cut", "")).lower()
    if not env.spans_halls or cut not in ("tp", "tensor", "tensor_parallel"):
        return None
    if env.span_rtt_us > policy.tensor_parallel_max_rtt_us:
        return Finding(
            "LR2", Decision.SHRINK,
            "a tensor-parallel cut across a stitch retains almost no useful capacity "
            "at any distance; a pipeline or checkpoint boundary is the legal cut",
        )
    return None


# --------------------------------------------------------------------------
# circuit health
# --------------------------------------------------------------------------


def rule_insertion_loss(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """CH1. Measured insertion loss is outside the budget for a healthy path."""
    if not env.spans_halls:
        return None
    if env.measured_il_db > policy.max_insertion_loss_db:
        return Finding(
            "CH1", Decision.DENY,
            f"measured insertion loss {env.measured_il_db:.1f} dB exceeds the "
            f"{policy.max_insertion_loss_db:.1f} dB budget",
        )
    return None


def rule_bit_error_rate(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """CH2. Measured error rate is above what the job can absorb."""
    if not env.spans_halls:
        return None
    if env.measured_ber > policy.max_bit_error_rate:
        return Finding(
            "CH2", Decision.DENY,
            f"measured BER {env.measured_ber:.2e} exceeds the "
            f"{policy.max_bit_error_rate:.0e} threshold",
        )
    return None


# --------------------------------------------------------------------------
# governance
# --------------------------------------------------------------------------


def rule_blast_radius(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """GV1. A stitch that can black-hole more than one hall needs a human.

    The specification's own example of an escalation. A blast radius above one
    means the failure of a single circuit removes capacity an operator did not
    knowingly couple together.
    """
    if not env.spans_halls:
        return None
    if env.blast_radius > policy.max_autonomous_blast_radius:
        return Finding(
            "GV1", Decision.ESCALATE,
            f"stitch {env.stitch_id!r} has blast radius {env.blast_radius} "
            f"(limit {policy.max_autonomous_blast_radius}); one circuit failure would "
            f"take down {env.blast_radius} halls, which is a human's decision",
        )
    return None


def rule_training_autonomy(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """GV2. Production training stitches stay at L0/L1."""
    if not env.spans_halls or env.requested_action not in policy.training_actions:
        return None
    if env.autonomy_level not in policy.training_autonomy_levels:
        return Finding(
            "GV2", Decision.ESCALATE,
            f"{env.requested_action} at autonomy {env.autonomy_level} would stitch halls "
            f"without a human in the loop; production training stitches stay at "
            f"{'/'.join(policy.training_autonomy_levels)}",
        )
    return None


# --------------------------------------------------------------------------
# plant envelope
# --------------------------------------------------------------------------


def rule_checkpoint_within_ride_through(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """PL1. A checkpoint must finish inside the hall's ride-through.

    Otherwise a power event during the write leaves a torn checkpoint and the
    job restarts from the previous one, which is the case the ride-through
    figure exists to prevent.
    """
    if not policy.require_checkpoint_within_ride_through or not env.spans_halls:
        return None
    if env.checkpoint_window_s > env.ride_through_s:
        return Finding(
            "PL1", Decision.SHRINK,
            f"checkpoint window {env.checkpoint_window_s:.0f}s exceeds ride-through "
            f"{env.ride_through_s:.0f}s; a power event mid-write leaves nothing usable",
        )
    return None


def rule_thermal_headroom(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """PL2. A hall with no thermal headroom cannot accept more work."""
    if not env.spans_halls:
        return None
    if env.thermal_headroom_k <= policy.min_thermal_headroom_k:
        return Finding(
            "PL2", Decision.DENY,
            f"thermal headroom {env.thermal_headroom_k:.1f} K is at or below the "
            f"{policy.min_thermal_headroom_k:.1f} K floor",
        )
    return None


def rule_power_headroom(env: SpanEnvelope, policy: Policy) -> Optional[Finding]:
    """PL3. A hall with no power headroom cannot accept more work."""
    if not env.spans_halls:
        return None
    if env.power_headroom_kw <= policy.min_power_headroom_kw:
        return Finding(
            "PL3", Decision.DENY,
            f"power headroom {env.power_headroom_kw:.0f} kW is at or below the "
            f"{policy.min_power_headroom_kw:.0f} kW floor",
        )
    return None


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------


def rule_checkpoint_contends_with_collective(
    env: SpanEnvelope, policy: Policy
) -> Optional[Finding]:
    """ST1. A checkpoint and a collective may not want the stitch at once.

    Both cross the same circuit. If the checkpoint window overlaps the
    collective window, the two contend for one aggregate circuit and neither
    completes in the time it was budgeted.
    """
    if not env.spans_halls:
        return None
    if env.collective_window_s <= 0 or env.checkpoint_window_s <= 0:
        return None
    if env.checkpoint_window_s > env.collective_window_s:
        return Finding(
            "ST1", Decision.SHRINK,
            f"checkpoint window {env.checkpoint_window_s:.0f}s is longer than the "
            f"{env.collective_window_s:.0f}s collective window, so the two contend for "
            "one circuit; co-schedule them or shrink the state that crosses",
        )
    return None


#: Every rule, in a fixed order for readability only. The validator's result
#: does not depend on this order, and ``test_rule_order_is_irrelevant`` proves
#: it by shuffling.
RULES: Tuple[Callable[[SpanEnvelope, Policy], Optional[Finding]], ...] = (
    rule_circuit_api_dark,
    rule_measurement_stale,
    rule_compile_cache_stale,
    rule_synchronous_training_regime,
    rule_tensor_parallel_never_spans,
    rule_insertion_loss,
    rule_bit_error_rate,
    rule_blast_radius,
    rule_training_autonomy,
    rule_checkpoint_within_ride_through,
    rule_thermal_headroom,
    rule_power_headroom,
    rule_checkpoint_contends_with_collective,
)

#: The three conditions section 4.3 requires to fail closed. Asserted present.
FAIL_CLOSED_RULE_IDS: Tuple[str, ...] = ("FC1", "FC2", "FC3")
