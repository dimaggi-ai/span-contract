"""Conditional cut refusal and unchanged valid LR2 semantics."""
import json
import pytest
from test_contract import clean
from spancontract import Decision, Policy, validate
from spancontract.cli import main
from spancontract.rules import rule_tensor_parallel_never_spans


@pytest.mark.parametrize('cut', [None, '', 'tensor-parallel', 'TP-8', 'unknown', 0, True, [], {}, b'tp'])
def test_spanning_unsupported_cut_is_denied(cut):
    env = clean(labels={**clean().labels, 'cut': cut})
    verdict = validate(env)
    assert verdict.decision is Decision.DENY
    assert any(f.rule_id == 'LR2' and f.decision is Decision.DENY for f in verdict.findings)


def test_missing_cut_refusal_and_recovery():
    env = clean(labels={'graph_hash': clean().labels['graph_hash']})
    assert validate(env).decision is Decision.DENY
    assert validate(env.replace(labels={**env.labels, 'cut': 'pp'})).decision is Decision.SPAN


@pytest.mark.parametrize('cut', ['pp', 'dp', 'PP', 'DP', 'tp', 'tensor', 'tensor_parallel', 'TP', 'TeNsOr', 'TENSOR_PARALLEL'])
def test_recognized_cuts_preserve_decisions(cut):
    verdict = validate(clean(labels={**clean().labels, 'cut': cut}))
    expected = Decision.SPAN if cut.lower() in ('pp', 'dp') else Decision.SHRINK
    assert verdict.decision is expected


@pytest.mark.parametrize('cut', [None, '', 'TP-8', 0, [], {}])
def test_hall_local_cut_is_not_applicable(cut):
    env = clean(span_mode='local', labels={**clean().labels, 'cut': cut})
    assert not env.spans_halls
    assert rule_tensor_parallel_never_spans(env, Policy()) is None


def test_tensor_threshold_is_unchanged():
    policy = Policy()
    env = clean(labels={**clean().labels, 'cut': 'tp'}, span_rtt_us=policy.tensor_parallel_max_rtt_us)
    assert rule_tensor_parallel_never_spans(env, policy) is None
    finding = rule_tensor_parallel_never_spans(env.replace(span_rtt_us=policy.tensor_parallel_max_rtt_us + 1), policy)
    assert finding.decision is Decision.SHRINK


def test_public_cli_refusal_and_corrected_recovery(tmp_path, capsys):
    path = tmp_path / 'envelope.json'
    env = clean(labels={**clean().labels, 'cut': 'tensor-parallel'})
    path.write_text(json.dumps(env.to_dict()))
    assert main(['validate', str(path)]) == 1
    output = capsys.readouterr().out
    assert 'DENY' in output and '[LR2]' in output
    path.write_text(json.dumps(env.replace(labels={**env.labels, 'cut': 'pp'}).to_dict()))
    assert main(['validate', str(path)]) == 0
    assert 'SPAN' in capsys.readouterr().out
