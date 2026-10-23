"""Isolated 25-case central target-ratio sweep and low-fee diagnostics.

No original kernel, demand extraction, or previously published output is changed.
Run from the repository root with PYTHONPATH=src and an Agg matplotlib backend.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT/'src', ROOT/'scripts', ROOT/'scripts/shared_fee'):
    sys.path.insert(0, str(directory))

from run_eip8372_calibration import (
    normalized_config, inputs as reference_inputs,
    calibration_table as reference_calibration_table,
)
from run_multiscale_design_surface import (
    BURN_IN, MEASURE_BLOCKS, N_SEEDS, build_canonical_workload,
)
from shared_fee.equilibrium import SharedFeeAnchor
from shared_fee.optimization import BLOCKS_PER_YEAR, BYTES_PER_GIB
from shared_fee.target_ratio import calibrate_at_target, run_ratio_batch

DATA = ROOT/'data/shared_fee'
REFERENCE = DATA/'eip8372'
OUT = DATA/'eip8372_target_ratio'
RATIOS = [(1, 2), (3, 5), (2, 3), (3, 4), (4, 5)]
EXPECTED_HASH = '2af918e3989c78a13c68bdd7c8f8e01df0e705a35ff9c0a0c81b115b41ecbec1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calibration_table(base):
    # Rebuild from the same original inputs, avoiding an extra CSV roundtrip
    # immediately before integer rounding at the equilibrium root.
    specs, _, source, _, _ = reference_inputs()
    cached = reference_calibration_table(specs, base, source)
    spec = specs[specs.window_days.eq(35)].iloc[0]
    records = []
    for _, old in cached.iterrows():
        anchor = SharedFeeAnchor(
            base.q_execution_per_block, base.q_data_per_block, base.q_state_per_block,
            old.m_execution, old.m_data, old.baseline_cpsb*old.bytes_per_reference_state,
            base.base_fee_ref_gwei, spec.eps_execution, spec.eps_data, spec.eps_state)
        for numerator, denominator in RATIOS:
            limit = int(old.shared_limit)
            target = limit*numerator//denominator
            # Transport precisely the original byte-budget convention. Flooring
            # CPSB adds at most one gas/byte of rounding, as in the reference.
            baseline = old.baseline_cpsb_before_rounding * (target/old.shared_target)
            cal = calibrate_at_target(limit, target, baseline, old.bytes_per_reference_state, anchor)
            if (numerator, denominator) == (1, 2):
                for key, value in cal.items():
                    if isinstance(value, str):
                        assert value == old[key], key
                    else:
                        np.testing.assert_allclose(value, old[key], rtol=1e-12, atol=1e-8, err_msg=key)
            assert abs(cal['equilibrium_regular_utilization']-1) < 1e-5
            assert abs(cal['equilibrium_state_utilization']-1) < 1e-5
            records.append(dict(
                **cal, propagation_time_s=old.propagation_time_s,
                target_ratio=numerator/denominator, ratio_label=f'{numerator}/{denominator}',
                ratio_numerator=numerator, ratio_denominator=denominator,
                floor_rate=int(old.floor_rate), m_execution=old.m_execution, m_data=old.m_data,
                bytes_per_reference_state=old.bytes_per_reference_state,
                window_days=35, calibration_window_days=35,
                eps_execution=spec.eps_execution, eps_data=spec.eps_data, eps_state=spec.eps_state,
                initial_fee_wei=int(old.launch_fee_wei),
                initial_fee_convention='inherited_half_target', controller='integer',
                benchmark='normalized_state_target_ratio',
                configuration=f'G{limit/1e6:.1f}-a{numerator}_{denominator}',
                state_byte_target=target/cal['cpsb']*cal['effective_scale'],
                target_state_growth_gib=target/cal['cpsb']*cal['effective_scale']*BLOCKS_PER_YEAR/BYTES_PER_GIB,
                nominal_full_block_fee_increase=(limit/target-1)/8,
            ))
    return pd.DataFrame(records)


def metrics_from_result(result, ix):
    metrics = {
        'metered_execution_gas': result['mean_execution'][ix],
        'data_or_floor_gas': result['mean_data'][ix],
        'regular_gas': result['mean_regular'][ix],
        'normalized_state_gas': result['mean_state_normalized'][ix],
        'raw_state_gas': result['mean_state_raw'][ix],
        'state_bytes': result['mean_state_bytes'][ix],
        'annualized_state_growth_gib': result['mean_state_bytes'][ix]*BLOCKS_PER_YEAR/BYTES_PER_GIB,
        'regular_utilization': result['regular_utilization'][ix],
        'state_utilization': result['state_utilization'][ix],
        'hard_limit_fraction': result['mean_any_limit'][ix],
        'normalized_controller_at_limit_fraction': result['included_limit_fraction'][ix, 1],
        'regular_limit_fraction': result['mean_regular_limit'][ix],
        'raw_state_limit_fraction': result['mean_state_limit'][ix],
        'regular_binding_fraction': result['mean_regular_larger'][ix],
        'state_binding_fraction': result['mean_state_larger'][ix],
        'branch_tie_fraction': result['mean_tied'][ix],
        'excluded_execution': result['mean_excluded_execution'][ix],
        'execution_excluded_fraction': result['execution_excluded_fraction'][ix],
        'mean_fee_wei': result['mean_mean_fee'][ix],
        'base_fee_exposure_proxy_eth_per_block': result['mean_base_fee_exposure_eth'][ix],
        'target_deviation': result['mean_absolute_target_deviation'][ix, 1],
        'regular_target_deviation': result['mean_absolute_target_deviation'][ix, 0],
        'state_target_deviation': result['mean_absolute_target_deviation'][ix, 2],
        'below_target_fraction': result['mean_below_target'][ix],
        'below_target_zero_decrease_fraction': result['mean_below_target_zero_decrease'][ix],
        'zero_decrease_given_below_target': result['zero_decrease_given_below_target'][ix],
        'fee_below_8_fraction': result['mean_fee_below_8'][ix],
        'fee_at_7_fraction': result['mean_fee_at_7'][ix],
        'minimum_measured_fee_wei': result['minimum_measured_fee_wei'][ix],
        'final_base_fee_wei': result['final_base_fee_wei'][ix],
    }
    for resource in ('execution', 'data', 'state'):
        metrics[f'{resource}_price_variation'] = result['log_return_sd'][ix, 1]
    return metrics


def replay(rows, base, workload, *, controller='integer', label='replay'):
    count = len(workload)
    started = time.monotonic()
    result = run_ratio_batch(
        normalized_config(rows, base, repeat=count), workload,
        np.repeat(rows.initial_fee_wei.to_numpy(), count), burn_in=BURN_IN,
        controller=controller,
        progress=lambda done, total: print(
            f'{label}: block {done:,}/{total:,}; {time.monotonic()-started:.1f}s', flush=True))
    summaries, paths = [], []
    for index, (_, row) in enumerate(rows.iterrows()):
        metrics = metrics_from_result(result, slice(index*count, (index+1)*count))
        summary = row.to_dict()
        summary['controller'] = controller
        for name, values in metrics.items():
            summary[name] = float(np.mean(values))
            summary[name+'_p05'] = float(np.quantile(values, .05))
            summary[name+'_p95'] = float(np.quantile(values, .95))
        summaries.append(summary)
        for replication in range(count):
            paths.append(dict(**row.to_dict(), replication=replication,
                              **{name: float(values[replication]) for name, values in metrics.items()}))
            paths[-1]['controller'] = controller
    return pd.DataFrame(summaries), pd.DataFrame(paths)


def verify_half_target(paths):
    cached = pd.read_csv(REFERENCE/'normalized_paths.csv').query('window_days == 35')
    keys = ['propagation_time_s', 'replication']
    new = paths.set_index(keys).sort_index()
    old = cached.set_index(keys).sort_index()
    tested = []
    for column in old.select_dtypes(include=[np.number]).columns:
        if column in new and column not in ['window_days']:
            np.testing.assert_allclose(new[column], old[column], rtol=1e-12, atol=1e-10, err_msg=column)
            tested.append(column)
    return tested


def paired_changes(paths):
    keys = ['propagation_time_s', 'replication']
    baseline = paths[paths.ratio_label.eq('1/2')]
    pairs = paths.merge(baseline, on=keys, suffixes=('', '_half'), validate='many_to_one')
    metrics = ['metered_execution_gas', 'annualized_state_growth_gib', 'hard_limit_fraction',
               'regular_utilization', 'state_utilization', 'execution_price_variation']
    summaries = []
    for key, group in pairs.groupby(['propagation_time_s', 'ratio_label', 'target_ratio']):
        row = dict(propagation_time_s=key[0], ratio_label=key[1], target_ratio=key[2])
        for metric in metrics:
            d = group[metric].to_numpy()-group[metric+'_half'].to_numpy()
            row[metric+'_change'] = d.mean()
            row[metric+'_change_week_p05'] = np.quantile(d, .05)
            row[metric+'_change_week_p95'] = np.quantile(d, .95)
            row[metric+'_change_mcse'] = d.std(ddof=1)/np.sqrt(len(d))
        summaries.append(row)
    return pd.DataFrame(summaries)


def eip7999_comparison(paths):
    cached = pd.read_csv(REFERENCE/'fixed_7999_paths.csv').query('window_days == 35')
    keys = ['propagation_time_s', 'replication']
    rows = []
    for label, group in paths.groupby('ratio_label'):
        paired = cached.merge(group, on=keys, suffixes=('_7999', '_8372'), validate='many_to_one')
        for key, p in paired.groupby(['propagation_time_s', 'benchmark_7999']):
            delta = p.metered_execution_gas_7999-p.metered_execution_gas_8372
            rows.append(dict(propagation_time_s=key[0], benchmark_7999=key[1], ratio_label=label,
                configuration_7999=p.configuration_7999.iloc[0],
                execution_7999=p.metered_execution_gas_7999.mean(),
                execution_8372=p.metered_execution_gas_8372.mean(),
                execution_gain_7999=delta.mean(), gain_week_p05=delta.quantile(.05),
                gain_week_p95=delta.quantile(.95), gain_mcse=delta.std(ddof=1)/np.sqrt(len(delta)),
                state_growth_7999=p.annualized_state_growth_gib_7999.mean(),
                state_growth_8372=p.annualized_state_growth_gib_8372.mean(),
                hard_limit_7999=p.hard_limit_fraction_7999.mean(),
                hard_limit_8372=p.hard_limit_fraction_8372.mean()))
    return pd.DataFrame(rows)


def main():
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    # Hash all existing source/result artifacts, not the new experiment folder.
    protected = list(REFERENCE.glob('*')) + list(DATA.glob('*.csv'))
    protected += list((ROOT/'data/7999').glob('*.csv'))
    protected += [ROOT/p for p in (
        'src/shared_fee/normalized_state.py', 'src/shared_fee/replay.py',
        'src/shared_fee/equilibrium.py', 'src/dynamics/batched_replay.py',
        'src/dynamics/multiscale_shocks.py', 'markdowns/eip8279_floor_calibration_report.md')]
    original = {str(p.relative_to(ROOT)): sha(p) for p in protected if p.is_file()}
    base = pd.read_csv(DATA/'equilibrium_anchor_by_floor_rate.csv').iloc[0]
    rows = calibration_table(base)
    rows.to_csv(OUT/'calibration.csv', index=False)
    print(rows[['propagation_time_s', 'ratio_label', 'equilibrium_fee_wei', 'max_state_bytes']].to_string(index=False), flush=True)
    workload = build_canonical_workload().paths
    digest = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
    assert digest == EXPECTED_HASH and workload.shape == (N_SEEDS, BURN_IN+MEASURE_BLOCKS, 4)
    print(f'Workload verified: {digest}', flush=True)
    half, half_paths = replay(rows[rows.ratio_label.eq('1/2')], base, workload, label='half-target reproduction')
    reproduced = verify_half_target(half_paths)
    print(f'All {len(reproduced)} cached metrics reproduced on all 160 half-target paths.', flush=True)
    rest, rest_paths = replay(rows[~rows.ratio_label.eq('1/2')], base, workload, label='20 new ratios')
    outcomes = pd.concat([half, rest]).sort_values(['propagation_time_s', 'target_ratio'])
    paths = pd.concat([half_paths, rest_paths]).sort_values(['propagation_time_s', 'target_ratio', 'replication'])
    outcomes.to_csv(OUT/'outcomes.csv', index=False)
    paths.to_csv(OUT/'paths.csv', index=False)
    paired_changes(paths).to_csv(OUT/'paired_changes.csv', index=False)
    eip7999_comparison(paths).to_csv(OUT/'paired_7999_comparison.csv', index=False)
    diagnostic = rows[rows.propagation_time_s.eq(3.5) & rows.ratio_label.isin(['1/2', '2/3', '4/5'])].copy()
    continuous, cpaths = replay(diagnostic, base, workload, controller='continuous', label='fractional-fee diagnostic')
    own = diagnostic.copy()
    own['initial_fee_wei'] = own.launch_fee_wei
    own['initial_fee_convention'] = 'own_root_ceiling'
    integer_own, ipaths = replay(own, base, workload, label='integer initialization diagnostic')
    reference_diagnostic = outcomes[outcomes.propagation_time_s.eq(3.5) & outcomes.ratio_label.isin(diagnostic.ratio_label)]
    pd.concat([reference_diagnostic, continuous, integer_own]).to_csv(OUT/'update_diagnostics.csv', index=False)
    pd.concat([cpaths, ipaths]).to_csv(OUT/'update_diagnostic_paths.csv', index=False)
    # Full-length unshocked controls separate controller deadbands from shocks.
    unity = np.ones((1, BURN_IN+MEASURE_BLOCKS, 4))
    controls = []
    for controller in ('integer', 'continuous'):
        for label, launch in [('inherited_half_target', diagnostic), ('own_root_ceiling', own)]:
            control, _ = replay(launch, base, unity, controller=controller, label=f'unshocked {controller} {label}')
            controls.append(control)
    pd.concat(controls).to_csv(OUT/'unshocked_controls.csv', index=False)
    for name, digest_before in original.items():
        assert sha(ROOT/name) == digest_before, f'Protected file changed: {name}'
    manifest = dict(
        experiment='EIP-8372 target-ratio sensitivity', date='2026-09-25',
        ratio_fractions=RATIOS, configuration_count=len(rows), central_window_days=35,
        alternate_elasticities_run=False, calibration_frozen_for_future_elasticities=True,
        workload_sha256=digest, workload_shape=list(workload.shape),
        burn_in=BURN_IN, measured_blocks=MEASURE_BLOCKS, replications=N_SEEDS,
        source_hashes=original, half_target_reproduced_metrics=reproduced,
        reproduced_tolerance=dict(rtol=1e-12, atol=1e-10),
        target_rounding='L*numerator//denominator',
        byte_budget='same per-block byte target as preserved half-target calibration, ~120 GiB/year',
        calibration='floor budget CPSB; round calibrated CPSB half up; derive integer percentage scale',
        initialization='inherited half-target integer launch fee at the same propagation allocation',
        diagnostic='unrounded proportional EIP-1559, denominator eight and 1-wei floor; integer counters unchanged',
        intervals='5th–95th percentiles of paired simulated-week differences, not confidence intervals for the mean',
        implementation_hashes={p: sha(ROOT/p) for p in (
            'src/shared_fee/target_ratio.py', 'scripts/shared_fee/run_eip8372_target_ratio.py')},
        elapsed_seconds=time.monotonic()-started,
    )
    (OUT/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(outcomes[['propagation_time_s', 'ratio_label', 'metered_execution_gas',
                    'annualized_state_growth_gib', 'hard_limit_fraction']].to_string(index=False), flush=True)
    print(f'Complete in {time.monotonic()-started:.1f}s; protected artifacts unchanged.', flush=True)


if __name__ == '__main__':
    main()
