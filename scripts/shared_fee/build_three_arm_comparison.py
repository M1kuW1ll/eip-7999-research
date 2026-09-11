"""Compare EIP-7999 throughput/balanced designs with the shared-fee arm."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/shared_fee"
STATE_TARGET = 75_000_000.0
MINIMUM_BASE_FEE_WEI = 1.0


def central_7999_equilibrium_fees(
    execution_target: float,
    data_target: float,
    demand: pd.Series,
    metering: pd.Series,
    elasticity: pd.Series,
) -> tuple[float, float, float]:
    """Reserve-free bundle-priced equilibrium fees for the central model.

    The state and data fees are interior for every selected comparison row.
    Execution either clears its target above one wei or is pinned at the
    protocol minimum, in which case the data fee is solved jointly with the
    resulting execution quantity.
    """

    p0_wei = float(demand.base_fee_ref_gwei) * 1e9
    m_execution = float(demand.m_execution)
    m_state = float(demand.m_state)
    m_data = float(metering.static_data_metering_multiplier)
    q_execution_0 = float(demand.q_execution_per_block)
    q_state_0 = float(demand.q_state_per_block)
    g_static_0 = float(metering.static_data_gas_per_block)
    w_execution = float(demand.w_execution_reference)
    w_state = float(demand.w_state_reference)
    eps_execution = float(elasticity.eps_execution)
    eps_data = float(elasticity.eps_data)
    eps_state = float(elasticity.eps_state)

    q_execution_target = execution_target / m_execution
    q_state_target = STATE_TARGET / m_state
    execution_ratio = q_execution_target / q_execution_0
    state_ratio = q_state_target / q_state_0
    static_target = (
        data_target
        - w_execution * q_execution_target
        - w_state * q_state_target
    )
    if static_target <= 0:
        raise ValueError("data target leaves no room for static data")

    data_fee = (p0_wei / m_data) * (static_target / g_static_0) ** (
        -1.0 / eps_data
    )
    execution_price = p0_wei * execution_ratio ** (-1.0 / eps_execution)
    state_price = p0_wei * state_ratio ** (-1.0 / eps_state)
    execution_fee = (
        execution_price - w_execution * data_fee
    ) / m_execution
    state_fee = (state_price - w_state * data_fee) / m_state

    if execution_fee < MINIMUM_BASE_FEE_WEI:
        def data_residual(log_data_fee: float) -> float:
            candidate_data_fee = float(np.exp(log_data_fee))
            q_execution = q_execution_0 * (
                (
                    m_execution * MINIMUM_BASE_FEE_WEI
                    + w_execution * candidate_data_fee
                )
                / p0_wei
            ) ** (-eps_execution)
            static_data = g_static_0 * (
                m_data * candidate_data_fee / p0_wei
            ) ** (-eps_data)
            return (
                static_data
                + w_execution * q_execution
                + w_state * q_state_target
                - data_target
            )

        data_fee = float(
            np.exp(
                brentq(
                    data_residual,
                    np.log(MINIMUM_BASE_FEE_WEI),
                    np.log(p0_wei) + 50.0,
                )
            )
        )
        execution_fee = MINIMUM_BASE_FEE_WEI
        state_fee = (state_price - w_state * data_fee) / m_state

    fees = (float(execution_fee), float(data_fee), float(state_fee))
    if any(fee < MINIMUM_BASE_FEE_WEI for fee in fees):
        raise AssertionError("selected comparison requires an unsupported fee-floor regime")
    return fees


def main() -> None:
    shared = pd.read_csv(OUT / "shared_fee_8279_slot_scenarios.csv")
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
    elasticity_rows = pd.read_csv(
        ROOT / "data/glamsterdam/elasticity_vectors.csv"
    )
    elasticity = elasticity_rows.loc[elasticity_rows.window_days.eq(35)]
    if len(elasticity) != 1:
        raise AssertionError("expected one 35-day elasticity vector")
    elasticity = elasticity.iloc[0]

    if set(shared["n_replications"]) != {32} or set(eip7999["n_replications"]) != {32}:
        raise AssertionError("shared fee and EIP-7999 must use the same 32 paths")
    if set(shared["burn_in_blocks"]) != set(eip7999["burn_in_blocks"]):
        raise AssertionError("burn-in differs between shared fee and EIP-7999")
    if set(shared["measured_blocks"]) != set(eip7999["measured_blocks"]):
        raise AssertionError("measured path length differs between mechanisms")

    rows: list[dict] = []
    capacity_rows: list[dict] = []
    for propagation_time in sorted(shared["propagation_time_s"].unique()):
        shared_split = shared[np.isclose(shared["propagation_time_s"], propagation_time)]
        safe_rows = shared_split[
            np.isclose(shared_split.shared_limit, shared_split.safe_common_limit)
        ]
        if len(safe_rows) != 1:
            raise AssertionError("shared-fee safe-limit row is not unique")
        shared_best = safe_rows.iloc[0]
        safe_common = float(shared_best.safe_common_limit)

        full = eip7999[np.isclose(eip7999["propagation_time_s"], propagation_time)]
        eip_best = full.loc[full["included_execution"].idxmax()]
        balanced_rows = balanced[
            np.isclose(balanced["propagation_time_s"], propagation_time)
        ]
        if len(balanced_rows) != 1:
            raise AssertionError("balanced EIP-7999 row is not unique")
        eip_balanced = balanced_rows.iloc[0]

        def eip_row(source: pd.Series, label: str) -> dict:
            equilibrium_fees = central_7999_equilibrium_fees(
                float(source.execution_target),
                float(source.data_target),
                demand,
                metering,
                elasticity,
            )
            return {
                "propagation_time_s": propagation_time,
                "mechanism": label,
                "configuration": (
                    f"E{source.execution_target / 1e6:g}/"
                    f"D{source.data_target / 1e6:g}"
                ),
                "execution_limit": float(source.execution_limit),
                "data_limit": float(source.data_limit),
                "shared_limit": np.nan,
                "included_execution": float(source.execution_used),
                "included_data": float(source.data_used),
                "included_state_gas": float(source.state_used),
                "limit_hit_fraction": float(source.any_limit_hit_fraction),
                "execution_price_variation": float(source.execution_price_sd),
                "data_price_variation": float(source.data_price_sd),
                "state_price_variation": float(source.state_price_sd),
                "base_fee_exposure_proxy_eth_per_block": float(
                    source.total_base_fee_burn_eth_per_block
                ),
                "equilibrium_execution_base_fee_wei": equilibrium_fees[0],
                "equilibrium_data_base_fee_wei": equilibrium_fees[1],
                "equilibrium_state_base_fee_wei": equilibrium_fees[2],
                "source_file": "data/7999/slot_time_scenarios.csv",
            }

        rows.extend(
            [
                eip_row(eip_best, "EIP-7999: maximum throughput"),
                eip_row(eip_balanced, "EIP-7999: balanced"),
                {
                    "propagation_time_s": propagation_time,
                    "mechanism": "One-dimensional shared fee",
                    "configuration": f"G{shared_best.shared_limit / 1e6:.1f}",
                    "execution_limit": np.nan,
                    "data_limit": np.nan,
                    "shared_limit": float(shared_best.shared_limit),
                    # Regular gas includes repriced execution and the
                    # transaction-floor uplift; there is no separate data
                    # dimension in this mechanism.
                    "included_execution": float(shared_best.included_regular_metered),
                    "included_data": np.nan,
                    "included_state_gas": float(shared_best.included_state_metered),
                    "limit_hit_fraction": float(shared_best.shared_limit_hit_fraction),
                    "execution_price_variation": float(
                        shared_best.shared_fee_log_return_sd
                    ),
                    "data_price_variation": np.nan,
                    "state_price_variation": float(
                        shared_best.shared_fee_log_return_sd
                    ),
                    "base_fee_exposure_proxy_eth_per_block": float(
                        shared_best.base_fee_exposure_proxy_eth_per_block
                    ),
                    # The one-dimensional mechanism applies one common base
                    # fee to every metered resource. Repeat it in all three
                    # columns so the comparison table has a consistent shape.
                    "equilibrium_execution_base_fee_wei": float(
                        shared_best.equilibrium_fee_wei
                    ),
                    "equilibrium_data_base_fee_wei": float(
                        shared_best.equilibrium_fee_wei
                    ),
                    "equilibrium_state_base_fee_wei": float(
                        shared_best.equilibrium_fee_wei
                    ),
                    "source_file": "data/shared_fee/shared_fee_8279_slot_scenarios.csv",
                },
            ]
        )
        capacity_rows.append(
            {
                "propagation_time_s": propagation_time,
                "execution_time_s": float(shared_best.execution_time_s),
                "safe_payload_bytes": float(shared_best.safe_payload_bytes),
                "execution_capacity_gas": float(shared_best.execution_capacity_gas),
                "floor_rate": int(shared_best.floor_rate),
                "payload_capacity_at_floor_rate": float(
                    shared_best.payload_capacity_gas
                ),
                "safe_shared_limit": safe_common,
                "shared_physical_binding_constraint": str(
                    shared_best.physical_binding_constraint
                ),
                "eip7999_max_included_execution": float(eip_best.included_execution),
                "eip7999_balanced_included_execution": float(
                    eip_balanced.included_execution
                ),
                "shared_fee_included_regular_gas": float(
                    shared_best.included_regular_metered
                ),
                "eip7999_included_state_gas": float(eip_best.state_used),
                "eip7999_balanced_included_state_gas": float(
                    eip_balanced.state_used
                ),
                "shared_fee_included_state_gas": float(
                    shared_best.included_state_metered
                ),
            }
        )

    mechanism_order = {
        "EIP-7999: maximum throughput": 0,
        "EIP-7999: balanced": 1,
        "One-dimensional shared fee": 2,
    }
    comparison = pd.DataFrame(rows)
    comparison["mechanism_order"] = comparison.mechanism.map(mechanism_order)
    comparison = comparison.sort_values(
        ["propagation_time_s", "mechanism_order"]
    ).drop(columns="mechanism_order")
    capacity = pd.DataFrame(capacity_rows).sort_values("propagation_time_s")
    comparison.to_csv(OUT / "shared_vs_7999_by_slot_split.csv", index=False)
    capacity.to_csv(OUT / "shared_vs_7999_physical_capacity.csv", index=False)
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
