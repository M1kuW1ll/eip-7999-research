# EIP-7999 Demand Model & Simulation — Working Notes

Status: forward plan, updated 2026-07-02 (post-meeting). Meeting decisions and the pilot-window build are folded in; remaining open items are marked in §8.

---

## 0. One-paragraph version

We simulate four "worlds": **H0** (today, observed — used to validate accounting and estimate elasticities), **G0** (Glamsterdam counterfactual — the pre-7999 baseline), **A** (8037 state + separate 7999 data), and **B** (full 7999). Demand is modeled as **one system over transaction bundles**, not three independent per-resource curves: an *aggregate* demand curve (how full the block gets — very inelastic) plus a *share* allocation (how the mix splits across execution / data / state as relative prices move). We **calibrate elasticities on H0** (the only observed world) and **anchor the counterfactual runs on G0**. Maria's 8037 elasticities apply most directly to G0 (it is her exact mechanism) and require progressively more extension as we move G0 → A → B. Resource composition and price/share relationships are estimated on the **Feb 2026 → present** single-regime window (§3); the **aggregate elasticity is imported as an external prior** from Maria's gas-limit-raise events, which give cleaner variation than any short recent window can.

---

## 1. The four worlds

| World | What it is                                                                                                                                                                                | Role |
|---|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|
| **H0** | Today's rules: EIP-7623 calldata, current access-list costs, no 8037, no BALs, actual gas/base fees                                                                                       | **Validation + estimation.** The only observed world. Reproduce its accounting to small explained error (brief's gate); fit elasticities here. |
| **G0** | Same historical transactions, **repriced under Glamsterdam**: EIP-8037 state metering + EIP-7976 calldata floor + EIP-7981 access-list cost + BALs + ~100M limit on `max(regular, state)` | **Pre-7999 reference.** 7999 ships *after* Glamsterdam, so this — not raw H0 — is where A/B start. A counterfactual built from H0, **not observed data**. |
| **A** | 8037 state (max bottleneck) **+ data as its own 7999 resource** (8131/8279-style content set — calldata, access lists, auth tuples, blob hashes, BAL — at uniform 16 gas/byte; the floors themselves are deprecated in this world)                                                                                                     | Ablation: isolates the effect of *separating data*. |
| **B** | Full 7999: execution, data, state each with own base fee / target                                                                                                                         | Candidate final design. |

**Pipeline:** `H0 (validate + estimate) → G0 (reference) → A / B (counterfactual)`.

**Do not:** treat G0 as observed data; estimate a new elasticity from G0 (it has no observed price response); or compare raw H0 shares directly to B as the headline (that smuggles the Glamsterdam repricing into the "7999 effect").

---

## 2. Using Maria's elasticities: the confidence gradient

Maria's numbers (ε_agg ≈ 0.175 event-based, η ≈ 0.43, ε_state ≈ 0.3–0.6, ε_burst ≈ 0.0–0.2) were estimated on the **8037 two-resource** structure (state vs burst) under a `max(regular, state)` bottleneck. Their applicability degrades along the ablation:

- **G0 — apply directly (highest confidence).** G0 *is* the 8037 mechanism, at a capacity (100M) reached by the same kind of gas-limit increase she used as natural experiments. This is in-regime use, not transport.
- **A — extend (medium).** Data splits out of "burst," so her single burst elasticity must be **decomposed into execution + data**. Aggregate and state numbers still hold; the burst split is the L1 gap (see §6) — Offchain gives the L2 ordering, and we may estimate the L1 split ourselves.
- **B — most assumptions (lowest).** State gets its own fee (max bottleneck gone), so the **substitution structure changes most**, and the "does 1D substitution survive separate limits?" concern is strongest here.

**Two layers stay separate even for G0:** her elasticities give the *demand response*; they do **not** do the *accounting*. Use her ε/η for how demand moves, but reprice every transaction under the target mechanism's rules for the gas vectors.

**Caveat to state explicitly:** her elasticities were measured on pre-Glamsterdam data, so applying them to a Glamsterdam-repriced G0 assumes behavioral elasticities are invariant to the repricing — the same assumption she makes for 8037. Standard, but flag it, and let it justify sweeping ε rather than fixing it.

---

## 3. Data & estimation strategy

Two data tiers, one estimation window, one external prior.

**Tier 1 — daily panel (Xatu server-side only, no RPC).** Daily aggregates, **Feb 2026 → present**: median base fee, gas limit, gas used; state-creation physical units (new slots / new accounts / code bytes → both old-schedule gas and 8037 gas); calldata zero/nonzero bytes; EIP-7623 floor-bound gas share; blob base fee + blob count; tx count. This is the regime map and the estimation input. Daily is primary (matches Maria); hourly is the robustness cut, since the estimation window below has only ~150 daily points.

**Tier 2 — stratified per-tx windows (the existing validated pipeline).** Re-run the 500-block machinery on ~20–40 windows picked off the panel (calm / fee-spike / blob-heavy / state-heavy / weekend). Purpose: per-regime **recipes and multipliers**, not elasticities. Pilot-window values to re-measure per regime: 8037 state repricing ≈ **5.8×**, EIP-7981 AL surcharge ≈ **0.4M gas/block**, 7623-floor-bound txs ≈ **0.5%**, BAL ≈ **148 KB/block**. These feed the H0→G0 repricing and the bundle recipes; RPC-dependent components (access lists, auth lists, BAL, prestate) stay window-sampled and are imputed per-regime into the panel.

**Estimation window: Feb 2026 → present.** Used to estimate current **resource composition**, the **price/share relationships** (the η-type regressions), and our **3-way state/data/execution share split** (Maria's split was 2-way; the third dimension is our extension). Why this window: it is one clean regime — post-Fusaka (Dec 2025), past the Nov 2025 45→60M raise, no known capacity events inside — and it is the regime Glamsterdam launches from. Verify event-freeness from the panel rather than assuming it; if a 2026 limit raise turns up in-window, treat it as a bonus identification event, not a problem.

**Aggregate elasticity: external prior, not re-estimated.** A short, deliberately event-free window cannot identify ε_agg — daily variation only recovers the marginal-noise number (≈0.007). We therefore import Maria's **gas-limit-raise estimates as the prior: ε_agg ≈ 0.175 ± 0.093** (events Feb / Jul / Nov 2025), with the daily-ARDL ≈0.007 as the inelastic low anchor; the 0.1–0.28 sweep is unchanged. Her three natural experiments are cleaner variation than anything the current window can produce.

**Pipeline validation gate.** Before estimating anything on Feb 2026+: rebuild Maria's window (Jan 2025 – Jan 2026) as a **one-off pull with the same queries** (her window predates the panel start) and reproduce her published numbers (daily ε_agg ≈ 0.007, η ≈ 0.43). Failure means our panel construction is wrong — fix it before trusting any new estimate.

**Stretch — EIP-7623 event study (data own-price).** May 2025: the calldata floor ×4 for data-heavy txs — the one historical episode where the data price moved independently of execution. Runs on its own event window (predates Feb 2026 by construction) and partially identifies the data elasticity the brief treats as unobservable. The BAL channel stays swept regardless.

---

## 4. Glamsterdam accounting (what G0 must include)

G0 is a counterfactual repricing, so account for **all** of these. All floor logic is **per-transaction** (floors bind per tx, never at block level).

| Change | Effect on G0 accounting |
|---|---|
| **EIP-8037** state metering (CPSB 1530, ~120 GiB/yr) | Defines `state_gas_G0`. |
| **EIP-7976** calldata floor (64 gas/byte) | Reprices calldata → into `regular_gas_G0` via the per-tx floor. |
| **EIP-7981** access-list cost (64 gas/byte, folded into floor) | Reprices access-list data → `regular_gas_G0`. |
| **EIP-7928** BALs | Payload bytes. In G0: **diagnostic only** (no separate fee). |
| **Gas limit → ~100M** on `max(regular, state)` | G0's capacity. Use Maria's **event-based** ε_agg for the demand expansion to 100M. |

G0 base-fee input: `gas_used_for_base_fee_G0 = max(regular_gas_G0, state_gas_G0)`.

**Capacity note:** G0 has **one** limit bounding `max(regular, state)`; B has **separate** per-resource limits. Part of why 7999 supports higher per-resource limits is that separating resources removes the shared bottleneck. B's limits (execution / data / state) are **swept scenarios**, not settled — the previously floated 450M/60M/75M is one (aggressive) point; Glamsterdam's own gas-limit target is nearer 200M.

---

## 5. The demand model: two knobs + a fixed-point solve

Demand is **one system**, applied at aggregate (block/day) level. Two knobs:

**Knob 1 — Aggregate (how full):**
```
T_new = T_G0 * (P_new / P_G0)^(-eps_agg)
```
- `T` = total demand; `P` = aggregate **price index**; `eps_agg` ≈ 0.175 (sweep ~0.1–0.28).
- **`P` is a constructed index, not a given price.** Under multidimensional pricing there is no single base fee — build `P` as a usage-weighted composite of the three base fees (weights = G0 shares, so `P_G0` is well-defined). Applying a 1D-estimated `eps_agg` to this composite is a mild transport assumption — note it.

**Knob 2 — Share (how the mix splits):**
```
s_i_new  ∝  s_i_G0 * (relative_price_i)^(-eta_i)     # substitution
   or
s_i_new  =  s_i_G0                                    # fixed shares (eta -> 0 endpoint)
```
- Three-way split. Cleanest as **nested**: state-vs-rest (η ≈ 0.43, *measured*), then execution-vs-data within "rest" (*unmeasured on L1*, swept). Measured top level, assumed bottom level.
- **Fixed shares is a first-class scenario, not a fallback** — it's the η → 0 end of the sweep ("resources fully independent under separate limits"), which may be *closer to the multidimensional truth* than the 1D-measured η ≈ 0.43.

**This is a solve, not a plug-in.** demand → usage → base fees → prices → demand is circular. Structure it as iterate-to-convergence:
```
guess prices
  -> aggregate demand + shares
  -> per-resource loads (from bundle recipes)
  -> run the 7999 / 8037 base-fee update
  -> new prices
  -> repeat until stable
```
Maria's "infer equilibrium base fee at a new gas limit" is exactly this fixed point. **Scaling to fill the 100M/450M limits lives *inside* this loop** — the aggregate curve, run at the low equilibrium prices the new mechanism produces, is what expands demand to fill capacity. "Scaling" and "aggregate elasticity" are the same operation, not two steps.

**BAL note:** BAL bytes are part of the *recipe* (the data-resource component of each bundle), estimated from historical state access (the Xatu-vs-RPC work). This is **upstream** of the demand model — a Step-1 accounting problem, not an elasticity problem.

**One operator, applied per link.** The solve above is a single reusable operator: *(anchor point, mechanism, elasticities) → equilibrium*. Primary route: run it twice — **H0→G0**, then re-anchor at G0 and run **G0→A / G0→B**. Robustness route: **H0→B directly**; the gap between the two routes *measures* how much the Glamsterdam demand adjustment matters — report it, don't hide it. Validation: the H0→G0 link, run with Maria's parameters, should roughly reproduce her published Glamsterdam projections before we trust G0→B.

**Reserve prices stay off for this entire stage** — a staging decision, and also because the current implementation's hard floor clamp deviates from the spec's excess-ratchet (fix that before any reserve analysis).

---

## 6. Sources → how we use them

| Source | What we take from it |
|---|---|
| **Maria — elasticity post** | The **model structure** (aggregate + share) and the **state/substitution parameters** (ε_state, η, recovery formulas), plus the **natural-experiment method** for capacity shifts. Primary for G0 and the state dimension. |
| **Maria — aggregation-function post** | The 8037 `max()`-bottleneck **failure modes** under different elasticity regimes → frames the **A vs B** comparison. |
| **Offchain Labs paper** | **Independent cross-check** (wallet-panel IV vs her ARDL — different method, same picture ⇒ calibration is trustworthy). The **per-resource ordering** (storage > calldata > compute, *Arbitrum L2*) and a **calldata prior**. The **L1 aggregate** number (≈ −0.006) matches her daily estimate. |

**Aggregate elasticity exists for both chains** (L1 ≈ −0.006, L2 ≈ −0.036); the **per-resource decomposition is Arbitrum-only** (compute −0.027, calldata −0.06, storage −0.15, refunds −0.27). Use the L1 aggregate directly; use the L2 decomposition for **ordering** (trusted) more than **levels** (flag the L1-transport question — our data resource is L1 and folds in BALs with no L2 analog).

**The level difference between the two isn't noise to reconcile — it *is* the sweep range:** low end ≈ Offchain (marginal/inelastic), high end ≈ Maria (event/equilibrium).

**The gap:** nobody has published an L1 **execution-vs-calldata** split. Options, by effort: (a) borrow the L2 *ordering*, sweep the *level* within Maria's L1 burst band (0.0–0.2); (b) **estimate it ourselves** by extending Maria's state-vs-burst method one level finer on our Xatu data — the missing number is the least-elastic / least-consequential one, and doing it would be a genuine contribution; (c) the blob→calldata spillover (see §7) gives a partial L1 calldata response directly.

---

## 7. Measured vs assumed vs swept

**Measured (from H0 / literature):**
- Aggregate elasticity — L1 (Maria daily ≈0.007 / Offchain ≈0.006; event ≈0.175).
- State own-price elasticity ≈ 0.3–0.6 (Maria).
- Share/substitution η ≈ 0.43 — **measured under 1D shared capacity**.
- Per-resource ordering (Offchain, L2).
- **blob→calldata spillover** — observable (both exist since Dencun; blob-congestion episodes are in the data). This is the *one* cross-price channel we can estimate, and it's the economic rationale for the data reserve price. Feed historical blob base fee in as an input to calldata demand.

**Assumed (stated, not measured):**
- Resource mix persists into the future.
- Elasticities invariant to Glamsterdam repricing.
- L2 per-resource ordering transports to L1.

**Swept (report across a range):**
- `DATA_GAS_PER_BAL_BYTE` — 16 / 32 / 64.
- `DATA_LIMIT_TARGET_RATIO` — 2 / 3 / 4.
- Demand level / utilization — 25 / 50 / 75 / near-saturation.
- **Substitution strength η — 0.43 (full 1D persists) → 0 (fully independent).** The headline uncertainty.
- **BAL→bandwidth cross-price** — unobservable; sensitivity only.
- Gas limits — G0 ~100M; B scenarios (200M baseline … 450M stress).
- Aggregate elasticity — 0.1–0.28.

---

## 8. Open questions — post-meeting status

**Decided:**

1. ✅ **η is a swept axis, not an input** — 0.43 (1D substitution persists) → 0 (fully independent), both first-class scenarios. A-vs-B conclusions are reported across the sweep.
2. ✅ **Elastic expansion is the primary fill mechanism** — the aggregate curve inside the fixed point expands demand to the new equilibrium; manual scaling survives only as the step-4 diagnostic (§9).
3. ✅ **Sweeps start one-at-a-time** from a representative baseline; full grid only for axes that prove first-order.
4. ✅ **Validation bar** — receipt-anchored (per-tx receipt gas sums exactly to block gas), already passing on the pilot window; supersedes rebuild-and-compare.
5. ✅ **L1 execution/data split** — attempt it ourselves: 3-way shares on Feb 2026+ (§3), EIP-7623 event study as stretch; L2-ordering + swept-level remains the fallback.

**Still open (for Maria):**

6. **Does L2 calldata elasticity transport to an L1 bandwidth resource** (which folds in BALs)?
7. **Did the 7999 reserve-price work already characterize blob→calldata spillover?** If so we inherit the event set + crossover calibration.
8. Concrete params: `DATA_GAS_PER_BAL_BYTE` value; state **hard limit vs target-only** (and: does target-only actually hold ~120 GiB/yr given inelastic state demand, or overshoot?); data limit 60M vs propagation cap (recompute at the ~9s ePBS window before treating any tension as real).

---

## 9. Build order — status and next steps

**Done (pilot window 24,120,001–24,120,500):**

0. ✅ **H0 validation** — receipt-anchored: per-tx receipt gas sums exactly to block gas (asserted in the recalc/mechanism notebooks). De-accounting works *from* observed gas rather than reconstructing it — a stronger gate than rebuild-and-compare.
1. ✅ **Resource decomposition** — tx- and block-level execution/data/state vectors, incl. per-tx 7623/7976 floor handling and AL/auth/blob/BAL bytes; no calldata double-counting (asserted).
2. ✅ **G0 accounting** — per-tx 7976 floor + 7981 surcharge + 8037 state; base-fee input `max(regular, state)` with the 1559 update.
3. ✅ **Passive G0 / A / B replays** — behaved as predicted: near-dormant fee markets at design targets; G0's max-bottleneck runs hot at today's 60M limit. Data reserve price implemented but **pending spec fix** (drop the hard floor clamp; keep only the excess-ratchet).

**Next (in order):**

4. **Manual scaling diagnostic** on the existing replay CSVs — `k_i = target_i / usage_i` per world, first-binding-resource table. Nearly free; do before any elasticity work.
5. **Tier-1 daily panel** (Jan 2025 → present, §3) + the **Maria replication gate** on her window.
6. **Regime map → Tier-2 windows** — pick windows off the panel, re-run the per-tx pipeline per window, extract per-regime multipliers/recipes.
7. **Estimation on Feb 2026+** — composition, 3-way shares, price/share regressions; η re-estimated as a check against the 0.43 prior (divergence is regime information, and the sweep covers it).
8. **Demand operator** (aggregate + nested shares + fixed point; reserve off) → chain runs: **H0→G0** (validate against Maria's published Glamsterdam projections), then **G0→A**, **G0→B**; **H0→B** direct as the route-1 robustness check.
9. **Sweeps** (§7 grid, one-at-a-time first) → then reserve-price / anchor analysis (after the spec fix) → tx-level clustering as stretch (bar unchanged: **distinct + stable + resource-mix-differentiated**; temper expectations on the priority-fee willingness-to-pay signal).
