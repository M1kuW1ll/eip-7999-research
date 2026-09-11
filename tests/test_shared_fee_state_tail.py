from pathlib import Path
import runpy

import pandas as pd
import pytest


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/shared_fee/run_optimized_state_tail.py"))


def test_state_tail_append_preserves_existing_cases():
    old = pd.DataFrame({"cap": [2.0, 3.0], "value": [123.4, 234.5]})
    new = pd.DataFrame({"value": [99.9], "cap": [1.5]})
    result = MODULE["append_new_rows"](old, new, ["cap"])
    pd.testing.assert_frame_equal(result.iloc[:2], old)
    assert list(result.cap) == [2.0, 3.0, 1.5]
    with pytest.raises(ValueError, match="duplicate"):
        MODULE["append_new_rows"](old, old.iloc[:1], ["cap"])
    with pytest.raises(ValueError, match="columns differ"):
        MODULE["append_new_rows"](old, new.assign(extra=1), ["cap"])


def test_state_tail_grid_includes_fractional_cap():
    assert MODULE["CAP_MULTIPLES"] == (1.5, 2.0, 3.0, 4.0, 5.0, float("inf"))
    assert MODULE["label"](1.5) == "1.5x"
