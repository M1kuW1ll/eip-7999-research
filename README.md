# Ethereum resource pricing and fee mechanisms 

This repository compares one-dimensional and multi-dimensional fee mechanisms
under empirical Ethereum demand and shared propagation/execution constraints.
It includes the accounting and simulation code, frozen empirical inputs,
reference results, and a paper-specific reproduction entry point.

## Reproduce the paper

Use Python 3.11 or later (tested with Python 3.13). From the repository root:

```bash
python -m pip install -r requirements.txt
python reproducibility/reproduce.py
python reproducibility/reproduce.py --replay --full-grid
```

The first command restores bundled inputs and reproduces configuration selection
and comparison tables. The second rebuilds the 32 matched demand paths and
reruns the shared-fee benchmarks, the selected multi-dimensional cases,
elasticity checks, and all 301 central propagation/target configurations.
Neither command requires network access, an archive node, or credentials.
Generated results are written to `reproducibility/results/`; frozen reference
results are not overwritten. See [the reproduction guide](reproducibility/README.md)
for scope, inputs, expected results, and limitations.

The paper's conservative selection uses the historical near-limit fraction
**without a 25% tolerance and without a target-deviation filter**. The candidate
grid excludes D77. Earlier exploratory scripts and notebooks retain their
original grids and criteria; use the paper entry point above for current results.

## Tests

After restoring the bundled inputs:

```bash
PYTHONPATH=src python -m pytest -q
```

## Layout

- `src/`: resource accounting, demand, fee updates, inclusion, and simulation kernels.
- `scripts/`: empirical data collection and exploratory experiment workflows.
- `notebooks/`: exploratory analysis; execution outputs are cleared for review.
- `reproducibility/`: paper-specific runner, checksummed inputs, and reference tables.
- `data/`: restored inputs and historical experiment outputs.
- `tests/`: numerical, accounting, and reproduction checks.
- `plots/`: saved research figures; the reproduction guide identifies the current comparison.

## Data sources and accounting

Xatu supplies Ethereum mainnet block, transaction, and resource measurements.
Archive-node RPC supplies transaction access lists, authorization tuples, and
trace/state information needed for the metering and BAL reconstructions.
The equilibrium anchor covers February–May 2026; the simulation's contiguous
block panel covers April–May 2026. Data-source queries and extraction code are
included. Refreshing those original measurements requires the user's own Xatu
and archive-node access; `.env.example` lists the configuration variables.

The shared-fee benchmarks track regular and state gas with a common fee.
The multi-dimensional model prices execution, static data, and state separately,
including generated BAL data in the effective price of its parent activity.
State normalization changes the fee-update counter but preserves raw state-gas
charging. The shared-fee per-block charge statistic is a counter-weighted proxy,
not a transaction-exact measurement of fee burn.

Private manuscript drafts and internal reports are excluded from this artifact.
