"""The envelope's JSON Schema, generated from the dataclass.

Generated rather than hand-written, because a hand-written schema drifts from
the code the first time a field is renamed and then quietly accepts documents
the validator will reject. ``schema/span_contract.schema.json`` is this
function's output committed to the tree, and ``test_schema_matches_code``
fails if the two diverge.
"""

from __future__ import annotations

from typing import Any, Dict

from .decisions import SPAN_MODES, ScaleOut
from .envelope import AUTONOMY_LEVELS, SPEC_FIELDS, TENANCY_CLASSES

_NUMBER_FIELDS = (
    "span_rtt_us",
    "span_bw_gbps",
    "measured_il_db",
    "checkpoint_window_s",
    "collective_window_s",
    "ingest_budget_GBps",
    "thermal_headroom_k",
    "ride_through_s",
    "power_headroom_kw",
)

_DESCRIPTIONS = {
    "scale_out": "Transport the scale-out plane runs on.",
    "span_mode": (
        "Requested mode. Note that 'escalate' is a decision but not a span_mode; "
        "see DECISIONS.md D3."
    ),
    "span_rtt_us": "Measured round-trip time across the stitch, microseconds.",
    "span_bw_gbps": "Aggregate circuit bandwidth, gigabits per second. Shared, not per-rank.",
    "span_failure_domain": "Name of the domain a single stitch failure takes with it.",
    "slice_rect": "The rectangular reservation this job holds, inside one hall.",
    "stitch_id": "Identity of the circuit this job would cross.",
    "stitch_api": "Where to reach the circuit controller. Unreachable is a refusal.",
    "topology_hash": "Hash of the topology this job was planned against.",
    "measured_il_db": "Measured insertion loss, dB. Measured, not declared.",
    "measured_ber": "Measured pre-FEC bit error rate, as a probability.",
    "checkpoint_window_s": "Seconds the job needs to write a checkpoint.",
    "collective_window_s": "Seconds between collectives that cross the stitch.",
    "ingest_budget_GBps": "Data-path budget the job is entitled to, GB/s.",
    "thermal_headroom_k": "Kelvin of thermal headroom in the receiving hall.",
    "ride_through_s": "Seconds the hall rides through a power event.",
    "power_headroom_kw": "Spare power in the receiving hall, kW.",
    "compile_cache_key": "sha256(graph | slice_rect | stitch_id).",
    "blast_radius": "Halls whose share of this job stops if the stitch fails.",
    "autonomy_level": "L0 through L3. Production training stitches stay at L0/L1.",
    "requested_action": "What the job is asking to do, e.g. 'train' or 'infer'.",
}


def _tenancy_schema() -> Dict[str, Any]:
    """The optional tenancy block. Optional in the schema as in the code."""
    slice_quota = {
        "type": "object",
        "required": ["hall_id", "held", "quota"],
        "additionalProperties": False,
        "properties": {
            "hall_id": {"type": "string", "minLength": 1},
            "held": {
                "type": "integer", "minimum": 0,
                "description": "Slices the organization already holds in this hall, not counting this job.",
            },
            "quota": {
                "type": "integer", "minimum": 0,
                "description": "Slices the organization may hold in this hall. Zero is a ban.",
            },
        },
    }
    co_tenant = {
        "type": "object",
        "required": ["org_id", "job_id"],
        "additionalProperties": False,
        "properties": {
            "org_id": {"type": "string", "minLength": 1},
            "job_id": {"type": "string", "minLength": 1},
        },
    }
    lambda_sharing = {
        "type": ["object", "null"],
        "description": (
            "What is on the wavelength this job's stitch would use, as declared. "
            "null means the wavelength checks are listed as not checked."
        ),
        "required": ["lambda_id"],
        "additionalProperties": False,
        "properties": {
            "lambda_id": {"type": "string", "minLength": 1},
            "co_tenants": {
                "type": "array", "uniqueItems": True, "items": co_tenant,
                "description": "Jobs already carried on the wavelength, and whose they are.",
            },
            "must_not_share_with": {
                "type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1},
                "description": "Job ids this job may never share a wavelength with.",
            },
        },
    }
    return {
        "type": ["object", "null"],
        "description": (
            "Optional. Who the job belongs to, the isolation it asks for, and the quota "
            "and wavelength state it declares (section 6 W7). null means the tenant "
            "predicates TN1-TN4 are listed as not checked; it is not a failure."
        ),
        "required": ["org_id", "tenancy_class"],
        "additionalProperties": False,
        "properties": {
            "org_id": {"type": "string", "minLength": 1},
            "tenancy_class": {
                "type": "string", "enum": list(TENANCY_CLASSES),
                "description": "dedicated: the wavelength carries this job alone. shared: co-tenants from the job's own organization are accepted.",
            },
            "slices": {
                "type": "array", "uniqueItems": True, "items": slice_quota,
                "description": (
                    "One entry per hall the job takes a slice in. Must include the hall "
                    "the slice_rect sits in."
                ),
            },
            "lambda_sharing": lambda_sharing,
        },
    }


def envelope_schema() -> Dict[str, Any]:
    """A JSON Schema for the twenty-one fields plus provenance."""
    properties: Dict[str, Any] = {}
    for name in SPEC_FIELDS:
        prop: Dict[str, Any] = {"description": _DESCRIPTIONS[name]}
        if name == "scale_out":
            prop |= {"type": "string", "enum": [s.value for s in ScaleOut]}
        elif name == "span_mode":
            prop |= {"type": "string", "enum": list(SPAN_MODES)}
        elif name == "autonomy_level":
            prop |= {"type": "string", "enum": list(AUTONOMY_LEVELS)}
        elif name == "slice_rect":
            prop |= {
                "type": "object",
                "required": ["hall_id", "origin", "extent"],
                "additionalProperties": False,
                "properties": {
                    "hall_id": {"type": "string", "minLength": 1},
                    "origin": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "integer", "minimum": 0},
                    },
                    "extent": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "integer", "minimum": 1},
                    },
                },
            }
        elif name == "measured_ber":
            prop |= {"type": "number", "minimum": 0.0, "maximum": 1.0}
        elif name == "blast_radius":
            prop |= {"type": "integer", "minimum": 1}
        elif name in _NUMBER_FIELDS:
            prop |= {"type": "number", "minimum": 0.0}
        else:
            prop |= {"type": "string"}
        properties[name] = prop

    properties["measured_age_s"] = {
        "type": ["number", "null"], "minimum": 0.0,
        "description": "Age of the last path measurement, seconds. null means never measured.",
    }
    properties["stitch_api_reachable"] = {
        "type": ["boolean", "null"],
        "description": "Whether the controller answered. null means it was not polled.",
    }
    properties["labels"] = {
        "type": "object",
        "description": "Free-form, carried to the audit record untouched.",
    }
    properties["tenancy"] = _tenancy_schema()

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/dimaggi-ai/span-contract/schema/span_contract.schema.json",
        "title": "Span envelope",
        "description": (
            "One object per job: what a scheduler, a compiler, and a circuit controller "
            "must agree on before the job crosses a hall boundary."
        ),
        "type": "object",
        "required": list(SPEC_FIELDS),
        "additionalProperties": False,
        "properties": properties,
    }
