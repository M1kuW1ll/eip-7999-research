"""Convenience sweeps for bandwidth-limit notebooks."""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

import pandas as pd

from .eip7999_metering import BandwidthMeteringConfig
from .propagation import (
    CONSERVATIVE_P90,
    EMPIRICAL_P90,
    PropagationFit,
    propagation_time_ms,
    safe_payload_bytes,
)
from .scenarios import GasSchedule
from .worst_case import best_strategy, sweep_strategies


def best_strategy_sweep(
    gas_limits: Iterable[int], schedules: Iterable[GasSchedule]
) -> pd.DataFrame:
    rows = []
    for schedule in schedules:
        for gas_limit in gas_limits:
            result = best_strategy(int(gas_limit), schedule)
            row = asdict(result)
            row["schedule"] = row.pop("schedule_name")
            row["best_strategy"] = result.strategy
            rows.append(row)
    return pd.DataFrame(rows)


def add_propagation_times(
    df: pd.DataFrame,
    fits: Iterable[PropagationFit] = (EMPIRICAL_P90, CONSERVATIVE_P90),
    payload_col: str = "total_payload_bytes",
) -> pd.DataFrame:
    out = df.copy()
    for fit in fits:
        out[f"{fit.name}_ms"] = out[payload_col].map(
            lambda payload: propagation_time_ms(payload, fit)
        )
    return out


def safe_payload_cap_sweep(
    windows_ms: Iterable[int],
    safety_factors: Iterable[float],
    fit: PropagationFit = CONSERVATIVE_P90,
) -> pd.DataFrame:
    rows = []
    for window_ms in windows_ms:
        for safety_factor in safety_factors:
            rows.append(
                {
                    "fit": fit.name,
                    "window_ms": int(window_ms),
                    "safety_factor": float(safety_factor),
                    "safe_bandwidth_bytes": safe_payload_bytes(
                        window_ms, fit, safety_factor
                    ),
                }
            )
    return pd.DataFrame(rows)


def eip7999_limit_candidates(
    safe_caps: pd.DataFrame,
    gas_per_safe_byte: int = 16,
) -> pd.DataFrame:
    rows = []
    for cap in safe_caps.to_dict("records"):
        config = BandwidthMeteringConfig(
            safe_bandwidth_bytes=int(cap["safe_bandwidth_bytes"]),
            gas_per_safe_byte=gas_per_safe_byte,
        )
        bandwidth_gas_limit = config.gas_per_safe_byte * config.safe_bandwidth_bytes
        rows.append(
            {
                **cap,
                "bandwidth_gas_limit": bandwidth_gas_limit,
            }
        )
    return pd.DataFrame(rows)


def historical_bandwidth_usage(
    historical: pd.DataFrame,
    config: BandwidthMeteringConfig,
) -> pd.DataFrame:
    from .eip7999_metering import compute_bandwidth_usage

    rows = []
    for row in historical.to_dict("records"):
        usage = compute_bandwidth_usage(
            calldata_zero_bytes=int(row["calldata_zero_bytes"]),
            calldata_nonzero_bytes=int(row["calldata_nonzero_bytes"]),
            bal_rlp_bytes=int(row["bal_bytes"]),
            config=config,
        )
        rows.append({"block_number": row.get("block_number"), **usage})
    return pd.DataFrame(rows)


__all__ = [
    "add_propagation_times",
    "best_strategy_sweep",
    "eip7999_limit_candidates",
    "historical_bandwidth_usage",
    "safe_payload_cap_sweep",
    "sweep_strategies",
]
