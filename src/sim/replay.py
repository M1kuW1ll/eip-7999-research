"""Passive replay for Mechanism A."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd

from .basefee import fake_exponential, update_excess
from .config import SimulatorConfig
from .eip8037 import execution_state_bottleneck, update_shared_base_fee_8037_style


def _records(blocks: pd.DataFrame | Iterable[Any]) -> list[dict[str, Any]]:
    if isinstance(blocks, pd.DataFrame):
        return blocks.to_dict("records")

    records = []
    for block in blocks:
        if is_dataclass(block):
            records.append(asdict(block))
        elif isinstance(block, dict):
            records.append(dict(block))
        else:
            records.append(dict(block))
    return records


def _hard_floor_base_fee(block: dict[str, Any], config: SimulatorConfig) -> int:
    """Return a synthetic hard-floor base fee for explicit toy scenarios.

    This is not the EIP-7999/EIP-7918 reserve path. The current mechanism
    modules implement that reserve through excess-gas updates.
    """

    bandwidth = config.bandwidth
    mode = bandwidth.reserve_mode.lower()

    if mode == "none":
        return 0
    if mode == "fixed_floor":
        return int(bandwidth.fixed_floor_base_fee)
    if mode == "blob_anchor":
        return int(float(block.get("blob_base_fee", 0)) * bandwidth.blob_anchor_multiplier)
    if mode == "propagation_floor":
        return int(bandwidth.propagation_floor_base_fee)

    raise ValueError(f"Unknown bandwidth reserve_mode: {bandwidth.reserve_mode}")


def replay(blocks: pd.DataFrame | Iterable[Any], config: SimulatorConfig) -> pd.DataFrame:
    """Replay block demand through Mechanism A.

    Mechanism A separates bandwidth pricing for calldata + BAL bytes while
    preserving the EIP-8037-style shared execution/state base fee.
    """

    rows = []
    shared_base_fee = int(config.execution_state.initial_base_fee)
    bandwidth_excess = 0

    for idx, block in enumerate(_records(blocks)):
        regular_gas_used = int(block["regular_gas_used"])
        state_gas_used = int(block["state_gas_used"])
        calldata_bytes = int(block["calldata_bytes"])
        bal_bytes = int(block.get("bal_bytes", 0))

        execution_state_used = execution_state_bottleneck(
            regular_gas_used=regular_gas_used,
            state_gas_used=state_gas_used,
        )
        bandwidth_used = calldata_bytes + bal_bytes

        raw_bandwidth_base_fee = fake_exponential(
            config.bandwidth.min_base_fee,
            bandwidth_excess,
            config.bandwidth.fake_exponential_denominator,
        )
        bandwidth_hard_floor_base_fee = _hard_floor_base_fee(block, config)
        bandwidth_base_fee = max(
            raw_bandwidth_base_fee,
            bandwidth_hard_floor_base_fee,
        )
        hard_floor_activated = (
            bandwidth_hard_floor_base_fee > raw_bandwidth_base_fee
        )

        bandwidth_limit_hit = bandwidth_used >= config.bandwidth.limit_bytes
        execution_state_limit_hit = (
            execution_state_used >= config.execution_state.limit_gas
        )

        shared_cost = shared_base_fee * (regular_gas_used + state_gas_used)
        bandwidth_cost = (
            bandwidth_base_fee * bandwidth_used * config.bandwidth.gas_per_byte
        )

        rows.append(
            {
                "block_number": block.get("block_number", idx),
                "timestamp": block.get("timestamp"),
                "regime": block.get("regime"),
                "regular_gas_used": regular_gas_used,
                "state_gas_used": state_gas_used,
                "execution_state_used": execution_state_used,
                "calldata_bytes": calldata_bytes,
                "bal_bytes": bal_bytes,
                "bandwidth_used": bandwidth_used,
                "bandwidth_excess": bandwidth_excess,
                "shared_base_fee": shared_base_fee,
                "bandwidth_base_fee_raw": raw_bandwidth_base_fee,
                "bandwidth_hard_floor_base_fee": bandwidth_hard_floor_base_fee,
                "bandwidth_base_fee": bandwidth_base_fee,
                "hard_floor_activated": hard_floor_activated,
                "bandwidth_limit_hit": bandwidth_limit_hit,
                "execution_state_limit_hit": execution_state_limit_hit,
                "bandwidth_usage_ratio": bandwidth_used
                / config.bandwidth.limit_bytes,
                "execution_state_usage_ratio": execution_state_used
                / config.execution_state.limit_gas,
                "shared_cost": shared_cost,
                "bandwidth_cost": bandwidth_cost,
                "total_cost": shared_cost + bandwidth_cost,
            }
        )

        shared_base_fee = update_shared_base_fee_8037_style(
            parent_base_fee=shared_base_fee,
            used=execution_state_used,
            config=config.execution_state,
        )
        bandwidth_excess = update_excess(
            parent_excess=bandwidth_excess,
            used=bandwidth_used,
            target=config.bandwidth.target_bytes,
        )

    return pd.DataFrame(rows)
