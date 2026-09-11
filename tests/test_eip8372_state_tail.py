"""Frozen-calibration caps: price response, integer replay, and parity."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from shared_fee.equilibrium import SharedFeeAnchor
from shared_fee.normalized_state import NormalizedStateConfig, calibrate, run_normalized_batch
from shared_fee.normalized_state_tail import run_capped_normalized_batch, solve_capped_equilibrium


def setup():
    a = SharedFeeAnchor(24e6,1.2e6,5.2e6,1.45,3.1,20.74,.1069,.12116,.229476,.334864)
    r = calibrate(550e6,5610,20.74/5610,a)
    arr = lambda v: np.array([v,v])
    c = NormalizedStateConfig(arr(r['shared_limit']),arr(r['shared_target']),arr(r['cpsb']),
        arr(r['state_gas_limit_scale']),arr(a.eps_execution),arr(a.eps_data),arr(a.eps_state),
        arr(a.m_execution),arr(a.m_data),20.74/5610,a.q_execution,a.q_data,a.q_state,a.reference_fee_gwei*1e9)
    return a,r,c


def test_uncapped_replay_matches_original_exactly():
    a,r,c = setup()
    shocks = np.exp(np.random.default_rng(8372).normal(0,.7,(2,200,4)))
    launch = np.array([r['launch_fee_wei']]*2)
    old = run_normalized_batch(c,shocks,launch,burn_in=20,return_paths=True)
    new = run_capped_normalized_batch(c,shocks,launch,np.inf,burn_in=20,return_paths=True)
    for key in new.keys() & old.keys():
        np.testing.assert_array_equal(new[key],old[key],err_msg=key)
    assert np.all(new['mean_cap_active']==0)


def test_caps_preserve_calibration_and_remove_only_unreachable_state_root():
    a,r,c = setup()
    for cap in (1.5,2,3,4,5,np.inf):
        eq = solve_capped_equilibrium(r['shared_target'],a,r['m_state_raw'],r['state_gas_limit_scale'],cap)
        assert eq['equilibrium_fee_wei'] >= 1
        assert eq['equilibrium_regular_utilization'] <= 1+1e-10
        assert eq['equilibrium_state_utilization'] <= 1+1e-10
        if cap <= 2:
            assert eq['equilibrium_branch']=='regular'
            assert not eq['state_target_reachable']
            assert eq['equilibrium_fee_wei']==r['regular_root_wei']
        else:
            assert eq['equilibrium_fee_wei']==r['equilibrium_fee_wei']
    for bad in (0,-1,np.nan):
        with pytest.raises(ValueError):
            solve_capped_equilibrium(r['shared_target'],a,r['m_state_raw'],r['state_gas_limit_scale'],bad)


def test_cap_precedes_shock_and_uses_raw_state_price():
    _,_,c = setup()
    # Plenty of capacity: no inclusion clipping. A positive shock can produce
    # more than cap * anchor; the cap is not a per-block quantity ceiling.
    c = replace(c,gas_limit=np.array([10**12]*2),gas_target=np.array([5*10**11]*2))
    shock = np.ones((2,1,4));shock[1,0,2]=2
    out = run_capped_normalized_batch(c,shock,np.array([1,1]),1.5)
    expected = np.floor(c.cpsb*c.bytes_per_reference_state*c.q_state_0*1.5*shock[:,0,2])/c.cpsb
    np.testing.assert_array_equal(out['mean_state_bytes'],expected)
    assert np.all(out['mean_cap_active']==1)


def test_cached_cap_results_and_preserved_sources():
    root = Path(__file__).resolve().parents[1]
    data = root/'data/shared_fee/eip8372'
    folder = data/'state_tail'
    outcomes = pd.read_csv(folder/'normalized_outcomes.csv')
    paths = pd.read_csv(folder/'normalized_paths.csv')
    manifest = json.loads((folder/'manifest.json').read_text())
    original = json.loads((data/'manifest.json').read_text())
    assert manifest['workload_sha256']==original['workload_sha256']
    assert manifest['burn_in_blocks']==7200 and manifest['measured_blocks']==50400
    for path,digest in {**manifest['protected_sha256'],**manifest['implementation_sha256']}.items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest()==digest,path
    assert len(outcomes)==6 and len(paths)==192
    assert paths.groupby('state_demand_cap_label').replication.nunique().eq(32).all()
    central = pd.read_csv(data/'normalized_outcomes.csv')
    central = central[(central.window_days==35)&(central.propagation_time_s==3)].iloc[0]
    for column in ('cpsb','state_gas_limit_scale','shared_limit','shared_target','floor_rate'):
        assert outcomes[column].eq(central[column]).all()
    for metric in ('metered_execution_gas','annualized_state_growth_gib','state_binding_fraction',
                   'hard_limit_fraction','execution_price_variation'):
        np.testing.assert_allclose(paths.groupby('state_demand_cap_label')[metric].mean().sort_index(),
            outcomes.set_index('state_demand_cap_label')[metric].sort_index(),rtol=1e-13)
        control = outcomes[outcomes.state_demand_cap_label.eq('unrestricted')].iloc[0]
        np.testing.assert_allclose(control[metric],central[metric],rtol=1e-13)
    np.testing.assert_allclose(outcomes.state_binding_fraction+outcomes.regular_binding_fraction+
        outcomes.branch_tie_fraction,1)


def test_cap_gains_are_paired_not_a_uniform_dominance_claim():
    root = Path(__file__).resolve().parents[1]
    folder = root/'data/shared_fee/eip8372/state_tail'
    gains = pd.read_csv(folder/'paired_gains.csv')
    paths = pd.read_csv(folder/'paired_gain_paths.csv')
    assert len(gains)==36 and len(paths)==1152
    np.testing.assert_allclose(paths.execution_gain,
        paths.metered_execution_gas_7999-paths.metered_execution_gas_one_dimensional)
    keys = ['benchmark_one_dimensional','benchmark_7999','state_demand_cap_label','propagation_time_s']
    for key,g in paths.groupby(keys):
        assert len(g)==32 and g.replication.nunique()==32
        row = gains.set_index(keys).loc[key]
        np.testing.assert_allclose([row.mean_execution_gain,row.week_p05,row.week_p95,row.positive_path_fraction],
            [g.execution_gain.mean(),g.execution_gain.quantile(.05),g.execution_gain.quantile(.95),
             g.execution_gain.gt(0).mean()])
    closest = gains[(gains.benchmark_one_dimensional=='normalized_state')&
        (gains.benchmark_7999=='balanced')&(gains.state_demand_cap_label=='1.5x')].iloc[0]
    assert 0 < closest.mean_execution_gain < .2e6
    assert closest.positive_path_fraction==15/32 and closest.week_p05<0<closest.week_p95
    report = (root/'markdowns/eip8279_floor_calibration_report.md').read_text()
    caveat = report.split('### Caveat: state demand may saturate')[1].split('## Limitations')[0]
    assert 'three-second propagation' in caveat and '0.17M' in caveat
    assert '15 of 32' in caveat and 'unrestricted EIP-7999 references' in caveat
