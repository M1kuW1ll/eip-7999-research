"""Reduce the slot-time design surface with illustrative dynamic guardrails.

The thresholds in this file are protocol preferences supplied for interpretation;
they are not estimated from the simulation.  For each tier and slot split, the
script selects the admissible target pair with the greatest mean delivered
execution.  It also applies a 99%-of-maximum rule across slot splits and records
the marginal changes for the fixed E300/D80 diagnostic.

The script separately defines a balanced-design benchmark.  It allows the
fraction of blocks at or above 98% of either hard limit and the mean absolute
execution distance from target to be at most 120% of their historical values.
It also requires the central reserve-free execution equilibrium to clear
strictly above the one-wei protocol minimum.

For the throughput comparison, the configuration with the highest mean
delivered execution at each propagation time is retained.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/7999/slot_time_scenarios.csv"
HISTORICAL_SOURCE = ROOT / "data/7999/historical_fee_market_benchmark.csv"
HISTORICAL_TOLERANCE_MULTIPLIER = 1.20
MINIMUM_EXECUTION_BASE_FEE_WEI = 1.0
INTERIOR_FEE_TOLERANCE_WEI = 1e-6
STATE_TARGET = 75_000_000.0

TIERS = {
    "conservative": {
        "execution_fill_min": 0.98,
        "data_limit_hit_max": 0.01,
        "execution_limit_hit_max": 0.01,
        "execution_floor_bounded_max": 0.20,
        "data_rationed_share_max": 0.005,
    },
    "balanced": {
        "execution_fill_min": 0.98,
        "data_limit_hit_max": 0.05,
        "execution_limit_hit_max": 0.05,
        "execution_floor_bounded_max": 0.25,
        "data_rationed_share_max": 0.01,
    },
    "throughput-oriented": {
        "execution_fill_min": 0.95,
        "data_limit_hit_max": 0.15,
        "execution_limit_hit_max": 0.10,
        "execution_floor_bounded_max": 0.50,
        "data_rationed_share_max": 0.05,
    },
}


def add_derived_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    offered_data = result["data_used"] + result["data_rationed"]
    result["data_rationed_share"] = np.divide(
        result["data_rationed"],
        offered_data,
        out=np.zeros(len(result), dtype=float),
        where=offered_data > 0,
    )
    result["combined_limit_hit_fraction"] = (
        result["data_limit_hit_fraction"]
        + result["execution_limit_hit_fraction"]
    )
    return result


def add_central_equilibrium_fees(frame: pd.DataFrame) -> pd.DataFrame:
    """Invert the central bundle-priced demand curves at each target pair.

    The all-target-clearing quantities are known, so the isoelastic demand
    curves give the target-clearing fees directly.  A value at or below one
    wei means the configured execution target has no interior protocol
    equilibrium under the central, reserve-free specification.
    """

    result = frame.copy()
    demand = pd.read_csv(
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
    ).iloc[0]
    metering = pd.read_csv(
        ROOT / "data/7999/data_metering_runtime_bal_anchor.csv"
    ).iloc[0]
    elasticities = pd.read_csv(
        ROOT / "data/glamsterdam/elasticity_vectors.csv"
    )
    elasticity = elasticities.loc[elasticities["window_days"].eq(35)]
    if len(elasticity) != 1:
        raise AssertionError("expected one central 35-day elasticity vector")
    elasticity = elasticity.iloc[0]

    q_execution = result["execution_target"] / float(demand["m_execution"])
    q_state = STATE_TARGET / float(demand["m_state"])
    execution_ratio = q_execution / float(demand["q_execution_per_block"])
    bal_execution = (
        float(demand["w_execution_reference"])
        * float(demand["q_execution_per_block"])
        * execution_ratio
    )
    bal_state = float(demand["w_state_reference"]) * q_state
    static_data_target = result["data_target"] - bal_execution - bal_state
    if (static_data_target <= 0).any():
        raise AssertionError("every tested data target must leave room for static data")

    data_fee_gwei = (
        float(demand["base_fee_ref_gwei"])
        / float(metering["static_data_metering_multiplier"])
    ) * (
        static_data_target / float(metering["static_data_gas_per_block"])
    ) ** (-1.0 / float(elasticity["eps_data"]))
    effective_execution_price_gwei = float(demand["base_fee_ref_gwei"]) * (
        execution_ratio ** (-1.0 / float(elasticity["eps_execution"]))
    )
    unconstrained_execution_fee_wei = 1e9 * (
        effective_execution_price_gwei
        - float(demand["w_execution_reference"]) * data_fee_gwei
    ) / float(demand["m_execution"])

    result["unconstrained_equilibrium_execution_base_fee_wei"] = (
        unconstrained_execution_fee_wei
    )
    result["equilibrium_execution_base_fee_wei"] = np.maximum(
        MINIMUM_EXECUTION_BASE_FEE_WEI, unconstrained_execution_fee_wei
    )
    result["execution_equilibrium_is_interior"] = (
        unconstrained_execution_fee_wei
        > MINIMUM_EXECUTION_BASE_FEE_WEI + INTERIOR_FEE_TOLERANCE_WEI
    )
    return result


def admissible(frame: pd.DataFrame, spec: dict[str, float]) -> pd.DataFrame:
    return frame[
        (frame["execution_fill"] >= spec["execution_fill_min"])
        & (frame["data_limit_hit_fraction"] <= spec["data_limit_hit_max"])
        & (
            frame["execution_limit_hit_fraction"]
            <= spec["execution_limit_hit_max"]
        )
        & (
            frame["execution_floor_bounded_fraction"]
            <= spec["execution_floor_bounded_max"]
        )
        & (frame["data_rationed_share"] <= spec["data_rationed_share_max"])
    ]


def main() -> None:
    data = add_central_equilibrium_fees(
        add_derived_metrics(pd.read_csv(SOURCE))
    )
    historical = pd.read_csv(HISTORICAL_SOURCE).iloc[0]

    frontier_rows: list[pd.Series] = []
    selection_rows: list[pd.Series] = []
    for tier, spec in TIERS.items():
        all_admissible = admissible(data, spec)
        if all_admissible.empty:
            raise AssertionError(f"no admissible configurations for {tier}")

        for propagation_time, split in data.groupby("propagation_time_s"):
            split_admissible = admissible(split, spec)
            if split_admissible.empty:
                continue
            winner = split_admissible.loc[
                split_admissible["included_execution"].idxmax()
            ].copy()
            winner["tier"] = tier
            winner["admissible_count_at_split"] = len(split_admissible)
            for key, value in spec.items():
                winner[key] = value
            frontier_rows.append(winner)

        maximum = float(all_admissible["included_execution"].max())
        maximum_row = all_admissible.loc[
            all_admissible["included_execution"].idxmax()
        ].copy()
        maximum_row["tier"] = tier
        maximum_row["selection"] = "maximum_guardrail_feasible_throughput"
        maximum_row["tier_maximum_included_execution"] = maximum
        selection_rows.append(maximum_row)

        near_maximum = all_admissible[
            all_admissible["included_execution"] >= 0.99 * maximum
        ].sort_values(
            [
                "propagation_time_s",
                "combined_limit_hit_fraction",
                "included_execution",
            ],
            ascending=[True, True, False],
        )
        near_row = near_maximum.iloc[0].copy()
        near_row["tier"] = tier
        near_row["selection"] = "shortest_split_within_99pct_of_tier_maximum"
        near_row["tier_maximum_included_execution"] = maximum
        selection_rows.append(near_row)

    frontier = pd.DataFrame(frontier_rows).sort_values(
        ["tier", "propagation_time_s"]
    )
    selections = pd.DataFrame(selection_rows).sort_values(["tier", "selection"])

    fixed = data[
        np.isclose(data["execution_target"], 300e6)
        & np.isclose(data["data_target"], 80e6)
    ].sort_values("propagation_time_s")
    marginal_columns = {
        "included_execution": "delivered_execution_change",
        "data_limit_hit_fraction": "data_limit_hit_change",
        "execution_limit_hit_fraction": "execution_limit_hit_change",
        "execution_floor_bounded_fraction": "execution_floor_bounded_change",
    }
    marginal = fixed[["propagation_time_s", *marginal_columns]].copy()
    marginal.insert(1, "previous_propagation_time_s", marginal["propagation_time_s"].shift())
    for source, destination in marginal_columns.items():
        marginal[destination] = marginal[source].diff()
    marginal = marginal.iloc[1:][
        [
            "previous_propagation_time_s",
            "propagation_time_s",
            *marginal_columns.values(),
        ]
    ]

    near_limit_ceiling = (
        HISTORICAL_TOLERANCE_MULTIPLIER * historical["near_limit_fraction"]
    )
    target_deviation_ceiling = (
        HISTORICAL_TOLERANCE_MULTIPLIER
        * historical["mean_absolute_target_deviation"]
    )
    historical_admissible = data[
        (data["propagation_time_s"] >= 3.0)
        & (data["any_near_limit_fraction"] <= near_limit_ceiling)
        & (
            data["execution_mean_absolute_target_deviation"]
            <= target_deviation_ceiling
        )
        & data["execution_equilibrium_is_interior"]
    ].copy()
    historical_admissible["historical_tolerance_multiplier"] = (
        HISTORICAL_TOLERANCE_MULTIPLIER
    )
    historical_admissible["historical_near_limit_ceiling"] = near_limit_ceiling
    historical_admissible[
        "historical_execution_target_deviation_ceiling"
    ] = target_deviation_ceiling
    historical_frontier = pd.DataFrame(
        [
            split.loc[split["included_execution"].idxmax()]
            for _, split in historical_admissible.groupby("propagation_time_s")
        ]
    ).sort_values("propagation_time_s")
    maximum_throughput = pd.DataFrame(
        [
            split.loc[split["included_execution"].idxmax()]
            for _, split in data.loc[data["propagation_time_s"].ge(3.0)].groupby(
                "propagation_time_s"
            )
        ]
    ).sort_values("propagation_time_s")

    frontier_path = ROOT / "data/7999/slot_time_guardrail_frontier.csv"
    selection_path = ROOT / "data/7999/slot_time_guardrail_candidates.csv"
    marginal_path = ROOT / "data/7999/slot_time_e300_d80_marginal_tradeoffs.csv"
    historical_admissible_path = (
        ROOT / "data/7999/slot_time_historical_benchmark_admissible.csv"
    )
    historical_frontier_path = (
        ROOT / "data/7999/slot_time_historical_benchmark_frontier.csv"
    )
    maximum_throughput_path = (
        ROOT / "data/7999/slot_time_maximum_throughput.csv"
    )
    missing_guardrail_path = (
        ROOT / "data/7999/slot_time_guardrail_missing_splits.csv"
    )
    frontier.to_csv(frontier_path, index=False)
    selections.to_csv(selection_path, index=False)
    marginal.to_csv(marginal_path, index=False)
    historical_admissible.to_csv(historical_admissible_path, index=False)
    historical_frontier.to_csv(historical_frontier_path, index=False)
    maximum_throughput.to_csv(maximum_throughput_path, index=False)

    expected_pairs = pd.MultiIndex.from_product(
        [TIERS, sorted(data["propagation_time_s"].unique())],
        names=["tier", "propagation_time_s"],
    )
    observed_pairs = pd.MultiIndex.from_frame(
        frontier[["tier", "propagation_time_s"]]
    )
    missing_guardrails = expected_pairs.difference(observed_pairs).to_frame(index=False)
    missing_guardrails.to_csv(missing_guardrail_path, index=False)
    if len(selections) != 2 * len(TIERS):
        raise AssertionError("each tier should have a maximum and near-maximum row")
    if len(marginal) != 4:
        raise AssertionError("E300/D80 should have four adjacent split changes")
    if len(historical_frontier) != 5:
        raise AssertionError("historical benchmark should select one row per carried split")
    if not historical_frontier["execution_equilibrium_is_interior"].all():
        raise AssertionError("balanced designs must have an interior execution fee")

    print(f"{len(frontier)} rows -> {frontier_path.relative_to(ROOT)}")
    print(f"{len(selections)} rows -> {selection_path.relative_to(ROOT)}")
    print(f"{len(marginal)} rows -> {marginal_path.relative_to(ROOT)}")
    print(
        f"{len(historical_admissible)} rows -> "
        f"{historical_admissible_path.relative_to(ROOT)}"
    )
    print(
        f"{len(historical_frontier)} rows -> "
        f"{historical_frontier_path.relative_to(ROOT)}"
    )
    print(
        f"{len(maximum_throughput)} rows -> "
        f"{maximum_throughput_path.relative_to(ROOT)}"
    )
    print(
        f"{len(missing_guardrails)} missing tier/split pairs -> "
        f"{missing_guardrail_path.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
