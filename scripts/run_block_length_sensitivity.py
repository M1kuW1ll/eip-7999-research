"""Moving-block-bootstrap length sensitivity for the central dynamic rankings."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import (  # noqa: E402
    BatchConfig,
    bundle_cost_equivalent_start,
    run_batch,
)
from dynamics.multiscale_shocks import build_full_multiscale_workload  # noqa: E402

BLOCKS_PER_DAY = 7_200
BURN_IN = BLOCKS_PER_DAY
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 32
REPORT_SHOCK_SEED = 20260814
DAILY_SHOCK_SEED = REPORT_SHOCK_SEED + 1
DAILY_BLOCK_LENGTH = 8
STATE_TARGET = 75_000_000.0
DATA_LIMIT = 90_000_000.0
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}
BLOCK_LENGTHS = (400, 800, 1_600, 3_200)
DESIGNS = (
    ("E225_D45", 225e6, 45e6),
    ("E250_D60", 250e6, 60e6),
    ("E300_D80", 300e6, 80e6),
)


def build_config(repeat_count: int, demand: pd.Series, anchor: pd.Series) -> BatchConfig:
    repeat = lambda values: np.repeat(np.asarray(values, dtype=float), repeat_count)
    ones = np.ones(len(DESIGNS) * repeat_count)
    return BatchConfig(
        execution_target=repeat([item[1] for item in DESIGNS]),
        execution_limit=repeat([2.0 * item[1] for item in DESIGNS]),
        data_target=repeat([item[2] for item in DESIGNS]),
        data_limit=ones * DATA_LIMIT,
        state_target=ones * STATE_TARGET,
        eps_execution=ones * EPS["execution"],
        eps_data=ones * EPS["data"],
        eps_state=ones * EPS["state"],
        w_execution=ones * float(demand.w_execution_reference),
        w_state=ones * float(demand.w_state_reference),
        rho_A=ones,
        m_execution=float(demand.m_execution),
        m_state=float(demand.m_state),
        m_data_static=float(anchor.static_data_metering_multiplier),
        q_execution_0=float(demand.q_execution_per_block),
        q_state_0=float(demand.q_state_per_block),
        g_static_0=float(anchor.static_data_gas_per_block),
        p0_gwei=float(demand.base_fee_ref_gwei),
    )


def add_interval(row: dict, name: str, values: np.ndarray) -> None:
    values = np.asarray(values, dtype=float)
    row[name] = float(values.mean())
    row[f"{name}_p05"] = float(np.quantile(values, 0.05))
    row[f"{name}_p95"] = float(np.quantile(values, 0.95))


def main() -> None:
    demand = pd.read_csv(
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
    ).iloc[0]
    anchor = pd.read_csv(
        ROOT / "data/7999/data_metering_runtime_bal_anchor.csv"
    ).iloc[0]
    cfg = build_config(N_SEEDS, demand, anchor)

    rows: list[dict] = []
    for block_length in BLOCK_LENGTHS:
        workload = build_full_multiscale_workload(
            block_panel_path=ROOT / "data/contiguous/contiguous_block_panel_2026-04-02_60d.csv",
            runtime_bal_paths=[
                ROOT / "data/contiguous/contiguous_runtime_bal_hist60d_24788193_25118358.csv",
                ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv",
            ],
            demand_parameters_path=ROOT / "data/7999/bal_decomposition_demand_parameters.csv",
            accounting_panel_path=ROOT / "data/daily_accounting_panel_calibrated_with_bal_2026-02-01_2026-06-01.csv",
            current_data_gas_path=ROOT / "data/daily_current_data_gas_xatu_2026-02-01_2026-06-01.csv",
            n_paths=N_SEEDS,
            n_blocks=BURN_IN + MEASURE_BLOCKS,
            fast_block_length=block_length,
            daily_block_length=DAILY_BLOCK_LENGTH,
            fast_seed=REPORT_SHOCK_SEED,
            daily_seed=DAILY_SHOCK_SEED,
        )
        result = run_batch(
            cfg,
            workload.paths,
            bundle_cost_equivalent_start(cfg),
            burn_in=BURN_IN,
            bundle_consistent=True,
        )
        for index, (design, execution_target, _data_target) in enumerate(DESIGNS):
            sl = slice(index * N_SEEDS, (index + 1) * N_SEEDS)
            row = {"design": design, "block_length": block_length}
            add_interval(
                row,
                "execution_fill",
                result["mean_used"][sl, 0] / execution_target,
            )
            add_interval(
                row,
                "data_limit_hit_fraction",
                result["included_limit_fraction"][sl, 1],
            )
            add_interval(row, "rationed_data", result["mean_rationed"][sl, 1])
            add_interval(
                row,
                "execution_floor_bounded_fraction",
                result["floor_downward_pressure_fraction"][sl, 0],
            )
            rows.append(row)
        print(f"block length {block_length:,}: complete")

    output = pd.DataFrame(rows)
    path = ROOT / "data/7999/block_length_sensitivity.csv"
    output.to_csv(path, index=False)
    print(f"wrote {path.relative_to(ROOT)} ({len(output)} rows)")


if __name__ == "__main__":
    main()
