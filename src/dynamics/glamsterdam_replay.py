"""Batched Glamsterdam dynamic replay, for comparison against full EIP-7999.

Glamsterdam keeps one EIP-1559-style base fee while metering regular gas and
state gas as separate branches. Regular gas carries execution and data; the
state branch carries EIP-8037 state creation. The shared fee responds to
whichever branch is larger:

    u(b) = max( m_E q_E(b) + m_D q_D(b),  m_S q_S(b) )

so metering is multi-dimensional while pricing stays one-dimensional. That is
the structural difference being tested: under EIP-7999 the same workload faces
three prices and a BAL charge, here it faces one price and none.

Fee update. Glamsterdam is a hardfork of the current chain and keeps the EIP-1559
rule, which is *not* the rule EIP-7999 uses. EIP-1559 moves the fee itself by a
fraction of the relative gap to target; with the usual limit equal to twice the
target, its largest upward move is one eighth per block. EIP-7999 accumulates a
normalised excess-gas counter and exponentiates it, with dynamics that depend on
each resource's target-to-limit ratio. The two share the same fixed point at
u = T, but differ in the approach to it and in floor behaviour. Volatility,
limit-hit and floor statistics are therefore not transferable between them.
Using the EIP-7999 rule here would compare EIP-7999's dynamics against itself.

Shock convention. The same latent workload (s_E, s_D, s_S, a) drives both
mechanisms. The access-composition shock ``a`` changes the BAL payload in both
worlds, but BAL is not a priced resource under Glamsterdam, so it does not
enter fee-controlled gas here. It is carried through only as a payload
diagnostic, which is the mechanism difference rather than an inconsistency.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .batched_replay import EffectivePriceSummary, GWEI, OnlineSummary

BASE_FEE_MAX_CHANGE_DENOMINATOR = 8


def update_base_fee_1559(
    base_fee: np.ndarray, gas_used: np.ndarray, gas_target: np.ndarray,
) -> np.ndarray:
    """EIP-1559 base-fee update, reproducing the reference integer arithmetic.

    The spec computes ``base_fee * delta_gas // target // 8``. Successive floors
    by a positive integer collapse, so that equals ``floor(base_fee * delta_gas /
    (target * 8))``, which is evaluated here in a grouping that keeps the
    intermediate small enough to stay inside float64's exact-integer range.

    The upward step is floored at one wei by the spec; the downward step is not,
    so integer truncation stalls the fee once ``base_fee`` drops below the change
    denominator. An under-target path can therefore stall below 8 wei rather
    than reaching EIP-7999's explicit one-wei floor, and that truncation is
    reproduced rather than
    smoothed over.
    """

    gap = gas_used - gas_target
    step = np.floor(
        base_fee * (np.abs(gap) / (gas_target * float(BASE_FEE_MAX_CHANGE_DENOMINATOR)))
    )
    return np.where(
        gap > 0, base_fee + np.maximum(step, 1.0),
        np.where(gap < 0, base_fee - step, base_fee),
    )


@dataclass(frozen=True)
class GlamsterdamConfig:
    """Per-trajectory arrays of shape (B,), plus scalar anchors."""

    gas_target: np.ndarray
    gas_limit: np.ndarray

    eps_execution: np.ndarray
    eps_data: np.ndarray
    eps_state: np.ndarray

    m_execution: float
    m_data: float
    m_state: float
    w_execution: float
    w_state: float
    q_execution_0: float
    q_data_0: float
    q_state_0: float
    p0_gwei: float

    @property
    def batch_size(self) -> int:
        return int(self.gas_target.shape[0])


def run_glamsterdam_batch(
    config: GlamsterdamConfig,
    shocks: np.ndarray,
    initial_base_fee_wei: np.ndarray,
    burn_in: int = 0,
) -> dict[str, np.ndarray]:
    """Advance every trajectory and return online summaries.

    Summaries use the same three-slot layout as the EIP-7999 kernel so the two
    mechanisms can be compared without reshaping: slot 0 is execution, slot 1
    is the fee-controlling branch, slot 2 is state.
    """

    n_paths, n_blocks, n_shocks = shocks.shape
    if n_shocks != 4:
        raise ValueError("shocks must have four components")
    batch = config.batch_size
    if n_paths == batch:
        shock_index = None
    elif batch % n_paths == 0:
        shock_index = np.tile(np.arange(n_paths), batch // n_paths)
    else:
        raise ValueError("batch is not a multiple of the supplied shock paths")

    p0_wei = config.p0_gwei * GWEI
    # EIP-1559 carries no excess-gas accumulator: the fee itself is the state.
    fee = np.maximum(initial_base_fee_wei.astype(float), 1.0)

    summary = OnlineSummary(batch)
    effective_prices = EffectivePriceSummary(batch)
    previous_prices = np.stack(
        [config.m_execution * fee, config.m_data * fee, config.m_state * fee], axis=1
    )
    execution_used_sum = np.zeros(batch)
    data_used_sum = np.zeros(batch)
    execution_rationed_sum = np.zeros(batch)
    data_rationed_sum = np.zeros(batch)
    state_rationed_sum = np.zeros(batch)
    bal_payload_sum = np.zeros(batch)
    regular_binding_count = np.zeros(batch)
    sub_eight_count = np.zeros(batch)
    measured = 0

    for t in range(n_blocks):
        block = shocks[:, t, :] if shock_index is None else shocks[shock_index, t, :]
        s_execution, s_data, s_state, a_access = (block[:, i] for i in range(4))

        # One shared fee, three effective prices through the metering multipliers.
        q_execution = (
            config.q_execution_0
            * np.maximum(config.m_execution * fee / p0_wei, 1e-300) ** (-config.eps_execution)
            * s_execution
        )
        q_data = (
            config.q_data_0
            * np.maximum(config.m_data * fee / p0_wei, 1e-300) ** (-config.eps_data)
            * s_data
        )
        q_state = (
            config.q_state_0
            * np.maximum(config.m_state * fee / p0_wei, 1e-300) ** (-config.eps_state)
            * s_state
        )

        regular_gas = config.m_execution * q_execution + config.m_data * q_data
        state_gas = config.m_state * q_state
        offered = np.maximum(regular_gas, state_gas)
        # Both branches are produced by the same transactions. If either branch
        # exceeds the shared limit, an aggregate inclusion rule must reduce all
        # parent activity together; otherwise the replay reports state or
        # execution from transactions that could not have been included.
        bundle_scale = np.minimum(
            1.0, config.gas_limit / np.maximum(offered, 1e-300)
        )
        included_execution = config.m_execution * q_execution * bundle_scale
        included_data = config.m_data * q_data * bundle_scale
        included_state = state_gas * bundle_scale
        used = offered * bundle_scale

        previous_fee = fee
        fee = update_base_fee_1559(fee, used, config.gas_target)

        # The three effective activity prices. Each is a fixed multiple of the one
        # shared fee, so under this mechanism they are perfectly correlated by
        # construction and share a single volatility -- the contrast against
        # EIP-7999, where each price carries its own fee plus a BAL term, is the
        # comparison these series exist to make.
        prices = np.stack([config.m_execution * fee, config.m_data * fee,
                           config.m_state * fee], axis=1)

        if t >= burn_in:
            measured += 1
            effective_prices.update(prices, previous_prices)
            triple = lambda values: np.stack([values, values, values], axis=1)
            summary.update(
                triple(fee), triple(previous_fee),
                np.stack([included_execution, used, included_state], axis=1),
                np.stack([config.m_execution * q_execution, offered, state_gas], axis=1),
                np.stack([config.gas_limit, config.gas_limit, config.gas_limit], axis=1),
            )
            execution_used_sum += included_execution
            data_used_sum += included_data
            execution_rationed_sum += config.m_execution * q_execution - included_execution
            data_rationed_sum += config.m_data * q_data - included_data
            state_rationed_sum += state_gas - included_state
            regular_binding_count += regular_gas >= state_gas
            # BAL is produced here exactly as it is under EIP-7999, by the same
            # parent activity and the same access shock. It is simply not
            # metered or priced, so it never enters the fee-controlled gas above
            # and grows with whatever activity the shared fee happens to admit.
            # Carrying it as a payload makes that difference measurable.
            bal_payload_sum += (
                config.w_execution * q_execution + config.w_state * q_state
            ) * a_access * bundle_scale
            sub_eight_count += fee < BASE_FEE_MAX_CHANGE_DENOMINATOR
        previous_prices = prices

    result = summary.to_dict()
    result.update(effective_prices.to_dict())
    result["final_base_fee_wei"] = fee
    result["mean_included_execution"] = execution_used_sum / max(measured, 1)
    result["mean_included_data"] = data_used_sum / max(measured, 1)
    result["mean_rationed_execution"] = execution_rationed_sum / max(measured, 1)
    result["mean_rationed_data"] = data_rationed_sum / max(measured, 1)
    result["mean_rationed_state"] = state_rationed_sum / max(measured, 1)
    result["regular_binding_fraction"] = regular_binding_count / max(measured, 1)
    result["mean_bal_payload"] = bal_payload_sum / max(measured, 1)
    result["sub_eight_fee_fraction"] = sub_eight_count / max(measured, 1)
    return result
