"""Figures for the three parts of the dynamic experiment.

The report follows the pipeline that produced it -- sweep the EIP-7999 target
grid, select candidates from it, compare those against Glamsterdam -- so the
figures follow the same order rather than the order in which the phenomena were
found. Cold-start and single-design steady-state diagnostics belong to neither
part and are drawn by ``make_dynamic_report_figures.py`` for the appendix.

Colour follows the job each encoding does. The grid heatmaps are magnitude, so
each takes a single-hue sequential ramp: blue where a larger value is the
objective (throughput, fill) and red where a larger value is pressure
(congestion, rationing, floor operation, price variation). Reading direction is
therefore carried by hue, not by an arbitrary rainbow. Resources and mechanisms
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PLOTS = ROOT / "plots"
DATA_LIMIT = 90e6

RESOURCE_HUES = {"execution": "#4C78A8", "data": "#F58518", "state": "#72B7B2"}
MECHANISM_HUES = {"eip7999": "#B22222", "glamsterdam": "#4C78A8"}
INK, INK_MUTED, GRID = "#1A1A1A", "#666666", "#D8D8D8"

plt.rcParams.update({
    "font.size": 11, "axes.titlesize": 12.5, "axes.labelsize": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK_MUTED, "ytick.color": INK_MUTED,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.6, "figure.facecolor": "white",
})

# (column, title, colour ramp, cell format, scale). "Blues" reads as more of a
# good thing, "Reds" as more pressure.
PANELS = [
    ("included_execution", "Delivered execution (M gas)", "Blues", "{:.0f}", 1e-6),
    ("execution_fill", "Execution fill", "Blues", "{:.2f}", 1.0),
    ("data_limit_hit_fraction", "Blocks at the data limit", "Reds", "{:.2f}", 1.0),
    ("execution_floor_fraction", "Execution fee at its floor", "Reds", "{:.2f}", 1.0),
    ("rationed_data", "Rationed data (M gas)", "Reds", "{:.1f}", 1e-6),
    ("data_price_sd", "Data price variation, sd", "Reds", "{:.3f}", 1.0),
]


def heatmap(ax, table, title, cmap, fmt, scale):
    values = table.to_numpy() * scale
    ax.imshow(values, cmap=cmap, aspect="auto")
    ax.set_xticks(range(table.shape[1]), [f"{c:.2f}" for c in table.columns], fontsize=9)
    ax.set_yticks(range(table.shape[0]), [f"{i/1e6:.0f}" for i in table.index], fontsize=9)
    # Cell labels rather than a colour bar: the grid is small enough to read
    # exactly, and an exact number is what a design choice needs.
    span = values.max() - values.min()
    for r in range(values.shape[0]):
        for c in range(values.shape[1]):
            v = values[r, c]
            shade = (v - values.min()) / span if span > 0 else 0.0
            ax.annotate(fmt.format(v), xy=(c, r), ha="center", va="center",
                        fontsize=8.5, color="white" if shade > 0.6 else INK)
    ax.set_title(title, pad=8)
    ax.grid(False)


def figure_design_grid(surface):
    grid = surface[surface.data_limit == DATA_LIMIT]
    fig, axes = plt.subplots(2, 3, figsize=(15.5, 8.0))
    for ax, (column, title, cmap, fmt, scale) in zip(axes.ravel(), PANELS):
        table = grid.pivot(index="execution_target", columns="target_ratio", values=column)
        heatmap(ax, table, title, cmap, fmt, scale)
    for ax in axes[1]:
        ax.set_xlabel("data target ratio  $T_D/L_D$")
    for ax in axes[:, 0]:
        ax.set_ylabel("execution target  $T_E$ (M)")
    fig.suptitle("EIP-7999 target grid at a fixed 90M data limit — "
                 "congestion reads across, throughput reads down",
                 fontsize=14, y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(PLOTS / "dynamic_design_grid.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def figure_candidates(comparison):
    seven999 = comparison[comparison.mechanism == "eip7999"]
    labels = [f"{r.configuration}\n{r.design.replace('_', '/')}"
              for _, r in seven999.iterrows()]
    shades = plt.cm.Blues(np.linspace(0.45, 0.85, len(seven999)))
    metrics = [
        ("included_execution", "Delivered execution (M gas)", 1e-6, "{:.0f}"),
        ("execution_fill", "Execution fill", 1.0, "{:.3f}"),
        ("data_limit_hit_fraction", "Blocks at the data limit", 1.0, "{:.3f}"),
        ("rationed_data", "Rationed data (M gas)", 1e-6, "{:.2f}"),
        ("execution_floor_fraction", "Execution fee at its floor", 1.0, "{:.3f}"),
        ("execution_per_state", "Execution per unit of state", 1.0, "{:.2f}"),
    ]
    if "data_limit_hit_fraction" not in seven999:
        metrics[2] = ("any_limit_hit_fraction", "Blocks at any hard limit", 1.0, "{:.3f}")
    fig, axes = plt.subplots(2, 3, figsize=(14.0, 7.0))
    for ax, (column, title, scale, fmt) in zip(axes.ravel(), metrics):
        values = seven999[column].to_numpy() * scale
        ax.bar(np.arange(len(values)), values, color=shades, width=0.62)
        for x, v in enumerate(values):
            ax.annotate(fmt.format(v), xy=(x, v), xytext=(0, 4),
                        textcoords="offset points", ha="center", fontsize=10)
        ax.set_xticks(np.arange(len(values)), labels, fontsize=9.5)
        ax.set_title(title, pad=8)
        ax.margins(y=0.20)
        ax.grid(axis="y", alpha=0.5)
    fig.suptitle("Three candidates off the grid: most execution deliverable at each "
                 "congestion tolerance, among designs that clear their target",
                 fontsize=13, y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
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
        ("state_gas", "State gas created (M)", 1e-6, "{:.0f}"),
        ("execution_per_state", "Execution per unit of state", 1.0, "{:.2f}"),
        ("rationed_data", "Rationed data (M gas)", 1e-6, "{:.2f}"),
    ]
    for ax, (column, title, scale, fmt) in zip(axes.ravel(), simple):
        values = comparison[column].to_numpy() * scale
        ax.bar(np.arange(len(values)), values, color=colours, width=0.62)
        for x, v in enumerate(values):
            ax.annotate(fmt.format(v), xy=(x, v), xytext=(0, 4),
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
    ax.set_title("User cost by bundle, relative to Glamsterdam", pad=8)
    ax.legend(frameon=False, fontsize=8.5, loc="lower left")
    ax.grid(axis="y", alpha=0.5)

    fig.suptitle("EIP-7999 candidates against Glamsterdam at 200M, "
                 "identical shock paths", fontsize=13, y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(PLOTS / "dynamic_mechanism_comparison.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    surface = pd.read_csv(ROOT / "data/7999/design_surface.csv")
    comparison = pd.read_csv(ROOT / "data/7999/mechanism_comparison.csv")
    figure_design_grid(surface)
    figure_candidates(comparison)
    figure_mechanism_comparison(comparison)
    print("wrote to plots/:")
    for name in ("design_grid", "candidates", "mechanism_comparison"):
        print(f"  dynamic_{name}.png")


if __name__ == "__main__":
    main()
