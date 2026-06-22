"""EIP-8037-style state baseline helpers."""

from __future__ import annotations

from .basefee import update_eip1559_base_fee
from .config import ExecutionStateConfig


def execution_state_bottleneck(regular_gas_used: int, state_gas_used: int) -> int:
    """Single shared demand quantity under the EIP-8037 max bottleneck."""

    return max(int(regular_gas_used), int(state_gas_used))


def update_shared_base_fee_8037_style(
    parent_base_fee: int,
    used: int,
    config: ExecutionStateConfig,
) -> int:
    """Update the shared execution/state base fee for the next block."""

    return update_eip1559_base_fee(
        parent_base_fee=parent_base_fee,
        used=used,
        target=config.target_gas,
        update_denominator=config.base_fee_update_denominator,
        min_base_fee=config.min_base_fee,
    )
