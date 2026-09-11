"""Run the independent EIP-8131/EIP-8279 shared-fee slot-time sweep."""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bandwidth_limits import EMPIRICAL_P90, safe_payload_bytes  # noqa: E402
from run_multiscale_design_surface import (  # noqa: E402
    BURN_IN,
    DAILY_BLOCK_LENGTH,
    EPS,
    MEASURE_BLOCKS,
    N_SEEDS,
    build_canonical_workload,
)
from shared_fee.equilibrium import (  # noqa: E402
    SharedFeeAnchor,
    solve_shared_fee_equilibrium,
)
from shared_fee.replay import SharedFeeConfig, run_shared_fee_batch  # noqa: E402
from shared_fee.optimization import (  # noqa: E402
    TRANSFER_GAS_PER_BYTE,
)


OUT = ROOT / "data/shared_fee"
PROPAGATION_TIMES = (3.0, 3.5, 4.0, 4.5, 5.0)
SLOT_BUDGET_S = 9.0
EXECUTION_SPEED_GAS_PER_S = 100e6
FLOOR_RATE_CANDIDATES = (64, 82, 96)
TARGET_LIMIT_RATIO = 0.5
LIMIT_STEP = 25e6
MINIMUM_LIMIT = 50e6


def selected_floor_rate(
    execution_capacity: float, payload_bytes: float
) -> tuple[int, float]:
    """Select the smallest tested rate meeting the balanced physical rate."""

    balance_rate = execution_capacity / payload_bytes
    eligible = [rate for rate in FLOOR_RATE_CANDIDATES if rate >= balance_rate]
    return (min(eligible) if eligible else max(FLOOR_RATE_CANDIDATES)), balance_rate


def safe_limits(propagation_time_s: float) -> dict[str, float | str]:
    payload_bytes = safe_payload_bytes(
        propagation_time_s * 1000.0, EMPIRICAL_P90, 1.0
    )
    execution_capacity = EXECUTION_SPEED_GAS_PER_S * (
        SLOT_BUDGET_S - propagation_time_s
    )
    transfer_capacity = TRANSFER_GAS_PER_BYTE * payload_bytes
    common = min(execution_capacity, transfer_capacity)
    floor_rate, _ = selected_floor_rate(common, payload_bytes)
    balance_rate = common / payload_bytes
    payload_capacity = floor_rate * payload_bytes
    return {
        "floor_rate": floor_rate,
        "balanced_floor_rate": float(balance_rate),
        "safe_payload_bytes": float(payload_bytes),
        "execution_capacity_gas": float(execution_capacity),
        "payload_capacity_gas": float(payload_capacity),
        "safe_common_limit": float(common),
        "physical_binding_constraint": (
            "execution"
            if execution_capacity <= transfer_capacity
            else "transfer payload"
        ),
    }


def limit_grid(safe_limit: float) -> list[float]:
    regular = np.arange(MINIMUM_LIMIT, safe_limit + 1e-9, LIMIT_STEP)
    values = set(float(value) for value in regular)
    values.add(float(safe_limit))
    return sorted(values)


def anchor_from_row(row: pd.Series, *, m_data: float) -> SharedFeeAnchor:
    return SharedFeeAnchor(
        q_execution=float(row.q_execution_per_block),
        q_data=float(row.q_data_per_block),
        q_state=float(row.q_state_per_block),
        m_execution=float(row.m_execution),
        m_data=float(m_data),
        m_state=float(row.m_state),
        reference_fee_gwei=float(row.base_fee_ref_gwei),
        eps_execution=EPS["execution"],
        eps_data=EPS["data"],
        eps_state=EPS["state"],
    )


def add_distribution(
    row: dict[str, float | str], name: str, values: np.ndarray
) -> None:
    values = np.asarray(values, dtype=float)
    row[name] = float(values.mean())
    row[f"{name}_p05"] = float(np.quantile(values, 0.05))
    row[f"{name}_p95"] = float(np.quantile(values, 0.95))


def collect(
    *,
    propagation_time: float,
    physical: dict[str, float | str],
    limits: list[float],
    config: SharedFeeConfig,
    result: dict[str, np.ndarray],
    equilibria: list,
) -> tuple[list[dict], list[dict]]:
    aggregate_rows: list[dict] = []
    path_rows: list[dict] = []
    for index, (limit, equilibrium) in enumerate(zip(limits, equilibria, strict=True)):
        selection = slice(index * N_SEEDS, (index + 1) * N_SEEDS)
        included_execution = result["mean_reference_execution"][selection]
        included_data = result["mean_reference_data"][selection]
        included_state = result["mean_reference_state"][selection]
        included_execution_metered = result["mean_included_execution"][selection]
        included_data_metered = result["mean_included_data"][selection]
        included_state_metered = result["mean_included_state"][selection]
        included_regular_metered = result["mean_included_regular"][selection]
        shared_used = result["mean_used"][selection, 1]
        fee = result["mean_fee_wei"][selection, 1]
        log_sd = result["log_return_sd"][selection, 1]
        limit_hits = result["included_limit_fraction"][selection, 1]
        near_limit = result["near_limit_fraction"][selection, 1]
        floor_bounded = result["floor_downward_pressure_fraction"][selection, 1]
        target_deviation = result["mean_absolute_target_deviation"][selection, 1]
        rationed = result["mean_rationed"][selection, 1]
        regular_binding = result["regular_binding_fraction"][selection]
        bal_gas_16 = result["mean_bal_payload"][selection]
        burn = result["mean_burn_wei"][selection, 1] / 1e18
        base_fee_exposure_proxy = (
            result["mean_base_fee_exposure_proxy_wei"][selection] / 1e18
        )

        equilibrium_log = np.log(max(equilibrium.base_fee_wei, 1.0))
        level_mean = result["effective_price_mean_log_level"][selection, 1]
        level_square = result["effective_price_mean_square_log_level"][selection, 1]
        # The data effective price is m_D*b. Subtracting log(m_D*b*) leaves
        # exactly log(b/b*), so this is the shared-fee equilibrium distance.
        equilibrium_effective_log = equilibrium_log + np.log(config.m_data)
        equilibrium_rmse = np.sqrt(
            np.maximum(
                level_square
                - 2 * equilibrium_effective_log * level_mean
                + equilibrium_effective_log**2,
                0.0,
            )
        )

        row: dict[str, float | str] = {
            "mechanism": "shared_fee_8131_8279",
            "workload": "full_multiscale_60d",
            "propagation_time_s": propagation_time,
            "execution_time_s": SLOT_BUDGET_S - propagation_time,
            **physical,
            "shared_limit": limit,
            "shared_target": limit * TARGET_LIMIT_RATIO,
            "target_limit_ratio": TARGET_LIMIT_RATIO,
            "n_replications": N_SEEDS,
            "burn_in_blocks": BURN_IN,
            "measured_blocks": MEASURE_BLOCKS,
            "daily_block_length": DAILY_BLOCK_LENGTH,
            "equilibrium_fee_wei": equilibrium.base_fee_wei,
            "equilibrium_floor_bounded": equilibrium.floor_bounded,
            "equilibrium_binding_branch": equilibrium.binding_branch,
            "equilibrium_regular_gas": equilibrium.regular_gas,
            "equilibrium_state_gas": equilibrium.state_gas,
            "equilibrium_execution_gas": equilibrium.execution_gas,
            "equilibrium_data_gas": equilibrium.data_gas,
            "m_execution": config.m_execution,
            "m_data": config.m_data,
            "m_state": config.m_state,
        }
        for name, values in (
            ("included_execution", included_execution),
            ("included_data", included_data),
            ("included_state", included_state),
            ("included_execution_metered", included_execution_metered),
            ("included_data_metered", included_data_metered),
            ("included_state_metered", included_state_metered),
            ("included_regular_metered", included_regular_metered),
            ("shared_gas_used", shared_used),
            ("shared_target_utilisation", shared_used / (limit / 2)),
            ("shared_fee_wei", fee),
            ("shared_fee_log_return_sd", log_sd),
            ("shared_limit_hit_fraction", limit_hits),
            ("shared_near_limit_fraction", near_limit),
            ("shared_fee_floor_bounded_fraction", floor_bounded),
            ("shared_target_deviation", target_deviation),
            ("shared_rationed_gas", rationed),
            ("regular_binding_fraction", regular_binding),
            ("runtime_bal_bytes", bal_gas_16 / 16.0),
            (
                "runtime_bal_floor_gas",
                bal_gas_16 * float(physical["floor_rate"]) / 16.0,
            ),
            ("base_fee_burn_eth_per_block", burn),
            ("base_fee_exposure_proxy_eth_per_block", base_fee_exposure_proxy),
            ("equilibrium_log_rmse", equilibrium_rmse),
        ):
            add_distribution(row, name, values)
        aggregate_rows.append(row)

        for replication in range(N_SEEDS):
            path_rows.append(
                {
                    "propagation_time_s": propagation_time,
                    "shared_limit": limit,
                    "shared_target": limit / 2,
                    "replication": replication,
                    "included_execution": included_execution[replication],
                    "included_data": included_data[replication],
                    "included_state": included_state[replication],
                    "included_regular_metered": included_regular_metered[replication],
                    "shared_gas_used": shared_used[replication],
                    "shared_fee_wei": fee[replication],
                    "shared_fee_log_return_sd": log_sd[replication],
                    "shared_limit_hit_fraction": limit_hits[replication],
                    "shared_near_limit_fraction": near_limit[replication],
                    "shared_fee_floor_bounded_fraction": floor_bounded[replication],
                    "shared_target_deviation": target_deviation[replication],
                    "shared_rationed_gas": rationed[replication],
                    "regular_binding_fraction": regular_binding[replication],
                    "runtime_bal_bytes": bal_gas_16[replication] / 16.0,
                    "runtime_bal_floor_gas": (
                    bal_gas_16[replication]
                    * float(physical["floor_rate"])
                    / 16.0
                    ),
                    "base_fee_burn_eth_per_block": burn[replication],
                    "base_fee_exposure_proxy_eth_per_block": (
                        base_fee_exposure_proxy[replication]
                    ),
                    "equilibrium_log_rmse": equilibrium_rmse[replication],
                }
            )
    return aggregate_rows, path_rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    anchors_by_rate = pd.read_csv(
        OUT / "equilibrium_anchor_by_floor_rate.csv"
    ).set_index("floor_rate")
    missing_rates = set(FLOOR_RATE_CANDIDATES) - set(anchors_by_rate.index)
    if missing_rates:
        raise AssertionError(f"missing calibrated floor rates: {sorted(missing_rates)}")
    demand = pd.read_csv(
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
    ).iloc[0]

    workload = build_canonical_workload().paths
    shock_hash = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
    if workload.shape != (N_SEEDS, BURN_IN + MEASURE_BLOCKS, 4):
        raise AssertionError(f"unexpected workload shape: {workload.shape}")

    aggregate_rows: list[dict] = []
    path_rows: list[dict] = []
    floor_rate_schedule: dict[float, int] = {}
    multiplier_schedule: dict[float, float] = {}
    started = time.time()
    for propagation_time in PROPAGATION_TIMES:
        physical = safe_limits(propagation_time)
        floor_rate = int(physical["floor_rate"])
        anchor_row = anchors_by_rate.loc[floor_rate]
        m_data = float(anchor_row.m_data)
        anchor = anchor_from_row(anchor_row, m_data=m_data)
        floor_rate_schedule[propagation_time] = floor_rate
        multiplier_schedule[propagation_time] = m_data
        limits = limit_grid(float(physical["safe_common_limit"]))
        equilibria = [
            solve_shared_fee_equilibrium(limit / 2, anchor) for limit in limits
        ]
        repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
        config = SharedFeeConfig(
            gas_target=repeat([limit / 2 for limit in limits]),
            gas_limit=repeat(limits),
            eps_execution=np.full(len(limits) * N_SEEDS, EPS["execution"]),
            eps_data=np.full(len(limits) * N_SEEDS, EPS["data"]),
            eps_state=np.full(len(limits) * N_SEEDS, EPS["state"]),
            m_execution=anchor.m_execution,
            m_data=anchor.m_data,
            m_state=anchor.m_state,
            q_execution_0=anchor.q_execution,
            q_data_0=anchor.q_data,
            q_state_0=anchor.q_state,
            p0_gwei=anchor.reference_fee_gwei,
            w_execution=float(demand.w_execution_reference),
            w_state=float(demand.w_state_reference),
        )
        initial = repeat([equilibrium.base_fee_wei for equilibrium in equilibria])
        result = run_shared_fee_batch(
            config, workload, initial, burn_in=BURN_IN
        )
        aggregate, paths = collect(
            propagation_time=propagation_time,
            physical=physical,
            limits=limits,
            config=config,
            result=result,
            equilibria=equilibria,
        )
        aggregate_rows.extend(aggregate)
        path_rows.extend(paths)
        print(
            f"{propagation_time:.1f}s: {len(limits)} limits, safe "
            f"{float(physical['safe_common_limit']) / 1e6:.1f}M "
            f"({physical['physical_binding_constraint']}) "
            f"[{time.time() - started:.1f}s]",
            flush=True,
        )

    scenarios = pd.DataFrame(aggregate_rows).sort_values(
        ["propagation_time_s", "shared_limit"]
    )
    paths = pd.DataFrame(path_rows).sort_values(
        ["propagation_time_s", "shared_limit", "replication"]
    )
    if scenarios.duplicated(["propagation_time_s", "shared_limit"]).any():
        raise AssertionError("duplicate shared-fee scenario rows")
    if len(paths) != len(scenarios) * N_SEEDS:
        raise AssertionError("path-level output does not reconcile to scenarios")
    expected_schedule = {3.0: 96, 3.5: 82, 4.0: 64, 4.5: 64, 5.0: 64}
    if floor_rate_schedule != expected_schedule:
        raise AssertionError(
            f"unexpected propagation-specific floor-rate schedule: {floor_rate_schedule}"
        )

    # The throughput surface is often flat near the maximum. Preserve every
    # design within 0.5% of the best mean rather than declaring a noisy argmax.
    maximum = scenarios.groupby("propagation_time_s")["included_execution"].transform(
        "max"
    )
    candidates = scenarios[scenarios["included_execution"] >= 0.995 * maximum].copy()
    candidates["throughput_gap_from_best"] = (
        maximum[candidates.index] - candidates["included_execution"]
    )

    scenarios.to_csv(OUT / "shared_fee_8279_slot_scenarios.csv", index=False)
    paths.to_csv(OUT / "shared_fee_8279_limit_sweep.csv", index=False)
    candidates.to_csv(OUT / "shared_fee_8279_candidates.csv", index=False)
    pd.DataFrame(
        [
            {
                "workload_sha256": shock_hash,
                "shape": "x".join(map(str, workload.shape)),
                "n_replications": N_SEEDS,
                "burn_in_blocks": BURN_IN,
                "measured_blocks": MEASURE_BLOCKS,
                "anchor": str((OUT / "equilibrium_anchor_by_floor_rate.csv").relative_to(ROOT)),
                "floor_rate_policy": "slot-specific candidate at or above balanced rate, with 64-gas minimum",
                "floor_rate_schedule": ";".join(
                    f"{time_s:.1f}s:{floor_rate_schedule[time_s]}"
                    for time_s in PROPAGATION_TIMES
                ),
                "m_data_schedule": ";".join(
                    f"{time_s:.1f}s:{multiplier_schedule[time_s]:.12f}"
                    for time_s in PROPAGATION_TIMES
                ),
                "anchor_q_execution": float(anchors_by_rate.iloc[0].q_execution_per_block),
                "anchor_q_data": float(anchors_by_rate.iloc[0].q_data_per_block),
                "anchor_q_state": float(anchors_by_rate.iloc[0].q_state_per_block),
                "anchor_m_execution": float(anchors_by_rate.iloc[0].m_execution),
                "anchor_m_state": float(anchors_by_rate.iloc[0].m_state),
                "anchor_reference_fee_gwei": float(anchors_by_rate.iloc[0].base_fee_ref_gwei),
                "anchor_eps_execution": EPS["execution"],
                "anchor_eps_data": EPS["data"],
                "anchor_eps_state": EPS["state"],
            }
        ]
    ).to_csv(OUT / "shared_fee_workload_manifest.csv", index=False)
    print(
        f"wrote {len(scenarios)} scenarios and {len(paths)} path rows; "
        f"workload sha256 {shock_hash[:16]}...",
        flush=True,
    )


if __name__ == "__main__":
    main()
