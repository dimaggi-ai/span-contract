import dataclasses
import pytest
from spancontract.cli import _example_envelope
from spancontract.envelope import SliceRect, SliceQuota, latency_regime
from spancontract.rules import Policy
from spancontract.adapters.delay_node import PathMeasurement, DelayNode

BAD = [float('nan'), float('inf'), -float('inf'), True, 'NaN', {}, None]

@pytest.mark.parametrize('bad', BAD)
def test_measurement_mutations(bad):
    for name in ('span_rtt_us', 'span_bw_gbps', 'measured_il_db', 'measured_ber',
                 'checkpoint_window_s', 'collective_window_s', 'ingest_budget_GBps',
                 'thermal_headroom_k', 'ride_through_s', 'power_headroom_kw', 'blast_radius'):
        with pytest.raises(ValueError):
            dataclasses.replace(_example_envelope(), **{name: bad})
    if bad is not None:  # Missing age is intentionally handled by fail-closed policy.
        with pytest.raises(ValueError):
            dataclasses.replace(_example_envelope(), measured_age_s=bad)
    with pytest.raises(ValueError):
        Policy(measurement_ttl_s=bad)
    with pytest.raises(ValueError):
        PathMeasurement('s', True, age_s=bad)
    with pytest.raises(ValueError):
        DelayNode('s', bad)
    with pytest.raises(ValueError):
        SliceRect('hall', (bad,), (8,))
    with pytest.raises(ValueError):
        SliceQuota('hall', bad, 2)
    with pytest.raises(ValueError):
        latency_regime(bad)
