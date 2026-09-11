"""Matched resource pulses for the frozen four-second central designs."""
from __future__ import annotations

import hashlib
import json
import numpy as np
import pandas as pd

from run_eip8372_calibration import (OUT, BURN_IN, inputs, normalized_config,
    build_canonical_workload, build_config, run_batch, bundle_cost_equivalent_start,
    run_normalized_batch)

MEASURED = 7200
ONSET = BURN_IN + 1200
HALF_LIFE = 120
EVENT_BLOCKS = 600
RECOVERY_HOLD = 120


def recovery_time(log_price_ratio):
    """First 120-block interval within ±log(1.1), after the event-window peak.

    All three effective prices must be within a symmetric multiplicative band.
    NaN means no recovery before the end of this path, rather than zero delay.
    The supplied trajectory starts at pulse onset.
    """
    distance = np.abs(log_price_ratio).max(axis=1)
    peak = int(np.argmax(distance[:EVENT_BLOCKS]))
    inside = distance <= np.log(1.1)
    runs = np.convolve(inside.astype(int), np.ones(RECOVERY_HOLD, dtype=int), mode='valid')
    candidates = np.flatnonzero((runs == RECOVERY_HOLD) & (np.arange(len(runs)) >= peak))
    return float(candidates[0]) if len(candidates) else np.nan


def normalized_replay(row, base, workload):
    config = normalized_config(row, base)
    result = run_normalized_batch(config, workload,
        np.repeat(row.launch_fee_wei.to_numpy(), 32), burn_in=BURN_IN, return_paths=True)
    prices = np.repeat(result['fee_paths'][:, :, None], 3, axis=2)
    # Multipliers cancel in same-design pulse / no-pulse price ratios.
    return result['used_paths'][:, :, 0], prices


def eip_replay(rows, specs, demand, metering, workload):
    combinations = [(0, r.execution_target, r.data_target, r.execution_limit, r.data_limit)
                    for _, r in rows.iterrows()]
    config = build_config(combinations, specs, demand, metering)
    result = run_batch(config, workload, bundle_cost_equivalent_start(config),
        burn_in=BURN_IN, bundle_consistent=True, return_paths=True)
    f = result['fee_paths']
    prices = np.stack([config.m_execution*f[:, :, 0]+config.w_execution[:, None]*f[:, :, 1],
        config.m_data_static*f[:, :, 1],
        config.m_state*f[:, :, 2]+config.w_state[:, None]*f[:, :, 1]], axis=2)
    return result['used_paths'][:, :, 0], prices


def main():
    specs, base, source, demand, metering = inputs()
    specs = specs[specs.window_days.eq(35)].reset_index(drop=True)
    normalized = pd.read_csv(OUT/'normalized_outcomes.csv')
    normalized = normalized[normalized.window_days.eq(35)&normalized.propagation_time_s.eq(4)]
    eip = pd.read_csv(OUT/'fixed_7999_outcomes.csv')
    eip = eip[eip.window_days.eq(35)&eip.propagation_time_s.eq(4)].reset_index(drop=True)
    full = build_canonical_workload().paths
    digest = hashlib.sha256(np.ascontiguousarray(full).view(np.uint8)).hexdigest()
    assert digest == json.loads((OUT/'manifest.json').read_text())['workload_sha256']
    workload = full[:, :BURN_IN+MEASURED].copy()
    controls = {}
    for mechanism in ('normalized_state','7999'):
        controls[mechanism] = (normalized_replay(normalized, base, workload) if mechanism=='normalized_state'
                              else eip_replay(eip, specs, demand, metering, workload))
    records, curves = [], []
    for resource, dimension in [('execution',0),('static_data',1),('state',2)]:
        shocked = workload.copy()
        shocked[:, ONSET:, dimension] *= 1+2.**(-np.arange(workload.shape[1]-ONSET)/HALF_LIFE)
        for mechanism in ('normalized_state','7999'):
            execution, prices = (normalized_replay(normalized, base, shocked) if mechanism=='normalized_state'
                                else eip_replay(eip, specs, demand, metering, shocked))
            control_execution, control_prices = controls[mechanism]
            families = ['normalized_state'] if mechanism=='normalized_state' else list(eip.benchmark)
            log_ratio = np.log(prices/control_prices)
            for family_index, family in enumerate(families):
                ix = slice(family_index*32, (family_index+1)*32)
                event = slice(ONSET, ONSET+EVENT_BLOCKS)
                baseline_mean = control_execution[ix,event].mean(axis=1)
                for replication in range(32):
                    j = family_index*32+replication
                    records.append(dict(benchmark=family, resource=resource, replication=replication,
                        propagation_time_s=4., window_days=35,
                        event_execution=execution[j,event].mean(),
                        control_event_execution=baseline_mean[replication],
                        event_execution_difference=execution[j,event].mean()-baseline_mean[replication],
                        event_execution_fraction=execution[j,event].mean()/baseline_mean[replication]-1,
                        recovery_blocks=recovery_time(log_ratio[j,ONSET:]),
                        **{f'peak_{r}_price_multiple':np.exp(log_ratio[j,event,k].max())
                           for k,r in enumerate(('execution','data','state'))}))
                for block in range(0,1200,20):
                    slot = slice(ONSET+block, ONSET+block+20)
                    # Pool gas before dividing: each interval uses the same 32 paths.
                    curves.append(dict(benchmark=family, resource=resource, blocks_after_onset=block+9.5,
                        execution_fraction=execution[ix,slot].mean()/control_execution[ix,slot].mean()-1))
    frame = pd.DataFrame(records)
    frame.to_csv(OUT/'stress_paths.csv', index=False)
    summaries = []
    for (family,resource), group in frame.groupby(['benchmark','resource']):
        recovered = group.recovery_blocks.dropna()
        summaries.append(dict(benchmark=family, resource=resource,
            event_execution_difference=group.event_execution_difference.mean(),
            event_execution_fraction=group.event_execution_fraction.mean(),
            **{f'peak_{r}_price_multiple':group[f'peak_{r}_price_multiple'].mean() for r in ('execution','data','state')},
            recovered_fraction=len(recovered)/32,
            median_recovery_among_recovered=recovered.median()))
    summary = pd.DataFrame(summaries)
    summary.to_csv(OUT/'stress_outcomes.csv', index=False)
    pd.DataFrame(curves).to_csv(OUT/'stress_response_curve.csv', index=False)
    (OUT/'stress_manifest.json').write_text(json.dumps(dict(workload_sha256=digest,
        propagation_time_s=4, window_days=35, n_paths=32, burn_in=BURN_IN, measured_blocks=MEASURED,
        onset_measured_block=1200, pulse_multiplier=2, half_life_blocks=120, event_blocks=600,
        recovery_band='1/1.1 to 1.1 times matched no-pulse effective price for all three resources',
        recovery_hold_blocks=120, recovery_search='after largest absolute log-price deviation in first 600 event blocks',
        censoring_horizon_blocks_after_onset=6000, price_alignment='post-block fee, for the following block',
        pulse_definition='Multiply only the chosen parent shock; keep all other sampled columns unchanged'), indent=2)+'\n')
    print(summary.to_string(index=False))


if __name__=='__main__':
    main()
