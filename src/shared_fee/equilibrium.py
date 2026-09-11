"""Equilibrium calculations for the independent one-dimensional benchmark."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


MIN_BASE_FEE_WEI = 1.0
GWEI = 1e9


@dataclass(frozen=True)
class SharedFeeAnchor:
    """Historical activity anchors and counterfactual metering multipliers."""

    q_execution: float
    q_data: float
    q_state: float
    m_execution: float
    m_data: float
    m_state: float
    reference_fee_gwei: float
    eps_execution: float
    eps_data: float
    eps_state: float
    state_demand_cap_multiple: float = float("inf")


@dataclass(frozen=True)
class SharedFeeEquilibrium:
    """Unshocked target-clearing solution for one common fee."""

    base_fee_wei: float
    target_gas: float
    offered_shared_gas: float
    regular_gas: float
    state_gas: float
    execution_gas: float
    data_gas: float
    binding_branch: str
    floor_bounded: bool
    state_demand_cap_active: bool


def offered_gas(base_fee_wei: float, anchor: SharedFeeAnchor) -> tuple[float, ...]:
    """Return shared, regular, state, execution, and data gas at ``base_fee``."""

    fee = max(float(base_fee_wei), MIN_BASE_FEE_WEI)
    reference = anchor.reference_fee_gwei * GWEI
    execution = anchor.m_execution * anchor.q_execution * (
        anchor.m_execution * fee / reference
    ) ** (-anchor.eps_execution)
    data = anchor.m_data * anchor.q_data * (
        anchor.m_data * fee / reference
    ) ** (-anchor.eps_data)
    state_price_response = (
        anchor.m_state * fee / reference
    ) ** (-anchor.eps_state)
    state = (
        anchor.m_state
        * anchor.q_state
        * min(state_price_response, anchor.state_demand_cap_multiple)
    )
    regular = execution + data
    return max(regular, state), regular, state, execution, data


def solve_shared_fee_equilibrium(
    target_gas: float,
    anchor: SharedFeeAnchor,
    *,
    maximum_fee_wei: float = 1e30,
    relative_tolerance: float = 1e-12,
) -> SharedFeeEquilibrium:
    """Solve the monotone target-clearing fee, respecting the one-wei minimum."""

    target = float(target_gas)
    if not np.isfinite(target) or target <= 0:
        raise ValueError("target_gas must be finite and positive")

    at_floor = offered_gas(MIN_BASE_FEE_WEI, anchor)
    if at_floor[0] <= target:
        solution = at_floor
        fee = MIN_BASE_FEE_WEI
        floor_bounded = True
    else:
        lower = MIN_BASE_FEE_WEI
        upper = max(anchor.reference_fee_gwei * GWEI, lower * 2)
        while offered_gas(upper, anchor)[0] > target and upper < maximum_fee_wei:
            upper *= 2
        if offered_gas(upper, anchor)[0] > target:
            raise ValueError("could not bracket the shared-fee equilibrium")

        log_lower, log_upper = np.log(lower), np.log(upper)
        for _ in range(200):
            log_mid = (log_lower + log_upper) / 2
            mid = float(np.exp(log_mid))
            if offered_gas(mid, anchor)[0] > target:
                log_lower = log_mid
            else:
                log_upper = log_mid
            if log_upper - log_lower <= relative_tolerance:
                break
        fee = float(np.exp((log_lower + log_upper) / 2))
        solution = offered_gas(fee, anchor)
        floor_bounded = False

    shared, regular, state, execution, data = solution
    branch = "regular" if regular >= state else "state"
    state_price_response = (
        anchor.m_state * fee / (anchor.reference_fee_gwei * GWEI)
    ) ** (-anchor.eps_state)
    return SharedFeeEquilibrium(
        base_fee_wei=fee,
        target_gas=target,
        offered_shared_gas=shared,
        regular_gas=regular,
        state_gas=state,
        execution_gas=execution,
        data_gas=data,
        binding_branch=branch,
        floor_bounded=floor_bounded,
        state_demand_cap_active=(
            state_price_response >= anchor.state_demand_cap_multiple
        ),
    )
