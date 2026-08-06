# EIP-7999 publication notebooks

These notebooks reproduce the quantitative results and figures in:

- `markdowns/bundle_priced_bal_demand_model_report.md`; and
- `markdowns/bundle_priced_7999_equilibrium_report.md`.

Run them in order from the repository root:

1. `01-data-metering-runtime-bal.ipynb` reconstructs current and
   counterfactual static-data metering, builds the deterministic 6,000-block
   EIP-8279 runtime sample, and estimates the runtime-BAL anchor.
2. `02-bal-decomposition.ipynb` attributes runtime bytes to direct state
   creation, co-produced access, and non-state transactions, then derives the
   BAL intensities used in bundle-priced parent demand. It also carries
   forward the execution and state metering multipliers calculated by
   `../resource_demand_and_glamsterdam_equilibrium/02-metering-multipliers.ipynb`.
3. `03-bundle-priced-equilibrium.ipynb` solves the active-set EIP-7999
   equilibrium, execution fee-floor frontier, capacity grid, and robustness
   cases using those metering multipliers and the elasticities estimated by
   `../resource_demand_and_glamsterdam_equilibrium/03-demand-model-elasticity.ipynb`.

## Data refresh

The notebooks use cached mode by default. To rebuild the ignored `data/`
artifacts from their sources, copy `.env.example` to `.env`, fill in the
credentials, and set:

```bash
export REFRESH_7999_FROM_NETWORK=1
```

The refresh requires `CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD` for Xatu,
plus either `ETHNODEOPS_API_KEY` or a complete `ALCHEMY_RPC` URL. Optional
endpoint overrides are `CLICKHOUSE_RAW_HOST`, `CLICKHOUSE_PORT`, and
`ETHNODEOPS_RPC`.

Notebook 01 queries canonical Xatu blocks and transactions, constructs the
same 500-candidate-per-day plan with seed 42, retains the first 50 stable ranks
per day, reconstructs the block-level EIP-8279 runtime counter, and downloads
complete transaction bodies through RPC. Notebook 02 queries the same blocks
at transaction level from Xatu for the BAL attribution. Both network paths are
chunked and resumable.

For exact report reproduction, notebook 01 retains the three RPC blocks that
were unavailable to the original static-field calibration as publication
sample exclusions. The switch is explicit in its configuration cell.

## Execution

After installing `requirements.txt`, run:

```bash
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/7999_equilibrium/01-data-metering-runtime-bal.ipynb \
  notebooks/7999_equilibrium/02-bal-decomposition.ipynb \
  notebooks/7999_equilibrium/03-bundle-priced-equilibrium.ipynb \
  --ExecutePreprocessor.timeout=7200
```

The first two notebooks write compact handoffs to `data/7999/`. The third
notebook regenerates the report-facing equilibrium CSVs under `data/` and the
tracked report figures under `plots/`. Shared execution/state metering anchors
and elasticity vectors are verified against `data/glamsterdam/` when those
handoffs are present; otherwise the exact published values are used and
identified as shared inputs in the notebooks.
