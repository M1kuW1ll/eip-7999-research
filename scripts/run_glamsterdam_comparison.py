"""Compare Glamsterdam and full EIP-7999 under one latent workload.

Each mechanism is run at its own central proposed parameters rather than forced
onto a common capacity. Glamsterdam is a 200M gas limit with a 100M target,
covering execution and data in one metered branch against state in the other,
priced by a single base fee. EIP-7999 gives each resource its own target and
limit and prices them separately.

Matching the two on realised execution is not a usable comparison: because one
shared fee cannot separate execution from state, delivering EIP-7999's
execution throughput under Glamsterdam requires lowering the shared fee until
state creation runs to tens of times the level EIP-7999 holds it at. That
trade-off is the structural difference being measured, so it is reported as a
frontier in (execution, state) space with each mechanism's central design
marked, instead of being hidden inside a matching rule.

Both mechanisms see identical shock paths from the same seeds. The access shock
changes BAL payload in both worlds but enters fee-controlled gas only under
EIP-7999, where BAL is a priced resource.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import BatchConfig, run_batch, GWEI  # noqa: E402
from dynamics.glamsterdam_replay import GlamsterdamConfig, run_glamsterdam_batch  # noqa: E402
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

GLAMSTERDAM_CENTRAL_LIMIT = 200e6
GLAMSTERDAM_SWEEP = (100e6, 150e6, 200e6, 300e6, 450e6, 600e6)

# The data limit is a fixed protocol constant, so every design shares it and
# only the targets vary. E225/D45 is the central case: at a conventional half
# target ratio it is the largest execution target the data side actually
# supports, delivering 223.3M at 99.3% utilisation. Raising T_E to 250M buys
# only 12M more throughput and does so by configuring a target that cannot be
# met: fill drops to 94% and the execution fee falls to its one-wei floor in 80%
# of blocks rather than 13%.
DATA_LIMIT = 90e6
DESIGNS = [
    ("E200_D45", 200e6, 45e6, DATA_LIMIT),
    ("E225_D45", 225e6, 45e6, DATA_LIMIT),
    ("E250_D60", 250e6, 60e6, DATA_LIMIT),
]

# Representative bundles in historical gas-equivalent units, so the mechanisms
# are compared on what a user pays rather than on base fees that price
# different gas units.
BUNDLES = {
    "execution_heavy": {"execution": 200_000.0, "data": 2_000.0, "state": 0.0},
    "data_heavy":      {"execution": 40_000.0, "data": 100_000.0, "state": 0.0},
    "state_creating":  {"execution": 80_000.0, "data": 3_000.0, "state": 40_000.0},
    "mixed":           {"execution": 120_000.0, "data": 20_000.0, "state": 10_000.0},
}


def seven999_config(design, batch, demand, anchor):
    _, execution_target, data_target, data_limit = design
    ones = np.ones(batch)
    return BatchConfig(
        execution_target=ones * execution_target, execution_limit=ones * 2 * execution_target,
        data_target=ones * data_target, data_limit=ones * data_limit,
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


def glamsterdam_config(gas_limit, batch, glam):
    ones = np.ones(batch)
    return GlamsterdamConfig(
        gas_target=ones * gas_limit / 2.0, gas_limit=ones * gas_limit,
        eps_execution=ones * EPS["execution"], eps_data=ones * EPS["data"],
        eps_state=ones * EPS["state"],
        m_execution=float(glam.m_execution), m_data=float(glam.m_data),
        m_state=float(glam.m_state),
        q_execution_0=float(glam.q_execution_per_block),
        q_data_0=float(glam.q_data_per_block),
        q_state_0=float(glam.q_state_per_block),
        p0_gwei=float(glam.base_fee_ref_gwei),
    )


def bundle_costs(fees_wei, multipliers, prefix):
    return {
        f"{prefix}_{name}": sum(
            multipliers[r] * fees_wei[r] * amount for r, amount in bundle.items()
        )
        for name, bundle in BUNDLES.items()
    }


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    glam = pd.read_csv(ROOT / "data/glamsterdam/equilibrium_anchor.csv").iloc[0]

    panel = build_shock_panel(
        ROOT / "data/contiguous/contiguous_block_panel_2026-05-18_14d.csv",
        [ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv"],
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv",
    )
    shocks = moving_block_bootstrap(
        panel, N_SEEDS, MEASURE_BLOCKS + BURN_IN, DEFAULT_BLOCK_LENGTH,
        np.random.default_rng(20260810),
    )
    start_fee = np.full(N_SEEDS, float(glam.base_fee_ref_wei))
    glam_multipliers = {"execution": float(glam.m_execution),
                        "data": float(glam.m_data), "state": float(glam.m_state)}

    rows = []
    for gas_limit in GLAMSTERDAM_SWEEP:
        out = run_glamsterdam_batch(
            glamsterdam_config(gas_limit, N_SEEDS, glam), shocks, start_fee, burn_in=BURN_IN
        )
        shared = float(out["mean_fee_wei"][:, 0].mean())
        rows.append({
            "mechanism": "glamsterdam",
            "design": f"G{gas_limit/1e6:.0f}M",
            "is_central": gas_limit == GLAMSTERDAM_CENTRAL_LIMIT,
            "gas_limit": gas_limit, "gas_target": gas_limit / 2.0,
            "included_execution": float(out["mean_included_execution"].mean()),
            "state_gas": float(out["mean_used"][:, 2].mean()),
            "shared_fee_wei": shared,
            "fee_sd": float(out["log_return_sd"][:, 0].mean()),
            "limit_hit_fraction": float(out["limit_hit_fraction"][:, 1].mean()),
            "rationed": float(out["mean_rationed"][:, 1].mean()),
            "regular_binding_fraction": float(out["regular_binding_fraction"].mean()),
            **bundle_costs({r: shared for r in EPS}, glam_multipliers, "cost"),
        })

    for design in DESIGNS:
        name, execution_target, data_target, data_limit = design
        cfg = seven999_config(design, N_SEEDS, demand, anchor)
        out = run_batch(cfg, shocks, bundle_cost_equivalent_start(cfg), burn_in=BURN_IN)
        fees = {"execution": float(out["mean_fee_wei"][:, 0].mean()),
                "data": float(out["mean_fee_wei"][:, 1].mean()),
                "state": float(out["mean_fee_wei"][:, 2].mean())}
        rows.append({
            "mechanism": "eip7999", "design": name, "is_central": name == "E225_D45",
            "gas_limit": np.nan, "gas_target": np.nan,
            "included_execution": float(out["mean_used"][:, 0].mean()),
            "state_gas": float(out["mean_used"][:, 2].mean()),
            "shared_fee_wei": np.nan,
            "fee_sd": float(out["log_return_sd"][:, 1].mean()),
            "limit_hit_fraction": float(out["limit_hit_fraction"][:, 1].mean()),
            "rationed": float(out["mean_rationed"][:, 1].mean()),
            "regular_binding_fraction": np.nan,
            **bundle_costs(fees, {"execution": float(demand.m_execution),
                                  "data": float(anchor.static_data_metering_multiplier),
                                  "state": float(demand.m_state)}, "cost"),
        })

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/glamsterdam_comparison.csv"
    results.to_csv(out_path, index=False)

    print("Glamsterdam sweep, one shared fee over two metered branches:\n")
    print(f"{'limit':>8} {'execution':>11} {'state gas':>11} {'shared fee':>13} "
          f"{'fee sd':>8} {'regular binds':>14}")
    for _, r in results[results.mechanism == "glamsterdam"].iterrows():
        mark = "  <- central" if r.is_central else ""
        print(f"{r.gas_limit/1e6:7.0f}M {r.included_execution/1e6:10.1f}M "
              f"{r.state_gas/1e6:10.1f}M {r.shared_fee_wei:13,.0f} {r.fee_sd:8.4f} "
              f"{r.regular_binding_fraction:14.3f}{mark}")
    print("\nEIP-7999 designs:\n")
    print(f"{'design':>22} {'execution':>11} {'state gas':>11} {'data fee sd':>12} {'limit hits':>11}")
    for _, r in results[results.mechanism == "eip7999"].iterrows():
        print(f"{r.design:>22} {r.included_execution/1e6:10.1f}M {r.state_gas/1e6:10.1f}M "
              f"{r.fee_sd:12.4f} {r.limit_hit_fraction:11.4f}")
    print(f"\nwrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
