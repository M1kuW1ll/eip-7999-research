# Bandwidth Limit Report

## Summary

This milestone derives the bandwidth vector limit only. In the current staged
model, state growth remains under EIP-8037. In the final project, state growth
may become its own EIP-7999 resource with its own base fee, target, and limit.

This does not change the bandwidth-limit derivation, because the bandwidth
limit is set by payload propagation:

```text
bandwidth = calldata + BAL bytes
```

So this report only covers how to choose candidate EIP-7999 bandwidth limits.
It does not choose bandwidth targets or target ratios yet; those are later
fee-market tuning parameters. It also does not decide whether state growth later
becomes a separate EIP-7999 vector.

The current conclusion is:

- Without an EIP-8279-like runtime BAL-byte floor, the worst-case payload is a
  mixed transaction: nonzero calldata plus many cold SLOADs that create BAL
  bytes.
- With an EIP-8279-like runtime BAL-byte floor, the worst case collapses back
  toward the simple uniform byte bound: roughly `execution_gas_limit / 64`.
- Recent historical blocks in the 50-block sample are far below the candidate
  propagation-derived byte caps.

## Files Added

```text
src/bandwidth_limits/
  scenarios.py
  worst_case.py
  propagation.py
  eip7999_metering.py
  sweep.py

notebooks/0.4-bandwidth-limit-scenarios.ipynb
tests/test_bandwidth_limits.py
```

## Scenario Definitions

The two implemented schedules are:

```text
glamsterdam_no_8279
  scheduled Glamsterdam / Toni worst-case analysis baseline
  EIP-7976 calldata floor: 64 gas per calldata byte for calldata-heavy transactions
  EIP-7981 access-list repricing
  EIP-7928 block-level access lists
  no runtime BAL-byte floor

glamsterdam_plus_8279
  Hegota / EIP-7999 sensitivity case
  same bandwidth payload components as above
  assumes an EIP-8279-like runtime BAL-byte floor ships with EIP-7999
  plus runtime BAL bytes charged at 64 gas per BAL byte in the floor accumulator
```

The first scenario is the Glamsterdam setting from Toni's repository and
analysis: EIP-7976, EIP-7981, and EIP-7928 are present, but no EIP-8279 runtime
BAL-byte floor is assumed.

The second scenario is not the scheduled Glamsterdam baseline. It is a
forward-looking Hegota/EIP-7999 sensitivity case: if EIP-7999 targets Hegota,
and if an EIP-8279-like runtime BAL-byte floor is included in the same fork,
then BAL bytes become protected by the same kind of 64 gas/byte floor as
calldata-heavy payloads. It is worth modeling because it materially changes the
worst-case bandwidth limit.

The important distinction is whether BAL bytes are protected by a runtime byte
floor. In `glamsterdam_no_8279`, execution can create BAL bytes through cheap
state accesses relative to their payload size. In `glamsterdam_plus_8279`, those
BAL bytes also contribute to the 64 gas/byte floor, which prevents the mixed
calldata/SLOAD strategy from exceeding the uniform byte bound.

The phrase "calldata floor" is important: EIP-7976 does not mean every
transaction pays 64 gas for every calldata byte in every case. It introduces a
floor that binds for calldata-heavy transactions. The worst-case calldata-only
strategy is intentionally calldata-heavy, so the model uses the 64 gas/byte
floor there.

## Worst-Case Strategy Model

The code does not add independent maximum calldata and independent maximum BAL.
Instead, it optimizes total payload under one gas limit.

Implemented strategies:

- `all_calldata_nonzero`: one transaction with only nonzero calldata.
- `sload_bal_only`: one transaction with one cold account plus many cold SLOADs.
- `mixed_calldata_plus_cold_sloads`: one transaction with nonzero calldata plus
  cold SLOADs; this searches over SLOAD count.
- `tx_access_list_plus_calldata`: a simple access-list plus calldata check under
  64 gas/byte access-list repricing.

For the mixed strategy, gas is:

```text
tx_base_gas + max(
    16 * calldata_bytes + execution_gas,
    64 * calldata_bytes + runtime_bal_floor_component
)
```

where `runtime_bal_floor_component` is `0` without 8279 and
`64 * bal_bytes` with 8279.

## How The Worst-Case Bytes Are Produced

The worst-case table reports the `calldata_bytes` and `BAL bytes` from the
winning strategy for each gas limit and schedule. These are not historical
measurements and not independent maxima. They are the bytes created by the best
adversarial construction under the gas constraint.

For `all_calldata_nonzero`, the construction is:

```text
available_gas = gas_limit - tx_base_gas
calldata_bytes = floor(available_gas / 64)
BAL bytes = 0
```

At 60M gas:

```text
available_gas = 60,000,000 - 21,000
              = 59,979,000

calldata_bytes = floor(59,979,000 / 64)
               = 937,171

total_payload_bytes = 937,171
```

For `mixed_calldata_plus_cold_sloads`, the construction chooses a number of
cold SLOADs and then fills the remaining gas with calldata. In the simplified
model:

```text
BAL bytes     = 20 + 32 * sload_count
execution gas = 2,600 + 2,100 * sload_count
```

The optimizer searches over `sload_count`. For each candidate it computes how
many calldata bytes still fit under:

```text
tx_base_gas + max(
    16 * calldata_bytes + execution_gas,
    64 * calldata_bytes + runtime_bal_floor_component
) <= gas_limit
```

At 60M gas without 8279, the winning mixed strategy is:

```text
sload_count = 21,420

BAL bytes = 20 + 32 * 21,420
          = 685,460

calldata_bytes = 937,150

total_payload_bytes = 937,150 + 685,460
                    = 1,622,610
```

This beats the calldata-only payload:

```text
1,622,610 > 937,171
```

So `mixed_calldata_plus_cold_sloads` is the best strategy for
`glamsterdam_no_8279` at 60M gas.

With 8279, the runtime BAL-byte floor adds:

```text
runtime_bal_floor_component = 64 * BAL bytes
```

That means BAL bytes consume the same kind of 64 gas/byte budget as calldata
bytes. The mixed strategy no longer gets extra payload cheaply, so the winning
strategy becomes the simple calldata-heavy transaction:

```text
calldata_bytes = 937,171
BAL bytes = 0
total_payload_bytes = 937,171
```

## Propagation Fits

The propagation model is:

```text
propagation_time_ms = intercept_ms + slope_ms_per_kb * (payload_bytes / 1024)
```

Two p90 fits are implemented:

```text
empirical_p90:
  slope_ms_per_kb = 0.443
  intercept_ms    = 569

conservative_p90:
  slope_ms_per_kb = 1.061
  intercept_ms    = 355
```

These values come from Toni's Glamsterdam worst-case block-size analysis. In the
local copy of `worst_case_block.html`, the fits are:

```text
empirical p90    = 0.443 * kb + 569
conservative p90 = 1.061 * kb + 355
```

Interpretation:

- `empirical_p90` is the realistic p90 fit from the payload-deadline analysis.
- `conservative_p90` is a steeper sensitivity fit. It gives less byte budget for
  the same propagation window.
- `p90` means the 90th-percentile propagation estimate. It is not a hard maximum.

## Safety Factor

The safe byte cap is:

```text
usable_ms = window_ms * safety_factor
safe_bytes = ((usable_ms - intercept_ms) / slope_ms_per_kb) * 1024
```

`safety_factor = 0.75` means we only spend 75% of the nominal propagation window
on the modeled payload propagation time.

This is a deliberate haircut, not a measured constant. It leaves room for:

- model error in the linear propagation fit,
- network variance beyond p90,
- implementation overhead not captured by payload size alone,
- ePBS/attestation timing uncertainty,
- future BAL encoding or execution-payload details changing slightly.

The notebook also computes `safety_factor = 1.0`, which is the no-haircut case.
That should be treated as an upper bound, not the safer recommendation.

## Worst-Case Results

| gas limit | scenario | best strategy | calldata bytes | BAL bytes | total payload bytes | MiB | gas used |
|---:|---|---|---:|---:|---:|---:|---:|
| 60,000,000 | glamsterdam_no_8279 | mixed calldata + cold SLOADs | 937,150 | 685,460 | 1,622,610 | 1.547 | 60,000,000 |
| 60,000,000 | glamsterdam_plus_8279 | all calldata | 937,171 | 0 | 937,171 | 0.894 | 59,999,944 |
| 100,000,000 | glamsterdam_no_8279 | mixed calldata + cold SLOADs | 1,562,171 | 1,142,580 | 2,704,751 | 2.579 | 99,999,944 |
| 100,000,000 | glamsterdam_plus_8279 | all calldata | 1,562,171 | 0 | 1,562,171 | 1.490 | 99,999,944 |
| 150,000,000 | glamsterdam_no_8279 | mixed calldata + cold SLOADs | 2,343,421 | 1,714,004 | 4,057,425 | 3.869 | 149,999,944 |
| 150,000,000 | glamsterdam_plus_8279 | all calldata | 2,343,421 | 0 | 2,343,421 | 2.235 | 149,999,944 |
| 200,000,000 | glamsterdam_no_8279 | mixed calldata + cold SLOADs | 3,124,650 | 2,285,460 | 5,410,110 | 5.159 | 200,000,000 |
| 200,000,000 | glamsterdam_plus_8279 | all calldata | 3,124,671 | 0 | 3,124,671 | 2.980 | 199,999,944 |
| 300,000,000 | glamsterdam_no_8279 | mixed calldata + cold SLOADs | 4,687,171 | 3,428,308 | 8,115,479 | 7.740 | 299,999,944 |
| 300,000,000 | glamsterdam_plus_8279 | all calldata | 4,687,171 | 0 | 4,687,171 | 4.470 | 299,999,944 |
| 450,000,000 | glamsterdam_no_8279 | mixed calldata + cold SLOADs | 7,030,921 | 5,142,580 | 12,173,501 | 11.610 | 449,999,944 |
| 450,000,000 | glamsterdam_plus_8279 | all calldata | 7,030,921 | 0 | 7,030,921 | 6.705 | 449,999,944 |

The important result is the gap between the two scenarios. At 60M gas:

```text
no_8279 payload   = 1,622,610 bytes
plus_8279 payload =   937,171 bytes
```

So without the BAL-byte floor, mixed state-access workload can increase the
worst-case payload by roughly 73% over pure calldata at 60M gas.

## Propagation Safety Caps

Using `conservative_p90`:

| window ms | safety factor | safe bandwidth bytes |
|---:|---:|---:|
| 3,000 | 0.75 | 1,828,916 |
| 3,000 | 1.00 | 2,552,761 |
| 4,000 | 0.75 | 2,552,761 |
| 4,000 | 1.00 | 3,517,888 |
| 6,000 | 0.75 | 4,000,452 |
| 6,000 | 1.00 | 5,448,143 |

Notice that `3,000ms` at `1.0` equals `4,000ms` at `0.75`, because both give
`3,000ms` of usable propagation budget.

## Candidate EIP-7999 Bandwidth Limits

For now, the module maps byte caps to EIP-7999 gas using:

```text
bandwidth_gas_limit = 16 * safe_bandwidth_bytes
```

Candidate limits only:

| window ms | safety factor | safe bytes | bandwidth gas limit |
|---:|---:|---:|---:|
| 3,000 | 0.75 | 1,828,916 | 29,262,656 |
| 3,000 | 1.00 | 2,552,761 | 40,844,176 |
| 4,000 | 0.75 | 2,552,761 | 40,844,176 |
| 4,000 | 1.00 | 3,517,888 | 56,286,208 |
| 6,000 | 0.75 | 4,000,452 | 64,007,232 |
| 6,000 | 1.00 | 5,448,143 | 87,170,288 |

The target is intentionally omitted here. The target ratio controls fee-market
responsiveness and expected utilization, so it should be chosen later using
replay metrics such as volatility, excess accumulation, and limit-hit behavior.

## Historical 50-Block Compatibility

The current historical sample is:

```text
data/xatu_calldata_50_blocks_22886891_22886940.csv
```

It uses:

```text
include_reads = True
include_system_changes = True
```

Totals:

```text
blocks           = 50
calldata bytes   = 2,850,752
BAL bytes        = 4,580,589
bandwidth bytes  = 7,431,341
max block bytes  = 281,981 at block 22,886,907
```

For the representative cap:

```text
fit               = conservative_p90
window_ms         = 4,000
safety_factor     = 0.75
safe bytes        = 2,552,761
gas limit         = 40,844,176
```

Historical usage is far below the limit:

```text
max bandwidth bytes / limit  = 11.05%
mean bandwidth bytes / limit = 5.82%

max bandwidth gas / limit    = 9.16%
mean bandwidth gas / limit   = 4.71%
```

This 50-block sample is much too small to recommend final parameters, but it is
useful as a pipeline sanity check: real recent blocks are far below the
candidate propagation caps, while the adversarial no-8279 worst case can get
close enough to matter.

## Interpretation

The bandwidth-limit question has two separate parts:

1. What is the adversarial worst-case payload size under Glamsterdam? How does
   it change with different execution gas limits, with or without EIP-8279?
2. What byte payload is safe for propagation?

The first part is handled by `worst_case.py`. The second part is handled by
`propagation.py`. Then `eip7999_metering.py` maps the byte cap into a resource
gas limit.

The reason the first question still matters is that execution activity can also
produce payload bytes. A cold SLOAD consumes execution gas, but it also adds a
storage key to the BAL, and that BAL is part of the execution payload. So even
if the final EIP-7999 model has a separate bandwidth resource, the two
constraints interact:

```text
execution_gas_used <= execution_gas_limit
bandwidth_bytes    <= safe_bandwidth_bytes
```

For Glamsterdam without EIP-8279, the adversarial construction is mixed
calldata plus cold SLOADs. The transaction fills most of the byte floor with
calldata, while also using execution gas to create BAL bytes:

```text
cold SLOADs consume execution gas
cold SLOADs also produce BAL storage-key bytes
BAL bytes contribute to payload propagation
```

Under a 60M execution gas limit, the current simplified worst-case model finds:

```text
calldata bytes =   937,150
BAL bytes      =   685,460
total payload  = 1,622,610 bytes
```

With EIP-8279, BAL bytes also contribute to the 64 gas/byte floor accumulator.
That makes the mixed SLOAD strategy stop beating the pure calldata strategy. At
60M, the worst case collapses back to:

```text
calldata bytes = 937,171
BAL bytes      = 0
total payload  = 937,171 bytes
```

The reason to analyze this is that, under some execution gas limits and without
EIP-8279, a block can be valid under the execution gas limit while exceeding the
safe propagation cap. For example:

```text
100M execution gas, Glamsterdam without EIP-8279:
  worst-case payload = 2,704,751 bytes

conservative p90 cap, 4s window, 0.75 safety factor:
  safe payload cap = 2,552,761 bytes

conservative p90 cap, 3s window, 1.0 safety factor:
  safe payload cap = 2,552,761 bytes
```

So the 100M no-8279 worst case is larger than that propagation cap:

```text
2,704,751 > 2,552,761
```

Without a separate bandwidth resource, that block can still be considered valid
if it fits the execution gas limit. The propagation risk is not directly
represented as its own validity condition.

This is the motivation for EIP-7999 in this bandwidth setting. If calldata plus
BAL bytes are measured as a separate resource dimension with a gas limit derived
from the safe propagation cap, then the same block would fail the bandwidth
dimension:

```text
bandwidth = calldata + BAL bytes
bandwidth_gas_limit = 16 * safe_bandwidth_bytes
```

For the `2,552,761` byte cap, the corresponding bandwidth gas limit is:

```text
16 * 2,552,761 = 40,844,176
```

The 100M no-8279 worst-case payload would require:

```text
16 * 2,704,751 = 43,276,016 bandwidth gas
```

So with EIP-7999 it would be invalid on the bandwidth dimension, even if it
still fits the execution gas dimension.

The most important design implication so far is:

```text
For Glamsterdam, the bandwidth resource limit must account for mixed calldata
plus state-access BAL payloads.

If EIP-8279 goes together with EIP-7999, the worst-case payload is much easier
to reason about because calldata and BAL bytes both face the same 64 gas/byte
floor.
```

## Caveats

- The propagation fits are imported from Toni's analysis, not re-estimated here.
- The conservative fit is a sensitivity case, not a proof of worst-case network
  behavior.
- `safety_factor = 0.75` is a policy haircut. It should be varied, not treated
  as magic.
- The 50-block historical sample is only a small smoke test.
- The current worst-case model is intentionally simple: single transaction,
  cold account plus cold SLOADs, and raw byte payload accounting.

## Next Steps

- Add a larger historical replay sample.
- Decide whether the simulator's default safe cap should use `3s`, `4s`, or `6s`
  as the propagation window.
- Treat `0.75` as the conservative default and keep `1.0` as an upper-bound
  comparison.
- If the research question becomes final-parameter recommendation, re-estimate
  propagation fits directly from Xatu/relay data rather than inheriting the
  current fits.
