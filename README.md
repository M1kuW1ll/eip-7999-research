# EIP-7999 Resource-Demand and Fee-Market Research

This repository studies Ethereum fee markets that price execution, data, and
state creation separately. The current analysis has four stages:

1. reconstruct historical resource use under proposed metering rules;
2. estimate independent isoelastic demand for execution, data, and state;
3. solve target-clearing base fees for Glamsterdam and full EIP-7999; and
4. use those equilibria to initialize a dynamic replay.

The central empirical model is the independent three-resource isoelastic model.
The older aggregate-demand and nested-share equilibrium notebooks are retained
under `archived/` for reference, but they are no longer part of the active
workflow.

## Canonical Reports

- `markdowns/project_proposal.md`: project motivation and research questions.
- `markdowns/bandwidth_limit_report.md`: propagation-based data limits.
- `markdowns/three_way_resource_elasticity_report.md`: independent execution,
  data, and state elasticities.
- `markdowns/three_way_glamsterdam_equilibrium_report.md`: Glamsterdam
  equilibrium fees under EIP-8037 and execution repricing.
- `markdowns/full_7999_data_metering_and_bal_report.md`: EIP-7999 static-data
  metering and the BAL demand model.
- `markdowns/modeling_plan.md`: equilibrium-initialized dynamic replay plan.

Superseded reports and working notes are in `archived/markdowns/`.

## Active Notebook Sequence

### Resource construction and passive replay

| Notebook | Purpose |
|---|---|
| `0.1-rpc-bal-rlp.ipynb` | Construct exact BAL RLP bytes from RPC traces. |
| `0.2-bandwidth-limit-scenarios.ipynb` | Derive propagation-based data limits. |
| `0.3-bandwidth-content.ipynb` | Combine calldata, BALs, access lists, authorization tuples, and blob hashes. |
| `0.4-state-growth-xatu.ipynb` | Build the scalable Xatu state-creation proxy. |
| `0.5-state-growth-rpc-calibration.ipynb` | Calibrate state creation against RPC traces. |
| `0.6-glamsterdam-regular-gas-recalculation.ipynb` | Recalculate Glamsterdam execution gas. |
| `0.7-glamsterdam-passive-replay.ipynb` | Replay the Glamsterdam/EIP-8037 mechanism. |
| `0.8-glamsterdam-plus-bandwidth.ipynb` | Replay EIP-8037 with a separate data dimension. |
| `0.9-full-7999-passive-replay.ipynb` | Replay full three-resource EIP-7999. |
| `1.0-blob-base-fee-calldata-correlation.ipynb` | Check the historical blob-fee/calldata relationship. |

### Empirical calibration

| Notebook | Purpose |
|---|---|
| `1.1-daily-accounting-panel.ipynb` | Construct the 120-day resource-accounting panel. |
| `1.2-sampled-block-calibration.ipynb` | Calibrate RPC-only access-list and authorization inputs. |
| `1.3-bal-size-calibration.ipynb` | Estimate BAL size from scalable Xatu block features. |
| `1.4-eip7623-calldata-event-study.ipynb` | Measure the EIP-7623 calldata response. |
| `1.5-gas-limit-data-share-event-study.ipynb` | Estimate resource responses around gas-limit changes. |
| `1.8-three-way-share-model.ipynb` | Recover independent execution, data, and state elasticities. |
| `1.10-execution-repricing-calibration.ipynb` | Estimate execution repricing under EIP-8038 and EIP-2780, with EIP-7904 as an additional scenario. |
| `1.11-bal-state-creation-coupling-calibration.ipynb` | Attribute BAL bytes to execution/state access and direct state creation. |

### Equilibrium and dynamics

| Notebook | Purpose |
|---|---|
| `1.9-three-way-equilibrium-model.ipynb` | Solve the Glamsterdam bottleneck-resource equilibrium. |
| `2.4-bal-bundle-pricing-reference.ipynb` | Solve the supported BAL bundle-pricing equilibrium. |
| `2.5-full-7999-bundle-priced-dynamic-replay.ipynb` | Run the supported bundle-priced EIP-7999 dynamic replay. |

Notebooks `1.6` and `1.7` were intermediate aggregate-demand models. They have
been superseded by notebooks `1.8` and `1.9` and moved to
`archived/notebooks/`.

Notebooks `2.0` through `2.2` preserve earlier full-EIP-7999 equilibrium and
replay specifications. They have been superseded by notebooks `2.4` and `2.5`
and moved to `archived/notebooks/`.

## Core Accounting Conventions

### Glamsterdam

Execution and EIP-8037 state gas share one EIP-1559 fee. The charged quantity
is the larger of repriced execution gas and state-creation gas:

```text
glamsterdam_gas_used = max(repriced_execution_gas, state_creation_gas_8037)
```

The current execution calibration includes EIP-8038 and EIP-2780. EIP-7904 is
kept as a separate scenario because its inclusion is less certain.

### Full EIP-7999

The full mechanism separates three quantities:

```text
execution gas = repriced execution activity

data gas = 16 * (
  calldata bytes
  + transaction access-list bytes
  + authorization-tuple bytes
  + blob-versioned-hash bytes
  + BAL bytes
)

state gas = EIP-8037 persistent-state creation gas
```

Static transaction data and BAL data do not share the same demand equation.
Static data uses the empirically estimated data-price elasticity. BALs are
derived from their parent execution/state activity, with the directly
state-creation-linked share calibrated in notebook `1.11`.

## Data Sources

- Xatu/CBT supplies scalable block and transaction measurements.
- RPC traces are used only where Xatu does not expose the required information,
  particularly exact BAL RLP construction and selected state-creation checks.
- Expensive RPC results are cached under `data/` and reused by later notebooks.

`data/` and most of `plots/` are generated local artifacts and are ignored by
Git. Figures embedded by canonical reports are explicitly retained. The active
`plots/` directory contains only figures generated by the current empirical,
equilibrium, and dynamic notebooks. Older figures are retained locally in
`archived/plots/`; the two figures embedded by an archived report are also
retained by Git.

## Repository Layout

```text
archived/
  markdowns/   superseded reports and working notes
  notebooks/   superseded and exploratory notebooks
  plots/       older generated figures
  src/         retired helper code
  tests/       retired tests

configs/       replay and simulation configuration
data/          cached input and generated CSV files
markdowns/     canonical reports and modeling plan
notebooks/     active research workflow
plots/         current generated figures
src/           reusable accounting, demand, mechanism, and simulation code
tests/         tests for active source modules
```

## Reproducing the Analysis

Install the dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the test suite:

```bash
PYTHONPATH=src python3 -m pytest
```

Most empirical notebooks can be rerun from cached CSV files. Notebooks that
refresh Xatu or RPC inputs require credentials in a local `.env` file. Do not
commit credentials or replace cached samples unintentionally.
