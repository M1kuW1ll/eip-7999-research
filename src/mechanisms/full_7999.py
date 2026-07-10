"""Passive replay for full EIP-7999-style separated resources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from basefee import ResourceFeeState, reserve_price_active
from basefee.eip7999_normalized import apply_resource_block

from ._common import initial_states, result_for_block
from .configs import MechanismConfig
from .types import MechanismBlockResult, PassiveBlockUsage


@dataclass(frozen=True)
class MechanismStep:
    """One full-7999 block transition.

    ``result`` records the parent fee state that governs the current block.
    ``next_states`` contains the fee state produced for the following block.
    Keeping both objects explicit prevents a one-block timing shift in driven
    simulations built on top of the passive mechanism core.
    """

    result: MechanismBlockResult
    next_states: Mapping[str, ResourceFeeState]
    reserve_active_by_resource: Mapping[str, bool]


def initialize_mechanism_states(
    config: MechanismConfig,
) -> dict[str, ResourceFeeState]:
    """Return the configured parent fee state for the first replayed block."""

    return initial_states(config)


def _validate_full_7999_config(config: MechanismConfig) -> None:
    if config.name != "full_7999":
        raise ValueError(f"expected full_7999 config, got {config.name!r}")
    if set(config.resources) != {"execution", "bandwidth", "state"}:
        raise ValueError("full_7999 requires execution, bandwidth, and state")
    if config.resources["state"].gas_limit is not None:
        raise ValueError("full_7999 state resource must not have a gas limit")


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


def step_full_7999(
    *,
    block: PassiveBlockUsage,
    config: MechanismConfig,
    parent_states: Mapping[str, ResourceFeeState],
) -> MechanismStep:
    """Apply one full-7999 block without hiding the parent/next-state boundary.

    Limited resources retain their raw usage in ``result`` for diagnostics but
    use a capped full-block input for their fee transition. State remains
    uncapped. The reserve-active flag is evaluated from the parent bandwidth
    fee and the blob base fee governing this block, matching the update path in
    :func:`basefee.eip7999_normalized.apply_resource_block`.
    """

    _validate_full_7999_config(config)
    if (
        config.resources["bandwidth"].has_reserve_price
        and block.blob_base_fee_per_gas is None
    ):
        raise ValueError(
            "blob_base_fee_per_gas is required for bandwidth reserve pricing"
        )

    states = dict(parent_states)
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

    reserve_anchors = {
        name: _reserve_anchor_for_resource(block=block, resource_name=name)
        for name in config.resources
    }
    reserve_active_by_resource = {
        name: reserve_price_active(
            base_fee=states[name].base_fee,
            reserve_anchor_base_fee=reserve_anchors[name],
            config=config.resources[name],
        )
        for name in config.resources
    }
    next_states = {
        name: _apply_limited_or_unlimited_resource_block(
            parent=states[name],
            gas_used=gas_used_by_resource[name],
            config=config,
            resource_name=name,
            reserve_anchor_base_fee=reserve_anchors[name],
        )
        for name in config.resources
    }

    return MechanismStep(
        result=result,
        next_states=next_states,
        reserve_active_by_resource=reserve_active_by_resource,
    )


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

    _validate_full_7999_config(config)
    if (
        config.resources["bandwidth"].has_reserve_price
        and any(block.blob_base_fee_per_gas is None for block in blocks)
    ):
        raise ValueError(
            "blob_base_fee_per_gas is required for bandwidth reserve pricing"
        )

    states = initialize_mechanism_states(config)
    results: list[MechanismBlockResult] = []

    for block in blocks:
        step = step_full_7999(
            block=block,
            config=config,
            parent_states=states,
        )
        results.append(step.result)
        states = dict(step.next_states)

    return results
