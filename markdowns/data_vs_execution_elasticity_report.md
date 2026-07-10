# Data vs. Execution Share and Elasticity Analysis

Status: working research note  
Primary notebook: `notebooks/1.4-eip7623-calldata-event-study.ipynb`  
Cross-check notebook: `notebooks/1.5-gas-limit-data-share-event-study.ipynb`  
Main data outputs: `data/eip7623_event_*_2025-03-07_2025-07-08.csv`, `data/gas_limit_data_share_*`

## 1. Summary

This note extends Maria's EIP-8037 state-vs-rest elasticity framework to the
next nesting level:

```text
total demand
  = state + rest

rest
  = data + execution
```

[Prior EIP-8037 analysis](https://ethresear.ch/t/empirical-analysis-of-price-elasticities-for-ethereum-state-and-burst-resources/24166)
estimates how demand splits between state creation and the
remaining burst/rest bucket. Our question is narrower: inside the rest bucket,
how much more price-sensitive is data demand than execution demand?

The best current L1 event for this is EIP-7623, activated with Pectra on May 7, 2025.
EIP-7623 raised the transaction-level calldata floor for calldata-heavy
transactions. This provides a historical price shock to calldata-heavy activity
while leaving ordinary execution-heavy transactions mostly unchanged.

As a second, weaker cross-check, we also use 2025 gas-limit increases. Those
events lower the common blockspace price rather than the calldata price alone,
so they test whether calldata/data share inside rest expands when blockspace
gets cheaper.

The main result from the event-study notebook is:


$$
\eta_{\text{data}} \approx 0.43
$$

$$
\alpha_{\text{data}\mid\text{rest}} \approx 0.0525
$$

$$
\epsilon_{\text{rest}} \approx 0.08
$$

which imply:

$$
\epsilon_{\text{data}} \approx 0.49
$$

$$
\epsilon_{\text{execution}} \approx 0.057
$$


Interpretation:

Data/calldata demand appears meaningfully more price-sensitive than execution
demand. But this should be treated as a prior for the full EIP-7999 bandwidth
resource, not as a final estimate, because EIP-7623 only shocks calldata-heavy
transactions, while the future bandwidth resource also includes access-list
bytes, authorization tuples, blob hashes, and BAL bytes.

For the Glamsterdam pilot, the cleaner central object to carry forward is the recovered
own-price prior:

$$
\epsilon_{\text{data}}^{\text{prior}} \approx 0.487
$$

The corresponding $\eta_{\text{data}}$ is still useful inside the nested demand
model, but it is a model parameter derived from the chosen share basis. Treating
$\epsilon_{\text{data}}$ as the fixed prior avoids making the central data
elasticity depend on the 500-block pilot composition.

For broader sensitivity, the recommended sweep remains:

$$
\eta_{\text{data}}
\in
\{0.0,\ 0.1,\ 0.3,\ 0.43,\ 0.6,\ 1.0\}
$$

with $\eta_{\text{data}} = 0.43$ as the current central L1
calldata-vs-execution prior. The gas-limit event study supports the lower part
of this sweep, roughly $\eta_{\text{data}} \approx 0.1$ to $0.3$, but is
noisier and therefore should not replace the EIP-7623 central value.

## 2. Relation to Prior State-vs-Rest Analysis

The key structure is:

Total demand responds to the overall base fee, and resource shares respond to
relative prices.


$$
\epsilon_{\text{agg}} \approx 0.175
$$

$$
\eta_{\text{state}} \approx 0.43
$$

$$
\epsilon_{\text{state}} \approx 0.3 \text{ to } 0.6
$$

$$
\epsilon_{\text{rest}} \approx 0.0 \text{ to } 0.2
$$

Central values:

$$
\epsilon_{\text{state}} \approx 0.51
$$

$$
\epsilon_{\text{rest}} \approx 0.08
$$

Our report reuses the same logic, but applies it one level deeper:

```text
Prior:
  state vs. rest

This note:
  data vs. execution, inside rest
```

So $\epsilon_{\text{rest}} \approx 0.08$ is the inherited elasticity for the whole non-state
bucket. We then estimate how that rest bucket splits between data and execution.

## 3. Model

Let:

```text
rest = data + execution
```

Define the data share inside rest:

$$
\alpha_{\text{data}\mid\text{rest}}
=
\frac{\text{data}}{\text{data} + \text{execution}}
$$

The share elasticity is:

$$
\eta_{\text{data}}
=
-\frac{
  \Delta \operatorname{logit}(\alpha_{\text{data}\mid\text{rest}})
}{
  \Delta \log(\text{relative data price})
}
$$

The logit is just the log of the odds of a share:

$$
\operatorname{odds}(\alpha)
=
\frac{\alpha}{1-\alpha}
$$

$$
\operatorname{logit}(\alpha)
=
\log\left(\operatorname{odds}(\alpha)\right)
=
\log\left(\frac{\alpha}{1-\alpha}\right)
$$

For example, if data is 5% of rest:

$$
\alpha = 0.05
$$

$$
\operatorname{odds}(\alpha)
=
\frac{0.05}{0.95}
\approx 0.0526
$$

$$
\operatorname{logit}(\alpha)
=
\log(0.0526)
\approx -2.94
$$

We use the change in logit rather than the raw change in share because a share
is bounded between 0 and 1. The logit turns the share into an unbounded
log-odds scale. For small shares, like data inside rest, a logit change is close
to a proportional change in the share.

```text
relative data price rises
data share falls
eta_data is positive
```

This is parallel to prior state-share elasticity:

$$
\eta_{\text{state}}
=
-\frac{
  \Delta \operatorname{logit}(\alpha_{\text{state}})
}{
  \Delta \log(\text{relative state price})
}
$$

Once we have $\eta_{\text{data}}$, we recover structural elasticities using the same
share-weighted system. To keep the equations readable, define:

$$
a \equiv \alpha_{\mathrm{data}\mid\mathrm{rest}}
$$

Then the rest-bucket elasticity is the share-weighted average of data and
execution elasticities:

$$
\epsilon_{\mathrm{rest}}
= a\,\epsilon_{\mathrm{data}} + (1-a)\,\epsilon_{\mathrm{execution}}
$$

and the data-vs-execution substitution parameter is:

$$
\eta_{\mathrm{data}}
=
\epsilon_{\mathrm{data}}-\epsilon_{\mathrm{execution}}
$$

Solving:

$$
\epsilon_{\mathrm{data}}
=
\epsilon_{\mathrm{rest}} +
\eta_{\mathrm{data}}(1-a)
$$

$$
\epsilon_{\mathrm{execution}}
=
\epsilon_{\mathrm{rest}} -
\eta_{\mathrm{data}}a
$$

where $\epsilon_{\text{rest}} = 0.08$ from Prior 8037 analysis, and $\alpha$ can
be derived from empirical data.


## 4. Event: EIP-7623 as a Calldata Price Shock

EIP-7623 is useful because it changed the effective price of calldata-heavy
transactions.

Before EIP-7623, calldata-heavy transactions faced a floor equivalent to:

```text
zero byte:     4 gas normal, 10 gas floor
nonzero byte: 16 gas normal, 40 gas floor
```

So the clean theoretical floor-price ratio is:

$$
\frac{10}{4}
=
\frac{40}{16}
=
2.5
$$

But the effective transaction-level price shock is smaller because transactions
also contain base gas and execution gas. The notebook therefore computes both:

```text
theoretical price ratio: 2.500
effective price ratio:   2.112
```

The effective ratio is the preferred value because it reflects the actual
treated transaction body, not only the pure calldata byte price.

## 5. Main Event-Study Result

The main event window is:

```text
pre:  March 7, 2025 to May 6, 2025
post: May 8, 2025 to July 7, 2025
```

The activation is excluded.

State-cleaned result:

| Quantity                                      | Value |
|-----------------------------------------------|---:|
| Pre inferred floor-bound calldata share     | 0.654% |
| Post inferred floor-bound calldata share     | 0.475% |
| $\eta_{\text{data}}$ using 2.5x theoretical ratio | 0.350 |
| $\eta_{\text{data}}$ using effective ratio    | 0.429 |

The state-cleaned estimate is preferred because the data-vs-execution split is
supposed to live inside the non-state rest bucket. If state creation gas remains
inside the denominator, the rest bucket is contaminated by the state component
that Maria's top-level model has already separated.

So the central result is:

$$
\eta_{\text{data}} \approx 0.43
$$


## 6. Cross-Check: Gas-Limit Increases as Common-Price Shocks

EIP-7623 is the cleaner calldata-specific event. Gas-limit increases are a
weaker but useful complement because they move the common blockspace price.
The question becomes:

```text
When base fee falls after a gas-limit increase,
does data share inside rest rise relative to execution?
```

The notebook `notebooks/1.5-gas-limit-data-share-event-study.ipynb` estimates:

$$
\eta_{\text{data}}
\approx
-\frac{
  \Delta \operatorname{logit}(\alpha_{\text{data}\mid\text{rest}})
}{
  \Delta \log(\text{base fee})
}
$$

Here the denominator is state-excluded using the daily state inventory
proxy:

```text
state_inventory_delta_gas_proxy =
    max(0, Delta account_bytes)       * 25_000 / 112
  + max(0, Delta storage_bytes)       * 20_000 / 32
  + max(0, Delta contract_code_bytes) * 200
```

This keeps the analysis in the historical/current-fee-market world. It is intentionally a broad
daily proxy, not the exact 500-block RPC-calibrated state creation estimator used
for mechanism replay.

Windowed gas-limit event results:

| Event | Median base-fee change | Data share before | Data share after | Implied $\eta_{\text{data}}$ |
|---|---:|---:|---:|---:|
| 30M $\to$ 36M, Feb. 4 2025 | $\log(P_1/P_0)=-2.114$ | 4.809% | 6.095% | 0.118 |
| 36M $\to$ 45M, Jul. 21 2025 | $\log(P_1/P_0)=-0.887$ | 5.874% | 6.313% | 0.087 |
| 45M $\to$ 60M, Nov. 25 2025 | $\log(P_1/P_0)=-1.254$ | 5.878% | 5.049% | -0.128 |

The daily ARDL version gives:

| Estimate | Value |
|---|---:|
| Cumulative $\eta_{\text{data}}$ | 0.268 |
| 95% CI | [0.169, 0.367] |
| Long-run $\eta_{\text{data}}$ | 0.123 |

Interpretation:

The first two gas-limit events are directionally consistent with data being more
elastic than execution, but the third event is negative. The ARDL estimate is
positive and lands in the low-to-mid part of the sweep. So the gas-limit evidence
supports using values like $0.1$ and $0.3$ in the simulator, but it is not strong
enough to override the EIP-7623 estimate around $0.43$.

EIP-7623 changes calldata-heavy transaction price
relative to execution. Gas-limit increases reduce the common price of all
blockspace, so identification comes only from differential expansion of data
relative to execution. That makes the gas-limit estimate closer to Maria's event
style, but weaker for this particular data/execution split.

## 7. State-Cleaned Rest Denominator

The notebook removes current-rule state creation gas from the non-calldata body
gas denominator.

The removed state-creation component is:

```text
pre period:  ~4.05M gas/block
post period: ~3.10M gas/block
```

As a share of the control denominator:

```text
pre:  28.7%
post: 22.9%
```

This matters because the project ultimately models:

```text
state
execution
data
```

not:

```text
state
execution plus hidden state
data
```

The state-cleaned denominator is therefore the denominator used throughout this
report.

## 8. Data Share Inside Rest

For recovering structural elasticities, the notebook uses the pre-fork
state-cleaned standard calldata share:

$$
\alpha_{\text{data}\mid\text{rest}} = 0.052494
$$

That means:

```text
data is about 5.25% of the non-state rest bucket
execution is about 94.75% of the non-state rest bucket
```

The full-window state-cleaned value is similar:

$$
\alpha_{\text{data}\mid\text{rest}} = 0.049567
$$

for the full window excluding the activation day.

So the result is not coming from a one-day denominator artifact.

## 9. Recovered Elasticities

Using:

$$
\epsilon_{\text{rest}} = 0.08
$$

$$
\alpha_{\text{data}\mid\text{rest}} = 0.052494
$$

we recover:

$$
\epsilon_{\text{data}}
=
\epsilon_{\text{rest}}
+
\eta_{\text{data}}\left(1-\alpha_{\text{data}\mid\text{rest}}\right)
$$

$$
\epsilon_{\text{execution}}
=
\epsilon_{\text{rest}}
-
\eta_{\text{data}}\alpha_{\text{data}\mid\text{rest}}
$$

Sweep results:

| $\eta_{\text{data}}$ | $\epsilon_{\text{data}}$ | $\epsilon_{\text{execution}}$ | Interpretation |
|---:|---:|---:|---|
| 0.00 | 0.080 | 0.080 | fixed data/execution split |
| 0.10 | 0.175 | 0.075 | mild data sensitivity |
| 0.30 | 0.364 | 0.064 | moderate data sensitivity |
| 0.43 | 0.487 | 0.057 | central state-cleaned prior |
| 0.60 | 0.649 | 0.049 | high data sensitivity |
| 1.00 | 1.028 | 0.028 | aggressive short-run sensitivity |

The exact state-cleaned long-window estimate gives:

$$
\eta_{\text{data}} = 0.429418
$$

$$
\epsilon_{\text{data}} = 0.486876
$$

$$
\epsilon_{\text{execution}} = 0.057458
$$

This is the cleanest current estimate.

## 10. Robustness Checks

The daily and weekly aggregation checks are useful mainly as sanity checks on
the EIP-7623 event-study construction. The gas-limit event study is a second
sanity check: it is positive for the first two 2025 gas-limit increases and in
the ARDL estimate, but negative for the 45M-to-60M window. The report's preferred
estimate therefore remains the state-cleaned 60-day EIP-7623 effective-ratio
estimate:

$$
\eta_{\text{data}} \approx 0.43
$$

The shorter event windows produce much larger estimates:

```text
7-day to 35-day windows: eta roughly 0.9 to 2.2
60-day window:           eta roughly 0.43 state-cleaned
```

This suggests the short-run response around activation was sharper, but also
much noisier. The long 60-day window is a better central input for the simulator.

Placebo windows before activation show unstable and sometimes negative
estimates. That is a warning against over-interpreting any single short window.

## 11. Stable Cohort Check

The notebook also defines a stable pre-fork high-calldata-intensity cohort.

The pre-fork p95 calldata intensity is:

```text
0.03618
```

The EIP-7623 floor-binding cutoff is:

```text
0.10
```

So the stable cohort uses:

```text
max(0.03618, 0.10) = 0.10
```

This ends up matching the main floor-bound cohort. The check is still useful:
it confirms that the central result is not mainly an artifact of changing the
cohort definition after the fork.

## 12. Data Quality and State-Creation Approximation

The state-cleaning step uses Xatu-derived state-creation estimates. We checked a
500-block RPC-calibrated sample to estimate the error.

Current-rule historical state creation gas:

```text
Xatu / RPC ratio: 0.9984
mean absolute error: ~8.3k gas/block
p95 absolute error: ~25k gas/block
```

EIP-8037 state gas:

```text
Xatu / RPC ratio: 0.9992
mean absolute error: ~28.5k gas/block
p95 absolute error: ~106k gas/block
```

This is small relative to the multi-million-gas state-cleaning adjustment.
Delegation indicators are the main known missing Xatu component, but in this
sample they are not large enough to materially affect the EIP-7623 estimate.

## 13. Interpretation

The result is economically intuitive:

```text
execution demand is very inelastic
calldata-heavy data demand is more elastic
```

Because data is only about 5% of the non-state rest bucket, even a moderately
large $\eta_{\text{data}}$ barely moves execution elasticity:

$$
\eta_{\text{data}} \approx 0.43
$$

$$
\epsilon_{\text{execution}} \approx 0.057
$$

But the same eta implies a substantially larger data elasticity:

$$
\epsilon_{\text{data}} \approx 0.49
$$

So the nested model says:

```text
rest as a whole is still inelastic
execution is especially inelastic
calldata-heavy data is the flexible part of rest
```

This is the right shape for the EIP-7999 simulator. We should not assume that
execution and data respond equally to price.

## 14. How To Use This In The Simulator

Use Maria's top-level state/rest values:

$$
\epsilon_{\text{state}} \approx 0.51
$$

$$
\epsilon_{\text{rest}} \approx 0.08
$$

$$
\eta_{\text{state}} \approx 0.43
$$

Then split rest using the EIP-7623 calldata prior. There are two equivalent
ways to express the central case:

$$
\eta_{\text{data}} \approx 0.43
$$

is the event-study share/substitution estimate, while:

$$
\epsilon_{\text{data}}^{\text{prior}} \approx 0.487
$$

is the recovered calldata own-price elasticity. For the Glamsterdam pilot, use
$\epsilon_{\text{data}}^{\text{prior}}$ as the fixed central prior and convert
it into the model's internal $\eta_{\text{data}}$ only when the nested demand
system requires it.

$$
\alpha_{\text{data}\mid\text{rest}} \approx 0.0525
$$

Recommended sweep:

$$
\eta_{\text{data}}
\in
\{0.0,\ 0.1,\ 0.3,\ 0.43,\ 0.6,\ 1.0\}
$$

with recovered elasticities:

$$
\epsilon_{\text{data}}
=
\epsilon_{\text{rest}}
+
\eta_{\text{data}}\left(1-\alpha_{\text{data}\mid\text{rest}}\right)
$$

$$
\epsilon_{\text{execution}}
=
\epsilon_{\text{rest}}
-
\eta_{\text{data}}\alpha_{\text{data}\mid\text{rest}}
$$

Guardrail:

$$
\epsilon_{\text{execution}} \ge 0
$$

Given $\epsilon_{\text{rest}} = 0.08$ and
$\alpha_{\text{data}\mid\text{rest}} = 0.052494$, the upper bound is:

$$
\eta_{\text{data}} \le 1.524
$$

So the proposed sweep remains inside the nonnegative-execution region.

When using the fixed data-elasticity prior directly, the corresponding execution
elasticity is recovered from:

$$
\epsilon_{\text{rest}}
=
\alpha_{\text{data}\mid\text{rest}}\epsilon_{\text{data}}^{\text{prior}}
+
\left(1-\alpha_{\text{data}\mid\text{rest}}\right)\epsilon_{\text{execution}}
$$

or:

$$
\epsilon_{\text{execution}}
=
\frac{
  \epsilon_{\text{rest}}
  - \alpha_{\text{data}\mid\text{rest}}\epsilon_{\text{data}}^{\text{prior}}
}{
  1-\alpha_{\text{data}\mid\text{rest}}
}
$$

## 15. Caveats

This is a calldata elasticity estimate, not a full bandwidth-resource
elasticity estimate.

The full EIP-7999 bandwidth resource includes:

```text
calldata
access-list bytes
authorization tuples
blob hashes
BAL bytes
```

Only calldata-heavy transactions were shocked by EIP-7623. Access-list,
authorization, blob-hash, and BAL behavior still need sensitivity analysis.

The treated group is small:

```text
state-cleaned treated data share: 0.65% pre, 0.48% post
```

That makes the estimate useful but noisy.

Blob market conditions and L2 batching behavior may confound the event. The
next version should add blob base fee, blob usage, and known L2 poster activity
as controls or stratification variables.

Finally, this is a historical estimate. When applying it to Glamsterdam,
Mechanism A, or full EIP-7999, the accounting must be rebased first. The
elasticities are behavioral priors; they do not replace mechanism-specific
repricing.

## 16. Bottom Line

The clean working result is:

EIP-7623 gives a usable L1 prior for data-vs-execution substitution.

Preferred estimate:

$$
\eta_{\text{data}} \approx 0.43
$$

Recovered central elasticities:

$$
\epsilon_{\text{data}} \approx 0.49
$$

$$
\epsilon_{\text{execution}} \approx 0.057
$$

Use this as a behavioral prior, not as a fixed truth. For the Glamsterdam pilot, the
most readable central input is:

$$
\epsilon_{\text{data}}^{\text{prior}} \approx 0.487
$$

The associated $\eta_{\text{data}} \approx 0.43$ remains useful for sensitivity
sweeps and for translating the prior into the nested demand model. The gas-limit
cross-check gives a weaker but useful second signal: common-price events mostly
support small positive values, around $0.1$ to $0.3$, while EIP-7623 supports the
higher central value around $0.43$.

Together, these plug the main gap left by Maria's state-vs-rest analysis: they
give a first-pass empirical handle on how the rest bucket should split into data
and execution when moving toward an EIP-7999 multidimensional fee market.
