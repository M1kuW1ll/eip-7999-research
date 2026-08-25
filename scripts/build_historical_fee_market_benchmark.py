"""Build the current-mainnet benchmark used by the slot-time design report.

The dynamic simulator can place a continuous aggregate quantity exactly at a
hard limit. Historical blocks contain indivisible transactions and therefore
rarely equal their limit byte-for-byte. For a comparable congestion statistic,
both historical and simulated blocks are classed as near their limit at 98%.

The historical target is the EIP-1559 target in each block, ``gas_limit / 2``.
Target distance is normalized by that block-specific target before averaging,
so it remains comparable when the gas limit changes during the source window.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from build_contiguous_block_panel import NETWORK, client


ROOT = Path(__file__).resolve().parents[1]
START = "2026-02-01 00:00:00"
END = "2026-06-01 00:00:00"
NEAR_LIMIT_THRESHOLD = 0.98

DAILY_QUERY = """
    SELECT
        toDate(block_date_time) AS date,
        count() AS block_count,
        avg(toFloat64(gas_used)) AS mean_gas_used,
        avg(toFloat64(gas_limit) / 2.0) AS mean_gas_target,
        avg(toFloat64(gas_used) / (toFloat64(gas_limit) / 2.0))
            AS mean_target_utilisation,
        avg(abs(toFloat64(gas_used) - toFloat64(gas_limit) / 2.0))
            AS mean_absolute_target_gap_gas,
        avg(
            abs(toFloat64(gas_used) - toFloat64(gas_limit) / 2.0)
            / (toFloat64(gas_limit) / 2.0)
        ) AS mean_absolute_target_deviation,
        avg(toFloat64(gas_used) >= {near_limit:Float64} * toFloat64(gas_limit))
            AS near_limit_fraction,
        avg(toFloat64(gas_used) >= 0.99 * toFloat64(gas_limit))
            AS near_limit_fraction_99,
        avg(toFloat64(gas_used) >= 0.999 * toFloat64(gas_limit))
            AS near_limit_fraction_999,
        avg(toFloat64(gas_limit) - toFloat64(gas_used) < 21000.0)
            AS less_than_21000_gas_remaining_fraction,
        avg(toFloat64(gas_used) >= toFloat64(gas_limit))
            AS limit_hit_fraction,
        min(toFloat64(gas_limit) - toFloat64(gas_used))
            AS minimum_gas_remaining,
        max(toFloat64(gas_used) / toFloat64(gas_limit))
            AS maximum_limit_utilisation,
        avg(toFloat64(gas_used) * toFloat64(base_fee_per_gas))
            AS mean_base_fee_burn_wei_per_block
    FROM default.canonical_execution_block FINAL
    WHERE meta_network_name = {network:String}
      AND block_date_time >= parseDateTime64BestEffort({start:String})
      AND block_date_time < parseDateTime64BestEffort({end:String})
      AND gas_limit > 0
    GROUP BY date
    ORDER BY date
"""


def weighted_mean(frame: pd.DataFrame, column: str) -> float:
    return float(np.average(frame[column], weights=frame["block_count"]))


def main() -> None:
    conn = client()
    daily = conn.query_df(
        DAILY_QUERY,
        parameters={
            "network": NETWORK,
            "start": START,
            "end": END,
            "near_limit": NEAR_LIMIT_THRESHOLD,
        },
        settings={"max_execution_time": 600},
    )
    if daily.empty:
        raise RuntimeError("historical benchmark query returned no blocks")

    daily["mean_base_fee_burn_eth_per_block"] = (
        daily["mean_base_fee_burn_wei_per_block"] / 1e18
    )
    daily_path = ROOT / "data/7999/historical_fee_market_benchmark_daily.csv"
    daily.to_csv(daily_path, index=False)

    metric_columns = [
        "mean_gas_used",
        "mean_gas_target",
        "mean_target_utilisation",
        "mean_absolute_target_gap_gas",
        "mean_absolute_target_deviation",
        "near_limit_fraction",
        "near_limit_fraction_99",
        "near_limit_fraction_999",
        "less_than_21000_gas_remaining_fraction",
        "limit_hit_fraction",
        "mean_base_fee_burn_wei_per_block",
        "mean_base_fee_burn_eth_per_block",
    ]
    summary = {
        "start_date": START[:10],
        "end_date_exclusive": END[:10],
        "block_count": int(daily["block_count"].sum()),
        "near_limit_threshold": NEAR_LIMIT_THRESHOLD,
        **{column: weighted_mean(daily, column) for column in metric_columns},
        "minimum_gas_remaining": float(daily["minimum_gas_remaining"].min()),
        "maximum_limit_utilisation": float(
            daily["maximum_limit_utilisation"].max()
        ),
    }
    summary_path = ROOT / "data/7999/historical_fee_market_benchmark.csv"
    pd.DataFrame([summary]).to_csv(summary_path, index=False)

    print(f"wrote {daily_path.relative_to(ROOT)} ({len(daily)} days)")
    print(f"wrote {summary_path.relative_to(ROOT)}")
    print(
        f"{summary['block_count']:,} blocks; "
        f"at limit {summary['limit_hit_fraction']:.2%}; "
        f"near limit {summary['near_limit_fraction']:.2%}; "
        f"minimum slack {summary['minimum_gas_remaining']:.0f} gas; "
        f"mean absolute target deviation "
        f"{summary['mean_absolute_target_deviation']:.2%}; "
        f"base-fee burn {summary['mean_base_fee_burn_eth_per_block']:.6f} ETH/block"
    )


if __name__ == "__main__":
    main()
