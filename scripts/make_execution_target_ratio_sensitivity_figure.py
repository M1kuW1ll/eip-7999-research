"""Summarize execution target-to-limit sensitivity at selected grid points."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/7999/execution_target_ratio_sensitivity.csv"
OUTPUT = ROOT / "plots/dynamic_execution_target_ratio_sensitivity.png"

RATIO_LABELS = {
    0.5: "1/2",
    0.6: "3/5",
    2.0 / 3.0: "2/3",
    0.75: "3/4",
    0.8: "4/5",
}
SETTINGS = (
    ("E200/D36", 200e6, 0.40),
    ("E225/D45", 225e6, 0.50),
    ("E250/D60", 250e6, 0.667),
    ("E300/D77", 300e6, 77 / 90),
    ("E300/D80", 300e6, 80 / 90),
)
COLOURS = ("#4C78A8", "#F58518", "#54A24B", "#7A5195", "#E45756")
METRICS = (
    ("execution_fill", "Execution target utilization"),
    ("execution_cap_active_fraction", "Execution hard-limit constraint active"),
    (
        "execution_floor_bounded_fraction",
        "Execution fee bounded at one wei",
    ),
    ("data_limit_hit_fraction", "Blocks included at the data limit"),
)


def main() -> None:
    frame = pd.read_csv(INPUT)
    ratios = np.array(sorted(RATIO_LABELS))
    workload_frame = frame[frame.workload == "full_multiscale"]

    plt.rcParams.update(
        {
            "font.size": 14,
            "axes.titlesize": 15,
            "axes.labelsize": 14,
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.alpha": 0.35,
            "figure.facecolor": "white",
        }
    )
    fig, axes = plt.subplots(1, 4, figsize=(22, 5.4), sharex=True)

    for column_index, (metric, title) in enumerate(METRICS):
        ax = axes[column_index]
        for (label, execution_target, data_ratio), colour in zip(
            SETTINGS, COLOURS
        ):
            part = workload_frame[
                np.isclose(workload_frame.execution_target, execution_target)
                & np.isclose(workload_frame.data_target_limit_ratio, data_ratio)
            ].sort_values("execution_target_limit_ratio")
            if len(part) != len(ratios):
                raise AssertionError(f"incomplete sensitivity path for {label}")
            ax.plot(
                part.execution_target_limit_ratio,
                100.0 * part[metric],
                color=colour,
                marker="o",
                linewidth=2.0,
                markersize=5.5,
                label=label,
            )
        ax.set_xticks(ratios, [RATIO_LABELS[value] for value in ratios])
        ax.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
        ax.grid(axis="y")
        ax.set_title(title, pad=10)
        ax.set_xlabel("execution target/limit ratio  $T_E/L_E$")
        if column_index == 0:
            ax.set_ylabel("share of target or blocks")

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=len(labels),
        frameon=False,
        bbox_to_anchor=(0.5, 0.91),
    )
    fig.suptitle(
        "Execution target-to-limit sensitivity at fixed execution and data targets",
        fontsize=18,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.84), w_pad=1.8)
    fig.savefig(OUTPUT, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
