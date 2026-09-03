"""Descriptive figures for the multiscale slot-time allocation experiment.

Colour follows the existing dynamic-report conventions: designs differ by a
continuous parameter and take a sequential single-hue ramp; the two hard limits
are identities and take the categorical execution/data hues already in use.

The figures show fixed-target paths, the complete target surfaces, the
controlled slot-time substitution at fixed targets, the two selection
standards compared across splits, and the outcome trade-offs across every
tested configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PLOTS = ROOT / "plots"

RESOURCE_HUES = {"execution": "#4C78A8", "data": "#F58518", "state": "#72B7B2"}
INK, INK_MUTED, GRID = "#1A1A1A", "#666666", "#D8D8D8"
BASELINE_T_PROP = 3.0

plt.rcParams.update({
    "font.size": 12, "axes.titlesize": 13.5, "axes.labelsize": 12,
    "axes.edgecolor": GRID, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK_MUTED, "ytick.color": INK_MUTED,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.6, "figure.facecolor": "white",
})

DESIGNS = [
    ("E300/D80", 300e6, 80e6), ("E300/D77", 300e6, 77e6),
    ("E275/D67.5", 275e6, 67.5e6), ("E275/D60", 275e6, 60e6),
    ("E250/D60", 250e6, 60e6), ("E250/D52.5", 250e6, 52.5e6),
    ("E225/D45", 225e6, 45e6),
    ("E225/D52.5", 225e6, 52.5e6), ("E225/D36", 225e6, 36e6),
]


def design_ramp(n):
    return plt.get_cmap("viridis")(np.linspace(0.08, 0.92, n))


def solved_data_target(group):
    """Smallest data target reaching the throughput plateau at this execution
    target.  Delivered execution is flat across a wide band of data targets;
    the low end of that band costs a fraction of a percent of throughput and
    a fraction of the limit pressure and rationing of the high end."""
    group = group.sort_values("data_target")
    plateau = group.included_execution >= 0.99 * group.included_execution.max()
    return group[plateau].iloc[0]


def main() -> None:
    d = pd.read_csv(ROOT / "data/7999/slot_time_scenarios.csv")
    # The 2.5s split is not carried into the design comparison: its 71.4M data
    # limit removes most of the target grid, so it is a different design space
    # rather than a shorter-propagation point on this one.
    d = d[d.propagation_time_s >= 3.0].copy()
    ramp = design_ramp(len(DESIGNS))

    solved = pd.DataFrame([
        solved_data_target(g)
        for _, g in d.groupby(["propagation_time_s", "execution_target"])
    ])
    max_throughput = pd.DataFrame([
        g.loc[g.included_execution.idxmax()]
        for _, g in d.groupby("propagation_time_s")
    ]).sort_values("propagation_time_s")
    balanced_designs = pd.read_csv(
        ROOT / "data/7999/slot_time_historical_benchmark_frontier.csv"
    ).sort_values("propagation_time_s")

    # ---- Figure 1: fixed designs across the slot split -------------------
    panels = [
        ("included_execution", "delivered execution gas (M)",
         "Delivered execution", 1e-6, False),
        ("execution_fill", "share of execution target",
         "Execution target utilization", 1.0, True),
        ("data_limit_hit_fraction", "share of blocks",
         "Blocks included at the data limit", 1.0, True),
        ("execution_limit_hit_fraction", "share of blocks",
         "Blocks included at the execution limit", 1.0, True),
        ("execution_floor_bounded_fraction", "share of blocks",
         "Execution fee bounded at one wei", 1.0, True),
    ]
    fig, axes = plt.subplots(1, 5, figsize=(23.0, 5.1))
    for ax, (column, ylabel, title, scale, as_percent) in zip(axes, panels):
        for (label, te, td), colour in zip(DESIGNS, ramp):
            s = d[(d.execution_target == te) & np.isclose(d.data_target, td)]
            s = s.sort_values("propagation_time_s")
            if s.empty:
                continue
            ax.plot(s.propagation_time_s, s[column] * scale, color=colour,
                    linewidth=1.9, marker="o", markersize=4.5, label=label)
        ax.axvline(BASELINE_T_PROP, color=INK_MUTED, linestyle=":", linewidth=1.2)
        ax.set_xlabel("propagation time (s)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        if as_percent:
            ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.grid(alpha=0.5)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, frameon=False, fontsize=10.5, ncol=5,
        loc="lower center", bbox_to_anchor=(0.5, 0.01),
    )
    axes[0].annotate("current split", xy=(BASELINE_T_PROP, axes[0].get_ylim()[0]),
                     xytext=(4, 6), textcoords="offset points",
                     color=INK_MUTED, fontsize=10)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(PLOTS / "slot_time_fixed_designs.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 2: design-surface heatmaps per split --------------------
    # Absolute levels rather than a difference: the longer splits admit data
    # targets that do not exist at the 3.0s baseline, and those cells would
    # render as "no change" on a difference map.
    times = sorted(d.propagation_time_s.unique())
    all_targets = sorted(d.data_target.unique())
    rows_spec = [
        ("included_execution", 1e-6, "YlGnBu", None,
         "delivered execution (M gas)"),
        ("data_limit_hit_fraction", 1.0, "OrRd", (0.0, 0.7),
         "fraction of blocks included at the data limit"),
    ]
    fig, axes = plt.subplots(len(rows_spec), len(times),
                             figsize=(3.5 * len(times), 3.4 * len(rows_spec)),
                             sharey=True)
    for r, (column, scale, cmap, clim, cbar_label) in enumerate(rows_spec):
        values = d[column] * scale
        vmin, vmax = clim if clim else (float(values.min()), float(values.max()))
        for c, t in enumerate(times):
            ax = axes[r, c]
            s_t = d[d.propagation_time_s == t]
            pivot = s_t.pivot_table(index="execution_target",
                                    columns="data_target", values=column) * scale
            pivot = pivot.reindex(columns=all_targets)
            mesh = ax.pcolormesh(
                np.arange(len(all_targets) + 1),
                np.arange(len(pivot.index) + 1),
                pivot.to_numpy(dtype=float), cmap=cmap, vmin=vmin, vmax=vmax,
                edgecolors="white", linewidth=0.4,
            )
            ax.set_xticks(np.arange(len(all_targets))[::2] + 0.5)
            ax.set_xticklabels([f"{c_/1e6:.0f}" for c_ in all_targets[::2]],
                               fontsize=8.5)
            ax.set_yticks(np.arange(len(pivot.index)) + 0.5)
            ax.set_yticklabels([f"{i/1e6:.0f}" for i in pivot.index], fontsize=8.5)
            if r == 0:
                row0 = s_t.iloc[0]
                ax.set_title(f"{t:.1f}s  |  $L_D$ {row0.data_limit/1e6:.0f}M\n"
                             f"$L_E$ {row0.execution_limit/1e6:.0f}M", fontsize=11)
            if r == len(rows_spec) - 1:
                ax.set_xlabel("data target (M)")
            if c == 0:
                ax.set_ylabel("execution target (M)")
        cbar = fig.colorbar(mesh, ax=axes[r, :], fraction=0.014, pad=0.010)
        cbar.set_label(cbar_label, fontsize=10)
    fig.suptitle("Design surface at each slot-time split "
                 "(white cells: target exceeds its own limit)", y=1.02)
    fig.savefig(PLOTS / "slot_time_delivered_execution_grid.png", dpi=200,
                bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 3 (section 1): the controlled substitution --------------
    # Both panels are the same fixed design, so the targets never move and
    # every change is attributable to the limits alone.
    diag = d[(d.execution_target == 300e6) & np.isclose(d.data_target, 80e6)]
    diag = diag.sort_values("propagation_time_s")

    fig, axes = plt.subplots(1, 2, figsize=(13.6, 5.0))
    axes[0].plot(diag.propagation_time_s, diag.data_limit_hit_fraction,
                 color=RESOURCE_HUES["data"], linewidth=2.2, marker="o",
                 markersize=6, label="blocks full on data")
    axes[0].plot(diag.propagation_time_s, diag.execution_limit_hit_fraction,
                 color=RESOURCE_HUES["execution"], linewidth=2.2, marker="s",
                 markersize=6, label="blocks full on execution")
    axes[0].set_ylabel("fraction of measured blocks")
    axes[0].yaxis.set_major_formatter(PercentFormatter(1.0))
    axes[0].set_title("Fraction of blocks at data or execution limit")
    axes[0].legend(frameon=False, fontsize=11)

    axes[1].plot(diag.propagation_time_s, diag.included_execution / 1e6,
                 color=RESOURCE_HUES["execution"], linewidth=2.2, marker="o",
                 markersize=6)
    for r in diag.itertuples():
        axes[1].annotate(f"{r.included_execution/1e6:.0f}M",
                         (r.propagation_time_s, r.included_execution / 1e6),
                         textcoords="offset points", xytext=(0, -17),
                         ha="center", fontsize=9.5, color=INK_MUTED)
    axes[1].set_ylim(bottom=diag.included_execution.min() / 1e6 - 3.0)
    axes[1].set_ylabel("delivered execution gas (M)")
    axes[1].set_title("Delivered execution")
    for ax in axes:
        ax.set_xlabel("propagation time (s)")
        ax.grid(alpha=0.5)
    fig.suptitle("E300/D80 metrics under different propagation times", y=1.02)
    fig.tight_layout()
    fig.savefig(PLOTS / "slot_time_substitution.png", dpi=200,
                bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 4 (section 2): the two selection standards ---------------
    MAXC, BALC = "#E76F51", "#2A9D8F"
    design_panels = [
        ("included_execution", "delivered execution gas (M)",
         "Delivered execution", 1e-6, False),
        ("execution_fill", "share of the execution target",
         "Execution target utilization", 1.0, "pct_only"),
        ("any_limit_hit_fraction", "fraction of measured blocks",
         "Blocks full on either limit", 1.0, True),
        ("data_limit_hit_fraction", "fraction of measured blocks",
         "Blocks full on data", 1.0, True),
        ("execution_limit_hit_fraction", "fraction of measured blocks",
         "Blocks full on execution", 1.0, True),
        ("execution_floor_bounded_fraction", "fraction of measured blocks",
         "Execution fee bounded at one wei", 1.0, True),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15.6, 8.4))
    for ax, (column, ylabel, title, scale, as_pct) in zip(axes.ravel(),
                                                          design_panels):
        for frame, colour, label in (
            (max_throughput, MAXC, "maximum throughput"),
            (balanced_designs, BALC, "historically anchored"),
        ):
            ax.plot(frame.propagation_time_s, frame[column] * scale,
                    color=colour, linewidth=2.2, marker="o", markersize=6,
                    label=label)
        ax.set_xlabel("propagation time (s)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        if as_pct:
            ax.yaxis.set_major_formatter(PercentFormatter(1.0))
            # Utilization lives in a narrow band near 1; a zero baseline would
            # hide the gap between the two standards, which is the point.
            if as_pct != "pct_only":
                ax.set_ylim(bottom=0)
        ax.grid(alpha=0.5)
    axes[0, 0].legend(frameon=False, fontsize=11, loc="lower right")
    fig.suptitle(
        "Maximum-throughput and historically anchored candidates", y=1.005
    )
    fig.tight_layout()
    fig.savefig(PLOTS / "slot_time_two_designs.png", dpi=200,
                bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 5: outcome trade-offs across every configuration --------
    cmap = plt.get_cmap("viridis")
    norm = plt.Normalize(d.propagation_time_s.min(), d.propagation_time_s.max())
    scatter_panels = [
        ("data_limit_hit_fraction", "blocks included at the data limit"),
        ("execution_limit_hit_fraction", "blocks included at the execution limit"),
        ("execution_floor_bounded_fraction", "execution fee bounded at one wei"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16.8, 5.0), sharey=True)
    for ax, (column, label) in zip(axes, scatter_panels):
        for t_prop, group in d.groupby("propagation_time_s"):
            ax.scatter(group[column], group.included_execution / 1e6,
                       color=cmap(norm(t_prop)), s=26, alpha=0.75,
                       linewidths=0, label=f"{t_prop:.1f}s")
        ax.set_xlabel(label)
        ax.xaxis.set_major_formatter(PercentFormatter(1.0))
        ax.grid(alpha=0.45)
    axes[0].set_ylabel("delivered execution gas (M)")
    axes[0].legend(frameon=False, fontsize=10, title="propagation",
                   title_fontsize=11, loc="upper right")
    fig.suptitle("Outcome trade-offs across the complete target grid")
    fig.tight_layout()
    fig.savefig(PLOTS / "slot_time_outcome_tradeoffs.png", dpi=200,
                bbox_inches="tight")
    plt.close(fig)

    print("wrote 5 figures to plots/")


if __name__ == "__main__":
    main()
