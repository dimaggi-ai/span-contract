# Assumptions

Everything this repository takes as given. Each entry says what would have to be
true for it to hold, and what breaks if it does not.

---

**A1. The policy defaults are conservative starting points, not measured values.**
`measurement_ttl_s=300`, `max_insertion_loss_db=20`, `max_bit_error_rate=1e-9`,
`sync_training_max_rtt_us=2000`, `max_autonomous_blast_radius=1`. None is
anchored to a published figure. They are in `Policy` so that an operator who
disagrees changes one field, and so that the audit record shows which numbers
produced a verdict. *If wrong:* verdicts are wrong in a knowable direction, and
the record says exactly which threshold was responsible.

**A2. A synchronous training job survives no partition.**
The basis for the all-or-nothing blast radius (D5). *If wrong* — for an
asynchronous or elastic job — the blast radius overstates the damage, and this
model should not be applied to it without change.

**A3. The declared circuit graph is the failure graph.**
`load_bearing_stitches` sees the circuits an operator listed, not the ducts they
run through. Two circuits down one trench are one failure wearing two names, and
nothing here can see it. *If wrong:* a job passes the redundancy check and is
still a single failure away from stopping. This is the most likely way for a
green verdict in this repository to be wrong about a real plant.

**A4. The emulated circuit models amplifier gain and not its noise cost.**
Real amplifiers cost optical signal-to-noise ratio, and OSNR is what sets the
error rate on a long span. An amplified path in the emulator reports a
comfortable insertion loss and a bit error rate the caller supplied. *Consequence:*
the emulator can demonstrate that the contract refuses an unhealthy circuit. It
cannot support a claim that any particular circuit is healthy.

**A5. A job's reservation is a rectangle inside one hall.**
`SliceRect` is a hall id, an origin and an extent. Rectangular rather than a free
set of node ids, because the planner this feeds reserves sub-grids of a torus,
where a non-rectangular reservation either fragments the interconnect or cannot
be embedded. *If wrong:* the compile cache key is keyed on the wrong description
of the placement.

**A6. A job has one anchor hall.**
Blast radius is computed relative to it. Reasonable for a job with a rank zero
and a checkpoint target; not reasonable for a fully symmetric job with no home.
*If wrong:* the computed blast radius depends on an arbitrary choice.

**A7. Checkpoint and collective contention is modelled as a window comparison
only.** Rule ST1 compares two durations. It does not model the actual bandwidth
each would take, or when in the step they land. *Consequence:* ST1 catches the
gross case and will miss a checkpoint that fits inside the window but collides
with the collective inside it.

**A8. One TTL covers every kind of measurement.**
Round-trip time, insertion loss and error rate share `measurement_ttl_s`. In a
real plant they age at very different rates: a fibre's loss changes over months,
its round-trip time when someone reroutes it. *If wrong:* the TTL is set for the
fastest-moving quantity and forces needless re-measurement of the others.

**A9. Single-mode fibre at a group index near 1.4682 and 0.2 dB/km at 1550 nm.**
Standard planning figures for G.652 fibre. Real plant runs higher loss once
splices and connectors are counted, which is why `excess_loss_db` is a separate
field rather than folded into the per-kilometre rate.

**A10. The twenty-one fields are taken as given.**
This repository implements the specification's field set; it did not derive it
and does not claim it is sufficient. The registry can show the set is internally
consistent and matches the specification. Whether it is everything a real
admission decision needs is a question only a plant can answer, and the DECLINED
list says so.

**A11. Autonomy levels are ordered L0 < L1 < L2 < L3 and the meaning of each is
the specification's.** The rules only ever test membership in a set, never an
inequality, so the ordering is not relied on — but the field name implies it and
a reader will assume it.
