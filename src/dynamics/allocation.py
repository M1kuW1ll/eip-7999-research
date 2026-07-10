"""Aggregate inclusion rules for offered multi-resource demand.

These rules are deliberately simple.  They make the capacity-coupling
assumption visible while a later transaction-level packer is developed.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Protocol

from .demand import DEMAND_RESOURCES


@dataclass(frozen=True)
class Allocation:
    included_gas: Mapping[str, int]
    unserved_gas: Mapping[str, int]
    bundle_scale: float
    binding_resources: tuple[str, ...]
    rule: str


class InclusionRule(Protocol):
    name: str

    def allocate(
        self,
        offered_gas: Mapping[str, int],
        gas_limits: Mapping[str, int | None],
        gas_quantum: Mapping[str, int],
    ) -> Allocation: ...


def _validate_inputs(
    offered_gas: Mapping[str, int],
    gas_limits: Mapping[str, int | None],
    gas_quantum: Mapping[str, int],
) -> None:
    for resource in DEMAND_RESOURCES:
        if resource not in offered_gas or resource not in gas_limits:
            raise ValueError(f"missing allocation input for {resource!r}")
        if resource not in gas_quantum:
            raise ValueError(f"missing gas quantum for {resource!r}")
        if int(offered_gas[resource]) < 0:
            raise ValueError("offered gas must be non-negative")
        limit = gas_limits[resource]
        if limit is not None and int(limit) <= 0:
            raise ValueError("gas limits must be positive when present")
        if int(gas_quantum[resource]) <= 0:
            raise ValueError("gas quantum must be positive")
        if limit is not None and int(limit) % int(gas_quantum[resource]) != 0:
            raise ValueError(
                f"gas limit for {resource!r} must be divisible by its gas quantum"
            )


def _floor_to_quantum(value: float, quantum: int) -> int:
    return max(0, int(value) // int(quantum) * int(quantum))


@dataclass(frozen=True)
class SeparateResourceCaps:
    """Cap each limited resource without changing the other quantities."""

    name: str = "separate_resource_caps"

    def allocate(
        self,
        offered_gas: Mapping[str, int],
        gas_limits: Mapping[str, int | None],
        gas_quantum: Mapping[str, int],
    ) -> Allocation:
        _validate_inputs(offered_gas, gas_limits, gas_quantum)
        included = {
            resource: (
                int(offered_gas[resource])
                if gas_limits[resource] is None
                else min(int(offered_gas[resource]), int(gas_limits[resource]))
            )
            for resource in DEMAND_RESOURCES
        }
        unserved = {
            resource: int(offered_gas[resource]) - included[resource]
            for resource in DEMAND_RESOURCES
        }
        binding = tuple(
            resource
            for resource in DEMAND_RESOURCES
            if gas_limits[resource] is not None
            and included[resource] == int(gas_limits[resource])
        )
        return Allocation(
            included_gas=included,
            unserved_gas=unserved,
            bundle_scale=1.0,
            binding_resources=binding,
            rule=self.name,
        )


@dataclass(frozen=True)
class ProportionalBundleCaps:
    """Preserve one aggregate bundle recipe when a hard limit binds.

    Every resource is multiplied by the tightest execution/data capacity
    ratio.  This is an intentionally strong fixed-recipe sensitivity, not a
    transaction-selection model.
    """

    name: str = "proportional_bundle_caps"

    def allocate(
        self,
        offered_gas: Mapping[str, int],
        gas_limits: Mapping[str, int | None],
        gas_quantum: Mapping[str, int],
    ) -> Allocation:
        _validate_inputs(offered_gas, gas_limits, gas_quantum)
        capacity_ratio = Fraction(1, 1)
        for resource in DEMAND_RESOURCES:
            offered = int(offered_gas[resource])
            limit = gas_limits[resource]
            if limit is not None and offered > 0:
                capacity_ratio = min(
                    capacity_ratio,
                    Fraction(int(limit), offered),
                )
        included = {
            resource: _floor_to_quantum(
                int(offered_gas[resource])
                * capacity_ratio.numerator
                // capacity_ratio.denominator,
                int(gas_quantum[resource]),
            )
            for resource in DEMAND_RESOURCES
        }
        # Defensive guard against floating-point rounding at a hard limit.
        for resource in DEMAND_RESOURCES:
            limit = gas_limits[resource]
            if limit is not None:
                included[resource] = min(included[resource], int(limit))
        unserved = {
            resource: int(offered_gas[resource]) - included[resource]
            for resource in DEMAND_RESOURCES
        }
        binding = tuple(
            resource
            for resource in DEMAND_RESOURCES
            if gas_limits[resource] is not None
            and included[resource] == int(gas_limits[resource])
        )
        return Allocation(
            included_gas=included,
            unserved_gas=unserved,
            bundle_scale=float(capacity_ratio),
            binding_resources=binding,
            rule=self.name,
        )
