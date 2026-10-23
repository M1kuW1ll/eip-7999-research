"""Exact EIP-4844 integer arithmetic and preservation of the original replay."""
import numpy as np
import pytest

from sim.basefee import fake_exponential
from shared_fee.excess_update import (
    ExactExponentialFees, excess_for_fee, run_controller_batch, update_denominators,
)
from shared_fee.normalized_state import integer_fee_update
from shared_fee.target_ratio import run_ratio_batch
from test_eip8372_target_ratio import configuration


def test_threshold_lookup_matches_integer_reference_including_boundaries():
    rng = np.random.default_rng(4844)
    denominators = np.repeat([800, 3_338_477, 3_520_000_000], 100)
    evaluator = ExactExponentialFees(denominators)
    excess = np.floor(rng.uniform(0, 8, len(denominators))*denominators).astype(np.int64)
    expected = [fake_exponential(1, int(x), int(d)) for x, d in zip(excess, denominators)]
    np.testing.assert_array_equal(evaluator(excess), expected)
    for fee in (1, 2, 3, 7, 8, 49, 257):
        values = np.array([excess_for_fee(fee, d) for d in denominators])
        np.testing.assert_array_equal(evaluator(values), fee)
        if fee > 1:
            assert np.all(evaluator(values-1) < fee)


def test_low_fee_changes_are_accumulated_not_discarded():
    denominator = np.array([800])
    evaluator = ExactExponentialFees(denominator)
    excess = np.array([excess_for_fee(2, 800)])
    for _ in range(10):
        excess += 1
    assert evaluator(excess)[0] == 2
    excess += 400
    assert evaluator(excess)[0] == 3
    assert integer_fee_update(7, 99, 100) == 7
    assert evaluator(np.array([excess_for_fee(7, 800)-1]))[0] == 6
    assert evaluator(np.array([0]))[0] == 1


def test_large_fee_peaks_use_exact_arithmetic_without_unbounded_threshold_cache():
    denominator = 2_200_000_000
    excess = np.array([
        excess_for_fee(fee, denominator) + offset
        for fee in (4096, 10_000, 1_000_000) for offset in (-1, 0, 1)
    ])
    evaluator = ExactExponentialFees(np.full(len(excess), denominator))
    expected = [fake_exponential(1, int(x), denominator) for x in excess]
    np.testing.assert_array_equal(evaluator(excess), expected)
    assert len(evaluator.thresholds[denominator]) <= evaluator.MAX_CACHED_FEE


def test_smoothing_calibrations():
    np.testing.assert_array_equal(update_denominators([440_000_000], 'excess_matched'),
                                  [3_520_000_000])
    value = update_denominators([440_000_000], 'excess_log1125')[0]
    np.testing.assert_allclose(440_000_000/value, np.log(1.125), rtol=1e-9)


@pytest.mark.parametrize('controller', ['integer', 'continuous'])
def test_original_controllers_reproduce_every_metric(controller):
    config, _ = configuration(.8)
    shocks = np.exp(np.random.default_rng(8372).normal(0, .8, (2, 500, 4)))
    old = run_ratio_batch(config, shocks, np.full(2, 49), burn_in=100, controller=controller)
    new = run_controller_batch(config, shocks, np.full(2, 49), burn_in=100, controller=controller)
    for key in old:
        np.testing.assert_array_equal(new[key], old[key], err_msg=key)


@pytest.mark.parametrize('controller', ['excess_matched', 'excess_log1125'])
def test_excess_controller_integer_fees_and_accumulator_identity(controller):
    config, _ = configuration(.8)
    shocks = np.exp(np.random.default_rng(8372).normal(0, .8, (2, 1200, 4)))
    result = run_controller_batch(config, shocks, np.full(2, 49), burn_in=200,
                                  controller=controller)
    assert np.all(result['minimum_measured_fee_wei'] >= 1)
    assert np.all(result['final_base_fee_wei'] == np.floor(result['final_base_fee_wei']))
    np.testing.assert_allclose(result['mean_shared']-config.gas_target,
        (result['final_excess']-result['measured_start_excess']-result['floor_reflection_gas'])/1000,
        atol=1e-7)
    assert np.all(result['mean_any_near_limit'] >= result['mean_any_limit'])
