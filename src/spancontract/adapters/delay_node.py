"""An emulated stitch: a delay node standing in for a circuit.

Section 9's seventh sequence item is to prove the contract against an emulated
delay node before anyone points it at glass. This module is that node. It
answers probes the way a circuit controller would, with a round-trip time, an
insertion loss, an error rate, and --- the part that matters --- the ability to
be *dark*, so the fail-closed path is exercised by something other than a unit
test constructing the failure by hand.

What this is not: a network simulator. It does not model queueing, congestion,
or the interaction between a collective and a checkpoint on one circuit. It
returns the numbers a controller would return so that the contract's plumbing
can be exercised end to end. The capacity question --- what a job actually
retains across a given cut --- is answered by the model in the
``network-vs-more-gpus`` repository, not here, and this module deliberately
does not offer a second opinion on it.

One limit is worth stating before anyone reads a green result as an
engineering answer. Amplification is modelled as gain and nothing else. Real
amplifiers cost optical signal-to-noise ratio, and OSNR is what actually sets
the error rate on a long span, so an amplified path here reports a comfortable
insertion loss and a bit error rate the caller made up. The emulator can show
that the contract *refuses* an unhealthy circuit; it cannot be used to argue a
particular circuit is healthy. ASSUMPTIONS.md A4 records this.

To run the same shape against real kernels rather than this object,
:func:`DelayNode.netem_command` prints the ``tc`` line that reproduces its
delay and loss on a Linux box between two halls. That is the bridge from this
file to a lab, and it is one command long.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional, Protocol, runtime_checkable

from ..envelope import SpanEnvelope, latency_regime
from ..numeric import nonnegative

#: Speed of light in single-mode fibre, metres per second. Group index ~1.4682.
FIBRE_C_M_PER_S = 299_792_458.0 / 1.4682
#: Loss of a typical single-mode span at 1550 nm, dB per km. A planning figure,
#: not a measurement of any particular cable: real plant runs higher once
#: splices and connectors are counted, which is why the emulator lets a caller
#: add a fixed penalty rather than pretending this is the whole loss.
FIBRE_LOSS_DB_PER_KM = 0.20


@dataclass(frozen=True)
class PathMeasurement:
    """What a controller returns when asked about a circuit.

    ``reachable=False`` is a real answer and a different thing from an
    exception: the probe completed and the controller is dark. ``None`` for the
    numbers in that case, because a dark controller reports nothing, and
    carrying a stale number forward as if it were fresh is the failure this
    whole contract exists to prevent.
    """

    stitch_id: str
    reachable: bool
    rtt_us: Optional[float] = None
    insertion_loss_db: Optional[float] = None
    bit_error_rate: Optional[float] = None
    bandwidth_gbps: Optional[float] = None
    age_s: float = 0.0

    def __post_init__(self):
        nonnegative(self.age_s, "age_s")
        for name in ("rtt_us", "insertion_loss_db", "bit_error_rate", "bandwidth_gbps"):
            value = getattr(self, name)
            if value is not None:
                nonnegative(value, name)
        if self.bit_error_rate is not None and self.bit_error_rate > 1:
            raise ValueError("bit_error_rate must be <= 1")

    @property
    def regime(self) -> Optional[str]:
        return None if self.rtt_us is None else latency_regime(self.rtt_us)


@runtime_checkable
class StitchController(Protocol):
    """The one thing the contract needs from a circuit controller."""

    def probe(self, stitch_id: str) -> PathMeasurement:
        """Return the current state of the path, or a dark answer."""
        ...


@dataclass(frozen=True)
class DelayNode:
    """An emulated circuit between two halls.

    Round-trip time is derived from the fibre length rather than set directly,
    so a caller changing the distance cannot forget to change the latency --- a
    mistake that makes an emulator agree with whatever it is testing.
    """

    stitch_id: str
    distance_km: float
    bandwidth_gbps: float = 800.0
    #: Loss beyond the fibre itself: splices, patch panels, an OCS crossbar.
    excess_loss_db: float = 2.0
    #: Total amplifier gain on the path, in dB. Zero models an unamplified
    #: span, which is why a long one here trips the loss budget: at 0.2 dB/km a
    #: 120 km hop arrives 26 dB down, and a real one would carry amplifiers.
    #: Set this to model an amplified path --- but see the class docstring for
    #: what that does *not* buy you.
    amplifier_gain_db: float = 0.0
    bit_error_rate: float = 1e-12
    #: Extra one-way latency from transponders and any regeneration, in
    #: microseconds. Real metro paths are not pure glass.
    equipment_latency_us: float = 10.0
    #: Set to False to emulate a dark controller.
    reachable: bool = True
    #: How stale the controller's own last measurement is.
    age_s: float = 0.0

    def __post_init__(self) -> None:
        for name in ("distance_km", "bandwidth_gbps", "excess_loss_db", "amplifier_gain_db",
                     "bit_error_rate", "equipment_latency_us", "age_s"):
            nonnegative(getattr(self, name), name)
        if self.distance_km < 0:
            raise ValueError("distance_km must be non-negative")
        if self.bandwidth_gbps <= 0:
            raise ValueError("bandwidth_gbps must be positive")
        if not 0.0 <= self.bit_error_rate <= 1.0:
            raise ValueError("bit_error_rate must be a probability in [0, 1]")
        if self.amplifier_gain_db < 0:
            raise ValueError("amplifier_gain_db must be non-negative")

    @property
    def rtt_us(self) -> float:
        """Round trip: two passes through the glass, plus the equipment."""
        one_way_s = (self.distance_km * 1_000.0) / FIBRE_C_M_PER_S
        return 2.0 * (one_way_s * 1e6 + self.equipment_latency_us)

    @property
    def insertion_loss_db(self) -> float:
        loss = self.distance_km * FIBRE_LOSS_DB_PER_KM + self.excess_loss_db
        return max(0.0, loss - self.amplifier_gain_db)

    def go_dark(self) -> "DelayNode":
        """The same node with its controller unreachable."""
        return replace(self, reachable=False)

    def aged(self, seconds: float) -> "DelayNode":
        """The same node whose last measurement is ``seconds`` old."""
        return replace(self, age_s=seconds)

    def measure(self) -> PathMeasurement:
        if not self.reachable:
            return PathMeasurement(self.stitch_id, reachable=False, age_s=self.age_s)
        return PathMeasurement(
            stitch_id=self.stitch_id,
            reachable=True,
            rtt_us=self.rtt_us,
            insertion_loss_db=self.insertion_loss_db,
            bit_error_rate=self.bit_error_rate,
            bandwidth_gbps=self.bandwidth_gbps,
            age_s=self.age_s,
        )

    def netem_command(self, interface: str = "eth0") -> str:
        """The ``tc`` line reproducing this node's delay on a Linux box.

        Emitted rather than executed. Running it needs root on a machine
        between two halls, which is a decision for whoever owns that machine.
        Loss is expressed as a percentage, so a bit error rate below 1e-8
        rounds to zero here --- netem cannot express it, and the command says
        so instead of silently dropping the term.
        """
        one_way_ms = self.rtt_us / 2_000.0
        loss_pct = self.bit_error_rate * 100.0
        parts = [
            f"tc qdisc replace dev {interface} root netem",
            f"delay {one_way_ms:.3f}ms",
            f"rate {self.bandwidth_gbps:.0f}gbit",
        ]
        if loss_pct >= 1e-6:
            parts.append(f"loss {loss_pct:.6f}%")
        else:
            parts.append(f"# loss {loss_pct:.3e}% below netem resolution, omitted")
        return " ".join(parts)


@dataclass(frozen=True)
class EmulatedController:
    """A :class:`StitchController` over a set of delay nodes."""

    nodes: tuple

    def node(self, stitch_id: str) -> DelayNode:
        for n in self.nodes:
            if n.stitch_id == stitch_id:
                return n
        raise KeyError(f"no emulated stitch {stitch_id!r}")

    def probe(self, stitch_id: str) -> PathMeasurement:
        return self.node(stitch_id).measure()


def apply_measurement(env: SpanEnvelope, m: PathMeasurement) -> SpanEnvelope:
    """Fill an envelope's measured fields from a probe.

    A dark probe leaves the declared numbers untouched and sets
    ``stitch_api_reachable`` to False. It does *not* zero them or invent
    pessimistic ones: the envelope should record what was declared and,
    separately, that nobody could confirm it. Rule FC1 turns that into a
    refusal, which keeps the reason for the refusal legible in the audit
    record instead of hidden behind a substituted value.
    """
    if m.stitch_id != env.stitch_id:
        raise ValueError(
            f"measurement is for stitch {m.stitch_id!r}, envelope names {env.stitch_id!r}"
        )
    if not m.reachable:
        return env.replace(stitch_api_reachable=False, measured_age_s=m.age_s)
    changes = {"stitch_api_reachable": True, "measured_age_s": m.age_s}
    if m.rtt_us is not None:
        changes["span_rtt_us"] = m.rtt_us
    if m.insertion_loss_db is not None:
        changes["measured_il_db"] = m.insertion_loss_db
    if m.bit_error_rate is not None:
        changes["measured_ber"] = m.bit_error_rate
    if m.bandwidth_gbps is not None:
        changes["span_bw_gbps"] = m.bandwidth_gbps
    return env.replace(**changes)
