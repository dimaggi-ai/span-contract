"""Mutation tests: delete a piece of the contract, watch the registry go red.

A registry that stays green when its subject is broken is decoration. Each test
here removes one specific piece of machinery and asserts that a *named* set of
points fails --- named, because "something went red" would also be satisfied by
a test that crashes.

The rules the mutations must follow, and the reason for each:

* Every mutation deletes machinery, or --- for two recorded decisions ---
  inserts the reversal of the decision. None edits a threshold. Moving a
  number until a check fails proves only that the check reads the number.
* Each mutation declares the exact set of points it must turn red. A superset
  is a failure too: it means the mutation was blunter than described, and a
  blunt mutation makes every point look load-bearing.
* ``test_unmutated_control`` runs first-class alongside them. Without a green
  control, a suite where every mutation reddens everything looks identical to
  a correct one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Set

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "validation"))

import validate_contract as reg  # noqa: E402
from spancontract import compile_cache as cache_mod  # noqa: E402
from spancontract import decisions as dec_mod  # noqa: E402
from spancontract import envelope as env_mod  # noqa: E402
from spancontract import plant as plant_mod  # noqa: E402
from spancontract import rules as rules_mod  # noqa: E402
from spancontract import validator as val_mod  # noqa: E402
from spancontract.adapters import delay_node as dn_mod  # noqa: E402

#: Every module a name might be bound in. A mutation that patches only the
#: defining module silently fails to bite anywhere the name was imported by
#: value, which is how a mutation test comes out green for the wrong reason.
NAMESPACES = (reg, rules_mod, val_mod, plant_mod, cache_mod, dn_mod, env_mod, dec_mod)


def patch_everywhere(monkeypatch, name: str, value) -> int:
    """Rebind ``name`` in every namespace that holds it. Returns the count."""
    hits = 0
    for module in NAMESPACES:
        if hasattr(module, name):
            monkeypatch.setattr(module, name, value, raising=False)
            hits += 1
    assert hits, f"{name} is not bound in any namespace; the mutation would not bite"
    return hits


def delete_rule(monkeypatch, rule_name: str) -> None:
    """Remove one rule from the set the validator runs."""
    target = getattr(rules_mod, rule_name)
    assert target in rules_mod.RULES, f"{rule_name} is not in RULES"
    remaining = tuple(r for r in rules_mod.RULES if r is not target)
    assert len(remaining) == len(rules_mod.RULES) - 1
    patch_everywhere(monkeypatch, "RULES", remaining)


def red(points) -> Set[str]:
    return {p.name for p in points if not p.passed}


def test_unmutated_control() -> None:
    """The green control. Without it the mutations below prove nothing."""
    points = reg.run_registry()
    assert red(points) == set(), "the registry must be green before anything is deleted"
    assert len(points) == 25


def test_delete_fail_closed_dark(monkeypatch) -> None:
    """A dark circuit controller stops being a refusal."""
    delete_rule(monkeypatch, "rule_circuit_api_dark")
    assert red(reg.run_registry()) == {
        "every-fail-closed-condition-is-one-edit-away",
        "the-three-specified-conditions-fail-closed",
        "a-dark-probe-changes-no-measured-value",
    }


def test_delete_staleness_check(monkeypatch) -> None:
    """A measurement past its TTL stops being a refusal."""
    delete_rule(monkeypatch, "rule_measurement_stale")
    assert red(reg.run_registry()) == {
        "every-fail-closed-condition-is-one-edit-away",
        "the-three-specified-conditions-fail-closed",
    }


def test_delete_compile_cache_check(monkeypatch) -> None:
    """A plan keyed on a different placement stops being a refusal."""
    delete_rule(monkeypatch, "rule_compile_cache_stale")
    assert red(reg.run_registry()) == {
        "every-fail-closed-condition-is-one-edit-away",
        "the-three-specified-conditions-fail-closed",
    }


def test_delete_distance_rule(monkeypatch) -> None:
    """Distance stops mattering, so the verdict is flat across the sweep.

    This is the mutation the naive form of the monotonicity point could not
    catch: a constant sequence is monotone. It bites only because the point
    also requires the verdict to move.
    """
    delete_rule(monkeypatch, "rule_synchronous_training_regime")
    assert red(reg.run_registry()) == {"refusal-is-monotone-in-distance"}


def test_collapse_blast_radius(monkeypatch) -> None:
    """Every stitch is declared harmless regardless of what it carries."""
    patch_everywhere(monkeypatch, "blast_radius", lambda *a, **k: 1)
    assert red(reg.run_registry()) == {"redundancy-collapses-blast-radius-in-one-step"}


def test_cache_ignores_topology(monkeypatch) -> None:
    """The compile cache hands back entries stamped with a dead topology."""

    def always_hit(self, key, current_topology_hash):
        entry = self.entries.get(key)
        if entry is None:
            return cache_mod.Lookup(None, "miss", "no entry")
        return cache_mod.Lookup(entry, "hit")

    monkeypatch.setattr(cache_mod.CompileCache, "get", always_hit)
    assert red(reg.run_registry()) == {"a-stale-cache-entry-is-refused-and-kept"}


def test_dark_probe_invents_values(monkeypatch) -> None:
    """A dark controller's silence is filled in with plausible numbers."""
    real = dn_mod.apply_measurement

    def optimistic(env, m):
        if not m.reachable:
            return env.replace(
                stitch_api_reachable=False,
                measured_age_s=m.age_s,
                span_rtt_us=1.0,
                measured_il_db=0.0,
                measured_ber=0.0,
            )
        return real(env, m)

    patch_everywhere(monkeypatch, "apply_measurement", optimistic)
    assert red(reg.run_registry()) == {"a-dark-probe-changes-no-measured-value"}


def test_flatten_the_severity_ladder(monkeypatch) -> None:
    """Every decision becomes equally severe, so the join stops ordering them."""
    flat = {d: 0 for d in dec_mod.Decision}
    monkeypatch.setattr(dec_mod, "_SEVERITY", flat)
    assert red(reg.run_registry()) == {
        "there-are-six-decisions-on-a-total-order",
        "refusal-is-monotone-in-distance",
        "the-emulated-stitch-flips-the-verdict-across-a-regime",
        "adding-a-rule-never-permits-more",
        "severity-ladder-dominates-by-construction",
        "every-fail-closed-condition-is-one-edit-away",
        "the-three-specified-conditions-fail-closed",
        "a-dark-probe-changes-no-measured-value",
        # The tenant predicates sit on the same ladder, so flattening it takes
        # every ordering they rely on with it.
        "each-tenant-predicate-is-one-edit-away",
        "refusal-is-monotone-in-slices-held",
        "adding-a-co-tenant-never-permits-more",
        "removing-the-tenancy-block-never-refuses-more",
        "an-absent-tenancy-block-is-listed-as-unchecked-not-refused",
    }


def test_drop_a_specified_field(monkeypatch) -> None:
    """One of the twenty-one fields quietly goes missing."""
    patch_everywhere(monkeypatch, "SPEC_FIELDS", env_mod.SPEC_FIELDS[:-1])
    assert red(reg.run_registry()) == {
        "the-envelope-has-the-twenty-one-specified-fields",
        "the-schema-matches-the-code-and-an-envelope-round-trips",
    }


def test_reconcile_the_span_mode_discrepancy(monkeypatch) -> None:
    """The specification's gap is quietly patched over instead of carried.

    Added because smoothing a discrepancy is exactly the kind of change that
    looks like a tidy-up in a diff, and the point that records it should notice.
    """
    patch_everywhere(monkeypatch, "SPAN_MODES", tuple(d.value for d in dec_mod.Decision))
    assert red(reg.run_registry()) == {"span-mode-omits-escalate-as-the-specification-does"}


def test_delete_the_slice_quota_rule(monkeypatch) -> None:
    """An organization past its quota stops being refused.

    Bites on the monotone-in-held sweep for the same reason the distance
    deletion bites: a flat sweep is monotone, and the point requires movement.
    """
    delete_rule(monkeypatch, "rule_org_slice_quota")
    assert red(reg.run_registry()) == {
        "each-tenant-predicate-is-one-edit-away",
        "refusal-is-monotone-in-slices-held",
    }


def test_delete_the_cross_organization_sharing_rule(monkeypatch) -> None:
    """Two organizations on one wavelength stops being a refusal."""
    delete_rule(monkeypatch, "rule_lambda_shared_across_orgs")
    assert red(reg.run_registry()) == {"each-tenant-predicate-is-one-edit-away"}


def test_delete_the_dedicated_wavelength_rule(monkeypatch) -> None:
    """A dedicated job sharing its wavelength stops being a refusal."""
    delete_rule(monkeypatch, "rule_dedicated_wavelength_is_shared")
    assert red(reg.run_registry()) == {"each-tenant-predicate-is-one-edit-away"}


def test_delete_the_pairwise_ban(monkeypatch) -> None:
    """'This job may not share a wavelength with that job' stops being enforced."""
    delete_rule(monkeypatch, "rule_lambda_pairwise_ban")
    assert red(reg.run_registry()) == {"each-tenant-predicate-is-one-edit-away"}


def test_silence_the_tenancy_gaps(monkeypatch) -> None:
    """An envelope with no tenancy block is admitted without saying what was skipped.

    The verdicts are identical; only the not_checked lines are gone. That a
    point catches this is the whole reason the gaps are printed rather than
    implied.
    """
    patch_everywhere(monkeypatch, "tenancy_gaps", lambda env, plant: [])
    assert red(reg.run_registry()) == {
        "an-absent-tenancy-block-is-listed-as-unchecked-not-refused",
    }


def test_an_absent_tenancy_block_starts_failing_closed(monkeypatch) -> None:
    """DECISIONS.md D13 is quietly reversed: no tenancy block becomes a refusal.

    This one adds a rule rather than deleting one. Like the span-mode
    reconcile test above it is the inversion of a recorded decision, included
    because D13 is the decision most likely to be "tidied up" by someone who
    thinks silence should refuse. Six points go red, for three reasons: the
    two points about absent blocks see them refused; the reference envelope
    declares no tenancy, so it is refused before the distance sweep, the
    emulated flip, and the fail-closed one-edit-away point can move it; and
    the three-conditions point finds a fourth fail-closed rule (measured: with
    the injected rule not marked fail-closed, that point stays green and the
    set is five).
    """

    def rule_absent_tenancy_fails_closed(env, policy):
        if env.spans_halls and env.tenancy is None:
            return rules_mod.Finding("TN0", dec_mod.Decision.DENY, "no tenancy block",
                                     fail_closed=True)
        return None

    patch_everywhere(monkeypatch, "RULES", rules_mod.RULES + (rule_absent_tenancy_fails_closed,))
    assert red(reg.run_registry()) == {
        "an-absent-tenancy-block-is-listed-as-unchecked-not-refused",
        "removing-the-tenancy-block-never-refuses-more",
        "every-fail-closed-condition-is-one-edit-away",
        "the-three-specified-conditions-fail-closed",
        "refusal-is-monotone-in-distance",
        "the-emulated-stitch-flips-the-verdict-across-a-regime",
    }


def test_every_mutation_is_a_deletion() -> None:
    """No mutation in this file may work by moving a threshold.

    Read as text rather than by introspection, because the property is about
    what the tests *do*, and a test that nudged a Policy field would still
    pass any structural check.
    """
    source = Path(__file__).read_text()
    for field in reg.Policy.__dataclass_fields__:
        assert f"{field}=" not in source, (
            f"a mutation appears to move the policy threshold {field!r}; mutations "
            "must delete machinery, not retune it"
        )
    # The two ways round the field scan: rebinding a default on the class, or
    # building a Policy from a dict. Spelled in halves so this test's own text
    # does not trip it.
    for dodge in ("setattr(" + "reg.Policy", "setattr(" + "rules_mod.Policy", "Policy(" + "**"):
        assert dodge not in source, f"a mutation appears to retune the policy via {dodge!r}"
