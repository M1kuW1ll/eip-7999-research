from dataclasses import replace

import numpy as np
import pytest

from dynamics.glamsterdam_replay import update_base_fee_1559 as frozen_update
from shared_fee.equilibrium import (
    SharedFeeAnchor,
    offered_gas,
    solve_shared_fee_equilibrium,
)
from shared_fee.replay import SharedFeeConfig, run_shared_fee_batch, update_base_fee_1559


def anchor() -> SharedFeeAnchor:
    return SharedFeeAnchor(
        q_execution=23_942_241.363,
        q_data=1_180_555.063,
        q_state=5_244_154.704,
        m_execution=1.4479558695732846,
        m_data=1.955090,
        m_state=5.656315,
        reference_fee_gwei=0.1069278435,
        eps_execution=0.121160,
        eps_data=0.229476,
        eps_state=0.334864,
    )


def test_shared_fee_update_matches_frozen_eip1559_driver():
    rng = np.random.default_rng(1559)
    fees = rng.integers(1, 10**12, size=4_080).astype(float)
    targets = rng.integers(1_000_000, 300_000_000, size=4_080).astype(float)
    used = rng.uniform(0, 2, size=4_080) * targets
    assert np.array_equal(
        update_base_fee_1559(fees, used, targets),
        frozen_update(fees, used, targets),
    )


def test_equilibrium_clears_target_above_floor():
    result = solve_shared_fee_equilibrium(100_000_000, anchor())
    assert result.base_fee_wei > 1
    assert np.isclose(result.offered_shared_gas, result.target_gas, rtol=1e-10)
    assert result.binding_branch in {"regular", "state"}


def test_equilibrium_reports_one_wei_floor_when_demand_is_insufficient():
    result = solve_shared_fee_equilibrium(1e12, anchor())
    assert result.base_fee_wei == 1
    assert result.floor_bounded
    assert result.offered_shared_gas == offered_gas(1, anchor())[0]


@pytest.mark.parametrize("cap", [1.5, 2.0])
def test_state_demand_cap_limits_price_driven_expansion(cap):
    capped = replace(anchor(), state_demand_cap_multiple=cap)
    result = offered_gas(1, capped)
    assert np.isclose(result[2], capped.m_state * capped.q_state * cap)


@pytest.mark.parametrize("cap", [1.5, 2.0])
def test_equilibrium_reports_active_state_demand_cap(cap):
    capped = replace(anchor(), state_demand_cap_multiple=cap)
    result = solve_shared_fee_equilibrium(100_000_000, capped)
    assert result.state_demand_cap_active
    assert result.binding_branch == "regular"


def test_fractional_state_cap_retains_multiplicative_state_shock():
    reference = anchor()
    config = SharedFeeConfig(
        gas_target=np.array([100_000_000.0]),
        gas_limit=np.array([1e15]),
        eps_execution=np.array([reference.eps_execution]),
        eps_data=np.array([reference.eps_data]),
        eps_state=np.array([reference.eps_state]),
        m_execution=reference.m_execution,
        m_data=reference.m_data,
        m_state=reference.m_state,
        q_execution_0=reference.q_execution,
        q_data_0=reference.q_data,
        q_state_0=reference.q_state,
        p0_gwei=reference.reference_fee_gwei,
        state_demand_cap_multiple=1.5,
    )
    shocks = np.ones((1, 1, 4))
    shocks[0, 0, 2] = 3.0
    result = run_shared_fee_batch(config, shocks, np.array([1.0]))
    np.testing.assert_allclose(result["mean_reference_state"], reference.q_state * 1.5 * 3.0)
    np.testing.assert_allclose(result["state_demand_cap_active_fraction"], 1.0)


def test_base_fee_exposure_proxy_uses_fee_times_regular_plus_state_counters():
    reference = anchor()
    config = SharedFeeConfig(
        gas_target=np.array([100_000_000.0]),
        gas_limit=np.array([1_000_000_000.0]),
        eps_execution=np.array([reference.eps_execution]),
        eps_data=np.array([reference.eps_data]),
        eps_state=np.array([reference.eps_state]),
        m_execution=reference.m_execution,
        m_data=reference.m_data,
        m_state=reference.m_state,
        q_execution_0=reference.q_execution,
        q_data_0=reference.q_data,
        q_state_0=reference.q_state,
        p0_gwei=reference.reference_fee_gwei,
        state_demand_cap_multiple=2.0,
    )
    initial_fee = np.array([1_000.0])
    result = run_shared_fee_batch(
        config,
        np.ones((1, 1, 4)),
        initial_fee,
    )
    expected = (
        result["mean_included_regular"] + result["mean_included_state"]
    ) * initial_fee
    assert np.allclose(result["mean_base_fee_exposure_proxy_wei"], expected)


def test_replay_accepts_trajectory_specific_metering_multipliers():
    reference = anchor()
    config = SharedFeeConfig(
        gas_target=np.array([100_000_000.0, 100_000_000.0]),
        gas_limit=np.array([1_000_000_000.0, 1_000_000_000.0]),
        eps_execution=np.full(2, reference.eps_execution),
        eps_data=np.full(2, reference.eps_data),
        eps_state=np.full(2, reference.eps_state),
        m_execution=np.full(2, reference.m_execution),
        m_data=np.array([reference.m_data, reference.m_data * 2]),
        m_state=np.array([reference.m_state, reference.m_state * 2]),
        q_execution_0=reference.q_execution,
        q_data_0=reference.q_data,
        q_state_0=reference.q_state,
        p0_gwei=reference.reference_fee_gwei,
    )
    result = run_shared_fee_batch(
        config,
        np.ones((2, 1, 4)),
        np.full(2, 1_000.0),
    )
    assert result["mean_included_data"][1] > result["mean_included_data"][0]
    assert result["mean_included_state"][1] > result["mean_included_state"][0]
