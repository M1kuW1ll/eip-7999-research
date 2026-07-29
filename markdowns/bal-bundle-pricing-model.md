# Pricing BAL Through the Parent Bundle: Revised Demand Model and Equilibrium Derivation

**Status**: proposal for revising the BAL demand model in the *BAL
Demand Model and Data Metering under 7999* and *Full EIP-7999
Equilibrium Base Fees* reports.

**Summary.** The current reports model BAL as a separate source of data
demand with an ad hoc response to the data fee (Model A's
$\gamma_{\mathrm{BAL}}$, Model B's $\beta_{\mathrm{BAL}}$), while
execution and state demand respond only to their own fees. This note
proposes a simpler *bundle-pricing* model: because BAL bytes are a
mechanical byproduct of execution and state activity, the BAL charge is
part of the price of *doing execution and state creation*. The parent
demand curves should therefore be evaluated at the all-in bundle price,
not at the resource fee alone. This change (i) eliminates both free
parameters $\gamma_{\mathrm{BAL}}$ and $\beta_{\mathrm{BAL}}$, deriving
BAL's fee response from the estimated parent elasticities; (ii) resolves
two acknowledged inconsistencies in the current model; and (iii)
materially changes the results --- in all four paired scenarios the
current equilibria are infeasible under bundle pricing (they would
require negative execution fees), the correct equilibria are corner
solutions at the 1-wei execution floor, data fees fall 37--62%, and the
near-boundary blow-up (600M/15M, 15.72 gwei) disappears entirely.

All numbers below use the 35-day elasticities, $\lambda = 0$, and the
rounded anchors from the reports; they should be recomputed in the
notebooks with full precision.

------------------------------------------------------------------------

## 1. The invariant: $p\,E(p) = p_e\,E(p) + w\,p_d\,E(p)$

### 1.1 Statement

Let $E(\cdot)$ be the execution demand curve: the quantity of execution
activity users undertake when one unit of execution activity costs $p$,
*all-in*. Suppose each unit of execution activity mechanically produces
$w$ units of BAL data gas. Under EIP-7999 the user's bill for $E$ units
of execution activity is

$$
\underbrace{p_e\,E}_{\text{execution gas line}} + \underbrace{w\,p_d\,E}_{\text{BAL data-gas line}},
$$

where $p_e$ is the execution price and $p_d$ the data price. Expenditure
consistency with the demand curve requires

$$
p\,E(p) = p_e\,E(p) + w\,p_d\,E(p)
\qquad\Longleftrightarrow\qquad
p = p_e + w\,p_d .
$$

The demand curve itself does not change. What changes is the price at
which it is evaluated. Equilibrium execution quantity is

$$
E^* = E(p_e + w\,p_d),
$$

which depends on **both** the execution fee and the data fee. From the
user's perspective, only the total bill matters. The same logic applies
to state creation, which also generates BAL.

### 1.2 Why the historical elasticity applies to the bundle price

The elasticities in the resource-elasticity report were estimated from
common-fee variation during a period when BAL carried **no charge**. In
that period, the all-in price of one unit of execution activity was
exactly the common fee $p$: the bundle price and the execution price
coincided because $p_d^{\mathrm{BAL}} = 0$. The estimated curve $E(p)$
is therefore a demand curve *in the bundle price*, and evaluating it at
$p_e + w\,p_d$ under EIP-7999 is the correct counterfactual use of the
estimate. By contrast, the current reports evaluate it at $p_e$ alone,
which implicitly assumes users do not notice or respond to the BAL line
on their bill --- inconsistent with how the same reports treat metering
multipliers (where repricing *is* passed into the effective price).

Note this is the same logic already used for the metering multipliers:
$m_i$ converts a fee into the effective price of historical activity.
The bundle extension simply adds the second billing line to the same
effective price.

### 1.3 Mapping to the reports' notation

In the reports, resource $i$'s effective price per historical
gas-equivalent unit is $p_i(b_i) = m_i b_i$. The bundle extension
defines **BAL intensities** --- data gas mechanically produced per
historical gas-equivalent unit of parent activity:

$$
w_{\mathrm{e}}(\lambda) = \frac{\omega_{\mathrm{execution}}(\lambda)\, g_{\mathrm{BAL}}^0}{q_{\mathrm{execution}}^0},
\qquad
w_{\mathrm{s}}(\lambda) = \frac{\omega_{\mathrm{state}}(\lambda)\, g_{\mathrm{BAL}}^0}{q_{\mathrm{state}}^0}.
$$

At $\lambda = 0$, with $g_{\mathrm{BAL}}^0 = 1.919$M,
$\omega_{\mathrm{execution}} = 0.886$,
$\omega_{\mathrm{state}} = 0.114$:

$$
w_{\mathrm{e}} = \frac{0.886 \times 1.919}{23.942} \approx 0.0710,
\qquad
w_{\mathrm{s}} = \frac{0.114 \times 1.919}{5.244} \approx 0.0417 .
$$

(Per *metered* EIP-7999 execution gas unit,
$w_{\mathrm{e}}/m_{\mathrm{e}} \approx 0.0462$ --- the same 4.6%
coefficient as the boundary slope in the full-equilibrium report, which
is not a coincidence: both are the execution-linked BAL intensity.)

The **effective bundle prices** replace the reports' effective prices:

$$
P_{\mathrm{e}}(b_{\mathrm{e}}, b_{\mathrm{d}}) = m_{\mathrm{e}} b_{\mathrm{e}} + w_{\mathrm{e}} b_{\mathrm{d}},
\qquad
P_{\mathrm{s}}(b_{\mathrm{s}}, b_{\mathrm{d}}) = m_{\mathrm{s}} b_{\mathrm{s}} + w_{\mathrm{s}} b_{\mathrm{d}} .
$$

Static data is unchanged: its effective price remains
$m_{\mathrm{data,static}}\, b_{\mathrm{d}}$, and its demand curve keeps
the independently estimated $\epsilon_{\mathrm{data}}$.

### 1.4 What this replaces, and which inconsistencies it fixes

The bundle model makes both existing BAL specifications unnecessary:

-   **Model A** ($r_{\mathrm{data}}^{-\gamma_{\mathrm{BAL}}}$) tried to
    give BAL a demand curve anchored at a price BAL never had. In the
    bundle model, BAL has no demand curve --- parents do --- and the
    "cheaper than free" pathology cannot arise because
    $b_{\mathrm{d}} = 0$ simply removes the second billing line.
-   **Model B** ($\Psi_{\mathrm{BAL}}$) had the right economics (an
    incremental surcharge on the parent transaction) but applied the
    response *only to the BAL quantity*, holding parent execution and
    state gas fixed --- the limitation acknowledged in the report ("when
    a BAL-carrying transaction exits, their execution, state and
    calldata gas usage also exit"). The bundle model is Model B
    completed: the surcharge response is applied to the parent quantity
    itself, so the transaction's execution gas, state gas, and BAL bytes
    exit together, and the response elasticity is the *estimated*
    $\epsilon_{\mathrm{e}}$ (or $\epsilon_{\mathrm{s}}$) rather than a
    heuristic $\beta_{\mathrm{BAL}}$.

Two internal inconsistencies of the current full-equilibrium report are
resolved automatically:

1.  **Realized vs target activity.** The current $\widetilde B$ scales
    BAL to the execution *target* even in scenarios where the same
    report shows the target is unreachable at the 1-wei floor. In the
    bundle model, BAL is
    $w_{\mathrm{e}} q_{\mathrm{e}}^* + w_{\mathrm{s}} q_{\mathrm{s}}^*$
    with $q^*$ the *solved equilibrium quantities* --- whatever they
    are, floor-limited or not.
2.  **No unidentified parameters.** $\gamma_{\mathrm{BAL}}$ and
    $\beta_{\mathrm{BAL}}$ disappear. The only remaining BAL degrees of
    freedom are the measured attribution ($\lambda$, via
    $w_{\mathrm{e}}, w_{\mathrm{s}}$) and the maintained proportionality
    assumption ($\rho_A$, see §6).

------------------------------------------------------------------------

## 2. The full model

**Primitives** (all from the existing reports): anchors
$q_{\mathrm{e}}^0, q_{\mathrm{s}}^0, g_{\mathrm{static}}^0, g_{\mathrm{BAL}}^0$,
common-price anchor $p^0$, multipliers
$m_{\mathrm{e}}, m_{\mathrm{s}}, m_{\mathrm{data,static}}$, elasticities
$\epsilon_{\mathrm{e}}, \epsilon_{\mathrm{s}}, \epsilon_{\mathrm{d}}$,
attribution weights
$\omega_{\mathrm{e}}(\lambda), \omega_{\mathrm{s}}(\lambda)$, targets
$T_{\mathrm{e}}, T_{\mathrm{s}}, T_{\mathrm{d}}$, and the protocol fee
floor $b_{\min} = 1$ wei.

**Demands.** Parent activities respond to bundle prices; static data to
its own price:

$$
q_{\mathrm{e}} = q_{\mathrm{e}}^0 \left( \frac{P_{\mathrm{e}}}{p^0} \right)^{-\epsilon_{\mathrm{e}}},
\qquad
q_{\mathrm{s}} = q_{\mathrm{s}}^0 \left( \frac{P_{\mathrm{s}}}{p^0} \right)^{-\epsilon_{\mathrm{s}}},
\qquad
g_{\mathrm{static}} = g_{\mathrm{static}}^0 \left( \frac{m_{\mathrm{data,static}}\, b_{\mathrm{d}}}{p^0} \right)^{-\epsilon_{\mathrm{d}}} .
$$

**BAL identity.** Runtime BAL is generated by realized parent activity:

$$
g_{\mathrm{BAL}} = w_{\mathrm{e}}\, q_{\mathrm{e}} + w_{\mathrm{s}}\, q_{\mathrm{s}} .
$$

(This is algebraically identical to the reports'
$g_{\mathrm{BAL}}^0 [\omega_{\mathrm{e}} q_{\mathrm{e}}/q_{\mathrm{e}}^0 + \omega_{\mathrm{s}} q_{\mathrm{s}}/q_{\mathrm{s}}^0]$
--- the parent-activity structure is retained; only the arguments of
$q_{\mathrm{e}}, q_{\mathrm{s}}$ change.)

**Market clearing with floors.** For each resource, either the fee is
interior and demand meets the target, or the fee is at the floor and
demand falls short:

$$
\begin{aligned}
\text{execution:}\quad & m_{\mathrm{e}}\, q_{\mathrm{e}} = T_{\mathrm{e}} \ \text{ and } \ b_{\mathrm{e}} \ge b_{\min},
\quad\text{or}\quad b_{\mathrm{e}} = b_{\min} \ \text{ and } \ m_{\mathrm{e}}\, q_{\mathrm{e}} < T_{\mathrm{e}}; \\
\text{state:}\quad & m_{\mathrm{s}}\, q_{\mathrm{s}} = T_{\mathrm{s}} \ \text{ (same floor logic)}; \\
\text{data:}\quad & g_{\mathrm{static}} + w_{\mathrm{e}}\, q_{\mathrm{e}} + w_{\mathrm{s}}\, q_{\mathrm{s}} = T_{\mathrm{d}} \ \text{ (same floor logic)}.
\end{aligned}
$$

The resulting system is fully simultaneous: the execution condition
involves $b_{\mathrm{d}}$ through $P_{\mathrm{e}}$, and the data
condition involves $b_{\mathrm{e}}, b_{\mathrm{s}}$ through the parent
quantities.

------------------------------------------------------------------------

## 3. Interior equilibrium: the incidence lemma

Before turning to the corner solution, it is useful to ask what happens
if all three fees remain above the protocol floor. In this case, the
bundle model preserves the same equilibrium quantities as the benchmark
specification. The difference lies in how the total cost is split across
the execution and data fees.

Suppose all three fees are interior. The execution and state conditions
pin the **bundle prices** exactly as the current report pins effective
prices:

$$
P_{\mathrm{e}}^* = p^0 \left( \frac{g_{\mathrm{e}}^0}{T_{\mathrm{e}}} \right)^{1/\epsilon_{\mathrm{e}}},
\qquad
P_{\mathrm{s}}^* = p^0 \left( \frac{g_{\mathrm{s}}^0}{T_{\mathrm{s}}} \right)^{1/\epsilon_{\mathrm{s}}} .
$$

Then $q_{\mathrm{e}}^* = T_{\mathrm{e}}/m_{\mathrm{e}}$ and
$q_{\mathrm{s}}^* = T_{\mathrm{s}}/m_{\mathrm{s}}$ --- identical to the
current benchmark --- so BAL equals the current $\widetilde B(\lambda)$,
and the data condition

$$
g_{\mathrm{static}}^0 \left( \frac{m_{\mathrm{data,static}}\, b_{\mathrm{d}}^*}{p^0} \right)^{-\epsilon_{\mathrm{d}}} = T_{\mathrm{d}} - \widetilde B(\lambda)
$$

gives **the same data fee as the current $\gamma = \beta = 0$
benchmark**. The only change is fee incidence:

$$
\boxed{\;
b_{\mathrm{e}}^* = \frac{P_{\mathrm{e}}^* - w_{\mathrm{e}}\, b_{\mathrm{d}}^*}{m_{\mathrm{e}}},
\qquad
b_{\mathrm{s}}^* = \frac{P_{\mathrm{s}}^* - w_{\mathrm{s}}\, b_{\mathrm{d}}^*}{m_{\mathrm{s}}}
\;}
$$

**Lemma (incidence).** *When all fees are interior, bundle pricing
leaves all equilibrium quantities and the data fee unchanged relative to
the current null benchmark; the execution and state fees fall
one-for-one with the BAL passthrough $w_i\, b_{\mathrm{d}}^*$.*

The intuition is simple: the target fixes how expensive execution must
be all-in; if part of that price is now collected through the data fee,
the execution fee must fall to compensate.

**Validity condition.** The interior solution exists only if the
passthrough leaves room for a fee above the floor:

$$
P_{\mathrm{e}}^* \;>\; w_{\mathrm{e}}\, b_{\mathrm{d}}^* + m_{\mathrm{e}}\, b_{\min},
$$

and analogously for state.

### 3.1 The condition fails in every paired scenario

Using the report's own benchmark fees (35-day elasticities,
$\lambda = 0$):

  ----------------------------------------------------------------------------------------------------------------
             Scenario      Required bundle                     BAL passthrough          Ratio              Implied
  ($T_{\mathrm{e}}$ /                price   $w_{\mathrm{e}} b_{\mathrm{d}}^*$                  $b_{\mathrm{e}}^*$
    $T_{\mathrm{d}}$)   $P_{\mathrm{e}}^*$                                                    
  ------------------- -------------------- ----------------------------------- -------------- --------------------
       136.3M / 15.0M            2,177 wei                          12,197 wei           5.6×       **−6,515 wei**

       163.5M / 18.0M              485 wei                           5,247 wei          10.8×       **−3,097 wei**

       204.4M / 22.5M               77 wei                           1,890 wei          24.6×       **−1,179 wei**

       272.6M / 30.0M                7 wei                             514 wei          72.1×         **−330 wei**
  ----------------------------------------------------------------------------------------------------------------

The BAL charge alone exceeds the market-clearing bundle price of
execution by factors of 5--72. **Every paired scenario in the current
report requires a negative execution fee under bundle pricing.** The
current model cannot detect this because its execution demand never sees
$b_{\mathrm{d}}$. State, by contrast, remains comfortably interior
everywhere: $P_{\mathrm{s}}^* \approx 6.70$M wei against a passthrough
of at most $\approx 7{,}200$ wei (0.1%).

------------------------------------------------------------------------

## 4. Corner equilibrium: execution at the floor

With $b_{\mathrm{e}} = b_{\min}$, execution's bundle price is

$$
P_{\mathrm{e}}(b_{\mathrm{d}}) = m_{\mathrm{e}}\, b_{\min} + w_{\mathrm{e}}\, b_{\mathrm{d}} \;\approx\; w_{\mathrm{e}}\, b_{\mathrm{d}}
\quad\text{for } b_{\mathrm{d}} \gg m_{\mathrm{e}}/w_{\mathrm{e}} \approx 22 \text{ wei},
$$

so **the data fee becomes the de facto execution price**: execution
activity is governed almost entirely by $b_{\mathrm{d}}$ through the BAL
line on the bill. State stays interior (its fee absorbs the small
passthrough), so $q_{\mathrm{s}}^* = T_{\mathrm{s}}/m_{\mathrm{s}}$ and
the state-linked BAL is the familiar constant
$w_{\mathrm{s}} T_{\mathrm{s}}/m_{\mathrm{s}} \approx 0.55$M.

The data market clears through a single equation in $b_{\mathrm{d}}$:

$$
F(b_{\mathrm{d}})
=
\underbrace{g_{\mathrm{static}}^0 \left( \frac{m_{\mathrm{data,static}}\, b_{\mathrm{d}}}{p^0} \right)^{-\epsilon_{\mathrm{d}}}}_{\text{static data}}
+
\underbrace{w_{\mathrm{e}}\, q_{\mathrm{e}}^0 \left( \frac{m_{\mathrm{e}} b_{\min} + w_{\mathrm{e}} b_{\mathrm{d}}}{p^0} \right)^{-\epsilon_{\mathrm{e}}}}_{\text{execution-linked BAL}}
+
\underbrace{\frac{w_{\mathrm{s}}\, T_{\mathrm{s}}}{m_{\mathrm{s}}}}_{\text{state-linked BAL}}
= T_{\mathrm{d}} .
$$

$F$ is continuous and strictly decreasing in $b_{\mathrm{d}}$, diverges
as $b_{\mathrm{d}} \to 0$, and tends to
$w_{\mathrm{s}} T_{\mathrm{s}}/m_{\mathrm{s}} \approx 0.55$M as
$b_{\mathrm{d}} \to \infty$ (execution-linked BAL now *falls with the
fee*, with elasticity $\epsilon_{\mathrm{e}}$). Hence a unique corner
equilibrium exists for any $T_{\mathrm{d}} > 0.55$M --- and even that
residual disappears once
$b_{\mathrm{d}} > (P_{\mathrm{s}}^* - m_{\mathrm{s}} b_{\min})/w_{\mathrm{s}} \approx 0.16$
gwei, where the state fee also floors and state activity begins to
decline with $b_{\mathrm{d}}$. **The infeasibility boundary is replaced
by a smooth corner equilibrium**; what remains is a steep-fee region,
and the qualitative mechanism that produces it (BAL crowding out static
data) survives in softened form.

Consistency check: the corner is the valid regime precisely when the
interior condition of §3 fails, so the two regimes partition the
parameter space with no gap.

### 4.1 Solved corner equilibria (35d, $\lambda = 0$, rounded anchors)

  -------------------------------------------------------------------------------------------------
     Scenario   $b_{\mathrm{d}}^*$          vs   Execution       BAL (share of   $b_{\mathrm{s}}^*$
                          (bundle)   benchmark        fill   $T_{\mathrm{d}}$) 
  ----------- -------------------- ----------- ----------- ------------------- --------------------
     136.3M /          109,071 wei      −36.5%    116.9M /       5.95M (39.7%)        1,183,741 wei
        15.0M                                       136.3M                     
                                                   (85.7%)                     

     163.5M /           40,478 wei      −45.2%    131.8M /       6.64M (36.9%)        1,184,247 wei
        18.0M                                       163.5M                     
                                                   (80.6%)                     

     204.4M /           12,344 wei      −53.6%    152.1M /       7.58M (33.7%)        1,184,454 wei
        22.5M                                       204.4M                     
                                                   (74.4%)                     

     272.6M /            2,766 wei      −61.8%    182.2M /       8.97M (29.9%)        1,184,525 wei
        30.0M                                       272.6M                     
                                                   (66.9%)                     
  -------------------------------------------------------------------------------------------------

The corner solution leads to three main changes:

1.  **Execution targets are unreachable in every paired scenario** ---
    not because demand is inadequate at low prices (the current Appendix
    B story, which appears only under the 60/75d elasticities), but
    because the BAL charge taxes execution above its market-clearing
    bundle price. This holds under the *central* 35-day estimates.
2.  **Data fees fall 37--62%**, because execution-linked BAL now yields
    to the data fee with elasticity $\epsilon_{\mathrm{e}}$ instead of
    being fixed.
3.  **Once execution floors, the execution target drops out of the data
    equilibrium entirely** --- $T_{\mathrm{e}}$ appears nowhere in
    $F(b_{\mathrm{d}})$. The current report's most alarming cell (600M
    limit / 15M data target: 96% BAL occupancy, 15.72 gwei) collapses to
    the same equilibrium as the 272.6M-limit case:
    $b_{\mathrm{d}}^* \approx 109{,}071$ wei with BAL at 39.7% of target
    and execution filling 116.9M regardless of the 300M target. The
    steep execution-data interaction in the current capacity grid is
    largely an artifact of scaling BAL to targets that the bundle-priced
    market never fills.

------------------------------------------------------------------------

## 5. What should change in the reports

**BAL/data-metering report (Report 3):**

-   Replace §"BAL demand model" onward: drop Model A entirely and
    reframe Model B as the transaction-level *implementation* of the
    bundle model (see §6.1). Define
    $w_{\mathrm{e}}(\lambda), w_{\mathrm{s}}(\lambda)$ and present the
    BAL identity
    $g_{\mathrm{BAL}} = w_{\mathrm{e}} q_{\mathrm{e}} + w_{\mathrm{s}} q_{\mathrm{s}}$.
-   The $\lambda$ discussion survives unchanged --- it now parameterizes
    the intensities $w_{\mathrm{e}}, w_{\mathrm{s}}$ rather than routing
    weights in a separate BAL equation.
-   The parameters table drops $\gamma_{\mathrm{BAL}}$ and
    $\beta_{\mathrm{BAL}}$, and adds $w_{\mathrm{e}}, w_{\mathrm{s}}$ at
    each $\lambda$.

**Full-equilibrium report (Report 4):**

-   §"Equilibrium model": replace effective prices with bundle prices
    for execution and state; state the simultaneous system with floors
    (§2 above).
-   Add the incidence lemma (§3) --- it is worth keeping because it
    shows the bundle model *nests* the current benchmark: same
    quantities, same data fee, shifted incidence, whenever fees are
    interior.
-   Add the validity table (§3.1) and the corner derivation (§4). The
    paired-scenario table becomes the corner table (§4.1).
-   Rewrite §"Minimum data target implied by BAL": the linear boundary
    $T_{\mathrm{data}}^{\min} = 0.55\mathrm{M} + 0.046\,T_{\mathrm{execution}}$
    remains meaningful **only as a full-utilization worst case** (all
    targets filled by fiat). Under bundle pricing the equilibrium never
    sits on it; the binding constant is the state-linked $0.55$M (for
    $b_{\mathrm{d}} < 0.16$ gwei), and above that, nothing. Present the
    old boundary as "conservative design envelope," the new one as
    "equilibrium outcome."
-   §"Demand adequacy" merges with the corner analysis: unreachable
    execution targets are now the *generic* outcome (all windows, all
    paired scenarios), driven by BAL passthrough rather than only by low
    elasticity at the floor. Appendix B should re-solve the corner
    system per elasticity window --- the mechanism is robust across
    windows because the passthrough dominates $P_{\mathrm{e}}^*$ by
    large factors.
-   The two BAL sensitivity figures ($\lambda$, $\beta_{\mathrm{BAL}}$)
    reduce to one ($\lambda$ only).

**Presentation note.** The single most communicable result: *under
EIP-7999, charging BAL as data gas makes the data fee the effective
price of execution whenever execution capacity is generous.* At a 272.6M
execution limit, a user's execution bill is \~2,180 wei per historical
gas unit via the execution fee but \~7,750 wei via the BAL line.
Fee-market designers should understand that the data fee, not the
execution fee, is the lever that governs execution inclusion in this
regime.

------------------------------------------------------------------------

## 6. Extensions and caveats

### 6.1 Heterogeneous BAL intensity (transaction-level implementation)

$w_{\mathrm{e}}$ is an average; transactions differ widely in BAL bytes
per unit of execution gas, and high-$w$ transactions face a larger
bundle-price increase and exit first. The existing 996,163-transaction
panel built for $\Psi_{\mathrm{BAL}}$ supports the heterogeneous version
directly: give each transaction $j$ its own passthrough
$w_j = g_{\mathrm{BAL},j}/g_{\mathrm{execution},j}$ and aggregate
execution demand as the execution-gas-weighted response to each
transaction's own bundle-price ratio,

$$
\frac{q_{\mathrm{e}}(b_{\mathrm{e}}, b_{\mathrm{d}})}{q_{\mathrm{e}}^0}
=
\frac{\sum_j g_{\mathrm{execution},j} \left( \dfrac{m_{\mathrm{e}} b_{\mathrm{e}} + w_j b_{\mathrm{d}}}{p^0} \right)^{-\epsilon_{\mathrm{e}}}}{\sum_j g_{\mathrm{execution},j}},
$$

with BAL aggregated using the same per-transaction responses weighted by
$g_{\mathrm{BAL},j}$. This is exactly the $\Psi$ machinery, re-pointed
at parent quantities. Because the exiting transactions are BAL-heavy,
aggregate BAL falls *faster* than the average-$w$ model predicts, so
§4's numbers are conservative for BAL pressure (and slightly optimistic
for execution fill).

### 6.2 Maintained assumptions

-   **Constant intensity ($\rho_A = 1$).** $w_{\mathrm{e}}$ constant as
    execution scales far above the anchor is the same proportionality
    assumption flagged for the current model; it deserves the same sweep
    (e.g., $\rho_A \in \{0.75, 1, 1.25\}$), now applied to the
    intensities.
-   **Salience.** The model assumes users respond to the all-in bill.
    Wallets display total fees, so full salience is the natural
    benchmark; partial salience would place outcomes between the current
    model ($w$ effectively 0 in parent demand) and this one --- which
    brackets the truth.
-   **Elasticity transfer.** The bundle prices in the corner regime sit
    well below the anchor, so the isoelastic extrapolation caveats from
    the earlier reviews apply here with equal force. Orderings and
    regime classifications (interior vs corner) are robust; wei-level
    fees are functional-form outputs.
-   **Independent parents.** The model retains independent demand curves
    for execution, state, and static data, and reroutes only where the
    BAL charge lands. A fully general bundle model (transactions
    demanding cost composites across all resources) would abandon the
    estimated framework; that is a separate, larger project.

### 6.3 Numerical notes

All figures in this note use $p^0 = 0.10693$ gwei, the rounded anchors
($q_{\mathrm{e}}^0 = 23.942$M, $q_{\mathrm{s}}^0 = 5.244$M,
$g_{\mathrm{static}}^0 = 2.134$M, $g_{\mathrm{BAL}}^0 = 1.919$M),
multipliers ($1.537898$, $5.656315$, $1.807251$), and 35-day
elasticities ($0.121160$, $0.229476$, $0.334864$). The corner equation
$F(b_{\mathrm{d}}) = T_{\mathrm{d}}$ was solved by bisection. Please
recompute in the notebooks with full-precision anchors and add the
corner solver next to the existing equilibrium code
(`src/demand/equilibrium.py` is the natural home).
