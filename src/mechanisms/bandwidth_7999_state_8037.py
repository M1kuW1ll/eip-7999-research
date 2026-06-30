"""Passive replay for Mechanism A.

Mechanism A adds an EIP-7999 bandwidth resource while keeping state priced
through the EIP-8037-style execution/state bottleneck path.
"""

from __future__ import annotations

from basefee import (
    ResourceFeeState,
    update_eip1559_base_fee,
)
from basefee.eip7999_normalized import apply_resource_block

from ._common import initial_states, result_for_block
from .configs import MechanismConfig
from .types import MechanismBlockResult, PassiveBlockUsage


def _apply_execution_state_block(
    *,
    parent: ResourceFeeState,
    gas_used: int,
    config: MechanismConfig,
) -> ResourceFeeState:
    resource = config.resources["execution_state"]
    if parent.name != resource.name:
        raise ValueError(f"State/config mismatch: {parent.name} != {resource.name}")

    gas_used_for_base_fee = min(int(gas_used), int(resource.gas_limit))
    next_base_fee = update_eip1559_base_fee(
        parent_base_fee=parent.base_fee,
        gas_used=gas_used_for_base_fee,
        gas_target=resource.gas_target,
        min_base_fee=resource.min_base_fee,
    )
    return ResourceFeeState(
        name=parent.name,
        excess_gas=0,
        base_fee=next_base_fee,
    )


def _apply_bandwidth_block(
    *,
    parent: ResourceFeeState,
    gas_used: int,
    config: MechanismConfig,
    reserve_anchor_base_fee: int | None = None,
) -> ResourceFeeState:
    resource = config.resources["bandwidth"]
    if parent.name != resource.name:
        raise ValueError(f"State/config mismatch: {parent.name} != {resource.name}")

    gas_used_for_base_fee = min(int(gas_used), int(resource.gas_limit))
    return apply_resource_block(
        parent=parent,
        gas_used=gas_used_for_base_fee,
        config=resource,
        reserve_anchor_base_fee=reserve_anchor_base_fee,
    )


def replay_bandwidth_7999_state_8037(
    blocks: list[PassiveBlockUsage],
    config: MechanismConfig,
) -> list[MechanismBlockResult]:
    """Replay Mechanism A with fixed historical block usage.

    Resources:
      - ``execution_state = max(execution_gas_used, state_gas_used)``
      - ``bandwidth`` from the caller's separated data-resource gas

    Invalid blocks are still returned in the result list. They update fee state
    with capped full-block inputs, because a real valid block cannot exceed its
    resource limits. The invalid flags mark where the historical block would
    have needed a different composition under this hypothetical mechanism.
    """

    if config.name != "bandwidth_7999_state_8037":
        raise ValueError(
            f"expected bandwidth_7999_state_8037 config, got {config.name!r}"
        )
    if set(config.resources) != {"execution_state", "bandwidth"}:
        raise ValueError(
            "bandwidth_7999_state_8037 requires execution_state and bandwidth"
        )
    if (
        config.resources["bandwidth"].has_reserve_price
        and any(block.blob_base_fee_per_gas is None for block in blocks)
    ):
        raise ValueError(
            "blob_base_fee_per_gas is required for bandwidth reserve pricing"
        )

    states = initial_states(config)
    results: list[MechanismBlockResult] = []

    for block in blocks:
        execution_state_used = max(block.execution_gas_used, block.state_gas_used)
        gas_used_by_resource = {
            "execution_state": execution_state_used,
            "bandwidth": block.bandwidth_gas,
        }

        invalid_reasons: list[str] = []
        if execution_state_used > config.resources["execution_state"].gas_limit:
            invalid_reasons.append("execution_state_limit_exceeded")
        if block.bandwidth_gas > config.resources["bandwidth"].gas_limit:
            invalid_reasons.append("bandwidth_limit_exceeded")

        result = result_for_block(
            block=block,
            config=config,
            states=states,
            gas_used_by_resource=gas_used_by_resource,
            invalid_reasons=invalid_reasons,
        )
        results.append(result)

        states = {
            "execution_state": _apply_execution_state_block(
                parent=states["execution_state"],
                gas_used=execution_state_used,
                config=config,
            ),
            "bandwidth": _apply_bandwidth_block(
                parent=states["bandwidth"],
                gas_used=block.bandwidth_gas,
                config=config,
                reserve_anchor_base_fee=block.blob_base_fee_per_gas,
            ),
        }

    return results
