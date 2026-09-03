# The contract, as implemented

The specification in prose, the code that implements it, and the three places
where the two do not agree.

---

## 1. What the contract is for

A job asks to run across more than one data hall. Something has to decide whether
it may. Today three systems each hold part of the answer and none of them is
asked:

- the **scheduler** knows how many accelerators are free, and where;
- the **compiler** knows what plan it emitted and what topology it assumed;
- the **circuit controller** knows what glass is lit, and how it is behaving.

The job finds out which of the three was wrong at step time. The span envelope is
one object that makes them agree first.

The contract decides **admission**. It does not decide **capacity**. What a job
would retain across a given cut is a measurement question, answered by the
latency-regime atlas in `network-vs-more-gpus`; the contract cites that work and
does not recompute it.

## 2. The twenty-one fields

Grouped by what they answer. Field order in the code follows the specification so
the two can be read side by side.

| Group | Fields | The question they answer |
|---|---|---|
| Transport and mode | `scale_out`, `span_mode` | What is the job asking for, over what? |
| The stitch | `span_rtt_us`, `span_bw_gbps`, `span_failure_domain` | How far, how wide, and what falls over with it? |
| Placement | `slice_rect` | Which rectangle of which hall does it hold? |
| Circuit identity and health | `stitch_id`, `stitch_api`, `topology_hash`, `measured_il_db`, `measured_ber` | Which circuit, who can be asked about it, and how is it? |
| Time and throughput budgets | `checkpoint_window_s`, `collective_window_s`, `ingest_budget_GBps` | What does the job need the circuit for, and for how long? |
| Plant envelope | `thermal_headroom_k`, `ride_through_s`, `power_headroom_kw` | Can the receiving hall physically take it? |
| Compilation | `compile_cache_key` | Which compiled plan is this, and what was it built for? |
| Governance | `blast_radius`, `autonomy_level`, `requested_action` | How bad is a failure, who is allowed to decide, and to do what? |

Four further fields are not part of the twenty-one. Three carry provenance:
`measured_age_s`, `stitch_api_reachable`, and free-form `labels`. They exist
because the twenty-one cannot be *checked* without them. A `topology_hash` with
no measurement age cannot be known to be stale; a `stitch_api` with no record of
whether it answered cannot be known to be dark. The specification's fail-closed
conditions are unimplementable without them, which is an observation about the
field set rather than a criticism of it. The fourth, `tenancy`, is optional and
is section 5.

## 3. The six decisions

`local` → `span` → `shrink` → `move` → `escalate` → `deny`, in increasing
severity. Rules join with a maximum. A rule can push the verdict toward refusal
and never away from it, so the order the rules run in is irrelevant to the
result — a property the registry proves by shuffling the rule list over 400
random envelopes.

The ladder is not the declaration order. `move` outranks `shrink` because
relocating a job is heavier than resizing it; `escalate` outranks both because it
stops automation; `deny` is the top because it is the only outcome that runs
nothing.

## 4. The three conditions that fail closed

Each names something the contract *does not know*, and in each case not knowing
is the refusal.

**FC1 — the circuit API is dark.** Distinguish two states the code keeps apart:
the controller was polled and did not answer, and the controller was never
polled. Neither is health. A dark probe leaves every declared number untouched
and only records that nobody could confirm them (D10), so the audit record shows
a circuit nobody could reach rather than a circuit that looked broken. Those are
different incidents.

**FC2 — the measured path is stale past its TTL.** A declared topology is a
claim. Only a measurement is an observation. A path that has never been measured
is treated as infinitely stale, not as fresh.

**FC3 — the compile cache was keyed on a topology that no longer exists.**
Checked in two places, because the condition has two halves. Rule FC3 recomputes
the key from the envelope's own `slice_rect` and `stitch_id` and refuses a key
that does not match the placement it claims to describe. Cross-check XP2 refuses
an envelope whose `topology_hash` is not the one the plant is currently on. The
first catches a plan compiled for somewhere else; the second catches a plan
compiled for here, before here changed.

## 5. The four tenant predicates

Section 6 of the specification, under the research program's W7, asks for two
refusals the rules above cannot make: *this org may take N slices in hall A*,
and *this job may not share a λ with that job*. Its one-line rationale is
"isolation is geometry and optics": on a raw inter-chip mesh there are no packet
headers to isolate tenants with, so a wavelength carrying two organizations is
two tenants on one piece of glass with nothing between them.

Since 1.1.0 the envelope may carry an optional `tenancy` block:

| Field | What it declares |
|---|---|
| `org_id` | whose job this is |
| `tenancy_class` | `dedicated` — the wavelength carries this job alone — or `shared` — co-tenants from the job's own organization are accepted |
| `slices[]` | per hall the job takes a slice in: `held`, the organization's slices there *without* this job, and `quota`, how many it may hold; zero is a ban |
| `lambda_sharing` | the wavelength the stitch would use, the jobs already on it and whose they are, and the jobs this one may never share with |

Four rules read it, and all four refuse with `deny`:

| | Predicate | Policy switch |
|---|---|---|
| **TN1** | `held >= quota` in any declared hall | `enforce_org_slice_quota` |
| **TN2** | a co-tenant belongs to another organization | `allow_lambda_sharing_across_orgs` |
| **TN3** | the class is one the policy treats as dedicated and the wavelength carries anything | `dedicated_tenancy_classes` |
| **TN4** | a co-tenant is on the job's own `must_not_share_with` list | none — it is the job's own declaration |

Four things about them are decisions rather than details.

**They do not fail closed.** An envelope with no tenancy block is not refused
for it, and its verdict lists `TN1` and `TN2-TN4` as not checked — the same pattern as the
plant cross-checks XP1 and XP2. Each fail-closed condition describes the plant
failing to answer a question the contract must have answered; an absent tenancy
block is a caller that has not wired its organization's bookkeeping, and
refusing it would make the block mandatory in all but name and turn every 1.0
envelope into a refusal in a minor release. A partial block lists only what it
left out: no quota state, a `TN1` line; no wavelength, a `TN2-TN4` line; a hall
the plant says the job occupies that the block does not cover, a `TN1` line
naming it; a block that declares only the home hall of a crossing job, with no
plant to name the far hall, a `TN1` line saying the far hall's count was taken
on trust. `DECISIONS.md` D13.

**They apply to crossings only.** Like every rule here they are gated on the
job leaving its hall. A hall-local job's slice is admitted by the slice packer
under its own tenancy model, and it uses no wavelength. The block must include
the hall the `slice_rect` sits in, so a declaration cannot cover only the far
hall and let TN1 pass on the one the job actually takes a slice in. D14.

**They are `deny`, not `escalate` or `move`.** A spent quota carries no
question for a human, and the contract cannot see the hall a `move` would point
at. PL2 and PL3 are the analogue: a limit that is simply exhausted. D15.

**Nothing is fetched.** `held`, `quota` and the occupancy list are declared, as
`measured_il_db` is: claims the audit record carries. The contract has no quota
service and no second adapter surface. A declaration that is wrong on the
envelope is wrong in the verdict, and the DECLINED list says so in two places.
D16.

## 6. Where the implementation and the specification disagree

### 6.1 `span_mode` omits `escalate`

Section 4.2 lists six decisions. The `span_mode` field in section 4.3 enumerates
five. Both are implemented as written and the gap is asserted by a registry
point, so closing it later fails a check rather than passing as a tidy-up.

It may not be an error. A `span_mode` is what a job *requests*, and `escalate` is
not something a job can ask for — it is what the contract does when it will not
decide alone. Read that way the specification is right and reconciling it would
destroy a real distinction. Read the other way it is an oversight. The person who
wrote the specification should be the one to say which. See `DECISIONS.md` D3.

### 6.2 The compile cache key cannot detect its own fail-closed condition

The key is `(graph, slice_rect, stitch_id)` and contains no topology hash, so a
cache built from the key alone cannot detect that the topology is gone. Resolved
by keying exactly as specified and stamping each entry with the topology hash
live at compile time; a lookup refuses on mismatch. See `DECISIONS.md` D4.

### 6.3 The governance engine

The specification proposes routing these decisions through an existing governance
engine and reusing its endpoint and log format. Not done. An admission contract
that only works inside one vendor's engine is that vendor's feature, not a
contract. `docs/integration.md` describes the binding surface; this repository
ships no integration. See `DECISIONS.md` D7.

## 7. What the registry can and cannot establish

Run `make validate`. It prints twenty-five points and then prints eleven things
it declined to check, and the second list is the more informative one.

**It can establish** that the contract is internally consistent, that its
refusals are reachable from a clean envelope by a single edit, that its structure
matches the specification, that the rule order does not matter, and that deleting
any piece of its machinery is detectable — the last of these enforced by
eighteen mutation tests, each naming the exact set of points it must turn red.

**It cannot establish** that any threshold is right. There is one calibrated
point in the registry and it is about the emulator's propagation delay, not about
the contract. No published figure fixes a measurement TTL, a loss budget, or an
organization's slice quota; they are operator choices. A registry that manufactured calibrated points for them
would look more rigorous and be less true. See `DECISIONS.md` D11.

It also cannot establish that any verdict here is right for a real cluster. Every
envelope in this repository is constructed. No verdict has been checked against a
job that actually ran, and until section 9's eighth sequence item has a named
plant behind it, none can be.
