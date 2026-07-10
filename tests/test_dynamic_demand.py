import pytest

from dynamics import ElasticityMatrixDemand, IndependentIsoelasticDemand


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
    assert quantities["data"] == pytest.approx(50.0 * 4 ** -0.2)


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
    matrix = {
        resource: {price: 0.0 for price in ANCHOR}
        for resource in ANCHOR
    }
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

    assert quantities["data"] == pytest.approx(50.0 * 2 ** -0.3)
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
