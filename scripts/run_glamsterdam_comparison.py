"""Compare Glamsterdam and full EIP-7999 under one latent workload.

Nominal capacity is not directly comparable: Glamsterdam has a single gas limit
covering execution and data together, while EIP-7999 gives each resource its
own target and limit, and the two meter data differently (1.969 against 1.807).
Matching a "same execution target" would therefore compare different amounts of
total capacity.

The comparison is matched on realised throughput instead. For each EIP-7999
design, the Glamsterdam gas limit is solved so that mean included execution
matches, and the mechanisms are then compared on fee volatility, congestion and
representative user cost at equal delivered execution.

Both mechanisms see identical shock paths from the same seeds. The access
shock changes BAL payload in both worlds but enters fee-controlled gas only
under EIP-7999, where BAL is a priced resource.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

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

DESIGNS = [
    ("E200_D45_fixed90M", 200e6, 45e6, 90e6),
    ("E300_D77_fixed90M", 300e6, 77e6, 90e6),
    ("E300_D77_matched2x", 300e6, 77e6, 154e6),
]

# Representative transaction bundles, in historical gas-equivalent units, used
# so the mechanisms are compared on what a user pays rather than on base fees
# that price different gas units.
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


def bundle_costs(fees_wei, multipliers):
    """Cost of each representative bundle, in wei, given effective prices."""

    return {
        name: sum(multipliers[r] * fees_wei[r] * amount for r, amount in bundle.items())
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

    rows = []
    for design in DESIGNS:
        name, execution_target, data_target, data_limit = design
        cfg = seven999_config(design, N_SEEDS, demand, anchor)
        out7999 = run_batch(cfg, shocks, bundle_cost_equivalent_start(cfg), burn_in=BURN_IN)
        target_execution = float(out7999["mean_used"][:, 0].mean())

        # Solve the Glamsterdam gas limit that delivers the same mean included
        # execution under identical shocks.
        def gap(gas_limit: float) -> float:
            gcfg = glamsterdam_config(gas_limit, N_SEEDS, glam)
            start = np.full(N_SEEDS, float(glam.base_fee_ref_wei))
            got = run_glamsterdam_batch(gcfg, shocks, start, burn_in=BURN_IN)
            return float(got["mean_included_execution"].mean()) - target_execution

        # Glamsterdam's execution throughput saturates: as capacity rises the
        # shared fee falls, state demand expands fastest of the three, and the
        # state branch pins the fee. Matching EIP-7999's execution can therefore
        # require an implausible gas limit, or be unreachable entirely. The
        # required limit is itself the comparison result, so the bracket is
        # widened rather than the solve being abandoned.
        MAX_TESTED_LIMIT = 40_000e6
        if gap(MAX_TESTED_LIMIT) < 0:
            gas_limit = float("nan")
        else:
            gas_limit = brentq(gap, 60e6, MAX_TESTED_LIMIT, xtol=1e5, rtol=1e-8)
        reference_limit = gas_limit if np.isfinite(gas_limit) else MAX_TESTED_LIMIT
        gcfg = glamsterdam_config(reference_limit, N_SEEDS, glam)
        outglam = run_glamsterdam_batch(
            gcfg, shocks, np.full(N_SEEDS, float(glam.base_fee_ref_wei)), burn_in=BURN_IN
        )

        fees7999 = {
            "execution": out7999["mean_fee_wei"][:, 0].mean(),
            "data": out7999["mean_fee_wei"][:, 1].mean(),
            "state": out7999["mean_fee_wei"][:, 2].mean(),
        }
        shared = outglam["mean_fee_wei"][:, 0].mean()
        cost7999 = bundle_costs(fees7999, {
            "execution": float(demand.m_execution),
            "data": float(anchor.static_data_metering_multiplier),
            "state": float(demand.m_state)})
        costglam = bundle_costs({r: shared for r in ("execution", "data", "state")}, {
            "execution": float(glam.m_execution), "data": float(glam.m_data),
            "state": float(glam.m_state)})

        rows.append({
            "design": name, "matched_execution_gas": target_execution,
            "glamsterdam_gas_limit": gas_limit,
            "glamsterdam_gas_target": gas_limit / 2.0,
            "regular_binding_fraction": float(outglam["regular_binding_fraction"].mean()),
            "fee_sd_7999_execution": float(out7999["log_return_sd"][:, 0].mean()),
            "fee_sd_7999_data": float(out7999["log_return_sd"][:, 1].mean()),
            "fee_sd_glamsterdam": float(outglam["log_return_sd"][:, 0].mean()),
            "limit_hit_7999_data": float(out7999["limit_hit_fraction"][:, 1].mean()),
            "limit_hit_glamsterdam": float(outglam["limit_hit_fraction"][:, 1].mean()),
            "rationed_7999_data": float(out7999["mean_rationed"][:, 1].mean()),
            "rationed_glamsterdam": float(outglam["mean_rationed"][:, 1].mean()),
            **{f"cost7999_{k}": v for k, v in cost7999.items()},
            **{f"costglam_{k}": v for k, v in costglam.items()},
        })
        delivered = float(outglam["mean_included_execution"].mean())
        rows[-1]["glamsterdam_delivered_execution"] = delivered
        rows[-1]["matched"] = bool(np.isfinite(gas_limit))
        limit_text = (f"{gas_limit/1e6:8.0f}M" if np.isfinite(gas_limit)
                      else f"unreachable below {MAX_TESTED_LIMIT/1e6:.0f}M")
        print(f"  {name:22s} EIP-7999 execution {target_execution/1e6:6.1f}M  "
              f"-> Glamsterdam limit {limit_text}  (delivers {delivered/1e6:6.1f}M)")

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/glamsterdam_comparison.csv"
    results.to_csv(out_path, index=False)
    print(f"\nwrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
