# Project Brief — Fei Wu

**Project:** Pricing bandwidth and state growth in the EIP-7999 unified multidimensional fee market
**Duration:** 12 weeks · June 15 – September 7, 2026
**Mentor:** Maria Silva

> This brief is meant to give you a clear picture of the goal, the deliverables, and how we'll work together — while leaving the interesting research decisions genuinely open for you to make. Read the "What's fixed vs. what's yours to shape" and "Open questions" sections especially: that's where your judgment matters most. Treat the week-by-week plan as a starting point we'll refine together in your first week, not a contract.

---

## The one-paragraph version

Ethereum is moving toward a multidimensional fee market, where scarce resources are priced separately instead of being bundled into a single "gas" number. EIP-7999 lays out that design and adds **calldata** as the first separate resource. Two more pieces land in **Glamsterdam**: EIP-8037 introduces independent metering of **state-creation** gas, and EIP-7928 (Block-Level Access Lists) puts every state access into the block payload — meaning state operations now also consume **bandwidth**. Your project is to figure out, empirically, how the next version of EIP-7999 should price the two resource dimensions that these changes make real: a **bandwidth resource** (calldata + BAL bytes) and a **state-growth resource**. You'll build a simulator that replays real mainnet demand through the mechanism, recommend parameter values for each resource, and write up both a public research post and a concrete proposed update to EIP-7999.

---

## Why this project, and why now

EIP-7999's own rationale says state is the resource it most wants to separate next, but that doing so "requires a multidimensional gas repricing, which has currently not yet been completed." EIP-8037 is that repricing, and it's shipping. At the same time, EIP-7928 changes the bandwidth picture: calldata was carved out as a separate resource specifically to bound worst-case payload propagation, and BALs now add state-access data to that same payload. So the same budget calldata was meant to protect now has to account for state operations too.

That's the gap this project fills: with all three EIPs converging in Glamsterdam, someone needs to work out — with data, not just argument — how bandwidth and state should be priced as resources in 7999, including the bandwidth cost of state operations. The current parameters in the spec were set by reasoning; nobody has yet replayed real demand through the mechanism to check them.

---

## Goals

By the end of the summer, we want you to be able to:

- **Research:** give a defensible, data-backed answer to "what parameters should EIP-7999 use for the bandwidth and state resources, and why" — including the design call on how state enters the framework and how BAL bytes are priced.
- **Engineering:** leave behind an open-source simulator that others (including the EIP authors) can rerun and extend.
- **Communication:** publish an ethresear.ch post and a proposed EIP-7999 update that the community and EIP authors actually engage with.

---

## The core project

### Problem statement

Given historical mainnet demand, recommend EIP-7999 fee-market parameters for (a) a **bandwidth resource** comprising calldata **and** BAL bytes, and (b) a **state-growth resource**, such that each resource's base fee is stable and responsive, the reserve-price regime rarely triggers or sticks, and limits hold — and recommend how both dimensions, including the bandwidth cost of state operations, should be specified in EIP-7999.

### What you'll build

A **resource-agnostic simulator** for the EIP-7999 base-fee mechanism (normalized excess-gas update, `fake_exponential`, generalized EIP-7918 reserve price), instantiated for two dimensions:

- **Bandwidth = calldata + BAL bytes** — the limit is a payload-propagation constraint, not a pricing artifact: $B = (T_2 - T_1 - c)/t_b$, where $T_1$ is the attestation deadline, $T_2$ the latest possible PTC deadline, $c$ the fixed propagation overhead, and $t_b$ the per-byte propagation slope. For the core project, treat $T_1$, $T_2$, $c$, $t_b$ as configuration inputs (current working values: $t_b \approx 0.443$ ms/kB and fixed overhead $\approx 569$ ms from the p90 fit in Toni's payload-deadline analysis; ePBS timings are not final). Estimating $t_b$ and $c$ properly is stretch goal 1 — note the same estimates also determine the propagation-derived reserve-price anchor in open question 2. On that anchor: EIP-7999 currently ties calldata's reserve price to the blob base fee, but on *economic-substitution* grounds (keeping calldata from undercutting blobs as an L2 data-availability option), not propagation grounds. Whether that anchor still fits once ePBS (EIP-7732) gives the execution payload its own, shorter propagation window — decoupled from blobs, and bloated further by BALs — is an open design decision, not a given (see open questions). The new part is folding BAL bytes into this resource, priced consistently with calldata's gas-per-byte, so state-accessing transactions pay for the payload they create.
- **State growth** — the limit is a long-term state-growth constraint (EIP-8037 targets ~100 GiB/yr via `CPSB = 1174`); whether it needs its own reserve price, and against what anchor, is open.

A **demand model with elasticity** sits in front of each replay so demand responds to price rather than being passive. Note that a state operation now consumes bandwidth (via BALs), state-gas, and execution at the same time, so demand here is really for a *bundle* responding to a composite price — this extends the 8037 elasticity work rather than reusing the state estimates directly (see open questions). For state, the simulator should also implement EIP-8037's accounting (the regular/state-gas split, reservoir model, and `max()`-bottleneck base fee) so you can compare 8037-as-shipped against state-as-a-7999-resource.

### How we'll judge "good" parameters

| Metric | What it captures | Direction |
|---|---|---|
| Base-fee volatility | Variance / mean-absolute change of the resource base fee | Lower is better |
| Reserve-price activation (per resource) | For each resource that has a reserve price, how often its floor triggers and for how long | Rare and short |
| Limit-hit frequency (per resource) | Share of blocks hitting each resource's limit | Low, with headroom |
| Payload propagation (bandwidth) | Worst-case payload (calldata + BAL) vs safe propagation | Within budget |
| Long-run growth (state) | Realized annual state growth vs ~100 GiB/yr target | On target |
| Capital efficiency | Aggregate `max_fee` buffer a user needs under the unified fee | Smaller is better |

These are the metrics we think matter — but deciding how to weight them, and whether we're missing one, is part of your job (see open questions).

---

## What's fixed vs. what's yours to shape

**Fixed (the things that make this *this* project):**

- The two-resource framing: a bandwidth resource (calldata + BALs) and a state-growth resource, grounded in EIP-7999 / 8037 / 7928.
- An **empirical, data-driven** approach — recommendations come from replaying real demand, not from intuition alone.
- The deliverables: a simulator, parameter recommendations, an ethresear.ch post, and a proposed EIP-7999 update.

**Yours to shape (we have opinions, not answers):**

- The design of the demand/elasticity model and how strategic vs. passive you make it.
- The parameter search strategy and how you explore the space.
- The metric suite — weighting, additions, and what "optimal" means in the end.
- The actual recommended parameter values (obviously) and the reserve-price/anchor decision for state.
- How BAL bytes should be metered and priced relative to calldata.
- Tooling, language, and how you structure the simulator.
- **The framing itself** — if your analysis suggests a better way to think about these resources than we've laid out here, we want to hear it. Pushing back is encouraged.

---

## Open questions we genuinely don't have answers to

These are real research questions, not exercises with known solutions. We'd love your view on any of them, and you should feel free to add to the list:

- Should the state resource have its own EIP-7918 reserve price? If so, anchored to what — blob, calldata, or something else?
- Should the bandwidth resource keep EIP-7999's blob-base-fee anchor for its reserve price? That anchor is an economic-substitution argument (don't undercut blob DA) and predates ePBS. After EIP-7732 the execution payload has its own shorter propagation window, decoupled from blobs and bloated further by BALs — which argues for a propagation-derived floor (absolute, or anchored to execution gas) instead of, or alongside, the blob anchor. Which is right, and why?
- Is EIP-8037's single-bottleneck base fee (`max(regular, state)`) actually worse in practice than 7999's separate base fees, or is the simplicity worth the cost? Under what demand patterns does the difference matter?
- Now that a state operation consumes state-gas, bandwidth (via BALs), and execution at once, do the 8037 elasticities still describe the right demand object? How should the bundle's response to its composite price — and the cross-price effect of expensive bandwidth on state-heavy transactions — be modeled, given the BAL-bandwidth price channel was never observed varying independently in historical data?
- How much does using elastic demand instead of passive replay actually change the conclusions here?
- Under one unified `max_fee`, is there a failure mode when bandwidth and state base fees spike together (correlated demand)? Correlated spikes also inflate the $b_\text{max}$ term in overflow-based funding checks (see stretch goal 5). How would you detect it early?

---

## Plan (a default we'll refine together)

Dates are guide-rails. In Week 1 we expect you to revisit this plan and propose changes.

**Phase 1 — Data & baselines (Weeks 1–2, Jun 15–28).** Onboarding; query all the per-block historical data — calldata gas usage and new-state-bytes — from Xatu. Estimate per-block BAL sizes programmatically from historical state-access patterns (Maria will share a repo with existing code that does this as a starting point). Reproduce today's calldata accounting (incl. the EIP-7623 floor 7999 deprecates) and EIP-8037's state-gas accounting as baselines.

**Phase 2 — Mechanism implementation (Weeks 3–4, Jun 29–Jul 12).** Implement the 7999 base-fee mechanism as a resource-agnostic module, validated against the EIP's Python helpers. Also implement 8037's bottleneck single-fee path for state. Passive replays as correctness checks.

**Phase 3 — Demand models (Weeks 5–7, Jul 13–Aug 2).** Build bandwidth and state demand models with elasticity. Because a state operation now consumes state-gas, bandwidth (via BALs), and execution at once, this means *extending* the 8037 elasticity work into a multidimensional bundle demand model rather than reusing the state estimates as-is: the 8037 own-price elasticity informs the bundle's response to its composite price, while the BAL-bandwidth response — a channel that never varied independently in historical data — is bounded via sensitivity analysis rather than estimated. Make replays responsive; finalize metrics.

**Phase 4 — Parameter sweep & integration analysis (Weeks 8–9, Aug 3–16).** Sweep each resource's target ratio, reserve factor/anchor, and the shared update fraction. Settle the BAL gas-per-byte and the state reserve-price/anchor questions. Produce recommendations with sensitivity analysis.

**Phase 5 — Write-up, proposed spec update & handoff (Weeks 10–12, Aug 17–Sep 7).** Write the ethresear.ch post; draft a concrete proposed EIP-7999 update (adds state as a resource; extends calldata into a bandwidth resource that prices BALs); open-source the simulator; final presentation. Week 12 is buffer + handoff.

---

## Deliverables & definition of done

- **Simulator** (open-source, resource-agnostic) that reproduces the calldata and EIP-8037 state baselines to within a small, explained error, and that someone else can rerun.
- **Parameter recommendations** for both resources, backed by the metric suite and a sensitivity analysis — not single runs.
- **Integration analysis** with a clear, defensible answer on how bandwidth (incl. BALs) and state enter 7999, including the reserve-price decisions.
- **ethresear.ch post** in the style of the existing 7999/8037 series.
- **Proposed EIP-7999 update**, good enough to share with the EIP authors.

---

## Stretch goals

If you have time and interest, in rough priority order. Each is self-contained.

1. **Worst-case payload-propagation bound for the bandwidth limit.** Use ethPandaOps Xatu / `lab.ethpandaops.io` data to relate block payload size (calldata + BAL) to attestation timing and propagation delay — i.e., estimate $t_b$ and $c$ in $B = (T_2 - T_1 - c)/t_b$ — and derive a data-backed safe value for the bandwidth limit. The highest-value extension, since it turns the limit from an assumption into a measurement, and the same estimates feed the propagation-derived reserve-price anchor (open question 2). Keep the limit byte-denominated so $B$ can double as the byte cap in a future variable-PTC-deadline / affine-metering design (Anders' ethresear.ch proposal) — modeling that design itself is out of scope.
2. **State vs history pricing: recurring vs one-time.** You raised that time-weighted (rent-like) pricing is hard and that history expiry complicates it — investigate one-time (as 8037 does) vs recurring pricing for state growth.
3. **LOG opcode repricing.** You flagged LOG as underpriced (8 gas/byte vs 16 for calldata) despite consuming bandwidth/history. Measure LOG-data volume and assess whether it belongs in the bandwidth resource.
4. **Builder heuristic revenue gap.** With two dimensions that can both bind, define a simple local-builder packing heuristic and measure revenue lost vs an optimal packer — testing the claim that centralization impact is negligible.
5. **Unified `max_fee` buffer & wallet fee-setting.** Model how a wallet should size the single `max_fee` buffer given volatility across both base fees, and quantify the capital-efficiency gain vs per-resource max fees. The buffer also depends on which gas-overflow design ships for legacy `CALL` observability (see Anders' [gas overflow post](https://ethresear.ch/t/gas-overflow-for-multidimensional-fee-markets/24766)): aggregate EVM gas prices the whole limit at the most expensive resource, universal overflow shrinks that to the overflow amount ($o_u \cdot b_\text{max}$), and the overflow vector removes it. Quantifying the capital-efficiency gap between these funding checks on simulated base-fee paths would be directly useful to the EIP authors choosing between them.

---

## How we'll work together

- **Weekly 1:1** with Maria to review progress, unblock, and make design calls together.
- **Work in the open:** code and notebooks live in a public repo from Week 1; rough findings get shared early as public notes rather than saved up for a big reveal (e.g.. markdown or HackMD). Early, messy results are welcome — they're how we course-correct.
- **Mid-point check-in (~Week 6–7):** short readout of progress and direction.
- **Final presentation (Week 12):** to the team, plus the published post and proposed update.

---

## Your first week

A concrete on-ramp (we'll adjust):

1. Read EIP-7999, then EIP-8037 and EIP-7928, and skim the EIP-8037 ethresear.ch elasticity/aggregation series.
2. Create the public repo for the project — code, notebooks, and notes will live here from day one.
3. Get access to Xatu and the BAL-estimation repo, and reproduce a single day of historical calldata, new-state-bytes, and estimated BAL sizes.
4. Run the `fake_exponential` / base-fee update from the 7999 spec on toy inputs until it's second nature.
5. Come to the first 1:1 with your own redline of this plan and your initial take on at least one open question.

---

## Risks & mitigations

- **BAL-size accuracy.** BALs don't exist in historical mainnet, so they're estimated programmatically from state-access patterns (starting from the repo Maria shares).
- **Scope across two resources + BALs.** The simulator is resource-agnostic, so each dimension is an instantiation of one mechanism, not a separate build.
- **Demand-elasticity uncertainty.** Extend the 8037 elasticities into the bundle model, bound the BAL-bandwidth response rather than estimate it, report across a range, and always show the passive-replay bound as a reference.
- **Moving target (Glamsterdam).** Keep `CPSB`, limits, targets, and BAL encoding sizes as configuration inputs, so the analysis reruns against final values.

---

## Tool

- BAL size estimation: https://github.com/nerolation/eth-bal-analysis. Use RLP encoding with something called FLAG?
- Xatu dataset: https://ethpandaops.io/data/xatu/schema/cbt/

## References

**EIPs**

- [EIP-7999 — Unified multidimensional fee market](https://eips.ethereum.org/EIPS/eip-7999) (Draft) · [discussion](https://ethereum-magicians.org/t/eip-7999-unified-multidimensional-fee-market/25010)
- [EIP-8037 — State Creation Gas Cost Increase](https://eips.ethereum.org/EIPS/eip-8037) (Draft; targeted for Glamsterdam) · [discussion](https://ethereum-magicians.org/t/eip-8037-state-creation-gas-cost-increase/25694)
- [EIP-7928 — Block-Level Access Lists](https://eips.ethereum.org/EIPS/eip-7928) (Draft; targeted for Glamsterdam) · [discussion](https://ethereum-magicians.org/t/eip-7928-block-level-access-lists/23337)
- [EIP-7732 — Enshrined Proposer-Builder Separation (ePBS)](https://eips.ethereum.org/EIPS/eip-7732) (targeted for Glamsterdam)
- Mechanism lineage referenced by 7999 / 8037: [EIP-7918](https://eips.ethereum.org/EIPS/eip-7918), [EIP-7706](https://eips.ethereum.org/EIPS/eip-7706), [EIP-7623](https://eips.ethereum.org/EIPS/eip-7623), [EIP-4844](https://eips.ethereum.org/EIPS/eip-4844), [EIP-7825](https://eips.ethereum.org/EIPS/eip-7825)

**EIP-8037 ethresear.ch series**

- [Two-resource metered gas equations for EIP-8037](https://ethresear.ch/t/two-resource-metered-gas-equations-for-eip-8037/23849)
- [State growth scenarios and the impact of repricings](https://ethresear.ch/t/state-growth-scenarios-and-the-impact-of-repricings/23476)
- [Analysis of different aggregation functions for EIP-8037 under different elasticity regimes](https://ethresear.ch/t/analysis-of-different-aggregation-functions-for-eip-8037-under-different-elasticity-regimes/24033)
- [Empirical analysis of price elasticities for Ethereum state and burst resources](https://ethresear.ch/t/empirical-analysis-of-price-elasticities-for-ethereum-state-and-burst-resources/24166)
- [Optimal aggregation functions for EIP-8037 under empirical elasticities](https://ethresear.ch/t/optimal-aggregation-functions-for-eip-8037-under-empirical-elasticities/24184)

**Multidimensional fee markets — background**

- Anders Elowsson, [Gas overflow for multidimensional fee markets](https://ethresear.ch/t/gas-overflow-for-multidimensional-fee-markets/24766) (May 2026) — directly on EIP-7999, including its relationship to EIP-8037 and splitting state creation into its own resource
- Anders Elowsson, [The case for a variable PTC deadline with affine metering and a unified calldata price](https://ethresear.ch/t/the-case-for-a-variable-ptc-deadline-with-affine-metering-and-a-unified-calldata-price/24708) (Apr 2026) — how a byte-denominated bandwidth limit doubles as the cap in a variable-deadline design (context for stretch goal 1; out of scope to model)
- Vitalik Buterin, [Multidimensional gas pricing](https://vitalik.eth.limo/general/2024/05/09/multidim.html) (2024)
- [Multidimensional EIP-1559](https://ethresear.ch/t/multidimensional-eip-1559/11651)
- [Going multidimensional: an empirical analysis on gas metering in the EVM](https://ethresear.ch/t/going-multidimensional-an-empirical-analysis-on-gas-metering-in-the-evm/22621)
- [A practical proposal for multidimensional gas metering](https://ethresear.ch/t/a-practical-proposal-for-multidimensional-gas-metering/22668)

**Data**

- [ethPandaOps Xatu / lab.ethpandaops.io](https://lab.ethpandaops.io/)
