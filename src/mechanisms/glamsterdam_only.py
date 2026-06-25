"""Passive replay for pure Glamsterdam-style bottleneck accounting."""

from __future__ import annotations

from basefee import ResourceFeeState, update_eip1559_base_fee

from ._common import initial_states, result_for_block
from .configs import MechanismConfig
from .types import MechanismBlockResult, PassiveBlockUsage


def _apply_eip8037_bottleneck_block(
    *,
    parent: ResourceFeeState,
    gas_used: int,
    config: MechanismConfig,
) -> ResourceFeeState:
    resource = config.resources["execution_state"]
    if parent.name != resource.name:
        raise ValueError(f"State/config mismatch: {parent.name} != {resource.name}")

    # Passive replay keeps the raw over-limit usage as a diagnostic, but the
    # EIP-1559 fee update can only see a valid full block at the gas limit.
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


def replay_glamsterdam_only(
    blocks: list[PassiveBlockUsage],
    config: MechanismConfig,
) -> list[MechanismBlockResult]:
    """Replay the Glamsterdam-only baseline.

    This baseline has one synthetic fee resource:

    ``execution_state = max(execution_gas_used, state_gas_used)``

    Its base fee follows the EIP-1559 linear update with denominator 8.
    EIP-8037 changes the gas-used input to the execution/state max bottleneck;
    it does not use the EIP-4844/EIP-7999 fake-exponential update.

    Bandwidth is reported on each result as diagnostics, but it is not enforced
    as a separate limit and has no base fee in this mechanism.
    """

    if config.name != "glamsterdam_only":
        raise ValueError(f"expected glamsterdam_only config, got {config.name!r}")
    if set(config.resources) != {"execution_state"}:
        raise ValueError("glamsterdam_only requires only execution_state")

    states = initial_states(config)
    results: list[MechanismBlockResult] = []

    for block in blocks:
        execution_state_used = max(block.execution_gas_used, block.state_gas_used)
        gas_used_by_resource = {
            "execution_state": execution_state_used,
        }
        invalid_reasons: list[str] = []
        if execution_state_used > config.resources["execution_state"].gas_limit:
            invalid_reasons.append("execution_state_limit_exceeded")

        result = result_for_block(
            block=block,
            config=config,
            states=states,
            gas_used_by_resource=gas_used_by_resource,
            invalid_reasons=invalid_reasons,
        )
        results.append(result)

        states = {
            "execution_state": _apply_eip8037_bottleneck_block(
                parent=states["execution_state"],
                gas_used=execution_state_used,
                config=config,
            )
        }

    return results
