"""Figures for the three parts of the dynamic experiment.

The report follows the pipeline that produced it -- sweep the EIP-7999 target
grid, inspect illustrative operating points, and compare those points against
Glamsterdam -- so the figures follow the same order rather than the order in
which the phenomena were found. Cold-start and single-design steady-state
diagnostics belong to neither part and are drawn by
``make_dynamic_report_figures.py`` for the appendix.

Colour follows the job each encoding does. The target grid is divided into
three figures so execution support, data-limit pressure, and price variation
can be read independently. Each heatmap takes a single-hue sequential ramp:
blue for execution outcomes, orange for data outcomes, and purple or red for
floor and congestion pressure. Resources and mechanisms
are identities and take categorical hues in fixed order; that triple was checked
for colour-vision deficiency rather than assumed safe -- blue/orange/green
collapses under protanopia to a pair separation of 3.5 in OKLab hundredths,
while blue/orange/teal holds at 17.1 protan, 18.0 deutan, 16.5 tritan against a
floor of 8, and 19.0 for normal vision against a floor of 15.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PLOTS = ROOT / "plots"
DATA_LIMIT = 90e6

RESOURCE_HUES = {"execution": "#4C78A8", "data": "#F58518", "state": "#72B7B2"}
MECHANISM_HUES = {"eip7999": "#B22222", "glamsterdam": "#4C78A8"}
SENSITIVITY_HUES = {
    "execution target utilization": "#4C78A8",
    "blocks included at data limit": "#F58518",
    "execution fee bounded at one wei": "#7A5195",
}
INK, INK_MUTED, GRID = "#1A1A1A", "#666666", "#D8D8D8"

plt.rcParams.update({
    "font.size": 11, "axes.titlesize": 12.5, "axes.labelsize": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK_MUTED, "ytick.color": INK_MUTED,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.6, "figure.facecolor": "white",
})

# Use familiar fractions for the regular design ratios. The 77M column is a
# frontier-specific target rather than a simple fraction, so retain its rounded
# decimal ratio.
DATA_TARGET_RATIO_LABELS = {
    0.25: "1/4",
    0.333: "1/3",
    0.40: "2/5",
    0.50: "1/2",
    0.583: "7/12",
    0.667: "2/3",
    0.75: "3/4",
    77 / 90: "0.856",
    80 / 90: "8/9",
}


def data_target_tick_label(ratio):
    """Label a data-grid column with both target gas and target/limit ratio."""

    target_m = ratio * DATA_LIMIT / 1e6
    rounded_target = round(target_m)
    target_text = (
        f"{rounded_target:.0f}M"
        if abs(target_m - rounded_target) < 0.06
        else f"{target_m:.1f}M"
    )
    ratio_text = next(
        (label for value, label in DATA_TARGET_RATIO_LABELS.items()
         if np.isclose(ratio, value)),
        f"{ratio:.3f}",
    )
    return f"{target_text}\n({ratio_text})"


def heatmap(ax, table, title, cmap, fmt, scale):
    values = table.to_numpy() * scale
    ax.imshow(values, cmap=cmap, aspect="auto")
    ax.set_xticks(
        range(table.shape[1]),
        [data_target_tick_label(c) for c in table.columns],
        fontsize=11.5,
    )
    ax.set_yticks(
        range(table.shape[0]),
        [f"{i/1e6:.0f}" for i in table.index],
        fontsize=12,
    )
    # Cell labels rather than a colour bar: the grid is small enough to read
    # exactly, and an exact number is what a design choice needs.
    span = values.max() - values.min()
    for r in range(values.shape[0]):
        for c in range(values.shape[1]):
            v = values[r, c]
            shade = (v - values.min()) / span if span > 0 else 0.0
            ax.annotate(fmt.format(v), xy=(c, r), ha="center", va="center",
                        fontsize=11, color="white" if shade > 0.6 else INK)
    ax.set_title(title, fontsize=15, pad=10)
    # Low execution targets read from the bottom up, matching the usual
    # capacity-axis convention and making increases move upward.
    ax.invert_yaxis()
    ax.grid(False)


def design_grid_table(grid, column):
    """Return a consistently ordered execution/data target table."""

    return grid.pivot(
        index="execution_target", columns="target_ratio", values=column,
    ).sort_index().sort_index(axis=1)


def label_grid_axes(axes):
    """Apply the shared capacity-axis labels to one or more heatmaps."""

    axes = np.atleast_1d(axes)
    for ax in axes:
        ax.set_xlabel(
            "data target and target/limit ratio  $T_D/L_D$",
            fontsize=14,
            labelpad=9,
        )
    axes[0].set_ylabel("execution target  $T_E$ (M)", fontsize=14, labelpad=9)


def figure_design_grids(surface):
    """Split the target surface into three figures with one question each."""

    grid = surface[surface.data_limit == DATA_LIMIT]

    fig, axes = plt.subplots(1, 2, figsize=(17.0, 6.2))
    heatmap(
        axes[0], design_grid_table(grid, "execution_fill"),
        "Execution target utilization", "Blues", "{:.1%}", 1.0,
    )
    heatmap(
        axes[1], design_grid_table(grid, "execution_floor_bounded_fraction"),
        "Execution fee bounded at one wei", "Purples", "{:.1%}", 1.0,
    )
    label_grid_axes(axes)
    fig.suptitle(
        "Execution support across the EIP-7999 target grid",
        fontsize=17, y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94), w_pad=2.6)
    fig.savefig(
        PLOTS / "dynamic_execution_support_grid.png",
        dpi=200, bbox_inches="tight",
    )
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(17.0, 6.2), sharey=True)
    heatmap(
        axes[0], design_grid_table(grid, "data_limit_hit_fraction"),
        "Blocks included at the 90M data limit", "Oranges", "{:.1%}", 1.0,
    )
    heatmap(
        axes[1], design_grid_table(grid, "bal_share_included_data"),
        "BAL share of included data gas", "Purples", "{:.1%}", 1.0,
    )
    label_grid_axes(axes)
    fig.suptitle(
        "Data-limit pressure and included-data composition",
        fontsize=17,
        y=0.99,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95], w_pad=2.6)
    fig.savefig(
        PLOTS / "dynamic_data_limit_pressure_grid.png",
        dpi=200, bbox_inches="tight",
    )
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(17.0, 6.2))
    heatmap(
        axes[0], design_grid_table(grid, "execution_price_sd"),
        "Execution effective-price variation", "Blues", "{:.3f}", 1.0,
    )
    heatmap(
        axes[1], design_grid_table(grid, "data_price_sd"),
        "Data effective-price variation", "Oranges", "{:.3f}", 1.0,
    )
    label_grid_axes(axes)
    fig.suptitle(
        "Block-to-block effective-price variation across the target grid",
        fontsize=17, y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94), w_pad=2.6)
    fig.savefig(
        PLOTS / "dynamic_price_variation_grid.png",
        dpi=200, bbox_inches="tight",
    )
    plt.close(fig)


def figure_combined_design_grid(
    surface,
    *,
    output_name="dynamic_design_grid.png",
    title="EIP-7999 target grid under within-day demand shocks",
    png_dpi=160,
):
    """Draw the six target-grid outcomes and save compact PNG and vector PDF copies."""

    grid = surface[surface.data_limit == DATA_LIMIT]
    if len(grid) != 63:
        raise ValueError("expected the 63-setting grid at the 90M data limit")

    panels = (
        (
            "execution_fill",
            "Execution target utilization",
            "Blues",
            "{:.1%}",
        ),
        (
            "execution_floor_bounded_fraction",
            "Execution fee bounded at one wei",
            "Purples",
            "{:.1%}",
        ),
        (
            "data_limit_hit_fraction",
            "Blocks included at the 90M data limit",
            "Oranges",
            "{:.1%}",
        ),
        (
            "bal_share_included_data",
            "BAL share of included data gas",
            "Purples",
            "{:.1%}",
        ),
        (
            "execution_price_sd",
            "Execution effective-price variation",
            "Blues",
            "{:.3f}",
        ),
        (
            "data_price_sd",
            "Data effective-price variation",
            "Oranges",
            "{:.3f}",
        ),
    )

    fig, axes = plt.subplots(2, 3, figsize=(23.0, 11.5))
    for ax, (column, panel_title, cmap, fmt) in zip(axes.ravel(), panels):
        heatmap(
            ax,
            design_grid_table(grid, column),
            panel_title,
            cmap,
            fmt,
            1.0,
        )

    for ax in axes[1]:
        ax.set_xlabel(
            "data target and target/limit ratio  $T_D/L_D$",
            fontsize=14,
            labelpad=9,
        )
    for ax in axes[:, 0]:
        ax.set_ylabel("execution target  $T_E$ (M)", fontsize=14, labelpad=9)

    fig.suptitle(title, fontsize=18, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.965), h_pad=3.2, w_pad=2.4)
    output_path = PLOTS / output_name
    fig.savefig(output_path, dpi=png_dpi, bbox_inches="tight")
    fig.savefig(output_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def figure_candidates(comparison):
    seven999 = comparison[comparison.mechanism == "eip7999"]
    labels = [f"{r.configuration}\n{r.design.replace('_', '/')}"
              for _, r in seven999.iterrows()]
    shades = plt.cm.Blues(np.linspace(0.45, 0.85, len(seven999)))
    metrics = [
        ("execution_fill", "Execution target utilization", 1.0, "{:.1%}"),
        (None, "Active hard-limit constraints", 1.0, "{:.1%}"),
        (
            "execution_floor_bounded_fraction",
            "Execution fee bounded at one wei",
            1.0,
            "{:.1%}",
        ),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16.0, 5.4))
    for ax, (column, title, scale, fmt) in zip(axes.ravel(), metrics):
        if column is None:
            bottom = np.zeros(len(seven999))
            components = (
                ("execution_only_cap_active_fraction", "execution only", RESOURCE_HUES["execution"]),
                ("data_only_cap_active_fraction", "data only", RESOURCE_HUES["data"]),
                ("both_caps_active_fraction", "both active", "#7A5195"),
            )
            for component, label, colour in components:
                values = seven999[component].to_numpy()
                ax.bar(
                    np.arange(len(values)), values, bottom=bottom,
                    color=colour, width=0.62, label=label,
                )
                bottom += values
            for x, value in enumerate(bottom):
                ax.annotate(
                    f"{value:.1%}", xy=(x, value), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=10,
                )
            ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
            ax.legend(frameon=False, fontsize=8.5, loc="upper left")
            ax.set_xticks(np.arange(len(bottom)), labels, fontsize=9.5)
            ax.set_title(title, pad=8)
            ax.margins(y=0.20)
            ax.grid(axis="y", alpha=0.5)
            continue
        values = seven999[column].to_numpy() * scale
        p05_column = f"{column}_p05"
        p95_column = f"{column}_p95"
        yerr = None
        if p05_column in seven999 and p95_column in seven999:
            lower = values - seven999[p05_column].to_numpy() * scale
            upper = seven999[p95_column].to_numpy() * scale - values
            yerr = np.vstack([lower, upper])
        ax.bar(
            np.arange(len(values)), values, color=shades, width=0.62,
            yerr=yerr, error_kw={"ecolor": INK, "elinewidth": 1.0, "capsize": 3},
        )
        for x, v in enumerate(values):
            label_height = (
                seven999[p95_column].iloc[x] * scale if yerr is not None else v
            )
            ax.annotate(fmt.format(v), xy=(x, label_height), xytext=(0, 4),
                        textcoords="offset points", ha="center", fontsize=10)
        if column in {"execution_fill", "execution_floor_bounded_fraction"}:
            ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
        ax.set_xticks(np.arange(len(values)), labels, fontsize=9.5)
        ax.set_title(title, pad=8)
        ax.margins(y=0.20)
        ax.grid(axis="y", alpha=0.5)
    fig.suptitle("Four illustrative EIP-7999 operating points",
                 fontsize=17, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.93), w_pad=2.2)
    fig.savefig(PLOTS / "dynamic_candidates.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def figure_mechanism_comparison(comparison):
    labels, colours = [], []
    for _, r in comparison.iterrows():
        labels.append(f"{r.configuration}\n{r.design.replace('_', '/')}"
                      if r.mechanism == "eip7999" else f"Glamsterdam\n{r.design}")
        colours.append(MECHANISM_HUES[r.mechanism])
    fig, axes = plt.subplots(2, 3, figsize=(14.5, 7.4))

    simple = [
        ("included_execution", "Delivered execution (M gas)", 1e-6, "{:.0f}"),
        ("state_gas", "Included state gas (M)", 1e-6, "{:.0f}"),
        ("execution_per_state", "Execution per unit of state", 1.0, "{:.2f}"),
        ("rationed_data", "Rationed data (M gas)", 1e-6, "{:.2f}"),
    ]
    for ax, (column, title, scale, fmt) in zip(axes.ravel(), simple):
        values = comparison[column].to_numpy() * scale
        p05 = comparison[f"{column}_p05"].to_numpy() * scale
        p95 = comparison[f"{column}_p95"].to_numpy() * scale
        ax.bar(
            np.arange(len(values)), values, color=colours, width=0.62,
            yerr=np.vstack([values - p05, p95 - values]),
            error_kw={"ecolor": INK, "elinewidth": 1.0, "capsize": 3},
        )
        for x, v in enumerate(values):
            ax.annotate(fmt.format(v), xy=(x, p95[x]), xytext=(0, 4),
                        textcoords="offset points", ha="center", fontsize=9.5)
        ax.set_xticks(np.arange(len(values)), labels, fontsize=8.5)
        ax.set_title(title, pad=8)
        ax.margins(y=0.22)
        ax.grid(axis="y", alpha=0.5)

    # Effective activity prices, grouped by resource. Under Glamsterdam the three
    # bars are equal by construction -- one shared fee scaled by three metering
    # multipliers -- which is the contrast this panel exists to show.
    ax = axes[1, 1]
    width = 0.26
    x = np.arange(len(comparison))
    for j, resource in enumerate(("execution", "data", "state")):
        ax.bar(x + (j - 1) * width, comparison[f"{resource}_price_sd"],
               width=width, color=RESOURCE_HUES[resource], label=resource)
    ax.set_xticks(x, labels, fontsize=8.5)
    ax.set_title("Effective price variation, sd of $\\Delta\\log P$", pad=8)
    ax.legend(frameon=False, fontsize=9.5)
    ax.grid(axis="y", alpha=0.5)
    ax.annotate("one shared fee:\nall three equal", xy=(len(x) - 1, 0.058),
                xytext=(-4, 26), textcoords="offset points", ha="right",
                fontsize=9, color=INK_MUTED,
                arrowprops=dict(arrowstyle="->", color=INK_MUTED, lw=1.0))

    ax = axes[1, 2]
    bundles = ["execution_heavy", "data_heavy", "state_creating", "mixed"]
    shades = plt.cm.Greys(np.linspace(0.35, 0.8, len(bundles)))
    for j, bundle in enumerate(bundles):
        costs = comparison[f"cost_{bundle}"] / comparison[f"cost_{bundle}"].iloc[-1]
        ax.bar(x + (j - 1.5) * 0.2, costs, width=0.2, color=shades[j],
               label=bundle.replace("_", " "))
    ax.axhline(1.0, color=MECHANISM_HUES["glamsterdam"], linewidth=1.1, linestyle="--")
    ax.set_yscale("log")
    ax.set_xticks(x, labels, fontsize=8.5)
    ax.set_title("Illustrative bundle cost, relative to Glamsterdam", pad=8)
    ax.legend(frameon=False, fontsize=8.5, loc="lower left")
    ax.grid(axis="y", alpha=0.5)

    fig.suptitle("EIP-7999 operating points against Glamsterdam at 200M, "
                 "identical shock paths", fontsize=13, y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(PLOTS / "dynamic_mechanism_comparison.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def figure_parameter_sensitivity(one_at_a_time):
    """One-at-a-time parameter effects at fixed central and saturated designs."""

    designs = ("E225_D45", "E300_D80")
    sensitivities = (
        ("elasticity_window", "Elasticity window", "window"),
        ("rho_A", "Access scaling $\\rho_A$", "$\\rho_A$"),
        ("lambda", "Co-produced allocation $\\lambda$", "$\\lambda$"),
    )
    metrics = (
        ("execution_fill", "execution target utilization"),
        ("data_limit_hit_fraction", "blocks included at data limit"),
        (
            "execution_floor_bounded_fraction",
            "execution fee bounded at one wei",
        ),
    )

    fig, axes = plt.subplots(2, 3, figsize=(16.0, 8.4), sharey=True)
    for row_index, design in enumerate(designs):
        for column_index, (sensitivity, title, xlabel) in enumerate(sensitivities):
            ax = axes[row_index, column_index]
            part = one_at_a_time[
                (one_at_a_time.design == design)
                & (one_at_a_time.sensitivity == sensitivity)
            ].sort_values("setting_order")
            x = np.arange(len(part))

            if sensitivity == "elasticity_window":
                constrained = np.flatnonzero(part.regime.eq("demand_constrained").to_numpy())
                for index in constrained:
                    ax.axvspan(index - 0.45, index + 0.45, color="#E6E6E6", alpha=0.65,
                               linewidth=0, zorder=0)
                if len(constrained):
                    ax.text(
                        constrained.mean(), 3.0, "demand constrained",
                        ha="center", va="bottom", fontsize=10.5, color=INK_MUTED,
                    )

            for metric, label in metrics:
                values = 100.0 * part[metric].to_numpy()
                ax.plot(
                    x, values, marker="o", markersize=6.5, linewidth=2.0,
                    color=SENSITIVITY_HUES[label], label=label, zorder=3,
                )
                central = np.flatnonzero(part.is_central.to_numpy())
                if len(central):
                    index = int(central[0])
                    ax.scatter(
                        [index], [values[index]], s=75, facecolor="white",
                        edgecolor=SENSITIVITY_HUES[label], linewidth=2.0, zorder=4,
                    )

            central = np.flatnonzero(part.is_central.to_numpy())
            if len(central):
                ax.axvline(int(central[0]), color=INK_MUTED, linewidth=0.9,
                           linestyle=":", zorder=1)
            ax.set_xticks(x, part.setting)
            ax.set_xlabel(xlabel, fontsize=12.5)
            ax.set_ylim(0, 105)
            ax.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
            ax.tick_params(labelsize=11.5)
            ax.grid(axis="y", alpha=0.5)
            if row_index == 0:
                ax.set_title(title, fontsize=14, pad=9)
            if column_index == 0:
                ax.set_ylabel(
                    f"{design.replace('_', '/')}\nfraction of target or blocks",
                    fontsize=12.5,
                )

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, 0.94), fontsize=12)
    fig.suptitle(
        "One-at-a-time parameter sensitivity at fixed targets and limits",
        fontsize=16, y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90), h_pad=2.4, w_pad=1.5)
    fig.savefig(PLOTS / "dynamic_parameter_sensitivity.png", dpi=200,
                bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    surface = pd.read_csv(ROOT / "data/7999/design_surface.csv")
    comparison = pd.read_csv(ROOT / "data/7999/mechanism_comparison.csv")
    one_at_a_time = pd.read_csv(ROOT / "data/7999/stage_c_one_at_a_time.csv")
    figure_design_grids(surface)
    figure_combined_design_grid(surface)
    figure_candidates(comparison)
    figure_mechanism_comparison(comparison)
    figure_parameter_sensitivity(one_at_a_time)
    print("wrote to plots/:")
    for name in (
        "execution_support_grid", "data_limit_pressure_grid",
        "price_variation_grid", "design_grid", "candidates",
        "mechanism_comparison", "parameter_sensitivity",
    ):
        print(f"  dynamic_{name}.png")


if __name__ == "__main__":
    main()
