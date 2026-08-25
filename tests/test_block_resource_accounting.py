import importlib.util
from pathlib import Path

import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_contiguous_block_panel.py"
SPEC = importlib.util.spec_from_file_location("build_contiguous_block_panel", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
allocate_weighted_with_caps = MODULE.allocate_weighted_with_caps


def test_weighted_allocation_preserves_total_and_respects_caps():
    allocation = allocate_weighted_with_caps(
        10.0,
        np.array([9.0, 1.0, 0.0]),
        np.array([3.0, 20.0, 20.0]),
    )

    assert allocation.sum() == pytest.approx(10.0)
    assert allocation == pytest.approx([3.0, 7.0, 0.0])


def test_zero_weights_fall_back_to_available_capacity():
    allocation = allocate_weighted_with_caps(
        6.0,
        np.zeros(3),
        np.array([1.0, 2.0, 3.0]),
    )

    assert allocation == pytest.approx([1.0, 2.0, 3.0])


def test_allocation_rejects_infeasible_daily_total():
    with pytest.raises(ValueError, match="exceeds the day's gas budget"):
        allocate_weighted_with_caps(
            7.0,
            np.ones(3),
            np.array([1.0, 2.0, 3.0]),
        )
