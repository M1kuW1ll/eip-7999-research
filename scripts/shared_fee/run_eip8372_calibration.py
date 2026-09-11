"""Add a fixed 35-day EIP-8372-style calibration; preserve previous results."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / 'src', ROOT / 'scripts', ROOT / 'scripts/shared_fee'):
    sys.path.insert(0, str(directory))

from dynamics.batched_replay import bundle_cost_equivalent_start, run_batch
from run_elasticity_comparison import record_metrics
from run_multiscale_design_surface import BURN_IN, MEASURE_BLOCKS, N_SEEDS, build_canonical_workload
from run_slot_time_parameter_sensitivity import build_config, specification_table
from shared_fee.equilibrium import SharedFeeAnchor
from shared_fee.normalized_state import (NormalizedStateConfig, calibrate,
    solve_normalized_equilibrium, run_normalized_batch)
from shared_fee.optimization import BLOCKS_PER_YEAR, BYTES_PER_GIB

DATA = ROOT / 'data/shared_fee'
OUT = DATA / 'eip8372'
SPEC_URL = 'https://eips.ethereum.org/EIPS/eip-8372'


def inputs():
    specs = specification_table()
    specs = specs[specs.lambda_bal.eq(0) & specs.rho_A.eq(1)].reset_index(drop=True)
    base = pd.read_csv(DATA/'equilibrium_anchor_by_floor_rate.csv').iloc[0]
    source = pd.read_csv(DATA/'shared_fee_state_tail.csv')
    source = source[source.benchmark.eq('fully_optimized') & source.state_demand_cap_label.eq('unrestricted')]
    demand = pd.read_csv(ROOT/'data/7999/bal_decomposition_demand_parameters.csv').iloc[0]
    metering = pd.read_csv(ROOT/'data/7999/data_metering_runtime_bal_anchor.csv').iloc[0]
    return specs, base, source, demand, metering


def make_anchor(base, source, spec):
    return SharedFeeAnchor(base.q_execution_per_block, base.q_data_per_block,
        base.q_state_per_block, source.m_execution, source.m_data, source.m_state,
        base.base_fee_ref_gwei, spec.eps_execution, spec.eps_data, spec.eps_state)


def calibration_table(specs, base, source):
    central = specs[specs.window_days.eq(35)].iloc[0]
    rows = []
    for _, row in source.iterrows():
        mapping = row.m_state/row.cpsb
        values = calibrate(row.shared_limit, row.cpsb, mapping, make_anchor(base,row,central))
        assert max(abs(values['equilibrium_regular_utilization']-1),
                   abs(values['equilibrium_state_utilization']-1)) < 1e-5
        assert abs(values['byte_capacity_relative_error']) < 1e-5
        rows.append(dict(propagation_time_s=row.propagation_time_s, calibration_window_days=35,
            floor_rate=int(row.floor_rate), m_execution=row.m_execution, m_data=row.m_data,
            bytes_per_reference_state=mapping, **values))
    return pd.DataFrame(rows)


def normalized_metadata(calibration, specs, base):
    rows=[]
    for _, cal in calibration.iterrows():
        for _, spec in specs.iterrows():
            anchor=SharedFeeAnchor(base.q_execution_per_block,base.q_data_per_block,base.q_state_per_block,
                cal.m_execution,cal.m_data,cal.baseline_cpsb*cal.bytes_per_reference_state,
                base.base_fee_ref_gwei,spec.eps_execution,spec.eps_data,spec.eps_state)
            eq=solve_normalized_equilibrium(int(cal.shared_target),anchor,cal.m_state_raw,int(cal.state_gas_limit_scale))
            rows.append({**cal.to_dict(),**eq,'benchmark':'normalized_state',
                'configuration':f'G{cal.shared_limit/1e6:.1f}', 'window_days':int(spec.window_days),
                **{k:spec[k] for k in ('eps_execution','eps_data','eps_state')},
                'available':True, 'calibration_frozen':True})
    return pd.DataFrame(rows)


def normalized_config(rows, base, repeat=32):
    col=lambda name:np.repeat(rows[name].to_numpy(),repeat)
    return NormalizedStateConfig(gas_limit=col('shared_limit'),gas_target=col('shared_target'),
        cpsb=col('cpsb'),state_gas_limit_scale=col('state_gas_limit_scale'),
        eps_execution=col('eps_execution'),eps_data=col('eps_data'),eps_state=col('eps_state'),
        m_execution=col('m_execution'),m_data=col('m_data'),
        bytes_per_reference_state=float(rows.iloc[0].bytes_per_reference_state),
        q_execution_0=base.q_execution_per_block,q_data_0=base.q_data_per_block,
        q_state_0=base.q_state_per_block,p0_wei=base.base_fee_ref_wei)


def run_normalized(rows, base, workload):
    config=normalized_config(rows,base)
    result=run_normalized_batch(config,workload,np.repeat(rows.launch_fee_wei.to_numpy(),32),burn_in=BURN_IN)
    records,paths=[],[]
    for index,(_, row) in enumerate(rows.iterrows()):
        ix=slice(index*32,(index+1)*32)
        metadata=row.to_dict()
        metrics={
            'metered_execution_gas':result['mean_execution'][ix],
            'data_or_floor_gas':result['mean_data'][ix],
            'regular_gas':result['mean_regular'][ix],
            'normalized_state_gas':result['mean_state_normalized'][ix],
            'raw_state_gas':result['mean_state_raw'][ix],
            'state_bytes':result['mean_state_bytes'][ix],
            'annualized_state_growth_gib':result['mean_state_bytes'][ix]*BLOCKS_PER_YEAR/BYTES_PER_GIB,
            'regular_utilization':result['regular_utilization'][ix],
            'state_utilization':result['state_utilization'][ix],
            # A raw state cap can bind even if integer normalization yields
            # L_G-1. Count either actual cap, not just normalized max == L_G.
            'hard_limit_fraction':result['mean_any_limit'][ix],
            'normalized_controller_at_limit_fraction':result['included_limit_fraction'][ix,1],
            'regular_limit_fraction':result['mean_regular_limit'][ix],
            'raw_state_limit_fraction':result['mean_state_limit'][ix],
            'regular_binding_fraction':result['mean_regular_larger'][ix],
            'state_binding_fraction':result['mean_state_larger'][ix],
            'branch_tie_fraction':result['mean_tied'][ix],
            'excluded_execution':result['mean_excluded_execution'][ix],
            'execution_excluded_fraction':result['execution_excluded_fraction'][ix],
            'mean_fee_wei':result['mean_mean_fee'][ix],
            'base_fee_exposure_proxy_eth_per_block':result['mean_base_fee_exposure_eth'][ix],
            'target_deviation':result['mean_absolute_target_deviation'][ix,1],
            **{f'{resource}_price_variation':result['log_return_sd'][ix,1] for resource in ('execution','data','state')}}
        record_metrics(metadata,metrics,paths)
        records.append(metadata)
    return pd.DataFrame(records),pd.DataFrame(paths)


def fixed_7999_metadata(specs,demand,metering):
    selected=pd.read_csv(DATA/'shared_fee_elasticity_reselected.csv')
    selected=selected[selected.window_days.eq(35)&selected.benchmark.isin(['maximum','balanced'])]
    rows,combinations=[],[]
    for _, central in selected.iterrows():
        for spec_index,spec in specs.iterrows():
            row={k:central[k] for k in ('benchmark','configuration','propagation_time_s','execution_target',
                 'data_target','execution_limit','data_limit')}
            row.update(window_days=int(spec.window_days),selection_window_days=35,available=True,
                **{k:spec[k] for k in ('eps_execution','eps_data','eps_state')})
            fees,_=fixed_7999_equilibrium(row['execution_target'],row['data_target'],demand,metering,spec)
            row.update({f'equilibrium_{resource}_fee_wei':fee for resource,fee in zip(('execution','data','state'),fees)})
            rows.append(row)
            combinations.append((spec_index,row['execution_target'],row['data_target'],row['execution_limit'],row['data_limit']))
    return pd.DataFrame(rows),build_config(combinations,specs,demand,metering)


def fixed_7999_equilibrium(execution_target, data_target, demand, metering, spec):
    """Solve all fee-floor combinations at rho=1, including a data-fee floor."""
    p0=float(demand.base_fee_ref_gwei)*1e9
    mE,mS,mD=float(demand.m_execution),float(demand.m_state),float(metering.static_data_metering_multiplier)
    qE0,qS0=float(demand.q_execution_per_block),float(demand.q_state_per_block)
    wE,wS=float(demand.w_execution_reference),float(demand.w_state_reference)
    eE,eD,eS=float(spec.eps_execution),float(spec.eps_data),float(spec.eps_state)
    target_price_E=p0*(execution_target/(mE*qE0))**(-1/eE)
    target_price_S=p0*(75e6/(mS*qS0))**(-1/eS)
    def at_data_fee(bD):
        bE=max(1.,(target_price_E-wE*bD)/mE)
        bS=max(1.,(target_price_S-wS*bD)/mS)
        qE=qE0*((mE*bE+wE*bD)/p0)**(-eE)
        qS=qS0*((mS*bS+wS*bD)/p0)**(-eS)
        data=float(metering.static_data_gas_per_block)*(mD*bD/p0)**(-eD)+wE*qE+wS*qS
        return (bE,bD,bS),np.array([mE*qE,data,mS*qS])
    if at_data_fee(1.)[1][1]<=data_target:
        fees,used=at_data_fee(1.)
    else:
        root=brentq(lambda x:at_data_fee(np.exp(x))[1][1]-data_target,0,np.log(p0)+100,xtol=1e-12)
        fees,used=at_data_fee(float(np.exp(root)))
    targets=np.array([execution_target,data_target,75e6])
    assert np.all(used<=targets*(1+1e-10))
    np.testing.assert_allclose(used[np.array(fees)>1],targets[np.array(fees)>1],rtol=1e-10)
    return fees,used


def run_fixed_7999(rows, config, workload):
    result=run_batch(config,workload,bundle_cost_equivalent_start(config),burn_in=BURN_IN,bundle_consistent=True)
    records,paths=[],[]
    cached=pd.read_csv(DATA/'shared_fee_elasticity_fixed_central.csv')
    for index,(_,source) in enumerate(rows.iterrows()):
        row=source.to_dict();ix=slice(index*32,(index+1)*32)
        included=result['mean_used'][ix,0];excluded=result['mean_rationed'][ix,0]
        metrics=dict(metered_execution_gas=included,data_or_floor_gas=result['mean_used'][ix,1],
            normalized_state_gas=result['mean_used'][ix,2],state_bytes=result['mean_used'][ix,2]/1530,
            annualized_state_growth_gib=result['mean_used'][ix,2]/1530*BLOCKS_PER_YEAR/BYTES_PER_GIB,
            execution_utilization=included/row['execution_target'],
            data_utilization=result['mean_used'][ix,1]/row['data_target'],
            state_utilization=result['mean_used'][ix,2]/75e6,
            hard_limit_fraction=result['any_limit_hit_fraction'][ix],
            execution_limit_fraction=result['included_limit_fraction'][ix,0],data_limit_fraction=result['included_limit_fraction'][ix,1],
            excluded_execution=excluded,execution_excluded_fraction=excluded/np.maximum(included+excluded,1e-300),
            target_deviation=result['mean_absolute_target_deviation'][ix,0],
            execution_floor_bounded_fraction=result['floor_downward_pressure_fraction'][ix,0],
            **{f'{r}_price_variation':result['effective_price_log_return_sd'][ix,i] for i,r in enumerate(('execution','data','state'))})
        record_metrics(row,metrics,paths)
        reference=cached[cached.window_days.eq(row['window_days'])&cached.benchmark.eq(row['benchmark'])
            &cached.propagation_time_s.eq(row['propagation_time_s'])].iloc[0]
        for metric in ('metered_execution_gas','annualized_state_growth_gib','hard_limit_fraction','execution_price_variation'):
            np.testing.assert_allclose(row[metric],reference[metric],rtol=1e-12)
        records.append(row)
    return pd.DataFrame(records),pd.DataFrame(paths)


def paired_gains(normalized_paths,eip_paths):
    paired=eip_paths.merge(normalized_paths,on=['window_days','propagation_time_s','replication'],
        suffixes=('_7999','_normalized'),validate='many_to_one')
    paired['execution_gain']=paired.metered_execution_gas_7999-paired.metered_execution_gas_normalized
    paired['state_growth_difference']=paired.annualized_state_growth_gib_7999-paired.annualized_state_growth_gib_normalized
    summaries=[]
    for key,group in paired.groupby(['benchmark_7999','window_days','propagation_time_s']):
        assert len(group)==32 and group.replication.nunique()==32
        d=group.execution_gain.to_numpy()
        summaries.append(dict(benchmark=key[0],window_days=key[1],propagation_time_s=key[2],mean_execution_gain=d.mean(),
            week_p05=np.quantile(d,.05),week_p95=np.quantile(d,.95),
            mean_state_growth_difference=group.state_growth_difference.mean()))
    return pd.DataFrame(summaries),paired


def main():
    started=time.monotonic();OUT.mkdir(exist_ok=True)
    protected=list(DATA.glob('*.csv'))+list((ROOT/'data/7999').glob('*.csv'))+list((ROOT/'data/glamsterdam').glob('*.csv'))
    protected += [ROOT/p for p in ('src/shared_fee/replay.py','src/shared_fee/equilibrium.py','src/dynamics/batched_replay.py',
        'scripts/run_slot_time_parameter_sensitivity.py','src/dynamics/multiscale_shocks.py')]
    original={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    specs,base,source,demand,metering=inputs()
    cal=calibration_table(specs,base,source)
    rows=normalized_metadata(cal,specs,base)
    cal.to_csv(OUT/'calibration.csv',index=False)
    print(cal[['propagation_time_s','cpsb','effective_scale','equilibrium_fee_wei']].to_string(index=False),flush=True)
    workload=build_canonical_workload().paths
    digest=hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
    expected=pd.read_csv(DATA/'shared_fee_factorial_manifest.csv').iloc[0].workload_sha256
    assert digest==expected and workload.shape==(32,57_600,4)
    print('Replaying 20 fixed-calibration normalized-state cases on unchanged 32 paths',flush=True)
    normalized,npaths=run_normalized(rows,base,workload)
    central_rows=rows[rows.window_days.eq(35)]
    control=run_normalized_batch(normalized_config(central_rows,base,repeat=1),np.ones((1,10_000,4)),
        central_rows.launch_fee_wei.to_numpy(),burn_in=BURN_IN)
    pd.DataFrame(dict(propagation_time_s=central_rows.propagation_time_s.to_numpy(),
        regular_utilization=control['regular_utilization'],state_utilization=control['state_utilization'],
        final_fee_wei=control['final_base_fee_wei'])).to_csv(OUT/'unshocked_control.csv',index=False)
    print(f'Normalized replay complete [{time.monotonic()-started:.1f}s]; replaying 40 frozen EIP-7999 cases',flush=True)
    erows,config=fixed_7999_metadata(specs,demand,metering)
    eip,epaths=run_fixed_7999(erows,config,workload)
    gains,gainpaths=paired_gains(npaths,epaths)
    for name,frame in [('normalized_outcomes',normalized),('normalized_paths',npaths),('fixed_7999_outcomes',eip),
                        ('fixed_7999_paths',epaths),('paired_gains',gains),('paired_gain_paths',gainpaths)]:
        frame.to_csv(OUT/(name+'.csv'),index=False)
    for name,d in original.items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==d,name
    manifest=dict(specification_url=SPEC_URL,specification_checked='2026-09-09',status='draft; constants unspecified',
        calibration_window_days=35,elasticity_windows=[21,35,60,75],lambda_bal=0,rho_A=1,
        workload_sha256=digest,shape=list(workload.shape),burn_in=BURN_IN,measured_blocks=MEASURE_BLOCKS,
        source_hashes=original,normalized_cases=len(normalized),fixed_7999_cases=len(eip),
        implementation_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ('src/shared_fee/normalized_state.py','scripts/shared_fee/run_eip8372_calibration.py')},
        eip7999_reproduction_tolerance=1e-12,integer_operations='CPSB integer; scale=CPSB*100//baseline; raw limit=L*scale//100; normalized=raw*100//scale',
        aggregate_rounding='Uniform aggregate inclusion, then floor regular and raw-state counters to integer gas',
        baseline='Preserve existing ~120 GiB/year byte target; floor its analytical CPSB to a positive integer',
        calibrated_cpsb_rounding='Nearest integer, half up',time_seconds=time.monotonic()-started)
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(normalized[normalized.window_days.eq(35)][['propagation_time_s','metered_execution_gas','annualized_state_growth_gib',
          'regular_utilization','state_utilization','state_binding_fraction','hard_limit_fraction']].to_string(index=False),flush=True)
    print(gains.groupby(['window_days','benchmark']).mean_execution_gain.agg(['min','max']).to_string(),flush=True)
    print(f'Completed in {time.monotonic()-started:.1f}s; previous outputs unchanged',flush=True)


if __name__=='__main__':
    main()
