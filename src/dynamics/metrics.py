"""Compact stationary-path summaries for driven replays."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .demand import DEMAND_RESOURCES


def _maximum_true_run(values: pd.Series) -> int:
    longest = 0
    current = 0
    for value in values.astype(bool):
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def summarize_driven_replay(
    replay: pd.DataFrame,
    *,
    burn_in_blocks: int = 0,
) -> pd.DataFrame:
    """Summarize fees, usage, capacity pressure, and the data reserve.

    The returned table has one row per demand resource.  Volatility is the
    sample standard deviation of block-to-block log fee changes.
    """

    if burn_in_blocks < 0:
        raise ValueError("burn_in_blocks must be non-negative")
    if burn_in_blocks >= len(replay):
        raise ValueError("burn_in_blocks must leave at least one observation")
    stationary = replay.iloc[burn_in_blocks:].reset_index(drop=True)
    rows: list[dict[str, float | int | str]] = []
    for resource in DEMAND_RESOURCES:
        fee = stationary[f"{resource}_base_fee_wei"].astype(float)
        if (fee <= 0).any():
            raise ValueError("base fees must be positive for log volatility")
        log_returns = np.log(fee).diff().dropna()
        volatility = (
            float(log_returns.std(ddof=1)) if len(log_returns) >= 2 else math.nan
        )
        limit = stationary[f"{resource}_gas_limit"].dropna()
        has_limit = not limit.empty
        row: dict[str, float | int | str] = {
            "resource": resource,
            "blocks": len(stationary),
            "mean_base_fee_wei": float(fee.mean()),
            "median_base_fee_wei": float(fee.median()),
            "p90_base_fee_wei": float(fee.quantile(0.90)),
            "p99_base_fee_wei": float(fee.quantile(0.99)),
            "maximum_base_fee_wei": float(fee.max()),
            "base_fee_floor_fraction": float((fee == 1).mean()),
            "base_fee_log_return_std": volatility,
            "mean_included_gas": float(stationary[f"{resource}_included_gas"].mean()),
            "p99_included_gas": float(
                stationary[f"{resource}_included_gas"].quantile(0.99)
            ),
            "mean_target_fill": float(
                (
                    stationary[f"{resource}_included_gas"]
                    / stationary[f"{resource}_gas_target"]
                ).mean()
            ),
            "target_or_above_fraction": float(
                (
                    stationary[f"{resource}_included_gas"]
                    >= stationary[f"{resource}_gas_target"]
                ).mean()
            ),
            "own_limit_exceeded_fraction": (
                float(stationary[f"{resource}_own_limit_exceeded"].mean())
                if has_limit
                else math.nan
            ),
            "rationed_fraction": float(stationary[f"{resource}_rationed"].mean()),
            "limit_hit_fraction": (
                float(stationary[f"{resource}_limit_hit"].mean())
                if has_limit
                else math.nan
            ),
            "mean_unserved_gas": float(stationary[f"{resource}_unserved_gas"].mean()),
            "maximum_unserved_gas": float(stationary[f"{resource}_unserved_gas"].max()),
            "reserve_active_fraction": math.nan,
            "maximum_reserve_run_blocks": math.nan,
        }
        if resource == "data":
            reserve = stationary["data_reserve_active"].astype(bool)
            row["reserve_active_fraction"] = float(reserve.mean())
            row["maximum_reserve_run_blocks"] = _maximum_true_run(reserve)
        rows.append(row)
    return pd.DataFrame(rows)
