# Status

Last updated: 2026-09-02.

## Current phase

**Published. 1.1.0 adds the tenant predicates of specification section 6, W7.**
1.0.0 (2026-09-01) and 1.0.1 (2026-09-02) are on GitHub and PyPI, tagged and
released, with an index card on `dimaggi-ai.github.io/research`. 1.1.0 adds an
optional `tenancy` block and four rules that read it, and is the release this
file ships with.

## What is done

| Piece | State |
|---|---|
| Envelope: the twenty-one fields of section 4.3 | complete, with a generated JSON Schema and a test that fails if the two drift |
| Tenancy: an optional block, four predicates TN1–TN4, taken on trust when absent | complete; D13–D16 |
| Decisions: the six of section 4.2, on a severity ladder | complete; the join is proved order-free over 400 random envelopes |
| Rules: three fail-closed conditions, ten admission rules, four tenant predicates | complete; every threshold and switch in `Policy`, none inline |
| Plant model: halls, circuits, blast radius, single points of failure | complete |
| Compile cache: keyed as specified, refuses a dead topology | complete |
| Emulated delay node (section 9, sequence item 7) | complete, with the `tc` line to reproduce it on real kernels |
| Validation registry | 25 points, 1 calibrated / 12 emergent / 12 sanity, 11 declined |
| Mutation tests | 18, each naming the exact set of points it must turn red |
| Tests | 150 passing |
| Examples | 16, each checked against its documented verdict |
| CLI, packaging, CI, PyPI | complete; `pip install span-contract` |

## What is deliberately absent

**A driver for a real circuit controller.** The adapter surface is one method.
Writing an OCS or ROADM driver against a plant nobody has run this on would be
fiction, and it would be the most quotable part of the repository.

**A quota service.** Tenancy is declared on the envelope and never fetched. The
contract has no second adapter surface for bookkeeping the scheduler already
holds (D16).

**Any claim that the thresholds are right.** They are conservative starting
points. The registry's DECLINED list says so in eleven separate places rather
than once in a footnote.

**Any coupling to a policy engine or audit product.** The record is a plain
dictionary with a hash chain. `docs/integration.md` describes the surface an
existing engine would bind to, and stops there.

## Blocked on someone else

Section 9's eighth and ninth sequence items need a named plant with a documented
circuit API — a lab OCS, a university ROADM testbed, or a design partner. Until
one exists, every verdict in this repository is a verdict about a constructed
envelope, and the registry says so.

## Next

Nothing is scheduled in this repository. The specification's W7 is closed by
1.1.0; section 9 items 8 and 9 wait on a named plant.
