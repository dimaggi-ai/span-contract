"""The six decisions a span contract can return, and what each obliges.

These are the outputs in section 4.2 of the specification. They are an ordered
severity ladder, not a flat enum: a rule that fires can only move a verdict
*toward* refusal, never away from it, which is what makes the evaluation order
of the rules irrelevant to the result. ``Decision.max`` is that join.

One wrinkle is carried faithfully rather than smoothed over. The specification
lists six decisions here, but the ``span_mode`` envelope field in section 4.3
enumerates only five --- ``escalate`` is missing from it. Both are implemented
as written: a verdict can be ``escalate``, and ``span_mode`` cannot. See
DECISIONS.md D3 for why that is left as a discrepancy to resolve rather than
quietly patched in the schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class Decision(str, Enum):
    """What the contract decided, in increasing order of refusal."""

    LOCAL = "local"
    SPAN = "span"
    SHRINK = "shrink"
    MOVE = "move"
    ESCALATE = "escalate"
    DENY = "deny"

    @property
    def severity(self) -> int:
        return _SEVERITY[self]

    @property
    def permits_span(self) -> bool:
        """Whether the job is allowed to cross a hall boundary at all."""
        return self is Decision.SPAN

    @classmethod
    def max(cls, decisions: Iterable["Decision"]) -> "Decision":
        """The most refusing decision in the set; LOCAL if the set is empty.

        The join is what lets rules be evaluated in any order and still produce
        one answer. A rule never argues a verdict back down.
        """
        out = cls.LOCAL
        for d in decisions:
            if d.severity > out.severity:
                out = d
        return out


#: Severity is deliberately not the declaration order: ``move`` is a heavier
#: intervention than ``shrink`` because it relocates a job rather than resizing
#: it, and ``escalate`` outranks both because it stops automation entirely.
#: ``deny`` is the top because it is the only outcome that runs nothing.
_SEVERITY = {
    Decision.LOCAL: 0,
    Decision.SPAN: 1,
    Decision.SHRINK: 2,
    Decision.MOVE: 3,
    Decision.ESCALATE: 4,
    Decision.DENY: 5,
}

#: The values ``span_mode`` may take, per section 4.3. Not the same set as
#: ``Decision``: see the module docstring.
SPAN_MODES = ("local", "span", "shrink", "move", "deny")


class ScaleOut(str, Enum):
    """Transport the job's scale-out plane runs on, per section 4.3."""

    IB = "ib"
    ROCE = "roce"
    ETHERNET = "ethernet"
    OCS_STITCHED = "ocs_stitched"
    METRO_ROADM = "metro_roadm"
    CAMPUS_FIBER = "campus_fiber"
    VENDOR = "vendor"

    @property
    def crosses_halls(self) -> bool:
        """Whether this transport is a hall-crossing one by construction."""
        return self in (ScaleOut.OCS_STITCHED, ScaleOut.METRO_ROADM, ScaleOut.CAMPUS_FIBER)
