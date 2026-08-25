import numpy as np
import pandas as pd
import pytest

from dynamics.batched_replay import (
    BatchConfig,
    EffectivePriceSummary,
    OnlineSummary,
    run_batch,
)
from dynamics.empirical_shocks import (
    _mean_one_log_center,
    _parent_bal_weight_center,
)
from dynamics.glamsterdam_replay import GlamsterdamConfig, run_glamsterdam_batch


def test_log_residual_centering_produces_mean_one_level_shocks():
    values = pd.DataFrame(
        {
            "execution": [-2.0, -0.5, 0.0, 1.0, 2.5],
            "data": [-1.0, -0.25, 0.0, 0.25, 1.0],
        }
    )

    centred = _mean_one_log_center(values)

    assert np.exp(centred).mean(axis=0).to_numpy() == pytest.approx([1.0, 1.0])


def test_access_centering_preserves_parent_bal_anchor():
    access = pd.Series([-0.5, 0.0, 0.8, 1.2])
    parent_bal = np.array([4.0, 2.0, 1.0, 0.5])

    centred = _parent_bal_weight_center(access, parent_bal)

    assert np.average(np.exp(centred), weights=parent_bal) == pytest.approx(1.0)
    assert np.exp(centred).mean() != pytest.approx(1.0)


def test_online_summary_reports_blockwise_union_of_limit_hits():
    summary = OnlineSummary(batch_size=1)
    fees = np.ones((1, 3))
    limits = np.array([[100.0, 100.0, np.inf]])

    summary.update(
        fees, fees,
        np.array([[100.0, 50.0, 0.0]]),
        np.array([[120.0, 50.0, 0.0]]),
        limits,
    )
    summary.update(
        fees, fees,
        np.array([[50.0, 100.0, 0.0]]),
        np.array([[50.0, 120.0, 0.0]]),
        limits,
    )

    result = summary.to_dict()
    assert result["limit_hit_fraction"][0, :2] == pytest.approx([0.5, 0.5])
    assert result["offered_limit_pressure_fraction"][0, :2] == pytest.approx(
        [0.5, 0.5]
    )
    assert result["scale_determining_fraction"][0, :2] == pytest.approx([0.5, 0.5])
    assert result["any_limit_hit_fraction"][0] == pytest.approx(1.0)
    assert result["any_near_limit_fraction"][0] == pytest.approx(1.0)
    assert result["near_limit_fraction"][0, :2] == pytest.approx([0.5, 0.5])


def test_online_summary_distinguishes_floor_presence_from_downward_pressure():
    summary = OnlineSummary(batch_size=1)
    fees = np.ones((1, 3))
    targets = np.full((1, 3), 100.0)
    limits = np.full((1, 3), 200.0)

    summary.update(
        fees, fees,
        np.array([[50.0, 100.0, 120.0]]),
        np.array([[50.0, 100.0, 120.0]]),
        limits,
        targets=targets,
    )
    summary.update(
        fees, fees,
        np.array([[120.0, 50.0, 100.0]]),
        np.array([[120.0, 50.0, 100.0]]),
        limits,
        targets=targets,
    )

    result = summary.to_dict()
    assert result["floor_fraction"][0] == pytest.approx([1.0, 1.0, 1.0])
    assert result["floor_downward_pressure_fraction"][0] == pytest.approx(
        [0.5, 0.5, 0.0]
    )
    assert result["floor_downward_pressure_given_floor"][0] == pytest.approx(
        [0.5, 0.5, 0.0]
    )
    assert result["mean_absolute_target_gap"][0] == pytest.approx(
        [35.0, 25.0, 10.0]
    )
    assert result["mean_absolute_target_deviation"][0] == pytest.approx(
        [0.35, 0.25, 0.10]
    )
    assert result["mean_burn_wei"][0] == pytest.approx([85.0, 75.0, 110.0])
    assert result["mean_total_burn_wei"][0] == pytest.approx(270.0)


def test_effective_price_summary_retains_log_level_moments():
    summary = EffectivePriceSummary(batch_size=1)
    previous = np.ones((1, 3))
    for level in (1.0, 2.0, 4.0):
        prices = np.full((1, 3), level)
        summary.update(prices, previous)
        previous = prices

    result = summary.to_dict()
    expected = np.log(np.array([1.0, 2.0, 4.0]))
    assert result["effective_price_mean_log_level"][0] == pytest.approx(
        np.full(3, expected.mean())
    )
    assert result["effective_price_mean_square_log_level"][0] == pytest.approx(
        np.full(3, np.square(expected).mean())
    )


def test_batched_7999_bundle_consistent_caps_keep_parent_bal_together():
    one = np.ones(1)
    config = BatchConfig(
        execution_target=one * 100.0,
        execution_limit=one * 100.0,
        data_target=one * 60.0,
        data_limit=one * 80.0,
        state_target=one * 50.0,
        eps_execution=one * 0.0,
        eps_data=one * 0.0,
        eps_state=one * 0.0,
        w_execution=one * 0.5,
        w_state=one * 0.5,
        rho_A=one,
        m_execution=1.0,
        m_state=1.0,
        m_data_static=1.0,
        q_execution_0=100.0,
        q_state_0=50.0,
        g_static_0=50.0,
        p0_gwei=1.0,
    )
    shocks = np.array([[[2.0, 1.0, 1.0, 1.0]]])
    initial_fees = np.ones((1, 3))

    with pytest.raises(TypeError, match="bundle_consistent"):
        run_batch(config, shocks, initial_fees)

    separate = run_batch(
        config, shocks, initial_fees, return_paths=True,
        bundle_consistent=False,
    )
    consistent = run_batch(
        config, shocks, initial_fees, return_paths=True, bundle_consistent=True
    )

    assert separate["used_paths"][0, 0] == pytest.approx([100.0, 80.0, 50.0])
    assert consistent["used_paths"][0, 0] == pytest.approx([64.0, 80.0, 32.0])
    assert consistent["offered_limit_pressure_fraction"][0, :2] == pytest.approx(
        [1.0, 1.0]
    )
    assert consistent["included_limit_fraction"][0, :2] == pytest.approx(
        [0.0, 1.0]
    )
    assert consistent["cap_active_fraction"][0, :2] == pytest.approx([1.0, 1.0])
    assert consistent["scale_determining_fraction"][0, :2] == pytest.approx(
        [0.0, 1.0]
    )
    assert consistent["both_caps_active_fraction"][0] == pytest.approx(1.0)
    assert consistent["mean_data_components_offered"][0] == pytest.approx(
        [50.0, 100.0, 25.0]
    )
    assert consistent["mean_data_components_included"][0] == pytest.approx(
        [32.0, 32.0, 16.0]
    )
    assert consistent["mean_data_components_included"][0].sum() == pytest.approx(
        consistent["mean_used"][0, 1]
    )
    assert separate["mean_data_components_included"][0].sum() == pytest.approx(
        separate["mean_used"][0, 1]
    )


def test_glamsterdam_caps_both_branches_as_one_transaction_bundle():
    one = np.ones(1)
    config = GlamsterdamConfig(
        gas_target=one * 50.0,
        gas_limit=one * 100.0,
        eps_execution=one * 0.0,
        eps_data=one * 0.0,
        eps_state=one * 0.0,
        m_execution=1.0,
        m_data=1.0,
        m_state=1.0,
        w_execution=0.5,
        w_state=0.5,
        q_execution_0=80.0,
        q_data_0=30.0,
        q_state_0=200.0,
        p0_gwei=1.0,
    )

    result = run_glamsterdam_batch(
        config,
        np.ones((1, 1, 4)),
        initial_base_fee_wei=np.array([100.0]),
    )

    assert result["mean_included_execution"][0] == pytest.approx(40.0)
    assert result["mean_included_data"][0] == pytest.approx(15.0)
    assert result["mean_used"][0, 2] == pytest.approx(100.0)
    assert result["mean_rationed_execution"][0] == pytest.approx(40.0)
    assert result["mean_rationed_data"][0] == pytest.approx(15.0)
    assert result["mean_rationed_state"][0] == pytest.approx(100.0)
    assert result["mean_bal_payload"][0] == pytest.approx(70.0)
