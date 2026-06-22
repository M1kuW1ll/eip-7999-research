# EIP-7999 Bandwidth Simulator

This repository first implements a transitional design: EIP-7999-style
bandwidth pricing for calldata + BAL bytes, while state growth remains priced
through the EIP-8037 regular/state-gas bottleneck baseline. This isolates the
bandwidth-design question before comparing against a later mechanism where
state growth also becomes a separate EIP-7999 resource.

## Mechanism A

Mechanism A is bandwidth-separated, with state under the EIP-8037 baseline.

Execution and state:

```text
regular_gas_used
state_gas_used
execution_state_used = max(regular_gas_used, state_gas_used)
```

The shared execution/state base fee updates from `execution_state_used`.

Bandwidth:

```text
bandwidth_used = calldata_bytes + bal_bytes
```

Bandwidth has its own target, limit, excess accumulator, base fee, and optional
reserve-price rule.

The approximate transaction-level cost model is:

```text
cost =
  shared_base_fee * (regular_gas + state_gas)
  + bandwidth_base_fee * (calldata_bytes + bal_bytes)
```

### BAL Data Path

The primary bandwidth data path combines Xatu calldata with RPC-built BAL
bytes. Xatu provides full-coverage calldata from the canonical beacon payload
transaction table. Xatu's `execution_transaction` table provides zero/nonzero
calldata byte counts for calldata gas after it is validated against the beacon
payload totals. `canonical_execution_transaction` is kept only as a diagnostic.
RPC provides BAL bytes using `debug_traceBlockByNumber` with `prestateTracer`:

```text
bandwidth_rlp_bytes = xatu_calldata_bytes + rpc_bal_rlp_bytes
```

Run `notebooks/0.2-calldata-xatu.ipynb` first, then
`notebooks/0.3-rpc-bal-rlp.ipynb`. The Xatu-only BAL notebook, helper, and
notes are archived as diagnostic context, but Xatu remains the main source for
calldata bytes.

### Bandwidth Limit vs Replay Error Bands

The Xatu calldata + RPC BAL notebooks estimate realized blocks. Their main
block-level columns are:

- `calldata_bytes`: total raw calldata bytes from Xatu
  `canonical_beacon_block_execution_transaction.call_data_size`.
- `calldata_zero_bytes`, `calldata_nonzero_bytes`, `calldata_gas_7999`: from
  Xatu `execution_transaction` only when it matches the beacon payload count and
  raw byte total. Otherwise these are unavailable.
- `bal_rlp_bytes`: raw RLP BAL bytes from the RPC BAL constructor when using
  `notebooks/0.3-rpc-bal-rlp.ipynb`.
- `bandwidth_rlp_bytes`: `calldata_bytes + bal_rlp_bytes`.
- `bal_union_raw_est`: older count-based raw RLP-like estimate after
  block-level set-union deduplication.
- `bal_no_dedup_raw_est`: older no-dedup replay sensitivity for an estimate
  error band on that realized block.

`bal_no_dedup_raw_est` is not the adversarial worst-case payload bound used to
set `bandwidth.limit_bytes`. The limit `B` should come from an analytic
gas-cost worst-case block-size model, such as
`nerolation/glamsterdam-worst-case-block-size`, plus the propagation-safety
target. Keep these two paths separate:

```text
realized replay estimate/error band -> Xatu calldata + RPC BAL estimator
adversarial propagation limit B     -> analytic gas-cost worst-case model
```

## Repository Layout

```text
configs/
  synthetic_bandwidth_only.yaml
data/
  generated CSV/RLP data artifacts
markdowns/
  project_proposal.md
  notes and writeups
archived/
  0.4-xatu-direct-bal-rlp.ipynb
  00_synthetic_replay.ipynb
  01_parameter_sweep_synthetic.ipynb
  test_xatu_bal.py
  xatu_bal.py
  xatu_direct_bal_notes.md
notebooks/
  0.1-data-pull.ipynb
  0.2-calldata-xatu.ipynb
  0.3-rpc-bal-rlp.ipynb
  0.4-bandwidth-limit-scenarios.ipynb
src/
  bandwidth_limits/
    scenarios.py
    worst_case.py
    propagation.py
    eip7999_metering.py
    sweep.py
  sim/
    config.py
    synthetic.py
    basefee.py
    eip8037.py
    replay.py
    metrics.py
    plots.py
    rpc_bal.py
    xatu_calldata.py
```

## BAL Construction

BAL is not only storage reads and writes. The RLP object is grouped by account:

```text
[address, storage_writes, storage_reads, balance_changes, nonce_changes, code_changes]
```

The RPC constructor in `src/sim/rpc_bal.py` maps those BAL sections from
`prestateTracer` output and encodes the resulting block object as raw RLP. The
calldata helper in `src/sim/xatu_calldata.py` reads calldata bytes from Xatu.
This split is intentional: Xatu is scalable and full-coverage for calldata,
while RPC is needed for the full BAL read set.

## Quick Start

Install the Python dependencies, then run the calldata/BAL notebooks:

```bash
python3 -m pip install -r requirements.txt
jupyter notebook notebooks/0.2-calldata-xatu.ipynb
jupyter notebook notebooks/0.3-rpc-bal-rlp.ipynb
```

## Credentials

Store ClickHouse credentials in a local `.env` file at the repo root. Do not put
real credentials in notebooks, YAML configs, markdown, or git history.

```bash
cp .env.example .env
# edit .env with your real username and password
```

The data-pull notebook loads `.env` automatically and expects:

```text
CLICKHOUSE_USER=...
CLICKHOUSE_PASSWORD=...
ALCHEMY_RPC=https://eth-mainnet.g.alchemy.com/v2/...
```

For a first credential smoke test, install dependencies, edit `.env`, then run
the small-range Xatu notebook:

```bash
python3 -m pip install -r requirements.txt
jupyter notebook notebooks/0.1-data-pull.ipynb
```

Or run the replay directly:

```bash
PYTHONPATH=src python3 - <<'PY'
from sim import generate_synthetic_blocks, load_config, replay
from sim.metrics import compute_metrics

config = load_config("configs/synthetic_bandwidth_only.yaml")
blocks = generate_synthetic_blocks(config)
df = replay(blocks, config)
print(compute_metrics(df, config).T)
PY
```

## First Milestone

The first milestone is passive replay on 10,000 synthetic blocks. It answers:

- Given block-level demand, what does the bandwidth base fee do?
- How different is `bandwidth = calldata + BAL` from `bandwidth = calldata`
  only?
- Does the EIP-8037 `max(regular, state)` baseline react when state gas is the
  bottleneck?

The synthetic generator uses five explicit regimes:

- normal blocks
- L2 calldata bursts
- BAL/state-access bursts
- state-growth bursts
- correlated calldata + BAL stress

The main notebook outputs the five MVP plots plus a metrics table.
