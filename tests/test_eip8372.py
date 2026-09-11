"""Accounting and calibration checks independent of the cached experiment."""
import numpy as np
import pytest

from shared_fee.equilibrium import SharedFeeAnchor
from shared_fee.normalized_state import (calibrate, normalized_state_gas, scaled_state_limit,
    integer_fee_update, branch_quantities, solve_normalized_equilibrium,
    NormalizedStateConfig, run_normalized_batch)


def test_exact_integer_percentage_accounting():
    assert int(scaled_state_limit(101,137)) == 138
    assert int(normalized_state_gas(138,137)) == 100
    assert int(normalized_state_gas(139,137)) == 101
    # The raw constraint is separate: 139 is invalid even though normalized
    # gas does not exceed a common limit of 101.
    assert 139 > scaled_state_limit(101,137)
    assert normalized_state_gas(3_673_202_500_000,667855) == 550_000_000
    with pytest.raises(ValueError):
        normalized_state_gas(100,0)


def test_exact_1559_rounding_and_low_fee_deadband():
    np.testing.assert_array_equal(integer_fee_update([8,8,8],[200,100,0],[100]*3),[9,8,7])
    np.testing.assert_array_equal(integer_fee_update([1,1,48],[101,0,99],[100]*3),[2,1,48])


def anchor():
    return SharedFeeAnchor(24e6,1.2e6,5.2e6,1.45,3.1,20.74,.1069,.12116,.229476,.334864)


def test_calibration_aligns_normalized_branches_and_preserves_bytes():
    a=anchor()
    result=calibrate(550e6,5610,20.74/5610,a)
    assert result['state_gas_limit_scale']==result['cpsb']*100//5610
    assert abs(result['equilibrium_regular_utilization']-1)<1e-5
    assert abs(result['equilibrium_state_utilization']-1)<1e-5
    assert abs(result['byte_capacity_relative_error'])<1e-5
    np.testing.assert_allclose(result['ideal_scale'],result['baseline_state_root_wei']/result['regular_root_wei'])
    np.testing.assert_allclose(result['state_byte_price_wei'],5610*result['baseline_state_root_wei'],rtol=1e-5)


def test_state_price_is_raw_and_capacity_is_normalized():
    a=anchor()
    _,_,raw1,n1=branch_quantities(100,a,a.m_state,100)
    _,_,raw2,n2=branch_quantities(100,a,a.m_state*10,1000)
    np.testing.assert_allclose(n2/n1,10**-a.eps_state)
    np.testing.assert_allclose(raw2/n2,10)
    # Increasing CPSB must change demand even with exactly scaled capacity.
    assert n2<n1


def test_unity_replay_integer_caps_and_determinism():
    a=anchor();r=calibrate(550e6,5610,20.74/5610,a)
    arr=lambda v:np.array([v,v])
    c=NormalizedStateConfig(arr(r['shared_limit']),arr(r['shared_target']),arr(r['cpsb']),
        arr(r['state_gas_limit_scale']),arr(a.eps_execution),arr(a.eps_data),arr(a.eps_state),
        arr(a.m_execution),arr(a.m_data),20.74/5610,a.q_execution,a.q_data,a.q_state,a.reference_fee_gwei*1e9)
    shocks=np.ones((2,200,4));shocks[1,:,2]=10
    out=run_normalized_batch(c,shocks,arr(r['launch_fee_wei']),burn_in=20,return_paths=True)
    assert np.max(out['used_paths'][:,:,1:])<=r['shared_limit']
    assert out['state_utilization'][1]<=2
    assert np.isfinite(out['log_return_sd']).all()
    assert out['mean_execution'][1]<out['mean_execution'][0]
    np.testing.assert_allclose(out['mean_state_normalized'],out['mean_state_raw']*100/r['state_gas_limit_scale'],atol=1)
    again=run_normalized_batch(c,shocks,arr(r['launch_fee_wei']),burn_in=20)
    np.testing.assert_array_equal(again['mean_execution'],out['mean_execution'])


def test_frozen_scale_can_switch_equilibrium_branch():
    a=anchor();r=calibrate(550e6,5610,20.74/5610,a)
    alternatives=[]
    for epsilon in (.07,.2):
        alt=SharedFeeAnchor(a.q_execution,a.q_data,a.q_state,a.m_execution,a.m_data,a.m_state,
            a.reference_fee_gwei,epsilon,a.eps_data,a.eps_state)
        alternatives.append(solve_normalized_equilibrium(r['shared_target'],alt,r['m_state_raw'],r['state_gas_limit_scale']))
    assert {x['equilibrium_branch'] for x in alternatives}=={'regular','state'}


def test_fixed_7999_equilibrium_all_floor_regimes():
    import runpy
    from pathlib import Path
    module=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/shared_fee/run_eip8372_calibration.py'))
    specs,base,source,demand,metering=module['inputs']()
    for _, spec in specs.iterrows():
        for e,d in ((300e6,90e6),(225e6,60e6),(175e6,36e6)):
            fees,used=module['fixed_7999_equilibrium'](e,d,demand,metering,spec)
            assert min(fees)>=1 and np.all(used<=np.array([e,d,75e6])*(1+1e-10))
    fees,_=module['fixed_7999_equilibrium'](300e6,90e6,demand,metering,specs[specs.window_days.eq(75)].iloc[0])
    assert fees[0]==1 and fees[1]==1


def test_raw_state_limit_counts_even_if_normalized_counter_is_below_limit():
    a=lambda x:np.array([x])
    config=NormalizedStateConfig(a(101),a(50),a(137),a(137),a(0),a(0),a(0),
        a(1),a(1),1.,10.,1.,10.,100.)
    out=run_normalized_batch(config,np.ones((1,4,4)),a(100),return_paths=True)
    assert out['mean_any_limit'][0]==1
    assert out['mean_state_limit'][0]==1
    assert out['mean_regular_limit'][0]==0
    assert np.all(out['used_paths'][0,:,2]==100)
    assert out['included_limit_fraction'][0,1]==0


def test_charge_proxy_uses_raw_counter_and_pre_update_fee_after_burn_in():
    a=lambda x:np.array([x])
    config=NormalizedStateConfig(a(101),a(50),a(137),a(137),a(0),a(0),a(0),
        a(1),a(1),1.,10.,1.,10.,100.)
    out=run_normalized_batch(config,np.ones((1,4,4)),a(100),burn_in=1,return_paths=True)
    # Raw state is capped at 138; its normalized counter is only 100.
    pre_update=np.r_[100.,out['fee_paths'][0,:-1]]
    regular=out['used_paths'][0,:,1]
    expected=np.mean(pre_update[1:]*(regular[1:]+138)/1e18)
    np.testing.assert_allclose(out['mean_base_fee_exposure_eth'][0],expected,rtol=1e-14)
    assert expected>np.mean(pre_update[1:]*(regular[1:]+100)/1e18)
