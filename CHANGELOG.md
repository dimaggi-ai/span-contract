# Changelog

## 1.1.0 — 2026-09-02

Tenant predicates: specification section 6, W7 — "this org may take N slices
in hall A; this job may not share a λ with that job."

- An optional `tenancy` block on the envelope: the organization, its tenancy
  class (`dedicated` or `shared`), its slice count and quota per hall, and what
  is already on the wavelength the stitch would use. Declared by the caller,
  never fetched (D16). Unknown and missing keys are refused by name. Optional in
  the schema as in the code: an envelope without it is a 1.0 envelope and
  reaches the same decision and findings as before. Its audit record now also
  carries `tenancy: null`, the three new policy keys and the two new not-checked
  lines, so its chain hash differs from the one 1.0.1 wrote: stored chains still
  verify, but a 1.0.1 record cannot be re-derived by 1.1.0.
- Four rules, all `deny` (D15): TN1, an organization that has spent its slice quota in a
  hall the job takes a slice in — a quota of zero is a ban; TN2, two
  organizations on one wavelength; TN3, a dedicated job whose wavelength carries
  anything, its own organization's jobs included; TN4, the pairwise ban. Three
  policy switches, named, none inline. TN4 has none, because it is the job's own
  declaration.
- An envelope with no tenancy block is not refused for it; its verdict lists
  `TN1` and `TN2-TN4` as not checked — the XP1/XP2 pattern (D13). Fail-closed
  stays reserved for the three ignorance conditions. A partial block lists only
  what it left out: a hall the plant says the job occupies but the block does
  not cover is listed by name, and a block that declares only the home hall of
  a crossing job, with no plant to name the far hall, lists the far hall's
  count as taken on trust.
- Registry: six points added (25: 1 calibrated / 12 emergent / 12 sanity), none
  of them calibrated, because no published figure fixes an organization's quota;
  two DECLINED entries added (11). The random population now carries a tenancy
  block half the time, so the 400-envelope shuffle exercises the new rules; the
  orderings they add have their own points.
- Mutation tests: six added (18) — each tenant rule deleted, the gap lines
  silenced, and D13 inverted by an added rule. Red sets measured; the
  flat-ladder mutation's set gains the five points that ride the ladder; the
  control expects 25.
- Example envelopes: five added (16) — one refusal per predicate, and the campus
  stitch with no tenancy block, which prints its gaps. The runner now checks
  that a declared gap is printed, that every crossing envelope without a block
  lists both tenancy gaps, and that a declared tenancy or a hall-local job
  leaves none.
- CLI: a `tenancy:` line in every printed verdict (the JSON record carries the
  block itself); `spancontract example` declares a tenancy that clears every
  predicate; an envelope the CLI cannot read exits 2 whatever the failure — a
  missing field used to surface as a traceback with exit 1, the refusal code.
- Tests: 150, from 92.
- Found while writing the tests: a tenancy block missing a required key raised
  `KeyError`. It now raises `ValueError` naming the field, as an unknown key
  already did. Found in QA: the block's parser coerced what the schema rejects
  (`"4"` to 4, `3.9` to 3, a string to a tuple of its characters) and a `null`
  inside the block escaped as a `TypeError`. The parser is now strict by type,
  each refusal names the field, a duplicate `must_not_share_with` entry is
  refused like a duplicate hall, and the schema marks the three arrays unique.

## 1.0.1 — 2026-09-02

- One registry point added, closing specification section 9 item 7 to the
  letter: the same job probed through the emulated delay node at 40 km spans
  and at 400 km is refused, so the demonstrated flip runs probe → measurement
  → envelope → verdict with nothing hand-set but the distance. (The monotone
  RTT sweep already showed the flip; it drove the envelope directly.)
- The severity-ladder mutation's measured red set gains the new point; the
  unmutated control now expects nineteen.

## 1.0.0 — 2026-09-01

First release.

- The span envelope: the twenty-one fields of specification section 4.3, inert by
  design, with a JSON Schema generated from the code and a test that fails if the
  two drift.
- Six decisions on a severity ladder, joined with a maximum so the order the
  rules run in cannot change the answer.
- Thirteen rules, including the three conditions that fail closed: a dark circuit
  API, a stale path measurement, and a compile cache keyed on a topology that no
  longer exists. Every threshold in `Policy`; none inline.
- Two plant cross-checks that compare what a job declared against what the plant
  actually is, and a `not_checked` list so a verdict without a plant model can
  never be read as a complete one.
- A plant model: halls, circuits, blast radius, and single points of failure.
- A compile cache keyed exactly as specified, which refuses rather than evicts an
  entry stamped with a topology that is gone.
- An emulated delay node, and the `tc` line that reproduces it on real kernels.
- A hash-chained audit record, as a shape rather than a system.
- Validation registry: 18 points at 1.0.0 — 1 calibrated, 7 emergent, 10 sanity — and 9
  declined checks printed on every run.
- 91 tests, including 12 mutation tests that delete machinery and require a named
  set of registry points to go red.
- 11 example envelopes, each checked against its documented verdict.
