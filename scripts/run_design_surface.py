"""Execution/data target surface under a fixed data limit.

The data limit is a protocol constant, so the design space is the pair of
targets (T_E, T_D) with L_D fixed and L_E = 2 T_E. Coupling T_D to T_E through
the static frontier assumes the operator always sits exactly on the one-wei
boundary; sweeping both independently shows the whole surface and lets the
question be asked the other way round -- given a tolerance for data-limit
pressure, how much execution is actually deliverable.

Both data limits of interest are run: the 90M counterfactual used throughout
the equilibrium report, and the 60M value written in ethereum/EIPs#11835.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import RESOURCES, BatchConfig, run_batch  # noqa: E402
from dynamics.empirical_shocks import (  # noqa: E402
    DEFAULT_BLOCK_LENGTH, build_shock_panel, moving_block_bootstrap,
)
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

BLOCKS_PER_DAY = 7_200
BURN_IN = BLOCKS_PER_DAY
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 32
STATE_TARGET = 75_000_000.0
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}

EXECUTION_TARGETS = np.array([150, 175, 200, 225, 250, 275, 300]) * 1e6
TARGET_RATIOS = np.array([0.25, 0.333, 0.40, 0.50, 0.583, 0.667, 0.75, 0.855])
DATA_LIMITS = (90e6, 60e6)


def cfg_target(config: BatchConfig, resource_index: int) -> np.ndarray:
    """The target a resource's utilisation is measured against."""

    return (config.execution_target, config.data_target,
            config.state_target)[resource_index]


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]

    panel = build_shock_panel(
        ROOT / "data/contiguous/contiguous_block_panel_2026-05-18_14d.csv",
        [ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv"],
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv",
    )
    shocks = moving_block_bootstrap(
        panel, N_SEEDS, MEASURE_BLOCKS + BURN_IN, DEFAULT_BLOCK_LENGTH,
        np.random.default_rng(20260812),
    )

    rows = []
    for data_limit in DATA_LIMITS:
        grid = [(e, r * data_limit) for e in EXECUTION_TARGETS for r in TARGET_RATIOS]
        n = len(grid)
        repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
        ones = np.ones(n * N_SEEDS)
        cfg = BatchConfig(
            execution_target=repeat([g[0] for g in grid]),
            execution_limit=repeat([2.0 * g[0] for g in grid]),
            data_target=repeat([g[1] for g in grid]),
            data_limit=ones * data_limit,
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
        for i, (execution_target, data_target) in enumerate(grid):
            sl = slice(i * N_SEEDS, (i + 1) * N_SEEDS)
            hits = out["limit_hit_fraction"][sl, 1]
            row = {
                "data_limit": data_limit, "execution_target": execution_target,
                "data_target": data_target, "target_ratio": data_target / data_limit,
                "included_execution": float(out["mean_used"][sl, 0].mean()),
                "execution_fill": float(out["mean_used"][sl, 0].mean() / execution_target),
                "data_limit_hit_fraction": float(hits.mean()),
                "data_limit_hit_ci95": 1.96 * float(np.std(hits, ddof=1)) / np.sqrt(N_SEEDS),
                "longest_data_limit_run": float(out["longest_limit_run"][sl, 1].mean()),
                "rationed_data": float(out["mean_rationed"][sl, 1].mean()),
                "execution_floor_fraction": float(out["floor_fraction"][sl, 0].mean()),
                "data_fee_sd": float(out["log_return_sd"][sl, 1].mean()),
            }
            # Every resource carries the same metric set, so a design can be read
            # on any axis without going back to the kernel. Prices are the
            # effective activity prices, not the raw base fees: an execution unit
            # pays its own metered gas plus the BAL data gas it generates, so its
            # base fee alone understates both its level and its variation.
            for j, resource in enumerate(RESOURCES):
                row.update({
                    f"{resource}_used": float(out["mean_used"][sl, j].mean()),
                    f"{resource}_utilisation": float(
                        out["mean_used"][sl, j].mean() / cfg_target(cfg, j)[i * N_SEEDS]
                    ),
                    f"{resource}_limit_hit_fraction": float(out["limit_hit_fraction"][sl, j].mean()),
                    f"{resource}_rationed": float(out["mean_rationed"][sl, j].mean()),
                    f"{resource}_floor_fraction": float(out["floor_fraction"][sl, j].mean()),
                    f"{resource}_fee_wei": float(out["mean_fee_wei"][sl, j].mean()),
                    f"{resource}_fee_sd": float(out["log_return_sd"][sl, j].mean()),
                    f"{resource}_price_sd": float(out["effective_price_log_return_sd"][sl, j].mean()),
                    f"{resource}_price_p95": float(out["effective_price_log_return_p95"][sl, j].mean()),
                    f"{resource}_price_p99": float(out["effective_price_log_return_p99"][sl, j].mean()),
                })
            rows.append(row)
        print(f"  data limit {data_limit/1e6:.0f}M: {n} designs done")

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/design_surface.csv"
    results.to_csv(out_path, index=False)
    print(f"\nwrote {out_path.relative_to(ROOT)}  ({len(results)} rows)")

    for data_limit in DATA_LIMITS:
        sub = results[results.data_limit == data_limit]
        print(f"\n=== data limit {data_limit/1e6:.0f}M — delivered execution (M) ===")
        pivot = sub.pivot(index="execution_target", columns="target_ratio",
                          values="included_execution") / 1e6
        pivot.index = [f"{i/1e6:.0f}M" for i in pivot.index]
        print(pivot.round(1).to_string())
        print(f"--- data-limit hit fraction ---")
        pivot = sub.pivot(index="execution_target", columns="target_ratio",
                          values="data_limit_hit_fraction")
        pivot.index = [f"{i/1e6:.0f}M" for i in pivot.index]
        print(pivot.round(3).to_string())

        print("\nmost execution deliverable at each tolerance for data-limit hits:")
        for tolerance in (0.01, 0.05, 0.10, 0.25):
            ok = sub[sub.data_limit_hit_fraction <= tolerance]
            if len(ok):
                best = ok.loc[ok.included_execution.idxmax()]
                print(f"   <= {tolerance:5.0%} hits : {best.included_execution/1e6:6.1f}M execution "
                      f"(T_E {best.execution_target/1e6:.0f}M, T_D {best.data_target/1e6:.1f}M, "
                      f"ratio {best.target_ratio:.3f})")
            else:
                print(f"   <= {tolerance:5.0%} hits : no design qualifies")


if __name__ == "__main__":
    main()
