# Dynamic Simulation of the Bundle-Priced EIP-7999 Fee Market

The [bundle-priced equilibrium analysis](bundle_priced_7999_equilibrium_report.md) identifies the execution and data targets that can clear simultaneously under steady demand. This report adds block-level demand variation and the protocol fee-update rules. It asks how often hard limits bind, how much offered gas is excluded, how the three prices move, and whether the static capacity rankings remain valid under shocks. The EIP-7999 mechanism follows the open [multi-resource pull request](https://github.com/ethereum/EIPs/pull/11835); the 90M data limit used for the main analysis is a capacity counterfactual, while the result files also retain the pull request's 60M value.

### Main results

1. **The data target ratio is the main determinant of data-limit pressure.** Across the selected settings, moving the data target toward the fixed 90M limit raises included-limit frequency from **1.7% to 59.2%**; changing the execution target at a fixed ratio moves it much less.
2. **Larger execution targets do not always deliver more execution.** E250/D60 delivers **244.8M** execution gas, while the more aggressive E300/D80 delivers only **238.0M**, because data-limit exclusion removes parent execution together with its linked BAL.
3. **The execution fee is bounded at one wei at both low and high data targets, for different reasons.** At low data targets a high data fee prices out BAL-producing execution; near the data limit, insufficient headroom packs it out. At E300/D77 the execution fee is bounded at one wei in 71.0% of blocks and delivers only 82.9% of its target.
4. **The 60-day calibration places E225/D45 close to the illustrative operating guardrails.** It delivers **220.4M** execution gas at 98.0% target utilization, reaches the data limit in 5.2% of blocks, and is bounded at one wei in 15.5% of blocks.
5. **Low price variation is not evidence of a stable market.** Execution-price variation falls to 0.027 at E300/D80 because the execution fee is usually constrained by its floor while data-limit exclusion absorbs pressure. Price-variation statistics are only interpretable alongside minimum-bound operation and limit frequency.
6. **The qualitative results are more sensitive to access scaling and demand elasticities than to BAL allocation.** Varying $\lambda$ has little effect in the displayed designs, while $\rho_A$ and the elasticity vector materially affect supportable execution.

## Notation and reference specification

| Group | Notation | Meaning |
|---|---|---|
| Fees | $b_i$, $P_i$ | Base fee and effective activity price for resource $i$ |
| Fee state | $x_{i,t}$ | Normalized excess-gas counter for resource $i$ |
| Capacity | $T_i$, $L_i$ | Gas target and hard gas limit |
| Block quantities | $g_{i,t}^{\mathrm{offered}}$, $g_{i,t}^{\mathrm{included}}$ | Gas demanded before packing and gas included after enforcing limits |
| Shocks | $s_{\mathrm{execution},t}$, $s_{\mathrm{data},t}$, $s_{\mathrm{state},t}$, $a_t$ | Execution, static-data, state, and BAL-access shocks |
| BAL structure | $\lambda$, $\rho_A$ | Co-produced-BAL routing and access-scaling parameters |
| Metering | $m_i$, $w_i$ | Gas-metering multiplier and BAL intensity for resource $i$ |

Unless stated otherwise, results use the 35-day elasticity estimates $(\epsilon_{\mathrm{execution}},\epsilon_{\mathrm{data}}, \epsilon_{\mathrm{state}})=(0.121,0.229,0.335)$; $\lambda=0$ and $\rho_A=1$; a 90M data limit and 75M state target; an execution limit equal to twice its target; and 32 bootstrap paths, with a one-day burn-in followed by seven measured days.

## Simulation framework

Each configuration begins at its historical cost-equivalent reference fees and is advanced through a one-day burn-in before any statistic is taken. Each block follows the same sequence: users respond to current prices, their execution and state activity generate BAL, the block builder includes only quantities that fit under the hard limits, and the protocol updates fees from included gas. Configurations see identical shock paths from the same seeds, so comparisons are paired and seed noise largely cancels.

When the data limit binds, the aggregate inclusion rule scales each transaction bundle proportionally, so excluded execution and its BAL leave together. This bundle-consistent packing is conservative: a real builder could select less data-intensive transactions first.

Under EIP-7999, the effective prices users face are

$$
P_{\mathrm{execution}} = m_{\mathrm{execution}} b_{\mathrm{execution}} + \bar{w}_{\mathrm{execution}} b_{\mathrm{data}}, \qquad P_{\mathrm{state}} = m_{\mathrm{state}} b_{\mathrm{state}} + w_{\mathrm{state}} b_{\mathrm{data}},
$$

so a higher data fee suppresses the activity that produces BAL. Under Glamsterdam, all three effective prices are fixed multiples of one shared fee: $P_i = m_i^G b_G$.

**Fee-update rules.** EIP-7999 accumulates a normalized excess-gas counter for each resource and exponentiates it: $b_{i,t+1} \approx b_{i,t} \exp\!\left[2\ln(1.125)\,(g_i^{\mathrm{included}}-T_i)/h_i\right]$, clamped at one wei. Glamsterdam uses EIP-1559's integer step: the fee moves by a fraction of $|g-T|/(8T)$, upward with a minimum step of one, downward with truncation to zero. Both reach approximately $\pm$12.5% at a full or empty block and share the same fixed point at $g=T$, but differ in approach speed and at low fees.

### Validation

| Check | Result |
|---|---|
| Vectorized fee transition against the integer `fake_exponential` | exact on all 3,943 values tested |
| Excess-gas recursion over 20,000 blocks, three fee regimes | zero drift |
| Warm start at a solved equilibrium under unit shocks | fees stationary to $4\times10^{-5}$ |
| Floor-bound execution target utilization against the static solver | agreement within 0.002 |
| Parent--BAL inclusion under binding limits | linked execution, state and BAL scale together exactly |

## Empirical demand shocks

We recover execution, static-data, state, and access-composition shocks from **430,605 consecutive blocks** over 60 days (2 April--31 May 2026, blocks 24,788,193 to 25,218,797). Two aligned inputs cover this range: one carries block-level execution, transaction data, state creation, historical base fees, and timestamps; the second reconstructs the EIP-8279 runtime BAL meter. Daily demand factors are estimated separately from the 120-day accounting panel.

### Why four shocks

EIP-7999 has three priced resources but four economically distinct sources of variation. Execution, static data, and state creation each have an independently modeled demand curve, so each requires a shock that shifts how much of that activity users want at a given price. BAL belongs to the data resource, but users do not choose BAL bytes independently — their execution and state activity produce BAL through the accounts and storage keys that transactions access.

The preceding [BAL demand report](bundle_priced_bal_demand_model_report.md) finds that **11.4%** of runtime-metered BAL is matched directly to state creation; the remaining **88.6%** is access-related. The fourth shock, $a_t$, captures block-level variation in access intensity — how BAL-intensive the transaction mix is, given the parent activity.

### Recovering demand shocks

Observed gas usage is not itself the demand shock: a block can carry high activity because the fee is low or because the underlying willingness to transact is unusually high. We invert the demand model to separate the two.

For each parent resource, the maintained demand equation is

$$
x_{i,t}^{\mathrm{obs}} = x_i^0 \widetilde{s}_{i,t} \left(\frac{p_t}{p^0}\right)^{-\epsilon_i}.
$$

Solving backward gives the raw multiplicative demand condition $\widetilde{s}_{i,t} = (x_{i,t}^{\mathrm{obs}}/x_i^0)(p_t/p^0)^{\epsilon_i}$. The pipeline then works in logs: it subtracts the median for the same UTC hour and the median of the hour-adjusted residuals within each calendar day. The remaining residual records whether demand was unusually high or low relative to the time of day and the overall demand condition of that day. It preserves within-day bursts, their persistence, and their cross-resource co-movement.

The multiplicative shock used by the simulator is $s_{i,t} = \exp(u_{i,t}) / \operatorname{mean}_t[\exp(u_{i,t})]$, ensuring $\operatorname{mean}_t(s_{i,t})=1$ so that the demand anchors are preserved as mean quantities. For the access shock, the raw ratio is observed runtime BAL divided by BAL predicted from parent activity; the pipeline removes a centered 201-block rolling median and normalizes using predicted BAL as the weight so that the runtime-BAL anchor is preserved.

### From the historical panel to simulated paths

Drawing individual blocks independently would preserve the distribution of each shock but destroy the observed bursts, persistence, and cross-resource co-movement. We use a **multiscale moving-block bootstrap**. It restores the recurring hourly profile and jointly sampled daily factors, then copies the four fast residual columns together in contiguous 3,200-block strips (approximately 10.7 hours). The 3,200-block length is selected from 400--6,400-block candidates using integrated correlation time, cross-resource correlations, and clustered extremes.

Each simulated path contains 57,600 blocks: a 7,200-block burn-in followed by 50,400 measured blocks. We generate 32 such paths. Within each comparison, every design or mechanism receives the same paths, so differences come from the fee rules and capacity settings.

### Demand in each simulated block

At each block, the current effective prices determine movement along the demand curves while the sampled shocks shift those curves:

$$
q_{i,t} = q_i^0 \, s_{i,t} \left(\frac{P_{i,t}}{p^0}\right)^{-\epsilon_i}, \quad i \in \{\text{execution, static data, state}\}.
$$

Runtime BAL is generated after parent activity is realized: $g_{\mathrm{BAL},t} = a_t\!\left[w_{\mathrm{execution}} q_{\mathrm{execution}}^0 R_{\mathrm{execution},t}^{\rho_A} + w_{\mathrm{state}} q_{\mathrm{state},t}\right]$. Offered data gas is the sum of static data and BAL. Bundle-consistent packing applies the hard limits, and the next block's fees depend on included rather than offered gas.

## Simulation design and outcome metrics

### Design variables

The protocol choices are the execution target $T_{\mathrm{execution}}$, execution limit $L_{\mathrm{execution}}=2T_{\mathrm{execution}}$, and data target $T_{\mathrm{data}}$, with $L_{\mathrm{data}}$ fixed at 90M and the state target at 75M. The parameters $\lambda$, $\rho_A$, and the elasticity vector describe model uncertainty and are varied in the sensitivity analysis while holding resource targets fixed. Every design and specification sees identical shock paths.

### Outcome metrics

| Group | Metrics |
|---|---|
| Throughput | mean included gas; target utilization $\overline{g}_i/T_i$ |
| Limit pressure | fraction of blocks whose included quantity equals the hard limit |
| Data composition | mean static data, execution-linked BAL, state-linked BAL; BAL share of included data |
| Minimum-bound operation | fraction of blocks with $b_i=1$ wei while included usage remains below target |
| Price variation | sd, p95, p99 of $\Delta\log P_i$ |

Limit pressure measures *included* quantities at the limit after packing, not offered quantities before it. Price variation is measured on the effective activity prices, not the raw base fees: an execution unit pays its own metered gas *and* the BAL data gas it generates.

### Glamsterdam benchmark

Glamsterdam runs at a 200M gas limit with a 100M target, metering execution and data in one branch against state in the other, and pricing both with a single base fee. The same latent workload drives both mechanisms:

| Shock | Under EIP-7999 | Under Glamsterdam |
|---|---|---|
| $s_{\mathrm{execution}}$ | execution activity and execution-generated BAL | the regular branch |
| $s_{\mathrm{data}}$ | static data | the regular branch |
| $s_{\mathrm{state}}$ | state creation and state-generated BAL | the state branch |
| $a$ | BAL intensity, priced as data gas | BAL payload only — unpriced |

Under EIP-7999, the access shock changes fee-controlled data gas because BAL is metered. Under Glamsterdam, it changes only an unpriced payload.

## EIP-7999 target grid

With $L_{\mathrm{data}}$ fixed at 90M, $L_{\mathrm{execution}}=2T_{\mathrm{execution}}$, and $T_{\mathrm{state}}=75$M, the main design space is the pair $(T_{\mathrm{execution}}, T_{\mathrm{data}})$. The grid covers seven execution targets from 150M to 300M and nine data targets from 22.5M to 80M, for 63 settings, each run on the same 32 weekly bootstrap paths.

Three figures read the same grid along three different questions: does execution get delivered, does the data limit bind, and how much do prices move. Every panel shares axes — data target increases rightward, execution target increases upward.

### Execution support: target utilization and floor operation

![Execution support grid](../plots/dynamic_execution_support_grid.png)

> Left: delivered execution as a fraction of the execution target. Right: the fraction of blocks in which the execution fee is bounded at one wei, meaning the fee is already one wei while included execution remains below target. Each cell is the mean across 32 weekly paths.

Reading across any row, the execution fee bounded at one wei is **U-shaped**: it is highest when the data target is very low *or* very high, and falls to a minimum only in a band around $T_{\mathrm{data}}\approx 60$–$67.5$M. The two arms of the U have opposite causes, and the utilization panel shows both as a loss of delivered execution.

**The left arm is price-constrained.** A low data target requires a high data fee to hold static-data demand down to that target — approximately 32,993 wei at $T_{\mathrm{data}}=22.5$M. That same fee prices the BAL that execution generates. With the execution fee bounded at one wei, the execution unit's price decomposes as

$$
P_{\mathrm{execution}} = \underbrace{m_{\mathrm{execution}}\cdot 1}_{1.54} + \underbrace{\bar w_{\mathrm{execution}} b_{\mathrm{data}}}_{2{,}343},
$$

so more than **99.9% of what an execution unit pays is the BAL charge rather than the execution fee**. The execution controller responds to underfill by cutting its own fee, reaches one wei, and has nothing left to give. Execution stops wherever the BAL charge leaves it.

The D22.5 column shows this as a plateau. Delivered execution is approximately 156.7M from E225 through E300, while the data limit binds in only 0.13% of blocks. Nothing about the data *limit* is active here; the data *price* is what stops execution. The low data target creates an endogenous ceiling on execution through the BAL charge.

**The right arm is hard-limit-constrained.** At $T_{\mathrm{data}}=80$M, the target leaves only 10M of headroom under the fixed 90M limit. Offered data averages 113.2M at E300, 26% above the limit, and blocks are clipped 63% of the time. Because inclusion is bundle-consistent, clipping the data side removes the parent execution that generated the BAL along with it. Execution underfills for the opposite reason to the left arm: not priced out, but packed out. The controller again cuts to one wei and again has nothing left.

**What this adds to the equilibrium result.** The equilibrium analysis places the one-wei frontier for a 300M execution target at approximately 76.97M of data target — the smallest data target at which all three resources clear with the execution fee still at or above one wei. Carrying that point into the dynamic setting fails in two ways.

First, 300M is not delivered. E300/D77 delivers 248.6M, or 82.9% of target. The static calculation asks whether a fee vector clears the market on an average block; it does not ask whether that average is reachable once a hard limit truncates the high blocks.

Second, and more consequential for how the frontier should be used: **the execution fee is bounded at one wei in 71.0% of blocks at E300/D77.** The frontier is *defined* as the locus where the equilibrium fee equals the minimum, so any design placed on it inherits that state as its normal condition rather than as an edge case. Scanning the entire E300 row, no data target escapes it — the lowest value available at a 300M execution target is 59.2%, at D67.5, where utilization peaks at 88.6%:

| E300 row | D22.5 | D36 | D45 | D60 | **D67.5** | D77 | D80 |
|---|---:|---:|---:|---:|---:|---:|---:|
| execution target utilization | 52.2% | 70.1% | 79.6% | 88.6% | **88.6%** | 82.9% | 79.3% |
| execution fee bounded at one wei | 95.9% | 85.1% | 76.3% | 60.5% | **59.2%** | 71.0% | 77.5% |
| delivered execution | 156.7M | 210.4M | 238.8M | 265.7M | **265.7M** | 248.6M | 238.0M |

Under this calibration a 300M execution target has no dynamically comfortable data target: it is priced out on the left, packed out on the right, and bounded at one wei in at least 59.2% of blocks throughout. A lower execution target gives the U a much deeper bottom — at D60 the execution fee is bounded at one wei in 1.8% of blocks at E200 and 5.6% at E225.

### Data-limit pressure and the composition of included data

![Data-limit pressure grid](../plots/dynamic_data_limit_pressure_grid.png)

> Left: the fraction of blocks whose included data gas equals the 90M limit. Right: BAL as a share of included data gas.

The left panel is almost columnar: the fraction of blocks at the data limit is set mainly by the data target ratio and moves much less with the execution target. At $T_{\mathrm{data}}/L_{\mathrm{data}}=0.5$ it stays between 5.2% and 5.9% across execution targets from 150M to 300M; across the full range of data targets at fixed execution target, it rises from approximately 0.1% to 59%.

The small movement that does exist can run in the opposite direction to the first intuition: raising the execution target slightly reduces data-limit pressure. At D60 it falls from 20.2% at E150 to 19.2% at E300. More execution generates more BAL, yet the data limit binds slightly less often.

The mechanism is a composition shift, and it is worth stating precisely because the aggregate hides it. The data controller holds *mean included* data at the target regardless of the execution target — at D60 it is 60.02M at both E150 and E300. What changes is the mix and the spread:

| D60 column | E150 | E300 | change |
|---|---:|---:|---:|
| mean data fee | 103.9 wei | 148.2 wei | +43% |
| static data offered | 60.26M | 53.42M | −6.84M |
| BAL offered | 8.12M | 13.73M | +5.61M |
| **total offered** | **68.39M** | **67.15M** | **−1.24M** |
| mean included | 60.01M | 60.02M | +0.01M |
| rationed data | 8.37M | 7.13M | −1.24M |
| BAL share of included data | 12.5% | 21.4% | +8.9% |

A higher execution target lowers the execution fee, so more execution runs and more BAL is produced. To keep total included data near 60M, the data controller raises the data fee by 43%, which contracts static-data demand. Roughly 6M of gas per block moves from static data into execution-linked BAL.

**The limit binds on the upper tail of offered data rather than on its mean.** Static data is driven by a log shock with standard deviation 0.746. BAL is driven mainly by execution activity, whose log shock has standard deviation 0.593, multiplied by the smaller access shock. The access shock is negatively correlated with execution at −0.20, so an unusually execution-heavy block tends to be slightly less access-intensive per unit of parent activity.

The resulting composition shift slightly lowers total offered data and data-limit frequency even as the BAL share rises. This is a second-order equilibrium response, since the fee adjusts static-data demand when execution-linked BAL expands.

This should not be read as a general claim that larger execution targets relieve data congestion. Doubling the execution target changes limit frequency by roughly one percentage point in this comparison, while moving the data target across its range changes it by tens of percentage points.

The right panel confirms the composition story directly. The BAL share of included data rises from 12.5% to 21.4% down the D60 column and generally falls as a higher data target admits proportionally more static data. At very low data targets, execution and therefore BAL stop responding strongly to the configured execution target once the execution fee reaches its minimum.

### Effective-price variation

![Price variation grid](../plots/dynamic_price_variation_grid.png)

> Standard deviation of block-to-block log changes in the effective activity prices. Left: execution, $P_{\mathrm{execution}} = m_{\mathrm{execution}}b_{\mathrm{execution}} + \bar w_{\mathrm{execution}}b_{\mathrm{data}}$. Right: data, $P_{\mathrm{data}} = m_{\mathrm{data}}b_{\mathrm{data}}$.

**Data-price variation generally rises with the data target ratio and changes little with the execution target.** Along the E300 row it rises from 0.029 at D22.5 to 0.125 at D77, then falls slightly to 0.121 at D80 because persistent clipping compresses the observed fee response. The first-order reason for the broader rise is mechanical: the excess-gas update divides the gap between included gas and target by the **limit**, not by the target:

$$
\Delta\log b_{\mathrm{data}} \approx 2\ln(1.125)\,\frac{g_{\mathrm{data}}^{\mathrm{included}}-T_{\mathrm{data}}}{L_{\mathrm{data}}}.
$$

$L_{\mathrm{data}}$ is fixed at 90M across the whole grid. A demand shock that moves included data by a given percentage of its target creates an absolute gap that scales with $T_{\mathrm{data}}$, while the divisor stays at 90M. The same proportional demand swing therefore produces a larger fee step at a larger target until frequent hard-limit clipping changes the response.

**Execution-price variation is not monotonic.** It forms a ridge, peaking at 0.103 at E225/D80 and falling to 0.027 at E300/D80, the lowest value on the grid. The execution effective price contains both the execution base-fee term and the data charge on execution-linked BAL. In the middle of the grid both terms move; at E300/D80 the execution fee is bounded at one wei in 77.5% of blocks, so variation in the own-fee component is compressed.

The E300 row shows the turnover directly:

| E300 row | D22.5 | D36 | D45 | D60 | D67.5 | D77 | D80 |
|---|---:|---:|---:|---:|---:|---:|---:|
| mean data fee (wei) | 32,993 | 3,173 | 1,009 | 148 | 40 | 8.8 | 5.0 |
| execution-price sd | 0.029 | 0.044 | 0.048 | 0.053 | 0.052 | 0.035 | 0.027 |
| data-price sd | 0.029 | 0.046 | 0.054 | 0.071 | 0.094 | 0.125 | 0.121 |

At the left edge the data fee is so large that variation in the BAL charge dominates the execution price. At the right edge the execution fee is usually constrained by its minimum and the data limit excludes a large fraction of offered bundles. **The practical consequence is that a low execution-price variation number carries little information on its own.** It can reflect a stable interior market, dominance by the data charge, or floor compression. The price-variation panel must therefore be read next to minimum-bound operation and data-limit pressure.

### Selected settings

| setting | $T_{\mathrm{data}}/L_{\mathrm{data}}$ | delivered execution | execution target utilization | blocks at data limit | execution fee bounded at one wei | execution-price sd | data-price sd |
|---|---:|---:|---:|---:|---:|---:|---:|
| E200/D36 | 0.400 | 195.8M [186.8, 199.0] | 97.9% | 1.7% | 15.0% | 0.047 | 0.046 |
| E225/D45 | 0.500 | 220.4M [211.5, 223.8] | 98.0% | 5.2% | 15.5% | 0.057 | 0.055 |
| E250/D60 | 0.667 | 244.8M [238.1, 248.7] | 97.9% | 19.3% | 18.6% | 0.081 | 0.073 |
| E300/D77 | 0.856 | 248.6M [234.4, 263.2] | 82.9% | 51.4% | 71.0% | 0.035 | 0.125 |
| E300/D80 | 0.889 | 238.0M [223.7, 252.7] | 79.3% | 59.2% | 77.5% | 0.027 | 0.121 |

Square brackets report the 5th--95th percentiles across the 32 weekly paths.

> The open [EIP-7999 pull request](https://github.com/ethereum/EIPs/pull/11835) specifies a 60M data limit. The main figures use the 90M counterfactual from the equilibrium report. Moving from 90M to 60M lowers the maximum deliverable execution by roughly 50M across the tested tolerances; both limit sweeps are retained in the result file.

## Illustrative operating points

The grid makes individual mechanisms difficult to follow. The four operating points below span low data pressure through a deliberately saturated case.

![Illustrative operating points](../plots/dynamic_candidates.png)

> The stacked panel separates blocks in which only the execution cap is active, only the data cap, or both. E300/D80 delivers less execution than E250/D60 even though its configured target is 50M higher.

| | conservative | central | aggressive | saturation |
|---|---:|---:|---:|---:|
| design | E200/D36 | E225/D45 | E250/D60 | E300/D80 |
| $T_{\mathrm{data}}/L_{\mathrm{data}}$ | 0.400 | 0.500 | 0.667 | 0.889 |
| delivered execution | 195.8M | 220.4M | 244.8M | 238.0M |
| execution target utilization | 0.979 | 0.980 | 0.979 | 0.793 |
| blocks at execution limit | 2.2% | 1.8% | 0.8% | 0.1% |
| blocks at data limit | 1.7% | 5.2% | 19.3% | 59.2% |
| execution fee bounded at one wei | 15.0% | 15.5% | 18.6% | 77.5% |
| execution per unit of state | 2.61 | 2.94 | 3.26 | 3.17 |

E225/D45 delivers 98.0% of its execution target and serves as the central illustrative operating point. E300/D80 illustrates the saturated regime, in which a larger configured execution target yields less delivered execution.

## Target-to-limit headroom

The target determines where the fee tries to hold average usage; the limit determines how much positive demand fits in a particular block. As $T_{\mathrm{data}}$ approaches $L_{\mathrm{data}}$, the mechanism increasingly resolves scarcity through exclusion at the hard limit. With $L_{\mathrm{data}}$ fixed, burst headroom above target is $(1-r_{\mathrm{data}})/r_{\mathrm{data}}$ where $r_{\mathrm{data}}=T_{\mathrm{data}}/L_{\mathrm{data}}$: a half ratio leaves a full target of headroom, two-thirds leaves half a target, and E300/D80 leaves only 12.5% of its target.

| design | $T_{\mathrm{data}}/L_{\mathrm{data}}$ | blocks at data limit | post-onset peak / pre-onset median data fee |
|---|---:|---:|---:|
| E200/D45 | 0.500 | 5.8% | 64.2× |
| E225/D45 | 0.500 | 5.6% | 57.3× |
| E250/D60 | 0.667 | 19.3% | 63.0× |
| E300/D77 | 0.856 | 52.3% | 23.7× |
| **E300/D80** | **0.889** | **60.0%** | **18.6×** |
| **E300/D85** | **0.944** | **69.3%** | **6.6×** |

![Saturation pathology](../plots/dynamic_saturation_pathology.png)

> Raising the data target toward the fixed 90M limit increases congestion. Beyond a target ratio of roughly two-thirds, the peak daily fee response falls because the hard limit excludes a growing share of demand before the fee update observes it.

The most congested design has the *smallest* fee response: once the block is clipped in most blocks, the fee controller never observes the demand that was turned away. Congestion keeps climbing while the price response falls. A low fee-variation statistic can therefore indicate that the hard limit has weakened the fee as a marginal scarcity signal.

## EIP-7999 and Glamsterdam

The figure places the four EIP-7999 operating points beside Glamsterdam at its 200M central limit.

![Mechanism comparison](../plots/dynamic_mechanism_comparison.png)

> All operating points receive identical demand-shock paths. Effective-price variation is the standard deviation of block-to-block log changes.

| Metric | conservative | central | aggressive | saturation | Glamsterdam 200M |
|---|---:|---:|---:|---:|---:|
| design | E200/D36 | E225/D45 | E250/D60 | E300/D80 | — |
| delivered execution | 195.8M | 220.4M | 244.8M | 238.0M | 68.1M |
| execution target utilization | 0.979 | 0.980 | 0.979 | 0.793 | — |
| included state gas | 75.0M | 75.0M | 75.0M | 75.0M | 93.6M |
| execution per unit of state | 2.61 | 2.94 | 3.26 | 3.17 | **0.73** |
| blocks at either limit | 3.8% | 7.0% | 20.1% | 59.3% | 6.2% |
| execution price, sd | 0.047 | 0.057 | 0.081 | 0.027 | 0.058 |
| data price, sd | 0.046 | 0.055 | 0.073 | 0.121 | 0.058 |
| state price, sd | 0.150 | 0.150 | 0.149 | 0.150 | 0.058 |
| state price, p99 | 0.537 | 0.537 | 0.531 | 0.531 | 0.120 |
| execution fee bounded at one wei | 15.0% | 15.5% | 18.6% | 77.5% | — |

**Throughput.** At the tested central parameterizations, E225/D45 delivers **3.24 times Glamsterdam-200M execution with 19.8% less included state gas**. The point comparison combines different capacity vectors and should not be read as the isolated effect of changing only the fee mechanism.

Under Glamsterdam, execution per unit of state falls as capacity rises because the lower shared fee expands the most elastic resource fastest. State creation has the largest estimated elasticity; the state branch sets the fee in 64% of blocks at a 200M limit and 97% at 600M.

| | execution | state gas | execution per unit state |
|---|---:|---:|---:|
| Glamsterdam, 100M limit | 44.6M | 30.5M | 1.46 |
| **Glamsterdam, 200M limit** | **68.1M** | **93.6M** | **0.73** |
| Glamsterdam, 300M limit | 80.6M | 148.5M | 0.54 |
| Glamsterdam, 600M limit | 104.3M | 303.1M | 0.34 |
| **EIP-7999, E225/D45** | **220.4M** | **75.0M** | **2.94** |

![Mechanism frontier](../plots/dynamic_mechanism_frontier.png)

> Glamsterdam's shared fee increasingly expands state as its common gas limit rises. The tested EIP-7999 operating points maintain the 75M state target and deliver substantially more execution per unit of included state gas.

**Prices.** Under Glamsterdam the three effective prices are fixed multiples of one fee and share sd 0.058 and p99 0.120. Under EIP-7999 the standard deviations separate: 0.057 for execution, 0.055 for data, and 0.150 for state. The higher state-price variation reflects the separate state fee responding to the most elastic and most variable resource.

**Representative bundle costs.** The following fixed recipes are expressed in historical gas-equivalent activity units:

| bundle | execution | static data | state |
|---|---:|---:|---:|
| execution-heavy | 200,000 | 2,000 | 0 |
| data-heavy | 40,000 | 100,000 | 0 |
| state-creating | 80,000 | 3,000 | 40,000 |
| mixed | 120,000 | 20,000 | 10,000 |

| bundle | conservative | central | aggressive | saturation | Glamsterdam 200M |
|---|---:|---:|---:|---:|---:|
| execution-heavy | 0.073 | 0.025 | 0.0049 | 0.00041 | 342.9 |
| data-heavy | 0.562 | 0.179 | 0.026 | 0.00098 | 284.4 |
| state-creating | 774.7 | 757.7 | 673.3 | 424.4 | 391.0 |
| mixed | 193.8 | 189.5 | 168.3 | 106.1 | 308.8 |

Execution and data become inexpensive while the state-creating bundle costs 1.94 times more at E225/D45. The separate fees move the charge toward the resource that generates the state-growth externality. These EIP-7999 configurations carry three to four times Glamsterdam's total block capacity, so the cost rows show the direction of price reallocation at each mechanism's stated capacity, not fee forecasts.

## Parameter sensitivity

The central specification uses the 35-day elasticity vector, $\rho_A=1$, and $\lambda=0$. Each input is varied separately while the others remain central. Resource targets, shock paths, seeds, and initialization are held fixed.

| Elasticity window | $\epsilon_{\mathrm{execution}}$ | $\epsilon_{\mathrm{data}}$ | $\epsilon_{\mathrm{state}}$ |
|---:|---:|---:|---:|
| 21 days | 0.117 | 0.202 | 0.478 |
| **35 days, central** | **0.121** | **0.229** | **0.335** |
| 60 days | 0.0817 | 0.205 | 0.280 |
| 75 days | 0.0785 | 0.201 | 0.254 |

The structural sensitivities use $\rho_A\in\{0.75,1,1.25\}$ and $\lambda\in\{0,0.5,1\}$.

![One-at-a-time parameter sensitivity](../plots/dynamic_parameter_sensitivity.png)

> Each row holds one design fixed. Each column changes one model input. Open markers identify the central specification. Shaded 60- and 75-day cases are demand-constrained before data capacity is considered.

| design | varied input | execution target utilization | blocks at data limit | execution fee bounded at one wei |
|---|---|---:|---:|---:|
| E225/D45 | elasticity, 21–35 days | 98.0–99.0% | 5.21–5.22% | 7.6–15.5% |
| E225/D45 | $\rho_A$, 0.75–1.25 | 93.2–99.0% | 4.88–5.83% | 6.4–46.6% |
| E225/D45 | $\lambda$, 0–1 | 98.0–99.0% | 5.21–5.73% | 6.4–15.5% |
| E300/D80 | elasticity, 21–35 days | 79.3–85.1% | 38.6–59.2% | 67.7–77.5% |
| E300/D80 | $\rho_A$, 0.75–1.25 | 76.1–80.8% | 57.4–61.6% | 74.4–84.5% |
| E300/D80 | $\lambda$, 0–1 | 79.3–80.2% | 58.4–59.2% | 75.6–77.5% |

The elasticity vector is the largest source of uncertainty for the saturated design: between the capacity-constrained 21- and 35-day estimates, blocks at the data limit move from 38.6% to 59.2%. The parameter $\rho_A$ can reduce execution target utilization when access-related BAL grows faster than execution. The allocation parameter $\lambda$ has the smallest effect.

### Demand-constrained elasticity estimates

Under the 60- and 75-day elasticity vectors, execution demand cannot reach a 225M or 300M target at a one-wei fee even with no BAL charge — their zero-charge ceilings are 160.9M and 152.0M. Those specifications are demand-constrained, and no data capacity can change the outcome.

### Interactions and bootstrap sensitivity

Across all nine $\lambda\times\rho_A$ combinations at the 35-day window, blocks at the data limit remain ordered: E225/D45 at 4.9–6.1%, E250/D60 at 19.3–20.1%, and E300/D80 at 57.2–61.6%. The data-target ratio remains the main congestion lever, while BAL allocation and access scaling matter for how much parent activity survives the cap.

The moving-block bootstrap uses 3,200-block fast-residual chunks centrally. Repeating with chunks of 400, 800, 1,600, and 3,200 blocks leaves the capacity ranking unchanged:

| design | execution target utilization range | data limit frequency range |
|---|---:|---:|
| E225/D45 | 97.96--98.18% | 5.21--5.33% |
| E250/D60 | 97.91--98.08% | 19.02--19.26% |
| E300/D80 | 79.08--79.49% | 58.89--59.48% |

## Limitations

**Aggregate block packing.** The simulator keeps parent activity and its BAL together when a limit binds, allocating a common fraction. A real builder can select less data-intensive transactions first, so the rule is conservative for delivered execution.

**Multiscale workload.** The central workload restores recurring hourly and jointly sampled daily factors on top of the fast residuals. The access-composition shock has no separate daily or hourly component.

**Sixty days of fast-shock data.** The longer panel improves estimates of ordinary variation and persistence but still does not identify very rare monthly or annual regimes.

**Historical capacity censoring.** In the source panel, 3.1% of blocks use at least 98% of the historical gas limit. Their included execution can be below latent demand, so the upper tail of the recovered execution shock may be understated.

**Isoelastic extrapolation.** Demand curves are carried well beyond the observed range, particularly at Glamsterdam limits above 300M. All reported values remain conditional model results.

**Access composition is a reduced form.** The −0.20 correlation between the access residual and execution is preserved but not interpreted causally.

## Conclusion

Execution capacity under EIP-7999 depends jointly on the execution and data targets because BAL generated by execution is charged to the data resource. At the central 90M data limit, moderate target ratios support close to full execution-target utilization, while targets near the data limit produce frequent exclusion and can reduce delivered execution even as the configured target rises.

Separate fees deliver more execution relative to state activity, while the shared Glamsterdam fee allows the more elastic state branch to expand as the common fee falls. Separate pricing does not reduce every price-variation measure: state prices move more under EIP-7999, and an execution fee fixed at one wei can make execution-price variation appear low while the data limit excludes transactions. The data target ratio remains the main determinant of data-limit pressure across all tested specifications.

## Appendix A: Empirical properties of the demand shocks

| | execution | static data | state | access |
|---|---:|---:|---:|---:|
| standard deviation of log shock | 0.593 | 0.746 | 0.767 | 0.188 |
| correlation with the next block | −0.102 | +0.025 | +0.071 | +0.169 |
| total correlation span | 12.2 blocks | 39.5 blocks | 62.5 blocks | 10.0 blocks |
| chance next block is also in top 5%, given a top-5% block | 13.8% | 27.4% | 28.3% | 15.9% |

**Dispersion.** State creation and static data vary the most across blocks. A one-standard-deviation movement corresponds to multiplying demand by approximately 2.15 and 2.11, versus 1.81 for execution and 1.21 for access intensity. The access shock is narrower because execution and state activity already explain most of the level of BAL.

**Persistence.** Execution has a small negative next-block correlation, while static data, state, and access have positive values. Total correlation spans — 12 blocks for execution, 39 for static data, 62 for state, and 10 for access — summarize aggregate serial dependence. The longer static-data and state spans are consistent with application activity or state-creating episodes extending across several blocks.

**Tail clustering.** A top-5% shock would be followed by another top-5% shock only 5% of the time if blocks were independent. In the data, the conditional probabilities are 13.8--28.3%, approximately three to six times that benchmark. Extreme demand therefore arrives in short runs, which matters because several consecutive high-demand blocks push a fee much further than isolated shocks.

**Cross-resource co-movement.** Execution correlates with static data at 0.78 and with state at 0.71; static data and state correlate at 0.61. Sampling the three demand shocks independently would remove this joint pressure and understate how often several resource fees come under pressure simultaneously.

**Access composition.** The access shock correlates −0.20 with execution, consistent with the transaction mix shifting toward relatively compute-heavy activity in execution-heavy blocks.

## Appendix B: Cold start and steady state

### Launch transient

![Cold-start convergence](../plots/dynamic_cold_start_convergence.png)

> The left panel expresses each cold-start fee relative to its paired warm-start path at E225/D45. The right panel reports the first block at which the median cold path meets the warm path.

At E225/D45, execution begins far above its warm path because the counterfactual target is much larger than the historical anchor. Every fee reaches its paired warm path within 618 blocks (about 2.1 hours). The one-day burn-in is conservative.

### Steady state at the central configuration

![Steady-state distributions](../plots/dynamic_steady_state_distributions.png)

> Fee distributions relative to each resource's median at E225/D45 (left); included gas relative to target (right).

At E225/D45, 90% of blocks put the execution fee between 1 and 96 wei, the data fee between 31 and 2,194 wei, and the state fee between 0.15M and 8.5M wei. The execution-fee distribution requires care because its median is only 7 wei: the visible steps correspond to individual integer-wei values, and the execution fee is bounded at one wei in 15.5% of blocks.

## Appendix C: Reproducing the analysis

The kernel and sampler are `src/dynamics/batched_replay.py`, `src/dynamics/glamsterdam_replay.py`, `src/dynamics/empirical_shocks.py`, and `src/dynamics/multiscale_shocks.py`.

| Part | Script | Result table |
|---|---|---|
| Target grid | `scripts/run_multiscale_design_surface.py` | `data/7999/design_surface.csv`; `data/7999/design_surface_multiscale.csv` |
| Operating points and Glamsterdam | `scripts/run_mechanism_comparison.py` | `data/7999/mechanism_comparison.csv` |
| Target-to-limit headroom | `scripts/run_stage_b_stresses.py` | `data/7999/stage_b_stresses.csv` |
| Parameter sensitivity | `scripts/run_stage_c_robustness.py` | `data/7999/stage_c_robustness.csv` |
| Bootstrap block-length sensitivity | `scripts/run_block_length_sensitivity.py` | `data/7999/block_length_sensitivity.csv` |
| Glamsterdam limit sweep | `scripts/run_glamsterdam_comparison.py` | `data/7999/glamsterdam_comparison.csv` |

`scripts/make_pipeline_figures.py` draws the grid, operating-point, mechanism, and parameter-sensitivity figures; `scripts/make_dynamic_report_figures.py` draws the saturation, frontier, and appendix figures.
