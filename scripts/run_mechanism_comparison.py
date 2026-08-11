"""Part C: selected EIP-7999 configurations against Glamsterdam, metric by metric.

Part A sweeps the (T_E, T_D) grid; this takes three configurations off that grid
and runs them beside Glamsterdam on identical shock draws, reporting one common
metric set for all four.

Candidate selection is a rule rather than a judgement call. At each tolerance
for data-limit pressure, the candidate is the design delivering the most
execution *among those that actually clear their own target* (fill >= 0.99).
Ranking on delivered gas alone picks targets the data side cannot support, which
deliver more gas while pricing execution at its one-wei floor in almost every
block -- throughput that is permitted rather than priced.

Comparison is on effective activity prices, not base fees. Under EIP-7999 an
execution unit pays m_E b_E + wbar_E b_D and a state unit pays m_S b_S + w_S b_D,
so both carry the data fee through their BAL charge; under Glamsterdam all three
are fixed multiples of one shared fee. Raw base fees price different gas units
across the two mechanisms and are not comparable; these prices are.

The same latent workload (s_E, s_D, s_S, a) drives both mechanisms. Identical
shocks do not mean identical metered gas: the access shock moves priced data gas
under EIP-7999 and only unpriced payload under Glamsterdam, which is the
metering difference under test rather than an inconsistency.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import RESOURCES, BatchConfig, run_batch  # noqa: E402
from dynamics.glamsterdam_replay import (  # noqa: E402
    GlamsterdamConfig, run_glamsterdam_batch,
)
from dynamics.empirical_shocks import (  # noqa: E402
    DEFAULT_BLOCK_LENGTH, build_shock_panel, moving_block_bootstrap,
)
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

BLOCKS_PER_DAY = 7_200
BURN_IN = BLOCKS_PER_DAY
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 32
STATE_TARGET = 75_000_000.0
DATA_LIMIT = 90e6
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}

GLAMSTERDAM_CENTRAL_LIMIT = 200e6
MIN_FILL = 0.99
CANDIDATE_TOLERANCES = (("conservative", 0.01), ("central", 0.05), ("aggressive", 0.25))

# Representative bundles in historical gas-equivalent units, so the mechanisms
# are compared on what a user pays rather than on base fees that price
# different gas units.
BUNDLES = {
    "execution_heavy": {"execution": 200_000.0, "data": 2_000.0, "state": 0.0},
    "data_heavy":      {"execution": 40_000.0, "data": 100_000.0, "state": 0.0},
    "state_creating":  {"execution": 80_000.0, "data": 3_000.0, "state": 40_000.0},
    "mixed":           {"execution": 120_000.0, "data": 20_000.0, "state": 10_000.0},
}


def select_candidates(surface: pd.DataFrame) -> list[tuple[str, float, float]]:
    """Most execution deliverable at each tolerance, among designs that clear."""

    grid = surface[(surface.data_limit == DATA_LIMIT) & (surface.execution_fill >= MIN_FILL)]
    chosen = []
    for label, tolerance in CANDIDATE_TOLERANCES:
        ok = grid[grid.data_limit_hit_fraction <= tolerance]
        if not len(ok):
            raise SystemExit(f"no design clears its target at {tolerance:.0%} hits")
        best = ok.loc[ok.included_execution.idxmax()]
        chosen.append((label, float(best.execution_target), float(best.data_target)))
    return chosen


def bundle_costs(prices: dict[str, float]) -> dict[str, float]:
    """Cost of each representative bundle at the given effective unit prices."""

    return {
        f"cost_{name}": sum(prices[r] * amount for r, amount in bundle.items())
        for name, bundle in BUNDLES.items()
    }


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    glam = pd.read_csv(ROOT / "data/glamsterdam/equilibrium_anchor.csv").iloc[0]
    surface = pd.read_csv(ROOT / "data/7999/design_surface.csv")

    candidates = select_candidates(surface)
    print("candidates selected from the Part A grid "
          f"(most execution at each tolerance, fill >= {MIN_FILL:.2f}):\n")
    for label, execution_target, data_target in candidates:
        print(f"  {label:>12}  T_E {execution_target/1e6:5.0f}M  T_D {data_target/1e6:5.1f}M "
              f"  ratio {data_target/DATA_LIMIT:.3f}")

    panel = build_shock_panel(
        ROOT / "data/contiguous/contiguous_block_panel_2026-05-18_14d.csv",
        [ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv"],
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv",
    )
    shocks = moving_block_bootstrap(
        panel, N_SEEDS, MEASURE_BLOCKS + BURN_IN, DEFAULT_BLOCK_LENGTH,
        np.random.default_rng(20260814),
    )

    n = len(candidates)
    repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
    ones = np.ones(n * N_SEEDS)
    cfg = BatchConfig(
        execution_target=repeat([c[1] for c in candidates]),
        execution_limit=repeat([2.0 * c[1] for c in candidates]),
        data_target=repeat([c[2] for c in candidates]),
        data_limit=ones * DATA_LIMIT, state_target=ones * STATE_TARGET,
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
    seven999 = run_batch(cfg, shocks, bundle_cost_equivalent_start(cfg), burn_in=BURN_IN)

    glam_cfg = GlamsterdamConfig(
        gas_target=np.full(N_SEEDS, GLAMSTERDAM_CENTRAL_LIMIT / 2.0),
        gas_limit=np.full(N_SEEDS, GLAMSTERDAM_CENTRAL_LIMIT),
        eps_execution=np.full(N_SEEDS, EPS["execution"]),
        eps_data=np.full(N_SEEDS, EPS["data"]),
        eps_state=np.full(N_SEEDS, EPS["state"]),
        m_execution=float(glam.m_execution), m_data=float(glam.m_data),
        m_state=float(glam.m_state),
        w_execution=float(demand.w_execution_reference),
        w_state=float(demand.w_state_reference),
        q_execution_0=float(glam.q_execution_per_block),
        q_data_0=float(glam.q_data_per_block),
        q_state_0=float(glam.q_state_per_block),
        p0_gwei=float(glam.base_fee_ref_gwei),
    )
    glamsterdam = run_glamsterdam_batch(
        glam_cfg, shocks, np.full(N_SEEDS, float(glam.base_fee_ref_wei)), burn_in=BURN_IN
    )

    rows = []
    for i, (label, execution_target, data_target) in enumerate(candidates):
        sl = slice(i * N_SEEDS, (i + 1) * N_SEEDS)
        mean_fee = seven999["mean_fee_wei"][sl].mean(axis=0)
        prices = {
            "execution": float(demand.m_execution) * mean_fee[0]
                         + float(demand.w_execution_reference) * mean_fee[1],
            "data": float(anchor.static_data_metering_multiplier) * mean_fee[1],
            "state": float(demand.m_state) * mean_fee[2]
                     + float(demand.w_state_reference) * mean_fee[1],
        }
        row = {
            "mechanism": "eip7999", "configuration": label,
            "design": f"E{execution_target/1e6:.0f}_D{data_target/1e6:.0f}",
            "execution_target": execution_target, "data_target": data_target,
            "gas_limit": np.nan,
            "included_execution": float(seven999["mean_used"][sl, 0].mean()),
            "execution_fill": float(seven999["mean_used"][sl, 0].mean() / execution_target),
            "state_gas": float(seven999["mean_used"][sl, 2].mean()),
            "bal_payload": np.nan,
            "any_limit_hit_fraction": float(
                np.maximum(seven999["limit_hit_fraction"][sl, 0],
                           seven999["limit_hit_fraction"][sl, 1]).mean()
            ),
            "rationed_execution": float(seven999["mean_rationed"][sl, 0].mean()),
            "rationed_data": float(seven999["mean_rationed"][sl, 1].mean()),
            "shared_fee_wei": np.nan, "shared_fee_sd": np.nan,
            "regular_binding_fraction": np.nan,
            "execution_per_state": float(
                seven999["mean_used"][sl, 0].mean() / seven999["mean_used"][sl, 2].mean()
            ),
            **bundle_costs(prices),
        }
        for j, resource in enumerate(RESOURCES):
            row[f"{resource}_price_sd"] = float(
                seven999["effective_price_log_return_sd"][sl, j].mean())
            row[f"{resource}_price_p99"] = float(
                seven999["effective_price_log_return_p99"][sl, j].mean())
            row[f"{resource}_floor_fraction"] = float(
                seven999["floor_fraction"][sl, j].mean())
        rows.append(row)

    shared = float(glamsterdam["mean_fee_wei"][:, 0].mean())
    glam_prices = {"execution": float(glam.m_execution) * shared,
                   "data": float(glam.m_data) * shared,
                   "state": float(glam.m_state) * shared}
    row = {
        "mechanism": "glamsterdam", "configuration": "central",
        "design": f"G{GLAMSTERDAM_CENTRAL_LIMIT/1e6:.0f}M",
        "execution_target": np.nan, "data_target": np.nan,
        "gas_limit": GLAMSTERDAM_CENTRAL_LIMIT,
        "included_execution": float(glamsterdam["mean_included_execution"].mean()),
        "execution_fill": np.nan,
        "state_gas": float(glamsterdam["mean_used"][:, 2].mean()),
        "bal_payload": float(glamsterdam["mean_bal_payload"].mean()),
        "any_limit_hit_fraction": float(glamsterdam["limit_hit_fraction"][:, 1].mean()),
        "rationed_execution": np.nan,
        "rationed_data": float(glamsterdam["mean_rationed"][:, 1].mean()),
        "shared_fee_wei": shared,
        "shared_fee_sd": float(glamsterdam["log_return_sd"][:, 0].mean()),
        "regular_binding_fraction": float(glamsterdam["regular_binding_fraction"].mean()),
        "execution_per_state": float(
            glamsterdam["mean_included_execution"].mean()
            / glamsterdam["mean_used"][:, 2].mean()
        ),
        **bundle_costs(glam_prices),
    }
    for j, resource in enumerate(RESOURCES):
        row[f"{resource}_price_sd"] = float(
            glamsterdam["effective_price_log_return_sd"][:, j].mean())
        row[f"{resource}_price_p99"] = float(
            glamsterdam["effective_price_log_return_p99"][:, j].mean())
        row[f"{resource}_floor_fraction"] = float(glamsterdam["floor_fraction"][:, j].mean())
    rows.append(row)

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/mechanism_comparison.csv"
    results.to_csv(out_path, index=False)

    labels = [f"{r.mechanism.replace('eip7999', '7999')} {r.design}" for _, r in results.iterrows()]
    def line(title, values, fmt):
        print(f"{title:<34}" + "".join(f"{format(v, fmt) if v == v else 'n/a':>16}"
                                       for v in values))
    print("\n" + "=" * 34 + "".join(f"{name:>16}" for name in labels))
    line("delivered execution (M)", results.included_execution / 1e6, ".1f")
    line("execution fill", results.execution_fill, ".3f")
    line("state gas (M)", results.state_gas / 1e6, ".1f")
    line("execution per unit state", results.execution_per_state, ".2f")
    line("any hard-limit hit", results.any_limit_hit_fraction, ".3f")
    line("rationed data (M)", results.rationed_data / 1e6, ".2f")
    print()
    for resource in RESOURCES:
        line(f"{resource} price sd", results[f"{resource}_price_sd"], ".4f")
    for resource in RESOURCES:
        line(f"{resource} price p99", results[f"{resource}_price_p99"], ".3f")
    print()
    for resource in RESOURCES:
        line(f"{resource} fee at floor", results[f"{resource}_floor_fraction"], ".3f")
    print()
    # Absolute levels, in gwei per bundle. A ratio against Glamsterdam is not
    # readable here: these EIP-7999 configurations carry three to four times the
    # total block capacity, so execution clears at single-digit wei and the ratio
    # rounds to zero. The levels show what is actually happening -- execution
    # becomes nearly free while state creation becomes markedly dearer.
    for name in BUNDLES:
        line(f"cost, {name} (gwei)", results[f"cost_{name}"] / 1e9, ".3f")
    print(f"\nwrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
