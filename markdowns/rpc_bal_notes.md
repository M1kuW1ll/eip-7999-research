# RPC BAL Construction Notes

## Decision

Use Xatu calldata plus RPC-built RLP BAL bytes as the primary simulator input.
The Xatu-only BAL path is now exploratory/legacy because its storage-read
coverage did not match the `eth-bal-analysis` RPC samples.

## Why RPC

BAL contains more than storage writes and reads:

```text
[address, storage_writes, storage_reads, balance_changes, nonce_changes, code_changes]
```

The storage-read section is the most sensitive part. Xatu's
`canonical_execution_storage_reads` table exposed fewer read slots than the
known RPC sample for block `22,886,891`, while `debug_traceBlockByNumber` with
`prestateTracer` can recover the full trace-derived read set used by
`eth-bal-analysis`.

BAL `storage_reads` is not a simple count of `SLOAD`
opcodes and it is not a per-transaction sum. It is a block-level set of storage
slots that were needed for execution but were not already represented as storage
writes in the block-level BAL. To construct it correctly, the builder needs the
full set of touched storage locations, then it performs block-level set logic:

```text
storage_reads = storage slots touched/read by execution
                minus storage slots written in the same block
```

That means a dataset table can be directionally useful but still too narrow for
BAL sizing if it does not expose every storage location that `prestateTracer`
would include in the transaction's accessed pre-state. In block `22,886,891`,
the local RPC/Toni path has `801` BAL storage-read slots. The Xatu-direct path
found only `527` unique storage-read slots before applying the read-not-written
filter, and only `302` after applying the BAL builder's filter. This is why the
Xatu-direct BAL estimate was short by thousands of bytes even when storage
writes and code bytes matched well.

RPC is better for this part because `prestateTracer` in non-diff mode returns
the pre-state for accounts and storage locations touched by execution, including
slots that do not end up with a post-state diff. The RPC builder can then union
those slots at block level and subtract written slots in the same way as
`eth-bal-analysis`. The Xatu table may be intentionally narrower, may represent
a different trace-derived read concept, or may omit cases that matter for BAL
construction. Until that semantic gap is resolved, Xatu is safe for calldata,
but RPC is the safer source for BAL bytes.

## Implementation

The primary notebooks are:

```text
notebooks/0.2-calldata-xatu.ipynb
notebooks/0.3-rpc-bal-rlp.ipynb
```

The underlying module is:

```text
src/sim/rpc_bal.py
```

It fetches:

| Data | RPC method |
| --- | --- |
| state writes / diffs | `debug_traceBlockByNumber`, `prestateTracer`, `diffMode=true` |
| storage reads / balance touches | `debug_traceBlockByNumber`, `prestateTracer`, `diffMode=false` |
| reverted tx gas accounting | `eth_getBlockReceipts` |
| block metadata / tx list for BAL bookkeeping | `eth_getBlockByNumber` |

The raw calldata column comes from Xatu:

```text
canonical_beacon_block_execution_transaction.call_data_size
```

Zero/nonzero byte counts and calldata gas come from Xatu `execution_transaction`
after checking that it matches the beacon payload transaction count and raw byte
total.

The BAL output column comes from RPC:

```text
bal_rlp_bytes
```

and bandwidth is:

```text
bandwidth_rlp_bytes = xatu_calldata_bytes + rpc_bal_rlp_bytes
```

## Calibration Block 22,886,891

Using Xatu for calldata and ethnodeops Erigon mainnet RPC for BAL, the joined
path successfully ran for block `22,886,891`.

```text
calldata_bytes      = 63,197  (Xatu)
calldata_zero_bytes = 39,716  (Xatu execution_transaction)
calldata_nonzero    = 23,481  (Xatu execution_transaction)
calldata_gas_7999   = 534,560 (4 * zero + 16 * nonzero)
bal_rlp_bytes       = 120,499
bandwidth_rlp_bytes = 183,696
accounts            = 559
storage writes      = 844 changes over 611 slots
storage reads       = 801
balance changes     = 708
nonce changes       = 271
code changes        = 2 changes, 16,479 code bytes
```

The current value uses:

```text
bal_semantics = eip7928_pre_tx_post_indices_v1
include_reads = True
include_system_changes = True
```

The important mismatch that broke the Xatu path is gone: the RPC path recovers
the full `801` storage reads seen in the local `eth-bal-analysis` sample, whereas
Xatu-direct exposed only `527` unique storage reads for this block.

## Why Our RLP Bytes Differ From Toni's Local Samples

The local `eth-bal-analysis` sample files are useful calibration artifacts, but
they should not be treated as the current target output for this simulator. The
simulator now estimates an EIP-7928-style block-level BAL payload, including
system entries.

For block `22,886,891`:

```text
Toni local sample, with reads              = 119,857 bytes
updated EIP-7928-style system-change mode  = 120,499 bytes  (+642)
```

The large gap is not caused by missing or extra storage reads. The decoded local
sample and the RPC path both have `801` storage reads. Most of the gap comes from
system-level entries that the current EIP-7928 design requires in the block
access list:

```text
withdrawal recipients -> balance changes
EIP-2935 parent-hash history -> system contract storage write
EIP-4788 beacon root -> system contract storage writes
```

The latest spec-style handling also changes the BAL indices:

```text
0       = pre-execution system contract calls
1..n    = transactions
n + 1   = post-execution system contract calls
```

Our previous system-change mode used normal Python transaction indices
`0..n-1` and put system changes at `tx_index = len(transactions)`. The updated
path shifts transaction entries to `1..n`, records pre-execution system writes at
index `0`, and records withdrawals at `n + 1`.

The updated path also records both EIP-4788 ring-buffer slots:

```text
timestamp slot = timestamp % 8191
root slot      = timestamp % 8191 + 8191
```

and uses the EIP-2935 history slot:

```text
(block_number - 1) % 8191
```

The calibration deltas against the local `with_reads` samples are:

```text
22886891: 120,499 vs 119,857  delta +642
22886892: 104,914 vs 104,376  delta +538
22886893:  88,311 vs  87,790  delta +521
```

## RPC Provider Cross-Check

The BAL builder supports RPC headers, so ethnodeops is now the default BAL RPC
provider. The notebook uses:

```text
ETHNODEOPS_RPC=https://erigon.mainnet.rpc.ethnodeops.xyz
X-API-Key: <ETHNODEOPS_API_KEY from .env>
```

The non-client-specific mainnet endpoint also works:

```text
https://mainnet.rpc.ethnodeops.xyz
```

For blocks `22,886,892` and `22,886,893`, ethnodeops matched the current CSV
exactly. For block `22,886,891`, the load-balanced endpoint produced a slightly
smaller BAL:

```text
ethnodeops Erigon / current CSV:   120,499 bytes, 801 storage reads
ethnodeops load-balanced result:   120,367 bytes, 797 storage reads
delta:                             -132 bytes, -4 storage reads
```

Client-specific ethnodeops endpoints explain the difference:

```text
geth.mainnet.rpc.ethnodeops.xyz    -> 120,367 bytes, 797 storage reads
erigon.mainnet.rpc.ethnodeops.xyz  -> 120,499 bytes, 801 storage reads
reth.mainnet.rpc.ethnodeops.xyz    -> 120,499 bytes, 801 storage reads
```

So the remaining provider difference is not from calldata, system changes,
balance changes, nonce changes, or code changes. It is a small
client-dependent `prestateTracer` storage-read difference. For reproducible BAL
calibration runs, the notebook pins Erigon instead of relying on a
load-balanced archive endpoint.

So the right interpretation is:

```text
include_system_changes = False
  Use as a comparison mode for Toni's older checked-in sample bytes.

include_system_changes = True
  Use as the main simulator estimate for calldata + EIP-7928 BAL bandwidth.
```

For calldata validation, `execution_transaction` aligns with the beacon payload
table on block `22,886,891`:

```text
beacon payload tx rows        = 268
execution_transaction rows    = 268
beacon calldata bytes         = 63,197
execution_transaction bytes   = 63,197
```

## System Changes

The module has an `include_system_changes` toggle. The notebook now sets it to
`True` for the main `bal_rlp_bytes` output. This is defensible because the
bandwidth resource is meant to capture the actual block payload:

```text
bandwidth = calldata bytes + BAL bytes
```

System contract writes and withdrawal balance changes still occupy BAL bytes,
even though they are not normal user transaction calldata.
