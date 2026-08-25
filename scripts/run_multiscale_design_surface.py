"""Run the canonical EIP-7999 target grid under the full multiscale workload.

Every target configuration receives the same daily, hourly, fast, and
access-composition shock paths. The multiscale workload is the sole central
dynamic specification; the earlier fast-only surface is no longer regenerated.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import (  # noqa: E402
    RESOURCES,
    BatchConfig,
    bundle_cost_equivalent_start,
    run_batch,
)
from dynamics.empirical_shocks import (  # noqa: E402
    DEFAULT_BLOCK_LENGTH,
)
from dynamics.multiscale_shocks import (  # noqa: E402
    build_full_multiscale_workload,
    score_daily_block_lengths,
    source_round_trip_diagnostics,
    summarize_workload_paths,
)

BLOCKS_PER_DAY = 7_200
BURN_IN = BLOCKS_PER_DAY
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 32
# One contiguous eight-day slow path (one burn-in day plus seven measured days)
# reproduces the 120-day source panel's lag-one daily correlations closely.
# Short two-day strips cut most consecutive-day pairs at artificial joins.
DAILY_BLOCK_LENGTH = 8
STATE_TARGET = 75_000_000.0
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}
REPORT_SHOCK_SEED = 20260814
DAILY_SHOCK_SEED = REPORT_SHOCK_SEED + 1

EXECUTION_TARGETS = np.array([150, 175, 200, 225, 250, 275, 300]) * 1e6
TARGET_RATIOS = np.array(
    [0.25, 0.333, 0.40, 0.50, 0.583, 0.667, 0.75, 77 / 90, 80 / 90]
)
DATA_LIMITS = (90e6, 60e6)

BLOCK_PANEL = ROOT / "data/contiguous/contiguous_block_panel_2026-04-02_60d.csv"
RUNTIME_BAL_PANELS = (
    ROOT / "data/contiguous/contiguous_runtime_bal_hist60d_24788193_25118358.csv",
    ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv",
)
DAILY_ACCOUNTING = (
    ROOT / "data/daily_accounting_panel_calibrated_with_bal_2026-02-01_2026-06-01.csv"
)
DAILY_CURRENT_DATA = (
    ROOT / "data/daily_current_data_gas_xatu_2026-02-01_2026-06-01.csv"
)
DEMAND_PARAMETERS = ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
DATA_ANCHOR = ROOT / "data/7999/data_metering_runtime_bal_anchor.csv"


def _target(config: BatchConfig, resource_index: int) -> np.ndarray:
    return (config.execution_target, config.data_target, config.state_target)[
        resource_index
    ]


def _add_interval(row: dict[str, float | str], name: str, values: np.ndarray) -> None:
    values = np.asarray(values, dtype=float)
    row[name] = float(values.mean())
    row[f"{name}_p05"] = float(np.quantile(values, 0.05))
    row[f"{name}_p95"] = float(np.quantile(values, 0.95))


def _build_config(
    grid: list[tuple[float, float]],
    data_limit: float,
    demand: pd.Series,
    anchor: pd.Series,
    *,
    execution_target_limit_ratio: float = 0.5,
) -> BatchConfig:
    if not 0.0 < execution_target_limit_ratio < 1.0:
        raise ValueError("execution target/limit ratio must lie between zero and one")
    n = len(grid)
    repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
    ones = np.ones(n * N_SEEDS)
    return BatchConfig(
        execution_target=repeat([point[0] for point in grid]),
        execution_limit=repeat(
            [point[0] / execution_target_limit_ratio for point in grid]
        ),
        data_target=repeat([point[1] for point in grid]),
        data_limit=ones * data_limit,
        state_target=ones * STATE_TARGET,
        eps_execution=ones * EPS["execution"],
        eps_data=ones * EPS["data"],
        eps_state=ones * EPS["state"],
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


def _collect_rows(
    *,
    workload: str,
    data_limit: float,
    grid: list[tuple[float, float]],
    config: BatchConfig,
    result: dict[str, np.ndarray],
) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for index, (execution_target, data_target) in enumerate(grid):
        path_slice = slice(index * N_SEEDS, (index + 1) * N_SEEDS)
        included_execution = result["mean_used"][path_slice, 0]
        execution_fill = included_execution / execution_target
        data_hits = result["included_limit_fraction"][path_slice, 1]
        row: dict[str, float | str] = {
            "workload": workload,
            "data_limit": data_limit,
            "execution_target": execution_target,
            "data_target": data_target,
            "target_ratio": data_target / data_limit,
            "n_replications": N_SEEDS,
            "burn_in_blocks": BURN_IN,
            "measured_blocks": MEASURE_BLOCKS,
            "fast_block_length": DEFAULT_BLOCK_LENGTH,
            "daily_block_length": DAILY_BLOCK_LENGTH,
            "data_limit_hit_ci95": 1.96
            * float(np.std(data_hits, ddof=1))
            / np.sqrt(N_SEEDS),
            "longest_data_limit_run": float(
                result["longest_limit_run"][path_slice, 1].mean()
            ),
        }
        _add_interval(row, "included_execution", included_execution)
        _add_interval(row, "execution_fill", execution_fill)
        _add_interval(row, "data_limit_hit_fraction", data_hits)
        _add_interval(
            row,
            "data_offered_limit_pressure_fraction",
            result["offered_limit_pressure_fraction"][path_slice, 1],
        )
        _add_interval(
            row,
            "data_cap_active_fraction",
            result["cap_active_fraction"][path_slice, 1],
        )
        _add_interval(
            row,
            "data_scale_determining_fraction",
            result["scale_determining_fraction"][path_slice, 1],
        )
        _add_interval(row, "rationed_data", result["mean_rationed"][path_slice, 1])
        _add_interval(
            row,
            "execution_floor_bounded_fraction",
            result["floor_downward_pressure_fraction"][path_slice, 0],
        )
        _add_interval(
            row,
            "execution_mean_absolute_target_deviation",
            result["mean_absolute_target_deviation"][path_slice, 0],
        )
        _add_interval(
            row,
            "execution_mean_absolute_target_gap_gas",
            result["mean_absolute_target_gap"][path_slice, 0],
        )
        _add_interval(row, "data_fee_sd", result["log_return_sd"][path_slice, 1])
        # Union over resources of "included usage reached the hard limit", i.e.
        # the block could not have carried more of anything.  Not recoverable
        # from the per-resource fractions, which double-count blocks at both.
        _add_interval(
            row, "any_limit_hit_fraction", result["any_limit_hit_fraction"][path_slice]
        )
        _add_interval(
            row,
            "any_near_limit_fraction",
            result["any_near_limit_fraction"][path_slice],
        )
        _add_interval(
            row,
            "total_base_fee_burn_eth_per_block",
            result["mean_total_burn_wei"][path_slice] / 1e18,
        )

        offered_components = result["mean_data_components_offered"][path_slice]
        included_components = result["mean_data_components_included"][path_slice]
        for component_index, component in enumerate(
            ("static", "bal_execution", "bal_state")
        ):
            row[f"{component}_data_offered"] = float(
                offered_components[:, component_index].mean()
            )
            row[f"{component}_data_included"] = float(
                included_components[:, component_index].mean()
            )
        included_bal = included_components[:, 1] + included_components[:, 2]
        row["bal_data_included"] = float(included_bal.mean())
        row["bal_share_included_data"] = float(
            included_bal.sum() / np.maximum(included_components.sum(), 1e-300)
        )

        for resource_index, resource in enumerate(RESOURCES):
            _add_interval(
                row,
                f"{resource}_near_limit_fraction",
                result["near_limit_fraction"][path_slice, resource_index],
            )
            _add_interval(
                row,
                f"{resource}_base_fee_burn_eth_per_block",
                result["mean_burn_wei"][path_slice, resource_index] / 1e18,
            )
            row.update(
                {
                    f"{resource}_used": float(
                        result["mean_used"][path_slice, resource_index].mean()
                    ),
                    f"{resource}_utilisation": float(
                        result["mean_used"][path_slice, resource_index].mean()
                        / _target(config, resource_index)[index * N_SEEDS]
                    ),
                    f"{resource}_limit_hit_fraction": float(
                        result["limit_hit_fraction"][path_slice, resource_index].mean()
                    ),
                    f"{resource}_offered_limit_pressure_fraction": float(
                        result["offered_limit_pressure_fraction"][
                            path_slice, resource_index
                        ].mean()
                    ),
                    f"{resource}_cap_active_fraction": float(
                        result["cap_active_fraction"][path_slice, resource_index].mean()
                    ),
                    f"{resource}_scale_determining_fraction": float(
                        result["scale_determining_fraction"][
                            path_slice, resource_index
                        ].mean()
                    ),
                    f"{resource}_rationed": float(
                        result["mean_rationed"][path_slice, resource_index].mean()
                    ),
                    f"{resource}_floor_bounded_fraction": float(
                        result["floor_downward_pressure_fraction"][
                            path_slice, resource_index
                        ].mean()
                    ),
                    f"{resource}_fee_wei": float(
                        result["mean_fee_wei"][path_slice, resource_index].mean()
                    ),
                    f"{resource}_fee_sd": float(
                        result["log_return_sd"][path_slice, resource_index].mean()
                    ),
                    f"{resource}_price_sd": float(
                        result["effective_price_log_return_sd"][
                            path_slice, resource_index
                        ].mean()
                    ),
                    f"{resource}_price_p95": float(
                        result["effective_price_log_return_p95"][
                            path_slice, resource_index
                        ].mean()
                    ),
                    f"{resource}_price_p99": float(
                        result["effective_price_log_return_p99"][
                            path_slice, resource_index
                        ].mean()
                    ),
                }
            )
        rows.append(row)
    return rows


def build_canonical_workload():
    """Build the shared 60-day full-multiscale workload used by every replay."""

    return build_full_multiscale_workload(
        block_panel_path=BLOCK_PANEL,
        runtime_bal_paths=list(RUNTIME_BAL_PANELS),
        demand_parameters_path=DEMAND_PARAMETERS,
        accounting_panel_path=DAILY_ACCOUNTING,
        current_data_gas_path=DAILY_CURRENT_DATA,
        n_paths=N_SEEDS,
        n_blocks=BURN_IN + MEASURE_BLOCKS,
        fast_block_length=DEFAULT_BLOCK_LENGTH,
        daily_block_length=DAILY_BLOCK_LENGTH,
        fast_seed=REPORT_SHOCK_SEED,
        daily_seed=DAILY_SHOCK_SEED,
        blocks_per_day=BLOCKS_PER_DAY,
        eps=EPS,
        trend_window=21,
    )


def main() -> None:
    demand = pd.read_csv(DEMAND_PARAMETERS).iloc[0]
    anchor = pd.read_csv(DATA_ANCHOR).iloc[0]

    total_blocks = BURN_IN + MEASURE_BLOCKS
    workload = build_canonical_workload()
    fast_panel = workload.fast_panel
    hourly_profile = workload.hourly_profile
    daily_panel = workload.daily_panel
    daily_draws = workload.daily_draws
    shocks = workload.paths
    daily_block_scores = score_daily_block_lengths(daily_panel)
    selected_daily_length = int(
        daily_block_scores.loc[
            daily_block_scores["mean_abs_lag1_error"].idxmin(),
            "daily_block_length",
        ]
    )
    if selected_daily_length != DAILY_BLOCK_LENGTH:
        raise AssertionError(
            f"configured daily block length {DAILY_BLOCK_LENGTH} differs from "
            f"measured choice {selected_daily_length}"
        )
    daily_block_scores.to_csv(
        ROOT / "data/7999/multiscale_daily_block_length_diagnostics.csv",
        index=False,
    )
    hourly_path = ROOT / "data/7999/multiscale_hourly_profile.csv"
    hourly_profile.to_csv(hourly_path)
    round_trip = source_round_trip_diagnostics(BLOCK_PANEL, eps=EPS)
    if round_trip["max_abs_log_reconstruction_error"].max() > 1e-12:
        raise AssertionError("hour/day/fast source decomposition failed round-trip")
    round_trip.to_csv(
        ROOT / "data/7999/multiscale_source_round_trip.csv", index=False
    )
    daily_positions = pd.DataFrame(
        daily_draws.source_positions,
        columns=[f"simulated_day_{day}" for day in range(daily_draws.factors.shape[1])],
    )
    daily_positions.index.name = "replication"
    daily_positions.to_csv(ROOT / "data/7999/multiscale_daily_source_positions.csv")
    daily_panel.to_csv(ROOT / "data/7999/multiscale_daily_factors.csv")
    shock_summary = summarize_workload_paths(shocks)
    shock_summary.to_csv(
        ROOT / "data/7999/multiscale_workload_shock_summary.csv", index=False
    )
    print(
        f"fast source: {fast_panel.n_blocks:,} blocks; daily source: "
        f"{len(daily_panel)} days; {N_SEEDS} paired paths x {total_blocks:,} blocks"
    )

    rows: list[dict[str, float | str]] = []
    for data_limit in DATA_LIMITS:
        grid = [
            (execution_target, ratio * data_limit)
            for execution_target in EXECUTION_TARGETS
            for ratio in TARGET_RATIOS
        ]
        config = _build_config(grid, data_limit, demand, anchor)
        result = run_batch(
            config,
            shocks,
            bundle_cost_equivalent_start(config),
            burn_in=BURN_IN,
            bundle_consistent=True,
        )
        rows.extend(
            _collect_rows(
                workload="full_multiscale",
                data_limit=data_limit,
                grid=grid,
                config=config,
                result=result,
            )
        )
        print(
            f"  full_multiscale, data limit {data_limit / 1e6:.0f}M: "
            f"{len(grid)} designs done"
        )

    surface = pd.DataFrame(rows)
    surface["fast_source_start_block"] = int(fast_panel.block_numbers[0])
    surface["fast_source_end_block"] = int(fast_panel.block_numbers[-1])
    surface["fast_source_blocks"] = int(fast_panel.n_blocks)
    surface["fast_shock_seed"] = REPORT_SHOCK_SEED
    surface["daily_shock_seed"] = DAILY_SHOCK_SEED
    output = ROOT / "data/7999/design_surface.csv"
    multiscale_output = ROOT / "data/7999/design_surface_multiscale.csv"
    surface.to_csv(output, index=False)
    surface.to_csv(multiscale_output, index=False)

    report_settings = (
        ("E200_D36", 200e6, 0.40),
        ("E225_D45", 225e6, 0.50),
        ("E250_D60", 250e6, 0.667),
        ("E300_D77", 300e6, 77 / 90),
        ("E300_D80", 300e6, 80 / 90),
    )
    selected: list[pd.Series] = []
    central_limit = surface[surface.data_limit == 90e6]
    for design, execution_target, target_ratio in report_settings:
        match = central_limit[
            np.isclose(central_limit.execution_target, execution_target)
            & np.isclose(central_limit.target_ratio, target_ratio)
        ]
        if len(match) != 1:
            raise AssertionError(f"expected one row for {design}")
        row = match.iloc[0].copy()
        row["design"] = design
        selected.append(row)
    selected_frame = pd.DataFrame(selected)
    selected_output = ROOT / "data/7999/design_surface_selected_settings.csv"
    multiscale_selected_output = (
        ROOT / "data/7999/design_surface_multiscale_selected.csv"
    )
    selected_frame.to_csv(selected_output, index=False)
    selected_frame.to_csv(multiscale_selected_output, index=False)
    print(f"wrote {output.relative_to(ROOT)} ({len(surface)} rows)")
    print(f"wrote {multiscale_output.relative_to(ROOT)} ({len(surface)} rows)")
    print(f"wrote {selected_output.relative_to(ROOT)} ({len(selected)} rows)")
    print(
        f"wrote {multiscale_selected_output.relative_to(ROOT)} "
        f"({len(selected)} rows)"
    )


if __name__ == "__main__":
    main()
