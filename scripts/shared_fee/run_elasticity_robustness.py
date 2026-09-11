"""Reselect over the existing shared-limit grid; preserve all earlier results.

Reuse central factorial paths and EIP-7999 sensitivity surfaces. Only the
three noncentral shared-fee limit sweeps require new simulation.
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
for directory in (ROOT / 'src', ROOT / 'scripts', ROOT / 'scripts/shared_fee'):
    sys.path.insert(0, str(directory))

from run_elasticity_comparison import record_metrics
from run_multiscale_design_surface import BURN_IN, MEASURE_BLOCKS, N_SEEDS, build_canonical_workload
from run_slot_time_parameter_sensitivity import specification_table
from shared_fee.equilibrium import SharedFeeAnchor, solve_shared_fee_equilibrium
from shared_fee.replay import SharedFeeConfig, run_shared_fee_batch
from shared_fee.optimization import BLOCKS_PER_YEAR, BYTES_PER_GIB

OUT = ROOT / 'data/shared_fee'
FAMILIES = ('proposal_faithful', 'fully_optimized')
KEYS = ['window_days', 'benchmark', 'propagation_time_s', 'shared_limit']
METRIC_MAP = {
    'metered_execution_gas': 'included_execution_metered',
    'data_or_floor_gas': 'included_data_metered',
    'state_gas': 'included_state_metered',
    'annualized_state_growth_gib': 'annualized_state_growth_gib',
    'hard_limit_fraction': 'shared_limit_hit_fraction',
    'target_deviation': 'shared_target_deviation',
    'execution_price_variation': 'shared_fee_log_return_sd',
    'regular_binding_fraction': 'regular_binding_fraction',
    'mean_shared_fee_wei': 'shared_fee_wei',
}


def metadata(source, spec):
    row = {key: source[key] for key in ('benchmark', 'propagation_time_s', 'shared_limit',
           'shared_target', 'floor_rate', 'cpsb', 'm_execution', 'm_data', 'm_state')}
    row.update({key: spec[key] for key in ('window_days', 'eps_execution', 'eps_data', 'eps_state')})
    row.update(configuration=f'G{source.shared_limit / 1e6:.1f}', available=True,
               n_replications=N_SEEDS, burn_in_blocks=BURN_IN, measured_blocks=MEASURE_BLOCKS)
    return row


def select_throughput(frame, keys):
    """Select highest mean; deterministic ties use the existing configuration order."""
    valid = frame[frame.available].sort_values(keys + ['configuration'])
    return valid.loc[valid.groupby(keys, sort=True).metered_execution_gas.idxmax()].reset_index(drop=True)


def paired_gains(selected, shared_paths, eip_paths):
    summaries, path_rows = [], []
    for _, row in selected[selected.benchmark.isin(['balanced', 'maximum'])].iterrows():
        result = {k: row[k] for k in ('window_days', 'propagation_time_s', 'benchmark', 'available', 'configuration')}
        if not row.available:
            result['unavailable_reason'] = 'No eligible configuration in the tested grid'
            summaries.append(result)
            continue
        ref = selected[(selected.window_days == row.window_days)
                       & (selected.propagation_time_s == row.propagation_time_s)
                       & selected.benchmark.eq('fully_optimized')].iloc[0]
        a = shared_paths[(shared_paths.window_days == row.window_days)
                         & (shared_paths.propagation_time_s == row.propagation_time_s)
                         & shared_paths.benchmark.eq('fully_optimized')
                         & (shared_paths.shared_limit == ref.shared_limit)]
        b = eip_paths[(eip_paths.window_days == row.window_days)
                      & (eip_paths.propagation_time_s == row.propagation_time_s)
                      & (eip_paths.benchmark == row.benchmark)]
        pair = a[['replication', 'metered_execution_gas']].merge(
            b[['replication', 'metered_execution_gas']], on='replication', how='outer',
            suffixes=('_shared', '_7999'), validate='one_to_one').sort_values('replication')
        if len(pair) != 32 or pair.isna().any().any() or set(pair.replication) != set(range(32)):
            raise ValueError('Gains require exactly 32 matched workload paths')
        delta = pair.metered_execution_gas_7999.to_numpy() - pair.metered_execution_gas_shared.to_numpy()
        rng = np.random.default_rng(20260909 + int(row.window_days * 100 + row.propagation_time_s * 10)
                                    + (1 if row.benchmark == 'maximum' else 0))
        means = rng.choice(delta, size=(10_000, 32), replace=True).mean(axis=1)
        result.update(mean_gain=delta.mean(), week_p05=np.quantile(delta, .05),
                      week_p95=np.quantile(delta, .95), mean_ci95_low=np.quantile(means, .025),
                      mean_ci95_high=np.quantile(means, .975), n_replications=32,
                      adjusted_configuration=ref.configuration)
        summaries.append(result)
        for replication, value in enumerate(delta):
            path_rows.append({**{k: row[k] for k in ('window_days', 'propagation_time_s', 'benchmark')},
                              'replication': replication, 'gain': value})
    return pd.DataFrame(summaries), pd.DataFrame(path_rows)


def fixed_central_candidates(selected, shared_surface):
    """Freeze each family's central candidate at every propagation allocation."""
    eip = pd.read_csv(ROOT / 'data/7999/slot_time_parameter_surface_one_at_a_time.csv')
    eip = eip[eip.lambda_bal.eq(0) & eip.rho_A.eq(1)]
    rows = []
    for _, central in selected[selected.window_days.eq(35) & selected.available].iterrows():
        for window in (21, 35, 60, 75):
            if central.benchmark in FAMILIES:
                source = shared_surface[(shared_surface.window_days == window)
                    & (shared_surface.benchmark == central.benchmark)
                    & (shared_surface.propagation_time_s == central.propagation_time_s)
                    & (shared_surface.shared_limit == central.shared_limit)]
                assert len(source) == 1
                row = source.iloc[0].to_dict()
            else:
                source = eip[(eip.window_days == window)
                    & (eip.propagation_time_s == central.propagation_time_s)
                    & (eip.execution_target == central.execution_target)
                    & (eip.data_target == central.data_target)
                    & (eip.execution_limit == central.execution_limit)
                    & (eip.data_limit == central.data_limit)]
                assert len(source) == 1
                source = source.iloc[0]
                row = {k: central[k] for k in ('benchmark', 'propagation_time_s', 'configuration',
                        'execution_target', 'data_target', 'execution_limit', 'data_limit')}
                row.update(window_days=window, available=True, metered_execution_gas=source.included_execution,
                    annualized_state_growth_gib=source.state_used / 1530 * BLOCKS_PER_YEAR / BYTES_PER_GIB,
                    hard_limit_fraction=source.any_limit_hit_fraction,
                    target_deviation=source.execution_mean_absolute_target_deviation,
                    execution_price_variation=source.execution_price_sd,
                    data_price_variation=source.data_price_sd, state_price_variation=source.state_price_sd,
                    execution_floor_bounded_fraction=source.execution_floor_bounded_fraction,
                    unconstrained_execution_fee_wei=source.unconstrained_equilibrium_execution_base_fee_wei)
            row['selection_basis'] = 'Frozen 35-day candidate at this propagation allocation'
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    start = time.monotonic()
    names = ['shared_fee_factorial_scenarios.csv', 'shared_fee_factorial_paths.csv',
             'shared_fee_elasticity_comparison.csv', 'shared_fee_elasticity_comparison_paths.csv',
             'shared_fee_factorial_manifest.csv', 'equilibrium_anchor_by_floor_rate.csv']
    protected = [OUT / n for n in names] + list((ROOT / 'data/7999').glob('*.csv'))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    specs = specification_table()
    specs = specs[specs.lambda_bal.eq(0) & specs.rho_A.eq(1)].reset_index(drop=True)
    source = pd.read_csv(OUT / names[0])
    source = source[source.floor_payload_feasible & source.benchmark.isin(FAMILIES)].reset_index(drop=True)
    assert len(source) == 177
    expected_hash = pd.read_csv(OUT / 'shared_fee_factorial_manifest.csv').iloc[0].workload_sha256
    surface_file = OUT / 'shared_fee_elasticity_surface.csv'
    paths_file = OUT / 'shared_fee_elasticity_surface_paths.csv'
    if surface_file.exists() and paths_file.exists():
        surface, paths = pd.read_csv(surface_file), pd.read_csv(paths_file)
        assert set(surface.workload_sha256) == {expected_hash}
        print('Reusing complete four-vector shared-limit sweep', flush=True)
    else:
        old_paths = pd.read_csv(OUT / 'shared_fee_factorial_paths.csv')
        rows, path_rows = [], []
        spec = specs[specs.window_days.eq(35)].iloc[0]
        for _, old in source.iterrows():
            row = metadata(old, spec)
            row.update(equilibrium_execution_fee_wei=old.equilibrium_fee_wei,
                       equilibrium_binding_branch=old.equilibrium_binding_branch)
            group = old_paths[(old_paths.benchmark == old.benchmark)
                & (old_paths.propagation_time_s == old.propagation_time_s)
                & (old_paths.shared_limit == old.shared_limit)].sort_values('replication')
            assert list(group.replication) == list(range(32))
            new_paths = []
            record_metrics(row, {k:group[v].to_numpy() for k,v in METRIC_MAP.items()}, new_paths)
            for p in new_paths:
                p['shared_limit'] = old.shared_limit
            rows.append(row); path_rows.extend(new_paths)
        print('Reusing 177 central cases; building unchanged canonical workload', flush=True)
        workload = build_canonical_workload().paths
        digest = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
        assert digest == expected_hash and workload.shape == (32, 57_600, 4)
        base = pd.read_csv(OUT / 'equilibrium_anchor_by_floor_rate.csv').iloc[0]
        demand = pd.read_csv(ROOT / 'data/7999/bal_decomposition_demand_parameters.csv').iloc[0]
        for propagation, group in source.groupby('propagation_time_s'):
            metadata_rows = []
            for _, old in group.iterrows():
                for _, spec in specs[~specs.window_days.eq(35)].iterrows():
                    row = metadata(old, spec)
                    anchor = SharedFeeAnchor(base.q_execution_per_block, base.q_data_per_block,
                        base.q_state_per_block, old.m_execution, old.m_data, old.m_state,
                        base.base_fee_ref_gwei, spec.eps_execution, spec.eps_data, spec.eps_state)
                    eq = solve_shared_fee_equilibrium(old.shared_target, anchor)
                    row.update(equilibrium_execution_fee_wei=eq.base_fee_wei,
                               equilibrium_binding_branch=eq.binding_branch)
                    metadata_rows.append(row)
            repeat = lambda key: np.repeat([r[key] for r in metadata_rows], 32)
            config = SharedFeeConfig(gas_target=repeat('shared_target'), gas_limit=repeat('shared_limit'),
                eps_execution=repeat('eps_execution'), eps_data=repeat('eps_data'), eps_state=repeat('eps_state'),
                m_execution=repeat('m_execution'), m_data=repeat('m_data'), m_state=repeat('m_state'),
                q_execution_0=base.q_execution_per_block, q_data_0=base.q_data_per_block,
                q_state_0=base.q_state_per_block, p0_gwei=base.base_fee_ref_gwei,
                w_execution=demand.w_execution_reference, w_state=demand.w_state_reference)
            print(f'{propagation:g}s: replaying {len(metadata_rows)} cases [{time.monotonic()-start:.1f}s]', flush=True)
            result = run_shared_fee_batch(config, workload, repeat('equilibrium_execution_fee_wei'), burn_in=BURN_IN)
            for index, row in enumerate(metadata_rows):
                ix=slice(index*32,(index+1)*32)
                metrics = {'metered_execution_gas':result['mean_included_execution'][ix],
                    'data_or_floor_gas':result['mean_included_data'][ix], 'state_gas':result['mean_included_state'][ix],
                    'annualized_state_growth_gib':result['mean_included_state'][ix]/row['cpsb']*BLOCKS_PER_YEAR/BYTES_PER_GIB,
                    'hard_limit_fraction':result['included_limit_fraction'][ix,1],
                    'target_deviation':result['mean_absolute_target_deviation'][ix,1],
                    'execution_price_variation':result['log_return_sd'][ix,1],
                    'regular_binding_fraction':result['regular_binding_fraction'][ix],
                    'mean_shared_fee_wei':result['mean_fee_wei'][ix,1]}
                new_paths=[]
                record_metrics(row,metrics,new_paths)
                for p in new_paths:
                    p['shared_limit']=row['shared_limit']
                rows.append(row);path_rows.extend(new_paths)
        surface=pd.DataFrame(rows).sort_values(KEYS)
        paths=pd.DataFrame(path_rows).sort_values(KEYS+['replication'])
        surface['workload_sha256']=expected_hash
        surface['state_binding_fraction']=1-surface.regular_binding_fraction
        surface.to_csv(surface_file,index=False)
        paths.to_csv(paths_file,index=False)
    assert len(surface)==708 and len(paths)==708*32
    assert not surface.duplicated(KEYS).any()
    # Constant multipliers leave all three effective-price log changes equal
    # to the shared-fee log change. Keep the cross-mechanism schema explicit.
    for resource in ('data', 'state'):
        surface[f'equilibrium_{resource}_fee_wei'] = surface.equilibrium_execution_fee_wei
        for suffix in ('', '_p05', '_p95'):
            surface[f'{resource}_price_variation{suffix}'] = surface[f'execution_price_variation{suffix}']
        paths[f'{resource}_price_variation'] = paths.execution_price_variation
    surface.to_csv(surface_file, index=False)
    paths.to_csv(paths_file, index=False)
    reference=pd.read_csv(OUT/'shared_fee_elasticity_comparison.csv')
    matched=surface.merge(reference[reference.benchmark.isin(FAMILIES)],on=KEYS,suffixes=('_new','_old'),validate='one_to_one')
    assert len(matched)==40
    for metric in ('metered_execution_gas','annualized_state_growth_gib','hard_limit_fraction','execution_price_variation'):
        np.testing.assert_allclose(matched[metric+'_new'],matched[metric+'_old'],rtol=1e-12)
    shared_selected=select_throughput(surface,['window_days','benchmark','propagation_time_s'])
    selected=pd.concat([shared_selected,reference[reference.benchmark.isin(['balanced','maximum'])]],ignore_index=True)
    selected=selected.sort_values(['window_days','benchmark','propagation_time_s'])
    best=select_throughput(selected,['window_days','benchmark'])
    missing=selected.groupby(['window_days','benchmark']).filter(lambda g:not g.available.any()).groupby(['window_days','benchmark']).head(1)
    best=pd.concat([best,missing],ignore_index=True).sort_values(['window_days','benchmark'])
    eip_paths=pd.read_csv(OUT/'shared_fee_elasticity_comparison_paths.csv')
    gains,gain_paths=paired_gains(selected,paths,eip_paths)
    fixed=fixed_central_candidates(selected,surface)
    selected.to_csv(OUT/'shared_fee_elasticity_reselected.csv',index=False)
    best.to_csv(OUT/'shared_fee_elasticity_best_designs.csv',index=False)
    gains.to_csv(OUT/'shared_fee_elasticity_gains.csv',index=False)
    gain_paths.to_csv(OUT/'shared_fee_elasticity_gain_paths.csv',index=False)
    fixed.to_csv(OUT/'shared_fee_elasticity_fixed_central.csv',index=False)
    for relative,digest in hashes.items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest,relative
    manifest={'workload_sha256':expected_hash,'source_hashes':hashes,'new_shared_cases':531,
              'central_shared_cases_reused':177,'shared_surface_rows':708,'shared_path_rows':len(paths),
              'paired_gain_rows':len(gains),'fixed_candidate_rows':len(fixed),
              'reference_40_cases_reproduced':'rtol=1e-12','selection_objective':'maximum mean included metered execution',
              'elapsed_seconds':time.monotonic()-start}
    (OUT/'shared_fee_elasticity_robustness_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(best[['window_days','benchmark','propagation_time_s','configuration','metered_execution_gas','annualized_state_growth_gib']].to_string(index=False),flush=True)
    print(gains.groupby('benchmark').mean_gain.agg(['min','max']).to_string(),flush=True)
    print(f'Completed in {time.monotonic()-start:.1f}s',flush=True)


if __name__=='__main__':
    main()
