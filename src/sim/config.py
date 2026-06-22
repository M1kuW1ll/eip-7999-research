"""Configuration dataclasses and YAML loading."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class ExecutionStateConfig:
    target_gas: int = 15_000_000
    limit_gas: int = 45_000_000
    initial_base_fee: int = 1_000_000_000
    min_base_fee: int = 1
    base_fee_update_denominator: int = 8


@dataclass(frozen=True)
class BandwidthConfig:
    unit: str = "bytes"
    gas_per_byte: int = 1
    target_bytes: int = 750_000
    limit_bytes: int = 1_500_000
    min_base_fee: int = 1
    update_fraction: float = 17.0
    reserve_mode: str = "none"
    fixed_floor_base_fee: int = 0
    blob_anchor_multiplier: float = 1.0
    propagation_floor_base_fee: int = 0

    @property
    def fake_exponential_denominator(self) -> int:
        """Raw denominator for fake_exponential.

        The YAML keeps ``update_fraction`` as a target-multiple, so a value of
        17 means roughly "one target of excess moves the exponent by 1/17".
        This keeps byte-denominated synthetic runs readable while preserving a
        single knob that can later be replaced by exact EIP-7999 constants.
        """

        return max(1, int(round(self.target_bytes * self.update_fraction)))


@dataclass(frozen=True)
class SyntheticConfig:
    num_blocks: int = 10_000
    seed: int = 7999
    start_block: int = 22_000_000
    start_timestamp: int = 1_781_481_600
    slot_time_seconds: int = 12
    correlation_calldata_bal: float = 0.35
    calldata_burst_probability: float = 0.008
    bal_burst_probability: float = 0.006
    state_burst_probability: float = 0.004
    correlated_stress_probability: float = 0.003
    burst_min_blocks: int = 4
    burst_max_blocks: int = 24
    blob_base_fee_initial: int = 1_000_000_000
    blob_base_fee_volatility: float = 0.04


@dataclass(frozen=True)
class SimulatorConfig:
    execution_state: ExecutionStateConfig = ExecutionStateConfig()
    bandwidth: BandwidthConfig = BandwidthConfig()
    synthetic: SyntheticConfig = SyntheticConfig()


def _coerce_dataclass(cls: type[Any], data: Mapping[str, Any] | None) -> Any:
    if data is None:
        return cls()
    valid = {field.name for field in fields(cls)}
    kwargs = {key: value for key, value in data.items() if key in valid}
    return cls(**kwargs)


def config_from_dict(data: Mapping[str, Any]) -> SimulatorConfig:
    """Build a typed simulator config from a nested dict."""

    return SimulatorConfig(
        execution_state=_coerce_dataclass(
            ExecutionStateConfig, data.get("execution_state")
        ),
        bandwidth=_coerce_dataclass(BandwidthConfig, data.get("bandwidth")),
        synthetic=_coerce_dataclass(SyntheticConfig, data.get("synthetic")),
    )


def load_config(path: str | Path) -> SimulatorConfig:
    """Load a YAML config file."""

    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, Mapping):
        raise TypeError(f"Expected mapping config in {path!s}")
    return config_from_dict(data)
