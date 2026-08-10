"""Stage A: relative screening of EIP-7999 target/limit designs.

Nine target pairs, placed relative to the static execution-clearing frontier
rather than on an arbitrary grid, crossed with two data-limit families. Each
design runs under the central 35-day calibration and an adverse low-execution
calibration, over common empirical shock paths.

Screening is deliberately relative. Absolute reliability thresholds are a
governance choice, so this reports the Pareto-nondominated set under either
calibration and does not apply pass/fail criteria of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import BatchConfig, run_batch, GWEI  # noqa: E402
from dynamics.empirical_shocks import (  # noqa: E402
    DEFAULT_BLOCK_LENGTH, build_shock_panel, moving_block_bootstrap,
)

BLOCKS_PER_DAY = 7_200
BURN_IN_DAYS = 1
MEASURE_DAYS = 7
N_SEEDS = 32
STATE_TARGET = 75_000_000.0

# Data targets placed below / near / above the static frontier for each
# execution target. Frontier values: 200M -> ~35M, 250M -> ~51.5M, 300M -> 77M.
TARGET_PAIRS = [
    (200e6, 30e6, "below"), (200e6, 35e6, "near"), (200e6, 45e6, "above"),
    (250e6, 45e6, "below"), (250e6, 51.5e6, "near"), (250e6, 60e6, "above"),
    (300e6, 60e6, "below"), (300e6, 77e6, "near"), (300e6, 85e6, "above"),
]
DATA_LIMIT_FAMILIES = {"fixed90M": None, "matched2x": 2.0}

CALIBRATIONS = {
    "central35": {"execution": 0.121160, "data": 0.229476, "state": 0.334864},
    "adverse75": {"execution": 0.078511, "data": 0.201391, "state": 0.253556},
}


def bundle_cost_equivalent_start(cfg: BatchConfig) -> np.ndarray:
    """Historically cost-equivalent launch fees, in wei.

    The three naive anchors p0/m_i are not jointly cost-equivalent once BAL is
    priced, because the BAL charge adds to both parent prices. Anchoring the
    data fee and solving the parents back to p0 preserves the historical
    BAL-inclusive execution and state prices at launch.
    """

    p0 = cfg.p0_gwei * GWEI
    b_data = p0 / cfg.m_data_static
    b_execution = np.maximum(1.0, (p0 - cfg.w_execution * b_data) / cfg.m_execution)
    b_state = np.maximum(1.0, (p0 - cfg.w_state * b_data) / cfg.m_state)
    return np.stack([b_execution, np.full_like(b_execution, b_data), b_state], axis=1)


def build_designs() -> pd.DataFrame:
    rows = []
    for execution_target, data_target, position in TARGET_PAIRS:
        for family, multiple in DATA_LIMIT_FAMILIES.items():
            rows.append({
                "design": f"E{execution_target/1e6:.0f}_D{data_target/1e6:.0f}_{family}",
                "execution_target": execution_target,
                "execution_limit": 2.0 * execution_target,
                "data_target": data_target,
                "data_limit": 90e6 if multiple is None else multiple * data_target,
                "state_target": STATE_TARGET,
                "frontier_position": position,
                "data_limit_family": family,
            })
    return pd.DataFrame(rows)


def main() -> None:
    designs = build_designs()
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]

    panel = build_shock_panel(
        ROOT / "data/contiguous/contiguous_block_panel_2026-05-18_14d.csv",
        [ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv"],
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv",
    )
    n_blocks = (BURN_IN_DAYS + MEASURE_DAYS) * BLOCKS_PER_DAY
    print(f"shock panel: {panel.n_blocks:,} blocks; drawing {N_SEEDS} paths x {n_blocks:,} blocks")

    # Common random numbers: every design and calibration sees the identical
    # shock paths, so design comparisons are paired and seed noise cancels.
    shared = moving_block_bootstrap(
        panel, N_SEEDS, n_blocks, DEFAULT_BLOCK_LENGTH, np.random.default_rng(20260807)
    )

    rows = []
    for calibration, eps in CALIBRATIONS.items():
        n_designs = len(designs)
        batch = n_designs * N_SEEDS
        repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
        ones = np.ones(batch)

        cfg = BatchConfig(
            execution_target=repeat(designs.execution_target),
            execution_limit=repeat(designs.execution_limit),
            data_target=repeat(designs.data_target),
            data_limit=repeat(designs.data_limit),
            state_target=repeat(designs.state_target),
            eps_execution=ones * eps["execution"],
            eps_data=ones * eps["data"],
            eps_state=ones * eps["state"],
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
        shocks = shared
        out = run_batch(cfg, shocks, bundle_cost_equivalent_start(cfg),
                        burn_in=BURN_IN_DAYS * BLOCKS_PER_DAY)

        for i, design in designs.iterrows():
            sl = slice(i * N_SEEDS, (i + 1) * N_SEEDS)

            # Uncertainty is reported across weekly replications, not across
            # blocks: block observations are serially dependent, so pooling
            # them would overstate precision by roughly the square root of the
            # integrated correlation time.
            def replication_ci(values: np.ndarray) -> tuple[float, float]:
                mean = float(np.mean(values))
                half = 1.96 * float(np.std(values, ddof=1)) / np.sqrt(len(values))
                return mean, half

            limit_mean, limit_half = replication_ci(out["limit_hit_fraction"][sl, 1])
            ration_mean, ration_half = replication_ci(out["mean_rationed"][sl, 1])
            fill_mean, fill_half = replication_ci(
                out["mean_used"][sl, 0] / design.execution_target
            )
            rows.append({
                "data_limit_hit_ci95_halfwidth": limit_half,
                "rationed_data_ci95_halfwidth": ration_half,
                "execution_fill_ci95_halfwidth": fill_half,
                "n_replications": N_SEEDS,
                "design": design.design, "calibration": calibration,
                "frontier_position": design.frontier_position,
                "data_limit_family": design.data_limit_family,
                "execution_target": design.execution_target,
                "data_target": design.data_target,
                "data_limit": design.data_limit,
                "execution_fill": out["mean_used"][sl, 0].mean() / design.execution_target,
                "data_fill": out["mean_used"][sl, 1].mean() / design.data_target,
                "included_execution": out["mean_used"][sl, 0].mean(),
                "fee_sd_execution": out["log_return_sd"][sl, 0].mean(),
                "fee_sd_data": out["log_return_sd"][sl, 1].mean(),
                "data_limit_hit_fraction": out["limit_hit_fraction"][sl, 1].mean(),
                "longest_data_limit_run": out["longest_limit_run"][sl, 1].mean(),
                "execution_floor_fraction": out["floor_fraction"][sl, 0].mean(),
                "rationed_data": out["mean_rationed"][sl, 1].mean(),
                "rationed_execution": out["mean_rationed"][sl, 0].mean(),
                "mean_data_fee_wei": out["mean_fee_wei"][sl, 1].mean(),
            })
        print(f"  {calibration}: {batch:,} trajectories x {n_blocks:,} blocks done")

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/stage_a_screening.csv"
    results.to_csv(out_path, index=False)
    print(f"\nwrote {out_path.relative_to(ROOT)}")

    # Relative screening only: a design is dominated if another is at least as
    # good on every axis and strictly better somewhere. No absolute thresholds.
    axes = [("included_execution", 1), ("fee_sd_execution", -1), ("fee_sd_data", -1),
            ("data_limit_hit_fraction", -1), ("rationed_data", -1)]
    keep = set()
    for calibration, group in results.groupby("calibration"):
        values = group[[a for a, _ in axes]].to_numpy()
        signs = np.array([s for _, s in axes])
        scored = values * signs
        for i, design in enumerate(group.design):
            better_equal = (scored >= scored[i] - 1e-12).all(axis=1)
            strictly = (scored > scored[i] + 1e-12).any(axis=1)
            if not (better_equal & strictly).any():
                keep.add(design)
    results["pareto_nondominated"] = results.design.isin(keep)
    results.to_csv(out_path, index=False)
    print(f"nondominated under either calibration: {len(keep)} of {results.design.nunique()} designs")
    for design in sorted(keep):
        print(f"    {design}")


if __name__ == "__main__":
    main()
