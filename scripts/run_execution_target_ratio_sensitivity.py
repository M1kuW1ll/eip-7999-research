"""Execution target-to-limit sensitivity for the dynamic EIP-7999 grid.

The central target grid fixes ``T_E / L_E = 1/2``.  This additive experiment
holds every execution and data target fixed while moving that ratio through
``{1/2, 3/5, 2/3, 3/4, 4/5}``. It runs the same 32 full-multiscale workloads
used by the central design surface and leaves that central CSV unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dynamics.batched_replay import run_batch  # noqa: E402
from run_multiscale_design_surface import (  # noqa: E402
    BLOCKS_PER_DAY,
    BLOCK_PANEL,
    BURN_IN,
    DAILY_ACCOUNTING,
    DAILY_BLOCK_LENGTH,
    DAILY_CURRENT_DATA,
    DAILY_SHOCK_SEED,
    DATA_ANCHOR,
    DEMAND_PARAMETERS,
    EPS,
    EXECUTION_TARGETS,
    MEASURE_BLOCKS,
    N_SEEDS,
    REPORT_SHOCK_SEED,
    TARGET_RATIOS,
    _build_config,
    _collect_rows,
    build_canonical_workload,
)
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

DATA_LIMIT = 90_000_000.0
EXECUTION_TARGET_LIMIT_RATIOS = (0.5, 0.6, 2.0 / 3.0, 0.75, 0.8)
OUTPUT = ROOT / "data/7999/execution_target_ratio_sensitivity.csv"


def build_workload() -> np.ndarray:
    """Build the canonical full-multiscale workload paths."""

    return build_canonical_workload().paths


def main() -> None:
    demand = pd.read_csv(DEMAND_PARAMETERS).iloc[0]
    anchor = pd.read_csv(DATA_ANCHOR).iloc[0]
    multiscale = build_workload()
    grid = [
        (execution_target, target_ratio * DATA_LIMIT)
        for execution_target in EXECUTION_TARGETS
        for target_ratio in TARGET_RATIOS
    ]

    rows: list[dict[str, float | str]] = []
    for workload, shocks in (("full_multiscale", multiscale),):
        for execution_ratio in EXECUTION_TARGET_LIMIT_RATIOS:
            config = _build_config(
                grid,
                DATA_LIMIT,
                demand,
                anchor,
                execution_target_limit_ratio=execution_ratio,
            )
            result = run_batch(
                config,
                shocks,
                bundle_cost_equivalent_start(config),
                burn_in=BURN_IN,
                bundle_consistent=True,
            )
            ratio_rows = _collect_rows(
                workload=workload,
                data_limit=DATA_LIMIT,
                grid=grid,
                config=config,
                result=result,
            )
            for row in ratio_rows:
                row["execution_target_limit_ratio"] = execution_ratio
                row["execution_limit"] = (
                    float(row["execution_target"]) / execution_ratio
                )
                row["data_target_limit_ratio"] = float(row["target_ratio"])
            rows.extend(ratio_rows)
            print(
                f"{workload}: T_E/L_E={execution_ratio:.6f} complete",
                flush=True,
            )

    output = pd.DataFrame(rows).sort_values(
        [
            "workload",
            "execution_target_limit_ratio",
            "execution_target",
            "data_target_limit_ratio",
        ]
    )
    expected_rows = (
        len(EXECUTION_TARGET_LIMIT_RATIOS)
        * len(EXECUTION_TARGETS)
        * len(TARGET_RATIOS)
    )
    if len(output) != expected_rows:
        raise AssertionError(f"expected {expected_rows} rows, got {len(output)}")
    if output.duplicated(
        [
            "workload",
            "execution_target_limit_ratio",
            "execution_target",
            "data_target",
        ]
    ).any():
        raise AssertionError("duplicate target-ratio sensitivity rows")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT, index=False)
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(output)} rows)")


if __name__ == "__main__":
    main()
