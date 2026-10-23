"""Target-ratio calibration and parity with the preserved integer kernel."""
import numpy as np
import pytest

from shared_fee.equilibrium import SharedFeeAnchor
from shared_fee.normalized_state import (
    NormalizedStateConfig, calibrate, integer_fee_update, run_normalized_batch,
)
from shared_fee.target_ratio import (
    calibrate_at_target, continuous_fee_update, run_ratio_batch,
)


def anchor():
    return SharedFeeAnchor(24e6, 1.2e6, 5.2e6, 1.45, 3.1, 20.74,
                          .1069, .12116, .229476, .334864)


def configuration(ratio, paths=2):
    a = anchor()
    target = int(550e6 * ratio)
    r = calibrate_at_target(550e6, target, 5610 * ratio / .5, 20.74 / 5610, a)
    arr = lambda v: np.full(paths, v)
    c = NormalizedStateConfig(
        arr(r['shared_limit']), arr(target), arr(r['cpsb']),
        arr(r['state_gas_limit_scale']), arr(a.eps_execution), arr(a.eps_data),
        arr(a.eps_state), arr(a.m_execution), arr(a.m_data), 20.74 / 5610,
        a.q_execution, a.q_data, a.q_state, a.reference_fee_gwei * 1e9)
    return c, r


def test_half_target_calibration_is_identical():
    old = calibrate(550e6, 5610, 20.74 / 5610, anchor())
    new = calibrate_at_target(550e6, 275e6, 5610, 20.74 / 5610, anchor())
    assert new == old


@pytest.mark.parametrize('ratio', [.5, .6, 2/3, .75, .8])
def test_calibration_preserves_byte_target_not_byte_limit(ratio):
    c, r = configuration(ratio)
    assert abs(r['equilibrium_regular_utilization'] - 1) < 1e-5
    assert abs(r['equilibrium_state_utilization'] - 1) < 1e-5
    np.testing.assert_allclose(r['shared_target'] / r['baseline_cpsb'],
                               275e6 / 5610, rtol=2e-4)
    np.testing.assert_allclose(r['max_state_bytes'], 275e6 / 5610 / ratio, rtol=2e-4)
    assert c.gas_target[0] < c.gas_limit[0]


@pytest.mark.parametrize('ratio', [.5, .6, 2/3, .75, .8])
def test_integer_replay_matches_original_exactly(ratio):
    c, r = configuration(ratio)
    shocks = np.exp(np.random.default_rng(8372).normal(0, .8, (2, 220, 4)))
    initial = np.full(2, 49)
    old = run_normalized_batch(c, shocks, initial, burn_in=20)
    new = run_ratio_batch(c, shocks, initial, burn_in=20)
    for key in old:
        np.testing.assert_array_equal(new[key], old[key], err_msg=key)
    assert np.all(new['mean_below_target_zero_decrease'] <= new['mean_below_target'])
    assert np.all(new['minimum_measured_fee_wei'] >= 7)


def test_fractional_controller_and_integer_deadband():
    np.testing.assert_allclose(continuous_fee_update([8, 3, 3], [200, 0, 100],
                                                   [100, 100, 80]), [9, 2.625, 3.09375])
    np.testing.assert_array_equal(integer_fee_update(np.arange(1, 8), 0, 100),
                                  np.arange(1, 8))
    assert integer_fee_update(8, 0, 100) == 7
    assert continuous_fee_update(1, 0, 100) == 1
    c, r = configuration(.8)
    output = run_ratio_batch(c, np.ones((2, 2000, 4)), np.full(2, 49.),
                             burn_in=1000, controller='continuous')
    np.testing.assert_allclose(output['regular_utilization'], 1, rtol=1e-3)


def test_invalid_target_and_controller_rejected():
    with pytest.raises(ValueError):
        calibrate_at_target(550e6, 550e6, 5610, .0037, anchor())
    c, r = configuration(.5)
    with pytest.raises(ValueError):
        run_ratio_batch(c, np.ones((2, 10, 4)), np.full(2, 49), controller='exponential')
