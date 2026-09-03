"""Parameter sensitivity for the EIP-7999 slot-time allocation experiment.

The experiment has two deliberately different scopes:

1. The fixed E300/D80 design is replayed under the full 4 x 3 x 3 grid of
   elasticity windows, BAL allocations, and access-scaling exponents. This
   tests interactions without changing either target.
2. The complete slot-time target surface is replayed under eight unique
   one-at-a-time specifications around the 35-day, lambda=0, rho_A=1 central
   case. This is the interpretable input for configuration-selection tables.

Every trajectory receives the same canonical 60-day multiscale shock paths.
The output ranges are specification envelopes, not sampling confidence bands.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dynamics.batched_replay import (  # noqa: E402
    BatchConfig,
    MIN_BASE_FEE_PER_GAS,
    bundle_cost_equivalent_start,
    run_batch,
)
from run_multiscale_design_surface import _collect_rows  # noqa: E402
from run_slot_time_scenarios import (  # noqa: E402
    BURN_IN,
    DATA_TARGETS,
    EPS,
    EXECUTION_TARGETS,
    MEASURE_BLOCKS,
    N_SEEDS,
    PROPAGATION_TIMES_S,
    STATE_TARGET,
    build_workload,
    limits_for,
)

WINDOWS = (21, 35, 60, 75)
LAMBDA_GRID = (0.0, 0.5, 1.0)
RHO_A_GRID = (0.75, 1.0, 1.25)
CENTRAL = (35, 0.0, 1.0)
E300_D80 = (300e6, 80e6)
HISTORICAL_TOLERANCE_MULTIPLIER = 1.20


def specification_table() -> pd.DataFrame:
    """Build the full factorial parameter grid from calibrated inputs."""

    windows = pd.read_csv(ROOT / "data/glamsterdam/elasticity_vectors.csv").set_index(
        "window_days"
    )
    intensities = pd.read_csv(ROOT / "data/7999/bal_intensities.csv").set_index(
        "lambda_bal"
    )
    rows = []
    for window in WINDOWS:
        elasticity = windows.loc[window]
        epsilon_values = {
            "execution": float(elasticity.eps_execution),
            "data": float(elasticity.eps_data),
            "state": float(elasticity.eps_state),
        }
        # Reproduce the existing slot-time reference exactly. The original
        # central pipeline records the 35-day estimates at six decimals.
        if window == CENTRAL[0]:
            epsilon_values = EPS.copy()
        for lambda_bal in LAMBDA_GRID:
            intensity = intensities.loc[lambda_bal]
            for rho_A in RHO_A_GRID:
                rows.append(
                    {
                        "window_days": int(window),
                        "lambda_bal": float(lambda_bal),
                        "rho_A": float(rho_A),
                        "eps_execution": epsilon_values["execution"],
                        "eps_data": epsilon_values["data"],
                        "eps_state": epsilon_values["state"],
                        "w_execution": float(intensity.w_execution),
                        "w_state": float(intensity.w_state),
                    }
                )
    specs = pd.DataFrame(rows)
    specs.insert(
        0,
        "specification",
        [
            f"W{row.window_days}_L{row.lambda_bal:g}_R{row.rho_A:g}"
            for row in specs.itertuples()
        ],
    )
    specs["is_central"] = (
        specs["window_days"].eq(CENTRAL[0])
        & specs["lambda_bal"].eq(CENTRAL[1])
        & specs["rho_A"].eq(CENTRAL[2])
    )
    if len(specs) != 36 or int(specs.is_central.sum()) != 1:
        raise AssertionError("expected 36 specifications and one central row")
    return specs


def one_at_a_time_specifications(specs: pd.DataFrame) -> pd.DataFrame:
    """Return the eight unique specifications used for selection sensitivity."""

    mask = (
        (specs.lambda_bal.eq(0.0) & specs.rho_A.eq(1.0))
        | (
            specs.window_days.eq(35)
            & specs.rho_A.eq(1.0)
            & specs.lambda_bal.isin(LAMBDA_GRID)
        )
        | (
            specs.window_days.eq(35)
            & specs.lambda_bal.eq(0.0)
            & specs.rho_A.isin(RHO_A_GRID)
        )
    )
    result = specs.loc[mask].copy().reset_index(drop=True)
    if len(result) != 8:
        raise AssertionError(
            f"expected 8 unique one-at-a-time specifications, got {len(result)}"
        )
    return result


def build_config(
    combinations: list[tuple[int, float, float, float, float]],
    specs: pd.DataFrame,
    demand: pd.Series,
    anchor: pd.Series,
) -> BatchConfig:
    """Construct one batched configuration from specification/target tuples."""

    specification_index = np.asarray([item[0] for item in combinations], dtype=int)
    selected = specs.iloc[specification_index]
    repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
    return BatchConfig(
        execution_target=repeat([item[1] for item in combinations]),
        execution_limit=repeat([item[3] for item in combinations]),
        data_target=repeat([item[2] for item in combinations]),
        data_limit=repeat([item[4] for item in combinations]),
        state_target=np.full(len(combinations) * N_SEEDS, STATE_TARGET),
        eps_execution=repeat(selected.eps_execution),
        eps_data=repeat(selected.eps_data),
        eps_state=repeat(selected.eps_state),
        w_execution=repeat(selected.w_execution),
        w_state=repeat(selected.w_state),
        rho_A=repeat(selected.rho_A),
        m_execution=float(demand.m_execution),
        m_state=float(demand.m_state),
        m_data_static=float(anchor.static_data_metering_multiplier),
        q_execution_0=float(demand.q_execution_per_block),
        q_state_0=float(demand.q_state_per_block),
        g_static_0=float(anchor.static_data_gas_per_block),
        p0_gwei=float(demand.base_fee_ref_gwei),
    )


def add_specification_fields(row: dict, specification: pd.Series) -> None:
    for column in (
        "specification",
        "window_days",
        "lambda_bal",
        "rho_A",
        "eps_execution",
        "eps_data",
        "eps_state",
        "w_execution",
        "w_state",
        "is_central",
    ):
        row[column] = specification[column]


def no_bal_execution_ceiling(specification: pd.Series, demand: pd.Series) -> float:
    """Execution target supported at the one-wei floor before BAL charges."""

    parent_floor = float(demand.m_execution) * MIN_BASE_FEE_PER_GAS
    p0_wei = float(demand.base_fee_ref_gwei) * 1e9
    return (
        float(demand.m_execution)
        * float(demand.q_execution_per_block)
        * (p0_wei / parent_floor) ** float(specification.eps_execution)
    )


def target_clearing_execution_fee(
    execution_target: float,
    data_target: float,
    specification: pd.Series,
    demand: pd.Series,
    anchor: pd.Series,
) -> float:
    """Solve the reserve-free execution fee when all three targets clear."""

    q_execution = execution_target / float(demand.m_execution)
    q_state = STATE_TARGET / float(demand.m_state)
    execution_ratio = q_execution / float(demand.q_execution_per_block)
    state_ratio = q_state / float(demand.q_state_per_block)
    bal_execution = (
        float(specification.w_execution)
        * float(demand.q_execution_per_block)
        * execution_ratio ** float(specification.rho_A)
    )
    bal_state = float(specification.w_state) * q_state
    static_target = data_target - bal_execution - bal_state
    if static_target <= 0:
        return float("nan")
    p0_gwei = float(demand.base_fee_ref_gwei)
    data_fee_gwei = (p0_gwei / float(anchor.static_data_metering_multiplier)) * (
        static_target / float(anchor.static_data_gas_per_block)
    ) ** (-1.0 / float(specification.eps_data))
    effective_execution_price_gwei = p0_gwei * execution_ratio ** (
        -1.0 / float(specification.eps_execution)
    )
    execution_intensity = float(specification.w_execution) * execution_ratio ** (
        float(specification.rho_A) - 1.0
    )
    return (
        1e9
        * (effective_execution_price_gwei - execution_intensity * data_fee_gwei)
        / float(demand.m_execution)
    )


def run_fixed_design(
    specs: pd.DataFrame,
    demand: pd.Series,
    anchor: pd.Series,
    shocks: np.ndarray,
) -> pd.DataFrame:
    """Run E300/D80 over every propagation split and full specification grid."""

    combinations = []
    metadata = []
    for propagation_time in PROPAGATION_TIMES_S:
        if propagation_time < 3.0:
            continue
        execution_limit, data_limit = limits_for(propagation_time)
        for specification_index in range(len(specs)):
            combinations.append(
                (
                    specification_index,
                    E300_D80[0],
                    E300_D80[1],
                    execution_limit,
                    data_limit,
                )
            )
            metadata.append(
                (propagation_time, execution_limit, data_limit, specification_index)
            )
    config = build_config(combinations, specs, demand, anchor)
    result = run_batch(
        config,
        shocks,
        bundle_cost_equivalent_start(config),
        burn_in=BURN_IN,
        bundle_consistent=True,
    )
    rows = []
    for index, (
        propagation_time,
        execution_limit,
        data_limit,
        specification_index,
    ) in enumerate(metadata):
        path_slice = slice(index * N_SEEDS, (index + 1) * N_SEEDS)
        specification = specs.iloc[specification_index]
        included_execution = result["mean_used"][path_slice, 0]
        data_limit_hits = result["included_limit_fraction"][path_slice, 1]
        execution_limit_hits = result["included_limit_fraction"][path_slice, 0]
        row = {
            "design": "E300/D80",
            "propagation_time_s": propagation_time,
            "execution_time_s": 9.0 - propagation_time,
            "execution_target": E300_D80[0],
            "data_target": E300_D80[1],
            "execution_limit": execution_limit,
            "data_limit": data_limit,
            "n_replications": N_SEEDS,
            "included_execution": float(included_execution.mean()),
            "included_execution_p05": float(np.quantile(included_execution, 0.05)),
            "included_execution_p95": float(np.quantile(included_execution, 0.95)),
            "execution_fill": float(included_execution.mean() / E300_D80[0]),
            "data_limit_hit_fraction": float(data_limit_hits.mean()),
            "execution_limit_hit_fraction": float(execution_limit_hits.mean()),
            "execution_floor_bounded_fraction": float(
                result["floor_downward_pressure_fraction"][path_slice, 0].mean()
            ),
            "any_limit_hit_fraction": float(
                result["any_limit_hit_fraction"][path_slice].mean()
            ),
        }
        add_specification_fields(row, specification)
        ceiling = no_bal_execution_ceiling(specification, demand)
        row["no_bal_execution_ceiling"] = ceiling
        row["regime"] = (
            "demand_constrained" if ceiling < E300_D80[0] else "capacity_constrained"
        )
        rows.append(row)
    output = pd.DataFrame(rows).sort_values(
        ["propagation_time_s", "window_days", "lambda_bal", "rho_A"]
    )
    if len(output) != 5 * 36:
        raise AssertionError("fixed-design sensitivity should contain 180 rows")
    return output


def run_one_at_a_time_surfaces(
    specs: pd.DataFrame,
    demand: pd.Series,
    anchor: pd.Series,
    shocks: np.ndarray,
) -> pd.DataFrame:
    """Run the complete target surface under eight one-at-a-time specifications."""

    rows = []
    checkpoint = (
        ROOT / "data/7999/slot_time_parameter_surface_one_at_a_time.partial.csv"
    )
    started = time.time()
    for propagation_time in PROPAGATION_TIMES_S:
        if propagation_time < 3.0:
            continue
        execution_limit, data_limit = limits_for(propagation_time)
        target_grid = [
            (execution_target, data_target)
            for execution_target in EXECUTION_TARGETS
            if execution_target < execution_limit
            for data_target in DATA_TARGETS
            if data_target < data_limit
        ]
        combinations = [
            (
                specification_index,
                execution_target,
                data_target,
                execution_limit,
                data_limit,
            )
            for specification_index in range(len(specs))
            for execution_target, data_target in target_grid
        ]
        expanded_grid = [(item[1], item[2]) for item in combinations]
        config = build_config(combinations, specs, demand, anchor)
        result = run_batch(
            config,
            shocks,
            bundle_cost_equivalent_start(config),
            burn_in=BURN_IN,
            bundle_consistent=True,
        )
        collected = _collect_rows(
            workload="full_multiscale",
            data_limit=data_limit,
            grid=expanded_grid,
            config=config,
            result=result,
        )
        for index, row in enumerate(collected):
            specification_index = combinations[index][0]
            specification = specs.iloc[specification_index]
            add_specification_fields(row, specification)
            row.update(
                {
                    "propagation_time_s": float(propagation_time),
                    "execution_time_s": float(9.0 - propagation_time),
                    "execution_limit": float(execution_limit),
                    "data_limit": float(data_limit),
                }
            )
            ceiling = no_bal_execution_ceiling(specification, demand)
            row["no_bal_execution_ceiling"] = ceiling
            row["regime"] = (
                "demand_constrained"
                if ceiling < float(row["execution_target"])
                else "capacity_constrained"
            )
            row["unconstrained_equilibrium_execution_base_fee_wei"] = (
                target_clearing_execution_fee(
                    float(row["execution_target"]),
                    float(row["data_target"]),
                    specification,
                    demand,
                    anchor,
                )
            )
        rows.extend(collected)
        pd.DataFrame(rows).to_csv(checkpoint, index=False)
        print(
            f"  {propagation_time:.1f}s: {len(target_grid)} cells x {len(specs)} specs "
            f"[{time.time() - started:.1f}s]",
            flush=True,
        )
    output = pd.DataFrame(rows).sort_values(
        ["propagation_time_s", "specification", "execution_target", "data_target"]
    )
    expected = sum(
        len(
            [
                (execution_target, data_target)
                for execution_target in EXECUTION_TARGETS
                if execution_target < limits_for(propagation_time)[0]
                for data_target in DATA_TARGETS
                if data_target < limits_for(propagation_time)[1]
            ]
        )
        for propagation_time in PROPAGATION_TIMES_S
        if propagation_time >= 3.0
    ) * len(specs)
    if len(output) != expected:
        raise AssertionError(f"expected {expected} surface rows, got {len(output)}")
    return output


def selection_tables(surface: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select maximum-throughput and balanced configurations per specification."""

    historical = pd.read_csv(
        ROOT / "data/7999/historical_fee_market_benchmark.csv"
    ).iloc[0]
    near_limit_ceiling = HISTORICAL_TOLERANCE_MULTIPLIER * float(
        historical.near_limit_fraction
    )
    deviation_ceiling = HISTORICAL_TOLERANCE_MULTIPLIER * float(
        historical.mean_absolute_target_deviation
    )
    maximum_rows = []
    balanced_rows = []
    for (propagation_time, specification), group in surface.groupby(
        ["propagation_time_s", "specification"], sort=True
    ):
        maximum_rows.append(group.loc[group.included_execution.idxmax()].copy())

        eligible = group[
            (group.any_near_limit_fraction <= near_limit_ceiling)
            & (group.execution_mean_absolute_target_deviation <= deviation_ceiling)
            & (group.unconstrained_equilibrium_execution_base_fee_wei > 1.0)
        ]
        if eligible.empty:
            template = group.iloc[0].copy()
            identifiers = {
                column: template[column]
                for column in (
                    "workload",
                    "propagation_time_s",
                    "execution_time_s",
                    "execution_limit",
                    "data_limit",
                    "specification",
                    "window_days",
                    "lambda_bal",
                    "rho_A",
                    "eps_execution",
                    "eps_data",
                    "eps_state",
                    "w_execution",
                    "w_state",
                    "is_central",
                    "no_bal_execution_ceiling",
                    "regime",
                )
            }
            template.loc[:] = np.nan
            for column, value in identifiers.items():
                template[column] = value
            template["balanced_available"] = False
            balanced_rows.append(template)
        else:
            winner = eligible.loc[eligible.included_execution.idxmax()].copy()
            winner["balanced_available"] = True
            balanced_rows.append(winner)
    maximum_output = pd.DataFrame(maximum_rows)
    balanced_output = pd.DataFrame(balanced_rows)
    return maximum_output, balanced_output


def validate_central_reproduction(
    fixed: pd.DataFrame,
    surface: pd.DataFrame,
) -> None:
    """Verify that sensitivity batching reproduces preserved central outputs."""

    preserved_fixed = pd.read_csv(ROOT / "data/7999/slot_time_fixed_designs.csv")
    preserved_fixed = preserved_fixed[
        preserved_fixed.design.eq("E300/D80")
        & preserved_fixed.propagation_time_s.ge(3.0)
    ].sort_values("propagation_time_s")
    new_fixed = fixed[fixed.is_central].sort_values("propagation_time_s")
    for column in (
        "included_execution",
        "data_limit_hit_fraction",
        "execution_limit_hit_fraction",
        "execution_floor_bounded_fraction",
    ):
        if not np.allclose(
            preserved_fixed[column], new_fixed[column], rtol=0.0, atol=1e-6
        ):
            raise AssertionError(f"fixed central reproduction failed for {column}")

    preserved_surface = pd.read_csv(ROOT / "data/7999/slot_time_scenarios.csv")
    preserved_surface = preserved_surface[preserved_surface.propagation_time_s.ge(3.0)]
    new_surface = surface[surface.is_central]
    keys = ["propagation_time_s", "execution_target", "data_target"]
    merged = preserved_surface.merge(
        new_surface,
        on=keys,
        suffixes=("_preserved", "_new"),
        validate="one_to_one",
    )
    if len(merged) != len(preserved_surface):
        raise AssertionError("central surface does not cover all preserved cells")
    for column in (
        "included_execution",
        "any_near_limit_fraction",
        "execution_mean_absolute_target_deviation",
    ):
        if not np.allclose(
            merged[f"{column}_preserved"],
            merged[f"{column}_new"],
            rtol=0.0,
            atol=1e-6,
        ):
            raise AssertionError(f"surface central reproduction failed for {column}")


def main() -> None:
    demand = pd.read_csv(
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv"
    ).iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[
        0
    ]
    specs = specification_table()
    one_at_a_time = one_at_a_time_specifications(specs)
    shocks = build_workload()
    print(
        f"fixed design: 5 splits x {len(specs)} specs x {N_SEEDS} seeds; "
        f"selection surface: 5 splits x {len(one_at_a_time)} one-at-a-time specs",
        flush=True,
    )

    started = time.time()
    fixed = run_fixed_design(specs, demand, anchor, shocks)
    fixed_path = ROOT / "data/7999/slot_time_e300_d80_parameter_sensitivity.csv"
    fixed.to_csv(fixed_path, index=False)
    print(f"fixed E300/D80 complete [{time.time() - started:.1f}s]", flush=True)
    surface = run_one_at_a_time_surfaces(one_at_a_time, demand, anchor, shocks)
    maximum_throughput, balanced = selection_tables(surface)
    validate_central_reproduction(fixed, surface)

    output = ROOT / "data/7999"
    paths = {
        "fixed": output / "slot_time_e300_d80_parameter_sensitivity.csv",
        "surface": output / "slot_time_parameter_surface_one_at_a_time.csv",
        "maximum": output / "slot_time_parameter_maximum.csv",
        "balanced": output / "slot_time_parameter_balanced.csv",
    }
    fixed.to_csv(paths["fixed"], index=False)
    surface.to_csv(paths["surface"], index=False)
    maximum_throughput.to_csv(paths["maximum"], index=False)
    balanced.to_csv(paths["balanced"], index=False)
    partial = output / "slot_time_parameter_surface_one_at_a_time.partial.csv"
    if partial.exists():
        partial.unlink()
    print(f"completed in {time.time() - started:.1f}s")
    row_counts = {
        "fixed": len(fixed),
        "surface": len(surface),
        "maximum": len(maximum_throughput),
        "balanced": len(balanced),
    }
    for name, path in paths.items():
        print(f"  {name:8s} {row_counts[name]:5d} rows -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
