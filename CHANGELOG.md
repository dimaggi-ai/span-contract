# Changelog

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
- Validation registry: 18 points — 1 calibrated, 7 emergent, 10 sanity — and 9
  declined checks printed on every run.
- 91 tests, including 12 mutation tests that delete machinery and require a named
  set of registry points to go red.
- 11 example envelopes, each checked against its documented verdict.
