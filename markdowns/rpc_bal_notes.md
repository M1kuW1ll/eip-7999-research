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
total. `canonical_execution_transaction` is diagnostic only.

The BAL output column comes from RPC:

```text
bal_rlp_bytes
```

and bandwidth is:

```text
bandwidth_rlp_bytes = xatu_calldata_bytes + rpc_bal_rlp_bytes
```

## Calibration Block 22,886,891

Using Xatu for calldata and `ALCHEMY_RPC` for BAL, the joined path successfully
ran for block `22,886,891`.

```text
calldata_bytes      = 63,197  (Xatu)
calldata_zero_bytes = 39,716  (Xatu execution_transaction)
calldata_nonzero    = 23,481  (Xatu execution_transaction)
calldata_gas_7999   = 534,560 (4 * zero + 16 * nonzero)
bal_rlp_bytes       = 119,920
bandwidth_rlp_bytes = 183,117
accounts            = 555
storage writes      = 841 changes over 608 slots
storage reads       = 801
balance changes     = 692
nonce changes       = 271
code changes        = 2 changes, 16,479 code bytes
```

The local `eth-bal-analysis` sample for `22886891_with_reads.rlp` is `119,857`
bytes, so the current RPC builder is `+63` bytes. The important mismatch that
broke the Xatu path is gone: the RPC path recovers the full `801` storage reads
seen in the sample, whereas Xatu-direct exposed only `527` unique storage reads
for this block.

For calldata validation, `execution_transaction` aligns with the beacon payload
table on block `22,886,891`:

```text
beacon payload tx rows        = 268
execution_transaction rows    = 268
beacon calldata bytes         = 63,197
execution_transaction bytes   = 63,197
```

`canonical_execution_transaction` is sparse here:

```text
canonical_execution_transaction rows  = 184
canonical_execution_transaction bytes = 46,677
```

A broader sample is saved in:

```text
data/xatu_calldata_table_validation_sample.csv
```

In that sample, `canonical_execution_transaction` matched only 3 of 18 checked
blocks. We do not use it for calldata gas pricing.

## System Changes

The module has an `include_system_changes` toggle. The notebook now sets it to
`True`, matching the current `eth-bal-analysis` builder path, which appends
withdrawal balance changes plus EIP-4788/EIP-2935 system storage writes at
`tx_index = len(transactions)`.
