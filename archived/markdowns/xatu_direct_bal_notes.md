# Xatu-Direct BAL Construction Notes

Status: superseded by the RPC BAL path in `rpc_bal_notes.md`. Keep this note as
historical context for why the project moved away from Xatu-only BAL sizing.

## What We Build

The simulator needs raw bandwidth bytes:

```text
bandwidth_bytes = calldata_bytes + bal_rlp_bytes
```

For BAL, the RLP object is account-centric. Each account entry is:

```text
[address, storage_writes, storage_reads, balance_changes, nonce_changes, code_changes]
```

That is why BAL cannot be estimated from storage reads/writes alone. Balance,
nonce, code, and empty touched-account shells also occupy payload bytes.

## Xatu Table Mapping

The current Xatu-direct constructor uses:

| BAL section | Xatu source |
| --- | --- |
| calldata bytes | `canonical_beacon_block_execution_transaction.call_data_size` |
| storage writes | `canonical_execution_storage_diffs` |
| storage reads | `canonical_execution_storage_reads` |
| balance changes | `canonical_execution_balance_diffs` |
| touched balance accounts | `canonical_execution_balance_reads` |
| nonce changes | `canonical_execution_nonce_diffs` |
| code changes | `canonical_execution_contracts` plus canonical payload tx positions |

The default storage read mode is `read_not_written`, matching the BAL builder's
rule that read slots written in the same block are omitted from
`storage_reads`. `all_xatu_reads` is kept as a diagnostic upper variant over
the read slots Xatu exposes.

## Calibration Block 22,886,891

The known `eth-bal-analysis` RLP sample is:

```text
22886891_with_reads.rlp = 119,857 raw bytes
```

The Xatu-direct constructor currently gives:

| read mode | BAL RLP bytes | delta vs RPC sample |
| --- | ---: | ---: |
| `read_not_written` | 103,299 | -16,558 |
| `all_xatu_reads` | 110,756 | -9,101 |
| `none` | 93,232 | -26,625 |

The match is strong for writes and code:

```text
storage write changes = 841
unique written slots  = 608
code bytes            = 16,479
```

The remaining gap is mostly storage reads. The RPC sample has 801 storage-read
slots, while Xatu exposes 527 unique storage-read slots for this block, or 302
after applying the builder's read-not-written rule.

## Working Interpretation

Use the Xatu-direct BAL constructor as the main scalable pipeline, and use
RPC-built RLP samples as calibration points. Do not treat the old aggregate
`cold_sload_count` proxy as the main estimator anymore.

For the simulator, the default column should be the Xatu-direct raw RLP estimate
with the read-mode label preserved. The calibration gap should remain visible
until we know whether Xatu's storage-read table is intentionally narrower than
the `debug_traceBlockByNumber` `prestateTracer` read set.
