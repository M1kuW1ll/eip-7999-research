# Full EIP-7999 Equilibrium Base Fees

This report solves separate target-clearing base fees for execution, data, and state under full EIP-7999. The central calculation combines the independent isoelastic demand estimates with the EIP-7999 metering anchors and the EIP-8279 runtime-BAL demand model.

The capacity comparison has two parts:

- an **empirically anchored path**, which scales the execution and data targets together using their metered ratio in the February--May 2026 anchor; and
- an **off-path grid**, which crosses execution limits from 250M to 600M with five data targets to show what happens when the two capacities are deliberately imbalanced.

The data reserve is excluded. It changes the dynamic fee path and will be introduced in the driven replay.

## Main results

1. The observed full-7999 metered anchor contains **36.821M execution gas**, **2.124M static data gas**, **1.919M runtime-BAL gas**, and **29.663M state gas** per block.
2. The observed total-data-to-execution ratio is **0.109795**. Preserving this ratio matches data targets of 15M, 18M, 22.5M, and 30M to execution limits of approximately **273M, 328M, 410M, and 546M**. A 45M data target would match approximately 820M execution gas and is outside the 250M--600M central range.
3. Under the central 35-day elasticities, all four empirically anchored scenarios have target-clearing equilibria above the one-wei minimum. The execution fee nevertheless falls from **1,388 wei** at the 273M limit to only **5 wei** at the 546M limit.
4. Demand adequacy is sensitive to the event window. With the 60- and 75-day execution elasticities, the matched 328M, 410M, and 546M scenarios require continuous execution fees below one wei and therefore cannot clear their execution targets under the protocol minimum.
5. At the 600M execution limit, the 35-day curve clears the 300M execution target at only **2.10 wei**. The 21-day estimate is also barely above the minimum at **1.15 wei**, while the 60- and 75-day estimates leave only 161M and 152M gas of demand at one wei. The 600M case is consequently an extrapolation boundary, not a demand forecast.
6. Capacity imbalance matters for data. At a 600M execution limit and a 15M data target, induced BAL occupies **96.05%** of the target, and the remaining static-data demand clears only at **15.48 gwei**. Along the empirically anchored path, BAL occupies a much more stable **43.9%--45.7%** of the data target.

## Demand and metering anchors

Let $q_i^0$ be the reference activity quantity expressed in historical gas-equivalent units, $m_i$ the EIP-7999 metering multiplier, and $g_i^0=m_iq_i^0$ the resulting EIP-7999 gas at the anchor. Holding the underlying activity fixed, the candidate-world reference fee is $p_i^0=p^0/m_i$.

| Resource | Historical gas-equivalent quantity | EIP-7999 multiplier | EIP-7999 gas per block | Candidate-world reference fee |
|---|---:|---:|---:|---:|
| Execution | 23.942M | 1.537898 | 36.821M | 0.069529 gwei |
| Static data | 1.181M | 1.798834 | 2.124M | 0.059443 gwei |
| State | 5.244M | 5.656315 | 29.663M | 0.018904 gwei |

Runtime BAL is added separately rather than folded into the static-data multiplier. Its EIP-8279 anchor is **1.919M data gas per block**.

The central independent elasticities use the 35-day event window:

| Event window | $\epsilon_E$ | $\epsilon_D$ | $\epsilon_S$ |
|---:|---:|---:|---:|
| 21 days | 0.117067 | 0.201790 | 0.478438 |
| **35 days** | **0.121160** | **0.229476** | **0.334864** |
| 60 days | 0.081668 | 0.204691 | 0.279676 |
| 75 days | 0.078511 | 0.201391 | 0.253556 |

## Three-resource equilibrium

Execution and state each retain an independent isoelastic demand curve:

$$
g_i(p_i)=g_i^0\left(\frac{p_i}{p_i^0}\right)^{-\epsilon_i},
\qquad i\in\{E,S\}.
$$

Their continuous target-clearing fees are:

$$
p_i^*=p_i^0\left(\frac{g_i^0}{T_i}\right)^{1/\epsilon_i}.
$$

The EIP-8279 runtime BAL at the execution and state targets is:

$$
B^*=B_0\left[
w_{\mathrm{state}}\frac{T_S/m_S}{S_0}
+w_{\mathrm{execution}}
\left(\frac{T_E/m_E}{E_0}\right)^{\rho_A}
\right],
$$

with $w_{\mathrm{state}}=0.113932$, $w_{\mathrm{execution}}=0.886068$, and $\rho_A=1$. Total execution is a reduced-form proxy for existing-state access activity; the model does not claim that every execution-gas unit mechanically produces BAL.

The central model sets $\gamma_{\mathrm{BAL}}=0$, so BAL does not receive an additional direct response to the data fee after its parent activities are determined. Static data must fill the remaining target space:

$$
D_{\mathrm{static}}(p_D^*)=T_D-B^*.
$$

The continuous data fee is therefore:

$$
p_D^*=p_D^0
\left(\frac{g_{D,\mathrm{static}}^0}{T_D-B^*}\right)^{1/\epsilon_D}.
$$

A finite continuous data equilibrium exists only when $B^*<T_D$. Separately, a continuous execution, data, or state solution is protocol-reachable only when its target can be met at a base fee of at least one wei.

## Capacity design

The data gas limit is fixed at **90M**, corresponding to 5.625MB at 16 gas per byte. The data target is varied through target ratios of $1/6$, $1/5$, $1/4$, $1/3$, and $1/2$. Execution limits run from 250M through 600M in 50M increments, with $T_E=G_E/2$. State has a 75M target and no hard limit.

The empirically anchored path preserves:

$$
\kappa_0
=\frac{g_{D,\mathrm{static}}^0+B_0}{g_E^0}
=0.109795,
\qquad
T_E=\frac{T_D}{\kappa_0}.
$$

| Data target ratio | Data target | Matched execution target | Matched execution limit | Included centrally? |
|---:|---:|---:|---:|:---:|
| 1/6 | 15.0M | 136.6M | 273.2M | Yes |
| 1/5 | 18.0M | 163.9M | 327.9M | Yes |
| 1/4 | 22.5M | 204.9M | 409.9M | Yes |
| 1/3 | 30.0M | 273.2M | 546.5M | Yes |
| 1/2 | 45.0M | 409.9M | 819.7M | No |

This anchoring rule is not a claim that future demand will preserve exactly the same resource mix. It gives the central capacity comparison a measured starting point. The full grid shows the consequences of deviating from it.

## Empirically anchored equilibrium fees

The table reports the 35-day continuous solution and the nearest fee represented by the integer fake exponential. The integer fee is the correct warm start for the dynamic replay.

| Execution limit | Data target | Execution fee | Data fee | State fee | Runtime BAL | BAL share of data target |
|---:|---:|---:|---:|---:|---:|---:|
| 273.2M | 15.0M | 1,388 wei (0.000001388 gwei) | 170,470 wei (0.000170 gwei) | 1,184,471 wei (0.001184 gwei) | 6.862M | 45.75% |
| 327.9M | 18.0M | 308 wei (0.000000308 gwei) | 73,331 wei (0.000073 gwei) | 1,184,471 wei (0.001184 gwei) | 8.124M | 45.13% |
| 409.9M | 22.5M | 49 wei (0.000000049 gwei) | 26,418 wei (0.000026 gwei) | 1,184,471 wei (0.001184 gwei) | 10.017M | 44.52% |
| 546.5M | 30.0M | 5 wei (0.000000005 gwei) | 7,188 wei (0.000007 gwei) | 1,184,471 wei (0.001184 gwei) | 13.171M | 43.90% |

The state fee is unchanged because its target and demand curve do not vary across the capacity scenarios.

## Off-path grid

![Full EIP-7999 capacity grid](../plots/full_7999_equilibrium_capacity_grid_2026-02-01_2026-06-01.png)

> The left panel shows the execution target-clearing fee as the execution limit increases. The middle panel shows the data fee for each target ratio after adding BAL induced by the execution and state targets. The right panel shows the fraction of each data target already occupied by BAL. The dashed line marks the one-wei execution minimum or, in the BAL panel, the point at which BAL alone equals the data target.

The grid separates two different demand concerns:

- **Execution demand adequacy:** under the central 35-day curve, the continuous execution fee falls from 2,891 wei at a 250M limit to 2.10 wei at 600M. The 600M scenario is technically reachable but very close to the protocol minimum.
- **Data congestion from induced BAL:** at fixed execution capacity, increasing the data target lowers the data fee. At fixed data target, increasing execution capacity raises BAL and can sharply raise the data fee.

The most imbalanced grid point is 600M execution with a 15M data target. It still has a mathematical data equilibrium because BAL is 14.407M, just below the target. Only 0.593M remains for static data, so the data fee rises to 15.48 gwei. This is precisely the type of scenario the empirically anchored path is designed to avoid treating as central.

## Event-window robustness and demand adequacy

![Full EIP-7999 event-window robustness](../plots/full_7999_equilibrium_window_sensitivity_2026-02-01_2026-06-01.png)

> Each vertical interval spans the target-clearing fees implied by the 21-, 35-, 60-, and 75-day independent elasticity estimates. The larger marker is the 35-day central estimate. The dashed line is the one-wei protocol minimum.

Static data and state remain target-reachable across the displayed event windows. Execution is the capacity warning:

| Matched execution limit | Continuous execution-fee range | Windows below one wei |
|---:|---:|:---|
| 273.2M | 3.89--1,388 wei | None |
| 327.9M | 0.381--308 wei | 60 and 75 days |
| 409.9M | 0.022--48.9 wei | 60 and 75 days |
| 546.5M | 0.000569--4.55 wei | 60 and 75 days |

For the off-path 600M execution limit, the execution target is 300M. The continuous execution fees are 1.15, 2.10, 0.000486, and 0.000173 wei for the 21-, 35-, 60-, and 75-day estimates. At the one-wei minimum, the last two curves support only 160.9M and 152.0M gas. The model therefore does not provide robust evidence that a 300M execution target would be filled under current demand.

## Interpretation and limitations

- The equilibrium is a fee vector, not one shared fee. Execution and state clear their own targets; data clears static data plus induced runtime BAL.
- The empirically anchored path makes execution and data capacity internally comparable, but it does not identify the welfare-optimal target ratio.
- Total execution remains a proxy for state-access activity. Replacing it with an explicit access index is the main improvement to the BAL coupling model.
- The isoelastic curves are extrapolated well beyond the observed anchor. A target-clearing fee near one wei should be read as weak demand support, not a precise prediction.
- The static calculation has no transaction selection, hard-limit frequency, fee volatility, shocks, backlog, or reserve-price path. Those outcomes require the driven replay.

## Data used

- February 1--May 31, 2026 accounting panel: 120 days and 860,505 blocks.
- Independent elasticities: 21-, 35-, 60-, and 75-day event-window calibrations from notebook 1.8.
- Execution metering: 120-day EIP-8038 + EIP-2780 repricing with reconstructed EIP-8038 refunds.
- Static-data metering: 120-day calldata, access-list, authorization-tuple, and blob-hash accounting at 16 gas per byte.
- Runtime BAL anchor and attribution: EIP-8279 counter calibrated and decomposed over the 6,000-block panel in notebook 1.11.
- State metering: 120-day EIP-8037 accounting with `CPSB = 1530`.

The executable calculation is in [notebook 2.0](../notebooks/2.0-full-7999-equilibrium-model.ipynb).
