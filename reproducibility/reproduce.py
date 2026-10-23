"""Paper-specific, credential-free validation and simulation replay.

Outputs go to reproducibility/results; reference tables are never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
for folder in (ROOT / 'src', ROOT / 'scripts', ROOT / 'scripts/shared_fee'):
    sys.path.insert(0, str(folder))

import numpy as np
import pandas as pd

TAUS = [3., 3.5, 4., 4.5, 5.]
DATA_TARGETS = np.array([22.5, 36, 45, 52.5, 60, 67.5, 80, 90, 100]) * 1e6
WORKLOAD_HASH = '2af918e3989c78a13c68bdd7c8f8e01df0e705a35ff9c0a0c81b115b41ecbec1'
OUT = HERE / 'results'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    """Restore only missing bundled files; reject changed inputs, never replace them."""
    manifest = json.loads((HERE / 'inputs_manifest.json').read_text())
    for archive_name, archive_hash in manifest['archives'].items():
        chunks = []
        for name in manifest['archive_parts'][archive_name]:
            chunk = (HERE / name).read_bytes()
            if hashlib.sha256(chunk).hexdigest() != manifest['part_sha256'][name]:
                raise ValueError(f'Input part checksum mismatch: {name}')
            chunks.append(chunk)
        archive = b''.join(chunks)
        if hashlib.sha256(archive).hexdigest() != archive_hash:
            raise ValueError(f'Archive checksum mismatch: {archive_name}')
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            for member in tar:
                rel = Path(member.name)
                if (not member.isfile() or rel.is_absolute() or '..' in rel.parts
                        or not rel.parts or rel.parts[0] != 'data'
                        or member.name not in manifest['files']):
                    raise ValueError(f'Unexpected archive member: {member.name}')
                target = ROOT / rel
                if not target.resolve().is_relative_to(ROOT.resolve()):
                    raise ValueError(f'Unsafe destination: {member.name}')
                if not target.exists():
                    payload = tar.extractfile(member).read()
                    if hashlib.sha256(payload).hexdigest() != manifest['files'][member.name]:
                        raise ValueError(f'Input checksum mismatch: {member.name}')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
    for name, expected in manifest['files'].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f'Input differs from frozen paper input: {name}')
    print(f'Checked {len(manifest["files"])} frozen inputs.', flush=True)


def paper_grid(frame):
    return frame.loc[
        frame.propagation_time_s.isin(TAUS)
        & frame.execution_target.isin(np.arange(150, 301, 25) * 1e6)
        & frame.data_target.isin(DATA_TARGETS)
        & (frame.execution_target < frame.execution_limit)
        & (frame.data_target < frame.data_limit)
    ].copy()


def select(frame, ceiling, *, conservative):
    """Only congestion and interior-equilibrium conditions enter selection."""
    keys = (['window_days'] if 'window_days' in frame else []) + ['propagation_time_s']
    candidates = frame
    if conservative:
        candidates = frame.loc[
            (frame.any_near_limit_fraction <= ceiling)
            & (frame.unconstrained_equilibrium_execution_base_fee_wei > 1 + 1e-6)
        ]
    return candidates.loc[candidates.groupby(keys).included_execution.idxmax()].sort_values(keys)


def load_tables():
    from summarize_slot_time_candidates import add_central_equilibrium_fees
    surface = paper_grid(pd.read_csv(ROOT / 'data/7999/slot_time_scenarios.csv'))
    surface = add_central_equilibrium_fees(surface)
    assert len(surface) == 301
    assert not surface.duplicated(['propagation_time_s', 'execution_target', 'data_target']).any()
    ceiling = pd.read_csv(ROOT / 'data/7999/historical_fee_market_benchmark.csv').iloc[0].near_limit_fraction
    chosen = {}
    for name in ('conservative', 'maximum'):
        frame = select(surface, ceiling, conservative=name == 'conservative')
        saved = pd.read_csv(HERE / f'reference/central_{name}.csv').sort_values('propagation_time_s')
        for col in ['execution_target', 'data_target', 'included_execution', 'any_near_limit_fraction']:
            np.testing.assert_allclose(frame[col], saved[col], rtol=1e-11)
        chosen[name] = frame
        frame.to_csv(OUT / f'{name}.csv', index=False)
    half = pd.read_csv(ROOT / 'data/shared_fee/eip8372_excess_update_half/outcomes.csv').query("controller == 'integer'").sort_values('propagation_time_s')
    four = pd.read_csv(ROOT / 'data/shared_fee/eip8372_excess_update/outcomes.csv')
    integer = four.query("controller == 'integer'").sort_values('propagation_time_s')
    fake = four.query("controller == 'excess_matched'").sort_values('propagation_time_s')
    table = pd.DataFrame({'propagation_s': TAUS})
    for name, frame in [('normalized_half', half), ('normalized_four_fifths', integer), ('fake_exponential', fake)]:
        table[name + '_execution_M'] = frame.metered_execution_gas.to_numpy() / 1e6
        table[name + '_regular_target_utilization_pct'] = frame.regular_utilization.to_numpy() * 100
    for name, frame in chosen.items():
        table[name + '_execution_M'] = frame.included_execution.to_numpy() / 1e6
        table[name + '_execution_target_utilization_pct'] = (100 * frame.included_execution / frame.execution_target).to_numpy()
        table[name + '_near_limit_pct'] = frame.any_near_limit_fraction.to_numpy() * 100
    table.to_csv(OUT / 'comparison.csv', index=False)
    sensitivity = pd.read_csv(ROOT / 'data/7999/slot_time_parameter_surface_one_at_a_time.csv')
    main = paper_grid(sensitivity.query('lambda_bal == 0 and rho_A == 1 and window_days in [21, 35]'))
    lower = pd.read_csv(HERE / 'reference/lower_target_surface.csv').query('propagation_time_s != 3')
    physical = pd.read_csv(HERE / 'reference/lower_target_3s_physical.csv')
    combined = pd.concat([main, lower, physical], ignore_index=True)
    strict = select(combined, ceiling, conservative=True)
    saved = pd.read_csv(HERE / 'reference/elasticity_conservative.csv').sort_values(['window_days', 'propagation_time_s'])
    assert len(strict) == 20
    np.testing.assert_allclose(strict[['execution_target', 'data_target', 'included_execution']], saved[['execution_target', 'data_target', 'included_execution']], rtol=1e-11)
    strict.to_csv(OUT / 'elasticity_conservative.csv', index=False)
    normalized = pd.read_csv(ROOT / 'data/shared_fee/eip8372/normalized_outcomes.csv')
    gains = strict.merge(normalized[['window_days', 'propagation_time_s', 'metered_execution_gas']], on=['window_days', 'propagation_time_s'], validate='one_to_one')
    gains['gain_M'] = (gains.included_execution - gains.metered_execution_gas) / 1e6
    ranges = gains.groupby('window_days').gain_M.agg(['min', 'max'])
    np.testing.assert_allclose(ranges, pd.read_csv(HERE / 'reference/elasticity_gain_ranges.csv', index_col=0), rtol=1e-11)
    ranges.to_csv(OUT / 'elasticity_gain_ranges.csv')
    print(table.round(4).to_string(index=False), flush=True)
    print('Conservative selection: exact historical congestion ceiling; no target-deviation filter; no D77.', flush=True)
    return surface, chosen, strict, half, integer, fake


def replay_multi(rows, workload, label):
    from run_slot_time_parameter_sensitivity import specification_table, build_config
    from dynamics.batched_replay import run_batch, bundle_cost_equivalent_start
    specs = specification_table().query('lambda_bal == 0 and rho_A == 1').reset_index(drop=True)
    demand = pd.read_csv(ROOT / 'data/7999/bal_decomposition_demand_parameters.csv').iloc[0]
    metering = pd.read_csv(ROOT / 'data/7999/data_metering_runtime_bal_anchor.csv').iloc[0]
    specs_by_window = {int(row.window_days): i for i, row in specs.iterrows()}
    combos = [(specs_by_window[int(getattr(r, 'window_days', 35))], r.execution_target, r.data_target, r.execution_limit, r.data_limit) for r in rows.itertuples()]
    config = build_config(combos, specs, demand, metering)
    print(f'Replaying {label}: {len(rows)} configurations × 32 paths.', flush=True)
    result = run_batch(config, workload, bundle_cost_equivalent_start(config), burn_in=7200, bundle_consistent=True)
    execution_paths = result['mean_used'][:, 0].reshape(len(rows), 32)
    metrics = {
        'included_execution': execution_paths.mean(axis=1),
        'any_near_limit_fraction': result['any_near_limit_fraction'].reshape(len(rows), 32).mean(axis=1),
        'data_used': result['mean_used'][:, 1].reshape(len(rows), 32).mean(axis=1),
        'state_used': result['mean_used'][:, 2].reshape(len(rows), 32).mean(axis=1),
        'execution_floor_bounded_fraction': result['floor_downward_pressure_fraction'][:, 0].reshape(len(rows), 32).mean(axis=1),
        'data_limit_hit_fraction': result['included_limit_fraction'][:, 1].reshape(len(rows), 32).mean(axis=1),
    }
    for name, values in metrics.items():
        # Lower-target historical sweeps saved fewer metrics. Check every saved
        # value, and retain newly computed metrics without treating missing
        # reference values as successful comparisons.
        recorded = rows[name].to_numpy() if name in rows else np.full(len(rows), np.nan)
        available = np.isfinite(recorded)
        np.testing.assert_allclose(values[available], recorded[available], rtol=1e-10, atol=1e-8, err_msg=f'{label}: {name}')
        if not available.all():
            print(f'{label}: {name} checked for {available.sum()}/{len(rows)} configurations; other reference values were not recorded.', flush=True)
    if 'state_growth_gib' in rows:
        available = np.isfinite(rows.state_growth_gib.to_numpy())
        np.testing.assert_allclose((metrics['state_used'] / 1530 * 2628000 / 2**30)[available], rows.state_growth_gib.to_numpy()[available], rtol=1e-10, atol=1e-8)
    fresh = rows.copy()
    for name, values in metrics.items(): fresh[name] = values
    fresh.to_csv(OUT / f'replayed_{label}.csv', index=False)
    print(f'{label}: all recorded comparison metrics reproduced.', flush=True)
    return execution_paths


def replay_shared(workload, half, integer, fake):
    from run_slot_time_parameter_sensitivity import specification_table
    from run_elasticity_comparison import shared_rows
    from run_eip8372_calibration import run_normalized
    from run_eip8372_excess_update import replay
    specs = specification_table().query('lambda_bal == 0 and rho_A == 1').reset_index(drop=True)
    demand = pd.read_csv(ROOT / 'data/7999/bal_decomposition_demand_parameters.csv').iloc[0]
    print('Replaying baseline and growth-matched benchmarks under all four elasticities.', flush=True)
    fresh, paths = shared_rows(specs, workload, demand)
    fresh = pd.DataFrame(fresh)
    keys = ['benchmark', 'window_days', 'propagation_time_s']
    old = pd.read_csv(ROOT / 'data/shared_fee/shared_fee_elasticity_comparison.csv')
    old = old[old.benchmark.isin(['proposal_faithful', 'fully_optimized'])]
    metrics = ['metered_execution_gas', 'data_or_floor_gas', 'state_gas', 'near_limit_fraction', 'annualized_state_growth_gib']
    np.testing.assert_allclose(fresh.set_index(keys).sort_index()[metrics], old.set_index(keys).sort_index()[metrics], rtol=1e-10, atol=1e-8)
    fresh.to_csv(OUT / 'replayed_shared.csv', index=False)
    base = pd.read_csv(ROOT / 'data/shared_fee/equilibrium_anchor_by_floor_rate.csv').iloc[0]
    refs = pd.read_csv(ROOT / 'data/shared_fee/eip8372/normalized_outcomes.csv')
    print('Replaying normalized benchmark under all four elasticities.', flush=True)
    normalized, _ = run_normalized(refs, base, workload)
    metrics = ['metered_execution_gas', 'regular_utilization', 'state_utilization', 'annualized_state_growth_gib']
    np.testing.assert_allclose(normalized[metrics], refs[metrics], rtol=1e-10, atol=1e-8)
    normalized.to_csv(OUT / 'replayed_normalized_elasticities.csv', index=False)
    pathsets = {}
    for label, rows, controller in [('half', half, 'integer'), ('four_fifths', integer, 'integer'), ('fake', fake, 'excess_matched')]:
        fresh, paths = replay(rows, base, workload, controller, label)
        metrics = ['metered_execution_gas', 'regular_utilization', 'state_utilization', 'annualized_state_growth_gib', 'any_near_limit_fraction']
        np.testing.assert_allclose(fresh[metrics], rows[metrics], rtol=1e-10, atol=1e-8)
        fresh.to_csv(OUT / f'replayed_{label}.csv', index=False)
        pathsets[label] = paths.metered_execution_gas.to_numpy().reshape(5, 32)
    return pathsets


def replay_appendix(workload):
    """Check the remaining elasticity controls and the exact-90M experiments."""
    from run_eip8372_excess_update import replay
    base = pd.read_csv(ROOT / 'data/shared_fee/equilibrium_anchor_by_floor_rate.csv').iloc[0]
    frozen = pd.read_csv(HERE / 'reference/normalized_frozen_outcomes.csv')
    metrics = ['metered_execution_gas', 'regular_utilization', 'state_utilization', 'annualized_state_growth_gib', 'any_near_limit_fraction']
    for controller in ['integer', 'excess_matched']:
        rows = frozen[frozen.controller.eq(controller) & ~frozen.window_days.eq(35)]
        fresh, _ = replay(rows, base, workload, controller, f'appendix_{controller}')
        np.testing.assert_allclose(fresh[metrics], rows[metrics], rtol=1e-10, atol=1e-8)
        fresh.to_csv(OUT / f'appendix_{controller}.csv', index=False)
    maximum = pd.read_csv(HERE / 'reference/elasticity_maximum.csv')
    surface = paper_grid(pd.read_csv(ROOT / 'data/7999/slot_time_parameter_surface_one_at_a_time.csv').query('lambda_bal == 0 and rho_A == 1'))
    selected = select(surface, 0., conservative=False)
    keys = ['window_days', 'propagation_time_s']
    np.testing.assert_allclose(selected.set_index(keys).sort_index()[['execution_target', 'data_target', 'included_execution']], maximum.set_index(keys).sort_index()[['execution_target', 'data_target', 'included_execution']], rtol=1e-11)
    replay_multi(selected.query('window_days != 35'), workload, 'elasticity_maximum')
    for name in ['fixed_600m_90m', 'e275_exact90_sensitivity']:
        rows = pd.read_csv(HERE / f'reference/{name}.csv')
        replay_multi(rows, workload, name)
    gains = maximum.merge(frozen, on=keys, suffixes=('_multi', '_normalized'))
    gains['gain_M'] = (gains.included_execution - gains.metered_execution_gas) / 1e6
    gains.groupby(['window_days', 'controller']).gain_M.agg(['min', 'max']).to_csv(OUT / 'elasticity_maximum_gain_ranges.csv')


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', action='store_true', help='Rebuild demand paths and rerun selected configurations and elasticity checks.')
    parser.add_argument('--full-grid', action='store_true', help='Also rerun all 301 central candidate configurations.')
    parser.add_argument('--prepare-only', action='store_true', help='Restore bundled inputs and verify their checksums.')
    args = parser.parse_args()
    prepare()
    if args.prepare_only: return
    OUT.mkdir(exist_ok=True)
    surface, selected, strict, half, integer, fake = load_tables()
    report = {'selection_checked': True, 'near_limit_tolerance_multiplier': 1., 'target_deviation_filter': False, 'central_candidate_count': len(surface), 'replay_completed': False}
    if args.replay or args.full_grid:
        from run_multiscale_design_surface import build_canonical_workload
        workload = build_canonical_workload().paths
        h = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
        if h != WORKLOAD_HASH or workload.shape != (32, 57600, 4):
            raise AssertionError('Demand paths differ from the paper workload.')
        print(f'Paper demand paths reproduced: {h}', flush=True)
        shared = replay_shared(workload, half, integer, fake)
        multi = {name: replay_multi(rows, workload, name) for name, rows in selected.items()}
        replay_multi(strict.query('window_days != 35'), workload, 'elasticity_conservative')
        paired = []
        for name, m, s in [('conservative', 'conservative', 'half'), ('maximum', 'maximum', 'four_fifths'), ('update_diagnostic', 'maximum', 'fake')]:
            for j, tau in enumerate(TAUS):
                for i, gain in enumerate(multi[m][j] - shared[s][j]):
                    paired.append(dict(comparison=name, propagation_time_s=tau, path_id=i, execution_gain_gas=gain))
        paired = pd.DataFrame(paired)
        keys = ['comparison', 'propagation_time_s', 'path_id']
        old = pd.read_csv(HERE / 'reference/paired_paths.csv')
        np.testing.assert_allclose(paired.set_index(keys).sort_index().execution_gain_gas, old.set_index(keys).sort_index().execution_gain_gas, rtol=1e-9, atol=1e-6)
        paired.to_csv(OUT / 'paired_paths.csv', index=False)
        replay_appendix(workload)
        if args.full_grid:
            for tau in TAUS:
                replay_multi(surface[surface.propagation_time_s.eq(tau)], workload, f'grid_{tau:g}s')
        report.update(replay_completed=True, workload_sha256=h, full_central_grid_replayed=args.full_grid, paired_path_count=len(paired))
    report['elapsed_seconds'] = time.monotonic() - started
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
