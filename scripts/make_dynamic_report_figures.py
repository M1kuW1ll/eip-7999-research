"""Figures for the dynamic simulation report.

Colour follows the job each encoding does. Designs differ by a continuous
parameter, the data target ratio, so they take a sequential single-hue ramp
light to dark rather than arbitrary categorical hues. Resources and mechanisms
are identities, so they take categorical hues in fixed order.

The categorical triple was checked for colour-vision deficiency rather than
assumed safe: blue/orange/green, the obvious choice, collapses under
protanopia to a pair separation of 3.5 in OKLab hundredths. Blue/orange/teal
holds at 17.1 protan, 18.0 deutan, 16.5 tritan against a floor of 8, and 19.0
for normal vision against a floor of 15.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dynamics.batched_replay import BatchConfig, run_batch  # noqa: E402
from dynamics.empirical_shocks import (  # noqa: E402
    DEFAULT_BLOCK_LENGTH, build_shock_panel, moving_block_bootstrap,
)
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

PLOTS = ROOT / "plots"
BLOCKS_PER_DAY = 7_200
N_SEEDS = 32
STATE_TARGET = 75_000_000.0
DATA_LIMIT = 90e6
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}

DESIGNS = [
    ("E200/D45", 200e6, 45e6), ("E225/D45", 225e6, 45e6),
    ("E250/D60", 250e6, 60e6), ("E300/D77", 300e6, 77e6),
    ("E300/D85", 300e6, 85e6),
]
RESOURCE_HUES = {"execution": "#4C78A8", "data": "#F58518", "state": "#72B7B2"}
MECHANISM_HUES = {"eip7999": "#B22222", "glamsterdam": "#4C78A8"}
INK, INK_MUTED, GRID = "#1A1A1A", "#666666", "#D8D8D8"

plt.rcParams.update({
    "font.size": 12, "axes.titlesize": 13.5, "axes.labelsize": 12,
    "axes.edgecolor": GRID, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK_MUTED, "ytick.color": INK_MUTED,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.6, "figure.facecolor": "white",
})


def design_ramp(n):
    """Sequential single hue, light to dark, for an ordered parameter."""
    return plt.cm.Blues(np.linspace(0.38, 0.92, n))


def build(designs, batch_repeat, demand, anchor):
    repeat = lambda v: np.repeat(np.asarray(v, dtype=float), batch_repeat)
    ones = np.ones(len(designs) * batch_repeat)
    return BatchConfig(
        execution_target=repeat([d[1] for d in designs]),
        execution_limit=repeat([2 * d[1] for d in designs]),
        data_target=repeat([d[2] for d in designs]),
        data_limit=ones * DATA_LIMIT, state_target=ones * STATE_TARGET,
        eps_execution=ones * EPS["execution"], eps_data=ones * EPS["data"],
        eps_state=ones * EPS["state"],
        w_execution=ones * float(demand.w_execution_reference),
        w_state=ones * float(demand.w_state_reference), rho_A=ones,
        m_execution=float(demand.m_execution), m_state=float(demand.m_state),
        m_data_static=float(anchor.static_data_metering_multiplier),
        q_execution_0=float(demand.q_execution_per_block),
        q_state_0=float(demand.q_state_per_block),
        g_static_0=float(anchor.static_data_gas_per_block),
        p0_gwei=float(demand.base_fee_ref_gwei),
    )


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    panel = build_shock_panel(
        ROOT / "data/contiguous/contiguous_block_panel_2026-05-18_14d.csv",
        [ROOT / "data/contiguous/contiguous_runtime_bal_full14d_25118359_25218797.csv"],
        ROOT / "data/7999/bal_decomposition_demand_parameters.csv",
    )
    n_blocks = 2 * BLOCKS_PER_DAY
    shocks = moving_block_bootstrap(panel, N_SEEDS, n_blocks, DEFAULT_BLOCK_LENGTH,
                                    np.random.default_rng(20260813))
    cfg = build(DESIGNS, N_SEEDS, demand, anchor)
    colours = design_ramp(len(DESIGNS))

    # Warm equilibrium per design, then cold and warm replays with paths kept.
    warm_cfg = build(DESIGNS, 1, demand, anchor)
    warm_fees = run_batch(warm_cfg, np.ones((len(DESIGNS), 20_000, 4)),
                          bundle_cost_equivalent_start(warm_cfg))["final_base_fee_wei"]
    cold = run_batch(cfg, shocks, bundle_cost_equivalent_start(cfg), return_paths=True)
    warm = run_batch(cfg, shocks, np.repeat(warm_fees, N_SEEDS, axis=0), return_paths=True)

    hours = np.arange(n_blocks) * 12 / 3600

    # ---- Figure 1: cold-start convergence -------------------------------
    # All three fees are shown, not just data. Each resource starts from the
    # historical anchor's effective price for that resource and has its own
    # equilibrium to reach, and the three do not arrive together: how far a fee
    # has to travel depends on how far its design's target sits from what the
    # anchor workload wanted, which differs per resource.
    #
    # Each path is normalised by a warm run on identical shocks rather than by a
    # single equilibrium level, because a fee has no level to settle at, only a
    # distribution -- the warm run's own hourly median already spans 2x with no
    # transient present. The paired ratio cancels that shared variation, so
    # every resource converges to 1 and the three become comparable on one axis
    # despite pricing different gas units at wildly different levels.
    reference = DESIGNS.index(("E225/D45", 225e6, 45e6))
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.0),
                             gridspec_kw={"width_ratios": [1.35, 1]})
    ax = axes[0]
    # The transient is measured as a first crossing: the first block at which the
    # cold path is no longer above the warm path. The cold start begins orders of
    # magnitude high and decays monotonically, so the crossing is unambiguous and
    # needs no tolerance. A band criterion would have to be chosen instead, and
    # because base fees are integers settling anywhere from one wei to hundreds,
    # a band is loose for one resource and strict for another -- it measures the
    # fee level rather than the speed of convergence. The crossing is non-strict
    # because fees are integers: once the paths have merged they hold the same
    # value exactly, and a strict test would then wait for an unrelated downward
    # fluctuation long after the transient had cleared.
    def crossing(paths_slice, j):
        cold_path = np.median(cold["fee_paths"][paths_slice, :, j], axis=0)
        warm_path = np.median(warm["fee_paths"][paths_slice, :, j], axis=0)
        ratio = cold_path / np.maximum(warm_path, 1.0)
        settled = np.flatnonzero(ratio <= 1.0)
        return ratio, (int(settled[0]) if len(settled) else -1)

    ref_slice = slice(reference * N_SEEDS, (reference + 1) * N_SEEDS)
    for j, resource in enumerate(("execution", "data", "state")):
        ratio, blocks = crossing(ref_slice, j)
        ax.plot(np.arange(n_blocks), ratio, color=RESOURCE_HUES[resource],
                linewidth=1.7, label=f"{resource} — {blocks} blocks")
    ax.axhline(1.0, color=INK_MUTED, linewidth=0.9, linestyle="--")
    ax.set_yscale("log")
    ax.set_xscale("log")
    ax.set_xlim(1, n_blocks)
    ax.set_xlabel("blocks since activation")
    ax.set_ylabel("cold fee / warm fee, same shocks")
    ax.set_title(f"Three fees, three starting points, {DESIGNS[reference][0]}")
    ax.annotate("warm-start path", xy=(n_blocks * 0.22, 1.0), xytext=(0, 8),
                textcoords="offset points", color=INK_MUTED, fontsize=11)
    ax.legend(frameon=False, loc="upper right", title="resource", title_fontsize=11)
    ax.grid(alpha=0.5, which="both")

    ax = axes[1]
    convergence = {}
    for i, (name, _te, _td) in enumerate(DESIGNS):
        sl = slice(i * N_SEEDS, (i + 1) * N_SEEDS)
        convergence[name] = [crossing(sl, j)[1] for j in range(3)]
    y = np.arange(len(DESIGNS))
    height = 0.26
    for j, resource in enumerate(("execution", "data", "state")):
        ax.barh(y + (1 - j) * height, [convergence[d[0]][j] for d in DESIGNS],
                height=height, color=RESOURCE_HUES[resource], label=resource)
    ax.set_yticks(y, [d[0] for d in DESIGNS])
    ax.invert_yaxis()
    ax.set_xlabel("blocks until the cold path meets the warm path")
    ax.set_title("Execution starts furthest from its equilibrium")
    ax.legend(frameon=False, loc="lower right", title="resource", title_fontsize=11)
    ax.grid(axis="x", alpha=0.5)
    fig.tight_layout()
    fig.savefig(PLOTS / "dynamic_cold_start_convergence.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 2: steady state around equilibrium ----------------------
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.0))
    sl = slice(reference * N_SEEDS, (reference + 1) * N_SEEDS)
    settled = slice(BLOCKS_PER_DAY, None)

    ax = axes[0]
    # An empirical CDF rather than a histogram, because the three resources are
    # not equally continuous. Execution settles at a median of a few tens of wei
    # and is therefore genuinely discrete -- one integer step near its median is
    # wider than a fixed log-width bin, so a histogram renders it as a comb of
    # empty gaps, which is an artefact of the binning rather than the fee. State
    # settles near 2e6 wei, where the same integer grid is effectively
    # continuous. A CDF treats both correctly and needs no bin choice.
    for j, resource in enumerate(("execution", "data", "state")):
        series = np.sort(warm["fee_paths"][sl, settled, j].ravel())
        p5, p95 = np.percentile(series, [5, 95])
        span = (f"{p5/1e6:.2g}–{p95/1e6:.1f}M wei" if p95 > 1e5
                else f"{p5:,.0f}–{p95:,.0f} wei")
        ax.plot(np.log10(series / np.median(series)),
                np.linspace(0, 1, series.size), color=RESOURCE_HUES[resource],
                linewidth=1.9, label=f"{resource} — {span}")
    ax.axvline(0, color=INK_MUTED, linewidth=0.9, linestyle="--")
    for level in (0.05, 0.95):
        ax.axhline(level, color=GRID, linewidth=0.8, linestyle=":")
    ax.set_xlabel("base fee relative to its median, log$_{10}$")
    ax.set_ylabel("fraction of blocks below")
    ax.set_title("All three fees span more than a decade")
    ax.legend(frameon=False, loc="upper left", title="90% of blocks lie in",
              title_fontsize=11)
    ax.grid(alpha=0.5)

    ax = axes[1]
    targets = {"execution": DESIGNS[reference][1], "data": DESIGNS[reference][2],
               "state": STATE_TARGET}
    for j, resource in enumerate(("execution", "data", "state")):
        series = warm["used_paths"][sl, settled, j].ravel() / targets[resource]
        ax.hist(series, bins=70, histtype="step", linewidth=1.8,
                color=RESOURCE_HUES[resource], label=resource, density=True)
    ax.axvline(1.0, color=INK_MUTED, linewidth=0.9, linestyle="--")
    ax.annotate("target", xy=(1.0, ax.get_ylim()[1] * 0.92), xytext=(5, 0),
                textcoords="offset points", color=INK_MUTED, fontsize=11)
    ax.axvline(DATA_LIMIT / DESIGNS[reference][2], color=RESOURCE_HUES["data"],
               linewidth=1.2, linestyle=":")
    ax.annotate("data limit", xy=(DATA_LIMIT / DESIGNS[reference][2], ax.get_ylim()[1] * 0.72),
                xytext=(5, 0), textcoords="offset points", color=INK_MUTED, fontsize=11)
    ax.set_xlim(0, 2.6)
    ax.set_xlabel("included gas relative to target")
    ax.set_ylabel("density")
    ax.set_title(f"Utilisation around target, {DESIGNS[reference][0]}")
    ax.legend(frameon=False)
    ax.grid(alpha=0.5)
    fig.tight_layout()
    fig.savefig(PLOTS / "dynamic_steady_state_distributions.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 3: design surface ---------------------------------------
    surface = pd.read_csv(ROOT / "data/7999/design_surface.csv")
    surface = surface[surface.data_limit == DATA_LIMIT]
    execution_targets = sorted(surface.execution_target.unique())
    ramp = design_ramp(len(execution_targets))
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.0))
    for target, colour in zip(execution_targets, ramp):
        sub = surface[surface.execution_target == target].sort_values("target_ratio")
        axes[0].plot(sub.target_ratio, sub.included_execution / 1e6, color=colour,
                     linewidth=1.8, marker="o", markersize=4.5,
                     label=f"$T_E$ {target/1e6:.0f}M")
        axes[1].plot(sub.target_ratio, sub.data_limit_hit_fraction, color=colour,
                     linewidth=1.8, marker="o", markersize=4.5)
    axes[0].set_xlabel("data target ratio  $T_D/L_D$")
    axes[0].set_ylabel("delivered execution gas (M)")
    axes[0].set_title("Delivered execution saturates")
    axes[0].legend(frameon=False, fontsize=11)
    axes[0].grid(alpha=0.5)
    axes[1].set_xlabel("data target ratio  $T_D/L_D$")
    axes[1].set_ylabel("fraction of blocks at the data limit")
    axes[1].set_title("Congestion follows the ratio, not the execution target")
    axes[1].annotate("all seven execution targets\ncollapse onto one curve",
                     xy=(0.30, 0.36), color=INK_MUTED, fontsize=11)
    axes[1].grid(alpha=0.5)
    fig.tight_layout()
    fig.savefig(PLOTS / "dynamic_design_surface.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 4: saturation compresses the price signal ---------------
    stage_b = pd.read_csv(ROOT / "data/7999/stage_b_stresses.csv")
    stage_b = stage_b[(stage_b.start == "warm") & (stage_b.stress == "baseline")].copy()
    stage_b["ratio"] = stage_b.design.str.split("_D").str[1].astype(float) * 1e6 / DATA_LIMIT
    stage_b = stage_b.sort_values("ratio")
    # E200/D45 and E225/D45 share a target ratio, so no line is drawn through
    # these points: a curve would have to pass vertically through two designs at
    # the same x, and the gap between them at that one ratio is itself worth
    # seeing, since it bounds how much of the vertical spread is not the ratio.
    # Label offsets are set per point rather than uniformly, because the two
    # coincident designs would otherwise print on top of each other.
    # The two coincident designs sit on top of each other in the congestion
    # panel and are well separated in the price panel, so the offsets differ by
    # panel rather than being shared.
    offsets_congestion = {"E200_D45": (11, -11), "E225_D45": (11, 4), "E250_D60": (0, 11),
                          "E300_D77": (0, 11), "E300_D85": (0, 11)}
    offsets_price = {"E200_D45": (11, -4), "E225_D45": (11, -4), "E250_D60": (0, 11),
                     "E300_D77": (0, 11), "E300_D85": (0, 11)}
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.0), sharex=True)
    for ax, column, title, ylabel, label_offsets in (
        (axes[0], "data_limit_hit_fraction", "Congestion rises with the target ratio",
         "fraction of blocks at the data limit", offsets_congestion),
        (axes[1], "peak_data_fee_multiple", "but past two thirds the price response collapses",
         "peak data-fee multiple within a day", offsets_price),
    ):
        ax.scatter(stage_b.ratio, stage_b[column], color="#B22222", s=58, zorder=3)
        for _, row in stage_b.iterrows():
            dx, dy = label_offsets[row.design]
            ax.annotate(row.design.replace("_", "/"), xy=(row.ratio, row[column]),
                        xytext=(dx, dy), textcoords="offset points",
                        ha="left" if dx > 0 else "center",
                        fontsize=10.5, color=INK_MUTED)
        ax.set_xlabel("data target ratio  $T_D/L_D$")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(alpha=0.5)
        ax.margins(x=0.13, y=0.20)
    fig.tight_layout()
    fig.savefig(PLOTS / "dynamic_saturation_pathology.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 5: mechanism comparison ---------------------------------
    comparison = pd.read_csv(ROOT / "data/7999/glamsterdam_comparison.csv")
    g = comparison[comparison.mechanism == "glamsterdam"].sort_values("gas_limit")
    e = comparison[comparison.mechanism == "eip7999"]
    fig, ax = plt.subplots(figsize=(8.4, 5.6))
    ax.plot(g.state_gas / 1e6, g.included_execution / 1e6,
            color=MECHANISM_HUES["glamsterdam"], linewidth=2.0, marker="o", markersize=7,
            label="Glamsterdam, one shared fee")
    for _, row in g.iterrows():
        last = row.gas_limit == g.gas_limit.max()
        ax.annotate(f"{row.gas_limit/1e6:.0f}M", xy=(row.state_gas / 1e6, row.included_execution / 1e6),
                    xytext=(-7 if last else 7, -3 if last else -3),
                    ha="right" if last else "left",
                    textcoords="offset points", fontsize=10.5, color=INK_MUTED)
    ax.scatter(e.state_gas / 1e6, e.included_execution / 1e6, s=95, zorder=5,
               color=MECHANISM_HUES["eip7999"], label="EIP-7999, three separate fees")
    for _, row in e.iterrows():
        ax.annotate(row.design.replace("_", "/"),
                    xy=(row.state_gas / 1e6, row.included_execution / 1e6),
                    xytext=(9, -4), textcoords="offset points", fontsize=10.5, color=INK_MUTED)
    # The finding is the position of the two groups relative to each other, not
    # either curve on its own, so it is stated on the figure: raising the shared
    # limit walks along the blue curve and buys execution only by buying state
    # creation with it, and no point on that curve reaches the region the
    # separately priced designs occupy.
    ax.annotate("separate fees reach a region no\nshared gas limit does: more execution\n"
                "at a fraction of the state creation",
                xy=(0.055, 0.70), xycoords="axes fraction", fontsize=11,
                color=INK_MUTED, va="top")
    ax.set_xlabel("state gas per block (M)")
    ax.set_ylabel("delivered execution gas (M)")
    ax.set_title("Execution bought per unit of state creation")
    ax.legend(frameon=False, loc="upper right")
    ax.grid(alpha=0.5)
    ax.margins(x=0.09)
    fig.tight_layout()
    fig.savefig(PLOTS / "dynamic_mechanism_frontier.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    print("wrote five figures to plots/:")
    for name in ("cold_start_convergence", "steady_state_distributions", "design_surface",
                 "saturation_pathology", "mechanism_frontier"):
        print(f"  dynamic_{name}.png")
    print("\nblocks until the cold path is no longer above the warm path:")
    for name, blocks in convergence.items():
        parts = "  ".join(f"{r} {b}" for r, b in
                          zip(("execution", "data", "state"), blocks))
        print(f"  {name:>10}   {parts}")


if __name__ == "__main__":
    main()
