"""Rebuild the shared-fee execution multiplier under the current EIP schedule.

The earlier project-wide cache used the EIP-8038 schedule before commit
8331fb3. This script reuses the observed daily activity counts, reconstructs
refunds under the post-commit schedule, and writes the current calibration
under data/shared_fee/.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import clickhouse_connect
import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shared_fee.floor_accounting import (  # noqa: E402
    ACCESS_LIST_ADDRESS_COST_8038,
    ACCESS_LIST_STORAGE_KEY_COST_8038,
    ACCOUNT_WRITE_8038,
    COLD_STORAGE_ACCESS_8038,
    CREATE_ACCESS_8038,
    STORAGE_WRITE_8038,
)
from sim.xatu_refunds import query_xatu_refund_daily_full  # noqa: E402


TAG = "2026-02-01_2026-06-01"
SOURCE = ROOT / f"data/execution_repricing_daily_{TAG}.csv"
OUT_DIR = ROOT / "data/shared_fee"
REFUND_OUT = OUT_DIR / f"xatu_full_refund_daily_eip8038_post_8331fb3_{TAG}.csv"
EXECUTION_OUT = OUT_DIR / f"execution_repricing_daily_eip8038_current_{TAG}.csv"

CURRENT_ACCOUNT_WRITE_EQUIVALENT = 6_700
CURRENT_ACCESS_LIST_ADDRESS_COST = 2_400
CURRENT_ACCESS_LIST_STORAGE_KEY_COST = 1_900
CURRENT_AUTHORIZATION_INTRINSIC = 25_000
FUTURE_AUTHORIZATION_INTRINSIC = 7_816
STATE_CPSB = 1_530


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-refunds",
        action="store_true",
        help="Refresh the 120-day refund-cap aggregates from Xatu.",
    )
    parser.add_argument("--days-per-query", type=int, default=2)
    return parser.parse_args()


def write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def rebuild_requested_deltas(daily: pd.DataFrame) -> pd.DataFrame:
    """Recompute every observed-path delta under the same EIP schedule."""

    out = daily.copy()
    out["sstore_regular_8038"] = (
        100 * (out["sstore_count"] - out["sstore_cold_count"])
        + COLD_STORAGE_ACCESS_8038 * out["sstore_cold_count"]
        + STORAGE_WRITE_8038 * out["sstore_first_changes_est"]
    )
    out["delta_8038_sstore"] = (
        out["sstore_regular_8038"] - out["sstore_regular_current_aligned"]
    )
    out["delta_8038_sload_cold"] = 0.0
    out["delta_8038_account_cold"] = 400 * out["account_cold_count"]
    out["delta_8038_ext_second_read"] = 100 * out["ext_second_read_count"]
    out["delta_8038_internal_value_calls"] = (
        ACCOUNT_WRITE_8038 - CURRENT_ACCOUNT_WRITE_EQUIVALENT
    ) * out["positive_value_internal_calls"]
    out["delta_8038_access_lists"] = (
        (ACCESS_LIST_ADDRESS_COST_8038 - CURRENT_ACCESS_LIST_ADDRESS_COST)
        * out["access_list_address_count"]
        + (
            ACCESS_LIST_STORAGE_KEY_COST_8038
            - CURRENT_ACCESS_LIST_STORAGE_KEY_COST
        )
        * out["access_list_key_count"]
    )

    # The RPC calibration counts authorization tuples. EIP-2780 replaces the
    # current 25,000-gas intrinsic charge and 12,500-gas refund with a
    # 7,816-gas intrinsic charge plus one 9,000-gas authority-account write.
    # The removed refund is handled by the refund reconstruction below.
    out["delta_8038_authorizations"] = (
        FUTURE_AUTHORIZATION_INTRINSIC
        - CURRENT_AUTHORIZATION_INTRINSIC
        + ACCOUNT_WRITE_8038
    ) * out["eoa_account_write_count"]
    out["delta_8038_internal_create"] = (
        (CREATE_ACCESS_8038 - 32_000) * out["internal_create_opcode_count"]
        + 25_000 * out["successful_internal_creates"]
    )
    out["delta_2780_intrinsic"] = (
        -9_000 * out["self_txs"]
        -6_000 * out["distinct_zero_value_txs"]
        -4_000 * out["create_success_zero_value"]
        -4_000 * out["create_success_value"]
        -29_000 * out["create_failed_zero_value"]
        -29_000 * out["create_failed_value"]
    )
    delta_columns = [
        "delta_8038_sstore",
        "delta_8038_sload_cold",
        "delta_8038_account_cold",
        "delta_8038_ext_second_read",
        "delta_8038_internal_value_calls",
        "delta_8038_access_lists",
        "delta_8038_authorizations",
        "delta_8038_internal_create",
    ]
    out["delta_8038_central"] = out[delta_columns].sum(axis=1)
    out["delta_requested_central"] = (
        out["delta_8038_central"] + out["delta_2780_intrinsic"]
    )
    return out


def corrected_other_gross_delta_rate(daily: pd.DataFrame) -> float:
    storage_state_new = daily["new_storage_slots"] * 64 * STATE_CPSB
    storage_state_current = daily["new_storage_slots"] * 20_000
    other_regular = (
        daily["delta_requested_central"]
        - daily["delta_8038_sstore"]
    )
    other_state = (
        daily["state_gas_8037_calibrated"]
        - daily["current_state_creation_gas_calibrated"]
        - (storage_state_new - storage_state_current)
    )
    other_base = (
        daily["current_gas_used"] - daily["sstore_gas_current"]
    ).clip(lower=1)
    return float((other_regular.sum() + other_state.sum()) / other_base.sum())


def refresh_refunds(
    daily: pd.DataFrame,
    *,
    other_rate: float,
    days_per_query: int,
) -> pd.DataFrame:
    if days_per_query <= 0:
        raise ValueError("days-per-query must be positive")
    load_dotenv(ROOT / ".env")
    client = clickhouse_connect.get_client(
        host=os.environ.get(
            "CLICKHOUSE_RAW_HOST", "clickhouse-raw.xatu.ethpandaops.io"
        ),
        port=int(os.environ.get("CLICKHOUSE_PORT", "443")),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=True,
    )
    if REFUND_OUT.exists():
        completed = pd.read_csv(REFUND_OUT)
        completed["date"] = pd.to_datetime(completed["date"])
    else:
        completed = pd.DataFrame()
    completed_dates = (
        set(completed["date"]) if not completed.empty else set()
    )
    rows = [] if completed.empty else [completed]
    for start in range(0, len(daily), days_per_query):
        chunk = daily.iloc[start : start + days_per_query]
        if set(chunk["date"]).issubset(completed_dates):
            continue
        result = query_xatu_refund_daily_full(
            client,
            min_block=int(chunk["min_block"].min()),
            max_block=int(chunk["max_block"].max()),
            other_gross_delta_rate=other_rate,
        )
        result["date"] = pd.to_datetime(result["date"])
        rows.append(result)
        completed = (
            pd.concat(rows, ignore_index=True)
            .drop_duplicates("date", keep="last")
            .sort_values("date")
        )
        write_atomic(completed, REFUND_OUT)
        completed_dates = set(completed["date"])
        print(f"refund days cached: {len(completed)}/{len(daily)}", flush=True)
    return completed


def rebuild_execution(daily: pd.DataFrame, refund: pd.DataFrame) -> pd.DataFrame:
    refund_columns = [column for column in refund if column != "date"]
    out = daily.drop(
        columns=[column for column in refund_columns if column in daily]
    ).merge(refund, on="date", how="left", validate="one_to_one")
    if out[refund_columns].isna().any().any():
        raise ValueError("Corrected refund cache does not cover all 120 days")

    out["execution_8038_2780"] = (
        out["execution_current"] + out["delta_requested_central"]
    )
    out["refund_proxy_scale"] = (
        out["refund_counter_total"] / out["refund_counter_identified"]
    )
    out["refund_extra_8038"] = (
        out["extra_refund_current_floor"] * out["refund_proxy_scale"]
    )
    out["refund_extra_8038_7976_floor"] = (
        out["extra_refund_7976_floor"] * out["refund_proxy_scale"]
    )
    out["execution_8038_2780_refund_corrected"] = (
        out["execution_8038_2780"] - out["refund_extra_8038"]
    )
    out["execution_8038_2780_refund_corrected_7976_floor"] = (
        out["execution_8038_2780"] - out["refund_extra_8038_7976_floor"]
    )
    out["m_execution_8038_2780_refund_corrected_daily"] = (
        out["execution_8038_2780_refund_corrected"]
        / out["execution_current"]
    )
    out["m_execution_8038_2780_refund_corrected_7976_floor_daily"] = (
        out["execution_8038_2780_refund_corrected_7976_floor"]
        / out["execution_current"]
    )
    return out


def main() -> None:
    args = parse_args()
    daily = pd.read_csv(SOURCE)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = rebuild_requested_deltas(daily)
    other_rate = corrected_other_gross_delta_rate(daily)
    if args.refresh_refunds:
        refund = refresh_refunds(
            daily,
            other_rate=other_rate,
            days_per_query=args.days_per_query,
        )
    elif REFUND_OUT.exists():
        refund = pd.read_csv(REFUND_OUT)
        refund["date"] = pd.to_datetime(refund["date"])
    else:
        raise FileNotFoundError(
            f"Missing {REFUND_OUT.relative_to(ROOT)}; rerun with --refresh-refunds"
        )
    corrected = rebuild_execution(daily, refund)
    corrected["refund_other_gross_delta_rate"] = other_rate
    write_atomic(corrected, EXECUTION_OUT)
    multiplier = float(
        corrected["execution_8038_2780_refund_corrected"].sum()
        / corrected["execution_current"].sum()
    )
    print(f"current EIP-8038 execution multiplier: {multiplier:.12f}")


if __name__ == "__main__":
    main()
