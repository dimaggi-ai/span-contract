"""The span envelope: the twenty-one fields of specification section 4.3.

One object per job. The envelope is what a scheduler, a compiler, and a circuit
controller have to agree on before a job is allowed to cross a hall boundary,
and the point of writing it down is that today each of those three holds a
different half-truth about the topology.

The envelope is deliberately **inert**. It validates its own shape and computes
nothing about whether a span is a good idea; that is :mod:`spancontract.rules`.
Keeping the data model free of policy is what lets an operator carry the same
envelope through a planner, a validator, and an audit log without three
divergent notions of what the job asked for.

Three fields are worth reading twice, because they are the ones that make the
contract fail closed rather than fail quiet:

``topology_hash`` and ``measured_age_s``
    A declared topology and how long ago anyone last checked it. A compile cache
    keyed on a topology that no longer exists is the specification's third
    fail-closed condition, and staleness is not observable from the hash alone.

``stitch_api``
    How to reach the circuit controller. If it is dark, the contract cannot
    know the circuit state, and not knowing is a refusal rather than an
    assumption.

``blast_radius``
    How many halls one stitch failure takes down. A stitch that can black-hole
    two halls is the specification's own example of a decision a human has to
    make.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

from .decisions import SPAN_MODES, ScaleOut

#: Latency regimes, named to match the atlas in the ``network-vs-more-gpus``
#: repository so a verdict here can be read against a retention number there.
#: Upper bounds in microseconds, inclusive.
REGIME_BOUNDS: Tuple[Tuple[str, float], ...] = (
    ("scale-up", 1.0),
    ("rail", 5.0),
    ("campus-stitch", 80.0),
    ("metro", 2_000.0),
    ("region", float("inf")),
)

AUTONOMY_LEVELS = ("L0", "L1", "L2", "L3")


def latency_regime(rtt_us: float) -> str:
    """Name the regime a measured round-trip time falls in."""
    for name, upper in REGIME_BOUNDS:
        if rtt_us <= upper:
            return name
    return "region"


@dataclass(frozen=True)
class SliceRect:
    """A rectangular reservation inside one hall: ``{hall_id, origin, extent}``.

    Rectangular rather than a free set of node ids because the planner this
    feeds reserves sub-grids of a torus, where a non-rectangular reservation
    either fragments the interconnect or cannot be embedded at all.
    """

    hall_id: str
    origin: Tuple[int, ...]
    extent: Tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.hall_id:
            raise ValueError("slice_rect.hall_id must be non-empty")
        if len(self.origin) != len(self.extent):
            raise ValueError("slice_rect origin and extent must have equal rank")
        if not self.origin:
            raise ValueError("slice_rect must have rank >= 1")
        if any(o < 0 for o in self.origin):
            raise ValueError("slice_rect.origin must be non-negative")
        if any(e < 1 for e in self.extent):
            raise ValueError("slice_rect.extent must be positive in every dimension")

    @property
    def accelerators(self) -> int:
        n = 1
        for e in self.extent:
            n *= e
        return n

    def canonical(self) -> str:
        return json.dumps(
            {"hall_id": self.hall_id, "origin": list(self.origin), "extent": list(self.extent)},
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class SpanEnvelope:
    """The twenty-one first-class fields, plus the provenance to check them.

    Field order follows section 4.3 so the two can be read side by side.
    """

    # --- transport and mode -------------------------------------------------
    scale_out: ScaleOut
    span_mode: str

    # --- the stitch itself --------------------------------------------------
    span_rtt_us: float
    span_bw_gbps: float
    span_failure_domain: str

    # --- placement ----------------------------------------------------------
    slice_rect: SliceRect

    # --- circuit identity and health ---------------------------------------
    stitch_id: str
    stitch_api: str
    topology_hash: str
    measured_il_db: float
    measured_ber: float

    # --- time and throughput budgets ---------------------------------------
    checkpoint_window_s: float
    collective_window_s: float
    ingest_budget_GBps: float

    # --- plant envelope -----------------------------------------------------
    thermal_headroom_k: float
    ride_through_s: float
    power_headroom_kw: float

    # --- compilation --------------------------------------------------------
    compile_cache_key: str

    # --- governance ---------------------------------------------------------
    blast_radius: int
    autonomy_level: str
    requested_action: str

    # --- provenance, not part of the twenty-one but required to check them ---
    #: Age of the last path measurement, in seconds. ``None`` means never
    #: measured, which is treated as infinitely stale rather than as fresh.
    measured_age_s: Optional[float] = None
    #: Whether the circuit controller answered when last polled. ``None`` means
    #: it was not polled, which is not the same as answering "healthy".
    stitch_api_reachable: Optional[bool] = None
    #: Free-form, carried through to the audit record untouched.
    labels: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.span_mode not in SPAN_MODES:
            raise ValueError(
                f"span_mode {self.span_mode!r} not in {SPAN_MODES}; note that "
                "'escalate' is a decision but not a span_mode (DECISIONS.md D3)"
            )
        if self.autonomy_level not in AUTONOMY_LEVELS:
            raise ValueError(f"autonomy_level {self.autonomy_level!r} not in {AUTONOMY_LEVELS}")
        for name in ("span_rtt_us", "span_bw_gbps", "measured_il_db",
                     "checkpoint_window_s", "collective_window_s", "ingest_budget_GBps",
                     "thermal_headroom_k", "ride_through_s", "power_headroom_kw"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if not 0.0 <= self.measured_ber <= 1.0:
            raise ValueError("measured_ber must be a probability in [0, 1]")
        if self.blast_radius < 1:
            raise ValueError("blast_radius must be at least 1: a stitch failure always "
                             "takes down at least the hall that depends on it")
        if not self.stitch_id:
            raise ValueError("stitch_id must be non-empty")
        if not self.requested_action:
            raise ValueError("requested_action must be non-empty")

    # -- derived, but not policy --------------------------------------------

    @property
    def regime(self) -> str:
        return latency_regime(self.span_rtt_us)

    @property
    def spans_halls(self) -> bool:
        return self.span_mode != "local"

    def expected_compile_cache_key(self, graph_hash: str) -> str:
        """``hash(graph, slice_rect, stitch_id)``, exactly as section 4.3 states.

        The three inputs are the three things that invalidate a compiled plan:
        the graph, where it was placed, and what it was placed across. A cache
        keyed on any two of them will happily hand back a binary compiled for a
        topology that no longer exists.
        """
        payload = "|".join([graph_hash, self.slice_rect.canonical(), self.stitch_id])
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scale_out"] = self.scale_out.value
        d["slice_rect"] = {
            "hall_id": self.slice_rect.hall_id,
            "origin": list(self.slice_rect.origin),
            "extent": list(self.slice_rect.extent),
        }
        return d

    def replace(self, **changes: Any) -> "SpanEnvelope":
        return replace(self, **changes)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SpanEnvelope":
        d = dict(d)
        d["scale_out"] = ScaleOut(d["scale_out"])
        r = d["slice_rect"]
        d["slice_rect"] = SliceRect(r["hall_id"], tuple(r["origin"]), tuple(r["extent"]))
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown envelope fields: {sorted(unknown)}")
        return cls(**d)


#: The twenty-one field names of section 4.3, in specification order. Used by
#: the schema test to prove none has been quietly dropped or renamed.
SPEC_FIELDS: Tuple[str, ...] = (
    "scale_out",
    "span_mode",
    "span_rtt_us",
    "span_bw_gbps",
    "span_failure_domain",
    "slice_rect",
    "stitch_id",
    "stitch_api",
    "topology_hash",
    "measured_il_db",
    "measured_ber",
    "checkpoint_window_s",
    "collective_window_s",
    "ingest_budget_GBps",
    "thermal_headroom_k",
    "ride_through_s",
    "power_headroom_kw",
    "compile_cache_key",
    "blast_radius",
    "autonomy_level",
    "requested_action",
)
