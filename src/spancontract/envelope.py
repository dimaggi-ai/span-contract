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

One block is optional, and its absence is handled differently from the three
above. ``tenancy`` carries who the job belongs to, the organization's slice
allowance in each hall it takes a slice in, and what else is on the wavelength
its stitch would use. An envelope without it is not refused: the tenant
predicates are listed as *not checked*, by name, the way the plant
cross-checks are when no plant is supplied. Fail-closed is reserved for the
three states in which the contract does not know something it needs to decide
the crossing itself; an organization's quota is a policy its own scheduler
holds, and most first callers will not have it wired. DECISIONS.md D13.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

from .decisions import SPAN_MODES, ScaleOut
from .numeric import nonnegative

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

#: What a job asks of the wavelength it crosses on. ``dedicated`` means the
#: wavelength carries this job alone; ``shared`` means the job accepts
#: co-tenants from its own organization. Whether it may accept co-tenants from
#: *other* organizations is policy, not class: see ``Policy`` in rules.py.
TENANCY_CLASSES = ("dedicated", "shared")


def latency_regime(rtt_us: float) -> str:
    """Name the regime a measured round-trip time falls in."""
    nonnegative(rtt_us, "rtt_us")
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
        for x in self.origin + self.extent:
            nonnegative(x, "slice coordinate/extent", integer=True)
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
class SliceQuota:
    """An organization's slice allowance in one hall, as its scheduler declares it.

    ``held`` counts the slices the organization already holds in that hall
    *without* this job, so this job's own slice is the one that has to fit:
    there is room when ``held < quota``. A quota of zero is a ban and reads as
    one. Both numbers are claims carried in the envelope so the contract can
    check them against policy without asking anyone --- the envelope stays
    inert (DECISIONS.md D1) and the registry declines to say the claims are
    true.
    """

    hall_id: str
    held: int
    quota: int

    def __post_init__(self) -> None:
        if not self.hall_id:
            raise ValueError("slice quota hall_id must be non-empty")
        nonnegative(self.held, "held", integer=True)
        nonnegative(self.quota, "quota", integer=True)
        if self.held < 0:
            raise ValueError("slices held must be non-negative")
        if self.quota < 0:
            raise ValueError(
                "slice quota must be non-negative; zero means the organization may "
                "hold no slice in that hall"
            )

    @property
    def has_room(self) -> bool:
        """Whether this job's slice fits under the quota."""
        return self.held < self.quota

    def to_dict(self) -> Dict[str, Any]:
        return {"hall_id": self.hall_id, "held": self.held, "quota": self.quota}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SliceQuota":
        where = "tenancy.slices entry"
        _expect_block(d, where)
        _refuse_unknown(d, {"hall_id", "held", "quota"}, where)
        _require(d, ("hall_id", "held", "quota"), where)
        return cls(_str(d, "hall_id", where), _int(d, "held", where), _int(d, "quota", where))


@dataclass(frozen=True)
class CoTenant:
    """Another job already on the wavelength: whose it is, and which job."""

    org_id: str
    job_id: str

    def __post_init__(self) -> None:
        if not self.org_id:
            raise ValueError("co-tenant org_id must be non-empty")
        if not self.job_id:
            raise ValueError("co-tenant job_id must be non-empty")

    def to_dict(self) -> Dict[str, Any]:
        return {"org_id": self.org_id, "job_id": self.job_id}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CoTenant":
        where = "tenancy.lambda_sharing.co_tenants entry"
        _expect_block(d, where)
        _refuse_unknown(d, {"org_id", "job_id"}, where)
        _require(d, ("org_id", "job_id"), where)
        return cls(_str(d, "org_id", where), _str(d, "job_id", where))


@dataclass(frozen=True)
class LambdaSharing:
    """What is on the wavelength this job's stitch would use, as declared.

    ``co_tenants`` is the submitter's account of the jobs already carried on
    ``lambda_id``. ``must_not_share_with`` names jobs this one may never share
    a wavelength with, whoever owns them --- the specification's "this job may
    not share a lambda with that job", written down as a list rather than
    inferred. Neither is fetched; both are checked as claims.
    """

    lambda_id: str
    co_tenants: Tuple[CoTenant, ...] = ()
    must_not_share_with: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.lambda_id:
            raise ValueError("lambda_id must be non-empty")
        jobs = [c.job_id for c in self.co_tenants]
        if len(set(jobs)) != len(jobs):
            raise ValueError(f"co_tenants lists a job twice: {sorted(jobs)}")
        if any(not j for j in self.must_not_share_with):
            raise ValueError("must_not_share_with entries must be non-empty job ids")
        bans = list(self.must_not_share_with)
        if len(set(bans)) != len(bans):
            raise ValueError(f"must_not_share_with lists a job twice: {sorted(bans)}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lambda_id": self.lambda_id,
            "co_tenants": [c.to_dict() for c in self.co_tenants],
            "must_not_share_with": list(self.must_not_share_with),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LambdaSharing":
        where = "tenancy.lambda_sharing"
        _expect_block(d, where)
        _refuse_unknown(d, {"lambda_id", "co_tenants", "must_not_share_with"}, where)
        _require(d, ("lambda_id",), where)
        return cls(
            _str(d, "lambda_id", where),
            tuple(CoTenant.from_dict(c) for c in _list(d, "co_tenants", where)),
            tuple(
                _str_item(j, f"{where}.must_not_share_with")
                for j in _list(d, "must_not_share_with", where)
            ),
        )


@dataclass(frozen=True)
class Tenancy:
    """Who the job belongs to and what tenancy it declares. Optional on the envelope.

    Specification section 6, W7: "this org may take N slices in hall A; this
    job may not share a lambda with that job." Both predicates need state the
    twenty-one fields do not carry, and this block is where it is declared.

    ``slices`` holds one entry per hall the job takes a slice in. It must name
    the hall the envelope's ``slice_rect`` sits in --- a quota declaration that
    skipped the job's own hall would let that hall pass unchecked while reading
    as complete. Halls beyond it are declared by the submitter, and the quota
    itself is never fetched (DECISIONS.md D16); the validator only compares the
    halls declared here against the halls a plant model says the job occupies.
    """

    org_id: str
    tenancy_class: str
    slices: Tuple[SliceQuota, ...] = ()
    lambda_sharing: Optional[LambdaSharing] = None

    def __post_init__(self) -> None:
        if not self.org_id:
            raise ValueError("tenancy.org_id must be non-empty")
        if self.tenancy_class not in TENANCY_CLASSES:
            raise ValueError(
                f"tenancy_class {self.tenancy_class!r} not in {TENANCY_CLASSES}"
            )
        halls = [q.hall_id for q in self.slices]
        if len(set(halls)) != len(halls):
            raise ValueError(f"tenancy.slices names a hall twice: {sorted(halls)}")

    @property
    def declared_halls(self) -> Tuple[str, ...]:
        return tuple(q.hall_id for q in self.slices)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "org_id": self.org_id,
            "tenancy_class": self.tenancy_class,
            "slices": [q.to_dict() for q in self.slices],
            "lambda_sharing": (
                None if self.lambda_sharing is None else self.lambda_sharing.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Tenancy":
        where = "tenancy"
        _expect_block(d, where)
        _refuse_unknown(d, {"org_id", "tenancy_class", "slices", "lambda_sharing"}, where)
        _require(d, ("org_id", "tenancy_class"), where)
        sharing = d.get("lambda_sharing")
        return cls(
            _str(d, "org_id", where),
            _str(d, "tenancy_class", where),
            tuple(SliceQuota.from_dict(q) for q in _list(d, "slices", where)),
            None if sharing is None else LambdaSharing.from_dict(sharing),
        )


# The block's parsers are strict about types where the top-level parser is not:
# the schema is closed, and a block that coerced ``"4"`` to 4, ``null`` to a
# crash, or a string to a tuple of its characters would be the one place a
# schema-invalid document validated. Each refusal names the field.


def _expect_block(d: Any, where: str) -> None:
    """A block that is not an object is refused by name, not with a TypeError."""
    if not isinstance(d, dict):
        raise ValueError(f"{where} must be an object, got {type(d).__name__}")


def _str(d: Dict[str, Any], key: str, where: str) -> str:
    v = d[key]
    if not isinstance(v, str):
        raise ValueError(f"{where}.{key} must be a string, got {type(v).__name__}")
    return v


def _str_item(v: Any, where: str) -> str:
    if not isinstance(v, str):
        raise ValueError(f"{where} entries must be strings, got {type(v).__name__}")
    return v


def _int(d: Dict[str, Any], key: str, where: str) -> int:
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{where}.{key} must be an integer, got {v!r}")
    return v


def _list(d: Dict[str, Any], key: str, where: str) -> list:
    v = d.get(key, [])
    if not isinstance(v, (list, tuple)):
        raise ValueError(f"{where}.{key} must be an array, got {type(v).__name__}")
    return list(v)


def _require(d: Dict[str, Any], required: Tuple[str, ...], where: str) -> None:
    """A block missing a required key is refused by name, not with a KeyError."""
    missing = [k for k in required if k not in d]
    if missing:
        raise ValueError(f"{where} is missing required fields: {missing}")


def _refuse_unknown(d: Dict[str, Any], known: set, where: str) -> None:
    """An unknown key inside a block is refused, exactly as one at the top level is."""
    unknown = set(d) - known
    if unknown:
        raise ValueError(f"unknown {where} fields: {sorted(unknown)}")


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
    #: Optional. Who the job belongs to and the quota and wavelength state it
    #: declares. ``None`` means the tenant predicates are listed as not checked,
    #: not that they passed (DECISIONS.md D13).
    tenancy: Optional[Tenancy] = None

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
            nonnegative(getattr(self, name), name)
        nonnegative(self.measured_ber, "measured_ber")
        nonnegative(self.blast_radius, "blast_radius", integer=True)
        if self.measured_age_s is not None:
            nonnegative(self.measured_age_s, "measured_age_s")
        if not 0.0 <= self.measured_ber <= 1.0:
            raise ValueError("measured_ber must be a probability in [0, 1]")
        if self.blast_radius < 1:
            raise ValueError("blast_radius must be at least 1: a stitch failure always "
                             "takes down at least the hall that depends on it")
        if not self.stitch_id:
            raise ValueError("stitch_id must be non-empty")
        if not self.requested_action:
            raise ValueError("requested_action must be non-empty")
        if (
            self.tenancy is not None
            and self.tenancy.slices
            and self.slice_rect.hall_id not in self.tenancy.declared_halls
        ):
            raise ValueError(
                f"tenancy.slices names {list(self.tenancy.declared_halls)} but not "
                f"{self.slice_rect.hall_id!r}, the hall the slice_rect sits in; a quota "
                "declaration that skips the job's own hall would let it pass unchecked"
            )

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
        d["tenancy"] = None if self.tenancy is None else self.tenancy.to_dict()
        return d

    def replace(self, **changes: Any) -> "SpanEnvelope":
        return replace(self, **changes)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SpanEnvelope":
        d = dict(d)
        d["scale_out"] = ScaleOut(d["scale_out"])
        r = d["slice_rect"]
        d["slice_rect"] = SliceRect(r["hall_id"], tuple(r["origin"]), tuple(r["extent"]))
        tenancy = d.get("tenancy")
        d["tenancy"] = None if tenancy is None else Tenancy.from_dict(tenancy)
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
