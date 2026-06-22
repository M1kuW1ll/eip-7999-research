"""Plot helpers for the first synthetic replay milestone."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from .config import SimulatorConfig


def _axis(ax=None, figsize=(11, 4)):
    if ax is not None:
        return ax.figure, ax
    return plt.subplots(figsize=figsize)


def plot_bandwidth_components(
    df: pd.DataFrame, config: SimulatorConfig | None = None, ax=None
):
    fig, ax = _axis(ax)
    x = df["block_number"]
    ax.plot(x, df["calldata_bytes"], label="calldata bytes", linewidth=1.0)
    ax.plot(x, df["bal_bytes"], label="BAL bytes", linewidth=1.0)
    ax.plot(x, df["bandwidth_used"], label="total bandwidth", linewidth=1.2)
    if config is not None:
        ax.axhline(
            config.bandwidth.target_bytes,
            color="black",
            linestyle="--",
            linewidth=0.9,
            label="target",
        )
        ax.axhline(
            config.bandwidth.limit_bytes,
            color="black",
            linestyle=":",
            linewidth=0.9,
            label="limit",
        )
    ax.set_title("Calldata, BAL, and total bandwidth")
    ax.set_xlabel("block")
    ax.set_ylabel("bytes")
    ax.legend(loc="upper right", ncols=2)
    fig.tight_layout()
    return fig, ax


def plot_bandwidth_base_fee(df: pd.DataFrame, ax=None):
    fig, ax = _axis(ax)
    ax.plot(df["block_number"], df["bandwidth_base_fee"], linewidth=1.1)
    ax.set_title("Bandwidth base fee")
    ax.set_xlabel("block")
    ax.set_ylabel("fee units per byte")
    fig.tight_layout()
    return fig, ax


def plot_shared_base_fee(df: pd.DataFrame, ax=None):
    fig, ax = _axis(ax)
    ax.plot(df["block_number"], df["shared_base_fee"], linewidth=1.1)
    ax.set_title("Shared execution/state base fee")
    ax.set_xlabel("block")
    ax.set_ylabel("fee units per gas")
    fig.tight_layout()
    return fig, ax


def plot_bandwidth_usage_ratio(
    df: pd.DataFrame, config: SimulatorConfig | None = None, ax=None
):
    fig, ax = _axis(ax)
    ax.plot(df["block_number"], df["bandwidth_usage_ratio"], linewidth=1.0)
    if config is not None:
        target_ratio = config.bandwidth.target_bytes / config.bandwidth.limit_bytes
        ax.axhline(
            target_ratio,
            color="black",
            linestyle="--",
            linewidth=0.9,
            label="target / limit",
        )
        ax.legend(loc="upper right")
    ax.axhline(1.0, color="black", linestyle=":", linewidth=0.9)
    ax.set_title("Bandwidth usage / limit")
    ax.set_xlabel("block")
    ax.set_ylabel("ratio")
    fig.tight_layout()
    return fig, ax


def plot_state_vs_bal(df: pd.DataFrame, ax=None):
    fig, ax = _axis(ax, figsize=(6, 5))
    ax.scatter(df["state_gas_used"], df["bal_bytes"], s=8, alpha=0.35)
    ax.set_title("State gas vs BAL bytes")
    ax.set_xlabel("state gas used")
    ax.set_ylabel("BAL bytes")
    fig.tight_layout()
    return fig, ax


def make_main_plots(df: pd.DataFrame, config: SimulatorConfig) -> dict[str, plt.Figure]:
    """Create the five first-milestone figures."""

    figures = {}
    figures["bandwidth_components"] = plot_bandwidth_components(df, config)[0]
    figures["bandwidth_base_fee"] = plot_bandwidth_base_fee(df)[0]
    figures["shared_base_fee"] = plot_shared_base_fee(df)[0]
    figures["bandwidth_usage_ratio"] = plot_bandwidth_usage_ratio(df, config)[0]
    figures["state_vs_bal"] = plot_state_vs_bal(df)[0]
    return figures
