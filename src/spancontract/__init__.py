"""span-contract: one object a job carries when it wants to cross a hall.

A scale-across decision is made today by three systems that do not talk: a
scheduler that knows how many accelerators are free, a compiler that knows what
plan it emitted, and a circuit controller that knows what glass is lit. Each
holds a different half-truth about the topology, and the job finds out which
one was wrong at step time.

This package is the object that makes them agree before the job starts: a
twenty-one field envelope, six decisions, three conditions that fail closed,
and a reference validator that turns the first into the second and prints the
reasons. It decides admission. It does not decide capacity --- what a job
retains across a given cut is answered by the latency-regime atlas in the
``network-vs-more-gpus`` repository, and this package deliberately holds no
second opinion on it.

    >>> from spancontract import SpanEnvelope, validate
    >>> verdict = validate(envelope)   # doctest: +SKIP
    >>> verdict.decision, verdict.reasons()   # doctest: +SKIP
"""

from .plant import SpanGraph, Stitch, blast_radius, load_bearing_stitches
from .compile_cache import CompileCache, compile_cache_key
from .decisions import SPAN_MODES, Decision, ScaleOut
from .envelope import (
    AUTONOMY_LEVELS,
    REGIME_BOUNDS,
    SPEC_FIELDS,
    SliceRect,
    SpanEnvelope,
    latency_regime,
)
from .rules import FAIL_CLOSED_RULE_IDS, RULES, Finding, Policy
from .validator import Plant, Verdict, audit_record, validate, verify_chain

__version__ = "1.0.0"

__all__ = [
    "AUTONOMY_LEVELS",
    "CompileCache",
    "Decision",
    "FAIL_CLOSED_RULE_IDS",
    "Finding",
    "Plant",
    "Policy",
    "REGIME_BOUNDS",
    "RULES",
    "SPAN_MODES",
    "SPEC_FIELDS",
    "ScaleOut",
    "SliceRect",
    "SpanEnvelope",
    "SpanGraph",
    "Stitch",
    "Verdict",
    "audit_record",
    "blast_radius",
    "compile_cache_key",
    "latency_regime",
    "load_bearing_stitches",
    "validate",
    "verify_chain",
    "__version__",
]
