# Data Metering and BAL Bundle Pricing Under EIP-7999

[EIP-7928](https://github.com/ethereum/EIPs/blob/master/EIPS/eip-7928.md) specifies Block-Level Access Lists (BALs) for Glamsterdam. Glamsterdam leaves BALs outside fee accounting. Under EIP-7999, BALs become part of the data resource and consume data gas. Transaction execution generates BAL through state creation and access to existing state.

The fee model uses the transaction-local runtime byte counter specified by [EIP-8279](https://eips.ethereum.org/EIPS/eip-8279). We convert this counter and observed transaction content into the universal 16-data-gas-per-byte accounting assumed by this counterfactual extension. All empirical anchors use the 120 days from February 1 through May 31, 2026.

At the historical anchor, runtime BAL is **47.4%** of total data gas. How it responds to the data fee therefore decides most of what the data market does, and it is the hardest response in the model to pin down, because BAL is the one resource nobody demands. This report meters the data resource, measures where BAL bytes come from, and then gives BAL a demand model derived from the price of the activity that produces it.

The report covers metering and demand only. Equilibrium base fees under this model are solved separately, so the demand model can be reused without carrying one particular set of capacity scenarios with it.

The main results are:

1. Static-data accounting, including calldata, transaction access lists, authorization tuples and their EIP-8279 static BAL entries, and blob-versioned hashes, is **2.133559 million data gas per block**, giving a metering multiplier of **1.807251** relative to current EIP-7623 data gas.
2. The EIP-8279 runtime-meter anchor is **119,944 bytes per block**, or **1.919100 million data gas per block** at 16 data gas per runtime byte. Including it raises the data multiplier from 1.807251 to **3.432842**.
3. The transaction-level reconstruction over 6,000 sampled blocks separates runtime BAL into **11.394%** matched directly to state creation, **37.879%** of access bytes co-produced by state-creating transactions, and **50.727%** produced by transactions with no observed state creation.
4. Runtime-BAL demand is induced by parent execution and state activity, and its data charge enters
   the price those activities pay. At $\lambda=0$, each historical unit of execution activity
   produces $w_{\mathrm{execution}}=0.071023$ units of BAL data gas and each historical unit of state
   activity produces $w_{\mathrm{state}}=0.041695$. BAL's response to the data fee follows from
   the previously estimated parent elasticities applied to the BAL-inclusive parent prices.
5. Relative to each resource's own metered charge, the BAL charge is **4.62%** of what execution pays but only **0.74%** of what state pays. The gap is EIP-8037 metering, which prices state gas at 5.66× against execution's 1.54×.
6. The runtime decomposition measures the direct-state, co-produced, and non-state BAL shares. It
   does not identify how co-produced access responds when execution and state prices move
   independently. The central resource-based specification sets $\lambda=0$; values 0.5 and 1 are
   retained as structural coupling sensitivities rather than estimated parameter values.

## Notation

| Group | Notation | Meaning |
|---|---|---|
| Activity | $q_{\mathrm{execution}}$, $q_{\mathrm{state}}$, $q_{\mathrm{data}}$ | Execution activity, state-creating activity, and static transaction content, in historical gas-equivalent units |
| Anchors | $q_i^0$, $g_{\mathrm{static}}^0$, $g_{\mathrm{BAL}}^0$, $p^0$ | Historical activity per block, the static-data and runtime-BAL gas anchors, and the historical common-price anchor |
| Metering | $m_{\mathrm{execution}}$, $m_{\mathrm{state}}$, $m_{\mathrm{data,static}}$ | EIP-7999 metering multipliers |
| Base fees | $b_{\mathrm{execution}}$, $b_{\mathrm{state}}$, $b_{\mathrm{data}}$ | Protocol base fees |
| Parent prices | $P_{\mathrm{execution}}$, $P_{\mathrm{state}}$ | BAL-inclusive price of one historical unit of parent activity |
| BAL intensities | $w_{\mathrm{execution}}(\lambda)$, $w_{\mathrm{state}}(\lambda)$ | Data gas mechanically produced per historical unit of parent activity |
| BAL attribution | $\omega_{\mathrm{state-only}}$, $\omega_{\mathrm{coproduced}}$, $\omega_{\mathrm{nonstate}}$, $\lambda$ | Measured runtime-BAL shares and the maintained co-produced allocation assumption |
| Demand response | $\epsilon_{\mathrm{execution}}$, $\epsilon_{\mathrm{data}}$, $\epsilon_{\mathrm{state}}$ | Own-price elasticities |

Superscript $0$ denotes the historical anchor.


## Estimating EIP-8279 runtime-metered BAL bytes

[EIP-8279](https://eips.ethereum.org/EIPS/eip-8279) defines a per-transaction `bal_data_bytes` counter. It adds fixed byte amounts for cold account and storage access, storage values that differ from their pre-transaction value, value-bearing calls and self-destructs, internal contract creation, and deployed code.

These protocol-event counts are available from Xatu for the wider block panel. The block-level estimator is:

$$
\begin{aligned}
\widehat M_{\mathrm{BAL},k}={}&
20N_{\mathrm{cold\ account},k}
+32N_{\mathrm{cold\ storage},k}
+32N_{\mathrm{changed\ value},k} \\
&+32N_{\mathrm{value\ call},k}
+32N_{\mathrm{selfdestruct},k}
+28N_{\mathrm{create},k} \\
&+32N_{\mathrm{endowed\ create},k}
+\mathrm{codeBytes}_k,
\end{aligned}
$$

where $k$ indexes blocks. Each internal `CREATE` or `CREATE2` counted by the runtime meter adds 28 bytes: 20 bytes for the new contract address and 8 bytes for its nonce. If the creation also transfers ETH to the new contract, the meter adds another 32 bytes for the contract's initial balance.

We reconstruct transaction-level runtime BAL for 6,000 sampled blocks from February through May 2026, using 50 blocks per day. Daily sample means are weighted by the actual number of canonical blocks in each day.

| Priced BAL quantity at the historical anchor | Estimate |
|---|---:|
| EIP-8279 runtime counter | **119,944 bytes per block** |
| EIP-7999 data gas at 16 gas per runtime byte | **1.9191M gas per block** |
> Xatu's storage-diff table contains changes that remain after the transaction finishes. EIP-8279 retains a 32-byte meter charge when a reverted call temporarily changes a storage value; the final Xatu diff contains no corresponding entry. The reconstruction may therefore understate this specific source of runtime bytes.

EIP-8279 includes the runtime BAL counter in the transaction floor at 64 gas per byte. Under the EIP-7999 counterfactual, runtime BAL becomes a data-resource component. In this report, we assume 16 data gas per runtime byte; the final protocol value remains to be specified.


## Static-data metering in the EIP-7999 counterfactual

The current EIP-7999 draft removes the EIP-7623 floor while retaining calldata tokens, equivalent to 4 gas per zero byte and 16 per nonzero byte. This project's broader EIP-8131/EIP-8279-style bandwidth counterfactual instead meters every encoded byte at 16 gas and adds the specified static-data fields. The accounting bridge below reports both steps so that the broader counterfactual is not attributed to the base EIP-7999 draft.

Let $q_{\mathrm{data}}^0$ be current EIP-7623 data gas and let $g_{\mathrm{static}}^0$ be the gas assigned to the same static transaction content under the EIP-7999 counterfactual. The static-data metering multiplier is:

$$
m_{\mathrm{data,static}}
=\frac{g_{\mathrm{static}}^0}{q_{\mathrm{data}}^0}.
$$

The current anchor is $q_{\mathrm{data}}^0=1.180555$M gas per block. Removing the EIP-7623 floor while retaining 4/16 calldata, as in the current EIP-7999 draft, reduces the same transaction content to 1.032928M gas per block. The counterfactual then meters every calldata byte at 16 data gas and adds access-list content bytes, authorization tuples, and blob-versioned hashes. EIP-8279 also adds 51 static BAL bytes for every authorization: 20 bytes for the authority address, 23 for its delegation code, and 8 for its nonce. These bytes are part of the static authorization charge rather than the runtime BAL counter.

| Accounting step | Data gas per block | Change from previous step | Ratio to current EIP-7623 |
|---|---:|---:|---:|
| Current EIP-7623: 4/16 calldata plus floor uplift | 1.180555M | — | 1.000000 |
| Remove EIP-7623 floor; retain 4/16 calldata | 1.032928M | −0.147627M | 0.874952 |
| Meter every calldata byte at 16 gas | 2.008813M | +0.975884M | 1.701583 |
| Add sampled access-list bytes | 2.100737M | +0.091924M | 1.779448 |
| Add sampled authorization-tuple bytes | 2.121778M | +0.021042M | 1.797272 |
| Add 51 static BAL bytes per authorization | 2.131715M | +0.009936M | 1.805688 |
| Add 32-byte blob-versioned hashes | **2.133559M** | **+0.001844M** | **1.807251** |

The static-data metering multiplier is therefore:

$$
m_{\mathrm{data,static}}
=\frac{2.133559}{1.180555}
=1.807251.
$$

The static component uses the independently estimated historical data elasticity. Its effective price ratio is:

$$
r_{\mathrm{data}}(b_{\mathrm{data}})
=m_{\mathrm{data,static}}\frac{b_{\mathrm{data}}}{p^0}
=\frac{b_{\mathrm{data}}}{b_{\mathrm{data}}^0},
\qquad
b_{\mathrm{data}}^0=\frac{p^0}{m_{\mathrm{data,static}}}.
$$

Static data demand is therefore:

$$
g_{\mathrm{static}}(b_{\mathrm{data}})
=g_{\mathrm{static}}^0
r_{\mathrm{data}}(b_{\mathrm{data}})^{-\epsilon_{\mathrm{data}}},
\qquad
g_{\mathrm{static}}^0=2.133559\text{M},
\qquad
\epsilon_{\mathrm{data}}=0.229476.
$$

![daily_data_resource_components_runtime_8279_2026-02-01_2026-06-01](https://hackmd.io/_uploads/r1k86tI4Me.png)

> Total data byte composition at the historical anchor under EIP-7999.

## Separating BAL bytes between state creation and execution

BAL gas is a weighted combination of execution and state demand responses, with an additional unidentified response to the data price.

An important note is that a state-creating transaction also reads and modifies existing state. For example, a transaction may read existing slots before it creates a new slot. For such a transaction, the BAL bytes it creates can be related to both state creation and execution. **Therefore, the question is whether these execution-related BAL bytes of a state-creating transaction should respond to state demand or execution demand.**

This question concerns the parent-activity term $\widetilde g_{\mathrm{BAL}}$ and is therefore common to both models; the data-fee response is applied afterwards. One step further from state and execution, that term decomposes into three parts:

$$
\widetilde g_{\mathrm{BAL}}
=\widetilde g_{\mathrm{state-only}}
+\widetilde g_{\mathrm{coproduced}}
+\widetilde g_{\mathrm{nonstate}}.
$$

- $\widetilde g_{\mathrm{state-only}}$ is the BAL from state-creation activity that responds only to state demand, e.g., new storage slots, new accounts, or deployed code.
- $\widetilde g_{\mathrm{coproduced}}$ is the BAL from state-access (execution) activity that is related to state-creating transactions.
- $\widetilde g_{\mathrm{nonstate}}$ is the BAL from non-state-creation activity that responds only to execution demand.

Let $\lambda \in [0, 1]$ be a parameter that determines the fraction of the coproduced BAL gas responds to state demand, and $1-\lambda$ is the fraction of coproduced BAL gas responds to execution demand. Therefore, a richer model of BAL demand can be:

$$
\begin{align}
\frac{\widetilde g_{\mathrm{BAL}}}
{g_{\mathrm{BAL}}^0} = &
\;\omega_{\mathrm{state-only}}
r_{\mathrm{state}}(b_{\mathrm{state}})^{-\epsilon_{\mathrm{state}}}
\\ & +\omega_{\mathrm{coproduced}}[\lambda r_{\mathrm{state}}(b_{\mathrm{state}})^{-\epsilon_{\mathrm{state}}} + (1-\lambda)r_{\mathrm{execution}}
(b_{\mathrm{execution}})^{-\epsilon_{\mathrm{execution}}}]
\\ & +\omega_{\mathrm{nonstate}} r_{\mathrm{execution}}
(b_{\mathrm{execution}})^{-\epsilon_{\mathrm{execution}}}.
\end{align}
$$



The $\omega$ shares are measured directly from the decomposition; only their behavioral routing $\lambda$ is unresolved.

By decomposing the 6,000 sampled blocks, we get the following results:

| Runtime-meter group | Runtime BAL bytes | Share of runtime BAL |
|---|---:|---:|
| state creation | 81.997M | $\omega_{\mathrm{state-only}} = 11.394\%$|
| Co-produced access in state-creating transactions | 272.603M | $\omega_{\mathrm{coproduced}} = 37.879\%$ |
| non-state execution | 365.066M | $\omega_{\mathrm{nonstate}} = 50.727\%$ |
| **Total** | **719.666M** | **100.000%** |

>The co-produced group measures BAL bytes created by storage and account access that the transaction performs alongside state creation.

![bal_runtime_8279_three_way_components_2026-02-01_2026-06-01](https://hackmd.io/_uploads/rk8CMUC4Gx.png)
> Runtime-meter components across the 6,000-block panel. The first panel reports each component's contribution to total BAL bytes. The second separates direct state creation, co-produced access in state-creating transactions, and bytes from transactions with no observed state creation.

### Co-produced access inside state-creating transactions

The allocation parameter $\lambda$ determines how the co-produced component is routed:

- $\lambda=0$ attaches co-produced access to execution/access activity;
- $\lambda=1$ attaches it to state activity; and
- $\lambda=0.5$ is an intermediate structural sensitivity.

The central resource-based specification sets $\lambda=0$. Runtime bytes directly matched to state
creation follow state activity, while access-related BAL remains attached to the execution/access
activity in which it is generated. This convention is consistent with the independent resource
demand curves used throughout the analysis. The runtime decomposition identifies the three
$\omega$ shares, but it does not estimate $\lambda$.

## BAL demand model

### Why BAL cannot have a demand curve of its own

For every other resource, the user can decide how much the transaction consumes, e.g., calldata, compute, and state. Runtime BAL is different because it is assembled by the protocol from accounts and slots a transaction touches. The user does not request it, and cannot buy less of it without doing less of BAL creating activity.

This also removes the usual way of estimating a response. The demand curves in this study come from the three 2025 gas-limit changes, which moved the shared base fee and let us watch quantities react. BAL carried no per-byte fee then, so there is no price variation in the historical record from which to recover a BAL demand curve. Its charge is genuinely new until introduced by EIP-7999.

The way through is to stop treating BAL as something that is demanded. Consider the following toy example: A customer goes to a restaurant because they value the food. However, eating the meal also creates serving work, so the final bill includes both the menu price and a mandatory service charge. The customer decides whether to order based on the total bill. If the service charge rises enough, some customers stop ordering; both the meal and its associated service work disappear.

Similarly, BAL bytes appear because of its parent execution and state activity. If a user undertakes $q$ units of execution activity and that mechanically produces $w\,q$ units of BAL data gas, then under EIP-7999 the user pays $m_{\mathrm{execution}}b_{\mathrm{execution}}q$ on execution and $w\,b_{\mathrm{data}}q$ on data. Only the total fee enters the decision of whether to transact. So BAL needs no demand curve of its own — the price of its parents simply has a second term in it.


### BAL Intensities

The measured attribution converts into data gas produced per historical unit of parent activity:

$$
w_{\mathrm{e}}(\lambda)=\frac{\omega_{\mathrm{execution}}(\lambda)\,g_{\mathrm{BAL}}^0}{q_{\mathrm{e}}^0},
\qquad
w_{\mathrm{s}}(\lambda)=\frac{\omega_{\mathrm{state}}(\lambda)\,g_{\mathrm{BAL}}^0}{q_{\mathrm{s}}^0},
$$

with $\omega_{\mathrm{state}}=\omega_{\mathrm{state-only}}+\lambda \omega_{\mathrm{coproduced}}$ and $\omega_{\mathrm{execution}}=\omega_{\mathrm{nonstate}}+(1-\lambda)\omega_{\mathrm{coproduced}}$.

| $\lambda$ | $w_{\mathrm{e}}$ | $w_{\mathrm{s}}$ | $w_{\mathrm{e}}/m_{\mathrm{e}}$ |
|---:|---:|---:|---:|
| **0** | **0.071023** | **0.041695** | **0.046182** |
| 0.5 | 0.055842 | 0.111005 | 0.036310 |
| 1 | 0.040661 | 0.180314 | 0.026439 |

Let $R_{\mathrm{execution}}=q_{\mathrm{execution}}/q_{\mathrm{execution}}^0$. Existing-state access is approximated by:

$$
\frac{A}{A^0}=R_{\mathrm{execution}}^{\rho_A}.
$$

The execution-linked BAL component and its average intensity are therefore:

$$
g_{\mathrm{BAL,execution}}
=w_{\mathrm{execution}}q_{\mathrm{execution}}^0
R_{\mathrm{execution}}^{\rho_A},
\qquad
\bar w_{\mathrm{execution}}(R_{\mathrm{execution}})
=w_{\mathrm{execution}}R_{\mathrm{execution}}^{\rho_A-1}.
$$

The central case sets $\rho_A=1$, which keeps access intensity constant as execution scales. The sensitivity values $\rho_A=0.75$ and $1.25$ allow the intensity to fall or rise. All three specifications pass through the same historical BAL anchor because $R_{\mathrm{execution}}=1$ there.

The BAL-inclusive execution price uses the average intensity
$\bar w_{\mathrm{execution}}$. This matches the aggregate demand index and the observed average BAL
per historical execution unit, and it preserves the measured anchor charge for every $\rho_A$.

Expressed per unit of metered EIP-7999 execution gas rather than per historical unit, $w_{\mathrm{execution}}/m_{\mathrm{execution}}=0.0462$ at $\lambda=0$: each additional unit of execution gas brings 4.6% of a unit of BAL data gas with it.

The two intensities differ far more than the attribution shares alone suggest, because they are divided by different anchors. Relative to each resource's own metered charge, BAL is **4.62%** of what execution pays but only **0.74%** of what state pays. The gap is EIP-8037 metering, which prices state gas at 5.66× against execution's 1.54×: creating state is expensive in gas, and the accesses that accompany it are not.


### BAL-inclusive parent prices

Each parent activity is priced at its own metered charge plus the average BAL charge that activity mechanically generates:

$$
P_{\mathrm{execution}}
=m_{\mathrm{execution}}b_{\mathrm{execution}}+w_{\mathrm{execution}}b_{\mathrm{data}},
\qquad
P_{\mathrm{state}}
=m_{\mathrm{state}}b_{\mathrm{state}}+w_{\mathrm{state}}b_{\mathrm{data}} .
$$

Static transaction content keeps its own price, $m_{\mathrm{data,static}}b_{\mathrm{data}}$.

These are **BAL-inclusive parent prices**. Their scope covers the parent-resource charge and assigned
runtime-BAL charge. Static data carried by the same transactions and execution gas carried by
state-creating transactions remain outside them.

### The demand curves

Execution and state demand keep the functional form and the estimated elasticities from the resource-elasticity report. What changes is the price at which each curve is evaluated:

$$
q_{\mathrm{execution}}
=q_{\mathrm{execution}}^0
\left(\frac{P_{\mathrm{execution}}}{p^0}\right)^{-\epsilon_{\mathrm{execution}}},
\qquad
q_{\mathrm{state}}
=q_{\mathrm{state}}^0
\left(\frac{P_{\mathrm{state}}}{p^0}\right)^{-\epsilon_{\mathrm{state}}} .
$$

Runtime BAL is then whatever the realized parent activity produces:

$$
g_{\mathrm{BAL}}
=w_{\mathrm{execution}}q_{\mathrm{execution}}^0R_{\mathrm{execution}}^{\rho_A}
+w_{\mathrm{state}}q_{\mathrm{state}} .
$$

Because the average execution intensity depends on realized execution whenever $\rho_A\ne1$, the execution equation is implicit:

$$
R_{\mathrm{execution}}
=\left[
\frac{m_{\mathrm{execution}}b_{\mathrm{execution}}
+w_{\mathrm{execution}}R_{\mathrm{execution}}^{\rho_A-1}b_{\mathrm{data}}}{p^0}
\right]^{-\epsilon_{\mathrm{execution}}}.
$$

A higher $b_{\mathrm{data}}$ raises both parent prices, reduces parent activity, and thereby reduces BAL
without introducing a separate BAL own-price elasticity that history cannot identify. BAL is
calculated from realized activity, so it also remains internally consistent when a resource
underfills its configured target.

Total data gas is the sum of the two components:

$$
g_{\mathrm{data}}
=g_{\mathrm{static}}(b_{\mathrm{data}})
+w_{\mathrm{execution}}q_{\mathrm{execution}}^0R_{\mathrm{execution}}^{\rho_A}
+w_{\mathrm{state}}q_{\mathrm{state}} .
$$

Because the parent quantities depend on $b_{\mathrm{execution}}$ and $b_{\mathrm{state}}$ as well as $b_{\mathrm{data}}$, data demand is no longer a function of the data fee alone. Any equilibrium built on this model has to solve the three fees simultaneously.


### Why the estimated elasticities apply to these prices

The model's central behavioral assumption applies the execution and state elasticities to responses
in BAL-inclusive parent prices. The elasticities were recovered from the 2025 gas-limit events,
which moved a single shared fee: execution, data, and state prices never varied independently, and
BAL carried no charge. Those events therefore identify the response to a proportional change in
overall parent cost; they do not separately identify responses to each fee component.

We interpret the recovered execution and state elasticities as responses to the effective price of the underlying activity. Under EIP-7999 that effective price includes the newly charged BAL footprint, so applying the historical elasticities to BAL-inclusive parent prices is our preferred way of carrying the estimates into the counterfactual. It is not identified by historical variation in separate execution and data fees, and it assumes the response depends on the total price rather than on how that total is split across fee lines.

This is the same logic already used for the metering multipliers. $m_i$ converts a base fee into the effective price of historical activity; the BAL term adds the second fee line to that same effective price. Leaving it out would assume users respond to their execution charge and ignore the BAL charge entirely, which is a stronger thing to believe about a cost appearing on the same fee.

## Limitations

**The BAL-inclusive parent prices remain aggregate.** $P_{\mathrm{execution}}$ and
$P_{\mathrm{state}}$ include the average BAL charge generated by each parent activity. Static data
carried by the same transactions remains on its own demand curve, and the model does not require
every resource used by a transaction to enter or exit together. This treatment is consistent with
the aggregate elasticities estimated in the earlier analysis, but it does not model changes in
transaction composition.

**Allocation of co-produced BAL.** The transaction-level decomposition measures the amount of runtime
BAL directly matched to state creation, co-produced alongside state creation, and generated by
transactions with no observed state creation. It does not identify how the co-produced component
would scale when execution and state prices vary independently. The reference specification sets
$\lambda=0$, assigning co-produced access to the execution/access parent activity, and uses
$\lambda\in\{0,0.5,1\}$ as a sensitivity range. These values represent alternative behavioral
allocations and carry no estimated-probability interpretation.

**Execution is a proxy for existing-state access.** The counterfactual mapping $A/A^0=(q_{\mathrm{execution}}/q_{\mathrm{execution}}^0)^{\rho_A}$ allows BAL intensity to change as execution expands. The values 0.75, 1, and 1.25 bracket sub-proportional, proportional, and more-than-proportional scaling; they are sensitivities rather than predictions.

**The runtime counter does not measure the complete BAL payload.** The demand anchor uses EIP-8279's transaction-local runtime counter. Mandatory per transaction BAL entries are covered through `TX_BASE` rather than included in that counter, while the Xatu reconstruction may miss storage-value charges created inside reverted call frames. A design that prices the complete physical BAL would require a separate, block-aware measurement with address de-duplication.




## Parameters carried into the EIP-7999 equilibrium model


| Parameter | Value | Interpretation |
|---|---:|---|
| Current EIP-7623 data quantity $q_{\mathrm{data}}^0$ | 1.180555M gas/block | Historical static-data denominator |
| Counterfactual static-data anchor $g_{\mathrm{static}}^0$ | 2.133559M data gas/block | Flat-16 calldata plus access lists, authorizations and their static BAL entries, and blob hashes |
| Static-data metering multiplier $m_{\mathrm{data,static}}$ | 1.807251 | Accounting conversion applied to static-data demand |
| BAL runtime-meter anchor | 119,944 bytes/block | Direct EIP-8279 event reconstruction over 6,000 blocks |
| BAL metered anchor | 1.919100M data gas/block | Runtime counter at 16 data gas per byte |
| Direct-state runtime BAL share | 0.113937 | Runtime bytes matched to persistent state creation |
| Co-produced runtime BAL share | 0.378791 | Remaining runtime bytes in state-creating transactions |
| Non-state-transaction runtime BAL share | 0.507272 | Runtime bytes in transactions with no observed state creation |
| Co-produced allocation $\lambda$ | 0 as reference; 0.5 and 1 as sensitivities | Fraction of $c$ assigned to state; the remainder follows execution/access activity |



## Reproducibility

The publication-facing calculations are split into two ordered notebooks:

1. [data metering and the runtime-BAL anchor](../notebooks/7999_equilibrium/01-data-metering-runtime-bal.ipynb); and
2. [BAL decomposition and parent-activity demand](../notebooks/7999_equilibrium/02-bal-decomposition.ipynb).

Notebook 01 contains the credential-aware Xatu and RPC refresh path, including
the deterministic 50-block-per-day sampling plan. Notebook 02 contains the
resumable transaction-level Xatu attribution. Both default to cached mode and
write compact handoffs under `data/7999/`.







## Appendix: Data sources

### EIP-8279 runtime counter and state/execution attribution

| Source | Runtime components used |
|---|---|
| Xatu `default.canonical_execution_transaction_structlog_agg` | Cold account and storage accesses |
| Xatu `default.canonical_execution_storage_diffs` | Storage values that remain different from their pre-transaction value |
| Xatu `default.canonical_execution_traces` | Value-bearing calls, self-destruct transfers, internal creation, endowment, and deployed code |
| Xatu storage, contract, balance, nonce, and address-appearance tables | Transaction-level new slots, accounts, and code used for state-linked matching |
| Xatu `default.execution_transaction` | Transaction and calldata byte counts |
| Xatu `default.canonical_execution_transaction` | Receipt gas used only for the appendix cost diagnostic |


### Static-data metering multiplier

| Source | Fields used in the static-data calculation |
|---|---|
| Xatu `default.canonical_execution_block` | Canonical block dates and block coverage |
| Xatu `default.canonical_execution_transaction` | Receipt gas and zero/nonzero calldata bytes used to reconstruct current EIP-7623 data gas |
| Xatu `default.execution_transaction` | Exact calldata bytes, zero/nonzero byte counts, type-4 transaction counts, and blob-versioned hashes |
| Ethnodeops Erigon RPC sample | Access-list contents and authorization tuples not fully exposed by the Xatu transaction tables |
