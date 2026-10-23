"""Only the near-limit tolerance changes in the 25% conservative rule."""
from pathlib import Path
import runpy

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_near_limit_tolerance_does_not_relax_other_conditions():
    module = runpy.run_path(str(ROOT / "scripts/run_slot_time_parameter_sensitivity.py"))
    assert module["HISTORICAL_NEAR_LIMIT_TOLERANCE_MULTIPLIER"] == 1.25
    assert module["HISTORICAL_TARGET_DEVIATION_TOLERANCE_MULTIPLIER"] == 1.20
    source = pd.read_csv(ROOT / "data/7999/slot_time_parameter_surface_one_at_a_time.csv")
    historical = pd.read_csv(ROOT / "data/7999/historical_fee_market_benchmark.csv").iloc[0]
    base = source[source.is_central & source.propagation_time_s.eq(3)].iloc[0]
    cases = pd.DataFrame([base.copy() for _ in range(4)])
    cases["included_execution"] = [200e6, 300e6, 400e6, 500e6]
    cases["any_near_limit_fraction"] = historical.near_limit_fraction * np.array([1.25, 1.251, 1.24, 1.24])
    cases["execution_mean_absolute_target_deviation"] = historical.mean_absolute_target_deviation * np.array([1.20, 1.20, 1.201, 1.20])
    cases["unconstrained_equilibrium_execution_base_fee_wei"] = [2., 2., 2., 1.]
    cases = cases.reset_index(drop=True)
    _, selected = module["selection_tables"](cases)
    assert len(selected) == 1
    assert selected.iloc[0].included_execution == 200e6


def test_central_conservative_candidates_under_25_percent_near_limit_tolerance():
    select = runpy.run_path(str(ROOT / "scripts/run_slot_time_parameter_sensitivity.py"))["selection_tables"]
    source = pd.read_csv(ROOT / "data/7999/slot_time_parameter_surface_one_at_a_time.csv")
    _, selected = select(source[source.is_central])
    selected = selected.sort_values("propagation_time_s")
    np.testing.assert_array_equal(selected.execution_target / 1e6, [200, 225, 225, 225, 200])
    np.testing.assert_array_equal(selected.data_target / 1e6, [45, 52.5, 60, 60, 67.5])
    np.testing.assert_allclose(selected.iloc[0].included_execution / 1e6, 198.0927, atol=0.0001)
