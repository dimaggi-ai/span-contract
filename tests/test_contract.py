"""Unit and invariant tests for the span contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spancontract import (  # noqa: E402
    AUTONOMY_LEVELS,
    SPAN_MODES,
    SPEC_FIELDS,
    CompileCache,
    Decision,
    Plant,
    Policy,
    ScaleOut,
    SliceRect,
    SpanEnvelope,
    SpanGraph,
    Stitch,
    audit_record,
    blast_radius,
    compile_cache_key,
    latency_regime,
    load_bearing_stitches,
    validate,
    verify_chain,
)
from spancontract.adapters import DelayNode, EmulatedController, apply_measurement  # noqa: E402
from spancontract.cli import main  # noqa: E402
from spancontract.schema import envelope_schema  # noqa: E402

GRAPH_HASH = "a3f1" + "0" * 60
TOPOLOGY_HASH = "b7c2" + "0" * 60


def clean(**kw):
    base = dict(
        scale_out=ScaleOut.OCS_STITCHED,
        span_mode="span",
        span_rtt_us=412.0,
        span_bw_gbps=800.0,
        span_failure_domain="metro-ring-north",
        slice_rect=SliceRect("hall-a", (0, 0, 0), (8, 8, 8)),
        stitch_id="stitch-ab",
        stitch_api="https://ocs.plant.example/v1",
        topology_hash=TOPOLOGY_HASH,
        measured_il_db=10.0,
        measured_ber=1e-12,
        checkpoint_window_s=120.0,
        collective_window_s=300.0,
        ingest_budget_GBps=40.0,
        thermal_headroom_k=3.0,
        ride_through_s=180.0,
        power_headroom_kw=250.0,
        compile_cache_key="",
        blast_radius=1,
        autonomy_level="L1",
        requested_action="train",
        measured_age_s=30.0,
        stitch_api_reachable=True,
        labels={"graph_hash": GRAPH_HASH, "cut": "pp"},
    )
    base.update(kw)
    env = SpanEnvelope(**base)
    if not base["compile_cache_key"]:
        env = env.replace(compile_cache_key=env.expected_compile_cache_key(GRAPH_HASH))
    return env


# --- envelope -------------------------------------------------------------


def test_the_clean_envelope_clears_every_rule():
    verdict = validate(clean())
    assert verdict.decision is Decision.SPAN
    assert verdict.findings == ()
    assert verdict.allowed


@pytest.mark.parametrize(
    "kw",
    [
        {"span_mode": "escalate"},
        {"span_mode": "nonsense"},
        {"autonomy_level": "L9"},
        {"span_rtt_us": -1.0},
        {"measured_ber": 1.5},
        {"blast_radius": 0},
        {"stitch_id": ""},
        {"requested_action": ""},
    ],
)
def test_the_envelope_rejects_impossible_values(kw):
    with pytest.raises(ValueError):
        clean(**kw)


def test_span_mode_rejects_escalate_because_the_specification_omits_it():
    assert "escalate" not in SPAN_MODES
    assert Decision.ESCALATE.value not in SPAN_MODES
    with pytest.raises(ValueError, match="escalate"):
        clean(span_mode="escalate")


def test_the_envelope_round_trips_through_json():
    env = clean()
    assert SpanEnvelope.from_dict(json.loads(json.dumps(env.to_dict()))) == env


def test_an_unknown_field_is_refused_rather_than_ignored():
    payload = clean().to_dict()
    payload["span_jitter_us"] = 3.0
    with pytest.raises(ValueError, match="unknown envelope fields"):
        SpanEnvelope.from_dict(payload)


@pytest.mark.parametrize(
    "args",
    [
        ("", (0,), (1,)),
        ("hall-a", (0, 0), (1,)),
        ("hall-a", (), ()),
        ("hall-a", (-1,), (1,)),
        ("hall-a", (0,), (0,)),
    ],
)
def test_the_slice_rectangle_rejects_impossible_shapes(args):
    with pytest.raises(ValueError):
        SliceRect(*args)


def test_the_slice_rectangle_counts_its_accelerators():
    assert SliceRect("hall-a", (0, 0, 0), (8, 4, 2)).accelerators == 64


# --- decisions ------------------------------------------------------------


def test_the_join_takes_the_harshest_and_is_order_free():
    ladder = [Decision.LOCAL, Decision.SPAN, Decision.SHRINK,
              Decision.MOVE, Decision.ESCALATE, Decision.DENY]
    assert Decision.max(ladder) is Decision.DENY
    assert Decision.max(reversed(ladder)) is Decision.DENY
    assert Decision.max([]) is Decision.LOCAL
    assert Decision.max([Decision.SHRINK, Decision.ESCALATE]) is Decision.ESCALATE


def test_only_span_permits_crossing():
    assert Decision.SPAN.permits_span
    assert not any(d.permits_span for d in Decision if d is not Decision.SPAN)


@pytest.mark.parametrize(
    "rtt,expected",
    [(0.0, "scale-up"), (1.0, "scale-up"), (1.1, "rail"), (5.0, "rail"),
     (80.0, "campus-stitch"), (81.0, "metro"), (2_000.0, "metro"), (2_001.0, "region")],
)
def test_the_regime_boundaries_are_where_they_are_documented(rtt, expected):
    assert latency_regime(rtt) == expected


# --- rules ----------------------------------------------------------------


@pytest.mark.parametrize(
    "kw,expected,rule_id",
    [
        ({"stitch_api_reachable": False}, Decision.DENY, "FC1"),
        ({"stitch_api_reachable": None}, Decision.DENY, "FC1"),
        ({"measured_age_s": None}, Decision.DENY, "FC2"),
        ({"measured_age_s": 10_000.0}, Decision.DENY, "FC2"),
        ({"compile_cache_key": "0" * 64}, Decision.DENY, "FC3"),
        ({"span_rtt_us": 40_000.0}, Decision.DENY, "LR1"),
        ({"labels": {"graph_hash": GRAPH_HASH, "cut": "tp"}}, Decision.SHRINK, "LR2"),
        ({"measured_il_db": 40.0}, Decision.DENY, "CH1"),
        ({"measured_ber": 1e-5}, Decision.DENY, "CH2"),
        ({"blast_radius": 4}, Decision.ESCALATE, "GV1"),
        ({"autonomy_level": "L3"}, Decision.ESCALATE, "GV2"),
        ({"ride_through_s": 30.0}, Decision.SHRINK, "PL1"),
        ({"thermal_headroom_k": 0.0}, Decision.DENY, "PL2"),
        ({"power_headroom_kw": 0.0}, Decision.DENY, "PL3"),
        ({"checkpoint_window_s": 400.0}, Decision.SHRINK, "ST1"),
    ],
)
def test_each_rule_fires_alone_on_its_own_damage(kw, expected, rule_id):
    verdict = validate(clean(**kw))
    assert verdict.decision is expected
    assert rule_id in {f.rule_id for f in verdict.findings}


def test_an_empty_compile_cache_key_is_refused():
    assert validate(clean(compile_cache_key="x")).decision is Decision.DENY


def test_a_missing_graph_hash_cannot_be_checked_so_it_is_refused():
    env = clean().replace(labels={"cut": "pp"})
    verdict = validate(env)
    assert verdict.decision is Decision.DENY
    assert any("graph_hash" in f.message for f in verdict.findings)


def test_a_local_job_is_untouched_by_a_rotten_circuit():
    env = clean(
        span_mode="local", measured_il_db=99.0, measured_ber=0.1,
        thermal_headroom_k=0.0, power_headroom_kw=0.0, blast_radius=9,
    ).replace(stitch_api_reachable=False, measured_age_s=None)
    verdict = validate(env)
    assert verdict.decision is Decision.LOCAL
    assert verdict.findings == ()


def test_inference_may_cross_a_distance_training_may_not():
    far = {"span_rtt_us": 9_000.0}
    assert validate(clean(requested_action="train", **far)).decision is Decision.DENY
    assert validate(clean(requested_action="infer", **far)).decision is Decision.SPAN


def test_a_policy_change_moves_the_verdict_and_nothing_else_does():
    env = clean(measured_il_db=25.0)
    assert validate(env).decision is Decision.DENY
    assert validate(env, Policy(max_insertion_loss_db=30.0)).decision is Decision.SPAN


def test_the_three_fail_closed_findings_are_flagged_as_such():
    for kw in ({"stitch_api_reachable": False}, {"measured_age_s": 10_000.0},
               {"compile_cache_key": "0" * 64}):
        verdict = validate(clean().replace(**kw))
        assert verdict.fail_closed_findings
        assert all(f.fail_closed for f in verdict.fail_closed_findings)


# --- plant ----------------------------------------------------------------


def test_a_stitch_must_actually_cross_something():
    with pytest.raises(ValueError, match="not a stitch"):
        Stitch("s", frozenset({"hall-a"}))


def test_a_plant_refuses_duplicate_and_dangling_stitches():
    with pytest.raises(ValueError, match="duplicate"):
        SpanGraph(frozenset({"a", "b"}), (
            Stitch("s", frozenset({"a", "b"})), Stitch("s", frozenset({"a", "b"}))))
    with pytest.raises(ValueError, match="not in the plant"):
        SpanGraph(frozenset({"a", "b"}), (Stitch("s", frozenset({"a", "c"})),))


def test_a_chain_of_halls_has_every_link_load_bearing():
    halls = [f"h{i}" for i in range(4)]
    graph = SpanGraph(frozenset(halls), tuple(
        Stitch(f"s{i}", frozenset({halls[i], halls[i + 1]})) for i in range(3)))
    assert load_bearing_stitches(graph, halls, "h0") == ["s0", "s1", "s2"]
    assert blast_radius(graph, "s1", halls, "h0") == 4


def test_a_ring_of_halls_has_none():
    halls = [f"h{i}" for i in range(4)]
    graph = SpanGraph(frozenset(halls), tuple(
        Stitch(f"s{i}", frozenset({halls[i], halls[(i + 1) % 4]})) for i in range(4)))
    assert load_bearing_stitches(graph, halls, "h0") == []
    assert blast_radius(graph, "s0", halls, "h0") == 1


def test_the_plant_rejects_a_job_it_cannot_place():
    graph = SpanGraph(frozenset({"a", "b"}), (Stitch("s", frozenset({"a", "b"})),))
    with pytest.raises(KeyError):
        blast_radius(graph, "s", ("a", "z"), "a")
    with pytest.raises(ValueError, match="anchor"):
        blast_radius(graph, "s", ("a", "b"), "z")
    with pytest.raises(KeyError):
        blast_radius(graph, "nope", ("a", "b"), "a")


def test_the_validator_checks_a_declaration_against_the_plant():
    graph = SpanGraph(frozenset({"hall-a", "hall-b"}),
                      (Stitch("stitch-ab", frozenset({"hall-a", "hall-b"})),))
    plant = Plant(graph=graph, job_halls=("hall-a", "hall-b"), anchor="hall-a",
                  current_topology_hash=TOPOLOGY_HASH)
    understated = validate(clean(blast_radius=1), plant=plant)
    assert understated.decision is Decision.DENY
    assert "XP1" in {f.rule_id for f in understated.findings}
    # Declaring it correctly clears XP1 but trips the governance limit, which is
    # the point: the plant makes the job honest, and honesty makes it escalate.
    honest = validate(clean(blast_radius=2), plant=plant)
    assert honest.decision is Decision.ESCALATE
    assert {f.rule_id for f in honest.findings} == {"GV1"}


def test_a_retuned_plant_invalidates_the_envelope():
    plant = Plant(current_topology_hash="c9d4" + "0" * 60)
    verdict = validate(clean(), plant=plant)
    assert verdict.decision is Decision.DENY
    assert "XP2" in {f.rule_id for f in verdict.findings}


def test_unchecked_things_are_printed_not_omitted():
    verdict = validate(clean())
    assert len(verdict.not_checked) == 2
    assert any("blast radius" in n for n in verdict.not_checked)
    assert any("topology" in n for n in verdict.not_checked)
    assert validate(clean(span_mode="local")).not_checked == ()


# --- compile cache --------------------------------------------------------


def test_the_cache_key_needs_all_three_inputs():
    rect = SliceRect("hall-a", (0,), (8,))
    with pytest.raises(ValueError):
        compile_cache_key("", rect, "s")
    with pytest.raises(ValueError):
        compile_cache_key("g", rect, "")


def test_the_cache_refuses_a_dead_topology_and_keeps_the_entry():
    cache = CompileCache()
    key = compile_cache_key(GRAPH_HASH, SliceRect("hall-a", (0,), (8,)), "stitch-ab")
    cache.put(key, TOPOLOGY_HASH, artifact="plan")
    assert cache.get(key, TOPOLOGY_HASH).usable
    stale = cache.get(key, "dead")
    assert stale.status == "stale" and stale.entry is not None
    assert cache.stale_keys("dead") == [key]
    assert cache.get("absent", TOPOLOGY_HASH).status == "miss"
    assert len(cache.refusals) == 1


def test_an_entry_with_no_topology_could_never_be_checked():
    with pytest.raises(ValueError, match="never be checked"):
        CompileCache().put("k", "", artifact="plan")


# --- delay node -----------------------------------------------------------


def test_latency_follows_distance_rather_than_being_set_by_hand():
    near, far = DelayNode("s", distance_km=10.0), DelayNode("s", distance_km=100.0)
    assert far.rtt_us > near.rtt_us
    assert 9.5 < (far.rtt_us - near.rtt_us) / 90.0 < 10.0


def test_amplification_reduces_loss_but_never_below_zero():
    node = DelayNode("s", distance_km=100.0, amplifier_gain_db=1_000.0)
    assert node.insertion_loss_db == 0.0


@pytest.mark.parametrize(
    "kw", [{"distance_km": -1.0}, {"bandwidth_gbps": 0.0},
           {"bit_error_rate": 2.0}, {"amplifier_gain_db": -1.0}])
def test_the_delay_node_rejects_impossible_settings(kw):
    with pytest.raises(ValueError):
        DelayNode("s", **{"distance_km": 1.0, **kw})


def test_a_dark_node_reports_nothing_rather_than_something_stale():
    m = DelayNode("s", distance_km=40.0).go_dark().measure()
    assert m.reachable is False
    assert m.rtt_us is None and m.insertion_loss_db is None and m.regime is None


def test_netem_says_when_it_cannot_express_the_error_rate():
    assert "below netem resolution" in DelayNode("s", distance_km=1.0).netem_command()
    loud = DelayNode("s", distance_km=1.0, bit_error_rate=1e-4)
    assert "loss 0.010000%" in loud.netem_command()


def test_a_probe_for_the_wrong_stitch_is_an_error_not_a_merge():
    with pytest.raises(ValueError, match="measurement is for stitch"):
        apply_measurement(clean(), DelayNode("other", distance_km=1.0).measure())


def test_a_probe_overwrites_the_declared_path():
    node = DelayNode("stitch-ab", distance_km=40.0)
    env = apply_measurement(clean(), EmulatedController((node,)).probe("stitch-ab"))
    assert env.span_rtt_us == pytest.approx(node.rtt_us)
    assert env.measured_il_db == pytest.approx(node.insertion_loss_db)
    assert env.stitch_api_reachable is True


def test_the_delay_node_flips_the_decision_across_a_regime():
    near = validate(apply_measurement(
        clean(),
        EmulatedController((DelayNode("stitch-ab", distance_km=40.0),)).probe("stitch-ab")))
    far = validate(apply_measurement(
        clean(),
        EmulatedController((DelayNode("stitch-ab", distance_km=400.0),)).probe("stitch-ab")))
    assert near.decision is Decision.SPAN
    assert far.decision is not Decision.SPAN


def test_the_controller_knows_which_stitches_it_has():
    with pytest.raises(KeyError):
        EmulatedController((DelayNode("a", distance_km=1.0),)).probe("b")


# --- audit ----------------------------------------------------------------


def test_the_chain_verifies_and_detects_a_truncation():
    envs = [clean(), clean(span_rtt_us=40_000.0), clean(blast_radius=5)]
    records, previous = [], ""
    for env in envs:
        record = audit_record(env, validate(env), previous_hash=previous)
        records.append(record)
        previous = record["chain"]
    assert verify_chain(records)
    assert not verify_chain(records[1:])
    assert not verify_chain([records[0], records[2]])


def test_the_record_carries_the_policy_that_produced_it():
    record = audit_record(clean(), validate(clean()), Policy(measurement_ttl_s=99.0))
    assert record["policy"]["measurement_ttl_s"] == 99.0
    assert record["decision"] == "span"


# --- schema and cli -------------------------------------------------------


def test_the_committed_schema_matches_the_code():
    committed = json.loads((ROOT / "schema" / "span_contract.schema.json").read_text())
    assert committed == envelope_schema(), (
        "schema/span_contract.schema.json is stale; regenerate it with `make schema`"
    )


def test_the_schema_requires_exactly_the_specified_fields():
    schema = envelope_schema()
    assert schema["required"] == list(SPEC_FIELDS)
    assert not schema["additionalProperties"]
    assert set(schema["properties"]["autonomy_level"]["enum"]) == set(AUTONOMY_LEVELS)


def test_the_cli_separates_a_refusal_from_a_broken_envelope(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(clean().to_dict()))
    assert main(["validate", str(good)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(clean(span_rtt_us=40_000.0).to_dict()))
    assert main(["validate", str(bad)]) == 1

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert main(["validate", str(broken)]) == 2


def test_the_cli_emits_an_example_that_validates(tmp_path, capsys):
    assert main(["example"]) == 0
    payload = json.loads(capsys.readouterr().out)
    env = SpanEnvelope.from_dict(payload)
    # The example declares blast_radius 2, which escalates by design: an example
    # that sailed through would teach the reader nothing about what the contract
    # is for.
    assert validate(env).decision is Decision.ESCALATE


def test_the_cli_prints_the_schema_and_a_probe(capsys):
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "Span envelope"
    assert main(["probe", "--distance-km", "40"]) == 0
    assert "netem" in capsys.readouterr().out


def test_the_cli_reads_a_plant_file(tmp_path, capsys):
    plant = tmp_path / "plant.json"
    plant.write_text(json.dumps({
        "halls": ["hall-a", "hall-b"],
        "stitches": [{"stitch_id": "stitch-ab", "halls": ["hall-a", "hall-b"]}],
        "job_halls": ["hall-a", "hall-b"],
        "anchor": "hall-a",
        "current_topology_hash": TOPOLOGY_HASH,
    }))
    envelope = tmp_path / "env.json"
    envelope.write_text(json.dumps(clean().to_dict()))
    assert main(["validate", str(envelope), "--plant", str(plant), "--json"]) == 1
    record = json.loads(capsys.readouterr().out)
    assert record["decision"] == "deny"
    assert verify_chain([record])
