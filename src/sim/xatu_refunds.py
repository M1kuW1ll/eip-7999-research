"""Xatu-only calibration of current and EIP-8038 transaction refunds."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd


ZERO_WORD = "0x" + "00" * 32
FULL_RANGE_QUERY_PATH = Path(__file__).with_name("xatu_refund_full.sql")


def sample_blocks_by_day(
    days: pd.DataFrame,
    n_per_day: int = 5,
    seed: int = 42,
) -> pd.DataFrame:
    """Draw a deterministic uniform block sample within each daily range."""

    required = {"date", "min_block", "max_block"}
    missing = required - set(days.columns)
    if missing:
        raise ValueError(f"days is missing columns: {sorted(missing)}")
    if n_per_day <= 0:
        raise ValueError("n_per_day must be positive")

    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for day in days.sort_values("date").itertuples(index=False):
        low = int(day.min_block)
        high = int(day.max_block)
        if high < low:
            raise ValueError(f"{day.date} has max_block below min_block")
        count = min(n_per_day, high - low + 1)
        sampled = rng.choice(np.arange(low, high + 1), size=count, replace=False)
        for block_number in sampled:
            rows.append(
                {
                    "date": pd.Timestamp(day.date),
                    "block_number": int(block_number),
                }
            )
    return pd.DataFrame(rows).sort_values(["date", "block_number"]).reset_index(
        drop=True
    )


def _normalize_hash(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def query_xatu_refund_transactions(
    raw_client,
    block_numbers: Sequence[int],
    network: str = "mainnet",
) -> pd.DataFrame:
    """Return the Xatu fields needed to reconstruct refund-positive transactions."""

    blocks = sorted({int(block) for block in block_numbers})
    if not blocks:
        return pd.DataFrame()
    params = {"network": network, "blocks": blocks, "zero": ZERO_WORD}
    settings = {"max_execution_time": 900}

    ops = raw_client.query_df(
        """
        SELECT
            block_number,
            transaction_hash,
            sumIf(opcode_count, operation = 'SSTORE') AS sstore_count,
            sumIf(gas, operation = 'SSTORE') AS sstore_gas_current,
            sumIf(cold_access_count, operation = 'SSTORE') AS sstore_cold_count,
            maxIf(
                ifNull(gas_refund, 0),
                operation = '' AND call_frame_id = 0
            ) AS refund_counter_current
        FROM default.canonical_execution_transaction_structlog_agg FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number, transaction_hash
        HAVING refund_counter_current > 0
        """,
        parameters=params,
        settings=settings,
    )

    storage = raw_client.query_df(
        """
        SELECT
            block_number,
            transaction_hash,
            count() AS changed_slots,
            countIf(
                lower(from_value) = {zero:String}
                AND lower(to_value) != {zero:String}
            ) AS zero_to_nonzero_slots,
            countIf(lower(from_value) != {zero:String}) AS original_nonzero_changed,
            countIf(
                lower(from_value) != {zero:String}
                AND lower(to_value) = {zero:String}
            ) AS net_cleared_slots
        FROM default.canonical_execution_storage_diffs FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number, transaction_hash
        """,
        parameters=params,
        settings=settings,
    )

    transactions = raw_client.query_df(
        """
        SELECT
            block_number,
            hash AS transaction_hash,
            type AS transaction_type,
            n_input_zero_bytes AS calldata_zero_bytes,
            n_input_nonzero_bytes AS calldata_nonzero_bytes
        FROM default.execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        """,
        parameters=params,
        settings=settings,
    )

    receipts = raw_client.query_df(
        """
        SELECT
            block_number,
            transaction_hash,
            gas_used AS receipt_gas_used
        FROM default.canonical_execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        """,
        parameters=params,
        settings=settings,
    )

    keys = ["block_number", "transaction_hash"]
    out = (
        ops.merge(storage, on=keys, how="left", validate="one_to_one")
        .merge(transactions, on=keys, how="left", validate="one_to_one")
        .merge(receipts, on=keys, how="left", validate="one_to_one")
    )
    for column in [
        "changed_slots",
        "zero_to_nonzero_slots",
        "original_nonzero_changed",
        "net_cleared_slots",
    ]:
        out[column] = out[column].fillna(0)
    required_complete = [
        "transaction_type",
        "calldata_zero_bytes",
        "calldata_nonzero_bytes",
        "receipt_gas_used",
    ]
    if out[required_complete].isna().any().any():
        missing = out[required_complete].isna().sum().to_dict()
        raise RuntimeError(f"Incomplete Xatu refund sample merge: {missing}")
    out["transaction_hash"] = out["transaction_hash"].map(_normalize_hash)
    numeric = [column for column in out.columns if column != "transaction_hash"]
    out[numeric] = out[numeric].astype("int64")
    return out.sort_values(["block_number", "transaction_hash"]).reset_index(drop=True)


def query_xatu_refund_daily_full(
    raw_client,
    *,
    min_block: int,
    max_block: int,
    other_gross_delta_rate: float,
    network: str = "mainnet",
) -> pd.DataFrame:
    """Run the transaction-level refund recovery in ClickHouse and return daily sums.

    Storage repricing is transaction-specific. The remaining regular- and
    state-gas change enters the refund-cap denominator through
    ``other_gross_delta_rate``, calibrated from the full daily accounting panel.
    """

    if max_block < min_block:
        raise ValueError("max_block must not be below min_block")
    query = FULL_RANGE_QUERY_PATH.read_text()
    return raw_client.query_df(
        query,
        parameters={
            "network": network,
            "min_block": int(min_block),
            "max_block": int(max_block),
            "zero": ZERO_WORD,
            "other_rate": float(other_gross_delta_rate),
        },
        settings={"max_execution_time": 1800},
    )


def _cap_bound_current_gas(receipt_gas_used: int, refund_counter: int) -> int:
    """Invert the current 20% cap when the refund counter is cap-binding."""

    center = (5 * int(receipt_gas_used)) // 4
    candidates = []
    for gross in range(max(receipt_gas_used, center - 6), center + 8):
        applied = min(refund_counter, gross // 5)
        if gross - applied == receipt_gas_used:
            candidates.append(gross)
    return min(candidates) if candidates else receipt_gas_used + min(
        refund_counter, receipt_gas_used // 4
    )


def recover_eip8038_refunds(frame: pd.DataFrame) -> pd.DataFrame:
    """Recover EIP-8038 refund counters using Xatu final diffs and gas identities.

    Exact current-counter solutions are ranked by their reconstruction error for
    observed SSTORE gas. Transactions without an exact solution receive a pooled
    Xatu proxy after all identified transactions have been processed.
    """

    required = {
        "transaction_type",
        "sstore_count",
        "sstore_gas_current",
        "sstore_cold_count",
        "refund_counter_current",
        "changed_slots",
        "zero_to_nonzero_slots",
        "original_nonzero_changed",
        "net_cleared_slots",
        "calldata_zero_bytes",
        "calldata_nonzero_bytes",
        "receipt_gas_used",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"refund frame is missing columns: {sorted(missing)}")

    records: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        refund_current = int(row.refund_counter_current)
        residual = refund_current - 4_800 * int(row.net_cleared_slots)
        solutions: list[dict[str, int]] = []
        max_auth = residual // 12_500 if int(row.transaction_type) == 4 else 0
        for auth_refunds in range(max(0, max_auth) + 1):
            sstore_refund = residual - 12_500 * auth_refunds
            if sstore_refund < 0 or sstore_refund % 100:
                continue
            for zero_resets in range(sstore_refund // 19_900 + 1):
                remainder = sstore_refund - 19_900 * zero_resets
                if remainder < 0 or remainder % 2_800:
                    continue
                nonzero_resets = remainder // 2_800
                minimum_sstores = int(row.changed_slots) + 2 * (
                    zero_resets + nonzero_resets
                )
                if minimum_sstores > int(row.sstore_count):
                    continue
                modeled_sstore_gas = (
                    100 * int(row.sstore_count)
                    + 2_100 * int(row.sstore_cold_count)
                    + 19_900
                    * (int(row.zero_to_nonzero_slots) + zero_resets)
                    + 2_800
                    * (int(row.original_nonzero_changed) + nonzero_resets)
                )
                future_refund = (
                    12_500 * auth_refunds
                    + 12_480 * int(row.net_cleared_slots)
                    + 10_000 * (zero_resets + nonzero_resets)
                )
                solutions.append(
                    {
                        "auth_refunds": auth_refunds,
                        "zero_resets": zero_resets,
                        "nonzero_resets": nonzero_resets,
                        "sstore_gas_residual": int(row.sstore_gas_current)
                        - modeled_sstore_gas,
                        "refund_counter_8038": future_refund,
                    }
                )

        if solutions:
            best_error = min(abs(item["sstore_gas_residual"]) for item in solutions)
            preferred = [
                item
                for item in solutions
                if abs(item["sstore_gas_residual"]) == best_error
            ]
            future = [item["refund_counter_8038"] for item in preferred]
            central_item = preferred[len(preferred) // 2]
            record = {
                "refund_identification": (
                    "unique" if len(preferred) == 1 else "bounded"
                ),
                "refund_solution_count": len(solutions),
                "refund_preferred_count": len(preferred),
                "auth_refunds_est": central_item["auth_refunds"],
                "zero_reset_slots_est": central_item["zero_resets"],
                "nonzero_reset_slots_est": central_item["nonzero_resets"],
                "sstore_gas_residual": central_item["sstore_gas_residual"],
                "refund_counter_8038_low": min(future),
                "refund_counter_8038": int(np.median(future)),
                "refund_counter_8038_high": max(future),
            }
        else:
            record = {
                "refund_identification": "proxy",
                "refund_solution_count": 0,
                "refund_preferred_count": 0,
                "auth_refunds_est": np.nan,
                "zero_reset_slots_est": np.nan,
                "nonzero_reset_slots_est": np.nan,
                "sstore_gas_residual": np.nan,
                "refund_counter_8038_low": np.nan,
                "refund_counter_8038": np.nan,
                "refund_counter_8038_high": np.nan,
            }
        records.append(record)

    out = pd.concat(
        [frame.reset_index(drop=True), pd.DataFrame(records)], axis=1
    )
    identified = out[out["refund_identification"] != "proxy"].copy()
    if identified.empty:
        raise RuntimeError("No refund transactions were identified")
    ratios = (
        identified["refund_counter_8038"]
        / identified["refund_counter_current"]
    ).replace([np.inf, -np.inf], np.nan).dropna()
    pooled_ratio = (
        identified["refund_counter_8038"].sum()
        / identified["refund_counter_current"].sum()
    )
    ratio_low = float(ratios.quantile(0.10))
    ratio_high = float(ratios.quantile(0.90))
    proxy = out["refund_identification"].eq("proxy")
    out.loc[proxy, "refund_counter_8038"] = (
        out.loc[proxy, "refund_counter_current"] * pooled_ratio
    )
    out.loc[proxy, "refund_counter_8038_low"] = (
        out.loc[proxy, "refund_counter_current"] * ratio_low
    )
    out.loc[proxy, "refund_counter_8038_high"] = (
        out.loc[proxy, "refund_counter_current"] * ratio_high
    )

    out["calldata_tokens"] = (
        out["calldata_zero_bytes"] + 4 * out["calldata_nonzero_bytes"]
    ).astype("int64")
    out["current_7623_floor_proxy"] = (
        (out["calldata_tokens"] > 0)
        & (
            (out["receipt_gas_used"] - 21_000).clip(lower=0)
            <= 10 * out["calldata_tokens"]
        )
    )

    uncapped = 4 * out["refund_counter_current"] <= out["receipt_gas_used"]
    out["current_refund_cap_status"] = np.where(
        out["current_7623_floor_proxy"],
        "floor-proxied",
        np.where(uncapped, "uncapped", "cap-binding"),
    )
    out["refund_applied_current"] = out["refund_counter_current"].astype(
        "int64"
    )
    cap_binding = ~uncapped
    out.loc[cap_binding, "gross_gas_current_proxy"] = out.loc[
        cap_binding
    ].apply(
        lambda row: _cap_bound_current_gas(
            int(row["receipt_gas_used"]), int(row["refund_counter_current"])
        ),
        axis=1,
    )
    out.loc[~cap_binding, "gross_gas_current_proxy"] = (
        out.loc[~cap_binding, "receipt_gas_used"]
        + out.loc[~cap_binding, "refund_counter_current"]
    )
    out.loc[cap_binding, "refund_applied_current"] = (
        out.loc[cap_binding, "gross_gas_current_proxy"]
        - out.loc[cap_binding, "receipt_gas_used"]
    )

    integer_columns = [
        "refund_counter_8038_low",
        "refund_counter_8038",
        "refund_counter_8038_high",
        "refund_applied_current",
        "gross_gas_current_proxy",
    ]
    out[integer_columns] = out[integer_columns].round().astype("int64")
    return out
