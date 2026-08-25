"""Part C: selected EIP-7999 configurations against Glamsterdam, metric by metric.

Part A sweeps the (T_E, T_D) grid; this takes four illustrative operating points
from that design space and runs them beside Glamsterdam on identical shock draws.
They are not pass/fail selections. They span a low-data-target case, the central
E225/D45 case, a higher-throughput case, and an intentionally data-constrained
E300/D80 saturation case.

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
from run_multiscale_design_surface import build_canonical_workload  # noqa: E402
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

BLOCKS_PER_DAY = 7_200
BURN_IN = BLOCKS_PER_DAY
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 32
STATE_TARGET = 75_000_000.0
DATA_LIMIT = 90e6
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}
REPORT_SHOCK_SEED = 20260814

GLAMSTERDAM_CENTRAL_LIMIT = 200e6
OPERATING_POINTS = (
    # Static reserve-free equilibrium base fees (execution, data, state), in
    # wei per gas, from notebook 7999_equilibrium/03. Keeping them beside the
    # operating-point definitions makes the dynamic equilibrium-distance
    # diagnostic reproducible and prevents a table-only reference from drifting.
    ("conservative", 200e6, 36e6,
     (10.844102681588879, 1058.8795825234265, 1184463.3567844462)),
    ("central", 225e6, 45e6,
     (6.976963624698781, 338.2968986354443, 1184468.66853208)),
    ("aggressive", 250e6, 60e6,
     (5.9390753710562905, 76.50318194784771, 1184470.5983344272)),
    ("saturation", 300e6, 80e6,
     (1.2053387962943836, 19.445961938646366, 1184471.0189295374)),
)

# Representative bundles in historical gas-equivalent units, so the mechanisms
# are compared on what a user pays rather than on base fees that price
# different gas units.
BUNDLES = {
    "execution_heavy": {"execution": 200_000.0, "data": 2_000.0, "state": 0.0},
    "data_heavy":      {"execution": 40_000.0, "data": 100_000.0, "state": 0.0},
    "state_creating":  {"execution": 80_000.0, "data": 3_000.0, "state": 40_000.0},
    "mixed":           {"execution": 120_000.0, "data": 20_000.0, "state": 10_000.0},
}


def bundle_costs(prices: dict[str, float]) -> dict[str, float]:
    """Cost of each representative bundle at the given effective unit prices."""

    return {
        f"cost_{name}": sum(prices[r] * amount for r, amount in bundle.items())
        for name, bundle in BUNDLES.items()
    }


def add_interval(row: dict, name: str, values: np.ndarray) -> None:
    """Add a path mean and central 90% interval to one result row."""

    values = np.asarray(values, dtype=float)
    row[name] = float(values.mean())
    row[f"{name}_p05"] = float(np.quantile(values, 0.05))
    row[f"{name}_p95"] = float(np.quantile(values, 0.95))


def equilibrium_level_metrics(
    result: dict[str, np.ndarray], path_slice: slice,
    reference_effective_prices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-path effective-price distance and signed level relative to equilibrium.

    The first output is the root mean square of log(P_t / P*). Unlike a standard
    deviation, it retains persistent displacement from the equilibrium level.
    The second is the geometric-mean price ratio exp(mean(log(P_t / P*))), which
    records whether that displacement is predominantly above or below equilibrium.
    """

    mean_log = result["effective_price_mean_log_level"][path_slice]
    mean_square_log = result["effective_price_mean_square_log_level"][path_slice]
    log_reference = np.log(np.asarray(reference_effective_prices, dtype=float))[None, :]
    mean_square_distance = (
        mean_square_log - 2.0 * log_reference * mean_log + log_reference**2
    )
    log_rmse = np.sqrt(np.maximum(mean_square_distance, 0.0))
    geometric_mean_ratio = np.exp(mean_log - log_reference)
    return log_rmse, geometric_mean_ratio


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    glam = pd.read_csv(ROOT / "data/glamsterdam/equilibrium_anchor.csv").iloc[0]
    candidates = list(OPERATING_POINTS)
    print("illustrative operating points (no execution-fill cutoff):\n")
    for label, execution_target, data_target, _ in candidates:
        print(f"  {label:>12}  T_E {execution_target/1e6:5.0f}M  T_D {data_target/1e6:5.1f}M "
              f"  ratio {data_target/DATA_LIMIT:.3f}")

    shocks = build_canonical_workload().paths

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
    seven999 = run_batch(
        cfg, shocks, bundle_cost_equivalent_start(cfg), burn_in=BURN_IN,
        bundle_consistent=True,
    )
    # Diagnostic upper comparison: cap each gas counter independently. This can
    # keep execution while discarding the BAL it generated, so it is not a
    # feasible packing rule. The gap quantifies how much delivered execution is
    # lost when transaction bundles are kept internally consistent.
    independent_caps = run_batch(
        cfg, shocks, bundle_cost_equivalent_start(cfg), burn_in=BURN_IN,
        bundle_consistent=False,
    )

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
    for i, (label, execution_target, data_target, equilibrium_fees) in enumerate(candidates):
        sl = slice(i * N_SEEDS, (i + 1) * N_SEEDS)
        mean_fee = seven999["mean_fee_wei"][sl].mean(axis=0)
        execution_hits = float(seven999["included_limit_fraction"][sl, 0].mean())
        data_hits = float(seven999["included_limit_fraction"][sl, 1].mean())
        any_hits = float(seven999["any_limit_hit_fraction"][sl].mean())
        both_hits = max(execution_hits + data_hits - any_hits, 0.0)
        execution_pressure = float(
            seven999["offered_limit_pressure_fraction"][sl, 0].mean()
        )
        data_pressure = float(
            seven999["offered_limit_pressure_fraction"][sl, 1].mean()
        )
        cap_execution_only = float(
            seven999["execution_only_cap_active_fraction"][sl].mean()
        )
        cap_data_only = float(seven999["data_only_cap_active_fraction"][sl].mean())
        cap_both = float(seven999["both_caps_active_fraction"][sl].mean())
        prices = {
            "execution": float(demand.m_execution) * mean_fee[0]
                         + float(demand.w_execution_reference) * mean_fee[1],
            "data": float(anchor.static_data_metering_multiplier) * mean_fee[1],
            "state": float(demand.m_state) * mean_fee[2]
                     + float(demand.w_state_reference) * mean_fee[1],
        }
        equilibrium_fees = np.asarray(equilibrium_fees, dtype=float)
        equilibrium_prices = np.array([
            float(demand.m_execution) * equilibrium_fees[0]
            + float(demand.w_execution_reference) * equilibrium_fees[1],
            float(anchor.static_data_metering_multiplier) * equilibrium_fees[1],
            float(demand.m_state) * equilibrium_fees[2]
            + float(demand.w_state_reference) * equilibrium_fees[1],
        ])
        equilibrium_log_rmse, equilibrium_geomean_ratio = equilibrium_level_metrics(
            seven999, sl, equilibrium_prices,
        )
        row = {
            "mechanism": "eip7999", "configuration": label,
            "design": f"E{execution_target/1e6:.0f}_D{data_target/1e6:.0f}",
            "execution_target": execution_target, "data_target": data_target,
            "gas_limit": np.nan,
            "included_execution": float(seven999["mean_used"][sl, 0].mean()),
            "execution_fill": float(seven999["mean_used"][sl, 0].mean() / execution_target),
            "state_gas": float(seven999["mean_used"][sl, 2].mean()),
            "bal_payload": np.nan,
            "execution_limit_hit_fraction": execution_hits,
            "data_limit_hit_fraction": data_hits,
            "execution_offered_limit_pressure_fraction": execution_pressure,
            "data_offered_limit_pressure_fraction": data_pressure,
            "execution_only_included_limit_fraction": max(
                execution_hits - both_hits, 0.0
            ),
            "data_only_included_limit_fraction": max(data_hits - both_hits, 0.0),
            "both_included_limits_fraction": both_hits,
            "execution_only_cap_active_fraction": cap_execution_only,
            "data_only_cap_active_fraction": cap_data_only,
            "both_caps_active_fraction": cap_both,
            "execution_scale_determining_fraction": float(
                seven999["scale_determining_fraction"][sl, 0].mean()
            ),
            "data_scale_determining_fraction": float(
                seven999["scale_determining_fraction"][sl, 1].mean()
            ),
            "any_limit_hit_fraction": any_hits,
            "any_cap_active_fraction": cap_execution_only + cap_data_only + cap_both,
            "rationed_execution": float(seven999["mean_rationed"][sl, 0].mean()),
            "rationed_data": float(seven999["mean_rationed"][sl, 1].mean()),
            "independent_cap_execution": float(
                independent_caps["mean_used"][sl, 0].mean()
            ),
            "independent_cap_execution_fill": float(
                independent_caps["mean_used"][sl, 0].mean() / execution_target
            ),
            "independent_cap_rationed_data": float(
                independent_caps["mean_rationed"][sl, 1].mean()
            ),
            "shared_fee_wei": np.nan, "shared_fee_sd": np.nan,
            "equilibrium_shared_fee_wei": np.nan,
            "regular_binding_fraction": np.nan,
            "execution_per_state": float(
                seven999["mean_used"][sl, 0].mean() / seven999["mean_used"][sl, 2].mean()
            ),
            **bundle_costs(prices),
        }
        for j, resource in enumerate(RESOURCES):
            row[f"equilibrium_{resource}_base_fee_wei"] = equilibrium_fees[j]
            row[f"equilibrium_{resource}_effective_price_wei"] = equilibrium_prices[j]
            add_interval(
                row, f"{resource}_equilibrium_log_rmse",
                equilibrium_log_rmse[:, j],
            )
            add_interval(
                row, f"{resource}_equilibrium_geomean_ratio",
                equilibrium_geomean_ratio[:, j],
            )
        add_interval(row, "included_execution", seven999["mean_used"][sl, 0])
        add_interval(
            row, "execution_fill", seven999["mean_used"][sl, 0] / execution_target
        )
        add_interval(row, "state_gas", seven999["mean_used"][sl, 2])
        add_interval(
            row, "execution_per_state",
            seven999["mean_used"][sl, 0]
            / np.maximum(seven999["mean_used"][sl, 2], 1e-300),
        )
        add_interval(
            row, "execution_limit_hit_fraction_path",
            seven999["included_limit_fraction"][sl, 0],
        )
        add_interval(
            row, "data_limit_hit_fraction_path",
            seven999["included_limit_fraction"][sl, 1],
        )
        add_interval(row, "rationed_data", seven999["mean_rationed"][sl, 1])
        add_interval(
            row,
            "execution_floor_bounded_fraction",
            seven999["floor_downward_pressure_fraction"][sl, 0],
        )

        glam_execution = glamsterdam["mean_included_execution"]
        glam_state = glamsterdam["mean_used"][:, 2]
        eip_execution = seven999["mean_used"][sl, 0]
        eip_state = seven999["mean_used"][sl, 2]
        add_interval(row, "paired_execution_ratio_to_glamsterdam", eip_execution / glam_execution)
        add_interval(row, "paired_execution_difference", eip_execution - glam_execution)
        add_interval(row, "paired_state_difference", eip_state - glam_state)
        add_interval(row, "paired_state_reduction_fraction", 1.0 - eip_state / glam_state)
        for j, resource in enumerate(RESOURCES):
            add_interval(
                row, f"{resource}_price_sd",
                seven999["effective_price_log_return_sd"][sl, j],
            )
            row[f"{resource}_price_p99"] = float(
                seven999["effective_price_log_return_p99"][sl, j].mean())
            if resource != "execution":
                add_interval(
                    row, f"{resource}_floor_bounded_fraction",
                    seven999["floor_downward_pressure_fraction"][sl, j],
                )
        rows.append(row)

    shared = float(glamsterdam["mean_fee_wei"][:, 0].mean())
    glam_equilibrium = pd.read_csv(ROOT / "data/glamsterdam/equilibrium_results.csv")
    glam_equilibrium = glam_equilibrium[
        glam_equilibrium["window_days"].eq(35)
        & glam_equilibrium["gas_limit"].eq(GLAMSTERDAM_CENTRAL_LIMIT)
        & glam_equilibrium["demand_variant"].eq("uncapped_isoelastic")
    ]
    if len(glam_equilibrium) != 1:
        raise AssertionError("expected one central Glamsterdam equilibrium reference")
    equilibrium_shared_fee = float(
        glam_equilibrium.iloc[0]["equilibrium_base_fee_gwei"] * 1e9
    )
    glam_prices = {"execution": float(glam.m_execution) * shared,
                   "data": float(glam.m_data) * shared,
                   "state": float(glam.m_state) * shared}
    glam_equilibrium_prices = np.array([
        float(glam.m_execution) * equilibrium_shared_fee,
        float(glam.m_data) * equilibrium_shared_fee,
        float(glam.m_state) * equilibrium_shared_fee,
    ])
    glam_log_rmse, glam_geomean_ratio = equilibrium_level_metrics(
        glamsterdam, slice(None), glam_equilibrium_prices,
    )
    row = {
        "mechanism": "glamsterdam", "configuration": "central",
        "design": f"G{GLAMSTERDAM_CENTRAL_LIMIT/1e6:.0f}M",
        "execution_target": np.nan, "data_target": np.nan,
        "gas_limit": GLAMSTERDAM_CENTRAL_LIMIT,
        "included_execution": float(glamsterdam["mean_included_execution"].mean()),
        "execution_fill": np.nan,
        "state_gas": float(glamsterdam["mean_used"][:, 2].mean()),
        "bal_payload": float(glamsterdam["mean_bal_payload"].mean()),
        "execution_limit_hit_fraction": np.nan,
        "data_limit_hit_fraction": np.nan,
        "execution_offered_limit_pressure_fraction": np.nan,
        "data_offered_limit_pressure_fraction": np.nan,
        "execution_only_included_limit_fraction": np.nan,
        "data_only_included_limit_fraction": np.nan,
        "both_included_limits_fraction": np.nan,
        "execution_only_cap_active_fraction": np.nan,
        "data_only_cap_active_fraction": np.nan,
        "both_caps_active_fraction": np.nan,
        "execution_scale_determining_fraction": np.nan,
        "data_scale_determining_fraction": np.nan,
        "any_limit_hit_fraction": float(glamsterdam["any_limit_hit_fraction"].mean()),
        "any_cap_active_fraction": float(glamsterdam["any_limit_hit_fraction"].mean()),
        "rationed_execution": float(glamsterdam["mean_rationed_execution"].mean()),
        "rationed_data": float(glamsterdam["mean_rationed_data"].mean()),
        "independent_cap_execution": np.nan,
        "independent_cap_execution_fill": np.nan,
        "independent_cap_rationed_data": np.nan,
        "shared_fee_wei": shared,
        "equilibrium_shared_fee_wei": equilibrium_shared_fee,
        "shared_fee_sd": float(glamsterdam["log_return_sd"][:, 0].mean()),
        "regular_binding_fraction": float(glamsterdam["regular_binding_fraction"].mean()),
        "shared_fee_below_8_wei_fraction": float(
            glamsterdam["sub_eight_fee_fraction"].mean()
        ),
        "execution_per_state": float(
            glamsterdam["mean_included_execution"].mean()
            / glamsterdam["mean_used"][:, 2].mean()
        ),
        **bundle_costs(glam_prices),
    }
    for j, resource in enumerate(RESOURCES):
        row[f"equilibrium_{resource}_base_fee_wei"] = equilibrium_shared_fee
        row[f"equilibrium_{resource}_effective_price_wei"] = glam_equilibrium_prices[j]
        add_interval(
            row, f"{resource}_equilibrium_log_rmse", glam_log_rmse[:, j]
        )
        add_interval(
            row, f"{resource}_equilibrium_geomean_ratio",
            glam_geomean_ratio[:, j],
        )
    add_interval(row, "included_execution", glamsterdam["mean_included_execution"])
    add_interval(row, "state_gas", glamsterdam["mean_used"][:, 2])
    add_interval(
        row, "execution_per_state",
        glamsterdam["mean_included_execution"]
        / np.maximum(glamsterdam["mean_used"][:, 2], 1e-300),
    )
    add_interval(row, "rationed_data", glamsterdam["mean_rationed_data"])
    for j, resource in enumerate(RESOURCES):
        add_interval(
            row, f"{resource}_price_sd",
            glamsterdam["effective_price_log_return_sd"][:, j],
        )
        row[f"{resource}_price_p99"] = float(
            glamsterdam["effective_price_log_return_p99"][:, j].mean())
        # EIP-1559 has no explicit one-wei floor comparable to EIP-7999's.
        row[f"{resource}_floor_bounded_fraction"] = np.nan
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
    line("execution target utilization", results.execution_fill, ".3f")
    line("state gas (M)", results.state_gas / 1e6, ".1f")
    line("execution per unit state", results.execution_per_state, ".2f")
    line("execution-limit hit", results.execution_limit_hit_fraction, ".3f")
    line("data-limit hit", results.data_limit_hit_fraction, ".3f")
    line("either hard-limit hit", results.any_limit_hit_fraction, ".3f")
    line("rationed data (M)", results.rationed_data / 1e6, ".2f")
    print()
    for resource in RESOURCES:
        line(f"{resource} price sd", results[f"{resource}_price_sd"], ".4f")
    for resource in RESOURCES:
        line(f"{resource} price p99", results[f"{resource}_price_p99"], ".3f")
    print()
    for resource in RESOURCES:
        line(
            f"{resource} equilibrium log RMSE",
            results[f"{resource}_equilibrium_log_rmse"], ".3f",
        )
        line(
            f"{resource} geometric mean / eq.",
            results[f"{resource}_equilibrium_geomean_ratio"], ".3f",
        )
    print()
    line(
        "execution fee bounded at one wei",
        results["execution_floor_bounded_fraction"],
        ".3f",
    )
    print()
    # Absolute levels, in gwei per bundle. A ratio against Glamsterdam is not
    # readable here: these EIP-7999 configurations carry three to four times the
    # total block capacity, so execution clears at very low wei values and the
    # ratio rounds to zero. The levels show what is actually happening -- execution
    # becomes nearly free while state creation becomes markedly dearer.
    for name in BUNDLES:
        line(f"cost, {name} (gwei)", results[f"cost_{name}"] / 1e9, ".3f")
    print(f"\nwrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
