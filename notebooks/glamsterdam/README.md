# Glamsterdam publication notebooks

These notebooks reproduce the quantitative results and figures in
`markdowns/glamsterdam_analysis.md`:

1. `01-data-processing.ipynb`
2. `02-metering-multipliers.ipynb`
3. `03-demand-model-elasticity.ipynb`
4. `04-glamsterdam-equilibrium.ipynb`

Run them in order from the repository root. Notebook 01 supports cached and
full-refresh modes. In full-refresh mode it queries Xatu/CBT, runs the
deterministic 6,000-block RPC calibration, and reconstructs the execution
refund inputs. Set `REFRESH_FROM_NETWORK = True` in its configuration cell and
provide the documented `.env` credentials.

Large source artifacts remain in the Git-ignored `data/` directory. Compact
handoff files are written to `data/glamsterdam/`, and report figures are
written to `plots/`.

After installing `requirements.txt`, the non-interactive reproduction command
is:

```bash
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/glamsterdam/01-data-processing.ipynb \
  notebooks/glamsterdam/02-metering-multipliers.ipynb \
  notebooks/glamsterdam/03-demand-model-elasticity.ipynb \
  notebooks/glamsterdam/04-glamsterdam-equilibrium.ipynb \
  --ExecutePreprocessor.timeout=600
```

The original research notebooks remain unchanged and continue to document the
underlying collection, calibration, and exploratory work.
