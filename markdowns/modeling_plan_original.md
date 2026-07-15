# Modeling Plan — Driven Stationary Replay with Equilibrium Initialization

This note specifies the simulation we will use to grade EIP-7999 fee-market parameters: a stochastically-driven, elasticity-aware block replay, initialized at the counterfactual world's equilibrium, whose stationary path is the object we measure.

## 0. The three resources and two conventions

The mechanism side ([src/mechanisms/full_7999.py](../src/mechanisms/full_7999.py)) separates **execution**, **bandwidth**, and **state**. The demand side ([src/demand/model.py](../src/demand/model.py)) names its resources `execution`, `data`, `state`, where **`data` ≡ the bandwidth resource** (calldata + BAL + access-list + authorization + blob-hash bytes, mapped to resource gas). The plan uses "bandwidth" and "data" interchangeably; keep the mapping explicit in code.

Quantities are carried in **old-gas physical units** (the demand-model convention), so a world's repricing shows up purely as an effective-price change and metering multipliers are 1 at H0 by construction.

## 1. The two models and how they connect

The simulation is built from two models that are usually kept separate but here feed each other:

1. **A static equilibrium model** — a direct fixed-point solve of "demand system + a world's fee mechanism." It answers *where the repriced world settles*. Already implemented in [src/demand/equilibrium.py](../src/demand/equilibrium.py).
2. **A dynamic stochastic model** — a forward block-by-block recursion of the real base-fee mechanism, driven by exogenous demand shocks. It produces the *path* the metrics are computed on. This is the piece to build.

The equilibrium model does **not** need to feed the dynamic model as a required stage. Both compute the same fixed point — the equilibrium solver directly, the dynamic sim as an emergent attractor. The equilibrium model earns its place in three supporting roles: **initialization** (start the dynamic sim at the operating point), **validation** (the mean of the dynamic sim's stationary cloud must match the solved equilibrium), and **steady-state shortcuts** (long-run questions like annual state growth need no path).

### 1.1 Equilibrium derivation (the initializer)

A `WorldSpec` is a set of metering multipliers plus fee dimensions; each dimension carries one price and one target, and its usage is `max` over resource groups. All three candidate mechanisms are one shape:

- **G0 (Glamsterdam / 8037):** 1 dimension, groups `[[execution, data], [state]]`
- **A (8037 + separate bandwidth):** dim `execution_state` groups `[[execution],[state]]`, dim `data` groups `[[data]]`
- **B (full 7999):** 3 dimensions, one per resource

Derivation procedure:

1. **Build the H0 anchor** from observed data: per-resource physical quantities and the observed base fee(s), via `Anchor.from_single_price` (or a full `Anchor` when H0 already has separate prices). H0 is the empirical reference the demand curve is pinned to.
2. **Solve the target world** `B` with `solve_equilibrium(anchor_H0, params, world_B)`. It Gauss-Seidel-iterates each dimension's price to the point where metered usage equals target (or reports the floor / ceiling corner). Output: equilibrium prices `p*`, quantities `Q*`, and per-dimension `floor_binding` / `target_unreachable` flags.
3. **(Optional) chain through G0** with `anchor_from_equilibrium` if we want the B equilibrium expressed relative to the Glamsterdam intermediate rather than H0 directly. For pure initialization this is not required; it matters when we compare worlds on a common footing.

The equilibrium is a **derived, not simulated** object — it is deterministic given `(anchor_H0, params, world)`.

### 1.2 The stochastic demand model (the driver)

The elasticity model is **deterministic**: `demand_at_price_ratios` maps effective-price ratios to quantities. On its own, initialized at equilibrium, it produces a flat line. **All randomness is injected as an exogenous demand shock that shifts the curve**, block by block:

```
Q_it  =  D_i(p_t)  ×  s_it
         └──────┘     └───┘
     deterministic    stochastic demand shifter,  E[s_it] ≈ 1
     elastic LEVEL    (everything that moves demand independent of price)
```

- `D_i(p_t)` = `demand_at_price_ratios(anchor_H0, params, price_ratios(p_t))`, the price-responsive level. `price_ratios(p_t)[i] = effective_price_i(p_t) / anchor_H0.effective_prices[i]`.
- `s_it` = the shock. Two sourcing modes, and we use both:
  - **Empirical replay:** `s_it = historical_usage_it / baseline_it`, where the baseline is a price-neutral local trend. One run = the real realized path, carrying true autocorrelation and — critically — true cross-resource correlation. Use for the headline result and for validation.
  - **Generative (for confidence bands):** a **vector block bootstrap** — resample contiguous multi-block windows of the *joint* shock vector `(s_execution, s_data, s_state)` together. Contiguous windows preserve autocorrelation; the joint vector preserves cross-resource co-movement. The proposal demands "not single runs," so bands come from here.

Because we resample the per-resource shock vector *jointly*, total-demand variation, mix variation, and the calldata↔BAL↔state co-movement all come from one object — exactly the machinery for the "correlated spikes" open question.

### 1.3 How the driver feeds the block simulation

The base fee is **predetermined** (block *t*'s fee is set by block *t−1*'s excess), so there is **no per-block fixed point** — just a forward recursion. Per block *t*:

1. Read base fee `p_t` per resource from the carried excess accumulators via `fake_exponential` ([src/basefee/eip7999_normalized.py](../src/basefee/eip7999_normalized.py)).
2. Form price ratios `r_t` against the H0 anchor.
3. Elastic level: `Q_level = demand_at_price_ratios(anchor_H0, params, r_t)`.
4. Shock: read (empirical) or draw (bootstrap) the joint vector `s_t`.
5. Realized physical usage `u_t = Q_level ⊙ s_t`; map to metered resource gas via the world's metering multipliers / bandwidth gas-per-byte.
6. Apply the mechanism — `apply_resource_block` per resource for B, or the 8037 bottleneck path ([src/sim/eip8037.py](../src/sim/eip8037.py)) for G0/A — giving new excess, base fees, reserve-active and limit-hit / invalid flags.
7. Record the row.

The resulting dynamics are a **stochastically-driven mean-reverting system**: shocks kick usage off target; the mechanism feedback *plus* the demand elasticity pull it back. Base-fee volatility is the shock variance *filtered through* that feedback — higher elasticity absorbs a given shock at a more stable price, which is the causal channel the sweep measures, not an input we assume.

### 1.4 Equilibrium initialization

Seed excess accumulators so the block-0 base fee equals the solved equilibrium `p*` (invert `fake_exponential` at `p*`, or warm-start by running a short constant-demand pre-roll to `p*`). Then discard a burn-in window and measure the stationary portion.

**Validation cross-check:** running the driven sim initialized at H0 vs at `p*` must collapse to the same stationary cloud after burn-in, and the cloud's mean must match `p*`. This proves the equilibrium is an attractor, not an input, and catches bugs in either the solver or the mechanism.

---

## 2. Metrics extracted from the stationary path

Every metric is a functional of the recorded per-resource time series. Extend [src/sim/metrics.py](../src/sim/metrics.py) to all three resources and to the full proposal suite. Compute over the post-burn-in window; report as a distribution across bootstrap paths (median + band), not a single number.

| Metric | Definition on the path | Direction |
|---|---|---|
| Base-fee volatility (per resource) | std of log-returns of the base-fee series | lower |
| Reserve-price activation (per resource with a reserve) | mean of the reserve-active flag; plus max run-length | rare & short |
| Limit-hit frequency (per resource) | mean of the usage ≥ limit flag | low, with headroom |
| Payload propagation (bandwidth) | max realized bandwidth bytes vs the propagation budget `B` | within budget |
| Long-run state growth | cumulative realized state bytes → annualized, vs ~100 GiB/yr | on target |
| Capital efficiency | aggregate `max_fee` buffer a user needs under the unified fee | smaller |
| Correlated-spike risk | joint exceedance frequency of bandwidth & state base fees; corr of their spikes | detect early |

Notes:

- Volatility and reserve/limit frequencies are properties of the **stationary cloud**, which is why burn-in must be discarded.
- The invalid-block accounting from the passive replays carries over: over-limit draws are capped for the fee update exactly as in [src/mechanisms/full_7999.py](../src/mechanisms/full_7999.py).
- Always overlay the **passive-replay bound** (elasticity off, `s` only) and the full elasticity range so the reader sees how much elastic demand changes the conclusion.

---

## 3. Variables that must be empirically estimated

Split into "estimate from data," "bound by sensitivity," and "configure from the EIPs."

**Estimated from data**

- **H0 anchor**: per-resource physical quantities and observed effective prices — from the Xatu/RPC block pipeline already built.
- **Aggregate elasticity `eps_agg` and share elasticities `eta_state`, `eta_data`**: from the EIP-8037 elasticity series; per-resource elasticities are *outputs* of these at the anchor (`implied_anchor_elasticities`). **Swept**, not fixed — `share_mode` disagreement is itself a reported finding.
- **Shock process**: the price-neutral baseline (detrending choice), the shock distribution, and the **block-bootstrap window length** that reproduces historical autocorrelation and cross-resource correlation. Fit to the residual `s_it = usage/baseline` series.
- **BAL gas-per-byte / bandwidth metering multiplier**: the byte→resource-gas mapping (candidate `16 gas/byte`), calibrated so the H0 bandwidth quantity and price are consistent.

**Bounded by sensitivity, not estimated**

- **BAL-bandwidth price response**: this channel never varied independently in historical data, so it is swept over a plausible range rather than point-estimated. Report metrics across the range.
- **Cross-price / substitution terms** beyond what the share model implies.

**Configured from the EIPs (kept as inputs so the analysis reruns)**

- Propagation constants `t_b`, `c` and the derived bandwidth limit `B = (T2 − T1 − c) / t_b` (stretch goal 1 turns these from config into measurements).
- `CPSB`, per-resource targets and limits, `min_base_fee`, update fraction / fake-exponential denominator.
- Reserve-price anchors: blob-base-fee series for bandwidth (join from the blob sample); the state reserve anchor is an open decision, so it is a config axis.

---

## 4. Identification caveat (load-bearing)

Historical usage variation is partly exogenous shock and partly the market's response to historical prices. Defining `s_it` as raw usage *and* applying the elastic `D_i(p_t)` double-counts the price response. Handle one of two ways, and state which:

- **Pragmatic**: absorb the slow price trend into the baseline and treat the residual as price-exogenous (fine when within-window price variation is modest); the passive replay is the `elasticity-off` limit of this.
- **Rigorous**: de-elasticize the historical series first — remove the estimated price response, then re-inject the residual shock.

---

## 5. Build order

1. Extend the mechanism replay to accept a per-block **usage-producing callback** instead of a fixed usage table (the demand front-end), keeping the mechanism core unchanged. Passive = callback returns history; driven replay = callback returns `D(p_t) ⊙ s_t`.
2. Implement equilibrium initialization + burn-in discard.
3. Implement the two shock sources (empirical series; vector block bootstrap).
4. Extend `compute_metrics` to the full suite across three resources, over bootstrap paths.
5. Validation: H0-init vs equilibrium-init collapse; stationary mean vs solved `p*`; elasticity-off reduces to passive replay.
