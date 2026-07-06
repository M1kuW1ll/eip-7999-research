"""Two-stage demand system over transaction-bundle resources.

Implements Maria's aggregate + share structure from the elasticity post,
generalized to the three-resource split used in this project:

    aggregate:  T = T_ref * R^(-eps_agg)          R = spend-share weighted
                                                   effective-price ratio index
    top share:  alpha(x) = 1 / (1 + kappa * x^eta_state)
                kappa = (1 - alpha_ref) / alpha_ref, so alpha(1) = alpha_ref
    bottom:     data vs execution within "rest", fixed split by default
                (eta_data = 0), optional relative-price score split.

Quantities are in *physical* units chosen as current-schedule ("old") gas,
so H0 metering multipliers are 1 by construction and a world repricing shows
up purely as an effective-price change.

The share argument ``x`` depends on ``share_mode``. Maria's eta was estimated
in a one-price world, which cannot distinguish two structural readings, so
both are implemented and swept:

- ``"maria_own_price"``: x = r_state (her published functional form). The
  state share responds to state's *absolute* effective price, so a uniform
  fall in all prices raises the state share (state is the elastic resource).
- ``"relative_state_vs_rest"``: x = r_state / r_rest, with r_rest the
  spend-weighted execution+data price ratio. The state share responds only
  to *relative* prices; uniform price moves leave the mix unchanged. Also
  level-invariant at fee floors, so it avoids the alpha -> 1 extrapolation.

The two modes can disagree in sign under Glamsterdam (state's relative price
rises ~5.7x while its absolute effective price falls), so mode disagreement
is itself a reported finding, not noise.

Design notes:
- H0 is observed; anchors from counterfactual equilibria re-use the same
  system, which is what makes the H0 -> G0 -> B chain one operator applied
  per link.
- Per-resource elasticities are outputs, not inputs: at the anchor,
  eps_state = eps_agg + eta_state * (1 - alpha_ref) and
  eps_rest = eps_agg - eta_state * alpha_ref (Maria's recovered 0.51 / 0.08).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

RESOURCES = ("execution", "data", "state")
SHARE_MODES = ("maria_own_price", "relative_state_vs_rest")


@dataclass(frozen=True)
class Anchor:
    """Reference point: physical quantities and absolute effective prices.

    ``quantities`` are per block in old-gas physical units. ``effective_prices``
    are wei per old-gas unit. For the H0 anchor every resource has the same
    effective price (the observed base fee); re-anchoring on a counterfactual
    equilibrium generally gives different per-resource effective prices.
    """

    quantities: Mapping[str, float]
    effective_prices: Mapping[str, float]

    def __post_init__(self) -> None:
        for name in RESOURCES:
            if name not in self.quantities:
                raise ValueError(f"missing quantity for resource {name!r}")
            if name not in self.effective_prices:
                raise ValueError(f"missing effective price for {name!r}")
            if self.quantities[name] < 0:
                raise ValueError(f"quantity for {name!r} must be non-negative")
            if self.effective_prices[name] <= 0:
                raise ValueError(f"effective price for {name!r} must be positive")
        if self.total <= 0:
            raise ValueError("total anchor quantity must be positive")
        if self.quantities["state"] <= 0:
            raise ValueError("state anchor quantity must be positive")
        rest = self.quantities["execution"] + self.quantities["data"]
        if rest <= 0:
            raise ValueError("execution + data anchor quantity must be positive")

    @property
    def total(self) -> float:
        return float(sum(self.quantities[name] for name in RESOURCES))

    @property
    def alpha_state(self) -> float:
        return float(self.quantities["state"]) / self.total

    @property
    def data_share_of_rest(self) -> float:
        rest = self.quantities["execution"] + self.quantities["data"]
        return float(self.quantities["data"]) / rest

    @property
    def spend_shares(self) -> dict[str, float]:
        spend = {
            name: self.quantities[name] * self.effective_prices[name]
            for name in RESOURCES
        }
        total = sum(spend.values())
        return {name: value / total for name, value in spend.items()}

    @property
    def rest_exec_spend_weight(self) -> float:
        """Execution's spend weight within the rest (execution + data) bundle."""

        spend_exec = self.quantities["execution"] * self.effective_prices["execution"]
        spend_data = self.quantities["data"] * self.effective_prices["data"]
        return spend_exec / (spend_exec + spend_data)

    @classmethod
    def from_single_price(
        cls,
        *,
        total_gas: float,
        base_fee_wei: float,
        shares: Mapping[str, float],
    ) -> "Anchor":
        """H0-style anchor: one observed price, old-gas shares."""

        share_sum = sum(float(shares[name]) for name in RESOURCES)
        if abs(share_sum - 1.0) > 1e-9:
            raise ValueError(f"shares must sum to 1, got {share_sum}")
        return cls(
            quantities={
                name: float(total_gas) * float(shares[name]) for name in RESOURCES
            },
            effective_prices={name: float(base_fee_wei) for name in RESOURCES},
        )


@dataclass(frozen=True)
class DemandParams:
    eps_agg: float
    eta_state: float
    eta_data: float = 0.0
    share_mode: str = "maria_own_price"

    def __post_init__(self) -> None:
        if self.eps_agg < 0:
            raise ValueError("eps_agg must be non-negative")
        if self.eta_state < 0 or self.eta_data < 0:
            raise ValueError("eta values must be non-negative")
        if self.share_mode not in SHARE_MODES:
            raise ValueError(
                f"share_mode must be one of {SHARE_MODES}, got {self.share_mode!r}"
            )


def demand_at_price_ratios(
    anchor: Anchor,
    params: DemandParams,
    price_ratios: Mapping[str, float],
) -> dict[str, float]:
    """Physical quantities demanded at effective-price ratios vs the anchor.

    ``price_ratios[i] = p_i_effective / anchor.effective_prices[i]``; passing
    all ones returns the anchor quantities exactly.
    """

    for name in RESOURCES:
        if name not in price_ratios:
            raise ValueError(f"missing price ratio for resource {name!r}")
        if price_ratios[name] <= 0:
            raise ValueError(f"price ratio for {name!r} must be positive")

    alpha_ref = anchor.alpha_state
    kappa = (1.0 - alpha_ref) / alpha_ref
    r_state = float(price_ratios["state"])
    if params.share_mode == "maria_own_price":
        share_argument = r_state
    else:  # relative_state_vs_rest
        w_exec = anchor.rest_exec_spend_weight
        r_rest = w_exec * float(price_ratios["execution"]) + (1.0 - w_exec) * float(
            price_ratios["data"]
        )
        share_argument = r_state / r_rest
    alpha = 1.0 / (1.0 + kappa * share_argument**params.eta_state)

    weights = anchor.spend_shares
    index_ratio = sum(
        weights[name] * float(price_ratios[name]) for name in RESOURCES
    )
    total = anchor.total * index_ratio ** (-params.eps_agg)

    w_ref = anchor.data_share_of_rest
    if params.eta_data == 0.0 or w_ref in (0.0, 1.0):
        w_data = w_ref
    else:
        score_data = w_ref * float(price_ratios["data"]) ** (-params.eta_data)
        score_exec = (1.0 - w_ref) * float(price_ratios["execution"]) ** (
            -params.eta_data
        )
        w_data = score_data / (score_data + score_exec)

    rest = (1.0 - alpha) * total
    return {
        "state": alpha * total,
        "data": w_data * rest,
        "execution": (1.0 - w_data) * rest,
    }


def price_index_ratio(
    anchor: Anchor,
    price_ratios: Mapping[str, float],
) -> float:
    weights = anchor.spend_shares
    return float(
        sum(weights[name] * float(price_ratios[name]) for name in RESOURCES)
    )


def implied_anchor_elasticities(
    anchor: Anchor,
    params: DemandParams,
) -> dict[str, float]:
    """Elasticities to a *uniform* price move, implied at the anchor.

    In ``maria_own_price`` mode these are the numbers to sanity-check against
    Maria's recovered central scenario (state ~0.51, burst/rest ~0.08); they
    are outputs of (eps_agg, eta_state), never separate inputs.

    In ``relative_state_vs_rest`` mode a uniform move leaves relative prices
    (and hence shares) unchanged, so every resource responds with eps_agg;
    the eta_state substitution appears only for relative price moves.
    """

    alpha_ref = anchor.alpha_state
    if params.share_mode == "maria_own_price":
        return {
            "state": params.eps_agg + params.eta_state * (1.0 - alpha_ref),
            "rest": params.eps_agg - params.eta_state * alpha_ref,
        }
    return {"state": params.eps_agg, "rest": params.eps_agg}
