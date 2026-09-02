# The span contract: deciding whether an AI training job may cross a data hall

**When a job asks to run across more than one hall, who decides, and on what facts?**

Today, three systems decide, and none of them talks to the others. The scheduler
knows how many accelerators are free. The compiler knows what plan it emitted and
what topology it assumed. The circuit controller knows what glass is lit. Each
holds a different half-truth, and the job discovers which one was wrong at step
time — or worse, at checkpoint time, three hours in.

This repository is one object that makes them agree before the job starts:
twenty-one fields, six decisions, three conditions under which the contract
refuses rather than guesses, and a reference validator that turns the first into
the second and prints its reasons. It is a research artifact, not a product.

---

## What it is not

It is not a fabric, a scheduler, or a network model. It decides **admission** —
may this job cross — and holds no opinion on **capacity** — what the job would
retain if it did. That second question is answered by the latency-regime atlas in
[network-vs-more-gpus](https://github.com/dimaggi-ai/network-vs-more-gpus), and
this repository deliberately does not offer a second answer to it. The two are
designed to be read together: the atlas says a tensor-parallel cut retains 0.004
across any stitch at any distance, and the contract is what refuses to launch it.

## The shape of it

```python
from spancontract import SpanEnvelope, validate

verdict = validate(envelope)
verdict.decision      # Decision.DENY
verdict.reasons()     # ['[FC2] path measurement is 7200s old, past the 300s TTL']
verdict.not_checked   # what the validator could not check, printed rather than omitted
```

```
$ spancontract validate examples/long-haul-training-too-far.json
decision: DENY
regime:   region (2958 us RTT)

findings:
  - [LR1] synchronous train at 2958 us RTT (region) exceeds the 2000 us limit;
          the default policy is that training stays hall-local

not checked:
  ? XP1 declared-vs-computed blast radius: no plant graph supplied, so the
    envelope's blast_radius was taken on trust
  ? XP2 topology currency: no live topology hash supplied, so the envelope's
    topology_hash was taken on trust
```

## The three conditions that fail closed

Each describes a state in which the contract *does not know* something it needs,
and in each case not knowing is a refusal. A validator that read silence as
health would be worse than no validator, because it would be trusted.

| | Condition | Why it is a refusal and not a warning |
|---|---|---|
| **FC1** | The circuit API is dark | The state of the stitch is unknown. Unknown is not healthy. |
| **FC2** | The measured path is stale past its TTL | A declared topology is a claim. Only a fresh measurement is an observation. |
| **FC3** | The compile cache was keyed on a topology that no longer exists | The binary was built for a placement that is gone. |

## The six decisions

`local` · `span` · `shrink` · `move` · `escalate` · `deny`, on a severity ladder.
Rules join with a maximum, so a rule can only push a verdict toward refusal and
never away from it — which is what makes the order the rules run in irrelevant to
the answer. The registry proves that by shuffling the rule list over 400 random
envelopes and requiring every verdict to be identical.

## What the validator refuses to pretend

`make validate` prints the registry, and then prints the list of what it
**declined** to check. That second list is the more useful one. It says, among
other things, that no published figure fixes any threshold in this repository,
that no verdict here has been checked against a job that actually ran, and that
the emulated circuit models amplifier gain without the optical signal-to-noise
cost that comes with it, so it can demonstrate a refusal but cannot support a
claim of health.

There is exactly **one calibrated point** in the registry. That is the honest
count, not a gap. See [`docs/the-contract.md`](docs/the-contract.md).

## Install and run

```bash
git clone https://github.com/dimaggi-ai/span-contract
cd span-contract
make venv
make smoke-test      # tests, mutation tests, registry, examples — under a minute
```

Or from PyPI:

```bash
pip install span-contract
spancontract example > envelope.json
spancontract validate envelope.json
```

| Target | What it does |
|---|---|
| `make test` | 91 tests, including 12 mutation tests that delete machinery and require the registry to go red |
| `make validate` | the validation registry, and the nine things it declines to check |
| `make examples` | eleven example envelopes, each checked against its documented verdict |
| `make schema` | regenerate `schema/span_contract.schema.json` from the code |

## Repository map

| Path | What is in it |
|---|---|
| `src/spancontract/envelope.py` | the twenty-one fields, inert by design |
| `src/spancontract/rules.py` | every rule and every threshold, none of them inline |
| `src/spancontract/validator.py` | the join, the plant cross-checks, the hash-chained record |
| `src/spancontract/plant.py` | halls, circuits, and what one failure actually costs |
| `src/spancontract/compile_cache.py` | keyed as specified; refuses entries from a dead topology |
| `src/spancontract/adapters/delay_node.py` | an emulated circuit, and the `tc` line that reproduces it |
| `validation/validate_contract.py` | the registry: one calibrated, seven emergent, ten sanity, nine declined |
| `tests/test_mutations.py` | delete a piece, name the points that must go red |
| `docs/the-contract.md` | the specification as implemented, including where it contradicts itself |
| `docs/integration.md` | the surface an existing policy engine would bind to |

## The discrepancy that was carried rather than fixed

The specification lists six decisions, and then enumerates only five of them in
the `span_mode` field: `escalate` is missing. Both are implemented exactly as
written — a verdict can be `escalate`, and `span_mode` cannot — and a registry
point asserts the gap is still there, so that quietly closing it in a future
commit shows up as a failing check rather than a tidy-up. `DECISIONS.md` D3 has
the reasoning.

## Series

Part of a program on the usable capacity of large accelerator fleets:
[dimaggi-ai.github.io/research](https://dimaggi-ai.github.io/research).

## License

MIT. Copyright (c) 2026 Margaret Nanyonga.
