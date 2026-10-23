"""Frozen target-ratio replay with exact integer EIP-4844-style shared updates.

Defaults to the preserved 4/5 experiment; --ratio 1/2 writes a separate
eip8372_excess_update_half/ result set. Central calibration is frozen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / 'src', ROOT / 'scripts', ROOT / 'scripts/shared_fee'):
    sys.path.insert(0, str(directory))

from run_eip8372_target_ratio import (
    BURN_IN, MEASURE_BLOCKS, N_SEEDS, EXPECTED_HASH, build_canonical_workload,
    calibration_table, normalized_config, metrics_from_result,
)
from shared_fee.excess_update import run_controller_batch

DATA = ROOT / 'data/shared_fee'
OUT = DATA / 'eip8372_excess_update'
CONTROLLERS = ('integer', 'continuous', 'excess_matched', 'excess_log1125')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(rows, base, workload, controller, label):
    count = len(workload)
    start = time.monotonic()
    result = run_controller_batch(
        normalized_config(rows, base, repeat=count), workload,
        np.repeat(rows.initial_fee_wei.to_numpy(), count), burn_in=BURN_IN,
        controller=controller, progress=lambda done, total: print(
            f'{label}: {done:,}/{total:,} blocks; {time.monotonic()-start:.1f}s', flush=True))
    summaries, paths = [], []
    for index, (_, row) in enumerate(rows.iterrows()):
        ix = slice(index*count, (index+1)*count)
        metrics = metrics_from_result(result, ix)
        for name in ('any_near_limit', 'fee_at_1', 'floor_bounded', 'excess_at_zero',
                     'fee_decreases', 'fee_increases'):
            metrics[name+'_fraction'] = result['mean_'+name][ix]
        metrics['shared_utilization'] = result['shared_utilization'][ix]
        metrics['maximum_measured_fee_wei'] = result['maximum_measured_fee_wei'][ix]
        if controller.startswith('excess_'):
            for name in ('update_denominator', 'measured_start_excess', 'final_excess', 'floor_reflection_gas'):
                metrics[name] = result[name][ix]
            metrics['smooth_full_block_fee_increase'] = np.expm1(
                (row.shared_limit-row.shared_target)/result['update_denominator'][ix])
        metadata = dict(row.to_dict(), controller=controller, n_replications=count,
                        measured_blocks=MEASURE_BLOCKS, burn_in_blocks=BURN_IN)
        summary = dict(metadata)
        for name, values in metrics.items():
            summary[name] = float(np.mean(values))
            summary[name+'_p05'] = float(np.quantile(values, .05))
            summary[name+'_p95'] = float(np.quantile(values, .95))
        summaries.append(summary)
        for replication in range(count):
            paths.append(dict(metadata, replication=replication,
                              **{name: float(values[replication]) for name, values in metrics.items()}))
    return pd.DataFrame(summaries), pd.DataFrame(paths)


def verify_saved(paths, original, controller):
    keys = ['propagation_time_s', 'replication']
    new = paths[paths.controller.eq(controller)].set_index(keys).sort_index()
    old = original.set_index(keys).sort_index()
    new = new.loc[old.index]
    metrics = [c for c in old.select_dtypes(include=[np.number]).columns
               if c in new and c not in ('n_replications',)]
    for metric in metrics:
        np.testing.assert_allclose(new[metric], old[metric], rtol=1e-12, atol=1e-10,
                                   err_msg=metric)
    return len(metrics)


def paired_differences(paths):
    rows = []
    reference = paths[paths.controller.eq('integer')]
    for controller in CONTROLLERS[1:]:
        paired = paths[paths.controller.eq(controller)].merge(
            reference, on=['propagation_time_s', 'replication'], suffixes=('', '_integer'),
            validate='one_to_one')
        for propagation, group in paired.groupby('propagation_time_s'):
            row = dict(controller=controller, propagation_time_s=propagation)
            for metric in ('metered_execution_gas', 'annualized_state_growth_gib',
                           'any_near_limit_fraction', 'hard_limit_fraction', 'mean_fee_wei'):
                diff = group[metric]-group[metric+'_integer']
                row[metric+'_gain'] = diff.mean()
                row[metric+'_gain_week_p05'] = diff.quantile(.05)
                row[metric+'_gain_week_p95'] = diff.quantile(.95)
                row[metric+'_gain_mcse'] = diff.std(ddof=1)/np.sqrt(len(diff))
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ratio', choices=('1/2', '4/5'), default='4/5')
    args = parser.parse_args()
    destination = OUT if args.ratio == '4/5' else DATA/'eip8372_excess_update_half'
    start = time.monotonic()
    protected = list((DATA/'eip8372_target_ratio').glob('*'))
    protected += list((DATA/'eip8372').glob('*.csv'))
    protected += [DATA/'equilibrium_anchor_by_floor_rate.csv']
    for directory in (OUT, DATA/'eip8372_excess_update_half'):
        if directory != destination:
            protected += list(directory.glob('*'))
    protected += [ROOT/p for p in ('src/shared_fee/target_ratio.py',
        'src/shared_fee/normalized_state.py', 'src/dynamics/batched_replay.py',
        'src/dynamics/multiscale_shocks.py', 'scripts/run_multiscale_design_surface.py',
        'markdowns/eip8279_floor_calibration_report.md')]
    before = {str(p.relative_to(ROOT)): sha(p) for p in protected if p.is_file()}
    base = pd.read_csv(DATA/'equilibrium_anchor_by_floor_rate.csv').iloc[0]
    rows = calibration_table(base)
    rows = rows[rows.ratio_label.eq(args.ratio)].sort_values('propagation_time_s')
    assert len(rows) == 5
    workload = build_canonical_workload().paths
    digest = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
    assert digest == EXPECTED_HASH
    assert workload.shape == (N_SEEDS, BURN_IN+MEASURE_BLOCKS, 4)
    print(f'Preserved workload verified: {digest}', flush=True)
    all_outcomes, all_paths = [], []
    for controller in CONTROLLERS:
        outcomes, paths = replay(rows, base, workload, controller, controller)
        all_outcomes.append(outcomes)
        all_paths.append(paths)
        print(outcomes[['propagation_time_s', 'metered_execution_gas',
                        'annualized_state_growth_gib', 'any_near_limit_fraction',
                        'hard_limit_fraction', 'mean_fee_wei']].to_string(index=False), flush=True)
    outcomes, paths = pd.concat(all_outcomes), pd.concat(all_paths)
    saved_integer = pd.read_csv(DATA/'eip8372_target_ratio/paths.csv')
    saved_integer = saved_integer[saved_integer.ratio_label.eq(args.ratio)]
    saved_continuous = pd.read_csv(DATA/'eip8372_target_ratio/update_diagnostic_paths.csv')
    saved_continuous = saved_continuous[
        saved_continuous.ratio_label.eq(args.ratio) & saved_continuous.controller.eq('continuous')]
    integer_metrics = verify_saved(paths, saved_integer, 'integer')
    continuous_metrics = verify_saved(paths, saved_continuous, 'continuous')
    print(f'Reproduced cached metrics: integer={integer_metrics}, continuous={continuous_metrics}.', flush=True)
    controls = []
    for controller in CONTROLLERS:
        summary, _ = replay(rows[rows.propagation_time_s.eq(3.5)], base,
                            np.ones((1, BURN_IN+MEASURE_BLOCKS, 4)), controller,
                            f'unshocked {controller}')
        controls.append(summary)
    comparison = pd.read_csv(DATA/'eip8372/fixed_7999_paths.csv').query('window_days == 35')
    comparisons = []
    for controller in CONTROLLERS:
        joined = paths[paths.controller.eq(controller)].merge(
            comparison, on=['propagation_time_s', 'replication'],
            suffixes=('_8372', '_7999'), validate='one_to_many')
        for (propagation, benchmark), group in joined.groupby(['propagation_time_s', 'benchmark_7999']):
            gain = group.metered_execution_gas_7999-group.metered_execution_gas_8372
            comparisons.append(dict(controller=controller, propagation_time_s=propagation,
                benchmark_7999=benchmark, configuration_7999=group.configuration_7999.iloc[0],
                execution_7999=group.metered_execution_gas_7999.mean(),
                execution_8372=group.metered_execution_gas_8372.mean(),
                execution_gain_7999=gain.mean(), gain_week_p05=gain.quantile(.05),
                gain_week_p95=gain.quantile(.95), gain_mcse=gain.std(ddof=1)/np.sqrt(len(gain))))
    for path, digest_before in before.items():
        assert sha(ROOT/path) == digest_before, f'Protected file changed: {path}'
    destination.mkdir(parents=True, exist_ok=True)
    outcomes.to_csv(destination/'outcomes.csv', index=False)
    paths.to_csv(destination/'paths.csv', index=False)
    paired_differences(paths).to_csv(destination/'paired_changes.csv', index=False)
    pd.DataFrame(comparisons).to_csv(destination/'paired_7999_comparison.csv', index=False)
    pd.concat(controls).to_csv(destination/'unshocked_controls.csv', index=False)
    manifest = dict(
        material_passport=dict(origin_skill='experiment-agent', origin_mode='run',
            origin_date='2026-10-02', verification_status='VERIFIED', version_label='excess_update_v2'),
        experiment=f'EIP-8372, frozen {args.ratio} configurations, EIP-4844-style shared controller',
        target_ratio=args.ratio,
        status='completed', elapsed_seconds=time.monotonic()-start,
        controllers=list(CONTROLLERS), configuration_count=5, central_window_days=35,
        workload_sha256=digest, workload_shape=list(workload.shape), burn_in=BURN_IN,
        measured_blocks=MEASURE_BLOCKS, replications=N_SEEDS,
        calibration='Original ratio-specific CPSB, state normalization, floor, limits and smooth roots frozen.',
        initialization='Original half-target launch fees; minimal exact excess reproducing each integer fee.',
        shared_usage='max(included regular gas, floor(100*included raw state gas/scale))',
        excess_update='x_next=max(0,x+shared_usage-target); b_next=fake_exponential(1,x_next,F)',
        fee_arithmetic='Exact integer Taylor helper; accelerated by exact, binary-searched integer-fee thresholds.',
        smoothing=dict(excess_matched='F=8*T; local derivative matched to 1559 denominator eight',
                       excess_log1125='F=round(T/ln(1.125)); original 4844 target-normalized response convention'),
        scope='Diagnostic protocol variants, not specified EIP-8372 fee rules; no blob demand/reserve introduced.',
        intervals='p05-p95 across simulated weeks, not confidence intervals for the mean; MCSE from paired paths.',
        reproduced_cached_metrics=dict(integer=integer_metrics, continuous=continuous_metrics),
        source_hashes=before,
        implementation_hashes={p: sha(ROOT/p) for p in ('src/shared_fee/excess_update.py',
            'scripts/shared_fee/run_eip8372_excess_update.py', 'tests/test_eip8372_excess_update.py')},
        references=['https://eips.ethereum.org/EIPS/eip-4844', 'https://eips.ethereum.org/EIPS/eip-1559'],
    )
    (destination/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Complete in {time.monotonic()-start:.1f}s; all {len(before)} protected files unchanged.', flush=True)


if __name__ == '__main__':
    main()
