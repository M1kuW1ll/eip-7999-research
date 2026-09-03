"""Build and document the canonical demand-shock paths for the EIP-7999 report.

This is the notebook-facing entry point for the first stage of the publication
pipeline.  It uses the same constructors, source panels, seeds, and block
lengths as ``run_multiscale_design_surface.py`` but writes only workload and
validation artifacts; it does not run a fee-market target sweep.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dynamics.empirical_shocks import DEFAULT_BLOCK_LENGTH, SHOCK_COLUMNS  # noqa: E402
from dynamics.multiscale_shocks import (  # noqa: E402
    score_daily_block_lengths,
    source_round_trip_diagnostics,
    summarize_workload_paths,
)
from run_multiscale_design_surface import (  # noqa: E402
    BLOCK_PANEL,
    BURN_IN,
    DAILY_ACCOUNTING,
    DAILY_BLOCK_LENGTH,
    DAILY_CURRENT_DATA,
    DAILY_SHOCK_SEED,
    DEMAND_PARAMETERS,
    EPS,
    MEASURE_BLOCKS,
    N_SEEDS,
    REPORT_SHOCK_SEED,
    RUNTIME_BAL_PANELS,
    build_canonical_workload,
)

OUTPUT_DIR = ROOT / "data/7999"


def required_inputs() -> tuple[Path, ...]:
    """Return every ignored source or upstream handoff needed by this stage."""

    return (
        BLOCK_PANEL,
        *RUNTIME_BAL_PANELS,
        DAILY_ACCOUNTING,
        DAILY_CURRENT_DATA,
        DEMAND_PARAMETERS,
    )


def validate_inputs() -> None:
    missing = [path for path in required_inputs() if not path.exists()]
    if missing:
        formatted = "\n".join(f"  - {path.relative_to(ROOT)}" for path in missing)
        raise FileNotFoundError(
            "Missing demand-shock inputs:\n"
            f"{formatted}\n"
            "Run the documented Xatu/RPC refresh in "
            "notebooks/7999_simulation/01-demand-shocks.ipynb and the two "
            "upstream publication notebook sequences first."
        )


def main() -> None:
    validate_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    workload = build_canonical_workload()

    daily_scores = score_daily_block_lengths(workload.daily_panel)
    selected_daily_length = int(
        daily_scores.loc[
            daily_scores["mean_abs_lag1_error"].idxmin(), "daily_block_length"
        ]
    )
    if selected_daily_length != DAILY_BLOCK_LENGTH:
        raise AssertionError(
            f"configured daily block length {DAILY_BLOCK_LENGTH} differs from "
            f"measured choice {selected_daily_length}"
        )
    daily_scores.to_csv(
        OUTPUT_DIR / "multiscale_daily_block_length_diagnostics.csv", index=False
    )

    workload.hourly_profile.to_csv(OUTPUT_DIR / "multiscale_hourly_profile.csv")
    workload.daily_panel.to_csv(OUTPUT_DIR / "multiscale_daily_factors.csv")
    daily_positions = pd.DataFrame(
        workload.daily_draws.source_positions,
        columns=[
            f"simulated_day_{day}"
            for day in range(workload.daily_draws.factors.shape[1])
        ],
    )
    daily_positions.index.name = "replication"
    daily_positions.to_csv(OUTPUT_DIR / "multiscale_daily_source_positions.csv")

    round_trip = source_round_trip_diagnostics(BLOCK_PANEL, eps=EPS)
    if round_trip["max_abs_log_reconstruction_error"].max() > 1e-12:
        raise AssertionError("hour/day/fast decomposition failed its round trip")
    round_trip.to_csv(OUTPUT_DIR / "multiscale_source_round_trip.csv", index=False)

    summary = summarize_workload_paths(workload.paths)
    summary.to_csv(OUTPUT_DIR / "multiscale_workload_shock_summary.csv", index=False)
    path_means = pd.DataFrame(
        workload.paths.mean(axis=1),
        columns=SHOCK_COLUMNS,
    )
    path_means.index.name = "replication"
    path_means.to_csv(OUTPUT_DIR / "multiscale_path_mean_factors.csv")
    if np.allclose(path_means.to_numpy(), 1.0, rtol=0.0, atol=1e-12):
        raise AssertionError("simulated paths were unexpectedly normalized path by path")

    manifest = pd.DataFrame(
        [
            {
                "fast_source_start_block": int(workload.fast_panel.block_numbers[0]),
                "fast_source_end_block": int(workload.fast_panel.block_numbers[-1]),
                "fast_source_blocks": int(workload.fast_panel.n_blocks),
                "daily_source_days": int(len(workload.daily_panel)),
                "paths": N_SEEDS,
                "burn_in_blocks": BURN_IN,
                "measured_blocks": MEASURE_BLOCKS,
                "fast_block_length": DEFAULT_BLOCK_LENGTH,
                "daily_block_length": DAILY_BLOCK_LENGTH,
                "fast_seed": REPORT_SHOCK_SEED,
                "daily_seed": DAILY_SHOCK_SEED,
                "path_specific_normalization": False,
            }
        ]
    )
    manifest.to_csv(OUTPUT_DIR / "multiscale_workload_manifest.csv", index=False)

    print(
        f"built {N_SEEDS} paired paths x {BURN_IN + MEASURE_BLOCKS:,} blocks; "
        f"fast source {workload.fast_panel.n_blocks:,} blocks; "
        f"daily source {len(workload.daily_panel)} days"
    )
    print(f"wrote workload diagnostics to {OUTPUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
