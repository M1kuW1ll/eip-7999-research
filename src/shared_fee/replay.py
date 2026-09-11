"""Independent dynamic replay for the EIP-8131/EIP-8279 shared-fee arm.

The mechanism has one EIP-1559 fee and one common limit. Counterfactual
regular gas combines execution and data metering, while EIP-8037 state gas is
the competing branch:

    regular = m_execution * q_execution + m_data * q_data
    shared   = max(regular, m_state * q_state)

The implementation is deliberately separate from the frozen Glamsterdam
driver. It imports only generic streaming summaries used by every replay.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dynamics.batched_replay import EffectivePriceSummary, GWEI, OnlineSummary


BASE_FEE_MAX_CHANGE_DENOMINATOR = 8


def update_base_fee_1559(
    base_fee: np.ndarray,
    gas_used: np.ndarray,
    gas_target: np.ndarray,
) -> np.ndarray:
    """Apply the EIP-1559 integer base-fee update to a batch of trajectories."""

    gap = gas_used - gas_target
    step = np.floor(
        base_fee
        * (np.abs(gap) / (gas_target * float(BASE_FEE_MAX_CHANGE_DENOMINATOR)))
    )
    return np.where(
        gap > 0,
        base_fee + np.maximum(step, 1.0),
        np.where(gap < 0, base_fee - step, base_fee),
    )


@dataclass(frozen=True)
class SharedFeeConfig:
    """Per-trajectory mechanism inputs; vector fields have shape ``(batch,)``."""

    gas_target: np.ndarray
    gas_limit: np.ndarray
    eps_execution: np.ndarray
    eps_data: np.ndarray
    eps_state: np.ndarray
    m_execution: float | np.ndarray
    m_data: float | np.ndarray
    m_state: float | np.ndarray
    q_execution_0: float
    q_data_0: float
    q_state_0: float
    p0_gwei: float
    w_execution: float = 0.0
    w_state: float = 0.0
    state_demand_cap_multiple: float | np.ndarray = float("inf")

    @property
    def batch_size(self) -> int:
        return int(self.gas_target.shape[0])


def run_shared_fee_batch(
    config: SharedFeeConfig,
    shocks: np.ndarray,
    initial_base_fee_wei: np.ndarray,
    *,
    burn_in: int = 0,
) -> dict[str, np.ndarray]:
    """Replay one shared fee over common multiscale shock paths."""

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

    fee = np.maximum(np.asarray(initial_base_fee_wei, dtype=float), 1.0)
    if fee.shape != (batch,):
        raise ValueError("initial_base_fee_wei must have shape (batch,)")

    def batch_parameter(value: float | np.ndarray, name: str) -> np.ndarray:
        parameter = np.asarray(value, dtype=float)
        if parameter.ndim == 0:
            parameter = np.full(batch, float(parameter))
        if parameter.shape != (batch,):
            raise ValueError(f"{name} must be scalar or shape (batch,)")
        if not np.isfinite(parameter).all() or np.any(parameter <= 0):
            raise ValueError(f"{name} must be finite and positive")
        return parameter

    m_execution = batch_parameter(config.m_execution, "m_execution")
    m_data = batch_parameter(config.m_data, "m_data")
    m_state = batch_parameter(config.m_state, "m_state")

    state_cap = np.asarray(config.state_demand_cap_multiple, dtype=float)
    if state_cap.ndim == 0:
        state_cap = np.full(batch, float(state_cap))
    if state_cap.shape != (batch,):
        raise ValueError("state_demand_cap_multiple must be scalar or shape (batch,)")
    if np.any(state_cap <= 0) or np.any(np.isnan(state_cap)):
        raise ValueError("state_demand_cap_multiple must be positive")

    p0_wei = config.p0_gwei * GWEI
    summary = OnlineSummary(batch)
    effective_prices = EffectivePriceSummary(batch)
    previous_prices = np.stack(
        [m_execution * fee, m_data * fee, m_state * fee],
        axis=1,
    )
    execution_sum = np.zeros(batch)
    data_sum = np.zeros(batch)
    state_sum = np.zeros(batch)
    execution_reference_sum = np.zeros(batch)
    data_reference_sum = np.zeros(batch)
    state_reference_sum = np.zeros(batch)
    regular_sum = np.zeros(batch)
    base_fee_exposure_proxy_sum = np.zeros(batch)
    regular_binding = np.zeros(batch)
    state_cap_active = np.zeros(batch)
    bal_payload_sum = np.zeros(batch)
    measured = 0

    targets = np.stack(
        [config.gas_target, config.gas_target, config.gas_target], axis=1
    )
    limits = np.stack(
        [config.gas_limit, config.gas_limit, config.gas_limit], axis=1
    )

    for t in range(n_blocks):
        block = shocks[:, t, :] if shock_index is None else shocks[shock_index, t, :]
        s_execution, s_data, s_state, access_shock = (
            block[:, index] for index in range(4)
        )
        q_execution = (
            config.q_execution_0
            * np.maximum(m_execution * fee / p0_wei, 1e-300)
            ** (-config.eps_execution)
            * s_execution
        )
        q_data = (
            config.q_data_0
            * np.maximum(m_data * fee / p0_wei, 1e-300)
            ** (-config.eps_data)
            * s_data
        )
        state_price_response = (
            np.maximum(m_state * fee / p0_wei, 1e-300)
            ** (-config.eps_state)
        )
        q_state = (
            config.q_state_0
            * np.minimum(state_price_response, state_cap)
            * s_state
        )

        execution_gas = m_execution * q_execution
        data_gas = m_data * q_data
        state_gas = m_state * q_state
        regular_gas = execution_gas + data_gas
        offered_shared = np.maximum(regular_gas, state_gas)
        scale = np.minimum(1.0, config.gas_limit / np.maximum(offered_shared, 1e-300))
        used_shared = offered_shared * scale
        included_execution = execution_gas * scale
        included_data = data_gas * scale
        included_state = state_gas * scale

        previous_fee = fee
        fee = update_base_fee_1559(fee, used_shared, config.gas_target)
        prices = np.stack(
            [m_execution * fee, m_data * fee, m_state * fee],
            axis=1,
        )

        if t >= burn_in:
            measured += 1
            used = np.stack(
                [included_execution, used_shared, included_state], axis=1
            )
            offered = np.stack(
                [execution_gas, offered_shared, state_gas], axis=1
            )
            summary.update(
                np.stack([fee, fee, fee], axis=1),
                np.stack([previous_fee, previous_fee, previous_fee], axis=1),
                used,
                offered,
                limits,
                targets=targets,
            )
            effective_prices.update(prices, previous_prices)
            execution_sum += included_execution
            data_sum += included_data
            state_sum += included_state
            execution_reference_sum += q_execution * scale
            data_reference_sum += q_data * scale
            state_reference_sum += q_state * scale
            included_regular = included_execution + included_data
            regular_sum += included_regular
            # This is a counter-weighted base-fee exposure proxy rather than
            # an exact reconstruction of transaction payments.  Keep the
            # block-level product so fee/usage covariance is retained.
            base_fee_exposure_proxy_sum += (
                included_regular + included_state
            ) * previous_fee
            regular_binding += regular_gas >= state_gas
            state_cap_active += state_price_response >= state_cap
            # Diagnostic only. Runtime BAL has no independent fee or demand
            # channel in this one-dimensional benchmark.
            bal_payload_sum += (
                config.w_execution * q_execution + config.w_state * q_state
            ) * access_shock * scale
        previous_prices = prices

    result = summary.to_dict()
    result.update(effective_prices.to_dict())
    denominator = max(measured, 1)
    result.update(
        {
            "final_base_fee_wei": fee,
            "mean_included_execution": execution_sum / denominator,
            "mean_included_data": data_sum / denominator,
            "mean_included_state": state_sum / denominator,
            "mean_reference_execution": execution_reference_sum / denominator,
            "mean_reference_data": data_reference_sum / denominator,
            "mean_reference_state": state_reference_sum / denominator,
            "mean_included_regular": regular_sum / denominator,
            "mean_base_fee_exposure_proxy_wei": (
                base_fee_exposure_proxy_sum / denominator
            ),
            "regular_binding_fraction": regular_binding / denominator,
            "state_demand_cap_active_fraction": state_cap_active / denominator,
            "mean_bal_payload": bal_payload_sum / denominator,
        }
    )
    return result
