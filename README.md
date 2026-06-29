# EIP-7999 Multidimensional Fee/Resource Simulator

This repository studies Ethereum fee-market designs where block resources are
accounted separately instead of being collapsed into one gas counter.

The current project focus is:

- execution gas
- bandwidth gas, currently modeled from calldata + BAL bytes + transaction
  access-list bytes + authorization-list bytes + blob versioned hashes
- state-growth gas under EIP-8037

The project is staged deliberately. First, derive bandwidth limits from payload
propagation safety. Then build block-level resource inputs. Then replay
candidate mechanisms passively before adding elasticity or transaction-packing
models.

## Current Mechanisms

### Mechanism 0: Glamsterdam / EIP-8037 Baseline

This is the committed passive replay baseline in
`notebooks/0.9-glamsterdam-passive-replay.ipynb`.

The transaction-level regular-gas recalculation that feeds this baseline lives in
`notebooks/0.8-glamsterdam-regular-gas-recalculation.ipynb`.

State growth remains under EIP-8037. The block-level bottleneck is:

```text
execution_state_used = max(execution_gas_used, state_gas_used)
```

The shared execution/state base fee uses the normal EIP-1559 linear update with
denominator 8. EIP-8037 changes the gas-used input, not the update rule.

Bandwidth is reported as a diagnostic in this mechanism, but it does not have a
separate limit or base fee.

### Mechanism A: Glamsterdam + Separate Bandwidth

This is the next mechanism under active development. The goal is:

```text
execution/state:
  execution_state_used = max(execution_gas_used, state_gas_used)

bandwidth:
  bandwidth_gas = calldata_gas + BAL_gas + tx_access_list_gas
                  + authorization_tuple_gas + blob_versioned_hash_gas
```

Bandwidth then gets its own EIP-7999-style target, limit, excess accumulator,
and fake-exponential base fee. State remains under EIP-8037 for this stage.
The bandwidth gas formula here is a simulator design choice, not a claim that
every byte already has this gas price in the scheduled Glamsterdam specs.

## Data Pipeline

### Bandwidth Inputs

Bandwidth content is built from Xatu plus RPC:

- Xatu supplies calldata bytes.
- Xatu `execution_transaction` supplies zero/nonzero calldata byte counts for
  calldata gas.
- RPC `debug_traceBlockByNumber` with `prestateTracer` supplies BAL RLP bytes.
- RPC full transaction objects supply EIP-2930/EIP-7981 transaction access-list
  address and storage-key counts.
- RPC transaction fetches supply EIP-7702 authorization lists.
- Xatu transaction fields supply blob versioned hash counts.

The main bandwidth output is produced by
`notebooks/0.5-bandwidth-content.ipynb`:

```text
bandwidth_payload_bytes =
  calldata_bytes
  + bal_rlp_bytes
  + tx_access_list_bytes
  + authorization_tuple_rlp_bytes
  + blob_versioned_hash_bytes

bandwidth_gas =
  calldata_gas
  + bal_gas
  + tx_access_list_gas
  + authorization_tuple_gas
  + blob_versioned_hash_gas
```

These gas components intentionally mix two kinds of accounting, so keep the
labels straight:

- Current EIP-7999 calldata resource gas uses the old calldata rule:
  `4 * zero_calldata_bytes + 16 * nonzero_calldata_bytes`.
- The 64 gas/byte number is a floor-accounting rate from EIP-7976, EIP-7981,
  EIP-8131, and EIP-8279-style proposals. It is not automatically the unit of
  an EIP-7999 bandwidth resource.
- BAL bytes under EIP-7928 do not have a direct `16 gas/byte` price in
  Glamsterdam. They are constrained indirectly by execution gas and BAL item
  rules. The current simulator's `bal_gas = 16 * bal_rlp_bytes` is a candidate
  bandwidth-resource convention.
- Authorization tuples and blob versioned hashes are included in the broadened
  bandwidth content table because they are transaction-content bytes. Their
  `64 gas/byte` columns are EIP-8131-style floor-accounting columns, not current
  EIP-7999 calldata-resource gas.

For transaction access lists, `tx_access_list_bytes` follows EIP-7981:
`20 * address_entries + 32 * storage_keys`, charged at `64 gas/byte`.
For authorization tuples, the notebook keeps both actual RLP bytes and the
EIP-8131 fixed-size/floor-accounting byte count.

### State-Growth Inputs

State-growth inputs are built in two steps:

- `notebooks/0.6-state-growth-xatu.ipynb` pulls scalable Xatu/CBT estimates for
  storage-slot creation, account creation, and code bytes.
- `notebooks/0.7-state-growth-rpc-calibration.ipynb` calibrates the Xatu
  estimator against RPC/prestate traces and adds EIP-7702 delegation indicators.

The replay input is:

```text
state_gas_8037 =
  new_storage_slots * 64 * CPSB
  + new_accounts * 120 * CPSB
  + code_bytes * CPSB
  + new_delegation_indicators * 23 * CPSB
```

For the current EIP-8037 profile, `CPSB = 1530`.

## Notebook Sequence

```text
notebooks/
  0.1-data-pull.ipynb
    credential and Xatu smoke test

  0.2-calldata-xatu.ipynb
    calldata bytes and calldata gas from Xatu

  0.3-rpc-bal-rlp.ipynb
    BAL RLP bytes from RPC/prestate traces

  0.4-bandwidth-limit-scenarios.ipynb
    propagation caps and Glamsterdam worst-case bandwidth limits

  0.5-bandwidth-content.ipynb
    calldata + BAL + access-list + authorization-list + blob-hash bandwidth table

  0.6-state-growth-xatu.ipynb
    scalable Xatu state-growth estimator

  0.7-state-growth-rpc-calibration.ipynb
    RPC calibration for accounts and delegation indicators

  0.8-glamsterdam-regular-gas-recalculation.ipynb
    transaction-level EIP-7976/EIP-7981 regular-gas recalculation

  0.9-glamsterdam-passive-replay.ipynb
    Glamsterdam/EIP-8037 passive replay
```

## Repository Layout

```text
configs/
  synthetic_bandwidth_only.yaml

data/
  generated CSV/RLP artifacts

markdowns/
  project notes and reports

plots/
  generated PNG plots

archived/
  older exploratory notebooks and helpers

src/
  bandwidth_limits/
    bandwidth propagation limit and worst-case payload analysis

  basefee/
    EIP-1559 and EIP-7999-style base-fee helpers

  mechanisms/
    passive replay mechanisms

  resources/
    shared resource accounting types and helpers

  sim/
    Xatu/RPC data pulls, BAL construction, synthetic/replay helpers

  state_limits/
    state growth target/limit derivation helpers
```

## Quick Start

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the current passive EIP-8037 replay tests:

```bash
PYTHONPATH=src python -m pytest \
  tests/test_basefee_eip1559.py \
  tests/test_mechanism_glamsterdam_only.py
```

Open notebooks in order when rebuilding the 500-block sample:

```bash
jupyter notebook notebooks/0.2-calldata-xatu.ipynb
jupyter notebook notebooks/0.3-rpc-bal-rlp.ipynb
jupyter notebook notebooks/0.5-bandwidth-content.ipynb
jupyter notebook notebooks/0.6-state-growth-xatu.ipynb
jupyter notebook notebooks/0.7-state-growth-rpc-calibration.ipynb
jupyter notebook notebooks/0.8-glamsterdam-regular-gas-recalculation.ipynb
jupyter notebook notebooks/0.9-glamsterdam-passive-replay.ipynb
```

## Local Configuration

Some notebooks need private data-service or RPC credentials. Keep those in a
local `.env` file and do not commit real credentials to notebooks, YAML,
markdown, or git history.

## Important Modeling Notes

- The CBT `gas_state_growth` field is useful as a diagnostic, but it is too
  broad to subtract from execution gas for EIP-8037 replay because it includes
  non-creation state/access activity.
- For Glamsterdam-only replay, regular gas should come from the transaction-level
  0.8 recalculation: receipt gas after historical state-creation de-accounting,
  plus the EIP-7976 calldata floor branch and EIP-7981 access-list data
  surcharge where they bind.
- In the passive replay, over-limit historical blocks are flagged as invalid
  diagnostics. Their base-fee update is capped at the 60M block limit, matching
  how a valid full block would update by at most 12.5%.
- Synthetic notebooks and older Xatu-only BAL experiments are archived as
  context. The current realized-block pipeline uses Xatu for calldata and RPC
  for BAL/state calibration where Xatu lacks the necessary trace detail.
