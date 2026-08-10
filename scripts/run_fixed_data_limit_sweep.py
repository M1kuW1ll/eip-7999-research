"""What data target is viable under a fixed data limit?

The data limit is a protocol constant, not a per-design choice, so the only
data-side design variable is the target. Raising the target buys steady-state
capacity and spends burst headroom out of the same fixed budget:

    headroom = L_D - T_D,   target ratio = T_D / L_D.

This sweeps the target under a fixed limit and pairs each with the execution
target the static execution-clearing frontier says it supports, so the
dynamic cost of a target ratio can be read against what that ratio buys.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import BatchConfig, run_batch  # noqa: E402
from dynamics.empirical_shocks import (  # noqa: E402
    DEFAULT_BLOCK_LENGTH, build_shock_panel, moving_block_bootstrap,
)
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

BLOCKS_PER_DAY = 7_200
BURN_IN = BLOCKS_PER_DAY
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 48
STATE_TARGET = 75_000_000.0
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}

DATA_LIMIT = 90e6
TARGET_RATIOS = (0.25, 0.333, 0.40, 0.50, 0.583, 0.667, 0.75, 0.855, 0.944)

# Execution target the static one-wei frontier supports at each data target,
# interpolated from the reference frontier in the equilibrium report.
FRONTIER_DATA = np.array([15, 18, 22.5, 30, 45, 60, 75, 90]) * 1e6
FRONTIER_EXECUTION = np.array([116.9, 131.8, 152.2, 182.2, 232.4, 271.0, 297.4, 312.5]) * 1e6


def supported_execution(data_target: np.ndarray) -> np.ndarray:
    return np.interp(data_target, FRONTIER_DATA, FRONTIER_EXECUTION)


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]

    data_targets = np.array(TARGET_RATIOS) * DATA_LIMIT
    execution_targets = supported_execution(data_targets)
    n = len(data_targets)

    panel = build_shock_panel(
        ROOT / "data/contiguous/contiguous_block_panel_2026-05-18_14d.csv",
        [ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv"],
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv",
    )
    shocks = moving_block_bootstrap(
        panel, N_SEEDS, MEASURE_BLOCKS + BURN_IN, DEFAULT_BLOCK_LENGTH,
        np.random.default_rng(20260811),
    )

    repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
    ones = np.ones(n * N_SEEDS)
    cfg = BatchConfig(
        execution_target=repeat(execution_targets),
        execution_limit=repeat(2.0 * execution_targets),
        data_target=repeat(data_targets), data_limit=ones * DATA_LIMIT,
        state_target=ones * STATE_TARGET,
        eps_execution=ones * EPS["execution"], eps_data=ones * EPS["data"],
        eps_state=ones * EPS["state"],
        w_execution=ones * float(demand.w_execution_reference),
        w_state=ones * float(demand.w_state_reference), rho_A=ones,
        m_execution=float(demand.m_execution), m_state=float(demand.m_state),
        m_data_static=float(anchor.static_data_metering_multiplier),
        q_execution_0=float(demand.q_execution_per_block),
        q_state_0=float(demand.q_state_per_block),
        g_static_0=float(anchor.static_data_gas_per_block),
        p0_gwei=float(demand.base_fee_ref_gwei),
    )
    out = run_batch(cfg, shocks, bundle_cost_equivalent_start(cfg), burn_in=BURN_IN)

    rows = []
    for i in range(n):
        sl = slice(i * N_SEEDS, (i + 1) * N_SEEDS)
        hits = out["limit_hit_fraction"][sl, 1]
        rows.append({
            "data_limit": DATA_LIMIT, "data_target": data_targets[i],
            "target_ratio": TARGET_RATIOS[i],
            "headroom": DATA_LIMIT - data_targets[i],
            "supported_execution_target": execution_targets[i],
            "data_limit_hit_fraction": float(hits.mean()),
            "data_limit_hit_ci95": 1.96 * float(np.std(hits, ddof=1)) / np.sqrt(N_SEEDS),
            "longest_data_limit_run": float(out["longest_limit_run"][sl, 1].mean()),
            "rationed_data": float(out["mean_rationed"][sl, 1].mean()),
            "included_execution": float(out["mean_used"][sl, 0].mean()),
            "execution_fill": float(out["mean_used"][sl, 0].mean() / execution_targets[i]),
            "data_fee_sd": float(out["log_return_sd"][sl, 1].mean()),
        })

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/fixed_data_limit_sweep.csv"
    results.to_csv(out_path, index=False)

    print(f"Data limit fixed at {DATA_LIMIT/1e6:.0f}M; target is the only data-side choice.\n")
    print(f"{'T_D':>8} {'ratio':>7} {'headroom':>9} {'supports T_E':>13} "
          f"{'limit hits':>12} {'longest run':>12} {'rationed':>11} {'delivered':>11}")
    for _, r in results.iterrows():
        print(f"{r.data_target/1e6:7.1f}M {r.target_ratio:7.3f} {r.headroom/1e6:8.1f}M "
              f"{r.supported_execution_target/1e6:12.1f}M {r.data_limit_hit_fraction:12.4f} "
              f"{r.longest_data_limit_run:12.1f} {r.rationed_data/1e6:10.2f}M "
              f"{r.included_execution/1e6:10.1f}M")
    print(f"\nwrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
