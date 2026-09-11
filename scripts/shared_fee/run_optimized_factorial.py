"""Run the 2x2 shared-fee floor-rate and state-repricing experiment.

The four benchmark families keep the execution repricing fixed while varying:

1. the proposal floor of 64 gas per counted byte versus the minimum sufficient
   floor for each propagation-time/common-limit pair; and
2. the proposal CPSB of 1,530 versus a CPSB that preserves the same annual
   state-growth budget as the shared target changes.

Existing EIP-7999, Glamsterdam, and earlier shared-fee outputs are read-only.
"""

from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

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
from shared_fee.optimization import (  # noqa: E402
    BLOCKS_PER_YEAR,
    BYTES_PER_GIB,
    CPSB_REFERENCE,
    CALIBRATED_FLOOR_RATES,
    EXECUTION_SPEED_GAS_PER_S,
    PROPOSAL_FLOOR_RATE,
    REFERENCE_SHARED_LIMIT,
    SLOT_BUDGET_S,
    TRANSFER_GAS_PER_BYTE,
    cpsb_for_limit,
    minimum_sufficient_floor_rate,
    physical_capacities,
)
from shared_fee.replay import SharedFeeConfig, run_shared_fee_batch  # noqa: E402


OUT = ROOT / "data/shared_fee"
PROPAGATION_TIMES = (3.0, 3.5, 4.0, 4.5, 5.0)
TARGET_LIMIT_RATIO = 0.5
LIMIT_STEP = 25e6
MINIMUM_LIMIT = 50e6


@dataclass(frozen=True)
class Benchmark:
    benchmark: str
    label: str
    optimize_floor: bool
    match_state_growth: bool


BENCHMARKS = (
    Benchmark(
        "proposal_faithful",
        "Proposal-faithful: F=64, CPSB=1530",
        False,
        False,
    ),
    Benchmark(
        "state_matched_64",
        "State-matched 64: F=64, matched CPSB",
        False,
        True,
    ),
    Benchmark(
        "floor_optimized_only",
        "Floor-optimized only: derived F, CPSB=1530",
        True,
        False,
    ),
    Benchmark(
        "fully_optimized",
        "Floor- and state-growth-adjusted: derived F, matched CPSB",
        True,
        True,
    ),
)


def candidate_limits(physical: dict[str, float | str]) -> list[float]:
    maximum = float(physical["maximum_candidate_limit"])
    payload = float(physical["safe_payload_bytes"])
    regular = np.arange(MINIMUM_LIMIT, maximum + 1e-9, LIMIT_STEP)
    values = {float(value) for value in regular}
    values.add(maximum)
    # Include the largest limit certified by the fixed 64-gas floor so the
    # proposal-faithful and optimized frontiers are both observed exactly.
    values.add(min(maximum, PROPOSAL_FLOOR_RATE * payload))
    return sorted(value for value in values if value >= MINIMUM_LIMIT)


def static_bytes_per_reference_data_gas() -> float:
    components = pd.read_csv(OUT.parent / "7999/daily_data_resource_components.csv")
    current = pd.read_csv(
        OUT.parent / "7999/xatu_daily_data_metering_2026-02-01_2026-06-01.csv"
    )
    merged = components.merge(
        current[["date", "data_gas_current"]],
        on="date",
        validate="one_to_one",
    )
    static_bytes = merged[
        [
            "calldata_bytes",
            "blob_versioned_hash_bytes",
            "access_list_bytes",
            "authorization_bytes",
        ]
    ].sum(axis=1)
    return float(static_bytes.sum() / merged["data_gas_current"].sum())


def add_distribution(row: dict, name: str, values: np.ndarray) -> None:
    values = np.asarray(values, dtype=float)
    row[name] = float(values.mean())
    row[f"{name}_p05"] = float(np.quantile(values, 0.05))
    row[f"{name}_p95"] = float(np.quantile(values, 0.95))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    anchors = pd.read_csv(OUT / "equilibrium_anchor_by_floor_rate.csv")
    anchors["floor_rate"] = anchors["floor_rate"].astype(int)
    anchors = anchors.set_index("floor_rate")
    required_rates = set(CALIBRATED_FLOOR_RATES)
    missing = required_rates - set(anchors.index)
    if missing:
        raise AssertionError(
            "run the 40, 50, and 64--96 floor calibration first; missing rates: "
            f"{sorted(missing)}"
        )
    base = anchors.loc[PROPOSAL_FLOOR_RATE]
    demand = pd.read_csv(
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
    ).iloc[0]
    bytes_per_data_gas = static_bytes_per_reference_data_gas()

    workload = build_canonical_workload().paths
    if workload.shape != (N_SEEDS, BURN_IN + MEASURE_BLOCKS, 4):
        raise AssertionError(f"unexpected workload shape: {workload.shape}")
    shock_hash = hashlib.sha256(
        np.ascontiguousarray(workload).view(np.uint8)
    ).hexdigest()

    all_rows: list[dict] = []
    all_path_rows: list[dict] = []
    design_rows: list[dict] = []
    started = time.time()

    for propagation_time in PROPAGATION_TIMES:
        physical = physical_capacities(propagation_time)
        limits = candidate_limits(physical)
        designs: list[dict] = []
        equilibria = []
        for benchmark in BENCHMARKS:
            for limit in limits:
                sufficient_rate = minimum_sufficient_floor_rate(
                    limit, float(physical["safe_payload_bytes"])
                )
                floor_rate = (
                    sufficient_rate
                    if benchmark.optimize_floor
                    else PROPOSAL_FLOOR_RATE
                )
                cpsb = cpsb_for_limit(limit, benchmark.match_state_growth)
                m_state = float(base.m_state) * cpsb / CPSB_REFERENCE
                m_data = float(anchors.loc[floor_rate].m_data)
                anchor = SharedFeeAnchor(
                    q_execution=float(base.q_execution_per_block),
                    q_data=float(base.q_data_per_block),
                    q_state=float(base.q_state_per_block),
                    m_execution=float(base.m_execution),
                    m_data=m_data,
                    m_state=m_state,
                    reference_fee_gwei=float(base.base_fee_ref_gwei),
                    eps_execution=EPS["execution"],
                    eps_data=EPS["data"],
                    eps_state=EPS["state"],
                )
                designs.append(
                    {
                        "benchmark": benchmark.benchmark,
                        "benchmark_label": benchmark.label,
                        "optimize_floor": benchmark.optimize_floor,
                        "match_state_growth": benchmark.match_state_growth,
                        "shared_limit": limit,
                        "shared_target": limit * TARGET_LIMIT_RATIO,
                        "minimum_sufficient_floor_rate": sufficient_rate,
                        "floor_rate": floor_rate,
                        "cpsb": cpsb,
                        "m_data": m_data,
                        "m_state": m_state,
                        "floor_payload_feasible": (
                            limit
                            <= floor_rate * float(physical["safe_payload_bytes"])
                            + 1e-6
                        ),
                    }
                )
                equilibria.append(
                    solve_shared_fee_equilibrium(limit / 2.0, anchor)
                )

        def repeat(values: list[float]) -> np.ndarray:
            return np.repeat(np.asarray(values, dtype=float), N_SEEDS)

        config = SharedFeeConfig(
            gas_target=repeat([row["shared_target"] for row in designs]),
            gas_limit=repeat([row["shared_limit"] for row in designs]),
            eps_execution=np.full(len(designs) * N_SEEDS, EPS["execution"]),
            eps_data=np.full(len(designs) * N_SEEDS, EPS["data"]),
            eps_state=np.full(len(designs) * N_SEEDS, EPS["state"]),
            m_execution=np.full(len(designs) * N_SEEDS, float(base.m_execution)),
            m_data=repeat([row["m_data"] for row in designs]),
            m_state=repeat([row["m_state"] for row in designs]),
            q_execution_0=float(base.q_execution_per_block),
            q_data_0=float(base.q_data_per_block),
            q_state_0=float(base.q_state_per_block),
            p0_gwei=float(base.base_fee_ref_gwei),
            w_execution=float(demand.w_execution_reference),
            w_state=float(demand.w_state_reference),
        )
        initial = repeat([equilibrium.base_fee_wei for equilibrium in equilibria])
        result = run_shared_fee_batch(config, workload, initial, burn_in=BURN_IN)

        for index, (design, equilibrium) in enumerate(
            zip(designs, equilibria, strict=True)
        ):
            selection = slice(index * N_SEEDS, (index + 1) * N_SEEDS)
            reference_execution = result["mean_reference_execution"][selection]
            reference_data = result["mean_reference_data"][selection]
            reference_state = result["mean_reference_state"][selection]
            execution_metered = result["mean_included_execution"][selection]
            data_metered = result["mean_included_data"][selection]
            state_metered = result["mean_included_state"][selection]
            regular_metered = result["mean_included_regular"][selection]
            used = result["mean_used"][selection, 1]
            fee = result["mean_fee_wei"][selection, 1]
            bal_data_gas_16 = result["mean_bal_payload"][selection]
            runtime_bal_bytes = bal_data_gas_16 / 16.0
            static_bytes = reference_data * bytes_per_data_gas
            counted_payload_bytes = static_bytes + runtime_bal_bytes
            state_bytes = state_metered / float(design["cpsb"])
            annual_state_gib = state_bytes * BLOCKS_PER_YEAR / BYTES_PER_GIB
            equilibrium_effective_log = np.log(
                max(equilibrium.base_fee_wei, 1.0) * float(design["m_data"])
            )
            level_mean = result["effective_price_mean_log_level"][selection, 1]
            level_square = result[
                "effective_price_mean_square_log_level"
            ][selection, 1]
            equilibrium_rmse = np.sqrt(
                np.maximum(
                    level_square
                    - 2 * equilibrium_effective_log * level_mean
                    + equilibrium_effective_log**2,
                    0.0,
                )
            )

            row = {
                "mechanism": "shared_fee_8131_8279",
                "workload": "full_multiscale_60d",
                "propagation_time_s": propagation_time,
                "execution_time_s": SLOT_BUDGET_S - propagation_time,
                **physical,
                **design,
                "target_limit_ratio": TARGET_LIMIT_RATIO,
                "n_replications": N_SEEDS,
                "burn_in_blocks": BURN_IN,
                "measured_blocks": MEASURE_BLOCKS,
                "daily_block_length": DAILY_BLOCK_LENGTH,
                "m_execution": float(base.m_execution),
                "reference_cpsb": CPSB_REFERENCE,
                "reference_m_state": float(base.m_state),
                "static_bytes_per_reference_data_gas": bytes_per_data_gas,
                "equilibrium_fee_wei": equilibrium.base_fee_wei,
                "equilibrium_floor_bounded": equilibrium.floor_bounded,
                "equilibrium_binding_branch": equilibrium.binding_branch,
                "equilibrium_regular_gas": equilibrium.regular_gas,
                "equilibrium_state_gas": equilibrium.state_gas,
                "equilibrium_execution_gas": equilibrium.execution_gas,
                "equilibrium_data_gas": equilibrium.data_gas,
                "equilibrium_state_activity_multiple": (
                    equilibrium.state_gas
                    / (float(design["m_state"]) * float(base.q_state_per_block))
                ),
                "equilibrium_state_bytes": (
                    equilibrium.state_gas / float(design["cpsb"])
                ),
                "equilibrium_annual_state_gib": (
                    equilibrium.state_gas
                    / float(design["cpsb"])
                    * BLOCKS_PER_YEAR
                    / BYTES_PER_GIB
                ),
            }
            metric_values = (
                ("included_execution", reference_execution),
                ("included_data", reference_data),
                ("included_state", reference_state),
                ("included_execution_metered", execution_metered),
                ("included_data_metered", data_metered),
                ("included_state_metered", state_metered),
                ("included_regular_metered", regular_metered),
                ("shared_gas_used", used),
                (
                    "shared_target_utilisation",
                    used / float(design["shared_target"]),
                ),
                ("shared_fee_wei", fee),
                (
                    "shared_fee_log_return_sd",
                    result["log_return_sd"][selection, 1],
                ),
                (
                    "shared_limit_hit_fraction",
                    result["included_limit_fraction"][selection, 1],
                ),
                (
                    "shared_near_limit_fraction",
                    result["near_limit_fraction"][selection, 1],
                ),
                (
                    "shared_fee_floor_bounded_fraction",
                    result["floor_downward_pressure_fraction"][selection, 1],
                ),
                (
                    "shared_target_deviation",
                    result["mean_absolute_target_deviation"][selection, 1],
                ),
                ("shared_rationed_gas", result["mean_rationed"][selection, 1]),
                (
                    "regular_binding_fraction",
                    result["regular_binding_fraction"][selection],
                ),
                ("runtime_bal_bytes", runtime_bal_bytes),
                ("estimated_static_payload_bytes", static_bytes),
                ("estimated_counted_payload_bytes", counted_payload_bytes),
                ("included_state_bytes", state_bytes),
                ("annualized_state_growth_gib", annual_state_gib),
                (
                    "base_fee_burn_eth_per_block",
                    result["mean_burn_wei"][selection, 1] / 1e18,
                ),
                (
                    "base_fee_exposure_proxy_eth_per_block",
                    result["mean_base_fee_exposure_proxy_wei"][selection] / 1e18,
                ),
                ("equilibrium_log_rmse", equilibrium_rmse),
            )
            for name, values in metric_values:
                add_distribution(row, name, values)
            all_rows.append(row)

            for replication in range(N_SEEDS):
                path_row = {
                    "propagation_time_s": propagation_time,
                    "benchmark": design["benchmark"],
                    "shared_limit": design["shared_limit"],
                    "shared_target": design["shared_target"],
                    "floor_rate": design["floor_rate"],
                    "cpsb": design["cpsb"],
                    "replication": replication,
                }
                for name, values in metric_values:
                    path_row[name] = float(values[replication])
                all_path_rows.append(path_row)

            design_rows.append(
                {
                    "propagation_time_s": propagation_time,
                    **physical,
                    **design,
                }
            )

        print(
            f"{propagation_time:.1f}s: {len(limits)} limits x "
            f"{len(BENCHMARKS)} benchmarks "
            f"[{time.time() - started:.1f}s]",
            flush=True,
        )

    scenarios = pd.DataFrame(all_rows).sort_values(
        ["benchmark", "propagation_time_s", "shared_limit"]
    )
    paths = pd.DataFrame(all_path_rows).sort_values(
        ["benchmark", "propagation_time_s", "shared_limit", "replication"]
    )
    designs = pd.DataFrame(design_rows).drop_duplicates(
        ["benchmark", "propagation_time_s", "shared_limit"]
    )
    if scenarios.duplicated(
        ["benchmark", "propagation_time_s", "shared_limit"]
    ).any():
        raise AssertionError("duplicate factorial scenario rows")
    if len(paths) != len(scenarios) * N_SEEDS:
        raise AssertionError("factorial path output does not reconcile")

    admissible = scenarios[scenarios["floor_payload_feasible"]].copy()
    maxima = admissible.groupby(["benchmark", "propagation_time_s"])[
        "included_execution"
    ].transform("max")
    candidates = admissible[
        admissible["included_execution"] >= 0.995 * maxima
    ].copy()
    candidates["throughput_gap_from_best"] = (
        maxima.loc[candidates.index] - candidates["included_execution"]
    )

    scenarios.to_csv(OUT / "shared_fee_factorial_scenarios.csv", index=False)
    paths.to_csv(OUT / "shared_fee_factorial_paths.csv", index=False)
    designs.to_csv(OUT / "shared_fee_factorial_designs.csv", index=False)
    candidates.to_csv(OUT / "shared_fee_factorial_candidates.csv", index=False)
    pd.DataFrame(
        [
            {
                "workload_sha256": shock_hash,
                "shape": "x".join(map(str, workload.shape)),
                "floor_rate_range": "40, 50, and 64--96 inclusive",
                "transfer_gas_per_byte": TRANSFER_GAS_PER_BYTE,
                "cpsb_reference": CPSB_REFERENCE,
                "reference_shared_limit": REFERENCE_SHARED_LIMIT,
                "static_bytes_per_reference_data_gas": bytes_per_data_gas,
            }
        ]
    ).to_csv(OUT / "shared_fee_factorial_manifest.csv", index=False)
    print(
        f"wrote {len(scenarios)} factorial scenarios and {len(paths)} path rows",
        flush=True,
    )


if __name__ == "__main__":
    main()
