"""Publish the updated execution decomposition without replacing legacy results.

Uses only the existing February--May 2026 post-8331fb3 daily calibration.
Run from the repository root with:
    python scripts/shared_fee/make_execution_repricing_figure.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
TAG = "2026-02-01_2026-06-01"
SOURCE = ROOT / "data/shared_fee" / f"execution_repricing_daily_eip8038_current_{TAG}.csv"
OUTPUT = ROOT / "plots" / f"execution_repricing_8038_2780_post_8331fb3_{TAG}"
TABLE = ROOT / "data/shared_fee/execution_repricing_decomposition_eip8038_current.csv"

COMPONENTS = {
    "SSTORE repricing": ("delta_8038_sstore",),
    "Cold SLOAD": ("delta_8038_sload_cold",),
    "Cold account accesses": ("delta_8038_account_cold",),
    "EXTCODESIZE/COPY second read": ("delta_8038_ext_second_read",),
    "Value CALL account writes": ("delta_8038_internal_value_calls",),
    "Access-list + authorization charges": (
        "delta_8038_access_lists", "delta_8038_authorizations",
    ),
    "Internal CREATE split": ("delta_8038_internal_create",),
    "EIP-2780 intrinsic paths": ("delta_2780_intrinsic",),
}


def main() -> None:
    daily = pd.read_csv(SOURCE, parse_dates=["date"]).sort_values("date")
    expected_dates = pd.date_range("2026-02-01", "2026-05-31")
    assert daily["date"].tolist() == expected_dates.tolist()
    blocks = int(daily["block_count"].sum())
    assert blocks == 860_505

    delta_columns = [column for columns in COMPONENTS.values() for column in columns]
    np.testing.assert_allclose(
        daily["execution_current"] + daily[delta_columns].sum(axis=1),
        daily["execution_8038_2780"], rtol=1e-12, atol=1e-3,
    )
    np.testing.assert_allclose(
        daily["execution_8038_2780"] - daily["refund_extra_8038"],
        daily["execution_8038_2780_refund_corrected"], rtol=1e-12, atol=1e-3,
    )

    means = daily.select_dtypes(include="number").sum() / blocks
    multiplier = means["execution_8038_2780_refund_corrected"] / means["execution_current"]
    np.testing.assert_allclose(multiplier, 1.4479558695732846, rtol=1e-12)
    other = means["delta_8038_central"] - means["delta_8038_sstore"] - means["delta_8038_sload_cold"]
    rows = [
        ("Historical regular execution gas", means["execution_current"]),
        ("EIP-8038 SSTORE increase", means["delta_8038_sstore"]),
        ("EIP-8038 cold SLOAD increase", means["delta_8038_sload_cold"]),
        ("Other execution repricing changes", other),
        ("EIP-2780 intrinsic-gas changes", means["delta_2780_intrinsic"]),
        ("Counterfactual gas before additional refunds", means["execution_8038_2780"]),
        ("Additional effective refunds under the updated schedule", -means["refund_extra_8038"]),
        ("Counterfactual execution gas after refunds", means["execution_8038_2780_refund_corrected"]),
    ]
    table = pd.DataFrame(rows, columns=["execution_accounting", "gas_per_block"])
    table["gas_per_block_millions"] = table["gas_per_block"] / 1e6
    table.to_csv(TABLE, index=False)

    components = pd.Series({label: means[list(columns)].sum() for label, columns in COMPONENTS.items()})
    components["Additional effective refunds"] = -means["refund_extra_8038"]
    ordered = (components / 1e6).sort_values()
    daily_multiplier = daily["execution_8038_2780_refund_corrected"] / daily["execution_current"]
    np.testing.assert_allclose(daily_multiplier, daily["m_execution_8038_2780_refund_corrected_daily"])
    p10, p90 = daily_multiplier.quantile([0.1, 0.9])

    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({"font.size": 11, "axes.titlesize": 13, "axes.labelsize": 11})
    fig, axes = plt.subplots(1, 2, figsize=(16.5, 5.8), gridspec_kw={"width_ratios": [1.0, 1.3]}, layout="constrained")
    blue, orange = "#4c78a8", "#f58518"
    bars = axes[0].barh(ordered.index, ordered.values, color=[blue if value >= 0 else orange for value in ordered])
    axes[0].bar_label(bars, labels=[f"{value:+.3f}" if value else "0.000" for value in ordered], padding=4, fontsize=9)
    axes[0].axvline(0, color="black", linewidth=0.8)
    axes[0].set_xlim(-2.7, 13.5)
    axes[0].set_title("Observed-path execution-gas changes")
    axes[0].set_xlabel("million execution gas per block")
    axes[0].tick_params(axis="y", labelsize=10)

    axes[1].plot(daily["date"], daily_multiplier, color=blue, linewidth=1.5, label="daily execution-gas multiplier")
    axes[1].axhspan(p10, p90, color=blue, alpha=0.12, label="p10–p90 across days")
    axes[1].axhline(multiplier, color="#e45756", linestyle="--", linewidth=1.6, label=f"120-day multiplier = {multiplier:.4f}")
    axes[1].axhline(1, color="black", linewidth=0.8)
    axes[1].set_ylim(0.98, max(daily_multiplier.max() + 0.025, 1.55))
    axes[1].set_title("EIP-8038 + EIP-2780 execution-gas multiplier")
    axes[1].set_ylabel("counterfactual execution gas / historical execution gas")
    axes[1].set_xlabel("historical date")
    axes[1].xaxis.set_major_locator(mdates.MonthLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    axes[1].legend(loc="lower left", frameon=True, framealpha=0.96, fontsize=10)
    fig.suptitle("Updated execution repricing with full-range refund reconstruction", fontsize=16)
    OUTPUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUTPUT.with_suffix(".png"), dpi=160)
    fig.savefig(OUTPUT.with_suffix(".pdf"))
    plt.close(fig)

    print(table.to_string(index=False))
    print(f"Execution multiplier: {multiplier:.12f}")
    print(f"Daily multiplier p10–p90: {p10:.6f}–{p90:.6f} (descriptive range, not a confidence interval)")
    print(f"Saved {OUTPUT.with_suffix('.png')} and PDF")


if __name__ == "__main__":
    main()
