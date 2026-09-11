"""Read-only-kernel diagnostic of four existing frozen-calibration settings.

Reconstruct the same cached workload and retain block paths; do not refit shocks,
change controller arithmetic, or overwrite any original simulation result.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from run_eip8372_calibration import (
    BURN_IN, DATA, OUT, build_canonical_workload, normalized_config,
    run_normalized_batch,
)


def path_diagnostics(rows, shocks, result):
    n_paths = len(shocks)
    # Stored fees are post-update. The preceding entry prices this block.
    fee = result['fee_paths'][:, BURN_IN-1:-1]
    next_fee = result['fee_paths'][:, BURN_IN:]
    used = result['used_paths'][:, BURN_IN:]
    records = []
    for setting_index, (_, row) in enumerate(rows.iterrows()):
        for path in range(n_paths):
            index = setting_index*n_paths+path
            regular, state = used[index, :, 1], used[index, :, 2]
            below = np.maximum(regular, state) < row.shared_target
            unchanged = next_fee[index] == fee[index]
            ratio = fee[index]/row.state_root_wei
            state_shock = shocks[path, BURN_IN:, 2]
            response = ratio**(-row.eps_state)
            # The continuous state root makes normalized unshocked usage T.
            # Integer normalization is retained in the included path above.
            offered_ratio = state_shock*response
            included_ratio = state/row.shared_target
            records.append(dict(
                window_days=int(row.window_days), propagation_time_s=row.propagation_time_s,
                path=path, state_root_wei=row.state_root_wei,
                state_byte_clearing_price_wei=row.cpsb*row.state_root_wei,
                state_utilization=included_ratio.mean(),
                state_offered_utilization=offered_ratio.mean(),
                state_excluded_utilization=(offered_ratio-included_ratio).mean(),
                mean_fee_relative_to_state_root=ratio.mean(),
                fee_relative_to_state_root_p05=np.quantile(ratio, .05),
                fee_relative_to_state_root_p50=np.quantile(ratio, .50),
                fee_relative_to_state_root_p95=np.quantile(ratio, .95),
                state_binding_fraction=(state>regular).mean(),
                regular_binding_fraction=(regular>state).mean(),
                below_target_fraction=below.mean(),
                below_target_zero_decrease_fraction=(below & unchanged).mean(),
                zero_decrease_given_below_target=(below & unchanged).sum()/below.sum(),
                mean_price_response=response.mean(),
                mean_state_shock=state_shock.mean(),
                shock_price_response_covariance=(state_shock*response).mean()
                    -state_shock.mean()*response.mean(),
            ))
    return pd.DataFrame(records)


def main():
    source = OUT/'normalized_outcomes.csv'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    full = pd.read_csv(source)
    rows = full[full.window_days.isin([60, 75]) & full.propagation_time_s.isin([3.5, 5])].reset_index(drop=True)
    assert len(rows) == 4
    base = pd.read_csv(DATA/'equilibrium_anchor_by_floor_rate.csv').iloc[0]
    workload = build_canonical_workload()
    assert len(workload.paths) == 32
    config = normalized_config(rows, base, repeat=len(workload.paths))
    result = run_normalized_batch(config, workload.paths,
        np.repeat(rows.launch_fee_wei.to_numpy(), len(workload.paths)),
        burn_in=BURN_IN, return_paths=True)
    paths = path_diagnostics(rows, workload.paths, result)
    summary = paths.drop(columns='path').groupby(
        ['window_days', 'propagation_time_s'], as_index=False).mean()
    for _, row in summary.iterrows():
        cached = rows[rows.window_days.eq(row.window_days) & rows.propagation_time_s.eq(row.propagation_time_s)].iloc[0]
        np.testing.assert_allclose(row.state_utilization, cached.state_utilization, rtol=1e-12)
        np.testing.assert_allclose(row.state_binding_fraction, cached.state_binding_fraction, rtol=1e-12)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    paths.to_csv(OUT/'state_utilization_diagnostic_paths.csv', index=False)
    summary.to_csv(OUT/'state_utilization_diagnostics.csv', index=False)
    manifest = dict(
        source_sha256=before,
        workload_sha256=hashlib.sha256(workload.paths.tobytes()).hexdigest(),
        paths_per_setting=len(workload.paths), burn_in_blocks=BURN_IN,
        measured_blocks=workload.paths.shape[1]-BURN_IN,
        summary='Arithmetic mean of 32 path-level metrics; quantiles are mean within-path quantiles.',
        interpretation='Descriptive replay diagnostic; no counterfactual removal of integer rounding.',
    )
    (OUT/'state_utilization_diagnostic_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(summary.to_string(index=False))


if __name__ == '__main__':
    main()
