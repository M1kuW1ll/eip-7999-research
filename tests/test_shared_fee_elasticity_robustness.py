"""Checks for full-vector selection, paired gains, and frozen central designs."""
from pathlib import Path
import json
import runpy

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/shared_fee"
KEYS = ["window_days", "benchmark", "propagation_time_s", "shared_limit"]


def test_full_sweep_preserves_physical_parameters_and_uses_complete_vectors():
    surface = pd.read_csv(OUT / "shared_fee_elasticity_surface.csv")
    assert len(surface) == 708 and not surface.duplicated(KEYS).any()
    specs = runpy.run_path(str(ROOT / "scripts/run_slot_time_parameter_sensitivity.py"))["specification_table"]()
    specs = specs[specs.lambda_bal.eq(0) & specs.rho_A.eq(1)].set_index("window_days")
    for window, group in surface.groupby("window_days"):
        assert len(group) == 177
        for resource in ("execution", "data", "state"):
            np.testing.assert_allclose(group[f"eps_{resource}"], specs.loc[window, f"eps_{resource}"], rtol=1e-12)
    for _, group in surface.groupby(KEYS[1:]):
        assert len(group) == 4
        for field in ("shared_limit", "shared_target", "floor_rate", "cpsb", "m_execution", "m_data", "m_state"):
            assert group[field].nunique() == 1
    assert surface.workload_sha256.nunique() == 1
    for resource in ("data", "state"):
        np.testing.assert_array_equal(surface[f"{resource}_price_variation"], surface.execution_price_variation)
        np.testing.assert_array_equal(surface[f"equilibrium_{resource}_fee_wei"], surface.equilibrium_execution_fee_wei)


def test_all_surface_means_reproduce_from_32_paths():
    surface = pd.read_csv(OUT / "shared_fee_elasticity_surface.csv").set_index(KEYS).sort_index()
    paths = pd.read_csv(OUT / "shared_fee_elasticity_surface_paths.csv")
    assert len(paths) == 22_656
    assert paths.groupby(KEYS).replication.nunique().eq(32).all()
    assert not paths.duplicated(KEYS + ["replication"]).any()
    for metric in ("metered_execution_gas", "annualized_state_growth_gib", "hard_limit_fraction", "execution_price_variation"):
        actual = paths.groupby(KEYS)[metric].mean().sort_index()
        np.testing.assert_allclose(actual, surface[metric], rtol=1e-12)


def test_selection_maximizes_mean_execution_and_retains_missing_candidates():
    surface = pd.read_csv(OUT / "shared_fee_elasticity_surface.csv")
    selected = pd.read_csv(OUT / "shared_fee_elasticity_reselected.csv")
    assert len(selected) == 80 and (~selected.available).sum() == 9
    assert selected.loc[~selected.available, "metered_execution_gas"].isna().all()
    shared = selected[selected.benchmark.isin(["fully_optimized", "proposal_faithful"])]
    keys = KEYS[:3]
    expected = surface.groupby(keys).metered_execution_gas.max().sort_index()
    np.testing.assert_allclose(shared.set_index(keys).sort_index().metered_execution_gas, expected, rtol=1e-12)
    best = pd.read_csv(OUT / "shared_fee_elasticity_best_designs.csv")
    assert len(best) == 16 and (~best.available).sum() == 1
    expected = selected[selected.available].groupby(keys[:2]).metered_execution_gas.max().sort_index()
    np.testing.assert_allclose(best[best.available].set_index(keys[:2]).sort_index().metered_execution_gas, expected)

    select = runpy.run_path(str(ROOT / "scripts/shared_fee/run_elasticity_robustness.py"))["select_throughput"]
    synthetic = pd.DataFrame({"group": [1, 1], "available": [True, True], "configuration": ["G100", "G200"],
                              "shared_limit": [100, 200], "metered_execution_gas": [90, 80]})
    assert select(synthetic, ["group"]).iloc[0].configuration == "G100"


def test_gains_use_matched_paths_and_distinguish_week_spread_from_mean_uncertainty():
    selected = pd.read_csv(OUT / "shared_fee_elasticity_reselected.csv")
    paths = pd.read_csv(OUT / "shared_fee_elasticity_gain_paths.csv")
    gains = pd.read_csv(OUT / "shared_fee_elasticity_gains.csv")
    shared = pd.read_csv(OUT / "shared_fee_elasticity_surface_paths.csv")
    eip = pd.read_csv(OUT / "shared_fee_elasticity_comparison_paths.csv")
    assert len(gains) == 40 and len(paths) == 31 * 32
    for _, row in gains.iterrows():
        if not row.available:
            assert pd.isna(row.mean_gain)
            continue
        key = paths.window_days.eq(row.window_days) & paths.propagation_time_s.eq(row.propagation_time_s) & paths.benchmark.eq(row.benchmark)
        actual = paths[key].set_index("replication").gain.sort_index()
        reference = selected[selected.window_days.eq(row.window_days)
            & selected.propagation_time_s.eq(row.propagation_time_s) & selected.benchmark.eq("fully_optimized")].iloc[0]
        a = shared[shared.window_days.eq(row.window_days) & shared.propagation_time_s.eq(row.propagation_time_s)
            & shared.benchmark.eq("fully_optimized") & shared.shared_limit.eq(reference.shared_limit)]
        b = eip[eip.window_days.eq(row.window_days) & eip.propagation_time_s.eq(row.propagation_time_s)
            & eip.benchmark.eq(row.benchmark)]
        expected = b.set_index("replication").metered_execution_gas - a.set_index("replication").metered_execution_gas
        np.testing.assert_allclose(actual, expected.sort_index(), rtol=1e-12)
        np.testing.assert_allclose([row.mean_gain, row.week_p05, row.week_p95],
                                   [actual.mean(), actual.quantile(.05), actual.quantile(.95)])
        assert row.mean_ci95_low < row.mean_gain < row.mean_ci95_high
        assert row.mean_ci95_high - row.mean_ci95_low < row.week_p95 - row.week_p05


def test_state_growth_figure_matches_all_three_families(monkeypatch):
    import matplotlib.pyplot as plt
    render = runpy.run_path(str(ROOT / "scripts/shared_fee/make_figures.py"))["elasticity_state_growth_figure"]
    figures = []
    monkeypatch.setitem(render.__globals__, "save", lambda fig, name: figures.append((fig, name)))
    render()
    selected = pd.read_csv(OUT / "shared_fee_elasticity_reselected.csv")
    normalized = pd.read_csv(OUT / "eip8372/normalized_outcomes.csv")
    try:
        fig, name = figures[0]
        assert name == "shared_fee_elasticity_state_growth.png" and len(fig.axes) == 3
        for ax, (source, family) in zip(fig.axes, [(selected, "proposal_faithful"),
                    (selected, "fully_optimized"), (normalized, "normalized_state")], strict=True):
            assert "GiB/year" in ax.get_ylabel()
            for line, window in zip(ax.lines[:4], (21, 35, 60, 75), strict=True):
                group = source[source.benchmark.eq(family) & source.window_days.eq(window)].sort_values("propagation_time_s")
                assert line.get_label() == f"{window}-day vector"
                np.testing.assert_array_equal(line.get_ydata(), group.annualized_state_growth_gib)
                np.testing.assert_array_equal(line.get_xdata(), group.propagation_time_s)
        assert fig.axes[1].get_ylim() == fig.axes[2].get_ylim()
    finally:
        for fig, _ in figures:
            plt.close(fig)


def test_equilibrium_fee_figure_uses_solved_roots_and_common_log_scale(monkeypatch):
    import matplotlib.pyplot as plt
    render = runpy.run_path(str(ROOT / "scripts/shared_fee/make_figures.py"))["elasticity_equilibrium_fee_figure"]
    figures = []
    monkeypatch.setitem(render.__globals__, "save", lambda fig, name: figures.append((fig, name)))
    render()
    selected = pd.read_csv(OUT / "shared_fee_elasticity_reselected.csv")
    normalized = pd.read_csv(OUT / "eip8372/normalized_outcomes.csv")
    try:
        fig, name = figures[0]
        assert name == "shared_fee_elasticity_equilibrium_fee.png" and len(fig.axes) == 3
        for ax, (source, family, metric) in zip(fig.axes,
                [(selected, "proposal_faithful", "equilibrium_execution_fee_wei"),
                 (selected, "fully_optimized", "equilibrium_execution_fee_wei"),
                 (normalized, "normalized_state", "equilibrium_fee_wei")], strict=True):
            assert ax.get_yscale() == "log" and ax.get_ylim() == (10, 2e6)
            for line, window in zip(ax.lines, (21, 35, 60, 75), strict=True):
                group = source[source.benchmark.eq(family) & source.window_days.eq(window)].sort_values("propagation_time_s")
                assert line.get_label() == f"{window}-day vector"
                np.testing.assert_array_equal(line.get_ydata(), group[metric])
    finally:
        for fig, _ in figures:
            plt.close(fig)


def test_frozen_candidates_keep_central_geometry_and_match_current_grid():
    fixed = pd.read_csv(OUT / "shared_fee_elasticity_fixed_central.csv")
    assert len(fixed) == 80
    for (_, _), group in fixed.groupby(["benchmark", "propagation_time_s"]):
        assert len(group) == 4 and group.configuration.nunique() == 1
        for field in ("execution_target", "data_target", "execution_limit", "data_limit", "shared_limit", "floor_rate", "cpsb"):
            assert group[field].nunique() <= 1
    grid = pd.read_csv(ROOT / "data/7999/slot_time_parameter_surface_one_at_a_time.csv")
    grid = grid[grid.lambda_bal.eq(0) & grid.rho_A.eq(1)]
    eip = fixed[fixed.benchmark.isin(["maximum", "balanced"])]
    keys = ["window_days", "propagation_time_s", "execution_target", "data_target", "execution_limit", "data_limit"]
    joined = eip.merge(grid, on=keys, validate="many_to_one")
    assert len(joined) == 40
    np.testing.assert_allclose(joined.metered_execution_gas, joined.included_execution, rtol=1e-12)


def test_new_figures_plot_complete_vectors_and_nan_for_unavailable(monkeypatch):
    import matplotlib.pyplot as plt
    render = runpy.run_path(str(ROOT / "scripts/shared_fee/make_figures.py"))["elasticity_robustness_figures"]
    figures = []
    monkeypatch.setitem(render.__globals__, "save", lambda fig, name: figures.append((fig, name)))
    render()
    try:
        assert [name for _, name in figures] == ["shared_fee_elasticity_performance.png", "shared_fee_elasticity_execution_gains.png"]
        assert len(figures[0][0].axes) == 3
        for ax in figures[0][0].axes:
            assert len(ax.lines) == 4
            assert [line.get_label() for line in ax.lines] == [f"{w}-day vector" for w in (21, 35, 60, 75)]
        normalized = pd.read_csv(OUT / "eip8372/normalized_outcomes.csv")
        for line, window in zip(figures[0][0].axes[2].lines, (21, 35, 60, 75), strict=True):
            group = normalized[normalized.window_days.eq(window)].sort_values("propagation_time_s")
            np.testing.assert_array_equal(line.get_ydata(), group.metered_execution_gas / 1e6)
        ax = figures[1][0].axes[0]
        assert np.isfinite(ax.lines[2].get_ydata()).sum() == 1
        assert np.isnan(ax.lines[3].get_ydata()).all()
        np.testing.assert_array_equal(ax.lines[4].get_ydata(), [0, 0])
    finally:
        for fig, _ in figures:
            plt.close(fig)


def test_main_comparison_has_five_unrestricted_series(monkeypatch):
    import matplotlib.pyplot as plt
    render = runpy.run_path(str(ROOT / "scripts/shared_fee/make_figures.py"))["paired_dot_comparison"]
    figures = []
    monkeypatch.setitem(render.__globals__, "save", lambda fig, name: figures.append((fig, name)))
    render()
    source = pd.concat([pd.read_csv(OUT / "shared_fee_elasticity_comparison.csv"),
                        pd.read_csv(OUT / "eip8372/normalized_outcomes.csv")])
    source = source[source.window_days.eq(35)]
    try:
        fig, name = figures[0]
        assert name == "shared_fee_comparison_execution_paired_dot.png"
        ax = fig.axes[0]
        assert len(ax.lines) == 5  # Five unrestricted families; no capped points.
        for line, family in zip(ax.lines, ("proposal_faithful", "fully_optimized", "normalized_state", "balanced", "maximum"), strict=True):
            group = source[source.benchmark.eq(family)].sort_values("propagation_time_s")
            np.testing.assert_array_equal(line.get_xdata(), group.metered_execution_gas / 1e6)
            np.testing.assert_array_equal(line.get_ydata(), np.arange(5))
        assert [line.get_label().split("\n")[0] for line in ax.lines[:3]] == [
            "Baseline", "Floor-adjusted + EIP-8368", "Floor-adjusted + EIP-8372"]
        assert all(line.get_fillstyle() == "full" for line in ax.lines)
        assert ax.get_ylim()[0] < ax.get_ylim()[1]
    finally:
        for fig, _ in figures:
            plt.close(fig)


def test_report_tables_reproduce_from_outputs_and_link_unrestricted_figure():
    tables = runpy.run_path(str(ROOT / "scripts/shared_fee/elasticity_report_tables.py"))["report_tables"]()
    report = (ROOT / "markdowns/eip8279_floor_calibration_report.md").read_text()
    for key in ("selection", "proposal_faithful", "fully_optimized", "fixed"):
        assert tables[key] in report
    assert "../plots/shared_fee_comparison_execution_paired_dot.png" in report
    assert "rJmApYpuGl.png" not in report
    assert "floor price" not in report.lower()
    manifest = json.loads((OUT / "shared_fee_elasticity_robustness_manifest.json").read_text())
    assert manifest["shared_surface_rows"] == 708
    assert manifest["paired_gain_rows"] == 40
