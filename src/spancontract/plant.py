"""The plant as the contract sees it: halls, circuits, and what one failure costs.

``blast_radius`` is a field in the envelope, which means a planner declares it.
This module computes it instead, so the validator can check the declaration
against the plant rather than believe it. A declared blast radius that
understates the computed one is the interesting failure: it is how a job gets
admitted at an autonomy level that the plant does not actually support.

The definition used here is deliberately blunt, and worth stating plainly
because a gentler one would flatter the design:

    A synchronous job survives no partition. If a stitch failure separates any
    hall the job occupies from the hall holding its anchor, the whole job
    stops, so every hall it occupies is inside the blast radius.

There is no partial credit. A job spread over four halls does not lose a
quarter of its throughput when a load-bearing circuit drops; it loses all of
it, and the three surviving halls hold reserved, powered, idle accelerators
until someone reschedules. That is the number an operator needs, and it is
larger than the one that a "capacity lost" metric would report.

A stitch with a parallel path is not load-bearing, and its blast radius is 1:
the job keeps running, and only the hall's own local failure would stop it.
Redundancy shows up here as a drop from *n* to 1, not as a gentle slope, which
is the honest shape of the effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Set, Tuple


@dataclass(frozen=True)
class Stitch:
    """A circuit joining two or more halls."""

    stitch_id: str
    halls: FrozenSet[str]

    def __post_init__(self) -> None:
        if not self.stitch_id:
            raise ValueError("stitch_id must be non-empty")
        if len(self.halls) < 2:
            raise ValueError(
                f"stitch {self.stitch_id!r} joins {len(self.halls)} hall(s); a stitch "
                "that does not cross a hall boundary is not a stitch"
            )


@dataclass(frozen=True)
class SpanGraph:
    """The halls of a plant and the circuits between them."""

    halls: FrozenSet[str]
    stitches: Tuple[Stitch, ...] = ()

    def __post_init__(self) -> None:
        if not self.halls:
            raise ValueError("a span graph needs at least one hall")
        seen: Set[str] = set()
        for s in self.stitches:
            if s.stitch_id in seen:
                raise ValueError(f"duplicate stitch_id {s.stitch_id!r}")
            seen.add(s.stitch_id)
            missing = s.halls - self.halls
            if missing:
                raise ValueError(
                    f"stitch {s.stitch_id!r} names halls not in the plant: {sorted(missing)}"
                )

    def stitch(self, stitch_id: str) -> Stitch:
        for s in self.stitches:
            if s.stitch_id == stitch_id:
                return s
        raise KeyError(f"no stitch {stitch_id!r} in this plant")

    def reachable(self, anchor: str, *, without: Optional[str] = None) -> Set[str]:
        """Halls reachable from ``anchor``, optionally with one stitch removed."""
        if anchor not in self.halls:
            raise KeyError(f"no hall {anchor!r} in this plant")
        adjacency: Dict[str, Set[str]] = {h: set() for h in self.halls}
        for s in self.stitches:
            if s.stitch_id == without:
                continue
            for a in s.halls:
                adjacency[a] |= s.halls - {a}
        seen = {anchor}
        frontier = [anchor]
        while frontier:
            here = frontier.pop()
            for there in adjacency[here]:
                if there not in seen:
                    seen.add(there)
                    frontier.append(there)
        return seen


def severed_halls(
    graph: SpanGraph, stitch_id: str, job_halls: Iterable[str], anchor: str
) -> Set[str]:
    """Job halls that lose their path to ``anchor`` when this stitch fails."""
    job = set(job_halls)
    unknown = job - graph.halls
    if unknown:
        raise KeyError(f"job names halls not in the plant: {sorted(unknown)}")
    if anchor not in job:
        raise ValueError(f"anchor {anchor!r} must be one of the job's halls")
    graph.stitch(stitch_id)  # raises if the plant has no such circuit
    still_reachable = graph.reachable(anchor, without=stitch_id)
    return job - still_reachable


def blast_radius(
    graph: SpanGraph, stitch_id: str, job_halls: Iterable[str], anchor: str
) -> int:
    """Halls whose share of the job stops when this stitch fails.

    Returns ``len(job_halls)`` when the stitch is load-bearing for this job,
    and 1 otherwise. See the module docstring for why there is no value in
    between.
    """
    job = set(job_halls)
    if severed_halls(graph, stitch_id, job, anchor):
        return len(job)
    return 1


def load_bearing_stitches(
    graph: SpanGraph, job_halls: Iterable[str], anchor: str
) -> List[str]:
    """Every stitch whose single failure would stop this job, in plant order.

    The list is the job's single points of failure. An empty list on a job that
    spans halls means every crossing has a parallel path --- which is worth
    checking rather than assuming, because two circuits down the same conduit
    are one failure wearing two names. This function sees the graph an operator
    declared, not the ducts, so it cannot tell the difference; ASSUMPTIONS.md
    records that limit.
    """
    job = set(job_halls)
    return [
        s.stitch_id
        for s in graph.stitches
        if severed_halls(graph, s.stitch_id, job, anchor)
    ]
