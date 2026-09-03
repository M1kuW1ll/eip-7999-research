"""Create the slot-time parameter-sensitivity figure and compact tables."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_slot_time_parameter_sensitivity import selection_tables  # noqa: E402

DATA = ROOT / "data/7999"
PLOTS = ROOT / "plots"
FIXED_SOURCE = DATA / "slot_time_e300_d80_parameter_sensitivity.csv"
SURFACE_SOURCE = DATA / "slot_time_parameter_surface_one_at_a_time.csv"

EXECUTION = "#4C78A8"
DATA_COLOUR = "#F58518"
INK = "#1A1A1A"
MUTED = "#666666"
GRID = "#D8D8D8"
WINDOW_COLOURS = {
    21: "#08306B",
    35: "#2171B5",
    60: "#6BAED6",
    75: "#B3DDF2",
}
WINDOW_FULL_BLOCK_COLOURS = {
    21: "#8C2D04",
    35: "#D94801",
    60: "#F16913",
    75: "#FDAE6B",
}
WINDOW_LINESTYLES = {
    21: "-",
    35: "--",
    60: "-.",
    75: ":",
}
WINDOW_MARKERS = {
    21: "o",
    35: "s",
    60: "^",
    75: "D",
}
FULL_BLOCK_EXECUTION = "#B54A00"

plt.rcParams.update(
    {
        "font.size": 14,
        "axes.titlesize": 15,
        "axes.labelsize": 14,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "legend.fontsize": 12,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
    }
)


def configuration(frame: pd.DataFrame) -> pd.Series:
    return (
        "E"
        + (frame.execution_target / 1e6).map(lambda value: f"{value:g}")
        + "/D"
        + (frame.data_target / 1e6).map(lambda value: f"{value:g}")
    )


def joined_configurations(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "none"
    values = (
        frame.assign(configuration=configuration(frame))
        .sort_values(["execution_target", "data_target"])
        .configuration.drop_duplicates()
    )
    return "; ".join(values)


def build_summary_tables(
    surface: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    maximum, balanced = selection_tables(surface)
    maximum.to_csv(DATA / "slot_time_parameter_maximum.csv", index=False)
    balanced.to_csv(DATA / "slot_time_parameter_balanced.csv", index=False)

    throughput_rows = []
    balanced_rows = []
    for propagation_time in sorted(surface.propagation_time_s.unique()):
        maximum_split = maximum[maximum.propagation_time_s.eq(propagation_time)]
        central_maximum = maximum_split[maximum_split.is_central]
        throughput_rows.append(
            {
                "propagation_time_s": propagation_time,
                "central_maximum_configuration": joined_configurations(
                    central_maximum
                ),
                "configurations_across_sensitivities": joined_configurations(
                    maximum_split
                ),
                "tested_specifications": int(len(maximum_split)),
                "maximum_execution_min": float(
                    maximum_split.included_execution.min()
                ),
                "maximum_execution_max": float(
                    maximum_split.included_execution.max()
                ),
            }
        )

        balanced_split = balanced[balanced.propagation_time_s.eq(propagation_time)]
        available = balanced_split[balanced_split.balanced_available.fillna(False)]
        central_balanced = available[available.is_central]
        balanced_rows.append(
            {
                "propagation_time_s": propagation_time,
                "central_balanced_configuration": joined_configurations(
                    central_balanced
                ),
                "configurations_across_available_sensitivities": joined_configurations(
                    available
                ),
                "available_specifications": int(len(available)),
                "tested_specifications": int(len(balanced_split)),
                "balanced_execution_min": float(available.included_execution.min()),
                "balanced_execution_max": float(available.included_execution.max()),
            }
        )
    throughput_summary = pd.DataFrame(throughput_rows)
    balanced_summary = pd.DataFrame(balanced_rows)
    throughput_summary.to_csv(
        DATA / "slot_time_parameter_throughput_summary.csv", index=False
    )
    balanced_summary.to_csv(
        DATA / "slot_time_parameter_balanced_summary.csv", index=False
    )

    global_rows = []
    available_balanced = balanced[balanced.balanced_available.fillna(False)]
    for specification, maximum_spec in maximum.groupby("specification", sort=True):
        maximum_winner = maximum_spec.loc[
            maximum_spec.included_execution.idxmax()
        ]
        balanced_spec = available_balanced[
            available_balanced.specification.eq(specification)
        ]
        balanced_winner = (
            balanced_spec.loc[balanced_spec.included_execution.idxmax()]
            if not balanced_spec.empty
            else None
        )
        row = {
            "specification": specification,
            "window_days": int(maximum_winner.window_days),
            "lambda_bal": float(maximum_winner.lambda_bal),
            "rho_A": float(maximum_winner.rho_A),
            "is_central": bool(maximum_winner.is_central),
            "maximum_propagation_time_s": float(
                maximum_winner.propagation_time_s
            ),
            "maximum_execution_target": float(maximum_winner.execution_target),
            "maximum_data_target": float(maximum_winner.data_target),
            "maximum_included_execution": float(
                maximum_winner.included_execution
            ),
            "historically_anchored_available": balanced_winner is not None,
        }
        for output_column, source_column in (
            ("historically_anchored_propagation_time_s", "propagation_time_s"),
            ("historically_anchored_execution_target", "execution_target"),
            ("historically_anchored_data_target", "data_target"),
            ("historically_anchored_included_execution", "included_execution"),
        ):
            row[output_column] = (
                float(balanced_winner[source_column])
                if balanced_winner is not None
                else np.nan
            )
        global_rows.append(row)
    global_candidates = pd.DataFrame(global_rows)
    global_candidates.to_csv(
        DATA / "slot_time_parameter_global_candidates.csv", index=False
    )
    return maximum, balanced, throughput_summary, balanced_summary, global_candidates


def family_slice(frame: pd.DataFrame, family: str) -> pd.DataFrame:
    if family == "elasticity":
        return frame[frame.lambda_bal.eq(0.0) & frame.rho_A.eq(1.0)]
    if family == "lambda":
        return frame[frame.window_days.eq(35) & frame.rho_A.eq(1.0)]
    if family == "rho":
        return frame[frame.window_days.eq(35) & frame.lambda_bal.eq(0.0)]
    raise ValueError(f"unknown sensitivity family {family}")


def draw_range(
    ax: plt.Axes,
    frame: pd.DataFrame,
    column: str,
    colour: str,
    *,
    scale: float = 1.0,
) -> None:
    grouped = frame.groupby("propagation_time_s")[column]
    low = grouped.min().sort_index()
    high = grouped.max().sort_index()
    ax.fill_between(
        low.index.to_numpy(),
        scale * low.to_numpy(),
        scale * high.to_numpy(),
        color=colour,
        alpha=0.18,
        linewidth=0,
    )


def elasticity_legend(ax: plt.Axes, frame: pd.DataFrame) -> None:
    handles = [
        Patch(
            facecolor=WINDOW_COLOURS[35],
            alpha=0.18,
            label="21–75-day range",
        )
    ]
    labels = ["21–75-day range"]
    for window_days in (21, 35, 60, 75):
        epsilon_execution = frame.loc[
            frame.window_days.eq(window_days), "eps_execution"
        ].iloc[0]
        central = " central" if window_days == 35 else ""
        handles.append(
            Line2D(
                [0],
                [0],
                color=WINDOW_COLOURS[window_days],
                linewidth=2.2,
                linestyle=WINDOW_LINESTYLES[window_days],
                marker=WINDOW_MARKERS[window_days],
                markersize=5,
            )
        )
        labels.append(
            f"{window_days}-day{central} " f"($\\epsilon_E={epsilon_execution:.3f}$)"
        )
    ax.legend(
        handles,
        labels,
        loc="center left",
        bbox_to_anchor=(0.01, 0.54),
        frameon=False,
        fontsize=11,
        ncol=2,
        columnspacing=1.0,
        handlelength=2.0,
    )


def make_execution_figure(fixed: pd.DataFrame) -> None:
    central = fixed[fixed.is_central].sort_values("propagation_time_s")
    families = (
        ("elasticity", "Elasticity windows", "21, 35, 60, and 75 days"),
        ("lambda", "BAL allocation $\\lambda$", "$0$, $0.5$, and $1$"),
        ("rho", "Access scaling $\\rho_A$", "$0.75$, $1$, and $1.25$"),
    )
    fig, axes = plt.subplots(1, 3, figsize=(17.0, 5.4), sharex=True, sharey=True)
    for column_index, (family, title, subtitle) in enumerate(families):
        part = family_slice(fixed, family)
        ax = axes[column_index]
        if family == "elasticity":
            draw_range(
                ax,
                part,
                "included_execution",
                WINDOW_COLOURS[35],
                scale=1e-6,
            )
            for window_days in (21, 35, 60, 75):
                window = part[part.window_days.eq(window_days)].sort_values(
                    "propagation_time_s"
                )
                ax.plot(
                    window.propagation_time_s,
                    window.included_execution / 1e6,
                    color=WINDOW_COLOURS[window_days],
                    linewidth=2.2,
                    linestyle=WINDOW_LINESTYLES[window_days],
                    marker=WINDOW_MARKERS[window_days],
                    markersize=5.5,
                )
            elasticity_legend(ax, part)
        else:
            draw_range(ax, part, "included_execution", EXECUTION, scale=1e-6)
            ax.plot(
                central.propagation_time_s,
                central.included_execution / 1e6,
                color=EXECUTION,
                linewidth=2.4,
                marker="o",
                markersize=6,
            )
        ax.set_title(f"{title}\n{subtitle}")
        ax.set_ylim(120, 300)
        ax.grid(axis="y", alpha=0.55)
        ax.set_xticks(central.propagation_time_s)
    axes[0].set_ylabel("delivered execution gas (M)")
    fig.supxlabel("propagation time (s)", y=0.08, fontsize=14)
    handles = [
        Line2D(
            [0],
            [0],
            color=EXECUTION,
            marker="o",
            linewidth=2.4,
            label="central specification ($\\lambda$ and $\\rho_A$ panels)",
        ),
        Patch(
            facecolor=EXECUTION,
            alpha=0.18,
            label="range from varying the panel parameter",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.005),
        ncol=2,
        frameon=False,
    )
    fig.suptitle(
        "E300/D80 delivered execution across the slot-time allocation",
        fontsize=18,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0.13, 1, 0.94), w_pad=1.6)
    PLOTS.mkdir(exist_ok=True)
    fig.savefig(
        PLOTS / "slot_time_substitution_parameter_sensitivity.png",
        dpi=180,
        bbox_inches="tight",
        pil_kwargs={"optimize": True},
    )
    plt.close(fig)


def make_full_blocks_figure(fixed: pd.DataFrame) -> None:
    central = fixed[fixed.is_central].sort_values("propagation_time_s")
    families = (
        ("elasticity", "Elasticity windows", "21, 35, 60, and 75 days"),
        ("lambda", "BAL allocation $\\lambda$", "$0$, $0.5$, and $1$"),
        ("rho", "Access scaling $\\rho_A$", "$0.75$, $1$, and $1.25$"),
    )
    fig, axes = plt.subplots(1, 3, figsize=(17.0, 5.4), sharex=True, sharey=True)
    for column_index, (family, title, subtitle) in enumerate(families):
        part = family_slice(fixed, family)
        ax = axes[column_index]
        draw_range(ax, part, "data_limit_hit_fraction", DATA_COLOUR)
        draw_range(ax, part, "execution_limit_hit_fraction", FULL_BLOCK_EXECUTION)
        if family == "elasticity":
            for window_days in (21, 35, 60, 75):
                window = part[part.window_days.eq(window_days)].sort_values(
                    "propagation_time_s"
                )
                colour = WINDOW_FULL_BLOCK_COLOURS[window_days]
                marker = WINDOW_MARKERS[window_days]
                ax.plot(
                    window.propagation_time_s,
                    window.data_limit_hit_fraction,
                    color=colour,
                    linewidth=2.1,
                    marker=marker,
                    markersize=5,
                )
                ax.plot(
                    window.propagation_time_s,
                    window.execution_limit_hit_fraction,
                    color=colour,
                    linewidth=1.9,
                    linestyle="--",
                    marker=marker,
                    markersize=4.5,
                )
            window_handles = [
                Line2D(
                    [0],
                    [0],
                    color=WINDOW_FULL_BLOCK_COLOURS[window_days],
                    linewidth=2.1,
                    marker=WINDOW_MARKERS[window_days],
                    markersize=4.5,
                    label=(
                        f"{window_days}-day"
                        + (" central" if window_days == 35 else "")
                        + " "
                        + f"($\\epsilon_E="
                        + f"{part.loc[part.window_days.eq(window_days), 'eps_execution'].iloc[0]:.3f}"
                        + "$)"
                    ),
                )
                for window_days in (21, 35, 60, 75)
            ]
            ax.legend(
                handles=window_handles,
                loc="upper right",
                frameon=False,
                fontsize=11,
                ncol=2,
                columnspacing=1.0,
                handlelength=2.0,
            )
        else:
            ax.plot(
                central.propagation_time_s,
                central.data_limit_hit_fraction,
                color=DATA_COLOUR,
                linewidth=2.4,
                marker="o",
                markersize=5.5,
            )
            ax.plot(
                central.propagation_time_s,
                central.execution_limit_hit_fraction,
                color=FULL_BLOCK_EXECUTION,
                linewidth=2.4,
                linestyle="--",
                marker="s",
                markersize=5.5,
            )
        ax.set_title(f"{title}\n{subtitle}")
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.set_ylim(0, 0.66)
        ax.grid(axis="y", alpha=0.55)
        ax.set_xticks(central.propagation_time_s)
    axes[0].set_ylabel("full block fraction")
    fig.supxlabel("propagation time (s)", y=0.08, fontsize=14)
    handles = [
        Line2D(
            [0],
            [0],
            color=DATA_COLOUR,
            marker="o",
            linewidth=2.4,
            label="data limit (solid)",
        ),
        Line2D(
            [0],
            [0],
            color=FULL_BLOCK_EXECUTION,
            marker="s",
            linestyle="--",
            linewidth=2.4,
            label="execution limit (dashed)",
        ),
        Patch(facecolor=DATA_COLOUR, alpha=0.18, label="data-limit range"),
        Patch(
            facecolor=FULL_BLOCK_EXECUTION,
            alpha=0.18,
            label="execution-limit range",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.005),
        ncol=4,
        frameon=False,
    )
    fig.suptitle(
        "E300/D80 full blocks across the slot-time allocation",
        fontsize=18,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0.13, 1, 0.94), w_pad=1.6)
    fig.savefig(
        PLOTS / "slot_time_substitution_parameter_sensitivity_full_blocks.png",
        dpi=180,
        bbox_inches="tight",
        pil_kwargs={"optimize": True},
    )
    plt.close(fig)


def main() -> None:
    fixed = pd.read_csv(FIXED_SOURCE)
    surface = pd.read_csv(SURFACE_SOURCE)
    maximum, balanced, throughput, balanced_summary, global_candidates = (
        build_summary_tables(surface)
    )
    make_execution_figure(fixed)
    make_full_blocks_figure(fixed)
    print(
        f"wrote sensitivity figures, {len(maximum)} maximum-throughput rows, "
        f"{int(balanced.balanced_available.sum())}/{len(balanced)} balanced rows, "
        f"{len(throughput) + len(balanced_summary)} split-summary rows, and "
        f"{len(global_candidates)} global-candidate rows"
    )


if __name__ == "__main__":
    main()
