import math

import pytest

from dynamics import (
    BundlePriced7999Demand,
    ElasticityMatrixDemand,
    IndependentIsoelasticDemand,
)


ANCHOR = {"execution": 100.0, "data": 50.0, "state": 25.0}
REFERENCE_FEES = {"execution": 10.0, "data": 20.0, "state": 40.0}
ELASTICITIES = {"execution": 0.1, "data": 0.2, "state": 0.5}


def test_independent_isoelastic_returns_anchor_at_reference_fees():
    demand = IndependentIsoelasticDemand(
        anchor_metered_gas=ANCHOR,
        reference_base_fees_wei=REFERENCE_FEES,
        elasticities=ELASTICITIES,
    )

    assert demand.quantities(REFERENCE_FEES) == ANCHOR


def test_independent_isoelastic_responds_only_to_own_fee():
    demand = IndependentIsoelasticDemand(
        anchor_metered_gas=ANCHOR,
        reference_base_fees_wei=REFERENCE_FEES,
        elasticities=ELASTICITIES,
    )
    fees = dict(REFERENCE_FEES)
    fees["data"] *= 4

    quantities = demand.quantities(fees)

    assert quantities["execution"] == ANCHOR["execution"]
    assert quantities["state"] == ANCHOR["state"]
    assert quantities["data"] == pytest.approx(50.0 * 4**-0.2)


def test_diagonal_matrix_matches_independent_model():
    independent = IndependentIsoelasticDemand(
        anchor_metered_gas=ANCHOR,
        reference_base_fees_wei=REFERENCE_FEES,
        elasticities=ELASTICITIES,
    )
    matrix = ElasticityMatrixDemand.from_independent(
        anchor_metered_gas=ANCHOR,
        reference_base_fees_wei=REFERENCE_FEES,
        elasticities=ELASTICITIES,
    )
    fees = {"execution": 25.0, "data": 8.0, "state": 100.0}

    assert matrix.quantities(fees) == pytest.approx(independent.quantities(fees))


def test_negative_cross_price_entry_represents_bundle_complementarity():
    matrix = {resource: {price: 0.0 for price in ANCHOR} for resource in ANCHOR}
    for resource, elasticity in ELASTICITIES.items():
        matrix[resource][resource] = -elasticity
    matrix["data"]["execution"] = -0.3
    demand = ElasticityMatrixDemand(
        anchor_metered_gas=ANCHOR,
        reference_base_fees_wei=REFERENCE_FEES,
        matrix=matrix,
    )
    fees = dict(REFERENCE_FEES)
    fees["execution"] *= 2

    quantities = demand.quantities(fees)

    assert quantities["data"] == pytest.approx(50.0 * 2**-0.3)
    assert quantities["data"] < ANCHOR["data"]


def test_demand_rejects_nonpositive_fee():
    demand = IndependentIsoelasticDemand(
        anchor_metered_gas=ANCHOR,
        reference_base_fees_wei=REFERENCE_FEES,
        elasticities=ELASTICITIES,
    )
    fees = dict(REFERENCE_FEES)
    fees["state"] = 0

    with pytest.raises(ValueError, match="positive"):
        demand.quantities(fees)


def bundle_demand(*, rho_A=1.0):
    return BundlePriced7999Demand(
        execution_quantity_anchor=100.0,
        state_quantity_anchor=25.0,
        static_data_gas_anchor=50.0,
        historical_price_wei=100.0,
        metering_multipliers={"execution": 2.0, "data": 10.0, "state": 4.0},
        elasticities={"execution": 0.2, "data": 0.3, "state": 0.4},
        bal_intensities={"execution": 1.0, "state": 2.0},
        rho_A=rho_A,
    )


def test_bundle_priced_model_reproduces_anchor_components():
    evaluation = bundle_demand().evaluate_with_shocks(
        {"execution": 45.0, "data": 10.0, "state": 20.0}
    )

    assert evaluation.parent_prices_wei == pytest.approx(
        {"execution": 100.0, "state": 100.0}
    )
    assert evaluation.parent_quantities == pytest.approx(
        {"execution": 100.0, "state": 25.0}
    )
    assert evaluation.static_data_gas == pytest.approx(50.0)
    assert evaluation.execution_bal_gas == pytest.approx(100.0)
    assert evaluation.state_bal_gas == pytest.approx(50.0)
    assert evaluation.offered_gas == pytest.approx(
        {"execution": 200.0, "data": 200.0, "state": 100.0}
    )


def test_bundle_shocks_move_parents_and_static_data_without_independent_bal_shock():
    model = bundle_demand()
    fees = {"execution": 45.0, "data": 10.0, "state": 20.0}
    data_shock = model.evaluate_with_shocks(
        fees, {"execution": 1.0, "data": 2.0, "state": 1.0}
    )
    execution_shock = model.evaluate_with_shocks(
        fees, {"execution": 2.0, "data": 1.0, "state": 1.0}
    )
    state_shock = model.evaluate_with_shocks(
        fees, {"execution": 1.0, "data": 1.0, "state": 2.0}
    )

    assert data_shock.static_data_gas == pytest.approx(100.0)
    assert data_shock.total_bal_gas == pytest.approx(150.0)
    assert execution_shock.parent_quantities["execution"] == pytest.approx(200.0)
    assert execution_shock.execution_bal_gas == pytest.approx(200.0)
    assert state_shock.parent_quantities["state"] == pytest.approx(50.0)
    assert state_shock.state_bal_gas == pytest.approx(100.0)


def test_bundle_execution_implicit_equation_holds_away_from_rho_one():
    model = bundle_demand(rho_A=1.25)
    fees = {"execution": 30.0, "data": 25.0, "state": 20.0}
    shock = {"execution": 1.4, "data": 1.0, "state": 1.0}
    evaluation = model.evaluate_with_shocks(fees, shock)
    ratio = evaluation.parent_quantities["execution"] / 100.0
    right_hand_side = (
        shock["execution"]
        * ((2.0 * fees["execution"] + ratio ** (1.25 - 1.0) * fees["data"]) / 100.0)
        ** -0.2
    )

    assert math.log(ratio / right_hand_side) == pytest.approx(0.0, abs=1e-12)


def test_higher_data_fee_reduces_both_bal_generating_parent_quantities():
    model = bundle_demand()
    lower = model.evaluate_with_shocks({"execution": 45.0, "data": 10.0, "state": 20.0})
    higher = model.evaluate_with_shocks(
        {"execution": 45.0, "data": 20.0, "state": 20.0}
    )

    assert higher.parent_quantities["execution"] < lower.parent_quantities["execution"]
    assert higher.parent_quantities["state"] < lower.parent_quantities["state"]
    assert higher.total_bal_gas < lower.total_bal_gas
