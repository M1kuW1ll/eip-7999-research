import numpy as np
import pandas as pd
import pytest

from demand import (
    JointShockPanel,
    ShockEstimationSpec,
    empirical_shock_path,
    estimate_joint_shocks,
    vector_moving_block_bootstrap,
)

RESOURCES = ("execution", "data", "state")


def estimation_spec(*, frequency="day", trend_window=3):
    return ShockEstimationSpec(
        time_col="time",
        usage_cols={resource: f"q_{resource}" for resource in RESOURCES},
        price_cols="price",
        elasticities={"execution": 0.1, "data": 0.2, "state": 0.3},
        frequency=frequency,
        basis="historical_physical",
        trend_window=trend_window,
    )


def test_explicit_baseline_recovers_known_deelasticized_shocks():
    times = np.arange(6)
    price = np.array([80.0, 90.0, 100.0, 120.0, 110.0, 95.0])
    baseline_values = {
        "execution": np.linspace(10.0, 12.0, 6),
        "data": np.linspace(4.0, 5.0, 6),
        "state": np.linspace(2.0, 3.0, 6),
    }
    shock_values = {
        "execution": np.array([0.8, 1.0, 1.2, 1.1, 0.9, 1.0]),
        "data": np.array([1.2, 0.8, 1.0, 0.9, 1.1, 1.0]),
        "state": np.array([0.7, 1.3, 1.0, 1.2, 0.8, 1.0]),
    }
    eps = estimation_spec().elasticities
    frame = pd.DataFrame({"time": times, "price": price})
    for resource in RESOURCES:
        frame[f"q_{resource}"] = (
            baseline_values[resource]
            * shock_values[resource]
            * (price / 100.0) ** (-eps[resource])
        )
    baseline = pd.DataFrame({"time": times, **baseline_values})

    panel = estimate_joint_shocks(
        frame, estimation_spec(), baseline=baseline, source="known_dgp"
    )

    for resource in RESOURCES:
        assert panel.values[resource].to_numpy() == pytest.approx(
            shock_values[resource]
        )
        assert panel.values[resource].mean() == pytest.approx(1.0)


def test_rolling_log_median_removes_price_only_variation():
    price = np.array([50.0, 70.0, 90.0, 110.0, 130.0])
    frame = pd.DataFrame({"time": np.arange(len(price)), "price": price})
    spec = estimation_spec(trend_window=3)
    constants = {"execution": 10.0, "data": 5.0, "state": 2.0}
    for resource in RESOURCES:
        frame[f"q_{resource}"] = constants[resource] * (price / 100.0) ** (
            -spec.elasticities[resource]
        )

    panel = estimate_joint_shocks(frame, spec)

    assert panel.values.to_numpy() == pytest.approx(np.ones((5, 3)))


def test_zero_elasticity_reduces_to_usage_over_explicit_baseline():
    frame = pd.DataFrame(
        {
            "time": [0, 1, 2],
            "price": [1.0, 10.0, 100.0],
            "q_execution": [1.0, 2.0, 3.0],
            "q_data": [2.0, 4.0, 6.0],
            "q_state": [3.0, 6.0, 9.0],
        }
    )
    spec = ShockEstimationSpec(
        time_col="time",
        usage_cols={resource: f"q_{resource}" for resource in RESOURCES},
        price_cols="price",
        elasticities={resource: 0.0 for resource in RESOURCES},
        frequency="day",
        basis="historical_physical",
        trend_window=3,
    )
    baseline = pd.DataFrame(
        {"time": [0, 1, 2], **{resource: 1.0 for resource in RESOURCES}}
    )

    panel = estimate_joint_shocks(frame, spec, baseline=baseline)

    expected = np.array([0.5, 1.0, 1.5])
    for resource in RESOURCES:
        assert panel.values[resource].to_numpy() == pytest.approx(expected)


def sample_panel(*, frequency="block"):
    values = pd.DataFrame(
        {
            "execution": np.arange(1.0, 7.0),
            "data": np.arange(1.0, 7.0) * 10,
            "state": np.arange(1.0, 7.0) * 100,
        }
    )
    return JointShockPanel(
        values=values,
        frequency=frequency,
        basis="historical_physical",
        source="fixture",
    )


def test_empirical_path_is_an_exact_auditable_slice():
    path = empirical_shock_path(sample_panel(), start=2, length=3)

    assert path.source_positions == (2, 3, 4)
    assert path.values["execution"].tolist() == [3.0, 4.0, 5.0]
    assert path.values["data"].tolist() == [30.0, 40.0, 50.0]


def test_vector_bootstrap_is_reproducible_joint_and_contiguous():
    panel = sample_panel()
    a = vector_moving_block_bootstrap(
        panel, n_steps=11, block_length=3, seed=7999, circular=True
    )
    b = vector_moving_block_bootstrap(
        panel, n_steps=11, block_length=3, seed=7999, circular=True
    )

    assert a.source_positions == b.source_positions
    pd.testing.assert_frame_equal(a.values, b.values)
    assert (a.values["data"] == 10 * a.values["execution"]).all()
    assert (a.values["state"] == 100 * a.values["execution"]).all()
    for chunk_start in range(0, len(a.source_positions), 3):
        chunk = a.source_positions[chunk_start : chunk_start + 3]
        for left, right in zip(chunk, chunk[1:]):
            assert right == (left + 1) % len(panel.values)


def test_non_circular_bootstrap_never_wraps_within_a_chunk():
    panel = sample_panel()
    path = vector_moving_block_bootstrap(
        panel, n_steps=12, block_length=4, seed=7, circular=False
    )

    for chunk_start in range(0, len(path.source_positions), 4):
        chunk = path.source_positions[chunk_start : chunk_start + 4]
        assert all(right == left + 1 for left, right in zip(chunk, chunk[1:]))


def test_day_path_must_be_explicitly_disaggregated_before_block_replay():
    daily = empirical_shock_path(sample_panel(frequency="day"))
    with pytest.raises(ValueError, match="explicit disaggregation"):
        daily.require_block_frequency(step_seconds=12)

    block = empirical_shock_path(sample_panel(frequency="block"))
    block.require_block_frequency(step_seconds=12)


def test_invalid_inputs_fail_loudly():
    frame = pd.DataFrame(
        {
            "time": [0, 1, 2],
            "price": [1.0, 1.0, 1.0],
            "q_execution": [1.0, 0.0, 1.0],
            "q_data": [1.0, 1.0, 1.0],
            "q_state": [1.0, 1.0, 1.0],
        }
    )
    with pytest.raises(ValueError, match="finite and positive"):
        estimate_joint_shocks(frame, estimation_spec())

    with pytest.raises(ValueError, match="block_length"):
        vector_moving_block_bootstrap(
            sample_panel(), n_steps=5, block_length=7, seed=1
        )
