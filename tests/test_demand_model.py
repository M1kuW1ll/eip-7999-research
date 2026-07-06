import math

import pytest

from demand import (
    Anchor,
    DemandParams,
    demand_at_price_ratios,
    implied_anchor_elasticities,
)

P_REF = 0.33e9  # ~0.33 gwei in wei


def panel_anchor() -> Anchor:
    return Anchor.from_single_price(
        total_gas=30_400_000,
        base_fee_wei=P_REF,
        shares={"execution": 0.797, "data": 0.034, "state": 0.169},
    )


def maria_params() -> DemandParams:
    return DemandParams(eps_agg=0.175, eta_state=0.43)


def test_unit_ratios_reproduce_anchor_exactly():
    anchor = panel_anchor()
    quantities = demand_at_price_ratios(
        anchor,
        maria_params(),
        {"execution": 1.0, "data": 1.0, "state": 1.0},
    )
    for name in ("execution", "data", "state"):
        assert quantities[name] == pytest.approx(anchor.quantities[name])


def test_uniform_price_rise_moves_total_with_eps_agg():
    anchor = panel_anchor()
    params = maria_params()
    ratio = 2.0
    quantities = demand_at_price_ratios(
        anchor, params, {name: ratio for name in ("execution", "data", "state")}
    )
    total = sum(quantities.values())
    assert total == pytest.approx(anchor.total * ratio ** (-params.eps_agg))


def test_implied_elasticities_match_maria_recovered_values():
    anchor = panel_anchor()
    implied = implied_anchor_elasticities(anchor, maria_params())
    # Maria's central scenario: state ~0.51, burst/rest ~0.08.
    assert implied["state"] == pytest.approx(0.53, abs=0.03)
    assert implied["rest"] == pytest.approx(0.10, abs=0.03)


def test_implied_elasticities_match_numeric_derivative():
    anchor = panel_anchor()
    params = maria_params()
    implied = implied_anchor_elasticities(anchor, params)

    bump = 1e-6
    base = demand_at_price_ratios(anchor, params, dict.fromkeys(
        ("execution", "data", "state"), 1.0))
    bumped = demand_at_price_ratios(anchor, params, dict.fromkeys(
        ("execution", "data", "state"), 1.0 + bump))

    numeric_state = -(
        math.log(bumped["state"]) - math.log(base["state"])
    ) / math.log(1.0 + bump)
    rest_base = base["execution"] + base["data"]
    rest_bumped = bumped["execution"] + bumped["data"]
    numeric_rest = -(math.log(rest_bumped) - math.log(rest_base)) / math.log(
        1.0 + bump
    )

    assert numeric_state == pytest.approx(implied["state"], rel=1e-3)
    assert numeric_rest == pytest.approx(implied["rest"], rel=1e-3)


def test_state_repricing_shrinks_state_share_with_eta():
    anchor = panel_anchor()
    params = maria_params()
    quantities = demand_at_price_ratios(
        anchor, params, {"execution": 1.0, "data": 1.0, "state": 5.7}
    )
    total = sum(quantities.values())
    assert quantities["state"] / total < anchor.alpha_state

    fixed = demand_at_price_ratios(
        anchor,
        DemandParams(eps_agg=0.175, eta_state=0.0),
        {"execution": 1.0, "data": 1.0, "state": 5.7},
    )
    fixed_total = sum(fixed.values())
    assert fixed["state"] / fixed_total == pytest.approx(anchor.alpha_state)


def test_eta_data_zero_keeps_within_rest_split():
    anchor = panel_anchor()
    params = maria_params()
    quantities = demand_at_price_ratios(
        anchor, params, {"execution": 1.0, "data": 3.0, "state": 1.0}
    )
    rest = quantities["execution"] + quantities["data"]
    assert quantities["data"] / rest == pytest.approx(anchor.data_share_of_rest)

    substituted = demand_at_price_ratios(
        anchor,
        DemandParams(eps_agg=0.175, eta_state=0.43, eta_data=0.5),
        {"execution": 1.0, "data": 3.0, "state": 1.0},
    )
    sub_rest = substituted["execution"] + substituted["data"]
    assert substituted["data"] / sub_rest < anchor.data_share_of_rest


def test_anchor_validation():
    with pytest.raises(ValueError):
        Anchor.from_single_price(
            total_gas=30_000_000,
            base_fee_wei=P_REF,
            shares={"execution": 0.9, "data": 0.2, "state": 0.1},
        )


def relative_params(**kwargs) -> DemandParams:
    return DemandParams(
        eps_agg=kwargs.pop("eps_agg", 0.175),
        eta_state=kwargs.pop("eta_state", 0.43),
        share_mode="relative_state_vs_rest",
        **kwargs,
    )


def test_relative_mode_uniform_move_keeps_shares_fixed():
    anchor = panel_anchor()
    params = relative_params()
    ratio = 0.1  # uniform 10x price fall
    quantities = demand_at_price_ratios(
        anchor, params, {name: ratio for name in ("execution", "data", "state")}
    )
    total = sum(quantities.values())
    # Shares unchanged, total moves with eps_agg exactly.
    assert quantities["state"] / total == pytest.approx(anchor.alpha_state)
    assert total == pytest.approx(anchor.total * ratio ** (-params.eps_agg))


def test_relative_mode_implied_elasticities_are_flat():
    anchor = panel_anchor()
    implied = implied_anchor_elasticities(anchor, relative_params())
    assert implied["state"] == pytest.approx(0.175)
    assert implied["rest"] == pytest.approx(0.175)


def test_share_modes_disagree_in_sign_under_glamsterdam_ratios():
    """The G0 configuration: state's absolute effective price falls (~0.52)
    while its relative price vs rest rises (~5.4x). Own-price mode grows the
    state share; relative mode shrinks it. This divergence is the headline
    share-model uncertainty."""

    anchor = panel_anchor()
    ratios = {"execution": 0.092, "data": 0.092 * 2.13, "state": 0.092 * 5.69}

    own = demand_at_price_ratios(
        anchor, DemandParams(eps_agg=0.175, eta_state=0.43), ratios
    )
    rel = demand_at_price_ratios(anchor, relative_params(), ratios)

    own_share = own["state"] / sum(own.values())
    rel_share = rel["state"] / sum(rel.values())
    assert own_share > anchor.alpha_state
    assert rel_share < anchor.alpha_state


def test_relative_mode_state_only_bump_matches_derivative():
    anchor = panel_anchor()
    params = relative_params()
    bump = 1e-6
    base = demand_at_price_ratios(
        anchor, params, {"execution": 1.0, "data": 1.0, "state": 1.0}
    )
    bumped = demand_at_price_ratios(
        anchor, params, {"execution": 1.0, "data": 1.0, "state": 1.0 + bump}
    )
    numeric = -(
        math.log(bumped["state"]) - math.log(base["state"])
    ) / math.log(1.0 + bump)
    # State-only move: aggregate channel (eps * state spend weight) plus the
    # substitution channel (eta * (1 - alpha)).
    expected = (
        params.eps_agg * anchor.spend_shares["state"]
        + params.eta_state * (1.0 - anchor.alpha_state)
    )
    assert numeric == pytest.approx(expected, rel=1e-3)


def test_invalid_share_mode_raises():
    with pytest.raises(ValueError):
        DemandParams(eps_agg=0.175, eta_state=0.43, share_mode="nonsense")
