"""Generate paper-ready figures for the shared-fee calibration and comparison."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd
from sklearn.metrics import r2_score


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/shared_fee"
PLOTS = ROOT / "plots"


plt.rcParams.update(
    {
        "font.size": 14,
        "axes.titlesize": 16,
        "axes.labelsize": 14,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "legend.fontsize": 12,
        "figure.dpi": 140,
        "savefig.dpi": 160,
    }
)


def save(fig: plt.Figure, name: str) -> None:
    PLOTS.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOTS / name, bbox_inches="tight", pil_kwargs={"optimize": True})
    plt.close(fig)


def multiplier_bridge() -> None:
    summary = json.loads((DATA / "eip8279_data_multiplier.json").read_text())
    baseline = summary["m_data_7976_7981_baseline"]
    static_increment = summary["incremental_m_data_8131"]
    runtime_increment = summary["incremental_m_data_8279"]
    final = summary["m_data_8131_8279"]
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    ax.bar([0], [baseline], color="#4c78a8", width=0.62)
    ax.bar([1], [static_increment], bottom=[baseline], color="#f2cf5b", width=0.62)
    ax.bar(
        [2],
        [runtime_increment],
        bottom=[baseline + static_increment],
        color="#f58518",
        width=0.62,
    )
    ax.bar([3], [final], color="#54a24b", width=0.62)
    ax.text(0, baseline + 0.03, f"{baseline:.3f}", ha="center")
    ax.text(
        1,
        baseline + static_increment + 0.03,
        f"+{static_increment:.3f}",
        ha="center",
    )
    ax.text(
        2,
        baseline + static_increment + runtime_increment + 0.03,
        f"+{runtime_increment:.3f}",
        ha="center",
    )
    ax.text(3, final + 0.03, f"{final:.3f}", ha="center")
    ax.set_xticks(
        [0, 1, 2, 3],
        [
            "EIP-7976/7981\nbaseline",
            "96-gas EIP-8131\nstatic-floor increment",
            "EIP-8279 BAL\nincrement",
            "Combined\nmultiplier",
        ],
    )
    ax.set_ylabel("data metering multiplier")
    ax.set_ylim(0, final * 1.14)
    ax.set_title("Three-second propagation setting: 96 gas/byte")
    ax.grid(axis="y", alpha=0.25)
    save(fig, "shared_fee_8279_multiplier_bridge.png")


def floor_activation() -> None:
    data = pd.read_csv(DATA / "floor_rate_activation_by_class.csv")
    order = [
        "already floor-bound under static EIP-8131",
        "within 10% of static floor",
        "newly floor-bound primarily because of deployed code",
        "newly floor-bound through other non-code BAL",
    ]
    labels = [
        "already floor-bound",
        "close; pushed across",
        "newly bound by deployed code",
        "newly bound by other BAL",
    ]
    scenarios = pd.read_csv(DATA / "shared_fee_factorial_scenarios.csv")
    adjusted = scenarios[scenarios["benchmark"].eq("fully_optimized")]
    frontier = adjusted.loc[
        adjusted.groupby("propagation_time_s")["shared_limit"].idxmax()
    ].sort_values("propagation_time_s")
    settings = [(f"{row.propagation_time_s:.1f}s", int(row.floor_rate)) for row in frontier.itertuples()]
    rates = [rate for _, rate in settings]
    selected = data[data["floor_class"].isin(order)].pivot(
        index="floor_rate",
        columns="floor_class",
        values="incremental_bal_floor_gas_share",
    ).reindex(rates)
    fig, ax = plt.subplots(figsize=(10.2, 6.2))
    bottom = np.zeros(len(rates))
    colors = ["#4c78a8", "#f58518", "#e45756", "#72b7b2"]
    for floor_class, label, color in zip(order, labels, colors, strict=True):
        values = 100 * selected[floor_class].fillna(0).to_numpy()
        ax.bar(range(len(rates)), values, bottom=bottom, label=label, color=color)
        bottom += values
    ax.set_xticks(
        range(len(rates)),
        [f"{propagation}\nF={rate}" for propagation, rate in settings],
    )
    ax.set_ylabel("share of incremental EIP-8279 gas (%)")
    ax.set_xlabel("propagation setting and selected floor price")
    ax.set_ylim(0, 100)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18), ncol=2)
    ax.grid(axis="y", alpha=0.25)
    save(fig, "shared_fee_8279_floor_activation.png")


def block_uplift() -> None:
    data = pd.read_csv(DATA / "eip8279_block_uplift.csv")
    slope = data["incremental_data_gas_8279"].sum() / data[
        "charged_static_floor_gas"
    ].sum()
    predicted = slope * data["charged_static_floor_gas"]
    r2 = r2_score(data["incremental_data_gas_8279"], predicted)
    # A hexbin keeps 6,000 blocks readable without hiding the long tail.
    fig, ax = plt.subplots(figsize=(8.2, 6.2))
    ax.hexbin(
        data["charged_static_floor_gas"] / 1e6,
        data["incremental_data_gas_8279"] / 1e6,
        gridsize=45,
        mincnt=1,
        bins="log",
        cmap="viridis",
    )
    x = np.linspace(
        0,
        data["charged_static_floor_gas"].quantile(0.995) / 1e6,
        100,
    )
    ax.plot(
        x,
        slope * x,
        color="#e45756",
        linewidth=2,
        label=f"proportional block approximation; $R^2={r2:.3f}$",
    )
    ax.set_xlim(
        0,
        data["charged_static_floor_gas"].quantile(0.995) / 1e6,
    )
    ax.set_ylim(0, data["incremental_data_gas_8279"].quantile(0.995) / 1e6)
    ax.set_xlabel("charged static-floor gas per sampled block (M)")
    ax.set_ylabel("incremental EIP-8279 gas (M)")
    ax.set_title("Three-second propagation setting: 96 gas/byte")
    ax.legend()
    ax.grid(alpha=0.2)
    save(fig, "shared_fee_8279_block_uplift.png")


def safe_limits() -> None:
    data = pd.read_csv(DATA / "shared_vs_7999_physical_capacity.csv")
    fig, ax = plt.subplots(figsize=(8.5, 5.6))
    x = data["propagation_time_s"]
    ax.plot(x, data["execution_capacity_gas"] / 1e6, marker="o", label="execution capacity")
    ax.plot(
        x,
        data["payload_capacity_at_floor_rate"] / 1e6,
        marker="o",
        label="payload capacity at selected floor rate",
    )
    ax.plot(
        x,
        data["safe_shared_limit"] / 1e6,
        marker="o",
        linewidth=3,
        label="fit-implied common limit",
    )
    for _, row in data.iterrows():
        ax.annotate(
            f"F={int(row.floor_rate)}",
            (row.propagation_time_s, row.payload_capacity_at_floor_rate / 1e6),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=11,
        )
    ax.set_xlabel("propagation time (s)")
    ax.set_ylabel("shared-gas capacity (M)")
    ax.legend()
    ax.grid(alpha=0.3)
    save(fig, "shared_fee_8279_safe_limits.png")


def shared_sweep() -> None:
    data = pd.read_csv(DATA / "shared_fee_8279_slot_scenarios.csv")
    fig, axes = plt.subplots(2, 1, figsize=(9, 9), sharex=True, gridspec_kw={"hspace": 0.28})
    for propagation_time, sweep in data.groupby("propagation_time_s"):
        sweep = sweep.sort_values("shared_target")
        floor_rate = int(sweep["floor_rate"].iloc[0])
        label = f"{propagation_time:g}s, F={floor_rate}"
        x = sweep["shared_target"] / 1e6
        axes[0].plot(x, sweep["included_execution_metered"] / 1e6, marker="o", label=label)
        axes[1].semilogy(x, sweep["equilibrium_fee_wei"], marker="o", label=label)
    axes[0].set_ylabel("mean included gas (M)")
    axes[0].set_title("execution gas")
    axes[0].legend()
    axes[0].grid(alpha=0.3)
    axes[1].set_xlabel("shared gas target (M)")
    axes[1].set_ylabel("equilibrium base fee (wei)")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    save(fig, "shared_fee_8279_limit_sweep.png")


def pressure() -> None:
    data = pd.read_csv(DATA / "shared_fee_8279_slot_scenarios.csv")
    selected = data[np.isclose(data["shared_limit"], data["safe_common_limit"])].copy()
    selected = selected.sort_values("propagation_time_s")
    x = selected["propagation_time_s"]
    fig, ax = plt.subplots(figsize=(8.8, 5.8))
    ax.plot(x, 100 * selected["shared_limit_hit_fraction"], marker="o", label="blocks at common limit")
    ax.plot(x, 100 * selected["regular_binding_fraction"], marker="o", label="regular branch determines usage")
    ax.plot(x, 100 * (1 - selected["regular_binding_fraction"]), marker="o", label="state branch determines usage")
    ax.set_xlabel("propagation time (s)")
    ax.set_ylabel("share of measured blocks (%)")
    ax.legend()
    ax.grid(alpha=0.3)
    save(fig, "shared_fee_8279_dynamic_pressure.png")


def state_cap_sensitivity() -> None:
    data = pd.read_csv(DATA / "shared_fee_8279_state_cap_sensitivity.csv")
    cap_order = ["2x", "3x", "4x", "5x", "unrestricted"]
    cap_positions = np.arange(len(cap_order))
    colors = plt.cm.viridis(np.linspace(0.08, 0.88, data.propagation_time_s.nunique()))
    panels = (
        ("included_execution_metered", 1e6, "mean metered execution gas (M)", "execution activity"),
        ("included_state_metered", 1e6, "mean metered state gas (M)", "state activity"),
        ("regular_binding_fraction", 0.01, "share of measured blocks (%)", "regular branch determines usage"),
        ("shared_limit_hit_fraction", 0.01, "share of measured blocks (%)", "blocks at the common limit"),
    )
    fig, axes = plt.subplots(
        2,
        2,
        figsize=(13.5, 9.5),
        sharex=True,
        gridspec_kw={"hspace": 0.30, "wspace": 0.24},
    )
    for color, (propagation_time, group) in zip(
        colors,
        data.groupby("propagation_time_s", sort=True),
        strict=True,
    ):
        ordered = group.set_index("state_demand_cap_label").loc[cap_order]
        for ax, (column, divisor, ylabel, title) in zip(
            axes.flat,
            panels,
            strict=True,
        ):
            ax.plot(
                cap_positions,
                ordered[column] / divisor,
                marker="o",
                linewidth=2.1,
                color=color,
                label=f"{propagation_time:g}s",
            )
            ax.set_ylabel(ylabel)
            ax.set_title(title)
            ax.grid(alpha=0.28)
    for ax in axes[-1]:
        ax.set_xticks(cap_positions, cap_order)
        ax.set_xlabel("maximum price-driven state activity")
    axes[0, 0].legend(title="propagation time", ncol=2)
    save(fig, "shared_fee_8279_state_cap_sensitivity.png")


def three_arm() -> None:
    comparison = pd.read_csv(DATA / "shared_vs_7999_by_slot_split.csv")
    mechanisms = [
        "EIP-7999: maximum throughput",
        "EIP-7999: balanced",
        "One-dimensional shared fee",
    ]
    colors = {
        "EIP-7999: maximum throughput": "#4c78a8",
        "EIP-7999: balanced": "#f58518",
        "One-dimensional shared fee": "#54a24b",
    }
    fig, ax = plt.subplots(figsize=(9, 5.8))
    for mechanism in mechanisms:
        group = comparison[comparison.mechanism.eq(mechanism)].sort_values(
            "propagation_time_s"
        )
        ax.plot(
            group["propagation_time_s"],
            group["included_execution"] / 1e6,
            marker="o",
            linewidth=2.2,
            label=mechanism,
            color=colors[mechanism],
        )
    ax.set_xlabel("propagation time (s)")
    ax.set_ylabel("mean execution or regular gas (M)")
    ax.legend()
    ax.grid(alpha=0.3)
    save(fig, "shared_fee_8279_three_arm_throughput.png")

    fig, ax = plt.subplots(figsize=(8.5, 6.2))
    for mechanism in mechanisms:
        group = comparison[comparison.mechanism.eq(mechanism)].sort_values(
            "propagation_time_s"
        )
        ax.plot(
            group["included_state_gas"] / 1e6,
            group["included_execution"] / 1e6,
            marker="o",
            linewidth=2.2,
            label=mechanism,
            color=colors[mechanism],
        )
    ax.set_xlabel("mean included state gas (M)")
    ax.set_ylabel("mean execution or regular gas (M)")
    ax.legend()
    ax.grid(alpha=0.3)
    save(fig, "shared_fee_8279_three_arm_execution_state.png")


def optimized_floor_schedule() -> None:
    designs = pd.read_csv(DATA / "shared_fee_factorial_designs.csv")
    data = designs[designs["benchmark"].eq("fully_optimized")].copy()
    data = data.sort_values(["propagation_time_s", "shared_target"])
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(13.0, 5.6),
        gridspec_kw={"wspace": 0.28},
    )
    colors = plt.cm.viridis(
        np.linspace(0.08, 0.88, data["propagation_time_s"].nunique())
    )
    for color, (propagation, group) in zip(
        colors,
        data.groupby("propagation_time_s", sort=True),
        strict=True,
    ):
        axes[0].step(
            group["shared_target"] / 1e6,
            group["floor_rate"],
            where="mid",
            linewidth=2.1,
            color=color,
            label=f"{propagation:g}s",
        )
    axes[0].axhline(64, color="0.35", linestyle="--", linewidth=1.4)
    axes[0].set_xlabel("shared gas target (M)")
    axes[0].set_ylabel("lowest sufficient tested floor price (gas/byte)")
    axes[0].set_title("Candidate-specific floor price")
    axes[0].legend(title="propagation time", ncol=2)
    axes[0].grid(alpha=0.28)

    multipliers = pd.read_csv(DATA / "floor_rate_multiplier_sweep.csv")
    multipliers = multipliers.sort_values("floor_rate")
    axes[1].plot(
        multipliers["floor_rate"],
        multipliers["m_data_block"],
        marker="o",
        markersize=4,
        linewidth=2.2,
        color="#f58518",
    )
    axes[1].axvline(65.625, color="0.35", linestyle="--", linewidth=1.4)
    axes[1].annotate(
        "cold-storage break-even",
        (65.625, 2.26),
        xytext=(18, 20),
        textcoords="offset points",
        fontsize=11,
        arrowprops={"arrowstyle": "-", "color": "0.35"},
    )
    axes[1].set_xlabel("floor price (gas/byte)")
    axes[1].set_ylabel("data metering multiplier")
    axes[1].set_title("Transaction-level calibration")
    axes[1].grid(alpha=0.28)
    save(fig, "shared_fee_optimized_floor_schedule.png")


def optimized_factorial() -> None:
    data = pd.read_csv(DATA / "shared_fee_factorial_scenarios.csv")
    data = data[data["floor_payload_feasible"]].copy()
    frontier = data.loc[
        data.groupby(["benchmark", "propagation_time_s"])[
            "included_execution"
        ].idxmax()
    ].copy()
    labels = {
        "proposal_faithful": "F=64, CPSB=1,530",
        "state_matched_64": "F=64, matched CPSB",
        "floor_optimized_only": "derived F, CPSB=1,530",
        "fully_optimized": "derived F, matched CPSB",
    }
    colors = {
        "proposal_faithful": "#4c78a8",
        "state_matched_64": "#72b7b2",
        "floor_optimized_only": "#f58518",
        "fully_optimized": "#54a24b",
    }
    linestyles = {
        "proposal_faithful": "--",
        "state_matched_64": "--",
        "floor_optimized_only": "-",
        "fully_optimized": "-",
    }
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(13.2, 5.8),
        gridspec_kw={"wspace": 0.27},
    )
    for benchmark in labels:
        group = frontier[frontier["benchmark"].eq(benchmark)].sort_values(
            "propagation_time_s"
        )
        axes[0].plot(
            group["propagation_time_s"],
            group["included_execution"] / 1e6,
            marker="o",
            linewidth=2.2,
            linestyle=linestyles[benchmark],
            color=colors[benchmark],
            label=labels[benchmark],
        )
        axes[1].plot(
            group["propagation_time_s"],
            group["annualized_state_growth_gib"],
            marker="o",
            linewidth=2.2,
            linestyle=linestyles[benchmark],
            color=colors[benchmark],
            label=labels[benchmark],
        )
    axes[0].set_xlabel("propagation time (s)")
    axes[0].set_ylabel("mean parent execution activity (M gas-equivalent)")
    axes[0].set_title("Execution delivered by each benchmark")
    axes[0].grid(alpha=0.28)
    axes[1].axhline(
        120,
        color="0.35",
        linestyle=":",
        linewidth=1.6,
        label="120 GiB/year objective",
    )
    axes[1].set_xlabel("propagation time (s)")
    axes[1].set_ylabel("annualized state creation (GiB/year)")
    axes[1].set_title("Physical state growth")
    axes[1].grid(alpha=0.28)
    handles, legend_labels = axes[1].get_legend_handles_labels()
    fig.legend(
        handles,
        legend_labels,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.13),
        ncol=3,
    )
    save(fig, "shared_fee_optimized_factorial.png")


def optimized_state_tail() -> None:
    data = pd.read_csv(DATA / "shared_fee_state_tail.csv")
    order = ["1.5x", "2x", "3x", "4x", "5x", "unrestricted"]
    positions = np.arange(len(order))
    specifications = (
        (
            "proposal_faithful",
            "Baseline one-dimensional",
            "shared_fee_proposal_state_tail.png",
        ),
        (
            "fully_optimized",
            "Floor-adjusted + EIP-8368",
            "shared_fee_optimized_state_tail.png",
        ),
    )
    for benchmark, title, filename in specifications:
        selected = data[data["benchmark"].eq(benchmark)]
        colors = plt.cm.viridis(
            np.linspace(
                0.08,
                0.88,
                selected["propagation_time_s"].nunique(),
            )
        )
        fig, axes = plt.subplots(
            1,
            2,
            figsize=(13.0, 5.8),
            sharex=True,
            gridspec_kw={"wspace": 0.27},
        )
        fig.suptitle(title, fontsize=16)
        for color, (propagation, group) in zip(
            colors,
            selected.groupby("propagation_time_s", sort=True),
            strict=True,
        ):
            group = group.set_index("state_demand_cap_label").loc[order]
            axes[0].plot(
                positions,
                group["included_execution_metered"] / 1e6,
                marker="o",
                linewidth=2.1,
                color=color,
                label=f"{propagation:g}s",
            )
            axes[1].plot(
                positions,
                group["annualized_state_growth_gib"],
                marker="o",
                linewidth=2.1,
                color=color,
                label=f"{propagation:g}s",
            )
        axes[0].set_ylabel("mean metered execution gas (M)")
        axes[0].set_title("Execution response")
        axes[1].set_ylabel("annualized state creation (GiB/year)")
        axes[1].set_title("State-growth response")
        for ax in axes:
            ax.set_xticks(positions, order)
            ax.set_xlabel("maximum price-driven state activity")
            ax.grid(alpha=0.28)
        axes[0].legend(title="propagation time", ncol=2)
        save(fig, filename)


def paired_execution_gain_summary(paths: pd.DataFrame) -> pd.DataFrame:
    """Summarize 7999-minus-adjusted execution on identical workload paths."""
    keys = ["propagation_time_s", "replication"]
    metric = "metered_execution_gas"
    central = paths[paths.window_days.eq(35)]
    baseline = central[central.benchmark.eq("fully_optimized")][keys + [metric]]
    rows = []
    for benchmark in ("balanced", "maximum"):
        selected = central[central.benchmark.eq(benchmark)][keys + [metric]]
        paired = selected.merge(baseline, on=keys, how="outer",
                                suffixes=("_7999", "_shared"), validate="one_to_one")
        if paired.isna().any().any():
            raise ValueError("Execution gains require matching 7999 and shared-fee paths")
        paired["gain"] = paired[f"{metric}_7999"] - paired[f"{metric}_shared"]
        if set(paired.propagation_time_s) != {3.0, 3.5, 4.0, 4.5, 5.0}:
            raise ValueError("Execution gains require all five propagation allocations")
        for propagation_time, group in paired.groupby("propagation_time_s"):
            if set(group.replication) != set(range(32)):
                raise ValueError("Execution gains require the same 32 replications")
            rows.append({
                "benchmark": benchmark,
                "propagation_time_s": propagation_time,
                "mean": group.gain.mean(),
                "p05": group.gain.quantile(0.05),
                "p95": group.gain.quantile(0.95),
            })
    return pd.DataFrame(rows)


def optimized_comparison() -> None:
    """Show execution gains at matched slot allocations and state-growth levels."""
    families = {
        "Proposal-faithful shared fee": ("#7f7f7f", "", "Proposal-faithful shared fee"),
        "Floor- and state-growth-adjusted shared fee": (
            "#54a24b", "//", "Adjusted shared fee",
        ),
        "EIP-7999 balanced (historically anchored)": (
            "#f58518", "..", "EIP-7999 historically anchored",
        ),
        "EIP-7999 maximum throughput": (
            "#4c78a8", "xx", "EIP-7999 maximum throughput",
        ),
    }
    metrics = (
        ("metered_execution_gas", 1e6, "mean metered execution gas (M)", "execution"),
        ("annualized_state_growth_gib", 1, "annualized state growth (GiB/year)", "state_growth"),
        ("hard_limit_fraction", 1, "full block fraction", "hard_limits"),
    )
    keys = ["design_family", "propagation_time_s", "configuration"]
    data = pd.read_csv(DATA / "shared_fee_optimized_comparison.csv")
    data = data[data.design_family.isin(families)].copy()
    intervals = pd.read_csv(DATA / "shared_fee_elasticity_comparison.csv")
    intervals = intervals[intervals.window_days.eq(35) & intervals.available]
    interval_columns = [f"{metric}_{q}" for metric, *_ in metrics for q in ("p05", "p95")]

    # The central replays supply uncertainty for precisely the same 20 settings.
    matched = data.merge(
        intervals[keys + [metric for metric, *_ in metrics]],
        on=keys, validate="one_to_one", suffixes=("", "_replay"),
    )
    assert len(matched) == len(data) == 20
    for metric, *_ in metrics:
        np.testing.assert_allclose(matched[metric], matched[f"{metric}_replay"], rtol=1e-12)
    data = data.merge(intervals[keys + interval_columns], on=keys, validate="one_to_one")
    propagation = np.array([3, 3.5, 4, 4.5, 5])
    x = np.arange(len(propagation))
    width = 0.19

    def draw(ax, metric, scale, ylabel, filename):
        for index, (family, (color, hatch, label)) in enumerate(families.items()):
            group = data[data.design_family.eq(family)].set_index("propagation_time_s")
            group = group.loc[propagation]
            values = group[metric].to_numpy() / scale
            lower = group[f"{metric}_p05"].to_numpy() / scale
            upper = group[f"{metric}_p95"].to_numpy() / scale
            errors = np.vstack([values - lower, upper - values])
            assert np.all(np.isfinite(errors)) and np.all(errors >= 0)
            ax.bar(
                x + (index - 1.5) * width, values, width=width,
                yerr=errors, color=color, hatch=hatch, edgecolor="white",
                linewidth=0.6, label=label,
                error_kw={"ecolor": "0.25", "elinewidth": 1, "capsize": 2},
            )
        ax.set(xlabel="propagation time (s)", ylabel=ylabel)
        ax.set_xticks(x, [f"{t:.1f}" for t in propagation])
        ax.set_xlim(-0.6, len(propagation) - 0.4)
        ax.set_ylim(0, data[f"{metric}_p95"].max() / scale * 1.10)
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        if filename == "hard_limits":
            ax.yaxis.set_major_formatter(PercentFormatter(1))
        if filename == "state_growth":
            ax.axhline(120, color="0.35", linestyle=":", linewidth=1.4)

    def execution_gains():
        metric = "metered_execution_gas"
        adjusted = "Floor- and state-growth-adjusted shared fee"
        selections = (
            ("balanced", "EIP-7999 balanced (historically anchored)", "#f58518", "s"),
            ("maximum", "EIP-7999 maximum throughput", "#4c78a8", "o"),
        )

        def values(family):
            return data[data.design_family.eq(family)].set_index("propagation_time_s").loc[propagation]

        def axes_style(ax, ylabel, ymax):
            ax.set_xlabel("propagation time (s)")
            ax.set_ylabel(ylabel)
            ax.set_xticks(propagation, [f"{t:.1f}" for t in propagation])
            ax.set_xlim(2.94, 5.06)
            ax.set_ylim(0, ymax)
            ax.set_axisbelow(True)
            ax.grid(axis="y", alpha=0.2)
            ax.spines[["top", "right"]].set_visible(False)

        base = values(adjusted)[metric].to_numpy() / 1e6
        anchored = values(selections[0][1])[metric].to_numpy() / 1e6
        assert np.all(anchored > base)
        fig, ax = plt.subplots(figsize=(11.8, 7.0))
        ax.fill_between(propagation, base, anchored, color="#f58518", alpha=0.13,
                        linewidth=0, zorder=1)
        curves = (
            (adjusted, "#54a24b", "D", "-"),
            (selections[0][1], "#f58518", "s", "-"),
            (selections[1][1], "#4c78a8", "o", "-"),
            ("Proposal-faithful shared fee", "#737373", "^", "--"),
        )
        for family, color, marker, linestyle in curves:
            selected = values(family)
            mean = selected[metric].to_numpy() / 1e6
            lower = selected[f"{metric}_p05"].to_numpy() / 1e6
            upper = selected[f"{metric}_p95"].to_numpy() / 1e6
            ax.errorbar(propagation, mean, yerr=[mean - lower, upper - mean],
                        color=color, marker=marker, linestyle=linestyle,
                        markersize=6, linewidth=2.3, elinewidth=0.9, capsize=3,
                        label=families[family][2], zorder=3)
        ax.text(4.03, 151,
                "Additional execution under the\nhistorically anchored EIP-7999 design",
                ha="center", va="center", fontsize=14, color="#9c520d")
        axes_style(ax, "mean included execution gas per block (M)", 310)
        fig.legend(*ax.get_legend_handles_labels(), loc="upper center",
                   bbox_to_anchor=(0.5, 0.99), ncol=2, frameon=False, fontsize=14)
        fig.subplots_adjust(left=0.11, right=0.97, bottom=0.13, top=0.81)
        save(fig, "shared_fee_comparison_execution.png")

        # Pair by replication before taking quantiles: a difference of marginal
        # quantiles would not describe the gain under matched workload draws.
        paths = pd.read_csv(DATA / "shared_fee_elasticity_comparison_paths.csv")
        gains = paired_execution_gain_summary(paths)
        fig, ax = plt.subplots(figsize=(11.8, 6.5))
        for benchmark, family, color, marker in selections:
            summary = gains[gains.benchmark.eq(benchmark)].set_index("propagation_time_s").loc[propagation]
            mean = summary["mean"].to_numpy() / 1e6
            lower = summary.p05.to_numpy() / 1e6
            upper = summary.p95.to_numpy() / 1e6
            np.testing.assert_allclose(mean, values(family)[metric].to_numpy() / 1e6 - base,
                                       rtol=1e-12)
            ax.errorbar(propagation, mean, yerr=[mean - lower, upper - mean],
                        color=color, marker=marker, linewidth=2.3, markersize=6,
                        elinewidth=0.9, capsize=3, label=families[family][2])
            for t, value, high in zip(propagation, mean, upper, strict=True):
                ax.text(t, high + 6, f"+{value:.1f}", ha="center", va="bottom", color=color)
        axes_style(ax, "additional execution over adjusted shared fee\n(M gas per block)", 250)
        fig.legend(*ax.get_legend_handles_labels(), loc="upper center",
                   bbox_to_anchor=(0.5, 0.99), ncol=2, frameon=False, fontsize=14)
        fig.subplots_adjust(left=0.11, right=0.97, bottom=0.14, top=0.85)
        save(fig, "shared_fee_comparison_execution_gain.png")

    with plt.rc_context({"savefig.dpi": 300, "xtick.labelsize": 14, "ytick.labelsize": 14}):
        # Preserve the combined artifact used by the comparison notebook.
        fig, axes = plt.subplots(1, 2, figsize=(13.2, 6.2))
        for ax, specification in zip(axes, metrics[:2], strict=True):
            draw(ax, *specification)
        axes[0].set_title("Metered execution")
        axes[1].set_title("Physical state growth")
        fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center",
                   bbox_to_anchor=(0.5, 0.01), ncol=2, fontsize=13)
        fig.subplots_adjust(bottom=0.28, wspace=0.30)
        save(fig, "shared_fee_optimized_comparison.png")

        for specification in metrics:
            if specification[3] == "execution":
                execution_gains()
                continue
            fig, ax = plt.subplots(figsize=(10.5, 6.6))
            draw(ax, *specification)
            fig.legend(*ax.get_legend_handles_labels(), loc="upper center",
                       bbox_to_anchor=(0.5, 0.99), ncol=2, fontsize=13)
            fig.subplots_adjust(left=0.12, right=0.98, bottom=0.15, top=0.79)
            save(fig, f"shared_fee_comparison_{specification[3]}.png")


def paired_dot_comparison() -> None:
    """Five unrestricted benchmarks on the same central workload paths."""
    data = pd.read_csv(DATA / "shared_fee_elasticity_comparison.csv")
    normalized = pd.read_csv(DATA / "eip8372/normalized_outcomes.csv")
    benchmarks = (
        ("proposal_faithful", "#737373", "^", "Baseline\none-dimensional"),
        ("fully_optimized", "#54a24b", "D", "Floor-adjusted + EIP-8368\none-dimensional"),
        ("normalized_state", "#148878", "P", "Floor-adjusted + EIP-8372\none-dimensional"),
        ("balanced", "#f58518", "s", "EIP-7999 multi-dimensional\nhistorically anchored"),
        ("maximum", "#4c78a8", "o", "EIP-7999 multi-dimensional\nmaximum throughput"),
    )
    data = pd.concat([data, normalized], ignore_index=True)
    data = data[data.window_days.eq(35) & data.available
                & data.benchmark.isin([item[0] for item in benchmarks])].copy()
    assert len(data) == 25
    assert not data.duplicated(["benchmark", "propagation_time_s"]).any()
    propagation = np.array([3.0, 3.5, 4.0, 4.5, 5.0])
    rows = np.arange(len(propagation))
    means = {}

    with plt.rc_context({"savefig.dpi": 180, "xtick.labelsize": 14,
                         "ytick.labelsize": 14, "legend.fontsize": 14}):
        fig, ax = plt.subplots(figsize=(14, 9))
        for benchmark, color, marker, label in benchmarks:
            selected = data[data.benchmark.eq(benchmark)].set_index("propagation_time_s").loc[propagation]
            mean = selected.metered_execution_gas.to_numpy() / 1e6
            means[benchmark] = mean
            ax.plot(mean, rows, linestyle="none", marker=marker, color=color,
                    markersize=8, label=label, zorder=4)
            for value, row in zip(mean, rows, strict=True):
                # Opposite label positions separate the near-equal EIP-8372 and
                # historically anchored EIP-7999 points at three seconds.
                offset = .11 if benchmark in ("proposal_faithful", "balanced") else -.12
                ax.text(value, row + offset, f"{value:.1f}", color=color,
                        ha="center", va="bottom" if offset > 0 else "top", fontsize=14)

        for start, end, color in (
            ("normalized_state", "balanced", "#f58518"),
            ("balanced", "maximum", "#4c78a8"),
        ):
            gain = means[end] - means[start]
            assert np.all(gain > 0)
            ax.hlines(rows, means[start], means[end], color=color,
                      linewidth=2.5, alpha=0.5, zorder=2)
            for left, right, difference, row in zip(
                means[start], means[end], gain, rows, strict=True
            ):
                ax.text((left + right) / 2, row + .34, f"+{difference:.1f}",
                        color=color, ha="center", va="bottom", fontsize=14)

        ax.set_yticks(rows, [f"{t:.1f}" for t in propagation])
        ax.set_ylim(-.5, len(rows) - .35)
        ax.set_xlim(0, 310)
        ax.set_xticks(np.arange(0, 301, 50))
        ax.set_xlabel("mean execution gas usage per block (M)")
        ax.set_ylabel("propagation time (s)")
        ax.set_axisbelow(True)
        ax.grid(axis="x", alpha=.2)
        ax.spines[["top", "right"]].set_visible(False)
        # Three one-dimensional families above the two EIP-7999 selections.
        handles, labels = ax.get_legend_handles_labels()
        fig.legend(handles[:3], labels[:3], loc="upper center",
                   bbox_to_anchor=(.5, 1.0), ncol=3, frameon=False)
        fig.legend(handles[3:], labels[3:], loc="upper center",
                   bbox_to_anchor=(.5, .90), ncol=2, frameon=False)
        fig.subplots_adjust(left=.10, right=.98, bottom=.10, top=.77)
        save(fig, "shared_fee_comparison_execution_paired_dot.png")


def elasticity_robustness_figures() -> None:
    """Separate shared-fee outcomes from matched-propagation execution gains."""
    selected = pd.read_csv(DATA / "shared_fee_elasticity_reselected.csv")
    normalized = pd.read_csv(DATA / "eip8372/normalized_outcomes.csv")
    selected = pd.concat([selected, normalized], ignore_index=True)
    gains = pd.read_csv(DATA / "shared_fee_elasticity_gains.csv")
    styles = (
        (21, "#4c78a8", "o", "-"),
        (35, "#f58518", "s", "--"),
        (60, "#54a24b", "^", ":"),
        (75, "#737373", "D", "-."),
    )
    with plt.rc_context({"legend.fontsize": 14, "xtick.labelsize": 14,
                         "ytick.labelsize": 14, "savefig.dpi": 200}):
        fig, axes = plt.subplots(1, 3, figsize=(18, 5.8), sharex=True, sharey=True)
        for ax, family, title in zip(axes, ("proposal_faithful", "fully_optimized", "normalized_state"),
                ("Baseline", "Floor-adjusted + EIP-8368", "Floor-adjusted + EIP-8372"), strict=True):
            for window, color, marker, linestyle in styles:
                group = selected[(selected.benchmark == family) & selected.window_days.eq(window)]
                group = group.sort_values("propagation_time_s")
                assert len(group) == 5 and group.available.all()
                ax.plot(group.propagation_time_s, group.metered_execution_gas / 1e6,
                        color=color, marker=marker, linestyle=linestyle, linewidth=2.2,
                        label=f"{window}-day vector")
            ax.set_title(title)
            ax.set_xlabel("propagation time (s)")
            ax.set_xticks([3, 3.5, 4, 4.5, 5])
            ax.grid(alpha=.22)
        axes[0].set_ylabel("mean included execution gas per block (M)")
        fig.suptitle("One-dimensional execution under alternative elasticity estimates", fontsize=17)
        fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=4,
                   bbox_to_anchor=(.5, .015), frameon=False)
        fig.subplots_adjust(left=.09, right=.98, top=.81, bottom=.23, wspace=.12)
        save(fig, "shared_fee_elasticity_performance.png")

        fig, axes = plt.subplots(1, 2, figsize=(12.8, 6.2), sharex=True, sharey=True)
        for ax, family, title in zip(axes, ("balanced", "maximum"),
                ("Historically anchored EIP-7999", "Maximum-throughput EIP-7999"), strict=True):
            for window, color, marker, linestyle in styles:
                group = gains[(gains.benchmark == family) & gains.window_days.eq(window)]
                group = group.sort_values("propagation_time_s")
                assert len(group) == 5
                # NaN gaps retain explicitly unavailable selections; never plot them as zero.
                values = group.mean_gain.where(group.available) / 1e6
                ax.plot(group.propagation_time_s, values, color=color, marker=marker,
                        linestyle=linestyle, linewidth=2.2, label=f"{window}-day vector")
            ax.axhline(0, color="#333333", linestyle="--", linewidth=1.5)
            ax.set_title(title)
            ax.set_xlabel("propagation time (s)")
            ax.set_xticks([3, 3.5, 4, 4.5, 5])
            ax.grid(alpha=.22)
        axes[0].set_ylabel("additional execution gas per block (M)")
        axes[0].set_ylim(min(-12, float(gains.mean_gain.min()) / 1e6 - 10),
                         float(gains.mean_gain.max()) / 1e6 + 20)
        fig.suptitle("Additional execution relative to floor-adjusted + EIP-8368", fontsize=17)
        fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=4,
                   bbox_to_anchor=(.5, .07), frameon=False)
        fig.text(.5, .025, "Historically anchored: 60-day eligible only at 5s; no 75-day eligible design in the tested grid.",
                 ha="center", fontsize=12)
        fig.subplots_adjust(left=.09, right=.98, top=.81, bottom=.27, wspace=.12)
        save(fig, "shared_fee_elasticity_execution_gains.png")


def elasticity_state_growth_figure() -> None:
    """Physical state growth for the two original families and frozen EIP-8372 calibration."""
    selected = pd.read_csv(DATA / "shared_fee_elasticity_reselected.csv")
    normalized = pd.read_csv(DATA / "eip8372/normalized_outcomes.csv")
    styles = ((21, "#4c78a8", "o", "-"), (35, "#f58518", "s", "--"),
              (60, "#54a24b", "^", ":"), (75, "#737373", "D", "-."))
    panels = ((selected, "proposal_faithful", "Baseline", (270, 420)),
              (selected, "fully_optimized", "Floor-adjusted + EIP-8368", (80, 125)),
              (normalized, "normalized_state", "Floor-adjusted + EIP-8372", (80, 125)))
    with plt.rc_context({"legend.fontsize": 14, "xtick.labelsize": 14,
                         "ytick.labelsize": 14, "savefig.dpi": 170}):
        fig, axes = plt.subplots(1, 3, figsize=(18, 5.8), sharex=True)
        for ax, (data, family, title, bounds) in zip(axes, panels, strict=True):
            for window, color, marker, linestyle in styles:
                group = data[data.benchmark.eq(family) & data.window_days.eq(window)]
                group = group.sort_values("propagation_time_s")
                assert len(group) == 5 and group.available.all()
                ax.plot(group.propagation_time_s, group.annualized_state_growth_gib,
                        color=color, marker=marker, linestyle=linestyle, linewidth=2.2,
                        label=f"{window}-day vector")
            if family != "proposal_faithful":
                ax.axhline(120, color="#333333", linestyle="--", linewidth=1, alpha=.6)
            ax.set(title=title, xlabel="propagation time (s)",
                   ylabel="annualized state growth (GiB/year)", ylim=bounds)
            ax.set_xticks([3, 3.5, 4, 4.5, 5])
            ax.grid(alpha=.22)
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle("One-dimensional state growth under alternative elasticity estimates", fontsize=17)
        fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=4,
                   bbox_to_anchor=(.5, .015), frameon=False)
        fig.subplots_adjust(left=.06, right=.98, top=.81, bottom=.23, wspace=.31)
        save(fig, "shared_fee_elasticity_state_growth.png")


def elasticity_equilibrium_fee_figure() -> None:
    """Unshocked shared-fee roots, distinct from realized dynamic mean fees."""
    selected = pd.read_csv(DATA / "shared_fee_elasticity_reselected.csv")
    normalized = pd.read_csv(DATA / "eip8372/normalized_outcomes.csv")
    styles = ((21, "#4c78a8", "o", "-"), (35, "#f58518", "s", "--"),
              (60, "#54a24b", "^", ":"), (75, "#737373", "D", "-."))
    panels = ((selected, "proposal_faithful", "Baseline", "equilibrium_execution_fee_wei"),
              (selected, "fully_optimized", "Floor-adjusted + EIP-8368", "equilibrium_execution_fee_wei"),
              (normalized, "normalized_state", "Floor-adjusted + EIP-8372", "equilibrium_fee_wei"))
    with plt.rc_context({"legend.fontsize": 14, "xtick.labelsize": 14,
                         "ytick.labelsize": 14, "savefig.dpi": 170}):
        fig, axes = plt.subplots(1, 3, figsize=(18, 5.8), sharex=True, sharey=True)
        for ax, (data, family, title, metric) in zip(axes, panels, strict=True):
            for window, color, marker, linestyle in styles:
                group = data[data.benchmark.eq(family) & data.window_days.eq(window)]
                group = group.sort_values("propagation_time_s")
                assert len(group) == 5 and group.available.all() and group[metric].gt(0).all()
                ax.plot(group.propagation_time_s, group[metric], color=color, marker=marker,
                        linestyle=linestyle, linewidth=2.2, label=f"{window}-day vector")
            ax.set(title=title, xlabel="propagation time (s)", yscale="log", ylim=(10, 2e6))
            ax.set_xticks([3, 3.5, 4, 4.5, 5])
            ax.grid(alpha=.22)
            ax.spines[["top", "right"]].set_visible(False)
        axes[0].set_ylabel("equilibrium shared base fee (wei, log scale)")
        fig.suptitle("One-dimensional equilibrium fees under alternative elasticity estimates", fontsize=17)
        fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=4,
                   bbox_to_anchor=(.5, .015), frameon=False)
        fig.subplots_adjust(left=.06, right=.98, top=.81, bottom=.23, wspace=.12)
        save(fig, "shared_fee_elasticity_equilibrium_fee.png")


def elasticity_comparison() -> None:
    data = pd.read_csv(DATA / "shared_fee_elasticity_comparison.csv")
    families = {
        "maximum": ("#4c78a8", "o", "EIP-7999 maximum throughput"),
        "balanced": ("#f58518", "s", "EIP-7999 historically anchored"),
        "proposal_faithful": ("#7f7f7f", "^", "Proposal-faithful shared fee"),
        "fully_optimized": ("#54a24b", "D", "Adjusted shared fee"),
    }
    for metric, scale, ylabel, filename in (
        ("metered_execution_gas", 1e6, "mean metered execution gas (M)", "execution"),
        ("hard_limit_fraction", 1, "full block fraction", "hard_limits"),
    ):
        fig, axes = plt.subplots(2, 2, figsize=(13.8, 9.8), sharex=True,
                                 sharey=True, gridspec_kw={"hspace": .32, "wspace": .15})
        upper = float(data.loc[data.available, metric].max()) / scale * 1.15
        for ax, window in zip(axes.flat, (21, 35, 60, 75), strict=True):
            selected = data[data.window_days.eq(window)]
            for family, (color, marker, label) in families.items():
                group = selected[selected.benchmark.eq(family)].sort_values("propagation_time_s")
                ax.plot(group.propagation_time_s, group[metric] / scale,
                        marker=marker, color=color, linewidth=2.2, label=label)
            epsilon = selected.iloc[0].eps_execution
            ax.set_title(rf"{window}-day elasticities ($\epsilon_E={epsilon:.4f}$)")
            ax.set_xticks([3, 3.5, 4, 4.5, 5])
            ax.set_ylim(0, upper)
            ax.grid(alpha=.25)
            if window in (60, 75):
                text = ("Historically anchored: only at 5s" if window == 60
                        else "No historically anchored design in tested grid")
                ax.text(.03, .96, text, transform=ax.transAxes, va="top", fontsize=11)
            if metric == "hard_limit_fraction":
                ax.yaxis.set_major_formatter(PercentFormatter(1))
        for ax in axes[:, 0]:
            ax.set_ylabel(ylabel)
        for ax in axes[1]:
            ax.set_xlabel("propagation time (s)")
        fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="lower center",
                   bbox_to_anchor=(.5, -.025), ncol=2)
        save(fig, f"shared_fee_elasticity_comparison_{filename}.png")


def main() -> None:
    multiplier_bridge()
    floor_activation()
    block_uplift()
    safe_limits()
    shared_sweep()
    pressure()
    state_cap_sensitivity()
    three_arm()
    optimized_floor_schedule()
    optimized_factorial()
    optimized_state_tail()
    optimized_comparison()
    paired_dot_comparison()
    elasticity_comparison()
    elasticity_robustness_figures()
    elasticity_state_growth_figure()
    elasticity_equilibrium_fee_figure()


if __name__ == "__main__":
    main()
