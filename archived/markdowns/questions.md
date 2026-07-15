## Some Questions during progressing (updating)

1. For the state growth resource limit, the proposal says roughly 100 GiB/year via CPSB = 1174, but the current EIP-8037 draft says CPSB = 1530 and targets 120 GiB/year.

```
annual target = 120 GiB/year
blocks/year = 2,628,000
CPSB = 1530
state_target_bytes/block ≈ 49,029 bytes
state_target_gas/block ≈ 75,014,840 gas
state_gas_limit ≈ 150,029,680 gas

This gives the state gas limit of 150M.
```

If we use the number in the proposal, we have:

```
annual target = 100 GiB/year
CPSB = 1174
state_target_bytes/block ≈ 40,858 bytes
state_target_gas/block ≈ 47,967,005 gas
state_gas_limit ≈ 95,934,010 gas

This gives the state gas limit of ~96M.
```

2. Clarify gas-per-byte meanings for bandwidth.

The current confusion is that three different accounting concepts can look like
"gas per byte":

- standard / intrinsic gas
- transaction floor gas
- future EIP-7999 bandwidth-resource gas

The biggest correction is:

```text
64 gas/byte is a floor-accounting number from EIP-7976, EIP-7981,
EIP-8131, and EIP-8279-style rules.

It is not automatically the gas unit of an EIP-7999 bandwidth resource.
```

In current EIP-7999, calldata is moved into a separate resource, but its gas
formula is still the old calldata formula:

```text
zero calldata byte     = 4 gas
nonzero calldata byte  = 16 gas
```

The corrected table should be:

| Component | Current / post-7623 | Glamsterdam scheduled | EIP-8131 / EIP-8279 floor world | Future EIP-7999 bandwidth resource |
| --- | --- | --- | --- | --- |
| Calldata standard / intrinsic | 4 / 16 | 4 / 16 | 4 / 16 standard path still exists | moved out of intrinsic; resource gas is still 4 / 16 in current EIP-7999 |
| Calldata floor | 10 / 40 for data-heavy transactions | 64 / 64 for data-heavy transactions via EIP-7976 | 64 gas/byte under EIP-8131 unified tx-content floor | current EIP-7999 removes the floor; a future design could choose otherwise |
| Access-list data bytes | no per-byte data floor, but EIP-2930 still charges 2400/address + 1900/key | 64 gas/byte surcharge via EIP-7981 | 64 gas/byte under EIP-8131 | not automatically in current EIP-7999 bandwidth unless we choose to include it |
| BAL data bytes | no BAL | no direct per-byte price; constrained indirectly by opcode gas and EIP-7928 item rules | 64 gas/byte runtime BAL floor under EIP-8279 | project choice; current simulator assumes 16 gas/byte for BAL bandwidth gas |
| EIP-7702 auth-tuple bytes | no tx-content floor; EIP-7702 has per-auth gas costs | no tx-content floor unless EIP-8131 is included | 64 gas/byte, modeled as 108 bytes/auth under EIP-8131 | not automatically in current EIP-7999 bandwidth |
| Blob-versioned-hash bytes | no tx-content floor, but blobs have blob gas | no tx-content floor unless EIP-8131 is included | 64 gas/byte, modeled as 32 bytes/hash under EIP-8131 | not automatically in current EIP-7999 bandwidth |

So we should keep two separate mental models:

- the floor-accounting / worst-case block-size table, which defends against
  large transaction or block payloads under single-dimensional execution-gas
  style accounting
- the candidate EIP-7999 bandwidth-resource table, which is about our separate
  bandwidth vector and is a simulator design choice

Important notes:

- EIP-7928 does not price BAL bytes at 16 gas/byte.
- In Glamsterdam without EIP-8279, BAL bytes are created by execution. For
  example, cold SLOAD consumes execution gas and adds storage-key data to the
  BAL. This is not a direct BAL byte price.
- EIP-7981 adds a data-footprint surcharge for access lists, but access lists
  already have EIP-2930 address/key gas costs.
- Auth tuples and blob versioned hashes are not free. The point is that their
  serialized transaction-content bytes are not covered by the tx-content floor
  until an EIP-8131-style rule.

### B. Candidate EIP-7999 bandwidth-resource table

This table is about our separate bandwidth vector. It is a simulator design
choice, not necessarily the scheduled Glamsterdam gas schedule.

| Component | Current project assumption |
| --- | --- |
| Zero calldata byte | 4 bandwidth gas |
| Nonzero calldata byte | 16 bandwidth gas |
| BAL byte | 16 bandwidth gas, baseline simulator assumption |
| Transaction access-list byte | currently tracked; 64 gas/byte column is floor-style accounting |
| Authorization tuple byte | currently tracked; 64 gas/byte column is EIP-8131-style floor accounting |
| Blob versioned hash byte | currently tracked; 64 gas/byte column is EIP-8131-style floor accounting |
| Bandwidth gas limit | currently often mapped as `16 * safe_bandwidth_bytes` |

The clean project split should be:

```text
Mode 1: EIP-7999 bandwidth baseline
  calldata = 4/16
  BAL = 16/byte as a simulator convention

Mode 2: EIP-8131 + EIP-8279 floor stress test
  static tx content = 64/byte
  runtime BAL = 64/byte
```

Do not merge these unless we explicitly decide to propose a new
64-gas-per-byte EIP-7999 bandwidth dimension.

3. Do the same L2 blob posters also switch to calldata from the same address?

For the current 500-block sample:

```text
blocks = 24,120,001 to 24,120,500
source = mainnet.dim_block_blob_submitter joined to Xatu execution_transaction

blob submitter addresses checked = 91
addresses with calldata-only txs from the same address = 1
total calldata-only bytes from blob submitters = 4 bytes
```

So, in this sample, the answer is basically no. The addresses that submit blobs
do not also appear to send meaningful calldata-only transactions from the same
address.

This means `dim_block_blob_submitter` is useful for labeling blob demand by L2
or project, but it is not enough to label calldata fallback / calldata DA
demand. To study L2 calldata demand, we likely need a separate map of L2 inbox,
batch, or calldata-submission contracts and then classify calldata by
`to_address`, not only by blob submitter `from` address.

The better split for the calldata-demand question is:

```text
blob-submitter calldata:
  calldata sent by addresses that also submit blobs

L2-inbox calldata:
  calldata sent to known L2 inbox / batch / calldata DA contracts

other calldata:
  everything else
```

Then we can test:

```text
blob_base_fee[t] vs L2_inbox_calldata[t + k]
blob_gas_used[t] vs L2_inbox_calldata[t + k]
blob_base_fee[t] vs other_calldata[t + k]
```


## C. metrics to compare 8037 Glamsterdam vs. 7999

1. Base-fee volatility

   execution / execution_state

   data

   state

2. Bottleneck diagnostics under G0 and A

   share of blocks where execution > state

   share where state > execution

   size of the gap between execution and state

3. Cross-subsidy / mispricing proxy

   When execution is bottleneck but state is low:

     how much do state-heavy txs pay because execution is congested?

   When state is bottleneck but execution is low:

     how much do execution-heavy txs pay because state is congested?

4. Limit / target pressure

   data usage / data target

   data usage / data limit

   state usage / state target

5. Long-run state growth

   annualized state bytes under passive and elastic demand

6. Composite user cost by transaction class

   execution-heavy

   data-heavy

   state-growth-heavy

   BAL-heavy state-access

   mixed

7. Joint spikes

   frequency data and state base fees both spike

The “cross-subsidy” metric is especially important for the state question. If EIP-8037’s max-bottleneck fee often makes state-heavy users pay high fees when state is not scarce, or makes execution-heavy users pay high fees when execution is not scarce, then separate state pricing looks more valuable.

If those divergence cases are rare, then EIP-8037’s simplicity may be empirically good enough.

## D. Demand model and elasticity questions

The implementation ladder is now mostly represented in the notebooks, so the
remaining open questions are less about mechanics and more about demand
modeling.

### 1. How should historical demand be scaled to future capacity?

Passive replay is useful for accounting and base-fee paths, but it cannot answer
what happens under future high-capacity regimes if historical blocks do not fill
those limits.

Open question:

```text
For scenarios like 450M execution gas and a larger data limit, how should we
scale historical demand?
```

Candidate scaling scenarios:

- uniform scale-up
- execution-heavy scale-up
- data-heavy scale-up
- state-growth-heavy scale-up
- BAL-heavy state-access scale-up
- correlated data + state stress

The purpose is to ask which resource binds first as capacity expands.

### 2. What is the right elasticity structure?

Independent per-resource isoelastic curves are probably too simple because a
transaction consumes a bundle of resources:

```text
tx bundle = execution_gas + data_gas + state_gas
composite_cost = p_exec * x + p_data * d + p_state * s
```

A better first model may be two-layer:

```text
Layer 1: aggregate demand expansion / contraction
Layer 2: allocation or share substitution across transaction classes/resources
```

This matters because state-heavy transactions can also create BAL bytes and
therefore consume bandwidth/data gas.

Open question:

```text
Should the first elastic replay use aggregate demand elasticity plus
resource-share substitution, instead of independent resource demand curves?
```

### 3. How should Maria's substitution parameter be used?

Maria's state/burst elasticity work suggests that state and burst resources can
behave like capacity-constrained substitutes under a shared gas regime. The
important point for this project is that the substitution parameter should be
swept, not treated as known.

Useful priors from that work:

```text
aggregate demand elasticity: roughly 0.10 to 0.28
state-share elasticity eta: central estimate around 0.43
state-growth elasticity: roughly 0.3 to 0.6
burst/execution elasticity: roughly 0.0 to 0.2
```

But those estimates come from a one-dimensional shared-capacity setting. Under
full EIP-7999, where execution, data, and state have separate prices and limits,
that substitution may weaken.

Sweep candidates:

```text
eta = 0 or very low: weak substitution / resources more independent
eta ≈ 0.43: Maria central estimate
eta high: old shared-capacity substitution persists
```

Open question:

```text
Does the G0/A/B comparison remain stable across eta, or does the conclusion flip
when substitution is stronger or weaker?
```

### 4. How should Offchain Labs elasticity estimates be used?

The Offchain Labs paper is useful as a broad short-run elasticity sanity check.
The high-level implication is:

- aggregate L1/L2 demand appears very inelastic in the short run
- computation/execution is close to inelastic
- calldata/data is mildly elastic
- storage growth is more elastic than computation/data
- wallet and user heterogeneity matter

Open question:

```text
Should the elastic replay use low short-run aggregate elasticity, but allow
higher elasticity for state/storage growth than for execution?
```

### 5. Is drop-only elasticity enough?

Drop-only elasticity means:

```text
if price rises, demand falls
if price falls, demand does not expand
```

This is useful for congestion stress tests, but it cannot evaluate expanded
future capacity because high-limit scenarios require latent demand to grow.

Open question:

```text
Should drop-only demand be limited to congestion stress, while future-capacity
analysis uses symmetric elasticity or explicit demand expansion?
```

### 6. What transaction classes should be modeled first?

The first class breakdown should probably be simple and resource-vector based:

- execution-heavy
- data-heavy
- state-growth-heavy
- BAL-heavy state-access
- mixed execution/data/state

Open question:

```text
Is this class split enough for the first elastic replay, or do we need L2-specific
classes immediately?
```

### 7. Which axes are mandatory in the first elastic sweep?

Candidate sweep axes:

- data limit: propagation-derived cap around 40M vs draft-style 60M
- data target ratio
- BAL gas per byte
- state target
- substitution parameter eta
- aggregate demand elasticity
- state-growth elasticity
- demand scaling scenario

Open question:

```text
Which of these axes are mandatory for the first useful sweep, and which should
be deferred?
```

### Meeting framing

```text
The demand model should probably not be independent per-resource curves. It
should be a capacity-expansion model with aggregate elasticity and resource-share
substitution, using transaction bundles to map composite prices into
execution/data/state usage. The main question is how to scale historical demand
to future limits, and how broadly to sweep the substitution parameter eta.
```
