"""Equilibrium solve: demand system + a world's fee mechanism.

A world is a set of metering multipliers (metered gas per old-gas physical
unit) plus fee dimensions. Each dimension carries one price and one target;
its usage is ``max over groups of (sum of metered gas within the group)``,
which expresses all three mechanisms in one shape:

    G0 (Glamsterdam):  1 dim, groups [[execution, data], [state]]
                       -> max(regular, state) under a single price
    A  (8037 + data):  dim "execution_state" groups [[execution], [state]],
                       dim "data" groups [[data]]
    B  (full 7999):    3 dims, one per resource

Equilibrium condition per dimension (targeting fee markets): either usage
equals the target at a price above the floor, or the price sits at the floor
with usage below target (supply-abundant corner). The corner is reported via
``floor_binding`` — at fee floors the constant-elasticity demand curve is
extrapolated far outside the estimation range, so treat those quantities as
"demand does not reach the target", not as point predictions. The same
extrapolation caveat applies to interior equilibria reached through large
share shifts: as a resource's effective price falls far below the anchor,
the share logistic pushes its share toward 1, which is exactly why eta is
swept rather than fixed.

Chaining: ``anchor_from_equilibrium`` turns a solved world into the anchor
for the next link (H0 -> G0 -> A/B), which is the whole one-operator design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .model import RESOURCES, Anchor, DemandParams, demand_at_price_ratios, price_index_ratio

DemandFn = Callable[[Mapping[str, float]], dict[str, float]]


@dataclass(frozen=True)
class FeeDimension:
    name: str
    groups: tuple[tuple[str, ...], ...]
    target_gas: float
    price_floor_wei: float = 1.0

    def __post_init__(self) -> None:
        if not self.groups or any(not group for group in self.groups):
            raise ValueError("groups must be non-empty")
        for group in self.groups:
            for resource in group:
                if resource not in RESOURCES:
                    raise ValueError(f"unknown resource {resource!r}")
        if self.target_gas <= 0:
            raise ValueError("target_gas must be positive")
        if self.price_floor_wei <= 0:
            raise ValueError("price_floor_wei must be positive")

    @property
    def members(self) -> tuple[str, ...]:
        return tuple(resource for group in self.groups for resource in group)


@dataclass(frozen=True)
class WorldSpec:
    name: str
    multipliers: Mapping[str, float]
    dimensions: tuple[FeeDimension, ...]

    def __post_init__(self) -> None:
        for name in RESOURCES:
            if name not in self.multipliers:
                raise ValueError(f"missing metering multiplier for {name!r}")
            if self.multipliers[name] <= 0:
                raise ValueError(f"multiplier for {name!r} must be positive")
        covered = [r for dim in self.dimensions for r in dim.members]
        if sorted(covered) != sorted(RESOURCES):
            raise ValueError(
                "fee dimensions must cover each resource exactly once, got "
                f"{sorted(covered)}"
            )

    def dimension_of(self, resource: str) -> FeeDimension:
        for dim in self.dimensions:
            if resource in dim.members:
                return dim
        raise KeyError(resource)


@dataclass(frozen=True)
class Equilibrium:
    world: str
    prices_wei: dict[str, float]
    floor_binding: dict[str, bool]
    target_unreachable: dict[str, bool]
    quantities: dict[str, float]
    metered_usage: dict[str, float]
    binding_group: dict[str, int]
    targets: dict[str, float]
    total_physical: float
    alpha_state: float
    demand_expansion: float
    price_index_ratio: float
    effective_price_ratios: dict[str, float]
    converged: bool
    sweeps: int
    params: DemandParams = field(repr=False, default=None)  # type: ignore[assignment]


def _price_ratios(
    anchor: Anchor,
    world: WorldSpec,
    prices_wei: Mapping[str, float],
) -> dict[str, float]:
    ratios = {}
    for resource in RESOURCES:
        dim = world.dimension_of(resource)
        effective = world.multipliers[resource] * float(prices_wei[dim.name])
        ratios[resource] = effective / anchor.effective_prices[resource]
    return ratios


def _dimension_usage(
    dim: FeeDimension,
    world: WorldSpec,
    quantities: Mapping[str, float],
) -> tuple[float, int]:
    sums = [
        sum(world.multipliers[r] * quantities[r] for r in group)
        for group in dim.groups
    ]
    best = max(range(len(sums)), key=lambda i: sums[i])
    return sums[best], best


def _usage_at(
    anchor: Anchor,
    demand_fn: DemandFn,
    world: WorldSpec,
    prices_wei: Mapping[str, float],
    dim: FeeDimension,
) -> tuple[float, int]:
    quantities = demand_fn(_price_ratios(anchor, world, prices_wei))
    return _dimension_usage(dim, world, quantities)


def _solve_dimension_price(
    anchor: Anchor,
    demand_fn: DemandFn,
    world: WorldSpec,
    prices_wei: dict[str, float],
    dim: FeeDimension,
    *,
    max_iter: int = 200,
    rel_tol: float = 1e-10,
    max_doublings: int = 500,
) -> tuple[float, str]:
    """Price for one dimension holding the others fixed.

    Returns ``(price_wei, status)`` with ``status`` one of:

    - ``"floor"``: usage at the price floor is already at/below target
      (supply-abundant corner) -- the fee does not activate.
    - ``"interior"``: the target is met at a price above the floor (the
      normal targeting-market solution).
    - ``"ceiling"``: usage stays above target even at an extreme price
      (target unreachable). This is the inelastic-demand corner: when a
      resource's own-price elasticity is near zero and substitution from a
      neighbouring dimension pushes its usage above target, no finite price
      brings it back down. Reported (not raised) so the caller can flag it;
      the coupling matrix, whose complementarity pulls the resource back
      down, typically turns these back into interior solves.

    Bisection on log-price against the usage-equals-target condition; usage
    falls in own price, so the root is bracketed by doubling from the floor.
    """

    floor = float(dim.price_floor_wei)
    trial = dict(prices_wei)

    trial[dim.name] = floor
    usage_floor, _ = _usage_at(anchor, demand_fn, world, trial, dim)
    if usage_floor <= dim.target_gas:
        return floor, "floor"

    low = floor
    high = max(floor * 2.0, 1.0)
    for _ in range(max_doublings):
        trial[dim.name] = high
        usage_high, _ = _usage_at(anchor, demand_fn, world, trial, dim)
        if usage_high <= dim.target_gas:
            break
        low = high
        high *= 2.0
    else:
        return high, "ceiling"

    log_low, log_high = math.log(low), math.log(high)
    for _ in range(max_iter):
        log_mid = 0.5 * (log_low + log_high)
        trial[dim.name] = math.exp(log_mid)
        usage_mid, _ = _usage_at(anchor, demand_fn, world, trial, dim)
        if usage_mid > dim.target_gas:
            log_low = log_mid
        else:
            log_high = log_mid
        if log_high - log_low < rel_tol:
            break
    return math.exp(0.5 * (log_low + log_high)), "interior"


def solve_equilibrium(
    anchor: Anchor,
    params: DemandParams,
    world: WorldSpec,
    *,
    demand_fn: DemandFn | None = None,
    max_sweeps: int = 200,
    rel_tol: float = 1e-9,
) -> Equilibrium:
    """Gauss-Seidel over fee dimensions until prices stop moving.

    ``demand_fn`` overrides the share-model demand with any callable mapping
    effective-price ratios to physical quantities (e.g. a
    ``CrossElasticityDemand.quantities``); by default the share model in
    ``params`` is used.
    """

    if demand_fn is None:
        def demand_fn(ratios: Mapping[str, float]) -> dict[str, float]:
            return demand_at_price_ratios(anchor, params, ratios)

    prices = {dim.name: float(dim.price_floor_wei) for dim in world.dimensions}
    floor_binding = {dim.name: True for dim in world.dimensions}
    target_unreachable = {dim.name: False for dim in world.dimensions}

    converged = False
    sweeps = 0
    for sweeps in range(1, max_sweeps + 1):
        max_change = 0.0
        for dim in world.dimensions:
            new_price, status = _solve_dimension_price(
                anchor, demand_fn, world, prices, dim
            )
            change = abs(math.log(new_price) - math.log(prices[dim.name]))
            max_change = max(max_change, change)
            prices[dim.name] = new_price
            floor_binding[dim.name] = status == "floor"
            target_unreachable[dim.name] = status == "ceiling"
        if max_change < rel_tol:
            converged = True
            break

    ratios = _price_ratios(anchor, world, prices)
    quantities = demand_fn(ratios)
    usage = {}
    binding_group = {}
    for dim in world.dimensions:
        dim_usage, group_index = _dimension_usage(dim, world, quantities)
        usage[dim.name] = dim_usage
        binding_group[dim.name] = group_index

    total = sum(quantities[name] for name in RESOURCES)
    return Equilibrium(
        world=world.name,
        prices_wei=prices,
        floor_binding=floor_binding,
        target_unreachable=target_unreachable,
        quantities=quantities,
        metered_usage=usage,
        binding_group=binding_group,
        targets={dim.name: dim.target_gas for dim in world.dimensions},
        total_physical=total,
        alpha_state=quantities["state"] / total,
        demand_expansion=total / anchor.total,
        price_index_ratio=price_index_ratio(anchor, ratios),
        effective_price_ratios=ratios,
        converged=converged,
        sweeps=sweeps,
        params=params,
    )


def anchor_from_equilibrium(
    anchor: Anchor,
    world: WorldSpec,
    equilibrium: Equilibrium,
) -> Anchor:
    """Re-anchor the demand system on a solved world (the chain step)."""

    effective_prices = {
        resource: world.multipliers[resource]
        * equilibrium.prices_wei[world.dimension_of(resource).name]
        for resource in RESOURCES
    }
    return Anchor(
        quantities=dict(equilibrium.quantities),
        effective_prices=effective_prices,
    )
