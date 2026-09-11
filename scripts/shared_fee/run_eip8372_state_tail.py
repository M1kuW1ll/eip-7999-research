"""Three-second frozen-calibration state caps, with paired saved 7999 references.

Run from repository root with PYTHONPATH=src. No RPC or historical-shock
re-estimation. Writes only data/shared_fee/eip8372/state_tail/.
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
for directory in (ROOT/'src',ROOT/'scripts',ROOT/'scripts/shared_fee'):
    sys.path.insert(0,str(directory))

from run_eip8372_calibration import inputs, normalized_config, record_metrics
from run_multiscale_design_surface import build_canonical_workload, BURN_IN, MEASURE_BLOCKS, N_SEEDS
from shared_fee.equilibrium import SharedFeeAnchor
from shared_fee.normalized_state_tail import solve_capped_equilibrium, run_capped_normalized_batch
from shared_fee.optimization import BLOCKS_PER_YEAR, BYTES_PER_GIB

DATA = ROOT/'data/shared_fee'
OUT = DATA/'eip8372/state_tail'
CAPS = (1.5,2.,3.,4.,5.,np.inf)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def central_three(frame):
    subset = frame[frame.propagation_time_s.eq(3.)]
    return subset[subset.window_days.eq(35)] if 'window_days' in subset else subset


def metadata(base):
    frozen = central_three(pd.read_csv(DATA/'eip8372/normalized_outcomes.csv')).iloc[0]
    anchor = SharedFeeAnchor(base.q_execution_per_block,base.q_data_per_block,base.q_state_per_block,
        frozen.m_execution,frozen.m_data,frozen.m_state_raw,base.base_fee_ref_gwei,
        frozen.eps_execution,frozen.eps_data,frozen.eps_state)
    rows = []
    for cap in CAPS:
        row = {k:frozen[k] for k in ('benchmark','window_days','propagation_time_s','configuration',
            'shared_limit','shared_target','floor_rate','m_execution','m_data','cpsb',
            'state_gas_limit_scale','bytes_per_reference_state','eps_execution','eps_data','eps_state')}
        row.update(solve_capped_equilibrium(frozen.shared_target,anchor,frozen.m_state_raw,
            int(frozen.state_gas_limit_scale),cap))
        row['state_demand_cap_label'] = 'unrestricted' if np.isinf(cap) else f'{cap:g}x'
        row['calibration_frozen'] = True
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    started = time.monotonic()
    protected = list(DATA.glob('*.csv'))+list((DATA/'eip8372').glob('*.csv'))
    protected += [ROOT/'src/shared_fee/normalized_state.py',ROOT/'src/shared_fee/replay.py',
        ROOT/'src/dynamics/batched_replay.py']
    before = {str(p.relative_to(ROOT)):digest(p) for p in protected}
    _,base,*_ = inputs()
    rows = metadata(base)
    print(rows[['state_demand_cap_label','equilibrium_fee_wei','equilibrium_branch']].to_string(index=False),flush=True)
    workload = build_canonical_workload().paths
    workload_hash = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
    original_manifest = json.loads((DATA/'eip8372/manifest.json').read_text())
    assert workload_hash == original_manifest['workload_sha256']
    assert workload.shape == (N_SEEDS,BURN_IN+MEASURE_BLOCKS,4) == (32,57600,4)
    print('Replaying six caps at 3s on the unchanged 32 paths; EIP-8372 constants frozen.',flush=True)
    result = run_capped_normalized_batch(normalized_config(rows,base,N_SEEDS),workload,
        np.repeat(rows.launch_fee_wei.to_numpy(),N_SEEDS),
        np.repeat(rows.state_demand_cap_multiple.to_numpy(),N_SEEDS),burn_in=BURN_IN)
    records,paths = [],[]
    for index,(_,r) in enumerate(rows.iterrows()):
        row = r.to_dict();ix = slice(index*N_SEEDS,(index+1)*N_SEEDS)
        metrics = {
            'metered_execution_gas':result['mean_execution'][ix],
            'annualized_state_growth_gib':result['mean_state_bytes'][ix]*BLOCKS_PER_YEAR/BYTES_PER_GIB,
            'regular_utilization':result['regular_utilization'][ix],
            'state_utilization':result['state_utilization'][ix],
            'hard_limit_fraction':result['mean_any_limit'][ix],
            'state_binding_fraction':result['mean_state_larger'][ix],
            'regular_binding_fraction':result['mean_regular_larger'][ix],
            'branch_tie_fraction':result['mean_tied'][ix],
            'mean_fee_wei':result['mean_mean_fee'][ix],
            'state_demand_cap_active_fraction':result['mean_cap_active'][ix],
            'target_deviation':result['mean_absolute_target_deviation'][ix,1],
            'execution_price_variation':result['log_return_sd'][ix,1],
        }
        first = len(paths)
        record_metrics(row,metrics,paths)
        for path in paths[first:]:
            path.update(state_demand_cap_label=r.state_demand_cap_label,
                state_demand_cap_multiple=r.state_demand_cap_multiple)
        records.append(row)
    outcomes,paths = pd.DataFrame(records),pd.DataFrame(paths)
    cached = central_three(pd.read_csv(DATA/'eip8372/normalized_paths.csv')).sort_values('replication')
    control = paths[paths.state_demand_cap_label.eq('unrestricted')].sort_values('replication')
    parity_metrics = sorted(set(metrics)&set(cached.columns))
    for metric in parity_metrics:
        np.testing.assert_allclose(control[metric],cached[metric],rtol=1e-13,atol=1e-12,err_msg=metric)
    # Reuse existing baseline/EIP-8368 cap runs; harmonize only named metrics.
    rename = dict(included_execution_metered='metered_execution_gas',
        shared_limit_hit_fraction='hard_limit_fraction',shared_fee_log_return_sd='execution_price_variation',
        equilibrium_binding_branch='equilibrium_branch')
    old = central_three(pd.read_csv(DATA/'shared_fee_state_tail.csv')).rename(columns=rename)
    old_paths = central_three(pd.read_csv(DATA/'shared_fee_state_tail_paths.csv')).rename(columns=rename)
    keys = ['benchmark','propagation_time_s','state_demand_cap_label','state_demand_cap_multiple']
    common = ['metered_execution_gas','annualized_state_growth_gib','hard_limit_fraction',
              'execution_price_variation','state_demand_cap_active_fraction']
    comparison = pd.concat([old[keys+common+['equilibrium_fee_wei','equilibrium_branch']],
        outcomes[keys+common+['equilibrium_fee_wei','equilibrium_branch']]],ignore_index=True)
    all_paths = pd.concat([old_paths[keys+['replication']+common],paths[keys+['replication']+common]],ignore_index=True)
    refs = central_three(pd.read_csv(DATA/'eip8372/fixed_7999_paths.csv'))
    paired = all_paths.merge(refs[['benchmark','configuration','propagation_time_s','replication',
        'metered_execution_gas','annualized_state_growth_gib']],on=['propagation_time_s','replication'],
        suffixes=('_one_dimensional','_7999'),validate='many_to_many')
    paired['execution_gain'] = paired.metered_execution_gas_7999-paired.metered_execution_gas_one_dimensional
    paired['state_growth_difference'] = paired.annualized_state_growth_gib_7999-paired.annualized_state_growth_gib_one_dimensional
    gain_rows = []
    group_keys = ['benchmark_one_dimensional','benchmark_7999','state_demand_cap_label','propagation_time_s']
    for key,g in paired.groupby(group_keys):
        assert len(g)==32 and g.replication.nunique()==32
        d = g.execution_gain.to_numpy()
        gain_rows.append(dict(zip(group_keys,key),mean_execution_gain=d.mean(),
            week_p05=np.quantile(d,.05),week_p95=np.quantile(d,.95),
            positive_path_fraction=np.mean(d>0),mean_state_growth_difference=g.state_growth_difference.mean()))
    gains = pd.DataFrame(gain_rows)
    assert len(comparison)==18 and len(paths)==192 and len(gains)==36 and len(paired)==1152
    for path,value in before.items():
        assert digest(ROOT/path)==value,f'Protected file changed: {path}'
    OUT.mkdir(parents=True,exist_ok=True)
    for name,frame in [('normalized_outcomes',outcomes),('normalized_paths',paths),
        ('three_second_comparison',comparison),('three_second_paths',all_paths),
        ('paired_gains',gains),('paired_gain_paths',paired)]:
        frame.to_csv(OUT/f'{name}.csv',index=False)
    manifest = dict(workload_sha256=workload_hash,fast_seed=20260814,slow_seed=20260815,
        n_paths=N_SEEDS,burn_in_blocks=BURN_IN,measured_blocks=MEASURE_BLOCKS,
        propagation_time_s=3.,elasticity_window_days=35,
        cap_definition='min(price-driven state expansion, cap) times unchanged state shock',
        caps=['1.5','2','3','4','5','unrestricted'],calibration_frozen=True,
        eip7999_references='Frozen unrestricted 35-day central selections, not recapped or reselected',
        uncapped_parity_metrics=parity_metrics,protected_sha256=before,
        implementation_sha256={str(p.relative_to(ROOT)):digest(p) for p in (
            Path(__file__),ROOT/'src/shared_fee/normalized_state_tail.py')},
        elapsed_seconds=time.monotonic()-started,numpy_version=np.__version__,pandas_version=pd.__version__)
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(outcomes[['state_demand_cap_label','equilibrium_fee_wei','metered_execution_gas',
        'annualized_state_growth_gib','state_binding_fraction','state_demand_cap_active_fraction']].to_string(index=False),flush=True)
    print(f'Complete; all {len(before)} protected files unchanged. {manifest["elapsed_seconds"]:.1f}s.',flush=True)


if __name__=='__main__':
    main()
