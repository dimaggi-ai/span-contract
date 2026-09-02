"""Adapters between the contract and something that can answer for a circuit.

The contract needs one thing from the outside world: a measurement of the path,
with an age and an honest "I could not reach the controller". That is the whole
:class:`StitchController` surface. Everything else in this repository works off
the envelope.

Two adapters ship here. :mod:`spancontract.adapters.delay_node` is an emulated
circuit, which is what section 9's seventh sequence item asks for and what a
reader can run today. A real controller --- a lab OCS, a campus ROADM --- binds
to the same protocol; this repository does not ship one, because writing a
driver against a plant nobody has run it on would be fiction.
"""

from .delay_node import (
    DelayNode,
    EmulatedController,
    PathMeasurement,
    StitchController,
    apply_measurement,
)

__all__ = [
    "DelayNode",
    "EmulatedController",
    "PathMeasurement",
    "StitchController",
    "apply_measurement",
]
