"""Batched Glamsterdam dynamic replay, for comparison against full EIP-7999.

Glamsterdam keeps one EIP-1559-style base fee while metering regular gas and
state gas as separate branches. Regular gas carries execution and data; the
state branch carries EIP-8037 state creation. The shared fee responds to
whichever branch is larger:

    u(b) = max( m_E q_E(b) + m_D q_D(b),  m_S q_S(b) )

so metering is multi-dimensional while pricing stays one-dimensional. That is
the structural difference being tested: under EIP-7999 the same workload faces
three prices and a BAL charge, here it faces one price and none.

Shock convention. The same latent workload (s_E, s_D, s_S, a) drives both
mechanisms. The access-composition shock ``a`` changes the BAL payload in both
worlds, but BAL is not a priced resource under Glamsterdam, so it does not
enter fee-controlled gas here. It is carried through only as a payload
diagnostic, which is the mechanism difference rather than an inconsistency.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .batched_replay import (
    EffectivePriceSummary,
    GWEI, MIN_BASE_FEE_PER_GAS, OnlineSummary, compute_base_fee,
    excess_gas_for_base_fee, update_excess_gas,
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
    fee = np.maximum(initial_base_fee_wei.astype(float), MIN_BASE_FEE_PER_GAS)
    excess = excess_gas_for_base_fee(fee)

    summary = OnlineSummary(batch)
    effective_prices = EffectivePriceSummary(batch)
    previous_prices = np.stack(
        [config.m_execution * fee, config.m_data * fee, config.m_state * fee], axis=1
    )
    execution_used_sum = np.zeros(batch)
    bal_payload_sum = np.zeros(batch)
    regular_binding_count = np.zeros(batch)
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
        used = np.minimum(offered, config.gas_limit)

        previous_fee = fee
        excess = update_excess_gas(excess, used, config.gas_target, config.gas_limit)
        fee = compute_base_fee(excess)

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
                np.stack([config.m_execution * q_execution, used, state_gas], axis=1),
                np.stack([config.m_execution * q_execution, offered, state_gas], axis=1),
                np.stack([config.gas_limit, config.gas_limit,
                          np.full_like(config.gas_limit, np.inf)], axis=1),
            )
            # Included execution is its share of the clipped regular branch.
            share = np.where(regular_gas > 0, config.m_execution * q_execution / regular_gas, 0.0)
            execution_used_sum += share * np.minimum(regular_gas, config.gas_limit)
            regular_binding_count += regular_gas >= state_gas
            # BAL is produced here exactly as it is under EIP-7999, by the same
            # parent activity and the same access shock. It is simply not
            # metered or priced, so it never enters the fee-controlled gas above
            # and grows with whatever activity the shared fee happens to admit.
            # Carrying it as a payload makes that difference measurable.
            bal_payload_sum += (
                config.w_execution * q_execution + config.w_state * q_state
            ) * a_access
        previous_prices = prices

    result = summary.to_dict()
    result.update(effective_prices.to_dict())
    result["final_base_fee_wei"] = fee
    result["mean_included_execution"] = execution_used_sum / max(measured, 1)
    result["regular_binding_fraction"] = regular_binding_count / max(measured, 1)
    result["mean_bal_payload"] = bal_payload_sum / max(measured, 1)
    return result
