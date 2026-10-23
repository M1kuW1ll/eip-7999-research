"""Illustrate the execution/data projection of modeled slot-time hard limits.

Shaded regions are feasible usage combinations, not throughput, gas targets,
or a network-safety guarantee. State capacity is not depicted. This reads the
existing physical model and does not run or modify any demand simulation.
"""
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bandwidth_limits import EMPIRICAL_P90
from shared_fee.optimization import (
    EXECUTION_SPEED_GAS_PER_S, SLOT_BUDGET_S, physical_capacities,
)

PROPAGATION_TIMES_S = (3.0, 3.5, 4.0, 4.5, 5.0)
DATA_GAS_PER_BYTE = 16


def capacity_points():
    """Rows: propagation seconds, execution seconds, execution Mgas, data Mgas."""
    rows = []
    for propagation in PROPAGATION_TIMES_S:
        capacities = physical_capacities(propagation)
        rows.append((propagation, SLOT_BUDGET_S - propagation,
                     capacities["execution_capacity_gas"] / 1e6,
                     DATA_GAS_PER_BYTE * capacities["safe_payload_bytes"] / 1e6))
    return np.asarray(rows)


def feasible_union_vertices(points):
    """Union of the five origin-anchored rectangles, not their convex hull."""
    vertices = [(0., 0.), (points[0, 2], 0.)]
    for index, (_, _, execution, data) in enumerate(points):
        vertices.append((execution, data))
        if index + 1 < len(points):
            vertices.append((points[index + 1, 2], data))
    vertices.append((0., points[-1, 3]))
    return np.asarray(vertices)


def make_figure():
    points = capacity_points()
    colors = plt.get_cmap("viridis")(np.linspace(.08, .80, len(points)))
    with plt.rc_context({"font.size": 16, "axes.labelsize": 18,
                         "axes.titlesize": 19, "xtick.labelsize": 16,
                         "ytick.labelsize": 16, "pdf.fonttype": 42,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "savefig.dpi": 300}):
        fig, ax = plt.subplots(figsize=(8.3, 7.4))
        ax.set(xlim=(0, 665), ylim=(0, 235),
               xlabel="Execution gas usage (M)", ylabel="Data gas usage (M)")
        ax.set_xticks([0, 200, 400, 600])
        ax.set_yticks([0, 50, 100, 150, 200])
        ax.grid(alpha=.12, linewidth=.7)
        ax.set_axisbelow(True)
        ax.set_title("Reallocating a 9-second budget", loc="left", pad=14)
        # Both equations use the axes' Mgas units. The data equation omits
        # only the implemented integer-byte flooring (less than 16 gas).
        execution_formula = (
            rf"$L_E(t) = {EXECUTION_SPEED_GAS_PER_S / 1e6:g}"
            rf"\,({SLOT_BUDGET_S:g}-t)$"
        )
        data_formula = (
            rf"$L_D(t) \approx \frac{{{DATA_GAS_PER_BYTE}\times1024}}{{10^6}}"
            rf"\,\frac{{1000t-{EMPIRICAL_P90.intercept_ms:g}}}"
            rf"{{{EMPIRICAL_P90.slope_ms_per_kb:g}}}$"
        )
        ax.text(20, 225, execution_formula, fontsize=18, va="center")
        ax.text(20, 203, data_formula, fontsize=18, va="center")
        ax.text(20, 179, "$t$: propagation time (s); $L_E,L_D$: M gas",
                fontsize=13, color="#555555", va="center")
        ax.add_patch(Polygon(feasible_union_vertices(points), closed=True,
                             facecolor="#edf2ef", edgecolor="none", zorder=0))
        handles = []
        for (propagation, execution_time, execution, data), color in zip(points, colors, strict=True):
            ax.plot([0, execution, execution], [data, data, 0],
                    color=color, linewidth=1.7, alpha=.8)
            ax.plot(execution, data, "o", color=color, markersize=7, zorder=4)
            handles.append(Line2D([0], [0], color=color, marker="o", linewidth=2,
                                  label=f"{propagation:g} s / {execution_time:g} s"))
        ax.annotate("", xy=(440, 180), xytext=(625, 111),
                    arrowprops={"arrowstyle": "->", "color": "#555555",
                                "lw": 1.7, "connectionstyle": "arc3,rad=0.12"})
        ax.text(550, 185, "More propagation\nLess execution", ha="center",
                color="#555555", fontsize=15, linespacing=1.2)
        ax.legend(handles=handles, title="Propagation / execution", loc="lower left",
                  bbox_to_anchor=(.015, .015), frameon=False, ncol=1,
                  fontsize=14, title_fontsize=15, columnspacing=1.1,
                  handlelength=1.7, labelspacing=.55)
        fig.subplots_adjust(left=.12, right=.98, bottom=.12, top=.92)
    return fig


def main():
    fig = make_figure()
    png = ROOT / "plots/slot_time_capacity_geometry.png"
    pdf = ROOT / "output/pdf/slot_time_capacity_geometry.pdf"
    with plt.rc_context({"pdf.fonttype": 42}):
        for path in (png, pdf):
            path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=.06)
            print(path)
    plt.close(fig)


if __name__ == "__main__":
    main()
