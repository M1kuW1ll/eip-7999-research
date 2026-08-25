"""Draw the existing EIP-7999 target grids for the full multiscale workload."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
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


def main() -> None:
    surface = pd.read_csv(ROOT / "data/7999/design_surface_multiscale.csv")
    grid = surface[surface.data_limit == DATA_LIMIT]
    if len(grid) != 63:
        raise ValueError("expected the 63-setting 90M full-multiscale grid")

    figure_combined_design_grid(
        surface,
        output_name="dynamic_multiscale_design_grid.png",
        title="EIP-7999 target grid under the full multiscale workload",
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
    fig.suptitle(
        "Execution support under the full multiscale workload",
        fontsize=17,
        y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94), w_pad=2.6)
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
    fig.suptitle(
        "Data-limit pressure under the full multiscale workload",
        fontsize=17,
        y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95), w_pad=2.6)
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
    fig.suptitle(
        "Effective-price variation under the full multiscale workload",
        fontsize=17,
        y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94), w_pad=2.6)
    fig.savefig(
        PLOTS / "dynamic_multiscale_price_variation_grid.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(fig)

    print("wrote full-multiscale grid figures to plots/")


if __name__ == "__main__":
    main()
