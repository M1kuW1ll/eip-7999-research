"""RPC/prestateTracer helpers for EIP-8037 state-growth calibration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from resources.accounting import (
    STATE_BYTES_PER_DELEGATION_INDICATOR,
    STATE_BYTES_PER_NEW_ACCOUNT,
    STATE_BYTES_PER_STORAGE_SET,
)

from .rpc_bal import fetch_block_trace, parse_int, rpc_call

DELEGATION_CODE_PREFIX = "0xef0100"


@dataclass(frozen=True)
class RpcStateGrowthSummary:
    block_number: int
    tx_count: int
    successful_tx_count: int
    reverted_tx_count: int
    new_storage_slots: int
    new_accounts: int
    code_bytes: int
    new_delegation_indicators: int
    state_bytes_equivalent: int
    state_gas_used: int

    def as_dict(self) -> dict[str, int]:
        return {
            "block_number": self.block_number,
            "tx_count": self.tx_count,
            "successful_tx_count": self.successful_tx_count,
            "reverted_tx_count": self.reverted_tx_count,
            "rpc_new_storage_slots": self.new_storage_slots,
            "rpc_new_accounts": self.new_accounts,
            "rpc_code_bytes": self.code_bytes,
            "rpc_new_delegation_indicators": self.new_delegation_indicators,
            "rpc_state_bytes_equivalent": self.state_bytes_equivalent,
            "rpc_state_gas_used": self.state_gas_used,
        }


def normalize_code(code: Any) -> str:
    if not code:
        return "0x"
    text = str(code).lower()
    if not text.startswith("0x"):
        text = "0x" + text
    return text


def code_bytes_len(code: Any) -> int:
    text = normalize_code(code)
    if text == "0x":
        return 0
    return max(0, (len(text) - 2) // 2)


def is_delegation_code(code: Any) -> bool:
    return normalize_code(code).startswith(DELEGATION_CODE_PREFIX)


def account_exists(account: dict[str, Any] | None) -> bool:
    if not account:
        return False
    return (
        parse_int(account.get("balance"), 0) > 0
        or parse_int(account.get("nonce"), 0) > 0
        or code_bytes_len(account.get("code")) > 0
    )


def storage_value_nonzero(value: Any) -> bool:
    return parse_int(value, 0) != 0


def summarize_rpc_state_growth_from_traces(
    *,
    block_number: int,
    diff_trace: list[dict[str, Any]],
    receipts: Sequence[dict[str, Any]],
    cpsb: int = 1530,
) -> RpcStateGrowthSummary:
    if cpsb <= 0:
        raise ValueError("cpsb must be positive")

    reverted_tx_indices = {
        index
        for index, receipt in enumerate(receipts)
        if receipt and receipt.get("status") == "0x0"
    }

    new_storage_slots = 0
    new_accounts = 0
    code_bytes = 0
    new_delegation_indicators = 0

    for tx_index, tx_trace in enumerate(diff_trace):
        if tx_index in reverted_tx_indices:
            continue
        result = tx_trace.get("result")
        if not isinstance(result, dict):
            continue

        pre_state = result.get("pre", {}) or {}
        post_state = result.get("post", {}) or {}
        for address in set(pre_state) | set(post_state):
            pre_account = pre_state.get(address, {}) or {}
            post_account = post_state.get(address, {}) or {}

            if not account_exists(pre_account) and account_exists(post_account):
                new_accounts += 1

            pre_code = normalize_code(pre_account.get("code"))
            post_code = normalize_code(post_account.get("code"))
            if post_code != "0x" and post_code != pre_code:
                if is_delegation_code(post_code):
                    if not is_delegation_code(pre_code):
                        new_delegation_indicators += 1
                else:
                    code_bytes += code_bytes_len(post_code)

            pre_storage = pre_account.get("storage", {}) or {}
            post_storage = post_account.get("storage", {}) or {}
            for slot, post_value in post_storage.items():
                pre_value = pre_storage.get(slot, 0)
                if (
                    not storage_value_nonzero(pre_value)
                    and storage_value_nonzero(post_value)
                ):
                    new_storage_slots += 1

    state_bytes_equivalent = (
        new_storage_slots * STATE_BYTES_PER_STORAGE_SET
        + new_accounts * STATE_BYTES_PER_NEW_ACCOUNT
        + code_bytes
        + new_delegation_indicators * STATE_BYTES_PER_DELEGATION_INDICATOR
    )
    return RpcStateGrowthSummary(
        block_number=int(block_number),
        tx_count=len(diff_trace),
        successful_tx_count=len(diff_trace) - len(reverted_tx_indices),
        reverted_tx_count=len(reverted_tx_indices),
        new_storage_slots=new_storage_slots,
        new_accounts=new_accounts,
        code_bytes=code_bytes,
        new_delegation_indicators=new_delegation_indicators,
        state_bytes_equivalent=state_bytes_equivalent,
        state_gas_used=state_bytes_equivalent * int(cpsb),
    )


def summarize_rpc_state_growth_for_block(
    rpc_url: str,
    block_number: int,
    *,
    rpc_headers: dict[str, str] | None = None,
    cpsb: int = 1530,
) -> RpcStateGrowthSummary:
    diff_trace = fetch_block_trace(
        rpc_url,
        block_number,
        diff_mode=True,
        headers=rpc_headers,
    )
    receipts = rpc_call(
        rpc_url,
        "eth_getBlockReceipts",
        [hex(block_number)],
        timeout=120,
        headers=rpc_headers,
    )
    return summarize_rpc_state_growth_from_traces(
        block_number=block_number,
        diff_trace=diff_trace,
        receipts=receipts,
        cpsb=cpsb,
    )


def summarize_rpc_state_growth_for_blocks(
    rpc_url: str,
    block_numbers: Sequence[int],
    *,
    rpc_headers: dict[str, str] | None = None,
    cpsb: int = 1530,
) -> pd.DataFrame:
    rows = []
    for block_number in block_numbers:
        rows.append(
            summarize_rpc_state_growth_for_block(
                rpc_url,
                int(block_number),
                rpc_headers=rpc_headers,
                cpsb=cpsb,
            ).as_dict()
        )
    return pd.DataFrame(rows)
