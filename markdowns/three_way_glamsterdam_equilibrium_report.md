# Glamsterdam Equilibrium Base Fees Under Three-Resource Demand

This report solves the shared Glamsterdam base fee for execution, data, and state demand. The central calculation uses the independent isoelastic elasticities recovered from previous report. The aggregate-plus-softmax model, calibrated with the state-excluded EIP-7623 estimate, is retained as a structural sensitivity.

The demand anchor and Glamsterdam metering multipliers come from a calibrated 120-day panel of February–May 2026.

## Main results

1. Repricing all activity observed during the 120 days gives multipliers of **1.538 for execution**, **1.969 for data**, and **5.656 for state**.
2. With the 35-day independent elasticities, the equilibrium shared base fee falls from **0.01000 gwei** at 100M to **0.000502 gwei** at 200M, **0.000258 gwei** at 250M, and **0.000149 gwei** at 300M. The 60M result is **0.55375 gwei**.
3. EIP-8038 and EIP-2780 repricing makes regular gas bind at 60M and 100M. State gas binds from 150M through 300M.
4. Across the 21-, 35-, and 60-day independent calibrations, the equilibrium ranges are **0.00442-0.01000 gwei** at 100M, **0.000245-0.00149 gwei** at 200M, **0.000110-0.000935 gwei** at 250M, and **0.000058-0.000639 gwei** at 300M.
5. The state-excluded EIP-7623 softmax sensitivity gives **0.01858**, **0.000314**, **0.000157**, and **0.000088 gwei** at the same four limits. It is a structural check, not the central estimate.


## Glamsterdam fee market

Glamsterdam retains one EIP-1559-style base fee but meters regular gas and state gas separately. For physical quantities $q_i$, the two metered branches are:

$$
g_{\mathrm{regular}}(b)
=m_{\mathrm{execution}}q_{\mathrm{execution}}(b)
+m_{\mathrm{data}}q_{\mathrm{data}}(b),
$$

$$
g_{\mathrm{state}}(b)
=m_{\mathrm{state}}q_{\mathrm{state}}(b),
$$

where $m_i$ is the metering multiplier of resource $i$.


The shared fee responds to the larger branch:

$$
u(b)=\max\left\{g_{\mathrm{regular}}(b),g_{\mathrm{state}}(b)\right\}.
$$

For gas limit $G$, the target is $T=G/2$. The equilibrium fee $b^*$ solves:

$$
\max\left\{g_{\mathrm{regular}}(b^*),g_{\mathrm{state}}(b^*)\right\}=T.
$$

| Gas limit | Shared target |
|---:|---:|
| 60M | 30M |
| 100M | 50M |
| 150M | 75M |
| 200M | 100M |
| 250M | 125M |
| 300M | 150M |

## Anchor: 4-month panel of Feb-May 2026

The anchor covers February 1 through May 31, 2026: 120 days and 860,505 blocks. Its reference base fee is the median of the daily median base fees, **0.1069 gwei**.

Gas accounting for three resources:
- Data is the calldata gas, including EIP-7623 floor bound.
- State is the calibrated scalable proxy expressed in historical gas-equivalent units.
- Execution is total current gas minus those data and state gas, so the three components sum to observed block gas.

| Resource | Current quantity per block | Share |
|---|---:|---:|
| Execution | 23.942M | 78.84% |
| Data | 1.181M | 3.89% |
| State | 5.244M | 17.27% |
| **Total** | **30.367M** | **100%** |

<!-- Using a recent common panel avoids combining demand from one period with metering ratios estimated from another. -->


## Why metering multipliers are required

The demand anchor is observed under the current gas schedule, whereas the Glamsterdam target is stated in Glamsterdam gas. Those units are not directly comparable. For example, the same state creation that is represented by one unit of the historical state-gas proxy consumes substantially more gas after EIP-8037 repricing. The multiplier converts between the two accounting conventions while holding the underlying activity fixed.

Let $q_i^0$ denote the current-regime gas-equivalent quantity of resource $i$ at the historical anchor. For the same transactions and state creation, let $g_i^G$ denote the gas charged under Glamsterdam. The metering multiplier is:

$$
m_i =
\frac{g_i^G}{q_i^0}.
$$

The multiplier enters the equilibrium calculation in two places. First, at a candidate shared base fee $b$, one unit of the historical activity costs $m_i b$ under the new gas schedule. Its effective price relative to the anchor is therefore:

$$
r_i(b)=m_i\frac{b}{b_{\mathrm{ref}}}.
$$

Demand responds to this price ratio. Second, the resulting physical demand is converted back into the gas counted against the Glamsterdam target:

$$
q_i(b)=q_i^0r_i(b)^{-\epsilon_i},
\qquad
g_i(b)=m_iq_i(b).
$$

<!-- Without $m_i$, the model would assume that every activity consumes the same gas before and after repricing. It would understate both the price users face for heavily repriced activity and the amount that activity contributes to the fee-market target. A multiplier is consequently an accounting conversion. -->

## How the multipliers are chosen

To calculate each multiplier, we replay the same February–May 2026 activity under Glamsterdam gas accounting rules.

$$
m_i =
\frac{\sum_t g_{i,t}^{Glamsterdam}}
{\sum_t q_{i,t}^{0}}.
$$

For each resource, the numerator sums counterfactual gas across all 120 days and the denominator sums historical gas across the same days. We do not average daily multipliers. A day with more activity therefore contributes more gas to both totals automatically.

The multiplier for each resource is listed as follows:

| Resource | Central multiplier | Selection rule |
|---|---:|---|
| Execution | 1.538 | Replay the observed opcode and transaction paths under EIP-8038 and EIP-2780, reconstruct the EIP-8038 refund counter across the full 120-day Xatu range, and reapply the transaction-level 20% refund cap. |
| Data | 1.969 | Reprice the observed current-data quantity using the transaction-specific EIP-7976 uplift and the calibrated EIP-7981 transaction-access-list surcharge. |
| State | 5.656 | Apply the EIP-8037 byte accounting and `CPSB = 1530` to the same state creation represented by the historical proxy. |


### Execution under EIP-8038 and EIP-2780

The execution multiplier comes from EIP-8038 and EIP-2780, which change the pricing of state access and intrinsic gas.
The largest contribution is storage-write repricing: EIP-8038 changes the regular first-write charge from 2,800 to 10,000 gas and the cold storage access charge from 2,100 to 3,000 gas. EIP-2780 partly offsets this increase because its sender component is 12,000 rather than 21,000, with recipient and value-transfer charges added according to each transaction path.

| Execution accounting | Gas per block |
|---|---:|
| Current regular execution gas | 23.942M |
| EIP-8038 SSTORE increase | +11.687M |
| EIP-8038 cold SLOAD increase | +2.082M |
| Other EIP-8038 changes | +0.635M |
| EIP-2780 intrinsic-gas changes | −1.033M |
| Counterfactual gas before refund correction | 37.312M |
| Additional effective EIP-8038 refunds | −0.492M |
| **Refund-corrected counterfactual execution gas** | **36.821M** |

Thus:

$$
m_{\mathrm{execution}}
=\frac{36.821}{23.942}
=1.5379.
$$

Refunds are reconstructed for all 67.64 million refund-positive transactions in the 120-day range. The integer reconstruction identifies 99.82% of the observed refund counter; the remainder receives the same daily correction rate as the identified transactions. The refund calculation itself is Xatu-only. Small access-list and authorization-write components retain the existing RPC calibration because Xatu does not expose their complete transaction contents.

### Data under EIP-7976 and EIP-7981

For the same observed blocks, Glamsterdam data gas is constructed as:

| Component | Gas per block |
|---|---:|
| Current EIP-7623 data gas | 1.181M |
| EIP-7976 floor uplift | 0.776M |
| Calibrated EIP-7981 access-list gas | 0.368M |
| **Glamsterdam data gas** | **2.324M** |

The data multiplier is therefore:

$$
m_{\mathrm{data}}
=\frac{2.324}{1.181}
=1.969.
$$

<!-- The EIP-7981 term uses the calibrated access-list estimator because exact RPC/RLP reconstruction for every block would be unnecessarily expensive. It changes the accounting cost, not the observed physical demand. -->

The EIP-7976 uplift is calculated transaction by transaction:

$$
\Delta g_{7976,tx} =
\max\left\{0,\ 64B_{tx}-g_{\mathrm{body},tx}^{\mathrm{current}}\right\}.
$$

We identify 19.90 million of 270.78 million transactions, or **7.35%**, as binding under the EIP-7976 floor. Together, these transactions add 0.776M gas per block, equal to **65.7% of current data gas**. This does not mean that every transaction's calldata cost rises by 65.7%. A minority of calldata-heavy transactions accounts for the entire increase. Meanwhile, EIP-7981 adds the specified data charge to transaction access-list bytes.

### State under EIP-8037

The state proxy remains the scalable measure of physical state creation. We then price the same estimated account, storage, and code creation using the EIP-8037 state-gas schedule with `CPSB = 1530`.

| Accounting convention | State gas per block |
|---|---:|
| Historical gas-equivalent proxy | 5.244M |
| EIP-8037 state gas for the same activity | 29.663M |

Hence:

$$
m_{\mathrm{state}}
=\frac{29.663}{5.244}
=5.656.
$$

## Central demand model: independent isoelastic curves

The central model assumes three independent demands:

$$
q_i(b)=q_i^0\left(m_i\frac{b}{b_{\mathrm{ref}}}\right)^{-\epsilon_i}.
$$

| Event window | $\epsilon_{\mathrm{execution}}$ | $\epsilon_{\mathrm{data}}$ | $\epsilon_{\mathrm{state}}$ |
|---:|---:|---:|---:|
| 21 days | 0.117 | 0.202 | 0.478 |
| **35 days** | **0.121** | **0.229** | **0.335** |
| 60 days | 0.082 | 0.205 | 0.280 |

Each resource responds to its own effective price.

## Headline equilibrium results

The central accounting uses $m_{\mathrm{execution}}=1.538$, $m_{\mathrm{data}}=1.969$, and $m_{\mathrm{state}}=5.656$.

| Demand model | Gas limit | Target | Equilibrium base fee | 0.1069 gwei anchor fraction | Regular metered gas | State metered gas | Binding branch |
|---|---:|---:|---:|---:|---:|---:|---:|
| Independent isoelastic | 60M | 30M | **0.553747 gwei** | 517.9% | **30.00M** | 9.57M | Regular |
| Independent isoelastic | 100M | 50M | **0.009999 gwei** | 9.35% | **50.00M** | 36.71M | Regular |
| Independent isoelastic | 200M | 100M | **0.000502 gwei** | 0.469% | 73.73M | **100.00M** | State |
| Independent isoelastic | 250M | 125M | **0.000258 gwei** | 0.241% | 80.49M | **125.00M** | State |
| Independent isoelastic | 300M | 150M | **0.000149 gwei** | 0.140% | 86.49M | **150.00M** | State |



### Event-window sensitivity
| Gas limit | Event window | Equilibrium fee | Binding branch | Physical state share |
|---:|---:|---:|---|---:|
| 60M | 21 days | 0.606886 gwei | Regular | 4.9% |
| 60M | **35 days** | **0.553747 gwei** | Regular | 8.1% |
| 60M | 60 days | 1.404795 gwei | Regular | 7.5% |
| 100M | 21 days | 0.009175 gwei | Regular | 18.8% |
| 100M | **35 days** | **0.009999 gwei** | Regular | 16.9% |
| 100M | 60 days | 0.004418 gwei | Regular | 19.8% |
| 200M | 21 days | 0.001491 gwei | State | 30.7% |
| 200M | **35 days** | **0.000502 gwei** | State | 27.3% |
| 200M | 60 days | 0.000245 gwei | State | 29.9% |
| 250M | 21 days | 0.000935 gwei | State | 34.3% |
| 250M | **35 days** | **0.000258 gwei** | State | 30.1% |
| 250M | 60 days | 0.000110 gwei | State | 33.1% |
| 300M | 21 days | 0.000639 gwei | State | 37.4% |
| 300M | **35 days** | **0.000149 gwei** | State | 32.5% |
| 300M | 60 days | 0.000058 gwei | State | 35.8% |

The 200M, 250M, and 300M calculations extrapolate progressively farther from the anchor and are consequently more sensitive to the recovered state elasticity.

![Glamsterdam equilibrium fees and state share across gas limits](../plots/three_way_equilibrium_gas_limit_curves_2026-02-01_2026-06-01.png)

> The left panel reports the equilibrium shared base fee on a log scale; the blue points use the central 35-day independent elasticities, the blue band spans the 21-, 35-, and 60-day calibrations, and the green line is the state-excluded EIP-7623 softmax sensitivity. The right panel shows that the physical state share rises as capacity expands, consistent with the equilibrium switching from the regular-gas branch at 60M and 100M to the state branch from 150M onward.


## Which branch determines the equilibrium

The binding branch is the branch that reaches the shared target first as the base fee adjusts. For the independent model, metered demand can be written as:

$$
g_i(b)
=q_i^0m_i^{1-\epsilon_i}
\left(\frac{b}{b_{\mathrm{ref}}}\right)^{-\epsilon_i}.
$$

The multiplier has two opposing effects. It makes each unit of activity consume more metered gas, but it also raises the effective price $m_i b$ and reduces physical demand. State metered gas therefore scales with $m_{\mathrm{state}}^{1-\epsilon_{\mathrm{state}}}$ rather than directly with $m_{\mathrm{state}}$. With $m_{\mathrm{state}}=5.656$ and $\epsilon_{\mathrm{state}}=0.335$, the net factor at the reference fee is about $5.656^{0.665}=3.17$. The multiplier does not represent 5.656 times more physical state capacity.

State also starts from a much smaller historical quantity than execution. At the reference fee, after both metering and demand response, the 35-day independent model gives:

| Resource or branch | Metered gas at the reference fee |
|---|---:|
| Execution | 34.95M |
| Data | 1.99M |
| **Regular branch** | **36.94M** |
| **State branch** | **16.60M** |

At the 60M limit, the target is 30M. Regular gas is already above the target at the reference fee, whereas state gas is below it. The fee therefore rises until regular gas falls to 30M; state gas falls to 9.57M.

At the 100M limit, the target is 50M. Lowering the fee expands both branches, but regular gas starts much closer to the target and reaches 50M while state gas is still 36.71M. At still lower fees, state demand grows faster because $\epsilon_{\mathrm{state}}=0.335$ exceeds $\epsilon_{\mathrm{execution}}=0.121$. State consequently becomes binding at 150M and remains binding through 300M.

| Gas limit | Target | Equilibrium regular gas | Equilibrium state gas | Binding branch |
|---:|---:|---:|---:|---|
| 60M | 30M | **30.00M** | 9.57M | Regular |
| 100M | 50M | **50.00M** | 36.71M | Regular |
| 150M | 75M | 65.90M | **75.00M** | State |
| 200M | 100M | 73.73M | **100.00M** | State |
| 250M | 125M | 80.49M | **125.00M** | State |
| 300M | 150M | 86.49M | **150.00M** | State |

Once state is the binding branch, the independent-model condition is:

$$
T=m_{\mathrm{state}}q_{\mathrm{state}}^0
\left(m_{\mathrm{state}}\frac{b^*}{b_{\mathrm{ref}}}\right)^{-\epsilon_{\mathrm{state}}},
$$

so:

$$
\frac{b^*}{b_{\mathrm{ref}}} =
\left(
\frac{q_{\mathrm{state}}^0m_{\mathrm{state}}^{1-\epsilon_{\mathrm{state}}}}
{T}
\right)^{1/\epsilon_{\mathrm{state}}}.
$$

For $\epsilon_{\mathrm{state}}=0.335$, $b^*\propto T^{-2.986}$ and $b^*\propto m_{\mathrm{state}}^{1.986}$. Regular gas remains below the target at 200M, 250M, and 300M, so the state branch determines all three high-capacity fees.

## Interpretation

The 60M result is above the historical fee anchor because regular execution is substantially repriced and the 30M target is below the model's 36.94M regular-gas quantity at the reference fee. At 100M, the target is higher and the equilibrium fee falls to 9.35% of the historical anchor. The corresponding effective execution price, including the 1.538 multiplier, is 14.4% of its historical price.

At 200M, state activity is first repriced by the 5.656 multiplier, but the shared fee falls enough that its effective state price is about 2.65% of the historical anchor price.

The 200M, 250M, and 300M results require physical state demand of 17.68M, 22.10M, and 26.52M historical gas-equivalent units per block, respectively. These are 3.37, 4.21, and 5.06 times the 5.24M anchor, so the results should be read as internal fixed points of the calibrated curve rather than evidence that activity will immediately expand by those amounts.

The independent and softmax calculations answer different behavioral questions. The independent model asks how each activity changes with its own effective price. The softmax sensitivity additionally allows relative prices to reallocate demand among resources. Their difference measures dependence on the demand structure, not sampling error.

## Measurement limitation

The main empirical limitation is state measurement. Execution and current data gas come from protocol accounting, while physical state creation is inferred from a calibrated proxy and then translated into EIP-8037 gas. Bias in that proxy can affect the state anchor, the recovered state elasticity, and the equilibrium fee when state binds, as it does from 150M through 300M. The 120-day panel improves coverage, but it does not turn the proxy into direct protocol measurement.

The independent-demand structure, the isoelastic extrapolation, and the use of a long-run fixed point are explicit modeling assumptions. They define what the calculation means; they are not additional measurement failures.

## Appendix: data sources and construction details

The main calculations use Xatu for the full February-May 2026 range and a deterministic **5,997-block** sample from the Ethnodeops Erigon mainnet RPC where complete transaction objects or account-level traces are required.

### Execution multiplier

| Xatu table | Fields used in the execution replay |
|---|---|
| `default.canonical_execution_block` | Canonical block numbers, dates, and block gas totals |
| `default.canonical_execution_transaction_structlog_agg` | Opcode counts and gas, cold-access counts, SSTORE gas, and transaction refund counters |
| `default.canonical_execution_traces` | Successful internal contract creation and positive-value `CALL`/`CALLCODE` paths |
| `default.execution_transaction` | Transaction type, recipient, value, contract-creation status, calldata counts, and type-4 transactions |
| `default.canonical_execution_transaction` | Receipt gas used |
| `default.canonical_execution_storage_diffs` | Final storage changes used to reconstruct EIP-8038 refunds |

Xatu does not expose complete access-list contents or authorization lists. Those terms use `data/calibration_rpc_state_access_auth_blocks_2026-02-01_2026-06-01.csv`. The RPC pull uses `debug_traceBlockByNumber` with `prestateTracer` and `diffMode=true`, `eth_getBlockReceipts`, and `eth_getBlockByNumber(..., true)` to supply access-list address and storage-key counts and authorization-write counts.

### Data multiplier

| Source | Fields used in the data replay |
|---|---|
| Xatu `default.canonical_execution_transaction` | Receipt gas and zero/nonzero calldata byte counts for current EIP-7623 gas and the transaction-level EIP-7976 calculation |
| Xatu `default.canonical_execution_block` | Canonical block dates and block coverage |
| Ethnodeops Erigon RPC sample | Full access lists used to RLP encode addresses, storage keys, bytes, and the EIP-7981 charge |

Only `eth_getBlockByNumber(..., true)` is needed for the access-list byte calculation; the trace and receipt calls used elsewhere in the calibration file do not enter this multiplier.

### State multiplier

| Source | Fields used in the state replay |
|---|---|
| Xatu `default.canonical_execution_storage_diffs` | Newly created storage slots |
| Xatu `default.canonical_execution_contracts` | Contract accounts and code bytes |
| Xatu `default.canonical_execution_balance_diffs` and `default.canonical_execution_nonce_diffs` | New-account candidates |
| Xatu `default.canonical_execution_address_appearances` | First-seen account filter |
| Xatu `default.canonical_execution_block` | Dates and block coverage |
| CBT `mainnet.int_execution_state_size_by_block` and `mainnet.int_execution_block_by_date` | Inventory checks only; these tables do not determine the multiplier |
| Ethnodeops Erigon RPC sample | Account-proxy correction and delegation indicators |

For the RPC correction, `debug_traceBlockByNumber` with `prestateTracer` and `diffMode=true` supplies pre/post account and storage changes, `eth_getBlockReceipts` identifies successful transactions, and `eth_getBlockByNumber(..., true)` supplies full transaction objects and authorization lists. The corrected counts are priced under the historical schedule and EIP-8037 with `CPSB = 1530`.
