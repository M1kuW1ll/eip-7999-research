"""Stage C: structural and elasticity robustness over the full 36-specification grid.

Every combination of lambda, rho_A and the four event-window elasticity vectors
is run, including the windows whose execution demand cannot reach the target.
Those are not dropped: they are classified and reported separately, because a
low execution fill means something different in each case.

  demand-constrained  execution cannot reach its target even with no BAL charge
                      at all, so no data capacity can fix it and the expected
                      signature is a pinned one-wei execution fee with the
                      target underfilled
  capacity-constrained execution could reach its target, and whether it does is
                      a question about data capacity and the BAL charge

Reporting them together without that split would attribute demand infeasibility
to data parameters.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import BatchConfig, run_batch, GWEI, MIN_BASE_FEE_PER_GAS  # noqa: E402
from dynamics.empirical_shocks import (  # noqa: E402
    DEFAULT_BLOCK_LENGTH, build_shock_panel, moving_block_bootstrap,
)
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

BLOCKS_PER_DAY = 7_200
WARM_BURN_IN = 20_000
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 64
STATE_TARGET = 75_000_000.0

DESIGNS = [
    ("E200_D45", 200e6, 45e6, 90e6),
    ("E225_D45", 225e6, 45e6, 90e6),
    ("E250_D60", 250e6, 60e6, 90e6),
    ("E300_D77", 300e6, 77e6, 90e6),
    ("E300_D85", 300e6, 85e6, 90e6),
]
LAMBDA_GRID = (0.0, 0.5, 1.0)
RHO_A_GRID = (0.75, 1.0, 1.25)


def no_bal_execution_ceiling(eps_execution: float, m_execution: float,
                             q_execution_0: float, p0_gwei: float) -> float:
    """Largest execution target reachable at a one-wei fee with no BAL charge."""

    charge_floor = m_execution * MIN_BASE_FEE_PER_GAS
    return (m_execution * q_execution_0) * (p0_gwei * GWEI / charge_floor) ** eps_execution


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    windows = pd.read_csv(ROOT / "data/glamsterdam/elasticity_vectors.csv").set_index("window_days")

    intensity = pd.read_csv(ROOT / "data/7999/bal_intensities.csv").set_index("lambda_bal")

    specs = []
    for window in (21, 35, 60, 75):
        row = windows.loc[window]
        for lam in LAMBDA_GRID:
            for rho in RHO_A_GRID:
                specs.append({
                    "window_days": window, "lambda_bal": lam, "rho_A": rho,
                    "eps_execution": float(row.eps_execution),
                    "eps_data": float(row.eps_data),
                    "eps_state": float(row.eps_state),
                    "w_execution": float(intensity.loc[lam, "w_execution"]),
                    "w_state": float(intensity.loc[lam, "w_state"]),
                })
    specs = pd.DataFrame(specs)
    print(f"{len(DESIGNS)} designs x {len(specs)} specifications x {N_SEEDS} seeds "
          f"= {len(DESIGNS)*len(specs)*N_SEEDS:,} trajectories")

    combos = [(d, s) for d in range(len(DESIGNS)) for s in range(len(specs))]
    n_combos = len(combos)
    design_index = np.array([c[0] for c in combos])
    spec_index = np.array([c[1] for c in combos])

    def per_trajectory(values, index):
        return np.repeat(np.asarray(values)[index], N_SEEDS).astype(float)

    batch = n_combos * N_SEEDS
    cfg = BatchConfig(
        execution_target=per_trajectory([d[1] for d in DESIGNS], design_index),
        execution_limit=per_trajectory([2.0 * d[1] for d in DESIGNS], design_index),
        data_target=per_trajectory([d[2] for d in DESIGNS], design_index),
        data_limit=per_trajectory([d[3] for d in DESIGNS], design_index),
        state_target=np.full(batch, STATE_TARGET),
        eps_execution=per_trajectory(specs.eps_execution, spec_index),
        eps_data=per_trajectory(specs.eps_data, spec_index),
        eps_state=per_trajectory(specs.eps_state, spec_index),
        w_execution=per_trajectory(specs.w_execution, spec_index),
        w_state=per_trajectory(specs.w_state, spec_index),
        rho_A=per_trajectory(specs.rho_A, spec_index),
        m_execution=float(demand.m_execution), m_state=float(demand.m_state),
        m_data_static=float(anchor.static_data_metering_multiplier),
        q_execution_0=float(demand.q_execution_per_block),
        q_state_0=float(demand.q_state_per_block),
        g_static_0=float(anchor.static_data_gas_per_block),
        p0_gwei=float(demand.base_fee_ref_gwei),
    )

    # Warm start each design/specification pair at its own equilibrium.
    warm_cfg = BatchConfig(**{
        f.name: (getattr(cfg, f.name)[::N_SEEDS] if isinstance(getattr(cfg, f.name), np.ndarray)
                 else getattr(cfg, f.name))
        for f in cfg.__dataclass_fields__.values()
    })
    warm = run_batch(warm_cfg, np.ones((n_combos, WARM_BURN_IN, 4)),
                     bundle_cost_equivalent_start(warm_cfg))
    start_fees = np.repeat(warm["final_base_fee_wei"], N_SEEDS, axis=0)

    panel = build_shock_panel(
        ROOT / "data/contiguous/contiguous_block_panel_2026-05-18_14d.csv",
        [ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv"],
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv",
    )
    shocks = moving_block_bootstrap(
        panel, N_SEEDS, MEASURE_BLOCKS, DEFAULT_BLOCK_LENGTH,
        np.random.default_rng(20260809),
    )
    out = run_batch(cfg, shocks, start_fees)
    print("replay complete")

    rows = []
    for k, (d, s) in enumerate(combos):
        name, execution_target, data_target, data_limit = DESIGNS[d]
        spec = specs.iloc[s]
        sl = slice(k * N_SEEDS, (k + 1) * N_SEEDS)
        ceiling = no_bal_execution_ceiling(
            spec.eps_execution, float(demand.m_execution),
            float(demand.q_execution_per_block), float(demand.base_fee_ref_gwei))
        fills = out["mean_used"][sl, 0] / execution_target
        rows.append({
            "design": name, "window_days": int(spec.window_days),
            "lambda_bal": spec.lambda_bal, "rho_A": spec.rho_A,
            "execution_target": execution_target, "data_limit": data_limit,
            "no_bal_execution_ceiling": ceiling,
            "regime": "demand_constrained" if ceiling < execution_target else "capacity_constrained",
            "execution_fill": float(fills.mean()),
            "execution_fill_ci95": 1.96 * float(np.std(fills, ddof=1)) / np.sqrt(N_SEEDS),
            "execution_floor_fraction": float(out["floor_fraction"][sl, 0].mean()),
            "mean_execution_fee_wei": float(out["mean_fee_wei"][sl, 0].mean()),
            "data_limit_hit_fraction": float(out["limit_hit_fraction"][sl, 1].mean()),
            "rationed_data": float(out["mean_rationed"][sl, 1].mean()),
            "fee_sd_data": float(out["log_return_sd"][sl, 1].mean()),
        })

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/stage_c_robustness.csv"
    results.to_csv(out_path, index=False)
    print(f"wrote {out_path.relative_to(ROOT)}  ({len(results)} rows)")

    e300 = results[results.execution_target == 300e6]
    print("\ndemand-constrained signature check, 300M designs:")
    for regime, group in e300.groupby("regime"):
        print(f"  {regime:22s} n={len(group):3d}  "
              f"execution fee {group.mean_execution_fee_wei.min():.2f}-{group.mean_execution_fee_wei.max():.2f} wei  "
              f"floor {group.execution_floor_fraction.min():.3f}-{group.execution_floor_fraction.max():.3f}  "
              f"fill {group.execution_fill.min():.3f}-{group.execution_fill.max():.3f}")


if __name__ == "__main__":
    main()
