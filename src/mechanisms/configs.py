"""Configuration helpers for passive replay mechanisms."""

from __future__ import annotations

from dataclasses import dataclass, field

from basefee.eip7999_normalized import ResourceFeeConfig


@dataclass(frozen=True)
class MechanismConfig:
    name: str
    resources: dict[str, ResourceFeeConfig]
    initial_base_fee_by_resource: dict[str, int] = field(default_factory=dict)

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
        for resource_name, base_fee in self.initial_base_fee_by_resource.items():
            if base_fee < self.resources[resource_name].min_base_fee:
                raise ValueError(
                    f"initial base fee for {resource_name} must be >= min_base_fee"
                )


def _target_from_ratio(gas_limit: int, target_ratio: int) -> int:
    if gas_limit <= 0:
        raise ValueError("gas_limit must be positive")
    if target_ratio <= 0:
        raise ValueError("target_ratio must be positive")
    return int(gas_limit) // int(target_ratio)


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
