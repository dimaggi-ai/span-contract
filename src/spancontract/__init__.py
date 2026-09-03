"""span-contract: one object a job carries when it wants to cross a hall.

A scale-across decision is made today by three systems that do not talk: a
scheduler that knows how many accelerators are free, a compiler that knows what
plan it emitted, and a circuit controller that knows what glass is lit. Each
holds a different half-truth about the topology, and the job finds out which
one was wrong at step time.

This package is the object that makes them agree before the job starts: a
twenty-one field envelope, six decisions, three conditions that fail closed,
four tenant predicates that are taken on trust when the envelope does not
declare tenancy, and a reference validator that turns the first into the
second and prints the reasons. It decides admission. It does not decide capacity --- what a job
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
    TENANCY_CLASSES,
    CoTenant,
    LambdaSharing,
    SliceQuota,
    SliceRect,
    SpanEnvelope,
    Tenancy,
    latency_regime,
)
from .rules import FAIL_CLOSED_RULE_IDS, RULES, TENANT_RULE_IDS, Finding, Policy
from .validator import Plant, Verdict, audit_record, tenancy_gaps, validate, verify_chain

__version__ = "1.1.0"

__all__ = [
    "AUTONOMY_LEVELS",
    "CoTenant",
    "CompileCache",
    "Decision",
    "FAIL_CLOSED_RULE_IDS",
    "Finding",
    "LambdaSharing",
    "Plant",
    "Policy",
    "REGIME_BOUNDS",
    "RULES",
    "SPAN_MODES",
    "SPEC_FIELDS",
    "ScaleOut",
    "SliceQuota",
    "SliceRect",
    "SpanEnvelope",
    "SpanGraph",
    "Stitch",
    "TENANCY_CLASSES",
    "TENANT_RULE_IDS",
    "Tenancy",
    "Verdict",
    "audit_record",
    "blast_radius",
    "compile_cache_key",
    "latency_regime",
    "load_bearing_stitches",
    "tenancy_gaps",
    "validate",
    "verify_chain",
    "__version__",
]
