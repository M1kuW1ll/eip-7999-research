import pandas as pd
import pytest

from demand import (
    Anchor,
    CrossElasticityDemand,
    DemandParams,
    FeeDimension,
    WorldSpec,
    combine_matrices,
    coupling_exposures_from_transactions,
    coupling_matrix,
    implied_anchor_elasticities,
    implied_own_price_elasticities,
    share_model_jacobian,
    solve_equilibrium,
)

P_REF = 0.33e9


def panel_anchor() -> Anchor:
    return Anchor.from_single_price(
        total_gas=30_400_000,
        base_fee_wei=P_REF,
        shares={"execution": 0.797, "data": 0.034, "state": 0.169},
    )


def test_jacobian_rows_sum_to_uniform_elasticities():
    anchor = panel_anchor()
    params = DemandParams(eps_agg=0.175, eta_state=0.43)
    jacobian = share_model_jacobian(anchor, params)
    implied = implied_anchor_elasticities(anchor, params)

    state_row_sum = sum(jacobian["state"].values())
    rest_rows = [
        sum(jacobian[name].values()) for name in ("execution", "data")
    ]
    assert -state_row_sum == pytest.approx(implied["state"], rel=1e-3)
    for row_sum in rest_rows:
        assert -row_sum == pytest.approx(implied["rest"], rel=1e-3)


def test_matrix_demand_reproduces_anchor_and_share_model_nearby():
    anchor = panel_anchor()
    params = DemandParams(eps_agg=0.175, eta_state=0.43)
    model = CrossElasticityDemand(
        anchor=anchor, matrix=share_model_jacobian(anchor, params)
    )

    at_anchor = model.quantities({name: 1.0 for name in ("execution", "data", "state")})
    for name in ("execution", "data", "state"):
        assert at_anchor[name] == pytest.approx(anchor.quantities[name], rel=1e-9)

    # Consistency near the anchor: a world with a mild target change solves
    # to nearly the same equilibrium under both demand representations.
    world = WorldSpec(
        name="mild",
        multipliers={"execution": 1.0, "data": 1.0, "state": 1.0},
        dimensions=(
            FeeDimension(
                name="all",
                groups=(("execution", "data", "state"),),
                target_gas=0.9 * anchor.total,
            ),
        ),
    )
    share_eq = solve_equilibrium(anchor, params, world)
    matrix_eq = solve_equilibrium(
        anchor, params, world, demand_fn=model.quantities
    )
    # The matrix freezes elasticities the share model lets drift with the
    # mix, so agreement is approximate away from the anchor: ~3% on the
    # price after a ~1.9x price move, ~1% on quantities.
    assert share_eq.prices_wei["all"] == pytest.approx(
        matrix_eq.prices_wei["all"], rel=0.05
    )
    for name in ("execution", "data", "state"):
        assert share_eq.quantities[name] == pytest.approx(
            matrix_eq.quantities[name], rel=0.02
        )


def test_coupling_exposures_from_transactions():
    frame = pd.DataFrame(
        [
            # Pure execution tx.
            {"exec": 100.0, "data": 0.0, "state": 0.0},
            # State-heavy tx that carries execution and data with it.
            {"exec": 50.0, "data": 10.0, "state": 40.0},
        ]
    )
    exposures = coupling_exposures_from_transactions(
        frame, execution_col="exec", data_col="data", state_col="state"
    )
    # Fraction of execution riding with state intensity: only the second tx
    # has state (share 0.4), and it carries 50 of 150 execution units.
    assert exposures["execution"]["state"] == pytest.approx(50 * 0.4 / 150)
    # All data lives in the state-carrying tx.
    assert exposures["data"]["state"] == pytest.approx(0.4)
    # State's own diagonal exposure is its within-tx share.
    assert exposures["state"]["state"] == pytest.approx(0.4)


def test_coupling_makes_state_price_drag_execution_down():
    anchor = panel_anchor()
    params = DemandParams(eps_agg=0.175, eta_state=0.43)
    jacobian = share_model_jacobian(anchor, params)
    own = implied_own_price_elasticities(jacobian)

    exposures = {
        i: {j: 0.0 for j in ("execution", "data", "state")}
        for i in ("execution", "data", "state")
    }
    exposures["execution"]["state"] = 0.5  # half of execution rides in state txs
    gamma = coupling_matrix(exposures, own)
    assert gamma["execution"]["state"] == pytest.approx(-0.5 * own["state"])

    coupled = CrossElasticityDemand(
        anchor=anchor, matrix=combine_matrices(jacobian, gamma)
    )
    uncoupled = CrossElasticityDemand(anchor=anchor, matrix=jacobian)

    ratios = {"execution": 1.0, "data": 1.0, "state": 2.0}  # state-only rise
    with_coupling = coupled.quantities(ratios)
    without = uncoupled.quantities(ratios)
    # Substitution alone raises execution when state gets pricier; the
    # bundle coupling pulls it back down.
    assert with_coupling["execution"] < without["execution"]


def test_matrix_validation():
    anchor = panel_anchor()
    with pytest.raises(ValueError):
        CrossElasticityDemand(anchor=anchor, matrix={"execution": {}})
