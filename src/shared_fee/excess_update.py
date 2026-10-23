"""Isolated EIP-4844-style controller diagnostic for the EIP-8372 benchmark.

The inclusion/accounting loop mirrors the frozen target_ratio kernel and is
tested against it for both original controllers. Published kernels stay intact.
Only the shared fee controller changes; raw state charges remain unnormalized.
"""
from __future__ import annotations

import math
import numpy as np

from dynamics.batched_replay import OnlineSummary
from shared_fee.normalized_state import (
    integers, integer_fee_update, normalized_state_gas, scaled_state_limit,
)
from shared_fee.target_ratio import continuous_fee_update
from sim.basefee import fake_exponential


def excess_for_fee(fee: int, denominator: int) -> int:
    """Smallest integer excess whose exact fake exponential reaches fee."""
    fee, denominator = int(fee), int(denominator)
    if fee < 1 or denominator < 1:
        raise ValueError("positive fee and denominator required")
    if fee == 1:
        return 0
    low, high = 0, max(1, math.ceil(denominator * math.log(fee)) + 1)
    while fake_exponential(1, high, denominator) < fee:
        high *= 2
    while low + 1 < high:
        middle = (low + high) // 2
        if fake_exponential(1, middle, denominator) >= fee:
            high = middle
        else:
            low = middle
    return high


class ExactExponentialFees:
    """Exact integer fees via cached transition thresholds, not float exp.

Each threshold is binary-searched using the EIP-4844 integer Taylor helper.
    Searching these monotone thresholds is equivalent to that helper at every
    integer excess value, including at integer-fee boundaries. Above the cache
    range, evaluate the same exact helper directly so a rare large fee does not
    require precomputing every intermediate fee threshold.
    """
    MAX_CACHED_FEE = 4096

    def __init__(self, denominators):
        self.denominators = integers(denominators, "denominators")
        if np.any(self.denominators == 0):
            raise ValueError("positive denominators required")
        self.groups = [(int(d), np.flatnonzero(self.denominators == d))
                       for d in np.unique(self.denominators)]
        self.thresholds = {d: [0, excess_for_fee(2, d)] for d, _ in self.groups}

    def __call__(self, excess):
        excess = integers(excess, "excess")
        if excess.shape != self.denominators.shape:
            raise ValueError("one excess per denominator required")
        fees = np.empty_like(excess)
        for denominator, indices in self.groups:
            maximum = int(excess[indices].max())
            thresholds = self.thresholds[denominator]
            while maximum >= thresholds[-1] and len(thresholds) < self.MAX_CACHED_FEE:
                end = min(self.MAX_CACHED_FEE, max(32, len(thresholds) * 2))
                thresholds.extend(excess_for_fee(f, denominator)
                                  for f in range(len(thresholds) + 1, end + 1))
            cached = excess[indices] < thresholds[-1]
            fees[indices[cached]] = np.searchsorted(
                thresholds, excess[indices[cached]], side="right")
            fees[indices[~cached]] = [
                fake_exponential(1, int(x), denominator) for x in excess[indices[~cached]]
            ]
        return fees


def update_denominators(target, controller):
    target = integers(target, "target")
    if np.any(target == 0):
        raise ValueError("positive targets required")
    if controller == "excess_matched":
        return integers(8 * target, "denominator")
    if controller == "excess_log1125":
        return integers(np.floor(target / math.log(1.125) + .5), "denominator")
    raise ValueError("unknown excess controller")


def run_controller_batch(config, shocks, initial_fee, *, burn_in=0,
                         controller="excess_matched", progress=None):
    """Shared max(regular, normalized state) with unchanged bundle inclusion."""
    if controller not in ("integer", "continuous", "excess_matched", "excess_log1125"):
        raise ValueError("unknown controller")
    is_excess = controller.startswith("excess_")
    batch = len(config.gas_limit)
    n_paths, n_blocks, dimensions = shocks.shape
    if dimensions != 4 or batch % n_paths or not 0 <= burn_in < n_blocks:
        raise ValueError("invalid workload or burn-in")
    if not np.isfinite(shocks).all() or np.any(shocks <= 0):
        raise ValueError("finite positive shocks required")
    index = np.tile(np.arange(n_paths), batch // n_paths)
    limit, target = integers(config.gas_limit, "limit"), integers(config.gas_target, "target")
    if np.any(target <= 0) or np.any(target >= limit):
        raise ValueError("0 < target < limit required")
    cpsb = integers(config.cpsb, "cpsb")
    scale = integers(config.state_gas_limit_scale, "scale")
    raw_limit = scaled_state_limit(limit, scale)
    m_state_raw = cpsb * config.bytes_per_reference_state
    fee = (np.asarray(initial_fee, float).copy() if controller == "continuous"
           else integers(initial_fee, "initial_fee"))
    if fee.shape != (batch,) or not np.isfinite(fee).all() or np.any(fee < 1):
        raise ValueError("one positive starting fee per replay required")
    if is_excess:
        denominators = update_denominators(target, controller)
        fee_from_excess = ExactExponentialFees(denominators)
        excess = np.array([excess_for_fee(b, d) for b, d in zip(fee, denominators)], dtype=np.int64)
        np.testing.assert_array_equal(fee_from_excess(excess), fee)
        reflection = np.zeros(batch)
    summary = OnlineSummary(batch)
    names = ('execution', 'data', 'regular', 'state_normalized', 'state_raw',
             'state_bytes', 'offered_execution', 'excluded_execution',
             'regular_larger', 'state_larger', 'tied', 'regular_limit', 'state_limit',
             'any_limit', 'regular_scale', 'state_scale', 'mean_fee',
             'base_fee_exposure_eth', 'below_target', 'below_target_zero_decrease',
             'fee_below_8', 'fee_at_7', 'any_near_limit', 'fee_at_1', 'shared',
             'floor_bounded', 'excess_at_zero', 'fee_decreases', 'fee_increases')
    sums = {name: np.zeros(batch) for name in names}
    minimum_fee, maximum_fee = np.full(batch, np.inf), np.zeros(batch)
    limits = np.stack([limit] * 3, axis=1)
    targets = np.stack([target] * 3, axis=1)
    for t in range(n_blocks):
        if is_excess and t == burn_in:
            measured_start_excess = excess.copy()
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
        included_execution, included_data = execution*inclusion, data*inclusion
        regular = np.minimum(limit, np.floor(included_execution+included_data).astype(np.int64))
        raw = np.minimum(raw_limit, np.floor(raw_offered*inclusion).astype(np.int64))
        regular = np.where(regular_active, limit, regular)
        raw = np.where(state_active, raw_limit, raw)
        normalized = normalized_state_gas(raw, scale)
        used_shared = np.maximum(regular, normalized)
        previous = fee
        if is_excess:
            old_excess = excess
            candidate = excess + used_shared - target
            excess = np.maximum(0, candidate)
            fee = fee_from_excess(excess)
            if t >= burn_in:
                reflection += np.maximum(0, -candidate)
        elif controller == "integer":
            fee = integer_fee_update(fee, used_shared, target)
        else:
            fee = continuous_fee_update(fee, used_shared, target)
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
                any_near_limit=(100*regular>=98*limit)|(100*raw>=98*raw_limit),
                fee_at_1=previous==1, shared=used_shared,
                floor_bounded=(previous==1)&below,
                excess_at_zero=(old_excess==0) if is_excess else np.zeros(batch),
                fee_decreases=fee<previous, fee_increases=fee>previous,
            )
            for name, value in values.items():
                sums[name] += value
            np.minimum(minimum_fee, previous, out=minimum_fee)
            np.maximum(maximum_fee, previous, out=maximum_fee)
        if progress is not None and ((t+1) % 7200 == 0 or t+1 == n_blocks):
            progress(t+1, n_blocks)
    result = summary.to_dict()
    n = n_blocks-burn_in
    result.update({f'mean_{name}': value/n for name, value in sums.items()})
    result['execution_excluded_fraction'] = sums['excluded_execution']/np.maximum(sums['offered_execution'], 1e-300)
    result['regular_utilization'] = result['mean_regular']/target
    result['state_utilization'] = result['mean_state_normalized']/target
    result['shared_utilization'] = result['mean_shared']/target
    result['final_base_fee_wei'] = fee
    result['minimum_measured_fee_wei'], result['maximum_measured_fee_wei'] = minimum_fee, maximum_fee
    result['zero_decrease_given_below_target'] = np.divide(
        sums['below_target_zero_decrease'], sums['below_target'],
        out=np.zeros(batch), where=sums['below_target']>0)
    if is_excess:
        result['update_denominator'] = denominators
        result['measured_start_excess'] = measured_start_excess
        result['final_excess'] = excess
        result['floor_reflection_gas'] = reflection
        # Exact accumulator accounting: sum(usage-target) = end-start-reflection.
        np.testing.assert_array_equal(sums['shared']-n*target,
                                      excess-measured_start_excess-reflection)
    return result
