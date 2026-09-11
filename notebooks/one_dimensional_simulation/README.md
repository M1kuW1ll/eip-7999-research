# One-dimensional simulation: report reproduction

Run these four notebooks in order to reproduce the central results,
sensitivities, tables, and figures in
[One-dimensional vs. Multi-dimensional Fee Market: The Case for Ethereum](../../markdowns/eip8279_floor_calibration_report.md).

| Notebook | Results |
|---|---|
| [01 — Baseline simulation](01-baseline-simulation.ipynb) | Xatu input pulls, transaction-floor accounting, the 64-gas data multiplier, and baseline equilibria and simulation |
| [02 — Floor-adjusted + EIP-8368](02-floor-adjusted-eip8368.ipynb) | Physical limit and floor-rate derivation, rate-specific data multipliers, matched CPSB, simulations, floor/CPSB attribution, and shared baseline/EIP-8368 sensitivities |
| [03 — Floor-adjusted + EIP-8372](03-floor-adjusted-eip8372.ipynb) | CPSB and state-limit-scale calibration, normalized-counter simulations, elasticity and state-tail sensitivity, deployment capacity, rounding checks, and resource pulses |
| [04 — Comparison with EIP-7999](04-comparison-with-7999.ipynb) | Main five-row comparison table, all propagation allocations, paired gains, sensitivity tables, and comparison figures |

## Prerequisites and source reconstruction

Install the repository dependencies with `python -m pip install -r requirements.txt`.
Run the upstream publication notebooks before this sequence:

1. `../resource_demand_and_glamsterdam_equilibrium/01`–`04`: source pulls,
   February–May 2026 accounting/metering anchors, complete elasticity vectors,
   and the Glamsterdam reference anchor.
2. `../7999_equilibrium/01`–`02`: the deterministic 6,000-block sample,
   RPC static-content transaction panel, Xatu runtime-BAL carrier panel,
   and bundle-demand/data-metering anchors.
3. `../7999_simulation/01`–`04`: contiguous block/runtime panels, the
   canonical multiscale demand paths, physical target surfaces, historical
   selection benchmark, and parameter surfaces.

Use the EIP-7999 outputs regenerated under the report's updated execution
schedule. Notebook 01 checks the shared execution multiplier against the
EIP-7999 anchor; the comparison runners check numerical reproduction of the
EIP-7999 results. These notebooks retain the existing model kernels and dated
calibration assumptions. They do not silently update to later EIP schedules.

The upstream READMEs and notebook refresh cells document the Xatu/RPC pulls.
RPC inputs use `ETHNODEOPS_API_KEY` or `ALCHEMY_RPC` as configured there.
For the additional shared-fee Xatu inputs, configure `.env` with
`CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, and optionally
`CLICKHOUSE_RAW_HOST` / `CLICKHOUSE_PORT`. Notebook 01 executes:

```bash
python scripts/shared_fee/pull_transaction_inputs.py --chunk-size 100
python scripts/shared_fee/pull_execution_repricing_components.py --chunk-size 100
python scripts/shared_fee/pull_runtime_components.py --chunk-size 200
python scripts/shared_fee/rebuild_execution_repricing.py --refresh-refunds
```

Enable these pulls with `ONE_DIMENSIONAL_REFRESH_XATU=1`. Membership, opcode,
and runtime queries resume saved chunks; this flag is a network-enabled
reconstruction, not an instruction to discard completed chunks. Refund
aggregates are queried with `--refresh-refunds`. Without the flag, the
notebook uses existing source exports and reports missing inputs explicitly.
No credentials or large transaction panels are embedded in the notebooks.

## Execute

From the repository root, recompute calibration and simulation from local
source panels:

```bash
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/one_dimensional_simulation/01-baseline-simulation.ipynb \
  notebooks/one_dimensional_simulation/02-floor-adjusted-eip8368.ipynb \
  notebooks/one_dimensional_simulation/03-floor-adjusted-eip8372.ipynb \
  notebooks/one_dimensional_simulation/04-comparison-with-7999.ipynb \
  --ExecutePreprocessor.timeout=7200
```

Set `ONE_DIMENSIONAL_REFRESH_XATU=1` for a network-enabled input rebuild.
For a complete existing run, set `ONE_DIMENSIONAL_REUSE_OUTPUTS=1` to execute
the display, derivation, comparison, and validation cells while reusing
simulation outputs. Reuse does not claim to rerun the simulations or the
transaction-level calibration. Both modes regenerate the figures and the
comparison CSVs. Do not enable refresh and reuse together.

The default runs the calibration and central simulation stages. The existing
elasticity robustness runner reuses its complete cached common-limit surface
when present; on a fresh reconstruction it computes the alternative-vector
surface. The expensive floor sweep recalibrates 35 rates with 400 bootstrap
replications. Source pulls can take substantially longer than simulation.

## Order and outputs

Notebook 01 reconstructs floor exposure at 64 gas/byte and runs the five
baseline allocations. Notebook 02 then performs the full floor-rate sweep
and 380-setting attribution experiment. That sweep writes generic diagnostic
files for its detailed 96-gas case; Notebook 01 explicitly selects the
64-gas anchor when revisited in reuse mode.

The common state-tail and elasticity runners in Notebook 02 include baseline
and EIP-8368 together. They also prepare the frozen EIP-7999 references used
by Notebook 03. The normalized-state runner therefore has all prerequisites
before it calibrates its five configurations and replays its 20 fixed-vector
cases. Notebook 04 assembles the comparisons from these results.

Generated tables remain under `data/shared_fee/` and
`data/shared_fee/eip8372/`. In addition to the report's existing outputs:

- `publication_baseline_outcomes.csv` contains the standalone five-case
  baseline replay when recomputation is enabled;
- `publication_comparison_summary.csv` contains the five selected designs;
- `publication_comparison_all_allocations.csv` contains the 25 central
  family/propagation combinations.

Every comparison uses the same 32 workload paths, 7,200 burn-in blocks and
50,400 measured blocks. Hash checks preserve upstream EIP-7999/Glamsterdam
tables and verify matched-workload provenance. State-demand-cap comparisons
retain unrestricted EIP-7999 references, as stated in the report.

The table keeps metered execution separate from parent activity and reports
physical state growth, because EIP-8372 rescales raw state gas. The
one-dimensional fee-exposure measure is a counter-weighted charge proxy;
the EIP-7999 measure is modeled base-fee burn.
