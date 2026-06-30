"""Passive replay for full EIP-7999-style separated resources."""

from __future__ import annotations

from basefee import ResourceFeeState
from basefee.eip7999_normalized import apply_resource_block

from ._common import initial_states, result_for_block
from .configs import MechanismConfig
from .types import MechanismBlockResult, PassiveBlockUsage


def _apply_limited_or_unlimited_resource_block(
    *,
    parent: ResourceFeeState,
    gas_used: int,
    config: MechanismConfig,
    resource_name: str,
    reserve_anchor_base_fee: int | None = None,
) -> ResourceFeeState:
    resource = config.resources[resource_name]
    if parent.name != resource.name:
        raise ValueError(f"State/config mismatch: {parent.name} != {resource.name}")

    gas_used_for_base_fee = int(gas_used)
    if resource.gas_limit is not None:
        gas_used_for_base_fee = min(gas_used_for_base_fee, int(resource.gas_limit))

    return apply_resource_block(
        parent=parent,
        gas_used=gas_used_for_base_fee,
        config=resource,
        reserve_anchor_base_fee=reserve_anchor_base_fee,
    )


def _reserve_anchor_for_resource(
    *,
    block: PassiveBlockUsage,
    resource_name: str,
) -> int | None:
    if resource_name == "bandwidth":
        return block.blob_base_fee_per_gas
    return None


def replay_full_7999(
    blocks: list[PassiveBlockUsage],
    config: MechanismConfig,
) -> list[MechanismBlockResult]:
    """Replay full EIP-7999 with execution, bandwidth, and state separated.

    Resources:
      - ``execution`` with a hard block limit
      - ``bandwidth`` with a hard block limit
      - ``state`` with no hard block limit; it normalizes by its target

    Invalid blocks are still returned in the result list. Limited resources
    update fee state with capped full-block inputs, because a valid block cannot
    exceed their limits. State is not capped because the EIP-7999 draft gives it
    no per-block limit.
    """

    if config.name != "full_7999":
        raise ValueError(f"expected full_7999 config, got {config.name!r}")
    if set(config.resources) != {"execution", "bandwidth", "state"}:
        raise ValueError("full_7999 requires execution, bandwidth, and state")
    if config.resources["state"].gas_limit is not None:
        raise ValueError("full_7999 state resource must not have a gas limit")
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
        gas_used_by_resource = {
            "execution": block.execution_gas_used,
            "bandwidth": block.bandwidth_gas,
            "state": block.state_gas_used,
        }

        invalid_reasons: list[str] = []
        if block.execution_gas_used > config.resources["execution"].gas_limit:
            invalid_reasons.append("execution_limit_exceeded")
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
            name: _apply_limited_or_unlimited_resource_block(
                parent=states[name],
                gas_used=gas_used_by_resource[name],
                config=config,
                resource_name=name,
                reserve_anchor_base_fee=_reserve_anchor_for_resource(
                    block=block,
                    resource_name=name,
                ),
            )
            for name in config.resources
        }

    return results
