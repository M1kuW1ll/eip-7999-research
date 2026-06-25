"""Internal helpers shared by passive replay mechanisms."""

from __future__ import annotations

from basefee.eip7999_normalized import ResourceFeeState

from .configs import MechanismConfig
from .types import MechanismBlockResult, PassiveBlockUsage


def initial_states(config: MechanismConfig) -> dict[str, ResourceFeeState]:
    return {
        name: ResourceFeeState(
            name=name,
            base_fee=config.initial_base_fee_by_resource.get(
                name,
                resource.min_base_fee,
            ),
        )
        for name, resource in config.resources.items()
    }


def result_for_block(
    *,
    block: PassiveBlockUsage,
    config: MechanismConfig,
    states: dict[str, ResourceFeeState],
    gas_used_by_resource: dict[str, int],
    invalid_reasons: list[str],
) -> MechanismBlockResult:
    gas_limit_by_resource = {
        name: resource.gas_limit for name, resource in config.resources.items()
    }
    gas_target_by_resource = {
        name: resource.gas_target for name, resource in config.resources.items()
    }
    base_fee_by_resource = {
        name: states[name].base_fee for name in config.resources
    }
    excess_gas_by_resource = {
        name: states[name].excess_gas for name in config.resources
    }
    pct_limit_by_resource = {
        name: gas_used_by_resource[name] / gas_limit_by_resource[name]
        for name in gas_used_by_resource
    }
    pct_target_by_resource = {
        name: (
            gas_used_by_resource[name] / gas_target_by_resource[name]
            if gas_target_by_resource[name] > 0
            else float("inf")
        )
        for name in gas_used_by_resource
    }

    return MechanismBlockResult(
        block_number=block.block_number,
        timestamp=block.timestamp,
        mechanism=config.name,
        valid=not invalid_reasons,
        invalid_reasons=tuple(invalid_reasons),
        gas_used_by_resource=gas_used_by_resource,
        gas_limit_by_resource=gas_limit_by_resource,
        gas_target_by_resource=gas_target_by_resource,
        base_fee_by_resource=base_fee_by_resource,
        excess_gas_by_resource=excess_gas_by_resource,
        pct_limit_by_resource=pct_limit_by_resource,
        pct_target_by_resource=pct_target_by_resource,
        execution_gas_used=block.execution_gas_used,
        state_gas_used=block.state_gas_used,
        bandwidth_gas=block.bandwidth_gas,
        bandwidth_bytes=block.bandwidth_bytes,
    )
