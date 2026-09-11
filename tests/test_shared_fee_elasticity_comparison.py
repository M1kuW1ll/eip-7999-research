"""Regression checks for the committed compact matched-window experiment."""
from pathlib import Path
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/shared_fee"


def test_execution_gain_figure_pairs_workload_replications():
    import runpy
    import pytest

    summarize = runpy.run_path(str(ROOT / "scripts/shared_fee/make_figures.py"))[
        "paired_execution_gain_summary"
    ]
    paths = pd.read_csv(OUT / "shared_fee_elasticity_comparison_paths.csv")
    actual = summarize(paths).set_index(["benchmark", "propagation_time_s"]).sort_index()
    shuffled = summarize(paths.sample(frac=1, random_state=9)).set_index(
        ["benchmark", "propagation_time_s"]
    ).sort_index()
    pd.testing.assert_frame_equal(actual, shuffled, rtol=1e-12)
    assert len(actual) == 10

    central = paths[paths.window_days.eq(35)]
    for (benchmark, propagation), row in actual.iterrows():
        selected = central[
            central.benchmark.eq(benchmark) & central.propagation_time_s.eq(propagation)
        ].set_index("replication").metered_execution_gas.sort_index()
        reference = central[
            central.benchmark.eq("fully_optimized") & central.propagation_time_s.eq(propagation)
        ].set_index("replication").metered_execution_gas.sort_index()
        gain = selected - reference
        np.testing.assert_allclose(row[["mean", "p05", "p95"]],
                                   [gain.mean(), gain.quantile(.05), gain.quantile(.95)])

    missing = paths.drop(central[central.benchmark.eq("fully_optimized")].index[0])
    with pytest.raises(ValueError, match="matching 7999 and shared-fee paths"):
        summarize(missing)


def test_paired_dot_gaps_use_eip8372_reference_and_no_error_bars(monkeypatch):
    import runpy
    import matplotlib.pyplot as plt

    render = runpy.run_path(str(ROOT / "scripts/shared_fee/make_figures.py"))["paired_dot_comparison"]
    saved = []
    monkeypatch.setitem(render.__globals__, "save", lambda fig, name: saved.append((fig, name)))
    render()
    fig, _ = saved[0]
    try:
        ax = fig.axes[0]
        assert len(ax.containers) == 0
        assert len(fig.legends) == 2
        source = pd.concat([pd.read_csv(OUT / "shared_fee_elasticity_comparison.csv"),
                            pd.read_csv(OUT / "eip8372/normalized_outcomes.csv")])
        central = source[source.window_days.eq(35)]
        values = central.pivot(index="propagation_time_s", columns="benchmark", values="metered_execution_gas")
        expected = pd.concat([values.balanced - values.normalized_state,
                              values.maximum - values.balanced]) / 1e6
        labels = [text.get_text() for text in ax.texts if text.get_text().startswith("+")]
        assert labels == [f"+{value:.1f}" for value in expected]
    finally:
        plt.close(fig)


def test_window_comparison_keeps_all_design_slots_and_missing_candidates():
    frame = pd.read_csv(OUT / "shared_fee_elasticity_comparison.csv")
    assert len(frame) == 80
    assert not frame.duplicated(["window_days", "propagation_time_s", "benchmark"]).any()
    assert set(frame.window_days) == {21, 35, 60, 75}
    missing = frame[~frame.available]
    assert len(missing) == 9
    assert set(missing.benchmark) == {"balanced"}
    assert missing.metered_execution_gas.isna().all()
    assert set(frame.n_replications) == {32}
    assert set(frame.measured_blocks) == {50_400}
    assert set(frame.burn_in_blocks) == {7_200}


def test_shared_capacity_and_multipliers_stay_fixed_across_windows():
    frame = pd.read_csv(OUT / "shared_fee_elasticity_comparison.csv")
    shared = frame[frame.benchmark.isin(["proposal_faithful", "fully_optimized"])]
    for _, group in shared.groupby(["benchmark", "propagation_time_s"]):
        assert len(group) == 4
        for column in ("shared_limit", "shared_target", "floor_rate", "cpsb",
                       "m_execution", "m_data", "m_state"):
            assert group[column].nunique() == 1
    assert set(shared.equilibrium_binding_branch) == {"state"}
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    np.testing.assert_allclose(frame.m_execution, demand.m_execution, rtol=0, atol=1e-12)


def test_each_window_uses_matching_eip7999_candidates_and_effective_prices():
    frame = pd.read_csv(OUT / "shared_fee_elasticity_comparison.csv")
    for benchmark, filename in (("maximum", "slot_time_parameter_maximum.csv"),
                                 ("balanced", "slot_time_parameter_balanced.csv")):
        source = pd.read_csv(ROOT / "data/7999" / filename)
        source = source[source.lambda_bal.eq(0) & source.rho_A.eq(1)]
        actual = frame[(frame.benchmark == benchmark) & frame.available]
        joined = actual.merge(source, on=["window_days", "propagation_time_s"],
                              suffixes=("_new", "_old"), validate="one_to_one")
        assert len(joined) == len(actual)
        for name in ("execution_target", "data_target"):
            np.testing.assert_array_equal(joined[name + "_new"], joined[name + "_old"])
        np.testing.assert_allclose(joined.metered_execution_gas, joined.included_execution,
                                   rtol=1e-12)
        for resource in ("execution", "data", "state"):
            np.testing.assert_allclose(joined[resource + "_price_variation"],
                                       joined[resource + "_price_sd"], rtol=1e-12)


def test_reported_means_and_path_ranges_reproduce_from_replications():
    frame = pd.read_csv(OUT / "shared_fee_elasticity_comparison.csv")
    paths = pd.read_csv(OUT / "shared_fee_elasticity_comparison_paths.csv")
    assert len(paths) == 71 * 32
    keys = ["window_days", "propagation_time_s", "benchmark"]
    available = frame[frame.available].set_index(keys)
    for key, group in paths.groupby(keys):
        assert set(group.replication) == set(range(32))
        summary = available.loc[key]
        for metric in ("metered_execution_gas", "annualized_state_growth_gib", "hard_limit_fraction"):
            np.testing.assert_allclose(summary[metric], group[metric].mean(), rtol=1e-12)
            np.testing.assert_allclose(summary[metric + "_p05"], group[metric].quantile(.05), rtol=1e-12)
            np.testing.assert_allclose(summary[metric + "_p95"], group[metric].quantile(.95), rtol=1e-12)


def test_workload_hash_matches_preserved_central_experiment():
    manifest = json.loads((OUT / "shared_fee_elasticity_comparison_manifest.json").read_text())
    expected = pd.read_csv(OUT / "shared_fee_factorial_manifest.csv").iloc[0]
    assert manifest["workload_sha256"] == expected.workload_sha256
    assert manifest["shape"] == [32, 57_600, 4]
    assert manifest["shared_specifications"] == 40
    assert manifest["eip7999_selections_available"] == 31
