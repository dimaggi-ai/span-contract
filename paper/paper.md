# The Span Contract: Fail-Closed Admission for AI Training Jobs That Cross a Data Hall

**Margaret Nanyonga**, DIMAGGI AI

> Staged whitepaper. The claims, figures, and numbers here are reproduced
> by the accompanying open-source repository
> (`dimaggi-ai/span-contract`, MIT).

## Abstract

When a training job asks to run across more than one data hall, three
systems hold the facts that decide whether it should: the scheduler knows
what is free, the compiler knows what topology its plan assumed, and the
circuit controller knows what glass is lit. None of them talks to the
others, and the job discovers which half-truth was wrong at step time — or
at checkpoint time, three hours in. We propose a single admission object
that makes them agree before launch: an envelope of twenty-one fields, six
decisions (`local`, `span`, `shrink`, `move`, `escalate`, `deny`), and
three conditions under which the contract refuses rather than guesses. The
design principle is that **not knowing is a refusal**: a dark circuit API,
a path measurement stale past its TTL, or a compile cache keyed to a
topology that no longer exists each fails the admission closed, because a
validator that reads silence as health is worse than no validator — it
would be trusted. Rules join on a severity ladder by maximum, so a rule
can push a verdict toward refusal and never away from it; the registry
proves order-irrelevance by shuffling the rule list over 400 random
envelopes and requiring identical verdicts. Admission is deliberately
separated from capacity: the contract decides *whether* a job may cross,
and defers *what it would retain* to the latency-regime atlas of the
companion repository, which shows a tensor-parallel cut retaining 0.004 of
its throughput across any stitch at any distance — the contract is what
refuses to launch that job. The verdict flips out of a measured delay, not
a configuration: driven end to end through an emulated circuit controller,
the same job admits as `span` at 40 km and is refused at 400. Since 1.1.0
the envelope may also declare the job's tenancy — its organization's slice
quota per hall and what already shares the wavelength its stitch would use
— and four tenant predicates refuse an organization that has spent its quota, two
organizations on one wavelength, a dedicated job that would share, and a
job sharing with one it may not. They read declarations and fetch nothing,
and an envelope that declares no tenancy is not refused for it; those
checks are listed as not made: fail-closed is reserved for the
plant not answering, not for a caller that has not wired its bookkeeping.

## 1. The contract

The envelope is inert by design — twenty-one declared fields, no methods
that reach the network. The validator turns declarations into a verdict
and prints, alongside its findings, the list of what it *could not check*:
an envelope validated without a plant graph says so, rather than letting a
blast-radius figure taken on trust read as one that was verified. Policy
rules carry every threshold by name (none inline); the default policy holds
synchronous training at 2,000 microseconds of round-trip time — the top of
the metro regime, so the tighter two of the three regimes that cross a
hall — past which training stays hall-local. One specification discrepancy
is carried rather than fixed —
the decision list contains `escalate` and the `span_mode` field cannot —
and a registry point asserts the gap is still there, so a future tidy-up
surfaces as a failing check rather than a silent semantic change.

The tenant predicates of the specification's research program — *this org
may take N slices in hall A; this job may not share a λ with that job* —
arrive as an optional `tenancy` block and four rules that read it. Isolation
on a raw inter-chip mesh is geometry and optics, so two organizations on
one wavelength is two tenants on one piece of glass, and the default policy
refuses it. Every tenant refusal is `deny`: a spent quota carries no
question for a human, and the contract cannot see the hall a `move` would
name. What an undeclared block gets was the design decision. It is not a
refusal, because the three ignorance conditions each describe the plant
failing to answer, and an absent declaration is a caller that has not
wired its bookkeeping; refusing it would make the block mandatory in all
but name. Instead the verdict carries two more not-checked lines, and a
registry point holds that pattern across 400 random envelopes with the
block removed, while a mutation test that inverts the decision turns six
points red.

## 2. Validation

The registry holds twenty-five points and refuses to skip: one calibrated
point (the honest count — no published figure fixes any threshold here,
and none fixes an organization's quota), twelve emergent, and twelve
sanity, with eleven declined items printed before any result. Eighteen
mutation tests delete machinery — a fail-closed condition, the severity
join, the blast-radius computation, the cache's topology check, the probe's
silence about a dark controller, each tenant predicate, the lines that say
what was not checked — or reverse a recorded decision, and assert the
*measured* set of points that go red, against a control proving the
unmutated registry is green. The suite is 150 tests,
25/25 points, and sixteen example envelopes each checked against its
documented verdict.

## 3. What a skeptic should attack

No verdict here has been checked against a job that actually ran. The
emulated circuit models amplifier gain without the optical
signal-to-noise cost that comes with it, so it can demonstrate a refusal
but cannot support a claim of health. The thresholds are policy proposals,
not standards; a site that draws the synchronous-training line elsewhere
is not wrong. The tenant predicates check declarations: a quota snapshot
that is stale or an occupancy list that is incomplete produces a green
verdict that is wrong about the hall, and the contract cannot see either.
And the contract's value rests on an institutional claim —
that three systems will accept one envelope as the meeting point — which
no artifact can prove from inside a repository.

## 4. Conclusion

The expensive failure in cross-hall training is not the slow stitch; it is
the launch that should not have happened, discovered after the capital was
committed. An admission contract that fails closed on ignorance, joins its
rules so they can only tighten, and prints what it declined to check moves
that discovery to before the job starts — and its verdict can be made to
flip by a measured delay alone, which is the property that separates a
contract from a configuration file.
