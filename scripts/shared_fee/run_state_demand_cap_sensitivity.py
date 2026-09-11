"""Replay the largest safe shared-fee settings under state-demand saturation.

The cap applies only to price-driven state expansion. Empirical state shocks
continue to move realised block demand around the capped baseline. Every cap
and propagation setting receives the same canonical 32 multiscale paths.
"""

from __future__ import annotations

from dataclasses import replace
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT / "scripts", ROOT / "scripts/shared_fee"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_multiscale_design_surface import (  # noqa: E402
    BURN_IN,
    EPS,
    MEASURE_BLOCKS,
    N_SEEDS,
    build_canonical_workload,
)
from shared_fee.equilibrium import solve_shared_fee_equilibrium  # noqa: E402
from shared_fee.replay import SharedFeeConfig, run_shared_fee_batch  # noqa: E402
from run_shared_fee_scenarios import (  # noqa: E402
    OUT,
    PROPAGATION_TIMES,
    anchor_from_row,
    safe_limits,
)


CAP_MULTIPLES = (2.0, 3.0, 4.0, 5.0, float("inf"))


def add_distribution(row: dict, name: str, values: np.ndarray) -> None:
    values = np.asarray(values, dtype=float)
    row[name] = float(values.mean())
    row[f"{name}_p05"] = float(np.quantile(values, 0.05))
    row[f"{name}_p95"] = float(np.quantile(values, 0.95))


def cap_label(cap: float) -> str:
    return "unrestricted" if np.isinf(cap) else f"{cap:g}x"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    anchors_by_rate = pd.read_csv(
        OUT / "equilibrium_anchor_by_floor_rate.csv"
    ).set_index("floor_rate")
    demand = pd.read_csv(
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
    ).iloc[0]
    workload = build_canonical_workload().paths
    if workload.shape != (N_SEEDS, BURN_IN + MEASURE_BLOCKS, 4):
        raise AssertionError(f"unexpected workload shape: {workload.shape}")

    rows: list[dict] = []
    path_rows: list[dict] = []
    for propagation_time in PROPAGATION_TIMES:
        physical = safe_limits(propagation_time)
        floor_rate = int(physical["floor_rate"])
        anchor_row = anchors_by_rate.loc[floor_rate]
        base_anchor = anchor_from_row(anchor_row, m_data=float(anchor_row.m_data))
        limit = float(physical["safe_common_limit"])
        target = limit / 2.0
        anchors = [
            replace(base_anchor, state_demand_cap_multiple=cap)
            for cap in CAP_MULTIPLES
        ]
        equilibria = [
            solve_shared_fee_equilibrium(target, anchor) for anchor in anchors
        ]

        repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
        config = SharedFeeConfig(
            gas_target=np.full(len(CAP_MULTIPLES) * N_SEEDS, target),
            gas_limit=np.full(len(CAP_MULTIPLES) * N_SEEDS, limit),
            eps_execution=np.full(len(CAP_MULTIPLES) * N_SEEDS, EPS["execution"]),
            eps_data=np.full(len(CAP_MULTIPLES) * N_SEEDS, EPS["data"]),
            eps_state=np.full(len(CAP_MULTIPLES) * N_SEEDS, EPS["state"]),
            m_execution=base_anchor.m_execution,
            m_data=base_anchor.m_data,
            m_state=base_anchor.m_state,
            q_execution_0=base_anchor.q_execution,
            q_data_0=base_anchor.q_data,
            q_state_0=base_anchor.q_state,
            p0_gwei=base_anchor.reference_fee_gwei,
            w_execution=float(demand.w_execution_reference),
            w_state=float(demand.w_state_reference),
            state_demand_cap_multiple=repeat(CAP_MULTIPLES),
        )
        initial = repeat([equilibrium.base_fee_wei for equilibrium in equilibria])
        result = run_shared_fee_batch(config, workload, initial, burn_in=BURN_IN)

        for cap_index, (cap, equilibrium) in enumerate(
            zip(CAP_MULTIPLES, equilibria, strict=True)
        ):
            selection = slice(cap_index * N_SEEDS, (cap_index + 1) * N_SEEDS)
            row = {
                "mechanism": "shared_fee_8131_8279",
                "workload": "full_multiscale_60d",
                "propagation_time_s": propagation_time,
                "execution_time_s": 9.0 - propagation_time,
                "floor_rate": floor_rate,
                "m_data": base_anchor.m_data,
                "safe_common_limit": limit,
                "shared_target": target,
                "state_demand_cap_multiple": cap,
                "state_demand_cap_label": cap_label(cap),
                "n_replications": N_SEEDS,
                "burn_in_blocks": BURN_IN,
                "measured_blocks": MEASURE_BLOCKS,
                "equilibrium_fee_wei": equilibrium.base_fee_wei,
                "equilibrium_binding_branch": equilibrium.binding_branch,
                "equilibrium_state_demand_cap_active": (
                    equilibrium.state_demand_cap_active
                ),
                "equilibrium_execution_gas": equilibrium.execution_gas,
                "equilibrium_data_gas": equilibrium.data_gas,
                "equilibrium_regular_gas": equilibrium.regular_gas,
                "equilibrium_state_gas": equilibrium.state_gas,
                "equilibrium_state_activity_multiple": (
                    equilibrium.state_gas
                    / (base_anchor.m_state * base_anchor.q_state)
                ),
            }
            metrics = (
                ("included_execution_metered", result["mean_included_execution"][selection]),
                ("included_data_metered", result["mean_included_data"][selection]),
                ("included_state_metered", result["mean_included_state"][selection]),
                ("shared_gas_used", result["mean_used"][selection, 1]),
                (
                    "shared_target_utilisation",
                    result["mean_used"][selection, 1] / target,
                ),
                ("shared_fee_wei", result["mean_fee_wei"][selection, 1]),
                ("shared_fee_log_return_sd", result["log_return_sd"][selection, 1]),
                (
                    "shared_limit_hit_fraction",
                    result["included_limit_fraction"][selection, 1],
                ),
                (
                    "shared_fee_floor_bounded_fraction",
                    result["floor_downward_pressure_fraction"][selection, 1],
                ),
                (
                    "shared_target_deviation",
                    result["mean_absolute_target_deviation"][selection, 1],
                ),
                ("regular_binding_fraction", result["regular_binding_fraction"][selection]),
                (
                    "state_demand_cap_active_fraction",
                    result["state_demand_cap_active_fraction"][selection],
                ),
            )
            for name, values in metrics:
                add_distribution(row, name, values)
            rows.append(row)

            for replication in range(N_SEEDS):
                path_row = {
                    "propagation_time_s": propagation_time,
                    "state_demand_cap_multiple": cap,
                    "state_demand_cap_label": cap_label(cap),
                    "replication": replication,
                }
                for name, values in metrics:
                    path_row[name] = float(values[replication])
                path_rows.append(path_row)

        print(
            f"{propagation_time:.1f}s: {len(CAP_MULTIPLES)} state-demand cases at "
            f"the {limit / 1e6:.1f}M safe limit",
            flush=True,
        )

    output = pd.DataFrame(rows).sort_values(
        ["propagation_time_s", "state_demand_cap_multiple"]
    )
    paths = pd.DataFrame(path_rows).sort_values(
        ["propagation_time_s", "state_demand_cap_multiple", "replication"]
    )
    if len(output) != len(PROPAGATION_TIMES) * len(CAP_MULTIPLES):
        raise AssertionError("state-demand cap sensitivity is incomplete")
    if len(paths) != len(output) * N_SEEDS:
        raise AssertionError("path output does not reconcile to aggregate rows")

    central = pd.read_csv(OUT / "shared_fee_8279_slot_scenarios.csv")
    central = central[np.isclose(central.shared_limit, central.safe_common_limit)]
    unrestricted = output[np.isinf(output.state_demand_cap_multiple)]
    merged = unrestricted.merge(
        central,
        on="propagation_time_s",
        suffixes=("_cap", "_central"),
        validate="one_to_one",
    )
    for column in (
        "included_execution_metered",
        "included_data_metered",
        "included_state_metered",
        "shared_limit_hit_fraction",
        "shared_fee_wei",
    ):
        if not np.allclose(
            merged[f"{column}_cap"], merged[f"{column}_central"], rtol=1e-12
        ):
            raise AssertionError(f"unrestricted replay no longer matches {column}")

    output.to_csv(OUT / "shared_fee_8279_state_cap_sensitivity.csv", index=False)
    paths.to_csv(OUT / "shared_fee_8279_state_cap_sensitivity_paths.csv", index=False)
    print(f"wrote {len(output)} cap scenarios and {len(paths)} path rows")


if __name__ == "__main__":
    main()
