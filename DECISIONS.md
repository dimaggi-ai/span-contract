# Decision Log

Every decision that changed the scope, the data model, or what this repository
is willing to claim. Dated, with the reasoning that drove it.

---

## D1. The envelope is inert; every judgement lives in the rules
**Date:** 2026-09-01.

`SpanEnvelope` validates its own shape and computes nothing about whether a span
is a good idea. The alternative — methods like `is_safe()` on the data model —
was rejected because the same envelope has to travel through a planner, a
validator and an audit log, and a data model that carries policy gives those
three places three divergent notions of what the job asked for.

Consequence: the envelope can be serialised, stored and replayed against a
*different* policy, which is what makes the audit record worth keeping.

---

## D2. Decisions join with a maximum, so rule order cannot change the answer
**Date:** 2026-09-01.

The six decisions are a severity ladder rather than a flat enum, and a rule may
only push the verdict toward refusal. This is the difference between a contract
and a script: with a join, "which rule ran first" is not a question anyone has to
ask, and adding a rule can never accidentally permit something.

The ordering is deliberately not the declaration order. `move` outranks `shrink`
because relocating a job is a heavier intervention than resizing it, `escalate`
outranks both because it stops automation entirely, and `deny` is the top because
it is the only outcome that runs nothing.

Proved rather than asserted: the registry shuffles the rule list over 400 random
envelopes and requires every verdict to be unchanged.

---

## D3. The specification's `span_mode` gap is carried, not reconciled
**Date:** 2026-09-01.

Section 4.2 lists six decisions. Section 4.3's `span_mode` field enumerates five;
`escalate` is missing. Three options were considered:

1. Add `escalate` to `span_mode` and treat the omission as a typo.
2. Remove `escalate` from the decisions and treat 4.2 as the typo.
3. Implement both exactly as written and record the discrepancy.

Option 3 was chosen. The two are not obviously the same kind of thing: a
`span_mode` is what a job *requests*, and `escalate` is not a mode a job can ask
for — it is what the contract does when it will not decide alone. Read that way
the specification may be right, and reconciling it would have destroyed the
distinction. Read the other way it is an oversight, and the person who wrote the
specification should be the one to say which.

Implemented as: `SpanEnvelope` raises on `span_mode="escalate"` with a message
pointing here, and a registry point asserts the gap still exists — so closing it
later shows up as a failing check rather than as a tidy-up in a diff. A mutation
test (`test_reconcile_the_span_mode_discrepancy`) confirms that point bites.

---

## D4. The compile cache key stays as specified; the topology hash rides alongside
**Date:** 2026-09-01.

The specification keys the cache on `(graph, slice_rect, stitch_id)` and *also*
requires the contract to fail closed when "the compile cache was keyed on a
topology that no longer exists". Those two statements are in tension: the key
contains no topology hash, so a cache built from the key alone cannot detect the
condition it must fail closed on.

Rejected: folding the topology hash into the key. It would make every entry
unfindable after a retune, which produces a silent recompile. The specified
behaviour is a *refusal*, and a refusal produces an audit line.

Chosen: key exactly as specified, stamp each entry with the topology hash live
when it was compiled, and refuse on mismatch at lookup. A refused entry is kept
rather than evicted, so an operator asking why a job recompiled can see what was
rejected and what it was stamped with.

---

## D5. Blast radius is all-or-nothing
**Date:** 2026-09-01.

A synchronous job survives no partition. If a stitch failure separates any hall
the job occupies from its anchor, the whole job stops — so every hall it occupies
is inside the blast radius, and there is no partial credit.

This was chosen over a "fraction of capacity lost" measure, which would have been
gentler and wrong. A job spread over four halls does not lose a quarter of its
throughput when a load-bearing circuit drops. It loses all of it, and the three
surviving halls hold reserved, powered, idle accelerators until someone
reschedules.

The visible consequence, which the registry records as an emergent point:
redundancy shows up as a drop from *n* straight to 1, never as a slope.

---

## D6. Plant cross-checks live in the validator, not in the rule set
**Date:** 2026-09-01.

A rule sees only what the job declared. Comparing a declaration against the plant
is a different kind of check and needs an argument the envelope does not carry.
Keeping the two apart means the rule set runs with no plant model at all, which
is the state most first-time callers will be in.

Consequence, and the reason this is a decision rather than a detail: a verdict
with no plant supplied is *weaker* than one with a plant, and that has to be
visible. `Verdict.not_checked` names each cross-check that was skipped and why,
and the CLI prints it. A clean verdict must never be readable as a complete one.

---

## D7. No coupling to any particular policy engine or audit product
**Date:** 2026-09-01.

The source specification proposes routing these decisions through an existing
governance engine, reusing its endpoint and its log format. That was not done.

An admission contract that only works inside one vendor's engine is that vendor's
feature, not a contract. The value here is the *schema* and the reasoning — which
facts must be agreed on, and which absences are refusals — and both survive being
implemented by someone else's engine. `docs/integration.md` describes the surface
an existing engine would bind to and stops there; this repository ships no
integration.

The hash-chained record is included as a *shape*, not a system. Anyone with an
audit pipeline should map these fields onto it rather than run two.

---

## D8. The only shipped adapter is an emulator
**Date:** 2026-09-01.

The adapter surface is one method: `probe(stitch_id) -> PathMeasurement`. An
emulated delay node implements it, which is what section 9's seventh sequence
item asks for and what a reader can run today.

No OCS or ROADM driver ships. Writing one against a plant nobody has run this on
would be fiction, and it would be the most quotable thing in the repository.

---

## D9. This repository decides admission; it holds no opinion on capacity
**Date:** 2026-09-01.

What a job *retains* across a given cut is measured by the latency-regime atlas
in `network-vs-more-gpus`. Two things follow.

The emulated delay node returns the numbers a controller would return so the
plumbing can be exercised. It does not model queueing, congestion, or the
contention between a collective and a checkpoint on one circuit, and it must not
be read as a second opinion on capacity.

The regime names and boundaries in `envelope.py` deliberately match the atlas, so
a verdict here can be read against a retention number there. Where a rule cites a
retention figure — the tensor-parallel rule does — it cites the atlas and does
not recompute it.

---

## D10. A dark probe leaves the declared numbers untouched
**Date:** 2026-09-01.

When the controller does not answer, `apply_measurement` sets
`stitch_api_reachable=False` and changes nothing else. It does not zero the
measured fields, and it does not substitute pessimistic ones.

Substituting values would have produced the same refusal by a worse route: the
audit record would show a circuit that looked broken, rather than a circuit
nobody could reach. Those are different incidents and they get different
responses. The envelope records what was claimed, separately from the fact that
nobody could confirm it, and rule FC1 turns the second into the refusal.

---

## D11. One calibrated point, and the DECLINED list does the rest
**Date:** 2026-09-01.

The registry has exactly one calibrated point, and it is about the emulator's
propagation delay, not about the contract.

This is the honest count. No published figure says a path measurement goes stale
at three hundred seconds, or that twenty decibels is the right loss budget. Those
are operator choices. Every attempt to find an anchor for them produced either a
circular check — confirming the code reproduces its own constant — or a number
borrowed from an unrelated context and dressed up.

So the DECLINED list was nine entries long at 1.0.0 (eleven at 1.1.0, D16) and
is printed on every run, above the
pass count. A registry that manufactured six calibrated points here would look
more rigorous and be less true.

Related: the one calibrated point's acceptance band is `[4.5, 5.5)` rather than a
percentage tolerance, because the published figure carries one significant
figure. Writing the band as "what rounds to 5" keeps the criterion a property of
how the anchor was published, rather than a number chosen once the model's answer
was known.

---

## D12. Registry points report failure; they never crash the run
**Date:** 2026-09-01.

Found while writing the mutation tests: under one mutation a point hit a state
its author had not anticipated and raised, which aborted the run and hid every
point after it. A registry that stops looking once it finds a problem is not a
registry.

Fixed in two places. `run_registry` catches per point and reports the exception
as a failure, and the point that raised was rewritten to return a failing result
with an explanation instead of asserting.

A second defect surfaced the same way: the audit-chain point tampered with a
record by rewriting its verdict from `deny` to `span`, which is only an edit when
the verdict was not already `span`. Deleting an unrelated rule made it a no-op and
the point passed while detecting nothing. It now edits a recorded measurement,
which always differs.

---

## D13. An absent tenancy block is taken on trust, not failed closed
**Date:** 2026-09-02.

Section 6 of the specification, under W7, asks for two refusals the 1.0 rules
could not make: *this org may take N slices in hall A*, and *this job may not
share a λ with that job*. They are implemented as an optional `tenancy` block on
the envelope and four rules, TN1–TN4. The question was what an envelope with no
block gets. Three options:

1. Fail closed: no tenancy, no admission — the FC1–FC3 pattern.
2. Make the block mandatory in the schema — a 2.0 change; every 1.0 caller breaks.
3. Admit, and list the tenancy checks in `not_checked` by name — the XP1/XP2
   pattern for a missing plant.

Option 3 was chosen. Fail-closed is reserved for the three ignorance conditions
the specification names, and each of those is the *plant* failing to answer a
question the contract must have answered. An absent tenancy block is a different
absence: a caller that has not wired its organization's bookkeeping yet.
Refusing it would be option 2 by the back door, and would turn every 1.0
envelope into a refusal in a minor release.

Consequence: a verdict on a tenancy-free envelope is weaker than one on a
declared envelope, and says so in two lines (`TN1`, `TN2-TN4`). A partial block
is handled the same way, granularly — no quota state, a `TN1` line; no
wavelength, a `TN2-TN4` line; a hall the plant says the job occupies that the
block does not cover, a `TN1` line naming it; a block that declares only the
home hall of a crossing job when no plant names the far hall, a `TN1` line
saying the far hall's count was taken on trust (a crossing job occupies a hall
beyond its own by definition, so that incompleteness is known without a plant).
A registry point checks the pattern across 400 random envelopes with the block
removed, and two mutation tests bite: one silences the gap lines, and one
inverts this decision by adding a rule that refuses absent blocks, which turns
six points red — the two about absent blocks, three that need the tenancy-free
reference envelope to move, and the three-conditions point, which finds a
fourth fail-closed rule.

---

## D14. Tenant predicates apply to crossings only, and the home hall must be declared
**Date:** 2026-09-02.

Every rule in this repository is gated on the job leaving its hall, and a
registry point asserts that a hall-local job gets no findings. The tenant
predicates follow the same gate. A hall-local job's slice is admitted by the
slice packer under its own tenancy model — `slice-packer-torus` has one — and a
local job uses no wavelength, so an organization that has spent its quota in its home hall
with a local job is the slice packer's refusal, not this one's. The random
population the hall-local point draws from now carries tenancy blocks half the
time, so the gate is tested rather than assumed.

The second half: a block that declares quota state must include the hall the
`slice_rect` sits in. Without that, a declaration covering only the far hall
would let TN1 pass on the hall the job actually takes a slice in. The envelope
refuses the shape at construction rather than the rule tolerating it. Halls the
*plant* says the job occupies that the block does not cover are a gap, not a
refusal — D13's reasoning again.

---

## D15. Every tenant refusal is `deny`
**Date:** 2026-09-02.

`escalate` and `move` were considered. `escalate` is for the questions the
specification reserves for a human — a blast radius past the autonomous limit,
an autonomy level too high for the action — and a spent quota carries no
question: the organization may hold no more slices there, and that is the
policy's whole content. `move` would have the contract name a hall it cannot
see; the rule set runs with no plant model (D6), and a `move` toward an
undeclared hall is a guess presented as an instruction.

So all four are `deny`, with PL2 and PL3 as the analogue: a limit that is simply
exhausted. Policy can relax three of them, by name — `enforce_org_slice_quota`,
`allow_lambda_sharing_across_orgs`, `dedicated_tenancy_classes` — and the audit
record shows when it did. The pairwise ban, TN4, has no switch. It is the job's
own declaration about itself, and a policy that overrode it would be overriding
the submitter rather than the operator.

---

## D16. Quota state is declared, never fetched
**Date:** 2026-09-02.

The contract stays inert (D1): no network, no quota service. `held`, `quota`
and the wavelength's occupancy are on the envelope, as `measured_il_db` is —
claims the audit record carries.

Rejected: a second adapter surface, a `QuotaSource` beside `StitchController`.
The controller protocol exists because the fail-closed conditions need a
measurement's *age* and *reachability*, which are qualities of an observation.
A quota is bookkeeping the scheduler already holds, and a second adapter would
double the integration burden for a number the caller has in hand.

Consequence: the DECLINED list gains two entries. No published figure fixes any
organization's quota, so TN1 is checked for effect and never for correctness;
and the contract cannot see whether a declared occupancy is true. A wrong
declaration is a wrong verdict, and the record makes it findable afterwards —
it does not make it catchable at admission. `ASSUMPTIONS.md` A12 and A13 say
what has to hold.
