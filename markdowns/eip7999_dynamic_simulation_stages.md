# EIP-7999 Dynamic Simulation: Experimental Design and Stages

**Status:** Static equilibrium complete; Stage A and Stage B dynamic experiments complete; Stage C, the Glamsterdam comparison, and Stage D remain.

## 1. Purpose

The static EIP-7999 analysis identifies whether a proposed vector of execution, data, and state targets can clear in steady state while all base fees remain at least 1 wei. It also defines the **execution-clearing boundary**: for a given data target, the largest execution target that can still be fully used before the execution base fee reaches its minimum.

The dynamic simulation asks the questions that the static equilibrium cannot answer:

- How much hard-limit headroom is needed above a statically feasible target?
- How volatile are execution, data, and state fees under block-level demand variation?
- How often do execution or data hit their hard limits?
- How much demand is rationed rather than cleared through price?
- How quickly do fees recover from demand shocks?
- How sensitive are these results to the elasticities, BAL allocation, and access-scaling assumptions?
- How does EIP-7999 compare with Glamsterdam under the same latent workloads?

The central experimental distinction is:

\[
\text{targets choose the steady-state operating point,}
\qquad
\text{limits choose burst tolerance.}
\]

A target pair may be statically feasible but dynamically unreliable if the hard limit leaves too little room for block-level bursts.

---

## 2. Dynamic demand model

The simulation tracks three primitive activities and one workload-composition factor:

\[
(s_{E,t},\ s_{D,t},\ s_{S,t},\ a_t),
\]

where:

- \(s_{E,t}\) is the execution demand condition;
- \(s_{D,t}\) is the static transaction-data demand condition;
- \(s_{S,t}\) is the state-creation demand condition;
- \(a_t\) is the runtime-BAL access-composition factor.

The parent activities respond to BAL-inclusive prices. With

\[
R_{E,t}=\frac{q_{E,t}}{q_E^0},
\]

execution activity satisfies

\[
R_{E,t}
=
 s_{E,t}
\left[
\frac{
 m_E b_{E,t}
 +w_E R_{E,t}^{\rho_A-1}b_{D,t}
}{p^0}
\right]^{-\epsilon_E}.
\]

State activity satisfies

\[
q_{S,t}
=
q_S^0 s_{S,t}
\left[
\frac{m_S b_{S,t}+w_S b_{D,t}}{p^0}
\right]^{-\epsilon_S}.
\]

Static data follows

\[
g_{\mathrm{static},t}
=
g_{\mathrm{static}}^0 s_{D,t}
\left(
\frac{m_D b_{D,t}}{p^0}
\right)^{-\epsilon_D}.
\]

Runtime BAL is induced by realized parent activity:

\[
g_{\mathrm{BAL},t}
=
a_t
\left(
 w_E q_E^0 R_{E,t}^{\rho_A}
 +w_S q_{S,t}
\right).
\]

The fee mechanism therefore receives

\[
G_{E,t}=m_E q_{E,t},
\qquad
G_{S,t}=m_S q_{S,t},
\qquad
G_{D,t}=g_{\mathrm{static},t}+g_{\mathrm{BAL},t}.
\]

There is no independent BAL demand curve in the central model. A higher data fee raises the prices of the execution and state activities that generate BAL, reducing parent activity and hence runtime BAL.

### Block timing

For each block \(t\):

1. Current base fees and the current shock vector determine offered execution, static data, state creation, and runtime BAL.
2. Hard limits determine included gas and rationed demand.
3. Included usage updates the three excess-gas states using the exact integer fee recursion.
4. The updated excess-gas states determine the base fees for block \(t+1\).

The simulator uses parent/BAL-consistent aggregate clipping: when a parent activity is excluded, the linked BAL is excluded consistently. This remains an aggregate approximation because the simulation does not identify the exact transaction set included under a hard cap.

---

## 3. Parameters: design variables versus model uncertainty

### 3.1 Protocol-design variables

These are the parameters that the protocol designer can choose:

\[
T_E,\ L_E,\ T_D,\ L_D,\ T_S.
\]

- \(T_E\): execution target;
- \(L_E\): execution hard limit;
- \(T_D\): data target;
- \(L_D\): data hard limit;
- \(T_S\): state target.

The central analysis holds the state target at 75M and gives state no hard limit. The main design space is therefore

\[
(T_E,L_E,T_D,L_D).
\]

Targets determine the static equilibrium. Limits do not generally change that equilibrium, but they determine burst headroom, hard-limit hits, and rationing.

### 3.2 Model-uncertainty parameters

These are not protocol controls:

\[
\lambda,
\qquad
\rho_A,
\qquad
(\epsilon_E,\epsilon_D,\epsilon_S),
\]

and, in later sensitivities, the speed at which demand responds to price.

The maintained values are:

- \(\lambda\in\{0,0.5,1\}\): allocation of co-produced BAL between execution/access and state activity;
- \(\rho_A\in\{0.75,1,1.25\}\): sub-proportional, proportional, or super-proportional access scaling;
- 21-, 35-, 60-, and 75-day linked elasticity vectors.

These parameters are used to test whether a design remains acceptable under alternative demand models. They are not optimized as protocol settings.

---

## 4. Empirical shock construction

### 4.1 Primitive-resource panel

A contiguous block panel is required because the headline dynamic metrics depend on persistence and burst duration. The original 6,000-block sample was deliberately spaced and could estimate marginal dispersion but not block-to-block persistence.

The empirical panel supplies block-level:

- execution activity;
- static transaction data;
- state-creation activity;
- runtime BAL;
- historical base fee;
- timestamps and censorship/full-block indicators.

The primitive shocks are price-adjusted demand residuals. For resource \(i\), the observed quantity is divided by the maintained demand curve evaluated at the observed price, after removing slow trends and intraday shape.

### 4.2 Access-composition residual

The access residual is

\[
a_t
=
\frac{
 g_{\mathrm{BAL},t}^{\mathrm{observed}}
}{
 w_E q_E^0 R_{E,t}^{\rho_A}
 +w_S q_{S,t}
}.
\]

The contiguous pull showed that \(a_t\) has short persistence but is negatively correlated with execution activity, approximately \(-0.19\) in the central residual construction. It therefore cannot be sampled independently without changing the joint workload distribution.

The bootstrap samples

\[
(s_E,s_D,s_S,a)
\]

jointly in contiguous blocks. The block length is tested around the measured correlation scale.

### 4.3 Sampler validation

Every empirical or bootstrap panel must pass automatic checks for:

- missing and zero observations;
- source and bootstrap means;
- standard deviations and quantiles;
- cross-resource correlations;
- short-lag autocorrelations;
- exceedance frequencies and run lengths;
- no silent zero-padding or index misalignment.

The zero-BAL observations must be explicitly classified as genuine zeros or failed reconstructions. Genuine zeros should be represented as a point mass rather than silently removed from a log transform.

---

## 5. Initialization regimes

Warm and cold starts answer different questions and are run separately.

### 5.1 Warm start

Each design starts from its own static equilibrium:

- above the execution-clearing boundary: all resources start at their target-clearing equilibrium;
- on the boundary: execution starts at 1 wei and exactly fills its target;
- below the boundary: execution starts from the valid floor-bound equilibrium and underfills.

A warm start answers:

> Once this configuration has settled, how stable is it under recurring demand shocks?

Warm starts are the main basis for fee volatility, floor frequency, limit-hit frequency, rationing, and ordinary recovery metrics.

### 5.2 Bundle-cost-equivalent cold start

The central migration start preserves historical BAL-inclusive parent prices as closely as possible:

\[
b_{D,0}=\frac{p^0}{m_D},
\]

\[
b_{E,0}
=
\max\left\{
1,
\frac{p^0-w_E b_{D,0}}{m_E}
\right\},
\]

\[
b_{S,0}
=
\max\left\{
1,
\frac{p^0-w_S b_{D,0}}{m_S}
\right\}.
\]

A cold start answers:

> How quickly and safely does the mechanism discover the new equilibrium after activation or a regime change?

A separate all-fees-at-one-wei run is retained as an adverse underpriced-launch stress.

---

## 6. Stage overview

| Stage | Main question | Inputs | Status |
|---|---|---|---|
| Stage 0 | Are the accounting and fee mechanics correct? | Unit and synthetic shocks | Complete |
| Empirical workstream | What is the joint block-level shock process? | Contiguous execution/data/state/BAL panel | Complete for ordinary dynamics |
| Stage A | Which target/limit designs are dynamically viable under baseline demand? | Central and adverse calibrations | Complete |
| Stage B | How do shortlisted designs react to shocks and migration? | Named stresses and cold starts | Complete in substance; event-window stress summaries should be regenerated before Stage C |
| Stage C | Is the headroom conclusion robust to \(\lambda\), \(\rho_A\), and elasticity uncertainty? | Full 36-specification grid on shortlisted designs | Next |
| Glamsterdam comparison | Which mechanism performs better under the same latent workload? | Same shocks, mechanism-specific accounting | Remaining |
| Stage D | What are the extreme tail risks? | Longer source panel and many replications | Remaining |

---

## 7. Stage 0 — mechanics and kernel validation

### Purpose

Stage 0 validates the simulation instrument before interpreting any output economically.

### Tests

- Unit shocks preserve a static equilibrium indefinitely.
- Vectorized fee updates are bit-exact against the reference integer `fake_exponential` implementation.
- Excess-gas deltas are floored and clamped exactly as required.
- Dynamic floor-bound execution fill matches the independent static solver.
- Data-component identities hold after quantization and inclusion.
- Boundary solutions at 1 wei are handled correctly.
- Long unit-shock runs exhibit zero drift.

### Current validation

The kernel has reproduced static floor-bound execution fills independently and has been verified against the integer fee formula over thousands of fee values. A float/integer excess-delta drift was found and fixed before the design grid was evaluated.

### Stage gate

No design results are interpreted until all deterministic regression tests pass.

---

## 8. Stage A — baseline target/limit screening

### Purpose

Stage A asks:

> Is poor dynamic performance caused by the equilibrium target pair itself, or by insufficient hard-limit headroom above it?

### Design construction

Target pairs are chosen relative to the static execution-clearing boundary. The central grid contains execution targets near 200M, 250M, and 300M, with data targets below, on, and above the static boundary.

The crucial controlled comparison holds targets fixed and changes only the data limit:

- `E300_D77_fixed90M`: \(T_E=300\)M, \(T_D\approx77\)M, \(L_D=90\)M;
- `E300_D77_matched2x`: same targets, but \(L_D=154\)M.

A second high-target design uses \(T_D=85\)M under the fixed 90M limit.

### Screening calibrations

Stage A is run under:

- the 35-day central elasticity vector;
- an adverse lower-execution-demand vector.

The design shortlist is the union of designs that are nondominated or near-nondominated under either calibration. Absolute governance thresholds are not imposed at this stage.

### Main Stage A result

The same statically feasible targets behave very differently when the limit changes. Under the empirical baseline shocks, moving from a 90M data limit to a matched \(2\times\) limit reduces hard-limit hits and rationing by more than an order of magnitude.

The static analysis therefore supplies only one necessary condition:

\[
T_D\text{ must support the steady-state equilibrium.}
\]

The dynamic analysis adds a second:

\[
L_D-T_D\text{ must provide enough burst headroom.}
\]

### Screening method

Exact Pareto dominance was weak because several metrics measured the same capacity-pressure factor. The primary axes are reduced to:

1. mean included execution or execution fill;
2. normalized rationed data;
3. a user-cost or price-stability metric.

Limit-hit frequency, longest run, and raw data-fee volatility remain supporting diagnostics. Future screening uses \(\varepsilon\)-dominance, where \(\varepsilon\) is at least as large as Monte Carlo uncertainty or the smallest practically meaningful difference.

---

## 9. Stage B — shocks, saturation pathology, and migration

### Purpose

Stage B characterizes shortlisted designs under directional shocks and cold starts.

### Stress environments

The named stress set includes:

- execution demand shock;
- static-data shock;
- state-creation shock;
- access-only shock;
- execution-plus-access shock;
- broad persistent shock.

A central pulse uses a specified amplitude and decay or half-life. The same background path and seed are used for baseline and stressed runs.

### Paired event-window metrics

Whole-week averages dilute a short pulse. Stress effects are therefore measured in an event window around the pulse and as a paired difference against the same seed’s baseline:

\[
\Delta M_{d,s,k}
=
M_{d,s,k}^{\mathrm{stress}}(W)
-
M_{d,s}^{\mathrm{baseline}}(W).
\]

The stress window should cover several decay half-lives. Headline metrics include:

- incremental limit-hit blocks;
- incremental rationed gas;
- peak log-fee change relative to baseline;
- integrated log-fee response;
- time to peak and recovery time;
- longest additional limit-hit run.

### Hard-cap-induced price-signal compression

Stage B identified a mechanism pathology:

> When the data target lies close to the hard limit, offered demand is clipped before the fee controller can observe its full magnitude. Scarcity is increasingly resolved through exclusion rather than price.

The fee controller sees included usage, so the maximum positive excess-gas increment in a saturated block is

\[
L_D-T_D.
\]

Define normalized positive controller headroom:

\[
h_D=\frac{L_D-T_D}{T_D}.
\]

For the central 300M designs:

| Design | Data-limit hits | Peak data-fee multiple | Rationed data |
|---|---:|---:|---:|
| E300/D77, matched \(2\times\) limit | 3.1% | 18.2× | 0.85M gas/block |
| E300/D77, fixed 90M limit | 52.8% | 13.7× | 22.6M gas/block |
| E300/D85, fixed 90M limit | 79.4% | 5.9× | 61.4M gas/block |

The worst design has the smallest fee response. That is not good fee stability; it is a compressed price signal caused by persistent saturation.

### Price versus rationing decomposition

For a paired baseline and stress run, define:

- \(G_t\): stress demand evaluated at the baseline fee;
- \(O_t\): stress demand after the stress-run price response;
- \(I_t\): included demand after hard-limit clipping.

Then

\[
G_t-O_t
\]

is demand absorbed through price, while

\[
O_t-I_t
\]

is demand absorbed through rationing. This decomposition is the preferred diagnosis of whether the fee mechanism or the hard cap is allocating scarcity.

### Baseline fee volatility

Large data-fee multiples are a direct implication of inelastic demand and measured block-level variation. Under a simple isoelastic clearing calculation,

\[
\Delta\log p\approx\frac{\Delta\log s}{\epsilon_D}.
\]

With \(\epsilon_D\approx0.23\), moderate log-demand shocks can require order-of-magnitude price movements. Reports should therefore show both:

- fee multiples and log changes;
- absolute fees and representative transaction-bundle costs.

### Cold-start result

The bundle-cost-equivalent migration start causes only a modest first-day loss in execution fill relative to the warm start. The initial evidence suggests that migration cost is secondary to the steady-state cost of insufficient data-limit headroom.

### Stage gate

Before Stage C, regenerate the stress tables with paired event-window metrics rather than whole-horizon averages.

---

## 10. Stage C — structural and elasticity robustness

### Purpose

Stage C asks:

> Does the dynamic value of target-to-limit headroom survive uncertainty in BAL routing, access scaling, and the demand calibration?

### Model grid

For shortlisted designs, run all

\[
3\times3\times4=36
\]

combinations of:

\[
\lambda\in\{0,0.5,1\},
\qquad
\rho_A\in\{0.75,1,1.25\},
\]

and the four linked elasticity vectors.

### Demand-feasibility stratification

Every design/specification pair is classified before interpretation:

1. **Demand-feasible:** execution can reach the target absent the BAL charge.
2. **BAL/data-constrained:** execution demand is sufficient, but BAL pricing or data capacity can push execution to the fee floor.
3. **Demand-infeasible:** execution cannot reach the target even with a 1-wei execution fee and zero BAL charge.

Only the first two categories identify the effect of data targets and limits. In the third category, more data capacity cannot solve the underfill.

### Shock re-estimation

Primitive demand residuals are re-estimated when the elasticity vector changes. The access residual should be recomputed for each \((\lambda,\rho_A)\) specification where practical; otherwise, transporting the central residual must be stated explicitly as an additional assumption.

### Headline robustness statistic

The primary Stage C comparison is the ratio

\[
\frac{
\text{rationing under the fixed 90M limit}
}{
\text{rationing under matched headroom}
},
\]

with an analogous ratio for limit-hit frequency.

If matched headroom reduces rationing by an order of magnitude across most demand-feasible specifications, the Stage B conclusion is structurally robust.

---

## 11. Glamsterdam comparison

### Common latent workload

The same latent workload path

\[
(s_E,s_D,s_S,a)
\]

is applied to both mechanisms.

Under EIP-7999, \(a_t\) changes runtime BAL data gas and therefore affects the data fee and inclusion.

Under Glamsterdam, the same \(a_t\) changes the BAL payload diagnostic, but BAL is not separately priced and does not directly enter the shared fee update in the central comparison. Any effect of access composition on Glamsterdam regular gas requires a separately calibrated coefficient and is treated as a sensitivity.

This convention isolates the mechanism difference:

> The same access-heavy block exists in both worlds, but only EIP-7999 internalizes its BAL footprint through a separate data price.

### Fair comparison rules

Both mechanisms use:

- the same activity anchors;
- the same elasticity assumptions;
- the same shock paths and seeds;
- the same warm-start or cold-start category;
- the same burn-in and reporting horizon.

Warm-start each mechanism at its own equilibrium. Cold-start each from a historically comparable price state.

### Capacity comparisons

Report at least two comparisons:

1. **Matched nominal execution capacity:** the same execution/shared target and limit.
2. **Matched realized throughput:** parameters chosen so both mechanisms deliver similar average execution, then compare volatility, rationing, and user cost.

Do not compare raw base fees alone. Compare effective resource prices and representative transaction-bundle costs.

---

## 12. Stage D — extreme-tail validation

### Purpose

Stage D estimates the distribution of rare dynamic outcomes:

- weekly maximum fee spike;
- longest limit-hit run;
- worst rationing episode;
- extreme recovery time;
- joint execution/data saturation.

### Data requirement

The current 14-day contiguous panel is sufficient for ordinary block dynamics but not for strong claims about rare weekly or monthly regimes. Stage D should use:

- 30–60 contiguous days; or
- several non-overlapping windows spanning quiet, normal, and busy regimes.

Bootstrapping a short source panel many times estimates the distribution implied by that panel very precisely, but it does not create unobserved tail regimes.

### Replication counts

The replication is the statistical unit, not the individual block. Suggested starting points are:

- 32–64 weekly replications for means and ordinary volatility;
- 128–256 for longest-run and maximum-overshoot metrics;
- more or longer horizons when final design rankings depend on tail quantities.

Seeds are added in batches until the confidence interval of the decision-relevant metric is sufficiently narrow.

---

## 13. Metrics

### 13.1 Primary design metrics

- mean included execution gas;
- execution target fill;
- normalized rationed data gas;
- representative transaction-bundle cost and cost volatility;
- hard-limit size or implied worst-case payload as a physical-network cost.

### 13.2 Fee behavior

For each resource:

- median and mean base fee;
- standard deviation of log fee changes;
- p95 and p99 absolute log fee change;
- fraction of blocks at 1 wei;
- longest 1-wei run;
- stress overshoot and recovery time.

### 13.3 Capacity reliability

- target-exceedance frequency;
- hard-limit-hit frequency;
- longest limit-hit run;
- p95 and p99 utilization;
- offered/included ratio;
- cumulative and average rationed gas;
- simultaneous execution/data limit hits.

### 13.4 BAL coupling

- BAL share of total data gas;
- execution-linked and state-linked BAL;
- execution demand suppressed by the BAL charge;
- fraction of the execution parent price paid through data;
- correlation between execution and data fee changes.

### 13.5 Cold-start metrics

- time to enter and remain within an equilibrium-fee band;
- maximum overshoot and underpricing;
- cumulative limit-hit blocks before convergence;
- cumulative rationed gas;
- cumulative representative user cost during migration.

---

## 14. Design selection

### Relative screening

Early stages use relative screening only. A design is removed when another design is no worse on every primary axis and strictly better on at least one, allowing for an \(\varepsilon\) tolerance based on Monte Carlo uncertainty or practical significance.

### Final selection

Absolute reliability thresholds are governance inputs and are applied only after the full dynamic and network-capacity analysis. Final recommendations must combine:

\[
\text{static equilibrium feasibility}
+
\text{dynamic reliability}
+
\text{bandwidth and propagation safety}.
\]

A larger data limit mechanically reduces rationing inside the fee simulator, but it also raises the maximum metered payload. The simulator alone cannot recommend the largest limit.

---

## 15. Reproducibility

The project separates raw data from tracked publication outputs:

```text
data/raw/          ignored
data/cache/        ignored
results/stage_a/   tracked
results/stage_b/   tracked
results/stage_c/   tracked
results/stage_d/   tracked
```

Each tracked result directory should contain a manifest with:

- git commit;
- source block range;
- source-panel checksum;
- query or extraction version;
- bootstrap block length;
- seed list;
- model-configuration hash;
- creation timestamp.

The pipeline should assert that headline result tables are tracked before declaring a stage frozen.

Permanent regression tests include:

- unit-shock equilibrium preservation;
- bit-exact fake-exponential update;
- static/dynamic fill agreement;
- zero-drift long replay;
- one-wei boundary behavior;
- excess-gas flooring and clamping;
- source-versus-bootstrap distribution checks.

---

## 16. Findings to date

1. **Static feasibility is not dynamic reliability.** A statically feasible 300M/77M execution/data target pair performs poorly under a 90M data limit but much better with matched \(2\times\) data-limit headroom.
2. **Target-to-limit headroom is a first-order protocol parameter.** It changes limit-hit and rationing outcomes by more than an order of magnitude without changing the static equilibrium.
3. **A target close to the limit compresses the fee signal.** Low fee volatility in a saturated design can reflect rationing-dominant allocation, not stability.
4. **Large data-fee multiples are consistent with the elasticity calibration.** Inelastic demand requires large price changes to absorb ordinary block-level quantity variation.
5. **Migration from a bundle-cost-equivalent cold start appears modest relative to steady-state headroom effects.**
6. **The 75-day adverse calibration is demand-constrained.** High execution targets remain far below target regardless of data headroom, consistent with the static demand-feasibility result.
7. **Joint shock sampling is necessary.** The access-composition residual is not independent of execution demand.

---

## 17. Remaining deliverables

### Before Stage C

- regenerate Stage B stress summaries with paired event-window metrics;
- freeze the sampler diagnostics and zero-BAL convention;
- test bootstrap block-length sensitivity;
- finalize the \(\varepsilon\)-dominance screening rule.

### Stage C

- run the 36-specification robustness grid on shortlisted designs;
- stratify results by demand feasibility;
- report fixed-limit versus matched-headroom rationing ratios.

### Glamsterdam

- implement the shared-fee world adapter;
- apply the same latent workload paths;
- compare matched nominal capacity and matched realized throughput.

### Stage D

- extend the source panel to 30–60 days or multiple regimes;
- run tail-focused replications on final designs;
- report weekly extreme distributions with replication-level uncertainty.

### Final synthesis

The final parameter recommendation will combine:

- the static execution-clearing boundary;
- dynamic target/limit reliability;
- fee and user-cost behavior;
- physical bandwidth and propagation constraints;
- comparison with Glamsterdam under common shocks.
