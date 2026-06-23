"""EIP-7999 normalized resource base-fee updater."""

from __future__ import annotations

from dataclasses import dataclass

GAS_NORMALIZATION_FACTOR = 10**9
BASE_FEE_UPDATE_FRACTION = 4_245_093_508
MIN_BASE_FEE_PER_GAS = 1


@dataclass(frozen=True)
class ResourceFeeConfig:
    name: str
    gas_limit: int
    gas_target: int
    min_base_fee: int = MIN_BASE_FEE_PER_GAS
    update_fraction: int = BASE_FEE_UPDATE_FRACTION
    gas_normalization_factor: int = GAS_NORMALIZATION_FACTOR
    reserve_mode: str = "none"

    def __post_init__(self) -> None:
        if self.gas_limit <= 0:
            raise ValueError("gas_limit must be positive")
        if self.gas_target < 0:
            raise ValueError("gas_target must be non-negative")
        if self.gas_target > self.gas_limit:
            raise ValueError("gas_target must be <= gas_limit")
        if self.min_base_fee < 0:
            raise ValueError("min_base_fee must be non-negative")
        if self.update_fraction <= 0:
            raise ValueError("update_fraction must be positive")
        if self.gas_normalization_factor <= 0:
            raise ValueError("gas_normalization_factor must be positive")
        if self.reserve_mode != "none":
            raise NotImplementedError("reserve modes are not implemented yet")


@dataclass(frozen=True)
class ResourceFeeState:
    name: str
    excess_gas: int = 0
    base_fee: int = MIN_BASE_FEE_PER_GAS

    def __post_init__(self) -> None:
        if self.excess_gas < 0:
            raise ValueError("excess_gas must be non-negative")
        if self.base_fee < 0:
            raise ValueError("base_fee must be non-negative")


def fake_exponential(factor: int, numerator: int, denominator: int) -> int:
    """EIP-4844-style integer fake exponential.

    Approximates ``factor * exp(numerator / denominator)``. EIP-7999 reuses
    this fake-exponential base-fee shape after normalizing each resource's
    excess gas by its own gas limit.
    """

    if factor < 0:
        raise ValueError("factor must be non-negative")
    if numerator < 0:
        raise ValueError("numerator must be non-negative")
    if denominator <= 0:
        raise ValueError("denominator must be positive")

    i = 1
    output = 0
    numerator_accum = int(factor) * int(denominator)

    while numerator_accum > 0:
        output += numerator_accum
        numerator_accum = numerator_accum * int(numerator) // (
            int(denominator) * i
        )
        i += 1

    return output // int(denominator)


def update_normalized_excess_gas(
    parent_excess_gas: int,
    gas_used: int,
    config: ResourceFeeConfig,
) -> int:
    """Update one resource's normalized EIP-7999 excess gas."""

    if parent_excess_gas < 0:
        raise ValueError("parent_excess_gas must be non-negative")
    if gas_used < 0:
        raise ValueError("gas_used must be non-negative")
    if gas_used > config.gas_limit:
        raise ValueError("gas_used must be <= gas_limit")

    if gas_used >= config.gas_target:
        delta = int(gas_used) - int(config.gas_target)
        normalized_delta = (
            delta * int(config.gas_normalization_factor) // int(config.gas_limit)
        )
        return int(parent_excess_gas) + normalized_delta

    delta = int(config.gas_target) - int(gas_used)
    normalized_delta = (
        delta * int(config.gas_normalization_factor) // int(config.gas_limit)
    )
    if parent_excess_gas < normalized_delta:
        return 0
    return int(parent_excess_gas) - normalized_delta


def compute_base_fee(
    excess_gas: int,
    config: ResourceFeeConfig,
) -> int:
    if excess_gas < 0:
        raise ValueError("excess_gas must be non-negative")

    return fake_exponential(
        config.min_base_fee,
        int(excess_gas),
        config.update_fraction,
    )


def apply_resource_block(
    parent: ResourceFeeState,
    gas_used: int,
    config: ResourceFeeConfig,
) -> ResourceFeeState:
    if parent.name != config.name:
        raise ValueError(f"State/config mismatch: {parent.name} != {config.name}")

    next_excess = update_normalized_excess_gas(
        parent_excess_gas=parent.excess_gas,
        gas_used=gas_used,
        config=config,
    )
    next_base_fee = compute_base_fee(
        excess_gas=next_excess,
        config=config,
    )

    return ResourceFeeState(
        name=config.name,
        excess_gas=next_excess,
        base_fee=next_base_fee,
    )


def apply_vector_block(
    parent_states: dict[str, ResourceFeeState],
    gas_used_by_resource: dict[str, int],
    configs: dict[str, ResourceFeeConfig],
) -> dict[str, ResourceFeeState]:
    """Apply the normalized update independently to every resource."""

    next_states: dict[str, ResourceFeeState] = {}

    for name, config in configs.items():
        if name not in parent_states:
            raise KeyError(f"Missing parent state for resource {name}")
        if name not in gas_used_by_resource:
            raise KeyError(f"Missing gas usage for resource {name}")

        next_states[name] = apply_resource_block(
            parent=parent_states[name],
            gas_used=gas_used_by_resource[name],
            config=config,
        )

    return next_states
