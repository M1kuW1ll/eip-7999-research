# Bundle-priced EIP-7999 dynamic-simulation notebooks

These four notebooks reproduce the tables and figures in
`markdowns/bundle_priced_7999_dynamic_and_slot_time_report.md` and its
publication-facing copy, *Dynamic Simulation of a Bundle-Priced EIP-7999
Multidimensional Fee Market*.

Run the notebooks in order:

| Notebook | Report results reproduced |
|---|---|
| `01-demand-shocks.ipynb` | Three parent-demand shocks, BAL access-composition shock, multiscale bootstrap, normalization and source diagnostics |
| `02-simulation-and-target-grid.ipynb` | Fixed $L_E=2T_E$ target grid, E300-row results, and the three target-grid heatmaps |
| `03-slot-time-allocation.ipynb` | Physical execution/data limits, E300/D80 slot-time diagnostic, maximum-throughput candidates, and historically anchored candidates |
| `04-sensitivity-analysis.ipynb` | 36-case fixed-design sensitivity, eight full selection surfaces, sensitivity figures, and the two-regime summary |

The former `notebooks/simulation/2.5-full-7999-bundle-priced-dynamic-replay.ipynb`
was an exploratory predecessor that explicitly did not reproduce the report. It
is preserved under `archived/notebooks/simulation/` and is not part of this
workflow.

## Upstream publication inputs

The dynamic report is conditional on the metering anchors, BAL decomposition,
and elasticity estimates established by the preceding reports. Rebuild those
handoffs first by running:

1. `notebooks/resource_demand_and_glamsterdam_equilibrium/01` through `03`;
2. `notebooks/7999_equilibrium/01` and `02`.

Their READMEs document the Xatu and RPC refresh paths. The simulation notebooks
verify the required handoff files rather than silently substituting hard-coded
values.

## Xatu and RPC refresh

Copy `.env.example` to `.env` and configure:

- `CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD` for Xatu;
- optionally `CLICKHOUSE_RAW_HOST` and `CLICKHOUSE_PORT`;
- `ETHNODEOPS_API_KEY` or a complete `ALCHEMY_RPC` URL for the RPC-derived
  upstream calibration.

Notebook 01 contains and runs the exact contiguous-data commands when
`REFRESH_7999_SIMULATION_FROM_NETWORK=1`:

```text
python scripts/build_contiguous_block_panel.py \
  --start 2026-04-02 --days 60 --out-dir data/contiguous

python scripts/build_contiguous_runtime_bal.py \
  --range 24788193 25118358 --label hist60d --chunk-size 250

python scripts/build_contiguous_runtime_bal.py \
  --range 25118359 25218797 --label full14d --chunk-size 250
```

The runtime-BAL reconstruction is the expensive step. It is chunked and writes
partial checkpoints, so an interrupted refresh can resume. Notebook 03 uses the
same refresh flag to query the February–May 2026 historical fee-market benchmark
directly from Xatu.

## Execution

Install dependencies from the repository root:

```bash
python3 -m pip install -r requirements.txt
```

Run from cached local source panels while recomputing every simulation:

```bash
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/7999_simulation/01-demand-shocks.ipynb \
  notebooks/7999_simulation/02-simulation-and-target-grid.ipynb \
  notebooks/7999_simulation/03-slot-time-allocation.ipynb \
  notebooks/7999_simulation/04-sensitivity-analysis.ipynb \
  --ExecutePreprocessor.timeout=7200
```

For a full network refresh, execute notebook 01 and notebook 03 with
`REFRESH_7999_SIMULATION_FROM_NETWORK=1`. The default behavior reruns the
simulation stages. Set `REUSE_7999_SIMULATION_OUTPUTS=1` only to validate and
redraw the report from existing ignored CSV outputs.

All large inputs and result tables are written below `data/`, which is ignored
by Git. Report figures are regenerated below `plots/`; the figures embedded in
the report remain versioned.
