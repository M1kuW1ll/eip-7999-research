"""The schematic must retain the actual model limits and rectangular geometry."""
from pathlib import Path
import runpy

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "scripts/make_slot_time_capacity_geometry.py"))


def test_capacities_match_simulated_slot_limits():
    points = MODULE["capacity_points"]()
    cached = pd.read_csv(ROOT / "data/7999/slot_time_scenarios.csv")
    for propagation, execution_time, execution, data in points:
        rows = cached[cached.propagation_time_s.eq(propagation)]
        assert len(rows) > 0
        np.testing.assert_allclose(rows.execution_limit, execution * 1e6)
        np.testing.assert_allclose(rows.data_limit, data * 1e6)
        assert propagation + execution_time == 9


def test_union_uses_steps_not_a_diagonal_budget():
    vertices = MODULE["feasible_union_vertices"](MODULE["capacity_points"]())
    differences = np.diff(np.vstack([vertices, vertices[:1]]), axis=0)
    assert np.all((differences[:, 0] == 0) | (differences[:, 1] == 0))
    np.testing.assert_array_equal(vertices[0], [0, 0])


def test_single_panel_includes_both_capacity_formulas():
    import matplotlib.pyplot as plt

    fig = MODULE["make_figure"]()
    try:
        assert len(fig.axes) == 1
        ax = fig.axes[0]
        texts = [text.get_text() for text in ax.texts]
        assert any("L_E(t) = 100" in text for text in texts)
        assert any("L_D(t)" in text and "1000t-569" in text and "0.443" in text
                   for text in texts)
        assert len(ax.lines) == 10
        assert ax.get_ylabel() == "Data gas usage (M)"
    finally:
        plt.close(fig)
