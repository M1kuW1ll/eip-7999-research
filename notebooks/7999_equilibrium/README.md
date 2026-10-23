# EIP-7999 publication notebooks

These notebooks document the exploratory research workflow. For the paper’s
current strict selection, frozen inputs, and automated checks, start with
[the reproduction guide](../../reproducibility/README.md). Some exploratory
grids and selection criteria differ from the final paper; they are retained
for provenance and are not the paper reproduction entry point.

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
