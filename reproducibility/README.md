# Reproducing the paper results

## Commands and what they verify

Run from the repository root after installing `requirements.txt`:

```bash
# Restore and checksum the captured inputs; recompute strict selections/tables.
python reproducibility/reproduce.py

# Rebuild the empirical paths and replay the selected mechanisms and sensitivities.
python reproducibility/reproduce.py --replay

# Also replay the complete 301-cell central propagation/target grid.
python reproducibility/reproduce.py --replay --full-grid

# Numerical and accounting tests (inputs must first be restored).
PYTHONPATH=src python -m pytest -q
```

The complete replay compares fresh numerical output against the frozen tables.
It fails if execution, data, state, congestion, or the checked fee-floor metrics
do not agree. Inputs and results are separate: generated tables and the verification
report go to `reproducibility/results/`. Existing inputs with different checksums
are rejected rather than replaced. Use a clean checkout if local experiments
have modified the captured files. `--prepare-only` restores inputs without analysis.

The two compressed input bundles (split into parts of at most 7 MB for the
anonymous hosting service; reassembled automatically) contain captured public-chain measurements,
calibration tables, and historical experiment results. `inputs_manifest.json`
records each file's SHA-256 checksum. Archives have no author metadata or local
filesystem paths. The bundled table archive retains exploratory results needed
by the existing regression tests; it does not make every historical selection
part of the final paper. `reference/` and this entry point define the paper's
current selection.

## Frozen settings

- Central elasticity window: 35 days; sensitivity windows: 21, 60, and 75 days.
- Central elasticities used in simulation: execution 0.121160, data 0.229476,
  state 0.334864. These six-decimal inputs match the original runs.
- 32 matched paths, each with 7,200 burn-in and 50,400 measured blocks.
- Path shape: `(32, 57600, 4)`; path SHA-256:
  `2af918e3989c78a13c68bdd7c8f8e01df0e705a35ff9c0a0c81b115b41ecbec1`.
- The paths, including the central historical-price adjustment, stay fixed in
  elasticity sensitivity. Resource/BAL shocks are jointly sampled and combined
  with the hourly/daily factors by `build_canonical_workload`.
- Propagation allocations: 3, 3.5, 4, 4.5, and 5 seconds; total time budget 9 seconds.
- The propagation comparison uses the physically derived 3-second data limit
  **89.908576M**, not the rounded 90M used in the separate fixed-limit heatmap.
- Execution targets: 150–300M in steps of 25M. Data targets: 22.5, 36, 45, 52.5,
  60, 67.5, 80, 90, and 100M; retain targets strictly below their limits.
- Conservative eligibility: mean near-limit fraction no greater than
  **0.0473442920145728**, and equilibrium execution fee strictly above 1 wei
  (numerical tolerance `1e-6` wei). No target-deviation condition is applied.
- Near-limit means at least 98% of either hard limit, counting a block once.
- Maximum throughput maximizes execution over the same candidate grid.
- The 60-/75-day conservative sensitivity retains the previously tested lower
  execution-target extensions, recorded in `reference/lower_target*.csv`.
  No new candidates are added during reselection.

## Expected central comparison

Mean execution gas per block, in millions:

| Propagation (s) | Normalized 1/2 | Normalized 4/5 | Conservative | Maximum |
|---:|---:|---:|---:|---:|
| 3.0 | 166.9 | 206.4 | 173.6 | 252.9 |
| 3.5 | 177.9 | 215.0 | 198.1 | 263.6 |
| 4.0 | 174.7 | 214.1 | 221.4 | 270.7 |
| 4.5 | 165.3 | 208.5 | 221.2 | 272.6 |
| 5.0 | 151.9 | 199.0 | 199.4 | 271.0 |

Conservative pairs are E175/D36, E200/D45, E225/D52.5, E225/D52.5, and E200/D60.
Maximum-throughput pairs are E300/D67.5, E300/D67.5, E300/D80, E300/D90, and E300/D90.
The paired conservative gain is negative on two of the 32 paths at 3 seconds;
its mean is positive at every allocation. Configuration selection and comparison
use the same paths, so these are in-sample comparisons.

The [saved comparison figure](reference/execution_comparison.pdf) uses these
current selections. `results/comparison.csv` also reports execution target
utilization for the multi-dimensional selections and regular-branch target
utilization for the normalized benchmarks.

## Coverage and provenance

| Paper component | Inputs / implementation | Verification in this entry point |
|---|---|---|
| Elasticity calibration | `data/glamsterdam/elasticity_*`, resource-demand notebooks | Frozen estimates supplied; sensitivity is replayed |
| Execution and data metering | `data/shared_fee/execution_repricing_*`, floor-rate tables, accounting modules | Captured calibration supplied; accounting unit tests |
| BAL attribution | `data/7999/bal_runtime_*`, `build_bal_runtime_state_attribution.py` | Captured attribution/decomposition tables supplied |
| Empirical demand paths | Three contiguous panels plus daily accounting; `build_canonical_workload` | Rebuilt from captured inputs; exact hash checked |
| Baseline and growth-matched | `shared_fee.replay`; four elasticity vectors | Fresh execution, data, state and congestion compared |
| Normalized shared fee | `normalized_state`, `target_ratio`, `excess_update` | Central 1/2, 4/5, fake-exponential, and all four elasticity vectors |
| Multi-dimensional comparison | `dynamics.batched_replay`; strict selection here | Selected cases, paired paths, conservative and maximum elasticity replay |
| Exact-90M data-limit experiments | `reference/fixed_600m_90m.csv`, `reference/e275_exact90_sensitivity.csv` | Central heatmap and E275 sensitivity replay |
| Central propagation grid | `data/7999/slot_time_scenarios.csv` | All 301 paper cells with `--full-grid` |

This reproduces simulations from captured empirical inputs. It is not an
independent recollection of the original chain measurements. Full trace-level
RPC caches are not bundled, and the original extraction notebooks require Xatu
and archive-node credentials to refresh measurements. The exploratory notebooks
are not a single-command reproduction of the final paper's figure layout.
The numerical tables are the reference for checking that figures use current
rather than superseded selections.

`requirements-tested.txt` records the package versions used for verification;
Python/platform details are in `verification_summary.json`; each run records
its own elapsed time in `results/verification.json`. Small floating-point differences across platforms
are permitted by explicit numerical tolerances; demand-path generation is
checked against its exact reference hash.
