"""EIP-8372-style demand calibration and integer block-accounting replay.

This is a separate aggregate benchmark. Existing equal-raw-limit kernels are
unchanged. Transaction payment/refunds are not reconstructed here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import brentq

from dynamics.batched_replay import OnlineSummary
from shared_fee.equilibrium import SharedFeeAnchor

SCALE_DENOMINATOR = 100
INT_MAX = np.iinfo(np.int64).max


def integers(value, name):
    value = np.asarray(value)
    if not np.isfinite(value).all() or np.any(value < 0) or np.any(value != np.floor(value)):
        raise ValueError(f"{name} must contain nonnegative integers")
    if np.any(value >= INT_MAX):
        raise OverflowError(name)
    return value.astype(np.int64)


def scaled_state_limit(gas_limit, scale):
    limit, scale = integers(gas_limit, "gas_limit"), integers(scale, "scale")
    if np.any(scale == 0) or np.any(limit > INT_MAX // np.maximum(scale, 1)):
        raise ValueError("invalid or overflowing raw state limit")
    return limit * scale // SCALE_DENOMINATOR


def normalized_state_gas(raw_state, scale):
    raw, scale = integers(raw_state, "raw_state"), integers(scale, "scale")
    if np.any(scale == 0) or np.any(raw > INT_MAX // SCALE_DENOMINATOR):
        raise ValueError("invalid or overflowing normalized state counter")
    return raw * SCALE_DENOMINATOR // scale


def integer_fee_update(fee, used, target):
    fee, used, target = integers(fee, "fee"), integers(used, "used"), integers(target, "target")
    if np.any(fee == 0) or np.any(target == 0):
        raise ValueError("positive fee and target required")
    gap = used - target
    if np.any(fee > INT_MAX // np.maximum(np.abs(gap), 1)):
        raise OverflowError("EIP-1559 update product")
    delta = fee * np.abs(gap) // target // 8
    return np.where(gap > 0, fee + np.maximum(delta, 1),
                    np.where(gap < 0, fee - delta, fee)).astype(np.int64)


def branch_quantities(fee, anchor, state_multiplier_raw, scale):
    """Continuous demand quantities with a raw state price and normalized usage."""
    p0 = anchor.reference_fee_gwei * 1e9
    execution = anchor.m_execution * anchor.q_execution * (anchor.m_execution * fee / p0) ** -anchor.eps_execution
    data = anchor.m_data * anchor.q_data * (anchor.m_data * fee / p0) ** -anchor.eps_data
    raw = state_multiplier_raw * anchor.q_state * (state_multiplier_raw * fee / p0) ** -anchor.eps_state
    return execution, data, raw, raw * 100 / scale


def regular_root(target, anchor):
    def residual(log_fee):
        execution, data, *_ = branch_quantities(math.exp(log_fee), anchor, anchor.m_state, 100)
        return math.log((execution + data) / target)
    return math.exp(brentq(residual, -200, 200, xtol=1e-13))


def solve_normalized_equilibrium(target, anchor, state_multiplier_raw, scale):
    """Solve the smooth demand root, then verify the integer counter brackets.

    The demand root is real-valued. The replay launches from its ceiling in
    integer wei; EIP-1559 quantization need not permit an exact stationary fee.
    """
    b_regular = regular_root(target, anchor)
    m_normalized = state_multiplier_raw * 100 / scale
    b_state = anchor.reference_fee_gwei * 1e9 / state_multiplier_raw * (
        target / (m_normalized * anchor.q_state)) ** (-1 / anchor.eps_state)
    fee = max(1.0, b_regular, b_state)
    e, d, raw, normalized = branch_quantities(fee, anchor, state_multiplier_raw, scale)
    raw_int = int(math.floor(raw))
    n_int = raw_int * 100 // int(scale)
    regular_int = int(math.floor(e + d))
    branch = "both" if abs(b_regular / b_state - 1) < 1e-5 else ("regular" if b_regular > b_state else "state")
    return dict(equilibrium_fee_wei=fee, regular_root_wei=b_regular, state_root_wei=b_state,
                equilibrium_branch=branch, equilibrium_floor_bounded=max(b_regular, b_state) < 1,
                equilibrium_execution=e, equilibrium_regular=e+d, equilibrium_normalized_state=normalized,
                equilibrium_regular_utilization=(e+d)/target, equilibrium_state_utilization=normalized/target,
                integer_regular_at_root=regular_int, integer_normalized_state_at_root=n_int,
                launch_fee_wei=int(math.ceil(fee)))


def calibrate(gas_limit, baseline_cpsb, bytes_per_reference_state, anchor):
    """Calibrate once; round actual CPSB, then derive integer percent per EIP."""
    limit = int(math.floor(gas_limit))
    target = limit // 2
    baseline = int(math.floor(baseline_cpsb))
    if baseline <= 0 or bytes_per_reference_state <= 0:
        raise ValueError("positive baseline and state-byte mapping required")
    baseline_multiplier = baseline * bytes_per_reference_state
    regular_fee = regular_root(target, anchor)
    if regular_fee <= 1:
        raise ValueError("calibration regular root is at/below one wei; no interior alignment")
    state_fee = anchor.reference_fee_gwei * 1e9 / baseline_multiplier * (
        target / (baseline_multiplier * anchor.q_state)) ** (-1 / anchor.eps_state)
    ideal_scale = state_fee / regular_fee
    cpsb = max(1, int(math.floor(baseline * ideal_scale + .5)))
    scale = cpsb * 100 // baseline
    if scale <= 0:
        raise ValueError("integer percentage scale rounded to zero")
    raw_limit = int(scaled_state_limit(limit, scale))
    equilibrium = solve_normalized_equilibrium(target, anchor, cpsb * bytes_per_reference_state, scale)
    baseline_max_bytes = limit / baseline
    return dict(shared_limit=limit, shared_target=target, baseline_cpsb=baseline,
                baseline_cpsb_before_rounding=baseline_cpsb, ideal_scale=ideal_scale,
                cpsb=cpsb, state_gas_limit_scale=scale, effective_scale=scale/100,
                raw_state_limit=raw_limit, baseline_state_root_wei=state_fee,
                m_state_raw=cpsb * bytes_per_reference_state,
                m_state_normalized=cpsb * bytes_per_reference_state * 100 / scale,
                max_state_bytes=raw_limit/cpsb, baseline_max_state_bytes=baseline_max_bytes,
                byte_capacity_relative_error=(raw_limit/cpsb)/baseline_max_bytes-1,
                state_byte_price_wei=cpsb*equilibrium['equilibrium_fee_wei'],
                **equilibrium)


@dataclass(frozen=True)
class NormalizedStateConfig:
    gas_limit: np.ndarray
    gas_target: np.ndarray
    cpsb: np.ndarray
    state_gas_limit_scale: np.ndarray
    eps_execution: np.ndarray
    eps_data: np.ndarray
    eps_state: np.ndarray
    m_execution: np.ndarray
    m_data: np.ndarray
    bytes_per_reference_state: float
    q_execution_0: float
    q_data_0: float
    q_state_0: float
    p0_wei: float


def run_normalized_batch(config, shocks, initial_fee, *, burn_in=0, return_paths=False):
    """Integer raw limits/normalization/controller over continuous aggregate demand."""
    batch = len(config.gas_limit)
    n_paths, n_blocks, dimensions = shocks.shape
    if dimensions != 4 or batch % n_paths or not 0 <= burn_in < n_blocks:
        raise ValueError("invalid workload shape or burn-in")
    if not np.isfinite(shocks).all() or np.any(shocks <= 0):
        raise ValueError("finite positive shocks required")
    index = np.tile(np.arange(n_paths), batch // n_paths)
    limit = integers(config.gas_limit, "gas_limit")
    target = integers(config.gas_target, "gas_target")
    cpsb = integers(config.cpsb, "cpsb")
    scale = integers(config.state_gas_limit_scale, "scale")
    raw_limit = scaled_state_limit(limit, scale)
    m_state_raw = cpsb * config.bytes_per_reference_state
    fee = integers(initial_fee, "initial_fee")
    if fee.shape != (batch,) or np.any(fee == 0):
        raise ValueError("initial fees must be positive integer wei")
    summary = OnlineSummary(batch)
    sums = {name:np.zeros(batch) for name in ('execution','data','regular','state_normalized','state_raw',
            'state_bytes','offered_execution','excluded_execution','regular_larger','state_larger','tied',
            'regular_limit','state_limit','any_limit','regular_scale','state_scale','mean_fee','base_fee_exposure_eth')}
    limits = np.stack([limit,limit,limit],axis=1)
    targets = np.stack([target,target,target],axis=1)
    fee_paths = np.empty((batch,n_blocks)) if return_paths else None
    used_paths = np.empty((batch,n_blocks,3)) if return_paths else None
    for t in range(n_blocks):
        shock = shocks[index,t]
        execution = config.m_execution * config.q_execution_0 * (config.m_execution*fee/config.p0_wei)**(-config.eps_execution)*shock[:,0]
        data = config.m_data * config.q_data_0 * (config.m_data*fee/config.p0_wei)**(-config.eps_data)*shock[:,1]
        raw_offered = m_state_raw * config.q_state_0 * (m_state_raw*fee/config.p0_wei)**(-config.eps_state)*shock[:,2]
        regular_offered = execution + data
        regular_ratio = limit / np.maximum(regular_offered, 1e-300)
        state_ratio = raw_limit / np.maximum(raw_offered, 1e-300)
        regular_active = (regular_ratio <= 1) & (regular_ratio <= state_ratio)
        state_active = (state_ratio <= 1) & (state_ratio <= regular_ratio)
        inclusion = np.minimum(1.,np.minimum(regular_ratio,state_ratio))
        included_execution = execution*inclusion
        included_data = data*inclusion
        regular = np.minimum(limit,np.floor(included_execution+included_data).astype(np.int64))
        raw = np.minimum(raw_limit,np.floor(raw_offered*inclusion).astype(np.int64))
        # The binding continuous constraint reaches its integer cap exactly;
        # multiplication by the inclusion fraction can otherwise lose one gas
        # unit through floating-point roundoff before the integer conversion.
        regular = np.where(regular_active, limit, regular)
        raw = np.where(state_active, raw_limit, raw)
        # The protocol accounting uses integer operations, not raw/float(scale).
        normalized = normalized_state_gas(raw,scale)
        used_shared = np.maximum(regular,normalized)
        previous = fee
        fee = integer_fee_update(fee,used_shared,target)
        if t >= burn_in:
            used = np.stack([regular,used_shared,normalized],axis=1)
            normalized_offered = raw_offered*100/scale
            offered = np.stack([regular_offered,np.maximum(regular_offered,normalized_offered),normalized_offered],axis=1)
            summary.update(np.stack([fee]*3,axis=1),np.stack([previous]*3,axis=1),used,offered,limits,targets=targets)
            values = dict(execution=included_execution,data=included_data,regular=regular,state_normalized=normalized,
                          state_raw=raw,state_bytes=raw/cpsb,offered_execution=execution,
                          excluded_execution=execution-included_execution,regular_larger=regular>normalized,
                          state_larger=normalized>regular,tied=normalized==regular,
                          regular_limit=regular>=limit,state_limit=raw>=raw_limit,
                          any_limit=(regular>=limit)|(raw>=raw_limit),
                          regular_scale=(regular_offered>limit)&(limit/regular_offered<=raw_limit/raw_offered),
                          state_scale=(raw_offered>raw_limit)&(raw_limit/raw_offered<limit/regular_offered),mean_fee=previous,
                          # Raw state gas carries the monetary charge. Use the
                          # fee of this block, before the controller update.
                          base_fee_exposure_eth=previous.astype(float)*(regular.astype(float)+raw)/1e18)
            for name,value in values.items():
                sums[name] += value
        if return_paths:
            fee_paths[:,t] = fee
            used_paths[:,t] = np.stack([included_execution,regular,normalized],axis=1)
    result = summary.to_dict()
    measured = n_blocks-burn_in
    result.update({f'mean_{name}':value/measured for name,value in sums.items()})
    result['execution_excluded_fraction'] = sums['excluded_execution']/np.maximum(sums['offered_execution'],1e-300)
    result['regular_utilization'] = result['mean_regular']/target
    result['state_utilization'] = result['mean_state_normalized']/target
    result['final_base_fee_wei'] = fee
    if return_paths:
        result.update(fee_paths=fee_paths,used_paths=used_paths)
    return result
