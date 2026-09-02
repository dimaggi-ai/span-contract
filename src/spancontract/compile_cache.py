"""A compile cache that cannot hand back a plan for a topology that is gone.

Specification section 4.3 keys the cache on ``(graph, slice_rect, stitch_id)``
and makes "the compile cache was keyed on a topology that no longer exists" one
of three fail-closed conditions. Those two statements are in tension, and the
tension is the whole reason this module exists: the key does *not* contain the
topology hash, so a cache built from the key alone cannot detect the condition
it is required to fail closed on.

This implementation resolves it by keying entries exactly as specified and
stamping each entry with the ``topology_hash`` that was live when it was
compiled. A lookup takes the *current* hash and refuses any entry stamped with
a different one. The key stays as specified; the staleness check rides
alongside it. DECISIONS.md D4 records the alternative --- folding the topology
hash into the key --- and why it was rejected: it would make every entry
unfindable after a retune rather than findable and refused, and "unfindable"
produces a silent recompile where "refused" produces an audit line.

A refused entry is not evicted. An operator asking why a job recompiled should
be able to see the entry that was rejected and the hash it was stamped with.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .envelope import SliceRect


def compile_cache_key(graph_hash: str, slice_rect: SliceRect, stitch_id: str) -> str:
    """``sha256(graph | slice_rect | stitch_id)``, section 4.3's key.

    Kept as a free function as well as a method on the envelope so a compiler
    that has not built an envelope yet can produce the same key.
    """
    if not graph_hash:
        raise ValueError("graph_hash must be non-empty")
    if not stitch_id:
        raise ValueError("stitch_id must be non-empty")
    payload = "|".join([graph_hash, slice_rect.canonical(), stitch_id])
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    """A compiled plan and the topology it was compiled against."""

    key: str
    topology_hash: str
    artifact: Any


@dataclass(frozen=True)
class Lookup:
    """The outcome of a lookup, including why a hit was refused."""

    entry: Optional[CacheEntry]
    status: str  # "hit" | "miss" | "stale"
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.status == "hit"


@dataclass
class CompileCache:
    """Keyed as specified; refuses entries stamped with a dead topology."""

    entries: Dict[str, CacheEntry] = field(default_factory=dict)
    #: Every refusal, in order, for the audit record.
    refusals: List[Tuple[str, str]] = field(default_factory=list)

    def put(self, key: str, topology_hash: str, artifact: Any) -> CacheEntry:
        if not topology_hash:
            raise ValueError(
                "an entry with no topology_hash could never be checked for staleness"
            )
        entry = CacheEntry(key=key, topology_hash=topology_hash, artifact=artifact)
        self.entries[key] = entry
        return entry

    def get(self, key: str, current_topology_hash: str) -> Lookup:
        entry = self.entries.get(key)
        if entry is None:
            return Lookup(None, "miss", "no entry for this (graph, slice_rect, stitch_id)")
        if entry.topology_hash != current_topology_hash:
            reason = (
                f"entry was compiled against topology {entry.topology_hash[:12]}..., "
                f"the plant is now {current_topology_hash[:12]}...; the placement it "
                "assumes no longer exists"
            )
            self.refusals.append((key, reason))
            return Lookup(entry, "stale", reason)
        return Lookup(entry, "hit")

    def stale_keys(self, current_topology_hash: str) -> List[str]:
        """Entries that would be refused right now, sorted for stable output."""
        return sorted(
            k for k, e in self.entries.items() if e.topology_hash != current_topology_hash
        )
