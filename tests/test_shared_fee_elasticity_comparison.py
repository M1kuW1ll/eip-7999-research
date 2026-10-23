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


def test_paired_dot_connectors_keep_reference_without_gain_labels_or_error_bars(monkeypatch):
    import runpy
    import matplotlib.pyplot as plt

    render = runpy.run_path(str(ROOT / "scripts/shared_fee/make_figures.py"))["paired_dot_comparison"]
    saved = []
    monkeypatch.setitem(render.__globals__, "save", lambda fig, name, **kwargs: saved.append((fig, name)))
    render()
    fig, _ = saved[0]
    try:
        ax = fig.axes[0]
        assert len(ax.containers) == 0
        assert len(fig.legends) == 1
        source = pd.concat([pd.read_csv(OUT / "shared_fee_elasticity_comparison.csv"),
                            pd.read_csv(OUT / "eip8372/normalized_outcomes.csv")])
        central = source[source.window_days.eq(35)]
        values = central.pivot(index="propagation_time_s", columns="benchmark", values="metered_execution_gas")
        assert len(ax.collections) == 2
        for collection, start, end in zip(
            ax.collections, ("normalized_state", "balanced"),
            ("balanced", "maximum"), strict=True
        ):
            expected = np.array([
                [[left / 1e6, row], [right / 1e6, row]]
                for row, (left, right) in enumerate(zip(values[start], values[end], strict=True))
            ])
            np.testing.assert_allclose(collection.get_segments(), expected)
        labels = [text.get_text() for text in ax.texts if text.get_text().startswith("+")]
        assert labels == []
        assert len(ax.texts) == 30
        assert ax.get_xlabel() == "Mean execution gas usage per block (M)"
        assert ax.get_ylabel() == "Propagation time (s)"
    finally:
        plt.close(fig)


def test_focused_paired_dot_preserves_four_series_and_uses_separate_output(monkeypatch):
    import runpy
    import matplotlib.pyplot as plt

    render = runpy.run_path(str(ROOT / "scripts/shared_fee/make_figures.py"))["paired_dot_comparison"]
    saved = []
    monkeypatch.setitem(render.__globals__, "save", lambda fig, name, **kwargs: saved.append((fig, name)))
    render()
    render(include_reference_benchmarks=False)
    full, full_name = saved[0]
    focused, focused_name = saved[1]
    try:
        assert full_name == "shared_fee_comparison_execution_paired_dot.png"
        assert focused_name == "shared_fee_comparison_execution_paired_dot_8372_7999.png"
        ax = focused.axes[0]
        assert len(ax.lines) == 4
        assert len(ax.texts) == 20
        assert not any(text.get_text().startswith("+") for text in ax.texts)
        assert len(ax.containers) == 0
        focused_labels = (
            "One-dimensional normalized, 1/2 ratio",
            "One-dimensional normalized, 4/5 ratio",
            "Multi-dimensional, max throughput",
            "Multi-dimensional, conservative",
        )
        for original, retained, label in zip(full.axes[0].lines[2:], ax.lines,
                                             focused_labels, strict=True):
            np.testing.assert_array_equal(original.get_xydata(), retained.get_xydata())
            assert retained.get_label() == label
            assert original.get_color() == retained.get_color()
            assert original.get_marker() == retained.get_marker()
        legend = [text.get_text() for text in focused.legends[0].get_texts()]
        assert len(legend) == 4
        assert not any("Baseline" in label or "8368" in label for label in legend)
        assert ax.get_xlim() == (140, 285)
    finally:
        plt.close(full)
        plt.close(focused)


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
