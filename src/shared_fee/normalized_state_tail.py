"""Isolated state-tail sensitivity for the frozen EIP-8372 calibration.

The uncapped kernel and its historical provenance remain unchanged. This small
extension uses the same integer accounting and inclusion rule; parity tests
and the runner's per-path uncapped check guard against divergence.
"""
from __future__ import annotations

import math
import numpy as np

from dynamics.batched_replay import OnlineSummary
from shared_fee.normalized_state import (
    branch_quantities, integers, integer_fee_update, normalized_state_gas,
    scaled_state_limit, solve_normalized_equilibrium,
)


def validate_cap(cap):
    cap = np.asarray(cap, dtype=float)
    if np.any(np.isnan(cap)) or np.any(cap <= 0):
        raise ValueError("state caps must be positive, or infinity")
    return cap


def solve_capped_equilibrium(target, anchor, state_multiplier_raw, scale, cap):
    """Cap only price-driven state expansion, without recalibrating constants."""
    cap = float(validate_cap(cap))
    result = solve_normalized_equilibrium(target, anchor, state_multiplier_raw, scale)
    ceiling = state_multiplier_raw * anchor.q_state * cap * 100 / scale
    # A cap below the target removes the state-clearing root. At equality the
    # state branch has a plateau, and the regular root is its lowest joint fee.
    if ceiling <= target:
        fee = max(1., result['regular_root_wei'])
        e, d, raw, normalized = branch_quantities(fee, anchor, state_multiplier_raw, scale)
        raw = min(raw, state_multiplier_raw * anchor.q_state * cap)
        normalized = raw * 100 / scale
        result.update(equilibrium_fee_wei=fee,
            equilibrium_branch='regular' if ceiling < target else 'both',
            equilibrium_floor_bounded=result['regular_root_wei'] < 1,
            equilibrium_execution=e, equilibrium_regular=e+d,
            equilibrium_normalized_state=normalized,
            equilibrium_regular_utilization=(e+d)/target,
            equilibrium_state_utilization=normalized/target,
            integer_regular_at_root=int(math.floor(e+d)),
            integer_normalized_state_at_root=int(math.floor(raw))*100//int(scale),
            launch_fee_wei=int(math.ceil(fee)))
    # The inherited state root is explicitly the unrestricted root, not a
    # target-clearing fee available when the cap lies below the target.
    result['unrestricted_state_root_wei'] = result.pop('state_root_wei')
    result['state_target_reachable'] = ceiling >= target
    result['state_demand_cap_multiple'] = cap
    return result


def run_capped_normalized_batch(config, shocks, initial_fee, caps, *, burn_in=0, return_paths=False):
    """Same replay as normalized_state, with min(price expansion, cap) * shock."""
    batch = len(config.gas_limit)
    n_paths, n_blocks, dimensions = shocks.shape
    if dimensions != 4 or batch % n_paths or not 0 <= burn_in < n_blocks:
        raise ValueError('invalid workload shape or burn-in')
    if not np.isfinite(shocks).all() or np.any(shocks <= 0):
        raise ValueError('finite positive shocks required')
    caps = np.broadcast_to(validate_cap(caps), (batch,))
    index = np.tile(np.arange(n_paths), batch // n_paths)
    limit = integers(config.gas_limit, 'gas_limit')
    target = integers(config.gas_target, 'gas_target')
    cpsb = integers(config.cpsb, 'cpsb')
    scale = integers(config.state_gas_limit_scale, 'scale')
    raw_limit = scaled_state_limit(limit, scale)
    m_state_raw = cpsb * config.bytes_per_reference_state
    fee = integers(initial_fee, 'initial_fee')
    if fee.shape != (batch,) or np.any(fee == 0):
        raise ValueError('initial fees must be positive integer wei')
    summary = OnlineSummary(batch)
    sums = {k:np.zeros(batch) for k in ('execution', 'state_bytes', 'state_normalized',
        'regular', 'state_larger', 'regular_larger', 'tied', 'any_limit', 'mean_fee', 'cap_active')}
    limits = np.stack([limit]*3, axis=1)
    targets = np.stack([target]*3, axis=1)
    fee_paths = np.empty((batch,n_blocks)) if return_paths else None
    used_paths = np.empty((batch,n_blocks,3)) if return_paths else None
    for t in range(n_blocks):
        shock = shocks[index,t]
        execution = config.m_execution * config.q_execution_0 * (config.m_execution*fee/config.p0_wei)**(-config.eps_execution)*shock[:,0]
        data = config.m_data * config.q_data_0 * (config.m_data*fee/config.p0_wei)**(-config.eps_data)*shock[:,1]
        expansion = (m_state_raw*fee/config.p0_wei)**(-config.eps_state)
        raw_offered = m_state_raw * config.q_state_0 * np.minimum(expansion,caps)*shock[:,2]
        regular_offered = execution+data
        regular_ratio = limit / np.maximum(regular_offered,1e-300)
        state_ratio = raw_limit / np.maximum(raw_offered,1e-300)
        regular_active = (regular_ratio <= 1) & (regular_ratio <= state_ratio)
        state_active = (state_ratio <= 1) & (state_ratio <= regular_ratio)
        inclusion = np.minimum(1.,np.minimum(regular_ratio,state_ratio))
        included_execution = execution*inclusion
        included_data = data*inclusion
        regular = np.minimum(limit,np.floor(included_execution+included_data).astype(np.int64))
        raw = np.minimum(raw_limit,np.floor(raw_offered*inclusion).astype(np.int64))
        regular = np.where(regular_active,limit,regular)
        raw = np.where(state_active,raw_limit,raw)
        normalized = normalized_state_gas(raw,scale)
        used_shared = np.maximum(regular,normalized)
        previous = fee
        fee = integer_fee_update(fee,used_shared,target)
        if t >= burn_in:
            used = np.stack([regular,used_shared,normalized],axis=1)
            normalized_offered = raw_offered*100/scale
            offered = np.stack([regular_offered,np.maximum(regular_offered,normalized_offered),normalized_offered],axis=1)
            summary.update(np.stack([fee]*3,axis=1),np.stack([previous]*3,axis=1),used,offered,limits,targets=targets)
            values = dict(execution=included_execution,state_bytes=raw/cpsb,state_normalized=normalized,
                regular=regular,state_larger=normalized>regular,regular_larger=regular>normalized,
                tied=normalized==regular,any_limit=(regular>=limit)|(raw>=raw_limit),
                mean_fee=previous,cap_active=expansion>caps)
            for name,value in values.items():
                sums[name] += value
        if return_paths:
            fee_paths[:,t] = fee
            used_paths[:,t] = np.stack([included_execution,regular,normalized],axis=1)
    result = summary.to_dict()
    result.update({f'mean_{k}':v/(n_blocks-burn_in) for k,v in sums.items()})
    result['regular_utilization'] = result['mean_regular']/target
    result['state_utilization'] = result['mean_state_normalized']/target
    if return_paths:
        result.update(fee_paths=fee_paths,used_paths=used_paths)
    return result
