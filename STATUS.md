# Status

Last updated: 2026-09-01.

## Current phase

**Complete and internally verified; not yet published.** The contract, the
reference validator, the emulated adapter, the registry and the mutation suite
are finished and green. Publication to GitHub and PyPI is pending the project
owner's approval, which is required and has not been given.

## What is done

| Piece | State |
|---|---|
| Envelope: the twenty-one fields of section 4.3 | complete, with a generated JSON Schema and a test that fails if the two drift |
| Decisions: the six of section 4.2, on a severity ladder | complete; the join is proved order-free over 400 random envelopes |
| Rules: three fail-closed conditions plus ten admission rules | complete; every threshold in `Policy`, none inline |
| Plant model: halls, circuits, blast radius, single points of failure | complete |
| Compile cache: keyed as specified, refuses a dead topology | complete |
| Emulated delay node (section 9, sequence item 7) | complete, with the `tc` line to reproduce it on real kernels |
| Validation registry | 18 points, 1 calibrated / 7 emergent / 10 sanity, 9 declined |
| Mutation tests | 12, each naming the exact set of points it must turn red |
| Tests | 91 passing |
| Examples | 11, each checked against its documented verdict |
| CLI, packaging, CI | complete |

## What is deliberately absent

**A driver for a real circuit controller.** The adapter surface is one method.
Writing an OCS or ROADM driver against a plant nobody has run this on would be
fiction, and it would be the most quotable part of the repository.

**Any claim that the thresholds are right.** They are conservative starting
points. The registry's DECLINED list says so in nine separate places rather than
once in a footnote.

**Any coupling to a policy engine or audit product.** The record is a plain
dictionary with a hash chain. `docs/integration.md` describes the surface an
existing engine would bind to, and stops there.

## Blocked on someone else

Section 9's eighth and ninth sequence items need a named plant with a documented
circuit API — a lab OCS, a university ROADM testbed, or a design partner. Until
one exists, every verdict in this repository is a verdict about a constructed
envelope, and the registry says so.

## Next

1. Owner approval to publish.
2. GitHub repository, tagged release, PyPI.
3. An index card on `dimaggi-ai.github.io/research`, and a cross-link from
   `network-vs-more-gpus` — the atlas answers what a job retains, this answers
   whether it may try.
