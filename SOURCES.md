# Sources

Every external reference this repository relies on. A source is listed here only
if something in the code or the registry actually cites it; a citation that
points at nothing is worse than no citation.

---

**S1. Signal propagation in single-mode fibre: approximately 5 microseconds per
kilometre, one way.**
A planning figure quoted widely in optical transmission and latency-engineering
practice, derived from the group velocity in silica (group index near 1.47, so
roughly 4.9 µs/km). Used as the external anchor for the registry's single
calibrated point.

*Why it can serve as an anchor:* the code computes latency from a group index
constant, and the rule of thumb is quoted independently of that constant, so the
check is not the code confirming its own input. *Its weakness, stated plainly:*
one significant figure. The acceptance band is `[4.5, 5.5)` for that reason, and
the point is worth exactly what a one-significant-figure anchor is worth.

**S2. `DIMAGGI_Scale_Across_Comprehensive_v1.0`.**
The specification this repository implements: section 4.1 (inputs), section 4.2
(the six decisions), section 4.3 (the twenty-one envelope fields and the three
fail-closed conditions), section 9 (the sequence of work). Not a public document.
Where the implementation departs from it, `DECISIONS.md` says so and why —
see D3, D4 and D7.

**S3. `network-vs-more-gpus` — the latency-regime atlas.**
https://github.com/dimaggi-ai/network-vs-more-gpus

The sibling study that measures what a job *retains* across a cut. Two things are
taken from it: the regime names and boundaries, so a verdict here can be read
against a retention number there; and the finding that a tensor-parallel cut
retains 0.004 across a stitch at every distance and width tested, which is the
basis for rule LR2. No figure from it is recomputed here (D9).

**S4. ITU-T G.652 single-mode fibre, attenuation at 1550 nm.**
The origin of the 0.2 dB/km constant in the delay node. Cited for provenance
only: the registry **declines** to make a calibrated point of it, because the
emulator uses the figure as an input and a check would confirm the code
reproduces its own constant.

**S5. Linux `netem`.**
The kernel queueing discipline that `DelayNode.netem_command` emits a command
for. Emitted, never executed here — whether the kernel reproduces the modelled
path is untested in this repository, and the registry declines that too.
