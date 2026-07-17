# Modeling Plan — Driven Stationary Replay with Equilibrium Initialization

This note specifies the simulation we will use to grade EIP-7999 fee-market parameters: a stochastically-driven, elasticity-aware block replay, initialized at the counterfactual world's equilibrium, whose stationary path is the object we measure.

## Implementation status

The first full-7999 scaffold is now implemented in [src/dynamics](../src/dynamics) and [notebook 2.1](../notebooks/2.1-full-7999-driven-replay-scaffold.ipynb). It includes:

- the exact one-block 7999 transition shared with passive notebook 0.9;
- the independent isoelastic demand curves recovered in notebook 1.8;
- current-block and next-block fee states recorded separately;
- the exact blob-linked data reserve ratchet;
- joint empirical shocks and a vector moving-window bootstrap;
- an explicit guard against feeding daily shocks into 12-second fee updates;
- separate-resource and fixed-bundle aggregate inclusion rules;
- stationary-path summaries after a configurable burn-in; and
- deterministic checks for the notebook-2.0 warm starts and elasticity-off equivalence with passive replay.

The notebook's correlated block shocks are a controlled mechanics test, not an empirical volatility result. A longer contiguous block panel remains the main data requirement. Notebook 2.0 already uses the induced runtime-BAL equation specified below, but notebook 2.1 still treats total metered data as one isoelastic demand curve. The dynamic replay is therefore a mechanism and warm-start scaffold until the static-data/BAL decomposition is wired into its demand driver.

## 0. The three resources and two conventions

The mechanism side ([src/mechanisms/full_7999.py](../src/mechanisms/full_7999.py)) separates **execution**, **bandwidth**, and **state**. The driven demand side ([src/dynamics/demand.py](../src/dynamics/demand.py)) names its resources `execution`, `data`, `state`, where **`data` ≡ the bandwidth resource**. Its accounting is decomposed into static transaction content (calldata + access-list + authorization + blob-hash bytes) and BAL bytes induced by parent execution/state-access activity. The mapping is explicit at the replay boundary.

Elasticities are recovered from historical physical quantities. Notebook 2.0 then transports each anchor into candidate-world resource gas while preserving the historical effective price. The driven replay consumes those candidate-world gas anchors directly, so it does not apply the metering conversion a second time.

## 1. The two models and how they connect

The simulation is built from two models that are usually kept separate but here feed each other:

1. **A static equilibrium model** — a direct target-clearing calculation. Notebooks 1.9 and 2.0 provide the Glamsterdam and full-7999 integer protocol fees used for warm starts.
2. **A dynamic stochastic model** — a forward block-by-block recursion of the real base-fee mechanism, driven by exogenous demand shocks. It produces the path used for volatility, reserve, and capacity metrics.

The equilibrium model does **not** need to feed the dynamic model as a required stage. With shocks and reserve pricing disabled, both should recover the same deterministic fixed point. The equilibrium model earns its place in three supporting roles: **initialization**, **validation**, and **steady-state shortcuts** for questions that need no block path.

### 1.1 Equilibrium initialization

For full 7999, notebook 2.0 retains independent target-clearing conditions for execution and persistent state creation,

$$
g_i(p_i)=g_i^0\left(\frac{p_i}{p_i^0}\right)^{-\epsilon_i}=T_i,
$$

but decomposes data demand as

$$
D_{\mathrm{total}}(p_D)
=D_{\mathrm{static},0}
\left(\frac{p_D}{p_D^0}\right)^{-\epsilon_{\mathrm{static}}}
+B_0\left[
w_{\mathrm{state}}\frac{S^*}{S_0}
+w_{\mathrm{execution}}\frac{A^*}{A_0}
\right],
$$

where $A$ is existing-state access activity. Notebook 1.11 estimates $w_{\mathrm{state}}=0.113932$ and $w_{\mathrm{execution}}=0.886068$ from the full 6,000-block transaction attribution. Because an independently priced access index is not yet available, the aggregate model uses

$$
\frac{A_t}{A_0}\approx\left(\frac{E_t}{E_0}\right)^{\rho_A},
\qquad \rho_A=1.
$$

Total execution is a reduced-form proxy for access activity; the execution-linked BAL component is not empirically shown to follow execution demand. The suffix identifies the proxy used in the model rather than a mechanical cause for every byte. The model also sets $\gamma_{\mathrm{BAL}}=0$, so BAL has no additional direct response to the data fee after its parent activities are determined. Notebook 2.0 converts each continuous solution to the nearest fee represented by the integer fake exponential. The replay must initialize from that represented protocol fee, not from a rounded continuous fee paired with unrelated excess gas. `make_full_7999_config` performs the inverse fake-exponential warm start.

Notebook 2.0 fixes the data limit at 90M, varies its target from one sixth through one half of the limit, and sweeps execution limits from 250M through 600M with targets at half the limit. Its central capacity path preserves the observed full-7999 metered data/execution ratio, $\kappa_0=0.109795$, by setting $T_E=T_D/\kappa_0$. The full Cartesian grid is retained as an imbalance stress test. Every solution is also checked against the one-wei protocol minimum; a continuous fee below one wei means the target cannot be cleared under the mechanism even if the algebraic isoelastic solution exists.

The unconstrained equilibrium intentionally omits the data reserve. That is appropriate for initialization. With the reserve enabled, the dynamic path may settle away from the unconstrained target-clearing fee; this is a result rather than a validation failure. Notebook 2.1 therefore compares both the unconstrained data-fee start and a start at the contemporaneous blob-fee/12 threshold.

### 1.2 Demand, shocks, and transaction coupling

The intended central benchmark uses the independently recovered elasticities for execution, static data, and persistent state creation. BAL gas is then generated from the parent activity rather than shocked or price-scaled as if it were independently demanded:

$$
Q_{i,t}^{\mathrm{offered}}
=
g_i^0\left(\frac{p_{i,t}}{p_i^0}\right)^{-\epsilon_i}s_{i,t},
\qquad E[s_{i,t}]\approx 1.
$$

In the equilibrium implementation and intended replay specification,

$$
B_t=B_0\left[
w_{\mathrm{state}}
\frac{S_t}{S_0}
+w_{\mathrm{execution}}
\frac{A_t}{A_0}
\right].
$$

The priced EIP-8279 runtime anchor gives $B_0/E_0=0.080155$ BAL gas per historical execution gas, equivalent to about 5.01 kB of runtime-metered BAL content per million historical execution gas. The same 6,000-block panel estimates the 0.113932 state-linked weight and 0.886068 execution-linked weight. Until an explicit access index is available, the implementation uses $(E_t/E_0)^{\rho_A}$ with $\rho_A=1$ centrally.

The shock vector is resampled jointly, and bootstrap chunks are contiguous. This preserves contemporaneous execution/data/state co-movement and short-run persistence. It does **not** create counterfactual transaction coupling. A transaction consuming several resources should respond to several fees; that enters separately through the elasticity-matrix demand sensitivity in [src/dynamics/demand.py](../src/dynamics/demand.py). Capacity coupling is also separate: the fixed-bundle inclusion sensitivity scales the resource vector together when one hard limit binds.

Historical shocks are de-elasticized before detrending:

$$
\log y_{i,t}=\log q_{i,t}+\epsilon_i\log(p_{i,t}/p_i^0),
\qquad
s_{i,t}=\frac{\exp(\log y_{i,t}-\widehat\tau_{i,t})}
{\operatorname{mean}_t\exp(\log y_{i,t}-\widehat\tau_{i,t})}.
$$

The first trend is a centered 21-day rolling log-median, with window sensitivity required. These are elasticity-dependent implied demand shifters, not causal residuals.

### 1.3 How the driver feeds the block simulation

The base fee is **predetermined** (block *t*'s fee is set by block *t−1*'s excess), so there is **no per-block fixed point** — just a forward recursion. Per block *t*:

1. Read the current execution/data/state fees from the parent excess states.
2. Evaluate the execution, static-data, and persistent-state isoelastic demand curves at those fees.
3. Multiply the parent activities by the current joint shock vector, derive BAL gas from the shocked execution/state-access activity, and add it to static data to obtain total offered bandwidth gas. Do not shock or price-scale BAL as an independent demand resource.
4. Apply the selected inclusion rule. The central aggregate rule caps execution and total data separately; state remains uncapped. Record offered, included, and unserved gas separately.
5. Call `step_full_7999`, the same exact one-block transition used by passive notebook 0.9.
6. Record both the fee governing the current block and the fee produced for the next block, plus reserve status, targets, limits, and source shock positions.

The resulting dynamics are a **stochastically-driven mean-reverting system**: shocks kick usage off target; the mechanism feedback *plus* the demand elasticity pull it back. Base-fee volatility is the shock variance *filtered through* that feedback — higher elasticity absorbs a given shock at a more stable price, which is the causal channel the sweep measures, not an input we assume.

### 1.4 Warm-start validation

Seed excess accumulators so the block-0 base fee equals the solved equilibrium `p*` (invert `fake_exponential` at `p*`, or warm-start by running a short constant-demand pre-roll to `p*`). Then discard a burn-in window and measure the stationary portion.

**Validation cross-check:** with the reserve disabled or nonbinding, runs initialized at historical fees and at `p*` should converge after burn-in, and mean demand should remain near each target. With the reserve active, compare the unconstrained and threshold warm starts for convergence but do not require the mean data fee to equal the reserve-free equilibrium.

---

## 2. Metrics extracted from the stationary path

Every metric is computed from the recorded per-resource block path. Extend [src/dynamics/metrics.py](../src/dynamics/metrics.py) from its current compact summary to the full proposal suite. Compute over the post-burn-in window; report distributions across bootstrap paths (median + band), not one run.

| Metric | Definition on the path | Direction |
|---|---|---|
| Base-fee volatility (per resource) | std of block-to-block log fee changes | lower |
| Reserve-price activation (per resource with a reserve) | mean of the reserve-active flag; plus max run-length | rare & short |
| Limit-hit frequency (per resource) | mean of the usage ≥ limit flag | low, with headroom |
| Payload propagation (bandwidth) | max realized bandwidth bytes vs the propagation budget `B` | within budget |
| Long-run state growth | cumulative realized state bytes → annualized, vs ~100 GiB/yr | on target |
| Capital efficiency | aggregate `max_fee` buffer a user needs under the unified fee | smaller |
| Correlated-spike risk | joint exceedance frequency of bandwidth & state base fees; corr of their spikes | detect early |

Notes:

- Volatility and reserve/limit frequencies are properties of the **stationary cloud**, which is why burn-in must be discarded.
- Offered gas, included gas, and unserved gas are distinct. The output also distinguishes a resource exceeding its own limit, being rationed because another bundled resource binds, and actually filling its limit.
- Always overlay the **passive-replay bound** (elasticity off, `s` only) and the full elasticity range so the reader sees how much elastic demand changes the conclusion.

---

## 3. Variables that must be empirically estimated

Split into "estimate from data," "bound by sensitivity," and "configure from the EIPs."

**Estimated from data**

- **H0 anchor**: per-resource physical quantities and observed effective prices — from the Xatu/RPC block pipeline already built.
- **Independent elasticities `eps_execution`, `eps_data`, and `eps_state`**: recovered in notebook 1.8. Use the 35-day estimates centrally and sweep the 21-, 60-, and 75-day windows.
- **Shock process**: the price-neutral baseline, the shock distribution, and the **bootstrap window length** that reproduces historical autocorrelation and cross-resource correlation. Fit these choices to the price-adjusted shock observations.
- **Static bandwidth metering**: the byte→resource-gas mapping (candidate `16 gas/byte`) for calldata, access lists, authorization tuples, and blob hashes.
- **BAL technological coefficient**: the direct 6,000-block EIP-8279 runtime anchor gives $B_0/E_0=0.080155$ BAL gas per historical execution gas, equivalent to about 5.01 kB of runtime-metered BAL content per million execution gas.
- **Runtime BAL decomposition**: notebook 1.11 uses the full 6,000-block transaction attribution to estimate a 0.113932 state-linked runtime weight and a 0.886068 execution-linked runtime weight.

**Central reduced-form assumptions**

- **BAL-bandwidth price response $\gamma_{\mathrm{BAL}}=0$**: BAL changes through parent access and state-creation activity rather than an additional direct data-price response.
- **State-access quantity proxy $\rho_A=1$**: total execution quantity is used temporarily as the access proxy, with constant access intensity as execution scales. This is broader than state access and should be replaced by an explicit access index before interpreting the coupling structurally.
- **Cross-price complementarity and substitution terms** remain outside the aggregate model because the gas-limit events do not identify them separately.

**Configured from the EIPs (kept as inputs so the analysis reruns)**

- Propagation constants `t_b`, `c` and the derived bandwidth limit `B = (T2 − T1 − c) / t_b` (stretch goal 1 turns these from config into measurements).
- `CPSB`, per-resource targets and limits, `min_base_fee`, update fraction / fake-exponential denominator.
- The blob base-fee path that anchors the data reserve.

---

## 4. Identification caveat (load-bearing)

Historical usage variation is partly exogenous shock and partly the market's response to historical prices. Defining `s_it` as raw usage *and* applying the elastic `D_i(p_t)` double-counts the price response. Handle one of two ways, and state which:

- **Pragmatic**: absorb the slow price trend into the baseline and treat the residual as price-exogenous (fine when within-window price variation is modest); the passive replay is the `elasticity-off` limit of this.
- **Rigorous**: de-elasticize the historical observations first — remove the estimated price response, then re-inject the implied demand shifter.

---

## 5. Build order

1. **Implemented:** extract an exact public one-block transition and place a driven-demand front end around it.
2. **Implemented:** integer equilibrium warm starts, alternative data-reserve start, and burn-in-aware summaries.
3. **Implemented:** price-adjusted empirical shocks, empirical slicing, and joint moving-window bootstrap with a frequency guard.
4. **Next data task:** build a longer contiguous block panel from inexpensive execution/data/state proxies; exact RPC tracing is not required. Combine normalized within-day block variation with the daily demand condition rather than repeating daily values.
5. **Next mechanism task:** add the Glamsterdam driven runner and compare both mechanisms under identical shock positions.
6. **Next coupling task:** replace total execution gas with an explicit state-access index, then estimate cross-price exposure bounds and transaction-recipe or transaction-level packing.
7. **Implemented validation:** target demand preserves the notebook-2.0 integer warm starts; elasticity-off driven replay matches passive replay. **Remaining validation:** historical-init versus equilibrium-init convergence, bootstrap moment diagnostics, and window-length/elasticity sensitivity.
