"""Draw the existing EIP-7999 target grids for the full multiscale workload."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_pipeline_figures import (  # noqa: E402
    PLOTS,
    design_grid_table,
    figure_combined_design_grid,
    heatmap,
    label_grid_axes,
)

DATA_LIMIT = 90e6


def figure_operating_grid(surface: pd.DataFrame):
    """Draw the three central operating metrics in one horizontal figure.

    Read the saved multiscale means without rerunning or changing any workload.
    The floor metric requires both a current 1-wei fee and execution underfill;
    the data-limit metric measures included gas, not offered-demand pressure.
    """
    grid = surface.loc[surface.data_limit.eq(DATA_LIMIT)].copy()
    if len(grid) != 63 or grid.duplicated(["execution_target", "data_target"]).any():
        raise ValueError("expected 63 distinct settings at the exact 90M data limit")
    if not grid.workload.eq("full_multiscale").all():
        raise ValueError("the operating grid must use the central multiscale workload")
    if not grid.n_replications.eq(32).all() or not grid.measured_blocks.eq(50_400).all():
        raise ValueError("expected 32 paths with 50,400 measured blocks each")
    np.testing.assert_allclose(
        grid.execution_fill,
        grid.included_execution / grid.execution_target,
        rtol=1e-12,
    )
    panels = (
        ("execution_fill", "Execution target\nutilization", "Blues"),
        (
            "execution_floor_bounded_fraction",
            "Execution base fee\nbounded at 1 wei",
            "Purples",
        ),
        (
            "data_limit_hit_fraction",
            "Blocks included at\nthe 90M data limit",
            "Oranges",
        ),
    )
    fig, axes = plt.subplots(1, 3, figsize=(21.0, 5.8))
    for ax, (column, title, cmap) in zip(axes, panels):
        table = design_grid_table(grid, column)
        if table.shape != (7, 9) or not np.isfinite(table.to_numpy()).all():
            raise ValueError(f"incomplete target grid for {column}")
        if column != "execution_fill" and not grid[column].between(0, 1).all():
            raise ValueError(f"invalid block fractions for {column}")
        heatmap(ax, table, title, cmap, "{:.1%}", 1.0)
        ax.set_title(title, fontsize=18, pad=13)
        ax.tick_params(axis="both", labelsize=12.5)
        for annotation in ax.texts:
            annotation.set_fontsize(12)
        ax.set_xlabel("data target and target/limit ratio", fontsize=16, labelpad=10)
    axes[0].set_ylabel("execution target (M)", fontsize=16, labelpad=10)
    fig.tight_layout(w_pad=2.0)
    output = PLOTS / "dynamic_multiscale_operating_grid.png"
    fig.savefig(output, dpi=140, bbox_inches="tight")
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    return fig, axes


def main() -> None:
    surface = pd.read_csv(ROOT / "data/7999/design_surface_multiscale.csv")
    grid = surface[surface.data_limit == DATA_LIMIT]
    if len(grid) != 63:
        raise ValueError("expected the 63-setting 90M full-multiscale grid")

    operating_fig, _ = figure_operating_grid(surface)
    plt.close(operating_fig)

    figure_combined_design_grid(
        surface,
        output_name="dynamic_multiscale_design_grid.png",
        title=None,
    )

    fig, axes = plt.subplots(1, 2, figsize=(17.0, 6.2))
    heatmap(
        axes[0],
        design_grid_table(grid, "execution_fill"),
        "Execution target utilization",
        "Blues",
        "{:.1%}",
        1.0,
    )
    heatmap(
        axes[1],
        design_grid_table(grid, "execution_floor_bounded_fraction"),
        "Execution fee bounded at one wei",
        "Purples",
        "{:.1%}",
        1.0,
    )
    label_grid_axes(axes)
    fig.tight_layout(w_pad=2.6)
    fig.savefig(
        PLOTS / "dynamic_multiscale_execution_support_grid.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(17.0, 6.2), sharey=True)
    heatmap(
        axes[0],
        design_grid_table(grid, "data_limit_hit_fraction"),
        "Blocks included at the 90M data limit",
        "Oranges",
        "{:.1%}",
        1.0,
    )
    heatmap(
        axes[1],
        design_grid_table(grid, "bal_share_included_data"),
        "BAL share of included data gas",
        "Purples",
        "{:.1%}",
        1.0,
    )
    label_grid_axes(axes)
    fig.tight_layout(w_pad=2.6)
    fig.savefig(
        PLOTS / "dynamic_multiscale_data_limit_pressure_grid.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(17.0, 6.2))
    heatmap(
        axes[0],
        design_grid_table(grid, "execution_price_sd"),
        "Execution effective-price variation",
        "Blues",
        "{:.3f}",
        1.0,
    )
    heatmap(
        axes[1],
        design_grid_table(grid, "data_price_sd"),
        "Data effective-price variation",
        "Oranges",
        "{:.3f}",
        1.0,
    )
    label_grid_axes(axes)
    fig.tight_layout(w_pad=2.6)
    fig.savefig(
        PLOTS / "dynamic_multiscale_price_variation_grid.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(fig)

    print("wrote full-multiscale grid figures to plots/")


if __name__ == "__main__":
    main()
