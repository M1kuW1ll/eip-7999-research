"""State-demand-tail sensitivity for the two main shared-fee frontiers."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import sys
import time
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
from shared_fee.equilibrium import (  # noqa: E402
    SharedFeeAnchor,
    solve_shared_fee_equilibrium,
)
from shared_fee.replay import SharedFeeConfig, run_shared_fee_batch  # noqa: E402
from shared_fee.optimization import (  # noqa: E402
    BLOCKS_PER_YEAR,
    BYTES_PER_GIB,
    CPSB_REFERENCE,
)


OUT = ROOT / "data/shared_fee"


CAP_MULTIPLES = (1.5, 2.0, 3.0, 4.0, 5.0, float("inf"))
BENCHMARKS = ("proposal_faithful", "fully_optimized")
ROW_KEYS = ["benchmark", "propagation_time_s", "state_demand_cap_multiple"]


def label(cap: float) -> str:
    return "unrestricted" if np.isinf(cap) else f"{cap:g}x"


def add_distribution(row: dict, name: str, values: np.ndarray) -> None:
    values = np.asarray(values, dtype=float)
    row[name] = float(values.mean())
    row[f"{name}_p05"] = float(np.quantile(values, 0.05))
    row[f"{name}_p95"] = float(np.quantile(values, 0.95))


def append_new_rows(old: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Extend the cached grid without replacing previously simulated cases."""
    if set(old.columns) != set(new.columns):
        raise ValueError("cached and new state-tail columns differ")
    combined = pd.concat([old, new[old.columns]], ignore_index=True)
    if combined.duplicated(keys).any():
        raise ValueError("state-tail append would duplicate an existing case")
    return combined


def main(caps: tuple[float, ...] = CAP_MULTIPLES, *, append: bool = False) -> None:
    if not caps or len(set(caps)) != len(caps) or not set(caps) <= set(CAP_MULTIPLES):
        raise ValueError("caps must be a nonempty, unique subset of CAP_MULTIPLES")
    if not append and set(caps) != set(CAP_MULTIPLES):
        raise ValueError("a partial cap run requires --append to preserve cached cases")
    old_output = pd.read_csv(OUT / "shared_fee_state_tail.csv") if append else None
    old_paths = pd.read_csv(OUT / "shared_fee_state_tail_paths.csv") if append else None
    if append and old_output["state_demand_cap_multiple"].isin(caps).any():
        raise ValueError("requested caps already exist; use a full run to regenerate")
    surface = pd.read_csv(OUT / "shared_fee_factorial_scenarios.csv")
    main_benchmarks = surface[
        surface["benchmark"].isin(BENCHMARKS)
        & surface["floor_payload_feasible"]
    ].copy()
    frontier = main_benchmarks.loc[
        main_benchmarks.groupby(["benchmark", "propagation_time_s"])[
            "shared_limit"
        ].idxmax()
    ].sort_values(["benchmark", "propagation_time_s"])
    demand = pd.read_csv(
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
    ).iloc[0]
    base = pd.read_csv(OUT / "equilibrium_anchor_by_floor_rate.csv").iloc[0]
    workload = build_canonical_workload().paths
    if workload.shape != (N_SEEDS, BURN_IN + MEASURE_BLOCKS, 4):
        raise AssertionError(f"unexpected workload shape: {workload.shape}")
    workload_hash = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
    expected_hash = pd.read_csv(OUT / "shared_fee_factorial_manifest.csv").iloc[0].workload_sha256
    if workload_hash != expected_hash:
        raise AssertionError("state-tail workload differs from the preserved factorial draws")
    print(f"Verified workload {workload_hash}; running caps {[label(cap) for cap in caps]}", flush=True)
    rows: list[dict] = []
    path_rows: list[dict] = []
    started = time.monotonic()

    for scenario_index, source in enumerate(frontier.itertuples(index=False), start=1):
        print(f"Starting {scenario_index}/{len(frontier)}: {source.benchmark}, {source.propagation_time_s:g}s", flush=True)
        base_anchor = SharedFeeAnchor(
            q_execution=float(base.q_execution_per_block),
            q_data=float(base.q_data_per_block),
            q_state=float(base.q_state_per_block),
            m_execution=float(source.m_execution),
            m_data=float(source.m_data),
            m_state=float(source.m_state),
            reference_fee_gwei=float(base.base_fee_ref_gwei),
            eps_execution=EPS["execution"],
            eps_data=EPS["data"],
            eps_state=EPS["state"],
        )
        anchors = [
            replace(base_anchor, state_demand_cap_multiple=cap)
            for cap in caps
        ]
        equilibria = [
            solve_shared_fee_equilibrium(float(source.shared_target), anchor)
            for anchor in anchors
        ]

        def repeat(values: list[float]) -> np.ndarray:
            return np.repeat(np.asarray(values, dtype=float), N_SEEDS)

        config = SharedFeeConfig(
            gas_target=np.full(
                len(caps) * N_SEEDS, float(source.shared_target)
            ),
            gas_limit=np.full(
                len(caps) * N_SEEDS, float(source.shared_limit)
            ),
            eps_execution=np.full(len(caps) * N_SEEDS, EPS["execution"]),
            eps_data=np.full(len(caps) * N_SEEDS, EPS["data"]),
            eps_state=np.full(len(caps) * N_SEEDS, EPS["state"]),
            m_execution=float(source.m_execution),
            m_data=float(source.m_data),
            m_state=float(source.m_state),
            q_execution_0=base_anchor.q_execution,
            q_data_0=base_anchor.q_data,
            q_state_0=base_anchor.q_state,
            p0_gwei=base_anchor.reference_fee_gwei,
            w_execution=float(demand.w_execution_reference),
            w_state=float(demand.w_state_reference),
            state_demand_cap_multiple=repeat(list(caps)),
        )
        initial = repeat([item.base_fee_wei for item in equilibria])
        result = run_shared_fee_batch(config, workload, initial, burn_in=BURN_IN)

        for index, (cap, equilibrium) in enumerate(
            zip(caps, equilibria, strict=True)
        ):
            selection = slice(index * N_SEEDS, (index + 1) * N_SEEDS)
            state_bytes = (
                result["mean_included_state"][selection] / float(source.cpsb)
            )
            runtime_bal_bytes = result["mean_bal_payload"][selection] / 16.0
            static_bytes = (
                result["mean_reference_data"][selection]
                * float(source.static_bytes_per_reference_data_gas)
            )
            metrics = (
                ("included_execution", result["mean_reference_execution"][selection]),
                ("included_data", result["mean_reference_data"][selection]),
                ("included_state", result["mean_reference_state"][selection]),
                ("included_execution_metered", result["mean_included_execution"][selection]),
                ("included_data_metered", result["mean_included_data"][selection]),
                ("included_regular_metered", result["mean_included_regular"][selection]),
                ("included_state_metered", result["mean_included_state"][selection]),
                ("included_state_bytes", state_bytes),
                ("runtime_bal_bytes", runtime_bal_bytes),
                ("estimated_static_payload_bytes", static_bytes),
                (
                    "estimated_counted_payload_bytes",
                    static_bytes + runtime_bal_bytes,
                ),
                (
                    "annualized_state_growth_gib",
                    state_bytes * BLOCKS_PER_YEAR / BYTES_PER_GIB,
                ),
                ("shared_fee_wei", result["mean_fee_wei"][selection, 1]),
                (
                    "shared_limit_hit_fraction",
                    result["included_limit_fraction"][selection, 1],
                ),
                (
                    "shared_near_limit_fraction",
                    result["near_limit_fraction"][selection, 1],
                ),
                (
                    "shared_fee_floor_bounded_fraction",
                    result["floor_downward_pressure_fraction"][selection, 1],
                ),
                (
                    "shared_target_deviation",
                    result["mean_absolute_target_deviation"][selection, 1],
                ),
                ("shared_rationed_gas", result["mean_rationed"][selection, 1]),
                (
                    "shared_fee_log_return_sd",
                    result["log_return_sd"][selection, 1],
                ),
                (
                    "regular_binding_fraction",
                    result["regular_binding_fraction"][selection],
                ),
                (
                    "state_demand_cap_active_fraction",
                    result["state_demand_cap_active_fraction"][selection],
                ),
                (
                    "base_fee_exposure_proxy_eth_per_block",
                    result["mean_base_fee_exposure_proxy_wei"][selection] / 1e18,
                ),
            )
            row = {
                "mechanism": "shared_fee_8131_8279",
                "benchmark": str(source.benchmark),
                "benchmark_label": str(source.benchmark_label),
                "propagation_time_s": float(source.propagation_time_s),
                "shared_limit": float(source.shared_limit),
                "shared_target": float(source.shared_target),
                "floor_rate": int(source.floor_rate),
                "m_execution": float(source.m_execution),
                "m_data": float(source.m_data),
                "cpsb": float(source.cpsb),
                "m_state": float(source.m_state),
                "state_demand_cap_multiple": cap,
                "state_demand_cap_label": label(cap),
                "equilibrium_fee_wei": equilibrium.base_fee_wei,
                "equilibrium_binding_branch": equilibrium.binding_branch,
                "equilibrium_state_demand_cap_active": (
                    equilibrium.state_demand_cap_active
                ),
                "equilibrium_regular_gas": equilibrium.regular_gas,
                "equilibrium_state_gas": equilibrium.state_gas,
                "equilibrium_execution_gas": equilibrium.execution_gas,
                "equilibrium_data_gas": equilibrium.data_gas,
                "equilibrium_state_activity_multiple": (
                    equilibrium.state_gas
                    / (float(source.m_state) * base_anchor.q_state)
                ),
                "equilibrium_annual_state_gib": (
                    equilibrium.state_gas
                    / float(source.cpsb)
                    * BLOCKS_PER_YEAR
                    / BYTES_PER_GIB
                ),
                "n_replications": N_SEEDS,
                "burn_in_blocks": BURN_IN,
                "measured_blocks": MEASURE_BLOCKS,
                "reference_cpsb": CPSB_REFERENCE,
            }
            for name, values in metrics:
                add_distribution(row, name, values)
            rows.append(row)
            for replication in range(N_SEEDS):
                path = {
                    "benchmark": str(source.benchmark),
                    "propagation_time_s": float(source.propagation_time_s),
                    "state_demand_cap_label": label(cap),
                    "state_demand_cap_multiple": cap,
                    "replication": replication,
                }
                for name, values in metrics:
                    path[name] = float(values[replication])
                path_rows.append(path)
        print(f"Completed {scenario_index}/{len(frontier)}; elapsed {time.monotonic() - started:.1f}s", flush=True)

    output = pd.DataFrame(rows)
    paths = pd.DataFrame(path_rows)
    if append:
        output = append_new_rows(old_output, output, ROW_KEYS)
        paths = append_new_rows(old_paths, paths, ROW_KEYS + ["replication"])
    output = output.sort_values(
        ["benchmark", "propagation_time_s", "state_demand_cap_multiple"]
    )
    paths = paths.sort_values(
        [
            "benchmark",
            "propagation_time_s",
            "state_demand_cap_multiple",
            "replication",
        ]
    )
    if len(output) != len(frontier) * len(CAP_MULTIPLES):
        raise AssertionError("shared-fee state-tail grid is incomplete")
    if output.duplicated(ROW_KEYS).any() or paths.duplicated(ROW_KEYS + ["replication"]).any():
        raise AssertionError("shared-fee state-tail grid contains duplicate cases")
    if not paths.groupby(ROW_KEYS).size().eq(N_SEEDS).all() or len(paths) != len(output) * N_SEEDS:
        raise AssertionError("each state-tail case must have all 32 replications")

    unrestricted = output[np.isinf(output["state_demand_cap_multiple"])]
    expected = frontier[
        ["benchmark", "propagation_time_s", "included_execution", "shared_fee_wei"]
    ]
    check = unrestricted.merge(
        expected,
        on=["benchmark", "propagation_time_s"],
        suffixes=("_tail", "_factorial"),
        validate="one_to_one",
    )
    for column in ("included_execution", "shared_fee_wei"):
        if not np.allclose(
            check[f"{column}_tail"],
            check[f"{column}_factorial"],
            rtol=1e-12,
        ):
            raise AssertionError(
                f"unrestricted state-tail replay no longer matches {column}"
            )

    output.to_csv(OUT / "shared_fee_state_tail.csv", index=False)
    paths.to_csv(OUT / "shared_fee_state_tail_paths.csv", index=False)
    for benchmark, stem in (
        ("proposal_faithful", "shared_fee_proposal_state_tail"),
        ("fully_optimized", "shared_fee_optimized_state_tail"),
    ):
        output[output["benchmark"].eq(benchmark)].to_csv(
            OUT / f"{stem}.csv", index=False
        )
        paths[paths["benchmark"].eq(benchmark)].to_csv(
            OUT / f"{stem}_paths.csv", index=False
        )
    print(output.loc[output.state_demand_cap_multiple.isin(caps), [
        *ROW_KEYS, "equilibrium_fee_wei", "equilibrium_binding_branch",
        "included_execution_metered", "annualized_state_growth_gib",
        "shared_limit_hit_fraction",
    ]].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caps", nargs="+", type=float, default=CAP_MULTIPLES)
    parser.add_argument("--append", action="store_true", help="add new caps while preserving cached cases")
    args = parser.parse_args()
    main(tuple(args.caps), append=args.append)
