"""EIP-7999 normalized resource base-fee updater."""

from __future__ import annotations

from dataclasses import dataclass

GAS_NORMALIZATION_FACTOR = 10**9
BASE_FEE_UPDATE_FRACTION = 4_245_093_508
MIN_BASE_FEE_PER_GAS = 1


@dataclass(frozen=True)
class ResourceFeeConfig:
    name: str
    gas_limit: int | None
    gas_target: int
    min_base_fee: int = MIN_BASE_FEE_PER_GAS
    update_fraction: int = BASE_FEE_UPDATE_FRACTION
    gas_normalization_factor: int = GAS_NORMALIZATION_FACTOR
    normalization_denominator: int | None = None
    reserve_mode: str = "none"
    reserve_factor: int = 0
    reserve_anchor_resource: str | None = None

    def __post_init__(self) -> None:
        if self.gas_limit is not None and self.gas_limit <= 0:
            raise ValueError("gas_limit must be positive")
        if self.gas_target < 0:
            raise ValueError("gas_target must be non-negative")
        if self.gas_limit is None and self.gas_target <= 0:
            raise ValueError("gas_target must be positive for unlimited resources")
        if self.gas_limit is not None and self.gas_target > self.gas_limit:
            raise ValueError("gas_target must be <= gas_limit")
        if self.min_base_fee < 0:
            raise ValueError("min_base_fee must be non-negative")
        if self.update_fraction <= 0:
            raise ValueError("update_fraction must be positive")
        if self.gas_normalization_factor <= 0:
            raise ValueError("gas_normalization_factor must be positive")
        if (
            self.normalization_denominator is not None
            and self.normalization_denominator <= 0
        ):
            raise ValueError("normalization_denominator must be positive")
        if self.reserve_mode not in {"none", "eip7918"}:
            raise ValueError("reserve_mode must be 'none' or 'eip7918'")
        if self.reserve_factor < 0:
            raise ValueError("reserve_factor must be non-negative")
        if self.reserve_mode == "none" and self.reserve_factor != 0:
            raise ValueError("reserve_factor requires reserve_mode='eip7918'")
        if self.reserve_mode == "eip7918" and self.reserve_factor <= 0:
            raise ValueError("reserve_factor must be positive for eip7918")

    @property
    def normalization_denominator_value(self) -> int:
        """Return the denominator used for normalized excess deltas.

        EIP-7999 normalizes limited resources by their gas limit. State has no
        block limit, so callers configure it with ``gas_limit=None`` and it
        normalizes by its target.
        """

        if self.normalization_denominator is not None:
            return int(self.normalization_denominator)
        if self.gas_limit is not None:
            return int(self.gas_limit)
        return int(self.gas_target)

    @property
    def has_reserve_price(self) -> bool:
        return self.reserve_mode == "eip7918" and self.reserve_factor > 0


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
    this fake-exponential base-fee shape after normalizing each limited
    resource's excess gas by its own gas limit. Unlimited resources, such as
    state in the draft, normalize by their configured target.
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
    parent_base_fee: int | None = None,
    reserve_anchor_base_fee: int | None = None,
) -> int:
    """Update one resource's normalized EIP-7999 excess gas."""

    if parent_excess_gas < 0:
        raise ValueError("parent_excess_gas must be non-negative")
    if gas_used < 0:
        raise ValueError("gas_used must be non-negative")
    if config.gas_limit is not None and gas_used > config.gas_limit:
        raise ValueError("gas_used must be <= gas_limit")

    if reserve_price_active(
        base_fee=parent_base_fee,
        reserve_anchor_base_fee=reserve_anchor_base_fee,
        config=config,
    ):
        if config.gas_limit is None:
            raise ValueError("reserve pricing requires a gas limit")
        delta = (
            int(gas_used)
            * (int(config.gas_limit) - int(config.gas_target))
            // int(config.gas_limit)
        )
        normalized_delta = (
            delta
            * int(config.gas_normalization_factor)
            // int(config.gas_limit)
        )
        return int(parent_excess_gas) + normalized_delta

    denominator = config.normalization_denominator_value
    if gas_used >= config.gas_target:
        delta = int(gas_used) - int(config.gas_target)
        normalized_delta = (
            delta * int(config.gas_normalization_factor) // denominator
        )
        return int(parent_excess_gas) + normalized_delta

    delta = int(config.gas_target) - int(gas_used)
    normalized_delta = (
        delta * int(config.gas_normalization_factor) // denominator
    )
    if parent_excess_gas < normalized_delta:
        return 0
    return int(parent_excess_gas) - normalized_delta


def reserve_anchor_threshold_base_fee(
    reserve_anchor_base_fee: int | None,
    config: ResourceFeeConfig,
) -> int | None:
    """Return the base-fee threshold used by the EIP-7918 reserve condition.

    For EIP-7999 data/bandwidth, ``reserve_factor=12`` and the anchor is the
    blob base fee. This is a diagnostic threshold, not a hard base-fee floor:
    the spec applies reserve pricing through the excess-gas update path.
    """

    if not config.has_reserve_price:
        return None
    if reserve_anchor_base_fee is None:
        raise ValueError("reserve_anchor_base_fee is required for reserve pricing")
    if reserve_anchor_base_fee < 0:
        raise ValueError("reserve_anchor_base_fee must be non-negative")
    factor = int(config.reserve_factor)
    return (int(reserve_anchor_base_fee) + factor - 1) // factor


def reserve_price_active(
    *,
    base_fee: int | None,
    reserve_anchor_base_fee: int | None,
    config: ResourceFeeConfig,
) -> bool:
    if not config.has_reserve_price:
        return False
    if base_fee is None:
        raise ValueError("base_fee is required for reserve pricing")
    if base_fee < 0:
        raise ValueError("base_fee must be non-negative")
    if reserve_anchor_base_fee is None:
        raise ValueError("reserve_anchor_base_fee is required for reserve pricing")
    if reserve_anchor_base_fee < 0:
        raise ValueError("reserve_anchor_base_fee must be non-negative")
    return int(base_fee) * int(config.reserve_factor) < int(reserve_anchor_base_fee)


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
    reserve_anchor_base_fee: int | None = None,
) -> ResourceFeeState:
    if parent.name != config.name:
        raise ValueError(f"State/config mismatch: {parent.name} != {config.name}")

    next_excess = update_normalized_excess_gas(
        parent_excess_gas=parent.excess_gas,
        gas_used=gas_used,
        config=config,
        parent_base_fee=parent.base_fee,
        reserve_anchor_base_fee=reserve_anchor_base_fee,
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
    reserve_anchor_base_fee_by_resource: dict[str, int | None] | None = None,
) -> dict[str, ResourceFeeState]:
    """Apply the normalized update independently to every resource."""

    next_states: dict[str, ResourceFeeState] = {}
    reserve_anchors = reserve_anchor_base_fee_by_resource or {}

    for name, config in configs.items():
        if name not in parent_states:
            raise KeyError(f"Missing parent state for resource {name}")
        if name not in gas_used_by_resource:
            raise KeyError(f"Missing gas usage for resource {name}")

        next_states[name] = apply_resource_block(
            parent=parent_states[name],
            gas_used=gas_used_by_resource[name],
            config=config,
            reserve_anchor_base_fee=reserve_anchors.get(name),
        )

    return next_states
