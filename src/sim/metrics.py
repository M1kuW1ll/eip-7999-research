"""Replay metrics for synthetic and historical runs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import SimulatorConfig


def _log_return_volatility(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().clip(lower=1)
    if len(values) < 2:
        return 0.0
    return float(np.log(values).diff().dropna().std(ddof=0))


def _max_run_length(flags: pd.Series) -> int:
    max_run = 0
    current = 0
    for flag in flags.fillna(False).astype(bool):
        if flag:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def compute_metrics(df: pd.DataFrame, config: SimulatorConfig) -> pd.DataFrame:
    """Return the MVP metric table as a one-row DataFrame."""

    metrics = {
        "blocks": len(df),
        "bandwidth_base_fee_volatility": _log_return_volatility(
            df["bandwidth_base_fee"]
        ),
        "shared_base_fee_volatility": _log_return_volatility(df["shared_base_fee"]),
        "bandwidth_limit_hit_frequency": float(df["bandwidth_limit_hit"].mean()),
        "execution_state_limit_hit_frequency": float(
            df["execution_state_limit_hit"].mean()
        ),
        "mean_bandwidth_usage_over_target": float(
            df["bandwidth_used"].mean() / config.bandwidth.target_bytes
        ),
        "max_bandwidth_usage_over_limit": float(
            df["bandwidth_used"].max() / config.bandwidth.limit_bytes
        ),
        "hard_floor_activation_frequency": float(
            df["hard_floor_activated"].mean()
        ),
        "hard_floor_activation_run_length": _max_run_length(
            df["hard_floor_activated"]
        ),
        "correlation_calldata_bal": float(
            df["calldata_bytes"].corr(df["bal_bytes"])
        ),
        "correlation_bandwidth_state_gas": float(
            df["bandwidth_used"].corr(df["state_gas_used"])
        ),
    }
    return pd.DataFrame([metrics])
