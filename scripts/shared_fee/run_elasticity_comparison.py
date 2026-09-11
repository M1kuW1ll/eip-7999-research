"""Matched-window shared-fee/EIP-7999 comparison, using frozen shock draws.

Run the two maximum-fit-limit shared-fee benchmarks at four elasticity windows.
Reproduce the existing window-specific EIP-7999 selections without changing
their source surfaces. All new outputs stay in data/shared_fee/.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "src", ROOT / "scripts", ROOT / "scripts/shared_fee"):
    sys.path.insert(0, str(directory))

from build_three_arm_comparison import central_7999_equilibrium_fees
from dynamics.batched_replay import bundle_cost_equivalent_start, run_batch
from run_multiscale_design_surface import (
    BURN_IN, MEASURE_BLOCKS, N_SEEDS, build_canonical_workload,
)
from run_slot_time_parameter_sensitivity import (
    build_config, selection_tables, specification_table,
)
from shared_fee.equilibrium import SharedFeeAnchor, solve_shared_fee_equilibrium
from shared_fee.optimization import BLOCKS_PER_YEAR, BYTES_PER_GIB
from shared_fee.replay import SharedFeeConfig, run_shared_fee_batch

OUT = ROOT / "data/shared_fee"
BENCHMARKS = ("proposal_faithful", "fully_optimized")
LABELS = {
    "proposal_faithful": "Proposal-faithful shared fee",
    "fully_optimized": "Floor- and state-growth-adjusted shared fee",
    "maximum": "EIP-7999 maximum throughput",
    "balanced": "EIP-7999 balanced (historically anchored)",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_metrics(row: dict, metrics: dict, paths: list[dict]) -> None:
    for name, values in metrics.items():
        values = np.asarray(values, dtype=float)
        if not np.isfinite(values).all():
            raise AssertionError(f"non-finite metric: {name}")
        row[name] = float(values.mean())
        row[name + "_p05"] = float(np.quantile(values, .05))
        row[name + "_p95"] = float(np.quantile(values, .95))
    for replication in range(N_SEEDS):
        paths.append({
            **{key: row[key] for key in (
                "benchmark", "window_days", "propagation_time_s", "configuration",
            )},
            "replication": replication,
            **{key: float(value[replication]) for key, value in metrics.items()},
        })


def shared_rows(specs, workload, demand):
    previous = pd.read_csv(OUT / "shared_fee_state_tail.csv")
    frontier = previous[previous.state_demand_cap_label.eq("unrestricted")]
    if len(frontier) != 10 or set(frontier.benchmark) != set(BENCHMARKS):
        raise AssertionError("expected two unrestricted benchmarks at five splits")
    base = pd.read_csv(OUT / "equilibrium_anchor_by_floor_rate.csv").iloc[0]
    if not np.isclose(base.m_execution, demand.m_execution, rtol=0, atol=1e-12):
        raise AssertionError("shared-fee and EIP-7999 execution multipliers differ")
    metadata, equilibria = [], []
    for source in frontier.itertuples():
        for spec in specs.itertuples():
            anchor = SharedFeeAnchor(
                q_execution=base.q_execution_per_block,
                q_data=base.q_data_per_block, q_state=base.q_state_per_block,
                m_execution=source.m_execution, m_data=source.m_data,
                m_state=source.m_state, reference_fee_gwei=base.base_fee_ref_gwei,
                eps_execution=spec.eps_execution, eps_data=spec.eps_data,
                eps_state=spec.eps_state,
            )
            equilibrium = solve_shared_fee_equilibrium(source.shared_target, anchor)
            if not equilibrium.floor_bounded:
                np.testing.assert_allclose(
                    equilibrium.offered_shared_gas, source.shared_target, rtol=1e-10,
                )
            equilibria.append(equilibrium)
            metadata.append({
                "benchmark": source.benchmark,
                "design_family": LABELS[source.benchmark],
                "window_days": spec.window_days,
                "propagation_time_s": source.propagation_time_s,
                "configuration": f"G{source.shared_limit / 1e6:.1f}",
                "available": True,
                "shared_limit": source.shared_limit,
                "shared_target": source.shared_target,
                "floor_rate": source.floor_rate, "cpsb": source.cpsb,
                "m_execution": source.m_execution, "m_data": source.m_data,
                "m_state": source.m_state,
                "eps_execution": spec.eps_execution, "eps_data": spec.eps_data,
                "eps_state": spec.eps_state,
                "equilibrium_execution_fee_wei": equilibrium.base_fee_wei,
                "equilibrium_data_fee_wei": equilibrium.base_fee_wei,
                "equilibrium_state_fee_wei": equilibrium.base_fee_wei,
                "equilibrium_binding_branch": equilibrium.binding_branch,
                "equilibrium_state_activity_multiple": equilibrium.state_gas / (
                    source.m_state * base.q_state_per_block
                ),
            })
    repeat = lambda key: np.repeat([row[key] for row in metadata], N_SEEDS)
    config = SharedFeeConfig(
        gas_target=repeat("shared_target"), gas_limit=repeat("shared_limit"),
        eps_execution=repeat("eps_execution"), eps_data=repeat("eps_data"),
        eps_state=repeat("eps_state"), m_execution=repeat("m_execution"),
        m_data=repeat("m_data"), m_state=repeat("m_state"),
        q_execution_0=base.q_execution_per_block, q_data_0=base.q_data_per_block,
        q_state_0=base.q_state_per_block, p0_gwei=base.base_fee_ref_gwei,
        w_execution=demand.w_execution_reference, w_state=demand.w_state_reference,
    )
    result = run_shared_fee_batch(
        config, workload, repeat("equilibrium_execution_fee_wei"), burn_in=BURN_IN,
    )
    paths = []
    for index, row in enumerate(metadata):
        ix = slice(index * N_SEEDS, (index + 1) * N_SEEDS)
        volatility = result["log_return_sd"][ix, 1]
        record_metrics(row, {
            "metered_execution_gas": result["mean_included_execution"][ix],
            "data_or_floor_gas": result["mean_included_data"][ix],
            "regular_gas": result["mean_included_regular"][ix],
            "state_gas": result["mean_included_state"][ix],
            "annualized_state_growth_gib": result["mean_included_state"][ix]
                / row["cpsb"] * BLOCKS_PER_YEAR / BYTES_PER_GIB,
            "hard_limit_fraction": result["included_limit_fraction"][ix, 1],
            "near_limit_fraction": result["near_limit_fraction"][ix, 1],
            "target_deviation": result["mean_absolute_target_deviation"][ix, 1],
            "execution_floor_bounded_fraction": result["floor_downward_pressure_fraction"][ix, 1],
            "execution_price_variation": volatility,
            "data_price_variation": volatility, "state_price_variation": volatility,
            "regular_binding_fraction": result["regular_binding_fraction"][ix],
            "base_fee_exposure_proxy_eth_per_block": result["mean_base_fee_exposure_proxy_wei"][ix] / 1e18,
        }, paths)
        if row["window_days"] == 35:
            old = frontier[(frontier.benchmark == row["benchmark"]) & (
                frontier.propagation_time_s == row["propagation_time_s"]
            )].iloc[0]
            for new, old_name in {
                "metered_execution_gas": "included_execution_metered",
                "state_gas": "included_state_metered",
                "hard_limit_fraction": "shared_limit_hit_fraction",
                "execution_price_variation": "shared_fee_log_return_sd",
            }.items():
                np.testing.assert_allclose(row[new], old[old_name], rtol=1e-12)
    return metadata, paths


def selected_7999_rows(specs, workload, demand, metering):
    surface = pd.read_csv(ROOT / "data/7999/slot_time_parameter_surface_one_at_a_time.csv")
    surface = surface[surface.lambda_bal.eq(0) & surface.rho_A.eq(1)]
    maximum, balanced = selection_tables(surface)
    specs_by_window = specs.set_index("window_days")
    combinations, rows, sources, missing = [], [], [], []
    for selection, selected in (("maximum", maximum), ("balanced", balanced)):
        for source in selected.itertuples():
            spec = specs_by_window.loc[source.window_days]
            row = {
                "benchmark": selection, "design_family": LABELS[selection],
                "window_days": source.window_days,
                "propagation_time_s": source.propagation_time_s,
                "lambda_bal": 0., "rho_A": 1., "cpsb": 1530.,
                "eps_execution": spec.eps_execution, "eps_data": spec.eps_data,
                "eps_state": spec.eps_state, "m_execution": demand.m_execution,
            }
            if selection == "balanced" and not source.balanced_available:
                missing.append({**row, "available": False,
                    "configuration": "No qualifying design in tested grid"})
                continue
            row.update({
                "available": True,
                "configuration": f"E{source.execution_target / 1e6:g}/D{source.data_target / 1e6:g}",
                "execution_target": source.execution_target, "data_target": source.data_target,
                "execution_limit": source.execution_limit, "data_limit": source.data_limit,
            })
            fees = central_7999_equilibrium_fees(
                source.execution_target, source.data_target, demand, metering, spec,
            )
            for resource, fee in zip(("execution", "data", "state"), fees, strict=True):
                row[f"equilibrium_{resource}_fee_wei"] = fee
            row["equilibrium_binding_branch"] = (
                "execution fee at minimum" if fees[0] == 1 else "all targets clear"
            )
            spec_index = specs.index[specs.window_days.eq(source.window_days)][0]
            combinations.append((spec_index, source.execution_target, source.data_target,
                                 source.execution_limit, source.data_limit))
            rows.append(row)
            sources.append(source)
    config = build_config(combinations, specs, demand, metering)
    # Keep the original EIP-7999 initialization for an exact reproduction check.
    result = run_batch(config, workload, bundle_cost_equivalent_start(config),
                       burn_in=BURN_IN, bundle_consistent=True)
    paths = []
    for index, (row, source) in enumerate(zip(rows, sources, strict=True)):
        ix = slice(index * N_SEEDS, (index + 1) * N_SEEDS)
        record_metrics(row, {
            "metered_execution_gas": result["mean_used"][ix, 0],
            "data_or_floor_gas": result["mean_used"][ix, 1],
            "state_gas": result["mean_used"][ix, 2],
            "annualized_state_growth_gib": result["mean_used"][ix, 2]
                / 1530 * BLOCKS_PER_YEAR / BYTES_PER_GIB,
            "hard_limit_fraction": result["any_limit_hit_fraction"][ix],
            "execution_limit_fraction": result["included_limit_fraction"][ix, 0],
            "data_limit_fraction": result["included_limit_fraction"][ix, 1],
            "near_limit_fraction": result["any_near_limit_fraction"][ix],
            "target_deviation": result["mean_absolute_target_deviation"][ix, 0],
            "execution_floor_bounded_fraction": result["floor_downward_pressure_fraction"][ix, 0],
            **{f"{resource}_price_variation": result["effective_price_log_return_sd"][ix, i]
               for i, resource in enumerate(("execution", "data", "state"))},
            "base_fee_exposure_proxy_eth_per_block": result["mean_total_burn_wei"][ix] / 1e18,
        }, paths)
        for new, old in {
            "metered_execution_gas": "included_execution",
            "hard_limit_fraction": "any_limit_hit_fraction",
            "state_gas": "state_used",
            "execution_price_variation": "execution_price_sd",
            "data_price_variation": "data_price_sd",
            "state_price_variation": "state_price_sd",
        }.items():
            np.testing.assert_allclose(row[new], getattr(source, old), rtol=1e-12)
    return rows + missing, paths


def main():
    started = time.monotonic()
    # All pre-existing numerical outputs and all cached shock inputs are read-only.
    source_paths = sorted((ROOT / "data/7999").glob("*.csv"))
    source_paths += sorted((ROOT / "data/glamsterdam").glob("*.csv"))
    source_paths += [OUT / name for name in (
        "shared_fee_state_tail.csv", "shared_fee_factorial_manifest.csv",
        "equilibrium_anchor_by_floor_rate.csv",
    )]
    source_paths += [ROOT / name for name in (
        "scripts/shared_fee/run_elasticity_comparison.py",
        "src/shared_fee/equilibrium.py", "src/shared_fee/replay.py",
        "src/dynamics/batched_replay.py", "src/dynamics/multiscale_shocks.py",
        "scripts/run_slot_time_parameter_sensitivity.py",
    )]
    original_hashes = {str(path.relative_to(ROOT)): sha256(path) for path in source_paths}
    specs = specification_table()
    specs = specs[specs.lambda_bal.eq(0) & specs.rho_A.eq(1)].reset_index(drop=True)
    if list(specs.window_days) != [21, 35, 60, 75]:
        raise AssertionError("elasticity window grid is incomplete")
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    metering = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    print("Building unchanged canonical 32-path workload from cached panels", flush=True)
    workload = build_canonical_workload().paths
    digest = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
    expected = pd.read_csv(OUT / "shared_fee_factorial_manifest.csv").iloc[0].workload_sha256
    if digest != expected or workload.shape != (N_SEEDS, BURN_IN + MEASURE_BLOCKS, 4):
        raise AssertionError("canonical shock paths changed")
    print("Replaying 40 shared-fee specifications", flush=True)
    shared, shared_paths = shared_rows(specs, workload, demand)
    print("Shared-fee central results reproduced; verifying selected EIP-7999 designs", flush=True)
    eip, eip_paths = selected_7999_rows(specs, workload, demand, metering)
    output = pd.DataFrame(shared + eip).sort_values(
        ["window_days", "propagation_time_s", "benchmark"])
    output["n_replications"] = N_SEEDS
    output["burn_in_blocks"] = BURN_IN
    output["measured_blocks"] = MEASURE_BLOCKS
    output["workload_sha256"] = digest
    if len(output) != 80 or int(output.available.sum()) != len(shared) + len(eip_paths) // N_SEEDS:
        raise AssertionError("comparison grid incomplete")
    for relative, original in original_hashes.items():
        if sha256(ROOT / relative) != original:
            raise AssertionError(f"protected source changed: {relative}")
    output.to_csv(OUT / "shared_fee_elasticity_comparison.csv", index=False)
    pd.DataFrame(shared_paths + eip_paths).to_csv(
        OUT / "shared_fee_elasticity_comparison_paths.csv", index=False)
    manifest = {
        "workload_sha256": digest, "shape": list(workload.shape),
        "windows": list(specs.window_days), "shared_specifications": len(shared),
        "eip7999_selections_available": len(eip_paths) // N_SEEDS,
        "elapsed_seconds": time.monotonic() - started,
        "central_shared_reproduction": "passed rtol=1e-12",
        "selected_7999_reproduction": "passed rtol=1e-12",
        "shock_construction": "unchanged 35-day conditional multiscale workload",
        "inputs_sha256": original_hashes,
    }
    (OUT / "shared_fee_elasticity_comparison_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")
    print(output[["window_days", "propagation_time_s", "benchmark", "configuration",
                  "metered_execution_gas", "annualized_state_growth_gib",
                  "hard_limit_fraction"]].to_string(index=False), flush=True)
    print(f"Completed in {time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
