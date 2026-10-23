"""Isolated target-ratio extension of the frozen EIP-8372 experiment.

The original calibration and replay remain unchanged. Both controllers below
use integer resource counters and identical uniform aggregate inclusion. Only
the diagnostic controller permits fractional-wei proportional fee updates.
"""
from __future__ import annotations

import math

import numpy as np

from dynamics.batched_replay import OnlineSummary
from shared_fee.normalized_state import (
    integers, integer_fee_update, normalized_state_gas, regular_root,
    scaled_state_limit, solve_normalized_equilibrium,
)


def calibrate_at_target(gas_limit, gas_target, baseline_cpsb, mapping, anchor):
    """Align both branches at an explicit target and byte-budget-matched CPSB."""
    limit = int(integers(gas_limit, "gas_limit"))
    target = int(integers(gas_target, "gas_target"))
    baseline = int(math.floor(baseline_cpsb))
    if not 0 < target < limit or baseline <= 0 or mapping <= 0:
        raise ValueError("positive state mapping and 0 < target < limit required")
    multiplier = baseline * mapping
    b_regular = regular_root(target, anchor)
    if b_regular <= 1:
        raise ValueError("no interior regular-branch calibration above 1 wei")
    b_state = anchor.reference_fee_gwei * 1e9 / multiplier * (
        target / (multiplier * anchor.q_state)) ** (-1 / anchor.eps_state)
    ideal_scale = b_state / b_regular
    cpsb = max(1, int(math.floor(baseline * ideal_scale + .5)))
    scale = cpsb * 100 // baseline
    raw_limit = int(scaled_state_limit(limit, scale))
    eq = solve_normalized_equilibrium(target, anchor, cpsb * mapping, scale)
    return dict(
        shared_limit=limit, shared_target=target, baseline_cpsb=baseline,
        baseline_cpsb_before_rounding=baseline_cpsb, ideal_scale=ideal_scale,
        cpsb=cpsb, state_gas_limit_scale=scale, effective_scale=scale/100,
        raw_state_limit=raw_limit, baseline_state_root_wei=b_state,
        m_state_raw=cpsb*mapping, m_state_normalized=cpsb*mapping*100/scale,
        max_state_bytes=raw_limit/cpsb, baseline_max_state_bytes=limit/baseline,
        byte_capacity_relative_error=(raw_limit/cpsb)/(limit/baseline)-1,
        state_byte_price_wei=cpsb*eq['equilibrium_fee_wei'], **eq,
    )


def continuous_fee_update(fee, used, target):
    """Unrounded EIP-1559 proportional update, not an exponential update.

    Removes both integer division and the minimum +1-wei upward increment.
    Retains the 1-wei price floor, denominator eight, and integer usage counters.
    """
    fee, used, target = np.broadcast_arrays(
        np.asarray(fee, float), np.asarray(used, float), np.asarray(target, float))
    if not (np.isfinite(fee).all() and np.isfinite(used).all()
            and np.isfinite(target).all()) or np.any(fee < 1) or np.any(target <= 0) or np.any(used < 0):
        raise ValueError("finite fees >= 1, usage >= 0, and targets > 0 required")
    return np.maximum(1., fee * (1. + (used-target)/target/8.))


def run_ratio_batch(config, shocks, initial_fee, *, burn_in=0,
                    controller="integer", progress=None):
    """Replay with original accounting and extra low-fee diagnostics.

    Each consecutive configuration receives the same ordered shock paths.
    The default integer arm is tested against the frozen reference kernel.
    """
    if controller not in ("integer", "continuous"):
        raise ValueError("controller must be integer or continuous")
    batch = len(config.gas_limit)
    n_paths, n_blocks, dimensions = shocks.shape
    if dimensions != 4 or batch % n_paths or not 0 <= burn_in < n_blocks:
        raise ValueError("invalid workload or burn-in")
    if not np.isfinite(shocks).all() or np.any(shocks <= 0):
        raise ValueError("finite positive shocks required")
    index = np.tile(np.arange(n_paths), batch // n_paths)
    limit = integers(config.gas_limit, "gas_limit")
    target = integers(config.gas_target, "gas_target")
    cpsb = integers(config.cpsb, "cpsb")
    scale = integers(config.state_gas_limit_scale, "scale")
    if np.any(target <= 0) or np.any(target >= limit):
        raise ValueError("0 < target < limit required")
    raw_limit = scaled_state_limit(limit, scale)
    m_state_raw = cpsb * config.bytes_per_reference_state
    fee = (integers(initial_fee, "initial_fee") if controller == "integer"
           else np.asarray(initial_fee, float).copy())
    if fee.shape != (batch,) or not np.isfinite(fee).all() or np.any(fee < 1):
        raise ValueError("one finite positive starting fee per replay required")
    update = integer_fee_update if controller == "integer" else continuous_fee_update
    summary = OnlineSummary(batch)
    names = (
        'execution', 'data', 'regular', 'state_normalized', 'state_raw',
        'state_bytes', 'offered_execution', 'excluded_execution',
        'regular_larger', 'state_larger', 'tied', 'regular_limit', 'state_limit',
        'any_limit', 'regular_scale', 'state_scale', 'mean_fee',
        'base_fee_exposure_eth', 'below_target', 'below_target_zero_decrease',
        'fee_below_8', 'fee_at_7',
    )
    sums = {name: np.zeros(batch) for name in names}
    minimum_fee = np.full(batch, np.inf)
    limits = np.stack([limit, limit, limit], axis=1)
    targets = np.stack([target, target, target], axis=1)
    for t in range(n_blocks):
        shock = shocks[index, t]
        execution = config.m_execution * config.q_execution_0 * (config.m_execution*fee/config.p0_wei)**(-config.eps_execution)*shock[:, 0]
        data = config.m_data * config.q_data_0 * (config.m_data*fee/config.p0_wei)**(-config.eps_data)*shock[:, 1]
        raw_offered = m_state_raw * config.q_state_0 * (m_state_raw*fee/config.p0_wei)**(-config.eps_state)*shock[:, 2]
        regular_offered = execution + data
        regular_ratio = limit / np.maximum(regular_offered, 1e-300)
        state_ratio = raw_limit / np.maximum(raw_offered, 1e-300)
        regular_active = (regular_ratio <= 1) & (regular_ratio <= state_ratio)
        state_active = (state_ratio <= 1) & (state_ratio <= regular_ratio)
        inclusion = np.minimum(1., np.minimum(regular_ratio, state_ratio))
        included_execution = execution*inclusion
        included_data = data*inclusion
        regular = np.minimum(limit, np.floor(included_execution+included_data).astype(np.int64))
        raw = np.minimum(raw_limit, np.floor(raw_offered*inclusion).astype(np.int64))
        regular = np.where(regular_active, limit, regular)
        raw = np.where(state_active, raw_limit, raw)
        normalized = normalized_state_gas(raw, scale)
        used_shared = np.maximum(regular, normalized)
        previous = fee
        fee = update(fee, used_shared, target)
        if t >= burn_in:
            used = np.stack([regular, used_shared, normalized], axis=1)
            normalized_offered = raw_offered*100/scale
            offered = np.stack([regular_offered, np.maximum(regular_offered, normalized_offered), normalized_offered], axis=1)
            summary.update(np.stack([fee]*3, axis=1), np.stack([previous]*3, axis=1),
                           used, offered, limits, targets=targets)
            below = used_shared < target
            values = dict(
                execution=included_execution, data=included_data, regular=regular,
                state_normalized=normalized, state_raw=raw, state_bytes=raw/cpsb,
                offered_execution=execution, excluded_execution=execution-included_execution,
                regular_larger=regular>normalized, state_larger=normalized>regular,
                tied=normalized==regular, regular_limit=regular>=limit,
                state_limit=raw>=raw_limit, any_limit=(regular>=limit)|(raw>=raw_limit),
                regular_scale=(regular_offered>limit)&(limit/regular_offered<=raw_limit/raw_offered),
                state_scale=(raw_offered>raw_limit)&(raw_limit/raw_offered<limit/regular_offered),
                mean_fee=previous,
                base_fee_exposure_eth=previous.astype(float)*(regular.astype(float)+raw)/1e18,
                below_target=below, below_target_zero_decrease=below & (fee==previous),
                fee_below_8=previous<8, fee_at_7=previous==7,
            )
            for name, value in values.items():
                sums[name] += value
            np.minimum(minimum_fee, previous, out=minimum_fee)
        if progress is not None and ((t+1) % 7200 == 0 or t+1 == n_blocks):
            progress(t+1, n_blocks)
    result = summary.to_dict()
    n = n_blocks-burn_in
    result.update({f'mean_{name}': value/n for name, value in sums.items()})
    result['execution_excluded_fraction'] = sums['excluded_execution']/np.maximum(sums['offered_execution'], 1e-300)
    result['regular_utilization'] = result['mean_regular']/target
    result['state_utilization'] = result['mean_state_normalized']/target
    result['final_base_fee_wei'] = fee
    result['minimum_measured_fee_wei'] = minimum_fee
    result['zero_decrease_given_below_target'] = np.divide(
        sums['below_target_zero_decrease'], sums['below_target'],
        out=np.zeros(batch), where=sums['below_target']>0)
    return result
