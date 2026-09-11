"""Preservation, paired-path provenance, frozen constants, and reported metrics."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'data/shared_fee/eip8372'


def test_preserved_data_kernels_and_shock_hash():
    manifest=json.loads((DATA/'manifest.json').read_text())
    assert manifest['shape']==[32,57600,4]
    assert manifest['burn_in']==7200 and manifest['measured_blocks']==50400
    reference=pd.read_csv(ROOT/'data/shared_fee/shared_fee_factorial_manifest.csv').iloc[0]
    assert manifest['workload_sha256']==reference.workload_sha256
    for path,digest in {**manifest['source_hashes'],**manifest['implementation_hashes']}.items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest,path


def test_constants_and_central_target_pairs_are_frozen():
    n=pd.read_csv(DATA/'normalized_outcomes.csv')
    e=pd.read_csv(DATA/'fixed_7999_outcomes.csv')
    assert len(n)==20 and len(e)==40
    for _,g in n.groupby('propagation_time_s'):
        assert set(g.window_days)=={21,35,60,75}
        for col in ('cpsb','state_gas_limit_scale','shared_limit','shared_target','m_data','floor_rate'):
            assert g[col].nunique()==1
    for _,g in e.groupby(['propagation_time_s','benchmark']):
        assert set(g.window_days)=={21,35,60,75}
        for col in ('execution_target','data_target','execution_limit','data_limit','configuration'):
            assert g[col].nunique()==1
    for window,g in n.groupby('window_days'):
        other=e[e.window_days.eq(window)]
        for col in ('eps_execution','eps_data','eps_state'):
            np.testing.assert_allclose(g[col],other.iloc[0][col],rtol=1e-12)


def test_path_means_units_and_limit_accounting():
    keys=['propagation_time_s','window_days','benchmark']
    for name in ('normalized','fixed_7999'):
        frame=pd.read_csv(DATA/f'{name}_outcomes.csv').set_index(keys).sort_index()
        paths=pd.read_csv(DATA/f'{name}_paths.csv')
        assert paths.groupby(keys).replication.nunique().eq(32).all()
        assert not paths.duplicated(keys+['replication']).any()
        for metric in ('metered_execution_gas','annualized_state_growth_gib','hard_limit_fraction','execution_price_variation'):
            np.testing.assert_allclose(paths.groupby(keys)[metric].mean().sort_index(),frame[metric],rtol=1e-12)
    n=pd.read_csv(DATA/'normalized_outcomes.csv')
    np.testing.assert_allclose(n.annualized_state_growth_gib,n.raw_state_gas/n.cpsb*2628000/1024**3)
    np.testing.assert_allclose(n.regular_binding_fraction+n.state_binding_fraction+n.branch_tie_fraction,1,atol=1e-12)
    for col in ('execution','data','state'):
        np.testing.assert_array_equal(n[f'{col}_price_variation'],n.execution_price_variation)
    assert (n.hard_limit_fraction+1e-12>=n.raw_state_limit_fraction).all()
    assert (n.hard_limit_fraction+1e-12>=n.regular_limit_fraction).all()
    assert (n.hard_limit_fraction<=n.raw_state_limit_fraction+n.regular_limit_fraction+1e-12).all()
    control=pd.read_csv(DATA/'unshocked_control.csv')
    assert control.regular_utilization.between(.995,1).all()
    assert control.state_utilization.between(.995,1).all()


def test_gains_are_replication_paired_and_all_means_positive():
    gains=pd.read_csv(DATA/'paired_gains.csv')
    paths=pd.read_csv(DATA/'paired_gain_paths.csv')
    assert len(gains)==40 and len(paths)==1280
    np.testing.assert_allclose(paths.execution_gain,paths.metered_execution_gas_7999-paths.metered_execution_gas_normalized)
    for key,g in paths.groupby(['benchmark_7999','window_days','propagation_time_s']):
        r=gains[(gains.benchmark==key[0])&(gains.window_days==key[1])&(gains.propagation_time_s==key[2])].iloc[0]
        np.testing.assert_allclose([r.mean_execution_gain,r.week_p05,r.week_p95],
            [g.execution_gain.mean(),g.execution_gain.quantile(.05),g.execution_gain.quantile(.95)])
    assert gains.mean_execution_gain.gt(0).all()
    assert gains[(gains.benchmark=='balanced')&(gains.window_days==35)&(gains.propagation_time_s==3)].week_p05.iloc[0]<0


def test_pulse_paths_recovery_and_price_units():
    sys.path.insert(0,str(ROOT/'scripts/shared_fee'))
    module=runpy.run_path(str(ROOT/'scripts/shared_fee/run_eip8372_stresses.py'))
    recovery=module['recovery_time']
    signal=np.zeros((1000,3));signal[:90,0]=.3
    assert recovery(signal)==90
    assert np.isnan(recovery(np.ones((1000,3))))
    assert recovery(np.zeros((1000,3)))==0
    paths=pd.read_csv(DATA/'stress_paths.csv')
    assert len(paths)==9*32
    assert paths.groupby(['benchmark','resource']).replication.nunique().eq(32).all()
    n=paths[paths.benchmark.eq('normalized_state')]
    for resource in ('data','state'):
        np.testing.assert_array_equal(n.peak_execution_price_multiple,n[f'peak_{resource}_price_multiple'])
    manifest=json.loads((DATA/'stress_manifest.json').read_text())
    assert manifest['event_blocks']==600 and manifest['half_life_blocks']==120
    assert manifest['workload_sha256']==json.loads((DATA/'manifest.json').read_text())['workload_sha256']


def test_report_central_rows_and_figures_match_results():
    report=(ROOT/'markdowns/eip8279_floor_calibration_report.md').read_text()
    n=pd.read_csv(DATA/'normalized_outcomes.csv')
    for _,r in n[n.window_days.eq(35)].iterrows():
        line=(f'| {r.propagation_time_s:.1f}s | {r.metered_execution_gas/1e6:.1f}M | '
              f'{r.regular_utilization:.1%} | {r.state_utilization:.1%} | '
              f'{r.annualized_state_growth_gib:.1f} | {r.state_binding_fraction:.2%} | {r.hard_limit_fraction:.2%} | {r.execution_price_variation:.4f} |')
        assert line in report
    for name in ('central','frozen_elasticities','resource_pulses'):
        assert (ROOT/f'plots/shared_fee_eip8372_{name}.png').stat().st_size>1000
        assert (ROOT/f'plots/shared_fee_eip8372_{name}.pdf').stat().st_size>1000


def test_report_orders_benchmarks_before_comparison_and_caps_as_sensitivity():
    report=(ROOT/'markdowns/eip8279_floor_calibration_report.md').read_text()
    headings=['## Baseline configuration','## Floor-adjusted + EIP-8368',
              '## Floor-adjusted + EIP-8372','## Comparison with EIP-7999',
              '## Sensitivity to demand assumptions','### Caveat: state demand may saturate',
              '## Limitations and conclusion']
    positions=[report.index(h) for h in headings]
    assert positions==sorted(positions)
    comparison=report.split('## Comparison with EIP-7999')[1].split('## Sensitivity')[0]
    assert 'execution / data / state' in comparison
    assert '**raw** state counter' in comparison
    assert len([line for line in comparison.splitlines() if line.startswith('| ')])==7


def test_report_comparison_fee_columns_match_cached_means():
    report=(ROOT/'markdowns/eip8279_floor_calibration_report.md').read_text()
    report=report.split('## Comparison with EIP-7999')[1].split('## Sensitivity')[0]
    old=pd.read_csv(ROOT/'data/shared_fee/shared_fee_optimized_comparison.csv')
    selections=[('Proposal-faithful shared fee',4.,'Baseline'),
                ('Floor- and state-growth-adjusted shared fee',3.5,'Floor-adjusted + EIP-8368'),
                ('EIP-7999 balanced (historically anchored)',4.,'EIP-7999: historically anchored'),
                ('EIP-7999 maximum throughput',4.5,'EIP-7999: maximum-throughput')]
    for family,tau,label in selections:
        row=old[old.design_family.eq(family)&old.propagation_time_s.eq(tau)].iloc[0]
        line=next(line for line in report.splitlines() if line.startswith(f'| {label} |'))
        assert line.endswith(f'| {row.base_fee_exposure_proxy_eth_per_block:.7f} |')
        if label.startswith('EIP-7999'):
            fee=(f'{row.equilibrium_execution_fee_wei:.2f} / '
                 f'{row.equilibrium_data_or_regular_fee_wei:.2f} / {row.equilibrium_state_fee_wei:,.0f}')
        else:
            fee=f'{row.equilibrium_execution_fee_wei:,.0f}'
        assert f'| {fee} |' in line
    n=pd.read_csv(DATA/'normalized_outcomes.csv')
    r=n[n.window_days.eq(35)&n.propagation_time_s.eq(3.5)].iloc[0]
    line=next(line for line in report.splitlines() if line.startswith('| Floor-adjusted + EIP-8372 | 3.5s,'))
    assert f'| {r.equilibrium_fee_wei:.2f} |' in line
    assert line.endswith(f'| {r.base_fee_exposure_proxy_eth_per_block:.7f} |')
    paths=pd.read_csv(DATA/'normalized_paths.csv')
    keys=['propagation_time_s','window_days']
    np.testing.assert_allclose(paths.groupby(keys).base_fee_exposure_proxy_eth_per_block.mean().sort_index(),
        n.set_index(keys).base_fee_exposure_proxy_eth_per_block.sort_index(),rtol=1e-12)
