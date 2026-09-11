"""Compare the two main shared-fee benchmarks with EIP-7999 designs.

The comparison keeps execution activity, metered execution gas, transaction-
floor/data gas, and state bytes separate. Each shared-fee benchmark is shown
under unrestricted isoelastic state demand and under the 2x state-demand cap.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts/shared_fee"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_three_arm_comparison import central_7999_equilibrium_fees  # noqa: E402


OUT = ROOT / "data/shared_fee"
EIP7999_CPSB = 1_530.0
BLOCKS_PER_YEAR = 2_628_000
BYTES_PER_GIB = 1024**3

SHARED_SPECS = (
    (
        "proposal_faithful",
        "unrestricted",
        "Proposal-faithful shared fee",
    ),
    (
        "fully_optimized",
        "unrestricted",
        "Floor- and state-growth-adjusted shared fee",
    ),
    (
        "proposal_faithful",
        "2x",
        "Proposal-faithful shared fee, 2x state cap",
    ),
    (
        "fully_optimized",
        "2x",
        "Floor- and state-growth-adjusted shared fee, 2x state cap",
    ),
)


def main() -> None:
    shared = pd.read_csv(OUT / "shared_fee_state_tail.csv")
    eip7999 = pd.read_csv(ROOT / "data/7999/slot_time_scenarios.csv")
    balanced = pd.read_csv(
        ROOT / "data/7999/slot_time_historical_benchmark_frontier.csv"
    )
    demand = pd.read_csv(
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
    ).iloc[0]
    metering = pd.read_csv(
        ROOT / "data/7999/data_metering_runtime_bal_anchor.csv"
    ).iloc[0]
    elasticity_rows = pd.read_csv(ROOT / "data/glamsterdam/elasticity_vectors.csv")
    elasticity = elasticity_rows.loc[elasticity_rows.window_days.eq(35)]
    if len(elasticity) != 1:
        raise AssertionError("expected one 35-day elasticity vector")
    elasticity = elasticity.iloc[0]

    for frame, label in ((shared, "shared fee"), (eip7999, "EIP-7999")):
        if set(frame["n_replications"]) != {32}:
            raise AssertionError(f"{label} does not use the canonical 32 paths")

    rows: list[dict] = []
    for propagation_time in sorted(shared["propagation_time_s"].unique()):
        eip_split = eip7999[
            np.isclose(eip7999["propagation_time_s"], propagation_time)
        ]
        eip_max = eip_split.loc[eip_split["included_execution"].idxmax()]
        balanced_rows = balanced[
            np.isclose(balanced["propagation_time_s"], propagation_time)
        ]
        if len(balanced_rows) != 1:
            raise AssertionError("historically anchored EIP-7999 row is not unique")
        eip_balanced = balanced_rows.iloc[0]

        def eip_row(source: pd.Series, design: str) -> dict:
            fees = central_7999_equilibrium_fees(
                float(source.execution_target),
                float(source.data_target),
                demand,
                metering,
                elasticity,
            )
            state_bytes = float(source.state_used) / EIP7999_CPSB
            estimated_payload_bytes = (
                float(source.static_data_included)
                + float(source.bal_data_included)
            ) / 16.0
            return {
                "propagation_time_s": propagation_time,
                "design_family": design,
                "mechanism": "EIP-7999",
                "configuration": (
                    f"E{source.execution_target / 1e6:g}/"
                    f"D{source.data_target / 1e6:g}"
                ),
                "state_demand_cap_label": "unrestricted",
                "shared_limit": np.nan,
                "floor_rate": np.nan,
                "cpsb": EIP7999_CPSB,
                "actual_parent_execution": (
                    float(source.execution_used) / float(demand.m_execution)
                ),
                "metered_execution_gas": float(source.execution_used),
                "floor_or_data_gas": float(source.data_used),
                "state_gas": float(source.state_used),
                "state_bytes": state_bytes,
                "annualized_state_growth_gib": (
                    state_bytes * BLOCKS_PER_YEAR / BYTES_PER_GIB
                ),
                "estimated_payload_bytes": estimated_payload_bytes,
                "hard_limit_fraction": float(source.any_limit_hit_fraction),
                "execution_rationed_gas": float(source.execution_rationed),
                "data_or_regular_rationed_gas": float(source.data_rationed),
                "execution_price_variation": float(source.execution_price_sd),
                "data_or_regular_price_variation": float(source.data_price_sd),
                "state_price_variation": float(source.state_price_sd),
                "regular_binding_fraction": np.nan,
                "equilibrium_binding_branch": "separate targets",
                "base_fee_exposure_proxy_eth_per_block": float(
                    source.total_base_fee_burn_eth_per_block
                ),
                "equilibrium_execution_fee_wei": fees[0],
                "equilibrium_data_or_regular_fee_wei": fees[1],
                "equilibrium_state_fee_wei": fees[2],
                "source_file": "data/7999/slot_time_scenarios.csv",
            }

        rows.append(eip_row(eip_max, "EIP-7999 maximum throughput"))
        rows.append(
            eip_row(
                eip_balanced,
                "EIP-7999 balanced (historically anchored)",
            )
        )

        shared_split = shared[
            np.isclose(shared["propagation_time_s"], propagation_time)
        ].set_index(["benchmark", "state_demand_cap_label"])
        for benchmark, cap_label, design_label in SHARED_SPECS:
            source = shared_split.loc[(benchmark, cap_label)]
            rows.append(
                {
                    "propagation_time_s": propagation_time,
                    "design_family": design_label,
                    "mechanism": "one-dimensional shared fee",
                    "configuration": f"G{source.shared_limit / 1e6:.1f}",
                    "state_demand_cap_label": cap_label,
                    "shared_limit": float(source.shared_limit),
                    "floor_rate": int(source.floor_rate),
                    "cpsb": float(source.cpsb),
                    "actual_parent_execution": float(source.included_execution),
                    "metered_execution_gas": float(
                        source.included_execution_metered
                    ),
                    "floor_or_data_gas": float(source.included_data_metered),
                    "state_gas": float(source.included_state_metered),
                    "state_bytes": float(source.included_state_bytes),
                    "annualized_state_growth_gib": float(
                        source.annualized_state_growth_gib
                    ),
                    "estimated_payload_bytes": float(
                        source.estimated_counted_payload_bytes
                    ),
                    "hard_limit_fraction": float(
                        source.shared_limit_hit_fraction
                    ),
                    "execution_rationed_gas": np.nan,
                    "data_or_regular_rationed_gas": float(
                        source.shared_rationed_gas
                    ),
                    "execution_price_variation": float(
                        source.shared_fee_log_return_sd
                    ),
                    "data_or_regular_price_variation": float(
                        source.shared_fee_log_return_sd
                    ),
                    "state_price_variation": float(
                        source.shared_fee_log_return_sd
                    ),
                    "regular_binding_fraction": float(
                        source.regular_binding_fraction
                    ),
                    "equilibrium_binding_branch": str(
                        source.equilibrium_binding_branch
                    ),
                    "base_fee_exposure_proxy_eth_per_block": float(
                        source.base_fee_exposure_proxy_eth_per_block
                    ),
                    "equilibrium_execution_fee_wei": float(
                        source.equilibrium_fee_wei
                    ),
                    "equilibrium_data_or_regular_fee_wei": float(
                        source.equilibrium_fee_wei
                    ),
                    "equilibrium_state_fee_wei": float(
                        source.equilibrium_fee_wei
                    ),
                    "source_file": (
                        "data/shared_fee/shared_fee_state_tail.csv"
                    ),
                }
            )

    order = {
        "EIP-7999 maximum throughput": 0,
        "EIP-7999 balanced (historically anchored)": 1,
        **{
            design_label: index + 2
            for index, (_, _, design_label) in enumerate(SHARED_SPECS)
        },
    }
    output = pd.DataFrame(rows)
    output["design_order"] = output.design_family.map(order)
    if output["design_order"].isna().any():
        raise AssertionError("comparison design order is incomplete")
    output = output.sort_values(
        ["propagation_time_s", "design_order"]
    ).drop(columns="design_order")
    output.to_csv(OUT / "shared_fee_optimized_comparison.csv", index=False)
    print(output.to_string(index=False))


if __name__ == "__main__":
    main()
