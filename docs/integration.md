# Integration surface

This repository ships no integration with any policy engine, scheduler, or
circuit controller. It ships a schema, a rule set, and a reference validator.
This document describes what someone binding it to a real system has to provide,
and what they get back.

The reason it stops here is in `DECISIONS.md` D7: an admission contract that only
works inside one vendor's engine is that vendor's feature, not a contract.

---

## 1. What a caller must provide

### The envelope

Twenty-one fields, plus three that make them checkable, plus an optional
`tenancy` block. Build it with `SpanEnvelope(...)`, or validate a JSON document
against `schema/span_contract.schema.json` and load it with
`SpanEnvelope.from_dict`.

The schema is generated from the code and a test fails if the two drift, so it is
safe to generate client code from it.

### A circuit controller

One method:

```python
class StitchController(Protocol):
    def probe(self, stitch_id: str) -> PathMeasurement: ...
```

`PathMeasurement` carries `reachable`, and when reachable, a round-trip time, an
insertion loss, an error rate, a bandwidth, and an age. **`reachable=False` must
be a returned value, not a raised exception.** A controller that raises on an
unreachable device makes the caller decide what silence means, which is the
decision this contract exists to take away from the caller.

Feed the result through `apply_measurement(envelope, measurement)`. It fills the
measured fields on success and, on a dark probe, changes nothing but
`stitch_api_reachable` — see `DECISIONS.md` D10 for why it does not substitute
pessimistic values.

`spancontract.adapters.delay_node` implements the protocol against an emulated
circuit, which is the reference for what a real driver should return.

### A plant model, if you have one

`Plant(graph, job_halls, anchor, current_topology_hash)`. All of it optional.
With no plant, the rules still run; the two cross-checks cannot, and
`Verdict.not_checked` says so by name. **Surface that list.** A verdict computed
without a plant is weaker than one computed with it, and a UI that hides the
difference turns "not checked" into "checked and fine".

### A tenancy declaration, if you have one

`Tenancy(org_id, tenancy_class, slices, lambda_sharing)`, optional on the
envelope. The scheduler already holds the organization's slice count per hall
and the circuit controller already knows what is on a wavelength; put them on
the envelope and four rules read them (`docs/the-contract.md`, section 5).
Nothing is fetched: the contract has no quota service and no second adapter
surface, by decision (`DECISIONS.md` D16).

With no block, the envelope is a 1.0 envelope. It reaches the same decision as before and
`Verdict.not_checked` gains two lines, `TN1` and `TN2-TN4`. **Surface those
too.** A tenancy-free verdict is weaker than a declared one in exactly the way a
plant-free verdict is weaker than a checked one, and for the same reason it is
not a refusal: an absent declaration is your bookkeeping not being wired yet,
not the plant failing to answer (`DECISIONS.md` D13).

### A policy, if the defaults are wrong for you

Every threshold is a field on `Policy`, and so are the three tenancy switches;
the pairwise ban has none, because it is the job's own declaration. None is
inline. The defaults are conservative starting points with no published anchor —
`ASSUMPTIONS.md` A1 — and you should expect to change them. The policy is
recorded in the audit record, so a verdict can always be traced to the numbers
that produced it.

## 2. What a caller gets back

```python
verdict = validate(envelope, policy, plant)

verdict.decision        # one of the six
verdict.allowed         # True only for LOCAL and SPAN
verdict.findings        # every objection, each with a rule id
verdict.not_checked     # what could not be checked, and why
verdict.fail_closed_findings   # the subset a policy may not relax
```

`allowed` is deliberately narrow. `SHRINK` and `MOVE` are not refusals, but they
are not this job either — they describe a different job that would be admitted.
A caller that treats them as approval will run the job it was told not to run.

## 3. Audit

`audit_record(envelope, verdict, policy, previous_hash=...)` returns a plain
dictionary with a `chain` field: the SHA-256 of the previous record's chain
concatenated with this record's canonical body. `verify_chain(records)` checks a
sequence. A truncated or edited log is detectable without a signing key.

This is a **shape, not a system**. There is no writer, no rotation, no transport,
and no retention policy, because those belong to whatever audit pipeline you
already run. Map these fields onto it. Do not run two.

If you have no such pipeline, the shape is enough to start with, but note what
the chain does and does not give you: it detects edits and truncation by anyone
who cannot rewrite the whole log forward from the edit. It is not a signature and
it does not identify who wrote a record.

## 4. Binding to an existing policy engine

If you already run one, the natural mapping is:

| This repository | A policy engine |
|---|---|
| `SpanEnvelope` | the request payload |
| `Policy` | the engine's configuration for this domain |
| `RULES` | the rule set, or a translation of it into the engine's language |
| `Decision` | the engine's effect vocabulary |
| `audit_record` | discard; use the engine's log |

The part worth carrying across is not the code. It is the field set and the three
fail-closed conditions: which facts must be agreed on before a job crosses, and
which *absences* are refusals rather than defaults. Those survive being
reimplemented in someone else's engine, and they are the contribution.

## 5. What this cannot tell you

- **Whether the job will run well if admitted.** Admission is not capacity. See
  the latency-regime atlas in `network-vs-more-gpus`.
- **Whether your circuits are actually independent.** `load_bearing_stitches`
  sees the graph you declared, not the ducts. Two circuits in one trench are one
  failure — `ASSUMPTIONS.md` A3, and the most likely way a green verdict here is
  wrong about a real plant.
- **Whether a declared quota or wavelength occupancy is true.** They are the
  caller's claims, carried to the audit record so a wrong one is findable
  afterwards, not caught at admission — `ASSUMPTIONS.md` A12 and A13.
- **Whether the thresholds suit your plant.** They are starting points. Eleven
  entries in the registry's DECLINED list say so.
