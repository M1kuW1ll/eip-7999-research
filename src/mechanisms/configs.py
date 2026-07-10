"""Configuration helpers for passive replay mechanisms."""

from __future__ import annotations

from dataclasses import dataclass, field

from basefee.eip7999_normalized import (
    ResourceFeeConfig,
    excess_gas_for_base_fee,
)


@dataclass(frozen=True)
class MechanismConfig:
    name: str
    resources: dict[str, ResourceFeeConfig]
    initial_base_fee_by_resource: dict[str, int] = field(default_factory=dict)
    initial_excess_gas_by_resource: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for resource_name, config in self.resources.items():
            if resource_name != config.name:
                raise ValueError(
                    f"resource key/name mismatch: {resource_name!r} != {config.name!r}"
                )
        unknown_initial_fees = set(self.initial_base_fee_by_resource) - set(
            self.resources
        )
        if unknown_initial_fees:
            raise ValueError(
                "initial base fee specified for unknown resources: "
                + ", ".join(sorted(unknown_initial_fees))
            )
        unknown_initial_excesses = set(self.initial_excess_gas_by_resource) - set(
            self.resources
        )
        if unknown_initial_excesses:
            raise ValueError(
                "initial excess gas specified for unknown resources: "
                + ", ".join(sorted(unknown_initial_excesses))
            )
        for resource_name, base_fee in self.initial_base_fee_by_resource.items():
            if base_fee < self.resources[resource_name].min_base_fee:
                raise ValueError(
                    f"initial base fee for {resource_name} must be >= min_base_fee"
                )
        for resource_name, excess_gas in self.initial_excess_gas_by_resource.items():
            if excess_gas < 0:
                raise ValueError(
                    f"initial excess gas for {resource_name} must be non-negative"
                )


def _target_from_ratio(gas_limit: int, target_ratio: int) -> int:
    if gas_limit <= 0:
        raise ValueError("gas_limit must be positive")
    if target_ratio <= 0:
        raise ValueError("target_ratio must be positive")
    return int(gas_limit) // int(target_ratio)


def _warm_start_excess_gas(base_fee: int, resource: ResourceFeeConfig) -> int:
    return excess_gas_for_base_fee(int(base_fee), resource)


def make_glamsterdam_only_config(
    *,
    execution_state_gas_limit: int,
    execution_state_target_ratio: int = 2,
    initial_base_fee: int = 1,
    min_base_fee: int = 1,
) -> MechanismConfig:
    """Pure Glamsterdam-style bottleneck baseline.

    Fee resources:
      - ``execution_state``

    Bandwidth is report-only here: no bandwidth validity check and no bandwidth
    base fee.
    """

    execution_state = ResourceFeeConfig(
        name="execution_state",
        gas_limit=int(execution_state_gas_limit),
        gas_target=_target_from_ratio(
            execution_state_gas_limit,
            execution_state_target_ratio,
        ),
        min_base_fee=int(min_base_fee),
    )
    return MechanismConfig(
        name="glamsterdam_only",
        resources={"execution_state": execution_state},
        initial_base_fee_by_resource={"execution_state": int(initial_base_fee)},
    )


def make_mechanism_A_config(
    *,
    execution_state_gas_limit: int,
    bandwidth_gas_limit: int,
    execution_state_target_ratio: int = 2,
    bandwidth_target_ratio: int = 4,
    initial_execution_state_base_fee: int = 1,
    initial_bandwidth_base_fee: int = 1,
    min_base_fee: int = 1,
    bandwidth_reserve_factor: int = 12,
) -> MechanismConfig:
    """Mechanism A: EIP-8037 bottleneck plus EIP-7999 bandwidth.

    Fee resources:
      - ``execution_state`` with gas used ``max(execution_gas, state_gas)``
      - ``bandwidth`` with gas used from calldata + BAL + tx payload bytes

    State does not have a separate target or base fee in this mechanism.
    Bandwidth/data uses the EIP-7999 blob-base-fee reserve path when
    ``bandwidth_reserve_factor`` is positive. The reserve affects normalized
    excess growth; it is not a hard base-fee clamp.
    """

    execution_state = ResourceFeeConfig(
        name="execution_state",
        gas_limit=int(execution_state_gas_limit),
        gas_target=_target_from_ratio(
            execution_state_gas_limit,
            execution_state_target_ratio,
        ),
        min_base_fee=int(min_base_fee),
    )
    bandwidth = ResourceFeeConfig(
        name="bandwidth",
        gas_limit=int(bandwidth_gas_limit),
        gas_target=_target_from_ratio(
            bandwidth_gas_limit,
            bandwidth_target_ratio,
        ),
        min_base_fee=int(min_base_fee),
        reserve_mode="eip7918" if bandwidth_reserve_factor > 0 else "none",
        reserve_factor=int(bandwidth_reserve_factor),
        reserve_anchor_resource="blob",
    )
    return MechanismConfig(
        name="bandwidth_7999_state_8037",
        resources={
            "execution_state": execution_state,
            "bandwidth": bandwidth,
        },
        initial_base_fee_by_resource={
            "execution_state": int(initial_execution_state_base_fee),
            "bandwidth": int(initial_bandwidth_base_fee),
        },
        initial_excess_gas_by_resource={
            "bandwidth": _warm_start_excess_gas(
                int(initial_bandwidth_base_fee),
                bandwidth,
            ),
        },
    )


def make_full_7999_config(
    *,
    execution_gas_limit: int,
    bandwidth_gas_limit: int,
    state_gas_target: int,
    execution_target_ratio: int = 2,
    bandwidth_target_ratio: int = 4,
    initial_execution_base_fee: int = 1,
    initial_bandwidth_base_fee: int = 1,
    initial_state_base_fee: int = 1,
    min_base_fee: int = 1,
    bandwidth_reserve_factor: int = 12,
) -> MechanismConfig:
    """Full EIP-7999-style replay with execution, bandwidth, and state.

    Fee resources:
      - ``execution`` with a target and hard block limit
      - ``bandwidth`` with a target and hard block limit
      - ``state`` with a target but no hard block limit

    State follows the EIP-7999 draft rule that an unlimited resource normalizes
    excess deltas by its target.

    Bandwidth/data follows the EIP-7999 generalized EIP-7918 reserve rule,
    anchored to the blob base fee. With ``bandwidth_reserve_factor=12``, the
    reserve condition compares the data base fee to ``blob_base_fee / 12``.
    The reserve path changes excess growth; it is not a hard base-fee clamp.
    """

    execution = ResourceFeeConfig(
        name="execution",
        gas_limit=int(execution_gas_limit),
        gas_target=_target_from_ratio(
            execution_gas_limit,
            execution_target_ratio,
        ),
        min_base_fee=int(min_base_fee),
    )
    bandwidth = ResourceFeeConfig(
        name="bandwidth",
        gas_limit=int(bandwidth_gas_limit),
        gas_target=_target_from_ratio(
            bandwidth_gas_limit,
            bandwidth_target_ratio,
        ),
        min_base_fee=int(min_base_fee),
        reserve_mode="eip7918" if bandwidth_reserve_factor > 0 else "none",
        reserve_factor=int(bandwidth_reserve_factor),
        reserve_anchor_resource="blob",
    )
    state = ResourceFeeConfig(
        name="state",
        gas_limit=None,
        gas_target=int(state_gas_target),
        normalization_denominator=int(state_gas_target),
        min_base_fee=int(min_base_fee),
    )
    return MechanismConfig(
        name="full_7999",
        resources={
            "execution": execution,
            "bandwidth": bandwidth,
            "state": state,
        },
        initial_base_fee_by_resource={
            "execution": int(initial_execution_base_fee),
            "bandwidth": int(initial_bandwidth_base_fee),
            "state": int(initial_state_base_fee),
        },
        initial_excess_gas_by_resource={
            "execution": _warm_start_excess_gas(
                int(initial_execution_base_fee),
                execution,
            ),
            "bandwidth": _warm_start_excess_gas(
                int(initial_bandwidth_base_fee),
                bandwidth,
            ),
            "state": _warm_start_excess_gas(
                int(initial_state_base_fee),
                state,
            ),
        },
    )
