"""Aggregate inclusion rules for offered multi-resource demand.

These rules are deliberately simple.  They make the capacity-coupling
assumption visible while a later transaction-level packer is developed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Mapping, Protocol

from .demand import BundleDemandEvaluation, DEMAND_RESOURCES


@dataclass(frozen=True)
class Allocation:
    included_gas: Mapping[str, int]
    unserved_gas: Mapping[str, int]
    bundle_scale: float
    binding_resources: tuple[str, ...]
    rule: str
    diagnostics: Mapping[str, float] = field(default_factory=dict)


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


@dataclass(frozen=True)
class ParentBALConsistentCaps:
    """Keep rejected parent activity and its linked BAL together.

    An execution-cap scale applies to execution gas and execution-linked BAL.
    If the remaining data bundle still exceeds the data limit, all remaining
    parent activity, static data, and linked BAL are scaled proportionally.
    That second step is an explicit aggregate selection assumption; it is used
    until transaction-level block packing is available.
    """

    name: str = "parent_bal_consistent_caps"

    def allocate(
        self,
        offered_gas: Mapping[str, int],
        gas_limits: Mapping[str, int | None],
        gas_quantum: Mapping[str, int],
    ) -> Allocation:
        raise TypeError(
            "ParentBALConsistentCaps requires a component-aware demand evaluation"
        )

    def allocate_components(
        self,
        evaluation: BundleDemandEvaluation,
        offered_gas: Mapping[str, int],
        gas_limits: Mapping[str, int | None],
        gas_quantum: Mapping[str, int],
    ) -> Allocation:
        _validate_inputs(offered_gas, gas_limits, gas_quantum)

        execution_limit = gas_limits["execution"]
        offered_execution = int(offered_gas["execution"])
        execution_cap_scale = 1.0
        if execution_limit is not None and offered_execution > execution_limit:
            execution_cap_scale = float(execution_limit) / offered_execution

        execution_after_cap = _floor_to_quantum(
            offered_execution * execution_cap_scale,
            int(gas_quantum["execution"]),
        )
        state_after_cap = int(offered_gas["state"])
        component_after_execution_cap = {
            "static_data": float(evaluation.static_data_gas),
            "execution_bal": (
                float(evaluation.execution_bal_gas) * execution_cap_scale
            ),
            "state_bal": float(evaluation.state_bal_gas),
        }
        data_after_execution_cap = sum(component_after_execution_cap.values())

        data_limit = gas_limits["data"]
        data_bundle_scale = 1.0
        if data_limit is not None and data_after_execution_cap > float(data_limit):
            data_bundle_scale = float(data_limit) / data_after_execution_cap

        included_execution = _floor_to_quantum(
            execution_after_cap * data_bundle_scale,
            int(gas_quantum["execution"]),
        )
        included_state = _floor_to_quantum(
            state_after_cap * data_bundle_scale,
            int(gas_quantum["state"]),
        )
        if data_bundle_scale < 1.0:
            included_data = int(data_limit)
        elif execution_cap_scale == 1.0:
            included_data = int(offered_gas["data"])
        else:
            included_data = _floor_to_quantum(
                data_after_execution_cap,
                int(gas_quantum["data"]),
            )

        included = {
            "execution": included_execution,
            "data": included_data,
            "state": included_state,
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

        included_components = {
            name: value * data_bundle_scale
            for name, value in component_after_execution_cap.items()
        }
        component_total = sum(included_components.values())
        diagnostics = {
            "execution_inclusion_scale": (
                0.0
                if offered_execution == 0
                else included_execution / offered_execution
            ),
            "data_bundle_inclusion_scale": data_bundle_scale,
            "included_static_data_gas": included_components["static_data"],
            "included_execution_bal_gas": included_components["execution_bal"],
            "included_state_bal_gas": included_components["state_bal"],
            "included_total_bal_gas": (
                included_components["execution_bal"] + included_components["state_bal"]
            ),
            "included_data_rounding_residual_gas": included_data - component_total,
        }
        return Allocation(
            included_gas=included,
            unserved_gas=unserved,
            bundle_scale=execution_cap_scale * data_bundle_scale,
            binding_resources=binding,
            rule=self.name,
            diagnostics=diagnostics,
        )
