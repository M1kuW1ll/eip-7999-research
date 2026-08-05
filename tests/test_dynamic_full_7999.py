import pandas as pd
import pytest

from demand import JointShockPath
from dynamics import (
    BundlePriced7999Demand,
    IndependentIsoelasticDemand,
    ParentBALConsistentCaps,
    ProportionalBundleCaps,
    run_driven_full_7999,
    summarize_driven_replay,
)
from mechanisms import (
    PassiveBlockUsage,
    make_full_7999_config,
    replay_full_7999,
)


def shock_path(rows, *, frequency="block"):
    values = pd.DataFrame(rows, columns=["execution", "data", "state"])
    return JointShockPath(
        values=values,
        frequency=frequency,
        basis="7999_metered",
        source="test",
        source_positions=tuple(range(len(values))),
    )


def config(*, reserve_factor=0, initial_fee=10):
    return make_full_7999_config(
        execution_gas_limit=200,
        bandwidth_gas_limit=64,
        state_gas_target=75,
        execution_target_ratio=2,
        bandwidth_target_ratio=4,
        initial_execution_base_fee=initial_fee,
        initial_bandwidth_base_fee=initial_fee,
        initial_state_base_fee=initial_fee,
        bandwidth_reserve_factor=reserve_factor,
    )


def demand(*, anchor=None, elasticities=None, reference_fee=10):
    return IndependentIsoelasticDemand(
        anchor_metered_gas=(
            {"execution": 100.0, "data": 16.0, "state": 75.0}
            if anchor is None
            else anchor
        ),
        reference_base_fees_wei={
            "execution": float(reference_fee),
            "data": float(reference_fee),
            "state": float(reference_fee),
        },
        elasticities=(
            {"execution": 0.2, "data": 0.3, "state": 0.4}
            if elasticities is None
            else elasticities
        ),
    )


def test_target_demand_keeps_reserve_off_fee_state_fixed():
    replay = run_driven_full_7999(
        config=config(),
        demand_model=demand(),
        shock_path=shock_path([[1.0, 1.0, 1.0]] * 3),
        blob_base_fee_per_gas=None,
    )

    for resource in ["execution", "data", "state"]:
        assert (
            replay[f"{resource}_included_gas"].tolist()
            == [replay[f"{resource}_gas_target"].iloc[0]] * 3
        )
        assert replay[f"{resource}_base_fee_wei"].tolist() == [10, 10, 10]
        assert replay[f"{resource}_next_base_fee_wei"].tolist() == [10, 10, 10]


def test_output_distinguishes_current_fee_from_next_block_fee():
    zero_elasticity = {"execution": 0.0, "data": 0.0, "state": 0.0}
    replay = run_driven_full_7999(
        config=config(initial_fee=1_000_000),
        demand_model=demand(
            elasticities=zero_elasticity,
            reference_fee=1_000_000,
        ),
        shock_path=shock_path([[1.5, 1.0, 1.0], [1.0, 1.0, 1.0]]),
        blob_base_fee_per_gas=None,
    )

    assert replay.loc[0, "execution_base_fee_wei"] == 1_000_000
    assert replay.loc[0, "execution_next_base_fee_wei"] > 1_000_000
    assert (
        replay.loc[1, "execution_base_fee_wei"]
        == replay.loc[0, "execution_next_base_fee_wei"]
    )


def test_data_reserve_ratchets_excess_without_hard_clamping_fee():
    replay = run_driven_full_7999(
        config=config(reserve_factor=12, initial_fee=1),
        demand_model=demand(reference_fee=1),
        shock_path=shock_path([[1.0, 1.0, 1.0]]),
        blob_base_fee_per_gas=25,
    )

    assert bool(replay.loc[0, "data_reserve_active"])
    assert replay.loc[0, "data_reserve_threshold_wei"] == 3
    assert replay.loc[0, "data_next_excess_gas"] > replay.loc[0, "data_excess_gas"]
    assert replay.loc[0, "data_next_base_fee_wei"] < 3


def test_limited_resources_are_capped_and_state_remains_uncapped():
    replay = run_driven_full_7999(
        config=config(),
        demand_model=demand(anchor={"execution": 250.0, "data": 80.0, "state": 150.0}),
        shock_path=shock_path([[1.0, 1.0, 1.0]]),
        blob_base_fee_per_gas=None,
    )

    assert replay.loc[0, "execution_offered_gas"] == 250
    assert replay.loc[0, "execution_included_gas"] == 200
    assert replay.loc[0, "execution_unserved_gas"] == 50
    assert bool(replay.loc[0, "execution_own_limit_exceeded"])
    assert bool(replay.loc[0, "execution_rationed"])
    assert replay.loc[0, "data_offered_gas"] == 80
    assert replay.loc[0, "data_included_gas"] == 64
    assert replay.loc[0, "data_unserved_gas"] == 16
    assert replay.loc[0, "state_included_gas"] == 150
    assert replay.loc[0, "state_unserved_gas"] == 0
    assert not bool(replay.loc[0, "state_rationed"])
    assert replay.loc[0, "data_next_excess_gas"] > replay.loc[0, "data_excess_gas"]


def test_proportional_bundle_rule_scales_state_when_execution_binds():
    replay = run_driven_full_7999(
        config=config(),
        demand_model=demand(anchor={"execution": 250.0, "data": 32.0, "state": 150.0}),
        shock_path=shock_path([[1.0, 1.0, 1.0]]),
        blob_base_fee_per_gas=None,
        inclusion_rule=ProportionalBundleCaps(),
    )

    assert replay.loc[0, "bundle_scale"] == pytest.approx(0.8)
    assert replay.loc[0, "binding_resources"] == "execution"
    assert replay.loc[0, "execution_included_gas"] == 200
    assert replay.loc[0, "data_included_gas"] == 16
    assert replay.loc[0, "state_included_gas"] == 120
    assert not bool(replay.loc[0, "state_own_limit_exceeded"])
    assert bool(replay.loc[0, "state_rationed"])


def test_daily_shocks_cannot_drive_twelve_second_fee_updates():
    with pytest.raises(ValueError, match="explicit disaggregation"):
        run_driven_full_7999(
            config=config(),
            demand_model=demand(),
            shock_path=shock_path([[1.0, 1.0, 1.0]], frequency="day"),
            blob_base_fee_per_gas=None,
        )


def test_summary_discards_requested_burn_in_and_reports_reserve():
    replay = run_driven_full_7999(
        config=config(),
        demand_model=demand(),
        shock_path=shock_path([[1.0, 1.0, 1.0]] * 5),
        blob_base_fee_per_gas=None,
    )

    summary = summarize_driven_replay(replay, burn_in_blocks=2).set_index("resource")

    assert (summary["blocks"] == 3).all()
    assert summary.loc["execution", "mean_included_gas"] == 100
    assert summary.loc["execution", "base_fee_floor_fraction"] == 0
    assert summary.loc["execution", "mean_target_fill"] == 1
    assert summary.loc["execution", "maximum_unserved_gas"] == 0
    assert summary.loc["data", "reserve_active_fraction"] == 0
    assert pd.isna(summary.loc["state", "own_limit_exceeded_fraction"])
    assert pd.isna(summary.loc["state", "limit_hit_fraction"])
    assert summary.loc["state", "rationed_fraction"] == 0


@pytest.mark.parametrize(
    "execution_limit,data_limit,fees",
    [
        (
            100_000_000,
            40_000_000,
            {"execution": 245_220, "data": 708_790, "state": 1_184_471},
        ),
        (
            200_000_000,
            60_000_000,
            {"execution": 803, "data": 121_103, "state": 1_184_471},
        ),
    ],
)
def test_notebook_2_0_protocol_fees_are_consistent_warm_starts(
    execution_limit, data_limit, fees
):
    targets = {
        "execution": execution_limit / 2,
        "data": data_limit / 4,
        "state": 75_000_000.0,
    }
    fixed_point_demand = IndependentIsoelasticDemand(
        anchor_metered_gas=targets,
        reference_base_fees_wei=fees,
        elasticities={"execution": 0.121160, "data": 0.229476, "state": 0.334864},
    )
    fixed_point_config = make_full_7999_config(
        execution_gas_limit=execution_limit,
        bandwidth_gas_limit=data_limit,
        state_gas_target=75_000_000,
        initial_execution_base_fee=fees["execution"],
        initial_bandwidth_base_fee=fees["data"],
        initial_state_base_fee=fees["state"],
        bandwidth_reserve_factor=0,
    )

    replay = run_driven_full_7999(
        config=fixed_point_config,
        demand_model=fixed_point_demand,
        shock_path=shock_path([[1.0, 1.0, 1.0]]),
        blob_base_fee_per_gas=None,
    )

    for resource in ["execution", "data", "state"]:
        assert replay.loc[0, f"{resource}_included_gas"] == targets[resource]
        assert (
            replay.loc[0, f"{resource}_next_base_fee_wei"]
            == replay.loc[0, f"{resource}_base_fee_wei"]
        )
        assert (
            replay.loc[0, f"{resource}_next_excess_gas"]
            == replay.loc[0, f"{resource}_excess_gas"]
        )


def test_zero_elasticity_front_end_matches_passive_replay():
    fixed_config = config(initial_fee=1_000_000)
    usages = [
        {"execution": 120, "data": 32, "state": 80},
        {"execution": 90, "data": 16, "state": 60},
        {"execution": 150, "data": 48, "state": 100},
    ]
    blocks = [
        PassiveBlockUsage(
            block_number=index,
            timestamp=None,
            execution_gas_used=row["execution"],
            bandwidth_gas=row["data"],
            bandwidth_bytes=row["data"] // 16,
            state_gas_used=row["state"],
        )
        for index, row in enumerate(usages)
    ]
    passive = replay_full_7999(blocks, fixed_config)
    zero_response = IndependentIsoelasticDemand(
        anchor_metered_gas={
            resource: 1.0 for resource in ["execution", "data", "state"]
        },
        reference_base_fees_wei={
            resource: 1.0 for resource in ["execution", "data", "state"]
        },
        elasticities={resource: 0.0 for resource in ["execution", "data", "state"]},
    )
    driven = run_driven_full_7999(
        config=fixed_config,
        demand_model=zero_response,
        shock_path=shock_path(
            [[row["execution"], row["data"], row["state"]] for row in usages]
        ),
        blob_base_fee_per_gas=None,
    )

    for index, passive_row in enumerate(passive):
        for demand_name, mechanism_name in {
            "execution": "execution",
            "data": "bandwidth",
            "state": "state",
        }.items():
            assert (
                driven.loc[index, f"{demand_name}_base_fee_wei"]
                == passive_row.base_fee_by_resource[mechanism_name]
            )
            assert (
                driven.loc[index, f"{demand_name}_excess_gas"]
                == passive_row.excess_gas_by_resource[mechanism_name]
            )


def test_runner_applies_bundle_shocks_inside_component_demand_model():
    model = BundlePriced7999Demand(
        execution_quantity_anchor=100.0,
        state_quantity_anchor=25.0,
        static_data_gas_anchor=50.0,
        historical_price_wei=100.0,
        metering_multipliers={"execution": 2.0, "data": 10.0, "state": 4.0},
        elasticities={"execution": 0.2, "data": 0.3, "state": 0.4},
        bal_intensities={"execution": 1.0, "state": 2.0},
        rho_A=1.0,
    )
    bundle_config = make_full_7999_config(
        execution_gas_limit=500,
        bandwidth_gas_limit=512,
        state_gas_target=100,
        execution_target_ratio=2,
        bandwidth_target_ratio=2,
        initial_execution_base_fee=45,
        initial_bandwidth_base_fee=10,
        initial_state_base_fee=20,
        bandwidth_reserve_factor=0,
    )
    replay = run_driven_full_7999(
        config=bundle_config,
        demand_model=model,
        shock_path=shock_path([[1.0, 2.0, 1.0]]),
        blob_base_fee_per_gas=None,
    )

    assert replay.loc[0, "static_data_gas"] == pytest.approx(100.0)
    assert replay.loc[0, "execution_bal_gas"] == pytest.approx(100.0)
    assert replay.loc[0, "state_bal_gas"] == pytest.approx(50.0)
    assert replay.loc[0, "total_bal_gas"] == pytest.approx(150.0)
    assert replay.loc[0, "data_offered_gas"] == 256
    assert replay.loc[0, "execution_offered_gas"] == 200
    assert replay.loc[0, "state_offered_gas"] == 100


def test_parent_bal_consistent_rule_removes_linked_bal_at_execution_cap():
    model = BundlePriced7999Demand(
        execution_quantity_anchor=100.0,
        state_quantity_anchor=25.0,
        static_data_gas_anchor=50.0,
        historical_price_wei=100.0,
        metering_multipliers={"execution": 2.0, "data": 10.0, "state": 4.0},
        elasticities={"execution": 0.2, "data": 0.3, "state": 0.4},
        bal_intensities={"execution": 1.0, "state": 2.0},
    )
    capped_config = make_full_7999_config(
        execution_gas_limit=150,
        bandwidth_gas_limit=512,
        state_gas_target=100,
        execution_target_ratio=2,
        bandwidth_target_ratio=2,
        initial_execution_base_fee=45,
        initial_bandwidth_base_fee=10,
        initial_state_base_fee=20,
        bandwidth_reserve_factor=0,
    )
    replay = run_driven_full_7999(
        config=capped_config,
        demand_model=model,
        shock_path=shock_path([[1.0, 1.0, 1.0]]),
        blob_base_fee_per_gas=None,
        inclusion_rule=ParentBALConsistentCaps(),
    )

    assert replay.loc[0, "execution_included_gas"] == 150
    assert replay.loc[0, "execution_inclusion_scale"] == pytest.approx(0.75)
    assert replay.loc[0, "included_execution_bal_gas"] == pytest.approx(75.0)
    assert replay.loc[0, "included_static_data_gas"] + replay.loc[
        0, "included_execution_bal_gas"
    ] + replay.loc[0, "included_state_bal_gas"] + replay.loc[
        0, "included_data_rounding_residual_gas"
    ] == pytest.approx(
        replay.loc[0, "data_included_gas"]
    )
    assert replay.loc[0, "included_data_rounding_residual_gas"] == pytest.approx(-15.0)
    assert replay.loc[0, "data_included_gas"] == 160
    assert replay.loc[0, "data_unserved_gas"] == 32


def test_parent_bal_consistent_rule_scales_parents_when_data_cap_binds():
    model = BundlePriced7999Demand(
        execution_quantity_anchor=100.0,
        state_quantity_anchor=25.0,
        static_data_gas_anchor=50.0,
        historical_price_wei=100.0,
        metering_multipliers={"execution": 2.0, "data": 10.0, "state": 4.0},
        elasticities={"execution": 0.2, "data": 0.3, "state": 0.4},
        bal_intensities={"execution": 1.0, "state": 2.0},
    )
    data_capped_config = make_full_7999_config(
        execution_gas_limit=500,
        bandwidth_gas_limit=160,
        state_gas_target=100,
        execution_target_ratio=2,
        bandwidth_target_ratio=2,
        initial_execution_base_fee=45,
        initial_bandwidth_base_fee=10,
        initial_state_base_fee=20,
        bandwidth_reserve_factor=0,
    )
    replay = run_driven_full_7999(
        config=data_capped_config,
        demand_model=model,
        shock_path=shock_path([[1.0, 1.0, 1.0]]),
        blob_base_fee_per_gas=None,
        inclusion_rule=ParentBALConsistentCaps(),
    )

    assert replay.loc[0, "data_included_gas"] == 160
    assert replay.loc[0, "data_bundle_inclusion_scale"] == pytest.approx(0.8)
    assert replay.loc[0, "execution_included_gas"] == 160
    assert replay.loc[0, "state_included_gas"] == 80


def _access_shock_model():
    return BundlePriced7999Demand(
        execution_quantity_anchor=100.0,
        state_quantity_anchor=25.0,
        static_data_gas_anchor=50.0,
        historical_price_wei=100.0,
        metering_multipliers={"execution": 2.0, "data": 10.0, "state": 4.0},
        elasticities={"execution": 0.2, "data": 0.3, "state": 0.4},
        bal_intensities={"execution": 1.0, "state": 2.0},
        rho_A=1.0,
    )


def _access_shock_config():
    return make_full_7999_config(
        execution_gas_limit=500,
        bandwidth_gas_limit=1024,
        state_gas_target=100,
        execution_target_ratio=2,
        bandwidth_target_ratio=2,
        initial_execution_base_fee=45,
        initial_bandwidth_base_fee=10,
        initial_state_base_fee=20,
        bandwidth_reserve_factor=0,
    )


def test_access_shock_scales_bal_without_moving_parent_activity():
    """The composition residual is BAL news, not a fourth demand shock."""
    shocks = shock_path([[1.0, 2.0, 1.0]])
    baseline = run_driven_full_7999(
        config=_access_shock_config(),
        demand_model=_access_shock_model(),
        shock_path=shocks,
        blob_base_fee_per_gas=None,
    )
    doubled = run_driven_full_7999(
        config=_access_shock_config(),
        demand_model=_access_shock_model(),
        shock_path=shocks,
        blob_base_fee_per_gas=None,
        access_shock_path=[2.0],
    )

    # Parent activity is untouched: the residual does not enter the parent price.
    for column in ("execution_offered_gas", "state_offered_gas"):
        assert doubled.loc[0, column] == baseline.loc[0, column]
    assert doubled.loc[0, "static_data_gas"] == pytest.approx(
        baseline.loc[0, "static_data_gas"]
    )
    # Both BAL components scale with it, and data gas rises by exactly the BAL.
    assert doubled.loc[0, "execution_bal_gas"] == pytest.approx(
        2.0 * baseline.loc[0, "execution_bal_gas"]
    )
    assert doubled.loc[0, "state_bal_gas"] == pytest.approx(
        2.0 * baseline.loc[0, "state_bal_gas"]
    )
    assert doubled.loc[0, "data_offered_gas"] - baseline.loc[0, "data_offered_gas"] == (
        pytest.approx(baseline.loc[0, "total_bal_gas"], abs=16)
    )
    assert doubled.loc[0, "access_shock"] == pytest.approx(2.0)


def test_unit_access_shock_path_matches_omitting_it():
    shocks = shock_path([[1.0, 2.0, 1.0], [1.1, 0.9, 1.2]])
    omitted = run_driven_full_7999(
        config=_access_shock_config(),
        demand_model=_access_shock_model(),
        shock_path=shocks,
        blob_base_fee_per_gas=None,
    )
    explicit = run_driven_full_7999(
        config=_access_shock_config(),
        demand_model=_access_shock_model(),
        shock_path=shocks,
        blob_base_fee_per_gas=None,
        access_shock_path=[1.0, 1.0],
    )
    pd.testing.assert_frame_equal(omitted, explicit)


@pytest.mark.parametrize(
    "bad_path",
    [[1.0], [1.0, 1.0, 1.0], [1.0, 0.0], [1.0, -1.0], [1.0, float("nan")]],
)
def test_access_shock_path_is_validated(bad_path):
    with pytest.raises(ValueError):
        run_driven_full_7999(
            config=_access_shock_config(),
            demand_model=_access_shock_model(),
            shock_path=shock_path([[1.0, 2.0, 1.0], [1.1, 0.9, 1.2]]),
            blob_base_fee_per_gas=None,
            access_shock_path=bad_path,
        )
