"""Deterministic synthetic block-demand generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import SimulatorConfig, SyntheticConfig


@dataclass(frozen=True)
class BlockDemand:
    block_number: int
    timestamp: int
    regular_gas_used: int
    state_gas_used: int
    calldata_bytes: int
    bal_bytes: int
    blob_base_fee: int
    regime: str = "normal"


REGIME_MEANS: dict[str, dict[str, int]] = {
    "normal": {
        "regular_gas_used": 15_500_000,
        "state_gas_used": 2_500_000,
        "calldata_bytes": 170_000,
        "bal_bytes": 250_000,
    },
    "l2_calldata_burst": {
        "regular_gas_used": 18_000_000,
        "state_gas_used": 2_500_000,
        "calldata_bytes": 930_000,
        "bal_bytes": 240_000,
    },
    "bal_burst": {
        "regular_gas_used": 21_000_000,
        "state_gas_used": 3_000_000,
        "calldata_bytes": 190_000,
        "bal_bytes": 1_050_000,
    },
    "state_growth_burst": {
        "regular_gas_used": 22_000_000,
        "state_gas_used": 32_000_000,
        "calldata_bytes": 260_000,
        "bal_bytes": 850_000,
    },
    "correlated_stress": {
        "regular_gas_used": 33_000_000,
        "state_gas_used": 27_000_000,
        "calldata_bytes": 880_000,
        "bal_bytes": 920_000,
    },
}


def _synthetic_config(config: SyntheticConfig | SimulatorConfig) -> SyntheticConfig:
    if isinstance(config, SimulatorConfig):
        return config.synthetic
    return config


def _episode_regimes(config: SyntheticConfig, rng: np.random.Generator) -> list[str]:
    regimes = ["normal"] * config.num_blocks
    starts = [
        ("correlated_stress", config.correlated_stress_probability),
        ("state_growth_burst", config.state_burst_probability),
        ("bal_burst", config.bal_burst_probability),
        ("l2_calldata_burst", config.calldata_burst_probability),
    ]
    max_probability = sum(probability for _, probability in starts)

    i = 0
    while i < config.num_blocks:
        roll = rng.random()
        if roll >= max_probability:
            i += 1
            continue

        threshold = 0.0
        chosen = "normal"
        for regime, probability in starts:
            threshold += probability
            if roll < threshold:
                chosen = regime
                break

        duration = int(
            rng.integers(config.burst_min_blocks, config.burst_max_blocks + 1)
        )
        for j in range(i, min(config.num_blocks, i + duration)):
            regimes[j] = chosen
        i += duration

    return regimes


def _correlated_normals(
    count: int, correlation: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    correlation = float(np.clip(correlation, -0.95, 0.95))
    common = rng.normal(size=count)
    calldata_specific = rng.normal(size=count)
    bal_specific = rng.normal(size=count)
    scale = np.sqrt(1.0 - correlation**2)
    return (
        correlation * common + scale * calldata_specific,
        correlation * common + scale * bal_specific,
    )


def _positive_noisy_int(mean: int, sigma: float, z: float) -> int:
    return max(0, int(round(mean * np.exp(sigma * z))))


def _blob_base_fee_path(config: SyntheticConfig, rng: np.random.Generator) -> np.ndarray:
    shocks = rng.normal(
        loc=0.0,
        scale=config.blob_base_fee_volatility,
        size=config.num_blocks,
    )
    log_path = np.cumsum(shocks)
    path = config.blob_base_fee_initial * np.exp(log_path)
    return np.maximum(1, np.round(path)).astype(np.int64)


def generate_synthetic_blocks(
    config: SyntheticConfig | SimulatorConfig,
) -> pd.DataFrame:
    """Generate block-level demand rows for five explicit activity regimes."""

    config = _synthetic_config(config)
    rng = np.random.default_rng(config.seed)
    regimes = _episode_regimes(config, rng)
    calldata_z, bal_z = _correlated_normals(
        config.num_blocks, config.correlation_calldata_bal, rng
    )
    regular_z = rng.normal(size=config.num_blocks)
    state_z = rng.normal(size=config.num_blocks)
    blob_base_fees = _blob_base_fee_path(config, rng)

    rows: list[dict[str, Any]] = []
    for idx, regime in enumerate(regimes):
        means = REGIME_MEANS[regime]
        rows.append(
            {
                "block_number": config.start_block + idx,
                "timestamp": config.start_timestamp
                + idx * config.slot_time_seconds,
                "regular_gas_used": _positive_noisy_int(
                    means["regular_gas_used"], 0.10, regular_z[idx]
                ),
                "state_gas_used": _positive_noisy_int(
                    means["state_gas_used"], 0.18, state_z[idx]
                ),
                "calldata_bytes": _positive_noisy_int(
                    means["calldata_bytes"], 0.20, calldata_z[idx]
                ),
                "bal_bytes": _positive_noisy_int(
                    means["bal_bytes"], 0.22, bal_z[idx]
                ),
                "blob_base_fee": int(blob_base_fees[idx]),
                "regime": regime,
            }
        )

    return pd.DataFrame(rows)
