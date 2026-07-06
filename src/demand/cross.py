"""Cross-price elasticity matrix demand for the A/B simulation step.

The share model (model.py) encodes pure *substitution*: resources compete for
one budget, so every cross-price effect is positive. Transactions, however,
consume execution, data, and state *together*, so pricing out a state-heavy
transaction also removes the execution and data it carried — a *complementary*
(negative) cross effect the share model cannot represent.

This module recomposes demand as a constant-elasticity matrix around an
anchor:

    Q_i = Q_i_ref * prod_j (r_j ** E[i][j])

with the matrix built in two measurable parts:

    E = share_model_jacobian(anchor, params)   # substitution, from Maria
      + coupling_matrix(exposures, own_price)  # complementarity, measured

``share_model_jacobian`` is the numeric log-Jacobian of the existing share
model at the anchor, so with zero coupling the matrix model reproduces the
share model exactly at the anchor (and approximately nearby — the matrix
freezes elasticities that the share model lets drift with the mix).

``coupling_matrix`` uses bundle-exit logic: when resource j's price removes
its marginal transactions, resource i leaves in proportion to how much of i
rides inside j-heavy transactions. With exposures phi[i][j] (the share of
resource i carried by transactions weighted by j's within-tx cost share):

    gamma[i][j] = -eps_own[j] * phi[i][j]        (i != j; diagonal zero)

Exposures are measured from per-transaction resource decompositions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from .model import RESOURCES, Anchor, DemandParams, demand_at_price_ratios

Matrix = dict[str, dict[str, float]]


def share_model_jacobian(
    anchor: Anchor,
    params: DemandParams,
    *,
    bump: float = 1e-6,
) -> Matrix:
    """Numeric log-Jacobian E[i][j] = dln Q_i / dln r_j at the anchor."""

    base = demand_at_price_ratios(
        anchor, params, {name: 1.0 for name in RESOURCES}
    )
    jacobian: Matrix = {i: {} for i in RESOURCES}
    for j in RESOURCES:
        ratios = {name: 1.0 for name in RESOURCES}
        ratios[j] = 1.0 + bump
        bumped = demand_at_price_ratios(anchor, params, ratios)
        for i in RESOURCES:
            jacobian[i][j] = (
                math.log(bumped[i]) - math.log(base[i])
            ) / math.log(1.0 + bump)
    return jacobian


def implied_own_price_elasticities(jacobian: Matrix) -> dict[str, float]:
    """Own-price elasticities as positive numbers, from the matrix diagonal."""

    return {name: -jacobian[name][name] for name in RESOURCES}


def coupling_exposures_from_transactions(
    frame: pd.DataFrame,
    *,
    execution_col: str,
    data_col: str,
    state_col: str,
) -> Matrix:
    """Measure bundle exposures phi[i][j] from per-transaction quantities.

    phi[i][j] = sum_tx q_i,tx * s_j,tx / Q_i, where s_j,tx is resource j's
    share of the transaction's total (old-gas) resource cost. It answers:
    "if transactions exit in proportion to their j-intensity, what fraction
    of resource i exits with them". Diagonal entries are included for
    diagnostics but the coupling matrix only uses off-diagonals.
    """

    quantities = pd.DataFrame(
        {
            "execution": frame[execution_col].clip(lower=0).astype(float),
            "data": frame[data_col].clip(lower=0).astype(float),
            "state": frame[state_col].clip(lower=0).astype(float),
        }
    )
    totals = quantities.sum(axis=1)
    keep = totals > 0
    quantities = quantities[keep]
    totals = totals[keep]

    exposures: Matrix = {i: {} for i in RESOURCES}
    resource_totals = quantities.sum()
    for j in RESOURCES:
        tx_share_j = quantities[j] / totals
        for i in RESOURCES:
            exposures[i][j] = float(
                (quantities[i] * tx_share_j).sum() / resource_totals[i]
            )
    return exposures


def coupling_matrix(
    exposures: Matrix,
    own_price_elasticities: Mapping[str, float],
) -> Matrix:
    """Complementary (negative) cross terms from bundle-exit exposures."""

    gamma: Matrix = {i: {} for i in RESOURCES}
    for i in RESOURCES:
        for j in RESOURCES:
            if i == j:
                gamma[i][j] = 0.0
            else:
                gamma[i][j] = -float(own_price_elasticities[j]) * float(
                    exposures[i][j]
                )
    return gamma


def combine_matrices(*matrices: Matrix) -> Matrix:
    combined: Matrix = {
        i: {j: 0.0 for j in RESOURCES} for i in RESOURCES
    }
    for matrix in matrices:
        for i in RESOURCES:
            for j in RESOURCES:
                combined[i][j] += float(matrix[i][j])
    return combined


@dataclass(frozen=True)
class CrossElasticityDemand:
    """Constant-elasticity-matrix demand around an anchor.

    Plugs into ``solve_equilibrium(..., demand_fn=model.quantities)``.
    """

    anchor: Anchor
    matrix: Matrix

    def __post_init__(self) -> None:
        for i in RESOURCES:
            if i not in self.matrix:
                raise ValueError(f"matrix missing row for {i!r}")
            for j in RESOURCES:
                if j not in self.matrix[i]:
                    raise ValueError(f"matrix missing entry [{i!r}][{j!r}]")

    def quantities(self, price_ratios: Mapping[str, float]) -> dict[str, float]:
        out = {}
        for i in RESOURCES:
            log_q = math.log(self.anchor.quantities[i])
            for j in RESOURCES:
                ratio = float(price_ratios[j])
                if ratio <= 0:
                    raise ValueError(f"price ratio for {j!r} must be positive")
                log_q += self.matrix[i][j] * math.log(ratio)
            out[i] = math.exp(log_q)
        return out
