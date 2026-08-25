"""Stage B: dynamic characterisation of the shortlisted designs.

Stage A screened on ordinary variation. This adds the named directional
stresses and the two initial conditions, on a deliberately small design set so
the results stay interpretable. The data limit is a protocol constant, so all
five designs share it and only the targets differ.

Warm starts are obtained by burning the design in under unit shocks rather than
by calling a separate static solver. Each design then converges to its own
equilibrium, which is the correct warm start in all three cases the plan
distinguishes: interior above the frontier, execution exactly at one wei on it,
and floor-bound with execution underfilling below it.

Cold starts use the bundle-cost-equivalent launch fees, which preserve the
historical BAL-inclusive parent prices at activation. The three naive anchors
p0/m_i are not jointly cost-equivalent once BAL is priced.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import BatchConfig, run_batch, GWEI  # noqa: E402
from run_multiscale_design_surface import build_canonical_workload  # noqa: E402
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

BLOCKS_PER_DAY = 7_200
WARM_BURN_IN = 20_000
STRESS_BLOCKS = 7_200
STRESS_ONSET = 1_200
N_SEEDS = 24
STATE_TARGET = 75_000_000.0

SHORTLIST = [
    ("E200_D45", 200e6, 45e6, 90e6),
    ("E225_D45", 225e6, 45e6, 90e6),
    ("E250_D60", 250e6, 60e6, 90e6),
    ("E300_D77", 300e6, 77e6, 90e6),
    ("E300_D80", 300e6, 80e6, 90e6),
    ("E300_D85", 300e6, 85e6, 90e6),
]

# Amplitude and half-life in blocks, per shock component (execution, data,
# state, access). The central pulse doubles the stressed component and decays
# with a 120-block half-life; the broad case trades amplitude for duration.
STRESSES = {
    "baseline":          ((1.0, 1.0, 1.0, 1.0), 120),
    "execution":         ((2.0, 1.0, 1.0, 1.0), 120),
    "static_data":       ((1.0, 2.0, 1.0, 1.0), 120),
    "state":             ((1.0, 1.0, 2.0, 1.0), 120),
    "access_only":       ((1.0, 1.0, 1.0, 2.0), 120),
    "execution_access":  ((2.0, 1.0, 1.0, 2.0), 120),
    "broad_persistent":  ((1.4, 1.4, 1.4, 1.4), 1200),
}


def stress_multiplier(amplitudes, half_life: int, n_blocks: int) -> np.ndarray:
    """Decaying pulse applied on top of the empirical shock path."""

    t = np.arange(n_blocks)
    decay = np.where(t >= STRESS_ONSET,
                     np.exp(-(t - STRESS_ONSET) * np.log(2.0) / half_life), 0.0)
    return 1.0 + np.outer(decay, np.array(amplitudes) - 1.0)


def make_config(designs, eps, batch_repeat, demand, anchor) -> BatchConfig:
    repeat = lambda values: np.repeat(np.asarray(values, dtype=float), batch_repeat)
    ones = np.ones(len(designs) * batch_repeat)
    return BatchConfig(
        execution_target=repeat([d[1] for d in designs]),
        execution_limit=repeat([2.0 * d[1] for d in designs]),
        data_target=repeat([d[2] for d in designs]),
        data_limit=repeat([d[3] for d in designs]),
        state_target=ones * STATE_TARGET,
        eps_execution=ones * eps["execution"],
        eps_data=ones * eps["data"],
        eps_state=ones * eps["state"],
        w_execution=ones * float(demand.w_execution_reference),
        w_state=ones * float(demand.w_state_reference),
        rho_A=ones,
        m_execution=float(demand.m_execution), m_state=float(demand.m_state),
        m_data_static=float(anchor.static_data_metering_multiplier),
        q_execution_0=float(demand.q_execution_per_block),
        q_state_0=float(demand.q_state_per_block),
        g_static_0=float(anchor.static_data_gas_per_block),
        p0_gwei=float(demand.base_fee_ref_gwei),
    )


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    eps = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}

    # Warm start: converge each design under unit shocks to its own equilibrium.
    warm_cfg = make_config(SHORTLIST, eps, 1, demand, anchor)
    warm = run_batch(warm_cfg, np.ones((len(SHORTLIST), WARM_BURN_IN, 4)),
                     bundle_cost_equivalent_start(warm_cfg), bundle_consistent=True)
    warm_fees = warm["final_base_fee_wei"]
    print("warm-start equilibria reached under unit shocks:")
    for i, (name, execution_target, *_rest) in enumerate(SHORTLIST):
        fill = warm["mean_used"][i, 0] / execution_target
        print(f"  {name:22s} fees(wei) exec {warm_fees[i,0]:12,.0f}  data {warm_fees[i,1]:10,.0f}"
              f"  state {warm_fees[i,2]:12,.0f}   execution fill {fill:.4f}")

    cfg = make_config(SHORTLIST, eps, N_SEEDS, demand, anchor)
    base_shocks = build_canonical_workload().paths[:N_SEEDS, :STRESS_BLOCKS]
    tiled = base_shocks

    starts = {
        "warm": np.repeat(warm_fees, N_SEEDS, axis=0),
        "cold": bundle_cost_equivalent_start(cfg),
    }

    rows = []
    for stress, (amplitudes, half_life) in STRESSES.items():
        pulse = stress_multiplier(amplitudes, half_life, STRESS_BLOCKS)
        shocks = tiled * pulse[None, :, :]
        for start_name, start_fees in starts.items():
            out = run_batch(
                cfg, shocks, start_fees, return_paths=True,
                bundle_consistent=True,
            )
            fee_paths = out["fee_paths"]
            for i, (name, execution_target, data_target, data_limit) in enumerate(SHORTLIST):
                sl = slice(i * N_SEEDS, (i + 1) * N_SEEDS)
                data_fee = fee_paths[sl, :, 1]
                pre = np.median(data_fee[:, :STRESS_ONSET], axis=1)
                peak = data_fee[:, STRESS_ONSET:].max(axis=1)
                # Recovery: first block after the pulse from which the data fee
                # stays within 10% of its pre-stress level for the remainder.
                within = np.abs(data_fee[:, STRESS_ONSET:] / pre[:, None] - 1.0) <= 0.10
                never = ~within[:, ::-1].cumprod(axis=1)[:, ::-1].astype(bool)
                recovery = np.where(never.all(axis=1), np.nan, never.sum(axis=1))
                rows.append({
                    "design": name, "stress": stress, "start": start_name,
                    "data_limit": data_limit,
                    "peak_data_fee_multiple": float(np.mean(peak / np.maximum(pre, 1.0))),
                    "recovery_blocks_median": float(np.nanmedian(recovery)),
                    "recovery_fraction": float(np.mean(~np.isnan(recovery))),
                    "data_limit_hit_fraction": float(out["limit_hit_fraction"][sl, 1].mean()),
                    "data_offered_limit_pressure_fraction": float(
                        out["offered_limit_pressure_fraction"][sl, 1].mean()
                    ),
                    "data_cap_active_fraction": float(
                        out["cap_active_fraction"][sl, 1].mean()
                    ),
                    "data_scale_determining_fraction": float(
                        out["scale_determining_fraction"][sl, 1].mean()
                    ),
                    "longest_data_limit_run": float(out["longest_limit_run"][sl, 1].mean()),
                    "rationed_data": float(out["mean_rationed"][sl, 1].mean()),
                    "execution_fill": float(out["mean_used"][sl, 0].mean() / execution_target),
                    "execution_floor_bounded_fraction": float(
                        out["floor_downward_pressure_fraction"][sl, 0].mean()
                    ),
                })
        print(f"  stress '{stress}' done")

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/stage_b_stresses.csv"
    results.to_csv(out_path, index=False)
    print(f"\nwrote {out_path.relative_to(ROOT)}  ({len(results)} rows)")


if __name__ == "__main__":
    main()
