import pytest

from demand import (
    Anchor,
    DemandParams,
    FeeDimension,
    WorldSpec,
    anchor_from_equilibrium,
    solve_equilibrium,
)

P_REF = 0.33e9


def panel_anchor() -> Anchor:
    return Anchor.from_single_price(
        total_gas=30_400_000,
        base_fee_wei=P_REF,
        shares={"execution": 0.797, "data": 0.034, "state": 0.169},
    )


def g0_world(target: float = 50_000_000) -> WorldSpec:
    # Measured pilot/panel multipliers: state x5.69; data carries the 7976
    # floor uplift + 7981 surcharge (~2.1x its old gas); execution unchanged.
    return WorldSpec(
        name="g0",
        multipliers={"execution": 1.0, "data": 2.13, "state": 5.69},
        dimensions=(
            FeeDimension(
                name="regular_state",
                groups=(("execution", "data"), ("state",)),
                target_gas=target,
            ),
        ),
    )


def b_world(
    *,
    execution_target: float,
    data_target: float,
    state_target: float,
) -> WorldSpec:
    return WorldSpec(
        name="b",
        multipliers={"execution": 1.0, "data": 2.13, "state": 5.69},
        dimensions=(
            FeeDimension(name="execution", groups=(("execution",),), target_gas=execution_target),
            FeeDimension(name="data", groups=(("data",),), target_gas=data_target),
            FeeDimension(name="state", groups=(("state",),), target_gas=state_target),
        ),
    )


def test_g0_interior_equilibrium_hits_target():
    anchor = panel_anchor()
    params = DemandParams(eps_agg=0.175, eta_state=0.43)
    eq = solve_equilibrium(anchor, params, g0_world())

    assert eq.converged
    assert not eq.floor_binding["regular_state"]
    assert eq.metered_usage["regular_state"] == pytest.approx(50_000_000, rel=1e-6)
    # Repriced demand at unchanged behavior is ~29-30M vs the 50M target, so
    # the equilibrium price must fall below today's and demand must expand.
    assert eq.prices_wei["regular_state"] < P_REF
    assert eq.demand_expansion > 1.0
    # State is the bottleneck side of max(regular, state) at these multipliers.
    assert eq.binding_group["regular_state"] == 1


def test_g0_with_tiny_target_prices_above_reference():
    anchor = panel_anchor()
    params = DemandParams(eps_agg=0.175, eta_state=0.43)
    eq = solve_equilibrium(anchor, params, g0_world(target=15_000_000))

    assert eq.converged
    assert not eq.floor_binding["regular_state"]
    assert eq.prices_wei["regular_state"] > P_REF
    assert eq.demand_expansion < 1.0


def test_b_design_targets_eta_flips_state_between_dormant_and_filled():
    """The eta sweep IS the state un-throttling question, in one test.

    With eta = 0.43 (Maria's substitution), a cheap separate state fee pulls
    demand into state until the 75M target fills at a real price. With
    eta = 0 (fixed shares), state demand cannot reach the target and the
    state fee sits at the floor. Both legs lean on out-of-sample
    extrapolation of the share logistic -- that is why eta is swept.
    """

    anchor = panel_anchor()
    world = b_world(
        execution_target=30_000_000,
        data_target=15_000_000,
        state_target=75_000_000,
    )

    substituting = solve_equilibrium(
        anchor, DemandParams(eps_agg=0.175, eta_state=0.43), world
    )
    assert substituting.converged
    assert not substituting.floor_binding["execution"]
    assert substituting.metered_usage["execution"] == pytest.approx(
        30_000_000, rel=1e-6
    )
    # State fills its target at a real (above-floor) price, and the state
    # share expands well past the anchor share.
    assert not substituting.floor_binding["state"]
    assert substituting.metered_usage["state"] == pytest.approx(
        75_000_000, rel=1e-6
    )
    assert substituting.prices_wei["state"] > 1.0
    assert substituting.alpha_state > anchor.alpha_state
    # Data demand cannot reach 15M even free.
    assert substituting.floor_binding["data"]
    assert substituting.metered_usage["data"] < 15_000_000

    fixed_shares = solve_equilibrium(
        anchor, DemandParams(eps_agg=0.175, eta_state=0.0), world
    )
    assert fixed_shares.converged
    assert fixed_shares.floor_binding["state"]
    assert fixed_shares.metered_usage["state"] < 75_000_000
    assert fixed_shares.prices_wei["state"] == pytest.approx(1.0)


def test_b_reachable_targets_are_interior_when_data_can_substitute():
    # With eta_data > 0 the within-rest split has its own degree of freedom,
    # so execution and data fee markets can both be interior. (With
    # eta_data = 0 that is impossible off the ratio-consistent knife edge --
    # see the complements test below.)
    anchor = panel_anchor()
    params = DemandParams(eps_agg=0.175, eta_state=0.43, eta_data=0.3)
    eq = solve_equilibrium(
        anchor,
        params,
        b_world(
            execution_target=20_000_000,
            data_target=1_600_000,
            state_target=25_000_000,
        ),
    )

    assert eq.converged
    for dim in ("execution", "data", "state"):
        assert not eq.floor_binding[dim]
        assert eq.metered_usage[dim] == pytest.approx(eq.targets[dim], rel=1e-6)


def test_b_data_throttling_spills_into_execution_when_complements():
    # With eta_data = 0 the within-rest split is fixed, so cutting data works
    # only through the aggregate index -- and drags execution down with it.
    # A data target far below anchor usage can therefore push execution to
    # the floor below its own target: jointly infeasible targets are a real
    # model outcome, not a solver failure.
    anchor = panel_anchor()
    params = DemandParams(eps_agg=0.175, eta_state=0.43)
    eq = solve_equilibrium(
        anchor,
        params,
        b_world(
            execution_target=20_000_000,
            data_target=1_500_000,
            state_target=20_000_000,
        ),
    )

    assert eq.converged
    assert not eq.floor_binding["data"]
    assert eq.metered_usage["data"] == pytest.approx(1_500_000, rel=1e-6)
    assert eq.floor_binding["execution"]
    assert eq.metered_usage["execution"] < 20_000_000


def test_chain_reanchoring_roundtrip():
    anchor = panel_anchor()
    params = DemandParams(eps_agg=0.175, eta_state=0.43)
    world = g0_world()
    eq = solve_equilibrium(anchor, params, world)

    g0_anchor = anchor_from_equilibrium(anchor, world, eq)
    assert g0_anchor.total == pytest.approx(eq.total_physical)
    assert g0_anchor.alpha_state == pytest.approx(eq.alpha_state)
    # Effective state price = multiplier x dimension price.
    assert g0_anchor.effective_prices["state"] == pytest.approx(
        5.69 * eq.prices_wei["regular_state"]
    )

    # Unit ratios on the new anchor reproduce the G0 quantities: the next
    # link starts exactly where this one ended.
    from demand import demand_at_price_ratios

    quantities = demand_at_price_ratios(
        g0_anchor, params, {"execution": 1.0, "data": 1.0, "state": 1.0}
    )
    for name in ("execution", "data", "state"):
        assert quantities[name] == pytest.approx(eq.quantities[name])


def test_g0_share_modes_flip_state_growth_direction():
    """At the G0 equilibrium the two share modes disagree in sign on physical
    state creation: own-price mode grows it (the fee collapse dominates the
    5.69x repricing), relative mode shrinks it (state got pricier vs rest).
    Reported as the headline share-model uncertainty."""

    anchor = panel_anchor()
    world = g0_world()

    own = solve_equilibrium(
        anchor, DemandParams(eps_agg=0.175, eta_state=0.43), world
    )
    rel = solve_equilibrium(
        anchor,
        DemandParams(
            eps_agg=0.175, eta_state=0.43, share_mode="relative_state_vs_rest"
        ),
        world,
    )

    assert own.converged and rel.converged
    own_state_x = own.quantities["state"] / anchor.quantities["state"]
    rel_state_x = rel.quantities["state"] / anchor.quantities["state"]
    assert own_state_x > 1.0
    assert rel_state_x < 1.0
    # Both still clear the market at the target.
    assert own.metered_usage["regular_state"] == pytest.approx(50_000_000, rel=1e-6)
    assert rel.metered_usage["regular_state"] == pytest.approx(50_000_000, rel=1e-6)


def test_world_spec_requires_full_coverage():
    with pytest.raises(ValueError):
        WorldSpec(
            name="bad",
            multipliers={"execution": 1.0, "data": 1.0, "state": 1.0},
            dimensions=(
                FeeDimension(name="only_exec", groups=(("execution",),), target_gas=1.0),
            ),
        )
