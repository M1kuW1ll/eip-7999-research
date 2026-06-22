"""Build raw RLP BAL estimates from Xatu's canonical execution tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

import pandas as pd
import rlp

StorageReadMode = Literal["read_not_written", "all_xatu_reads", "none"]
TouchedAccountMode = Literal["balance_reads", "address_appearances", "none"]


@dataclass(frozen=True)
class XatuBalSummary:
    block_number: int
    read_mode: StorageReadMode
    touched_account_mode: TouchedAccountMode
    calldata_bytes: int
    bal_rlp_bytes: int
    bandwidth_rlp_bytes: int
    accounts: int
    storage_write_slots: int
    storage_write_changes: int
    storage_reads: int
    balance_changes: int
    nonce_changes: int
    code_changes: int
    code_bytes: int
    storage_writes_rlp_bytes: int
    storage_reads_rlp_bytes: int
    balance_changes_rlp_bytes: int
    nonce_changes_rlp_bytes: int
    code_changes_rlp_bytes: int
    account_shell_rlp_bytes: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "block_number": self.block_number,
            "read_mode": self.read_mode,
            "touched_account_mode": self.touched_account_mode,
            "calldata_bytes": self.calldata_bytes,
            "bal_rlp_bytes": self.bal_rlp_bytes,
            "bandwidth_rlp_bytes": self.bandwidth_rlp_bytes,
            "accounts": self.accounts,
            "storage_write_slots": self.storage_write_slots,
            "storage_write_changes": self.storage_write_changes,
            "storage_reads": self.storage_reads,
            "balance_changes": self.balance_changes,
            "nonce_changes": self.nonce_changes,
            "code_changes": self.code_changes,
            "code_bytes": self.code_bytes,
            "storage_writes_rlp_bytes": self.storage_writes_rlp_bytes,
            "storage_reads_rlp_bytes": self.storage_reads_rlp_bytes,
            "balance_changes_rlp_bytes": self.balance_changes_rlp_bytes,
            "nonce_changes_rlp_bytes": self.nonce_changes_rlp_bytes,
            "code_changes_rlp_bytes": self.code_changes_rlp_bytes,
            "account_shell_rlp_bytes": self.account_shell_rlp_bytes,
        }


@dataclass(frozen=True)
class XatuBalResult:
    block_number: int
    read_mode: StorageReadMode
    touched_account_mode: TouchedAccountMode
    accounts: list[list]
    rlp_bytes: bytes
    calldata_bytes: int
    summary: XatuBalSummary


def _strip_0x(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, bytes):
        value = value.decode()
    text = str(value).lower()
    return text[2:] if text.startswith("0x") else text


def hex_to_bytes(value: object, length: int | None = None) -> bytes:
    text = _strip_0x(value)
    if len(text) % 2:
        text = "0" + text
    raw = bytes.fromhex(text) if text else b""
    if length is None:
        return raw
    if len(raw) > length:
        raw = raw[-length:]
    return raw.rjust(length, b"\x00")


def canonical_address(value: object) -> str:
    return "0x" + hex_to_bytes(value, 20).hex()


def canonical_slot(value: object) -> str:
    return "0x" + hex_to_bytes(value, 32).hex()


def hex_quantity_to_int(value: object) -> int:
    if value is None or pd.isna(value):
        return 0
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, str):
        text = value.strip().lower()
        return int(text, 16) if text.startswith("0x") else int(text)
    return int(value)


def _empty_frame(columns: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _frame_with_columns(frame: pd.DataFrame | None, columns: Iterable[str]) -> pd.DataFrame:
    expected = list(columns)
    if frame is None or frame.empty:
        return _empty_frame(expected)
    return frame.copy().reindex(columns=expected)


def query_xatu_bal_frames(client, block_number: int, network: str = "mainnet") -> dict[str, pd.DataFrame]:
    """Query Xatu tables needed to construct a block-level BAL.

    Joins are intentionally done in pandas because public ClickHouse commonly
    disallows double-distributed joins.
    """

    params = {"network": network, "block": int(block_number)}

    block_roots = client.query_df(
        """
        SELECT block_root
        FROM default.canonical_beacon_block FINAL
        WHERE meta_network_name = {network:String}
          AND execution_payload_block_number = {block:UInt64}
        """,
        parameters=params,
    )
    if block_roots.empty:
        txs = _empty_frame(["position", "hash", "call_data_size"])
    else:
        roots = [row.decode() if isinstance(row, bytes) else row for row in block_roots["block_root"]]
        txs = client.query_df(
            """
            SELECT
                position,
                hash,
                call_data_size
            FROM default.canonical_beacon_block_execution_transaction FINAL
            WHERE meta_network_name = {network:String}
              AND block_root IN {roots:Array(FixedString(66))}
            ORDER BY position
            """,
            parameters={"network": network, "roots": roots},
        )

    storage_diffs = client.query_df(
        """
        SELECT
            transaction_index,
            internal_index,
            lower(address) AS address,
            lower(slot) AS slot,
            lower(to_value) AS to_value
        FROM default.canonical_execution_storage_diffs FINAL
        WHERE meta_network_name = {network:String}
          AND block_number = {block:UInt64}
        ORDER BY address, slot, transaction_index, internal_index
        """,
        parameters=params,
    )

    storage_reads = client.query_df(
        """
        SELECT
            transaction_index,
            internal_index,
            lower(contract_address) AS address,
            lower(slot) AS slot
        FROM default.canonical_execution_storage_reads FINAL
        WHERE meta_network_name = {network:String}
          AND block_number = {block:UInt64}
        ORDER BY address, slot, transaction_index, internal_index
        """,
        parameters=params,
    )

    balance_diffs = client.query_df(
        """
        SELECT
            transaction_index,
            internal_index,
            lower(address) AS address,
            to_value
        FROM default.canonical_execution_balance_diffs FINAL
        WHERE meta_network_name = {network:String}
          AND block_number = {block:UInt64}
        ORDER BY address, transaction_index, internal_index
        """,
        parameters=params,
    )

    balance_reads = client.query_df(
        """
        SELECT DISTINCT lower(address) AS address
        FROM default.canonical_execution_balance_reads FINAL
        WHERE meta_network_name = {network:String}
          AND block_number = {block:UInt64}
        ORDER BY address
        """,
        parameters=params,
    )

    nonce_diffs = client.query_df(
        """
        SELECT
            transaction_index,
            internal_index,
            lower(address) AS address,
            to_value
        FROM default.canonical_execution_nonce_diffs FINAL
        WHERE meta_network_name = {network:String}
          AND block_number = {block:UInt64}
        ORDER BY address, transaction_index, internal_index
        """,
        parameters=params,
    )

    contracts = client.query_df(
        """
        SELECT
            transaction_hash,
            internal_index,
            create_index,
            lower(contract_address) AS address,
            lower(code) AS code,
            n_code_bytes
        FROM default.canonical_execution_contracts FINAL
        WHERE meta_network_name = {network:String}
          AND block_number = {block:UInt64}
        ORDER BY address, internal_index, create_index
        """,
        parameters=params,
    )

    address_appearances = client.query_df(
        """
        SELECT DISTINCT lower(address) AS address
        FROM default.canonical_execution_address_appearances FINAL
        WHERE meta_network_name = {network:String}
          AND block_number = {block:UInt64}
        ORDER BY address
        """,
        parameters=params,
    )

    if not txs.empty:
        txs["hash"] = txs["hash"].map(lambda h: h.decode() if isinstance(h, bytes) else str(h))
    if not contracts.empty:
        contracts["transaction_hash"] = contracts["transaction_hash"].map(
            lambda h: h.decode() if isinstance(h, bytes) else str(h)
        )
    if not contracts.empty and not txs.empty:
        tx_index = txs[["hash", "position"]].rename(
            columns={"hash": "transaction_hash", "position": "transaction_index"}
        )
        contracts = contracts.merge(tx_index, on="transaction_hash", how="left")
    elif not contracts.empty:
        contracts["transaction_index"] = pd.NA

    return {
        "txs": txs,
        "storage_diffs": storage_diffs,
        "storage_reads": storage_reads,
        "balance_diffs": balance_diffs,
        "balance_reads": balance_reads,
        "nonce_diffs": nonce_diffs,
        "contracts": contracts,
        "address_appearances": address_appearances,
    }


def build_bal_from_frames(
    *,
    block_number: int,
    frames: dict[str, pd.DataFrame],
    read_mode: StorageReadMode = "read_not_written",
    touched_account_mode: TouchedAccountMode = "balance_reads",
) -> XatuBalResult:
    storage_diffs = _frame_with_columns(
        frames.get("storage_diffs"),
        ["transaction_index", "internal_index", "address", "slot", "to_value"],
    )
    storage_reads = _frame_with_columns(
        frames.get("storage_reads"),
        ["transaction_index", "internal_index", "address", "slot"],
    )
    balance_diffs = _frame_with_columns(
        frames.get("balance_diffs"),
        ["transaction_index", "internal_index", "address", "to_value"],
    )
    balance_reads = _frame_with_columns(frames.get("balance_reads"), ["address"])
    nonce_diffs = _frame_with_columns(
        frames.get("nonce_diffs"),
        ["transaction_index", "internal_index", "address", "to_value"],
    )
    contracts = _frame_with_columns(
        frames.get("contracts"),
        ["transaction_index", "internal_index", "create_index", "address", "code", "n_code_bytes"],
    )
    address_appearances = _frame_with_columns(frames.get("address_appearances"), ["address"])
    txs = _frame_with_columns(frames.get("txs"), ["call_data_size"])

    for frame in [storage_diffs, storage_reads, balance_diffs, balance_reads, nonce_diffs, contracts, address_appearances]:
        if "address" in frame.columns and not frame.empty:
            frame["address"] = frame["address"].map(canonical_address)
    for frame in [storage_diffs, storage_reads]:
        if "slot" in frame.columns and not frame.empty:
            frame["slot"] = frame["slot"].map(canonical_slot)

    written_slots = set()
    if not storage_diffs.empty:
        written_slots = set(zip(storage_diffs["address"], storage_diffs["slot"]))

    read_slots = set()
    if read_mode != "none" and not storage_reads.empty:
        read_slots = set(zip(storage_reads["address"], storage_reads["slot"]))
        if read_mode == "read_not_written":
            read_slots -= written_slots

    touched_accounts: set[str] = set()
    if touched_account_mode == "balance_reads" and not balance_reads.empty:
        touched_accounts.update(balance_reads["address"])
    elif touched_account_mode == "address_appearances" and not address_appearances.empty:
        touched_accounts.update(address_appearances["address"])

    account_addresses = set(touched_accounts)
    for frame in [storage_diffs, balance_diffs, nonce_diffs, contracts]:
        if not frame.empty:
            account_addresses.update(frame["address"])
    account_addresses.update(address for address, _ in read_slots)

    accounts = []
    for address in sorted(account_addresses, key=lambda addr: hex_to_bytes(addr, 20)):
        storage_writes = []
        account_writes = storage_diffs[storage_diffs["address"] == address]
        if not account_writes.empty:
            for slot, slot_rows in account_writes.groupby("slot", sort=True):
                changes = []
                for _, row in slot_rows.sort_values(["transaction_index", "internal_index"]).iterrows():
                    changes.append(
                        [
                            int(row["transaction_index"]),
                            hex_to_bytes(row["to_value"], 32),
                        ]
                    )
                storage_writes.append([hex_to_bytes(slot, 32), changes])
            storage_writes.sort(key=lambda item: item[0])

        storage_read_list = sorted(
            [hex_to_bytes(slot, 32) for read_address, slot in read_slots if read_address == address]
        )

        account_balance = balance_diffs[balance_diffs["address"] == address]
        balance_changes = []
        if not account_balance.empty:
            for _, row in account_balance.sort_values(["transaction_index", "internal_index"]).iterrows():
                balance_changes.append(
                    [int(row["transaction_index"]), hex_quantity_to_int(row["to_value"])]
                )

        account_nonce = nonce_diffs[nonce_diffs["address"] == address]
        nonce_changes = []
        if not account_nonce.empty:
            for _, row in account_nonce.sort_values(["transaction_index", "internal_index"]).iterrows():
                nonce_changes.append([int(row["transaction_index"]), hex_quantity_to_int(row["to_value"])])

        account_code = contracts[contracts["address"] == address]
        code_changes = []
        if not account_code.empty:
            for _, row in account_code.sort_values(["transaction_index", "internal_index", "create_index"]).iterrows():
                tx_index = row.get("transaction_index")
                if pd.isna(tx_index):
                    raise ValueError(f"Missing tx index for code change at {address}")
                code_changes.append([int(tx_index), hex_to_bytes(row["code"])])

        accounts.append(
            [
                hex_to_bytes(address, 20),
                storage_writes,
                storage_read_list,
                balance_changes,
                nonce_changes,
                code_changes,
            ]
        )

    encoded = rlp.encode(accounts)
    calldata_bytes = int(txs["call_data_size"].fillna(0).sum()) if "call_data_size" in txs else 0
    summary = summarize_bal(
        block_number=block_number,
        accounts=accounts,
        encoded=encoded,
        calldata_bytes=calldata_bytes,
        read_mode=read_mode,
        touched_account_mode=touched_account_mode,
    )
    return XatuBalResult(
        block_number=block_number,
        read_mode=read_mode,
        touched_account_mode=touched_account_mode,
        accounts=accounts,
        rlp_bytes=encoded,
        calldata_bytes=calldata_bytes,
        summary=summary,
    )


def summarize_bal(
    *,
    block_number: int,
    accounts: list[list],
    encoded: bytes,
    calldata_bytes: int,
    read_mode: StorageReadMode,
    touched_account_mode: TouchedAccountMode,
) -> XatuBalSummary:
    storage_writes_rlp_bytes = 0
    storage_reads_rlp_bytes = 0
    balance_changes_rlp_bytes = 0
    nonce_changes_rlp_bytes = 0
    code_changes_rlp_bytes = 0
    storage_write_slots = 0
    storage_write_changes = 0
    storage_reads = 0
    balance_changes = 0
    nonce_changes = 0
    code_changes = 0
    code_bytes = 0

    for account in accounts:
        _, writes, reads, balances, nonces, codes = account
        if writes:
            storage_writes_rlp_bytes += len(rlp.encode(writes))
            storage_write_slots += len(writes)
            storage_write_changes += sum(len(changes) for _, changes in writes)
        if reads:
            storage_reads_rlp_bytes += len(rlp.encode(reads))
            storage_reads += len(reads)
        if balances:
            balance_changes_rlp_bytes += len(rlp.encode(balances))
            balance_changes += len(balances)
        if nonces:
            nonce_changes_rlp_bytes += len(rlp.encode(nonces))
            nonce_changes += len(nonces)
        if codes:
            code_changes_rlp_bytes += len(rlp.encode(codes))
            code_changes += len(codes)
            code_bytes += sum(len(code) for _, code in codes)

    component_bytes = (
        storage_writes_rlp_bytes
        + storage_reads_rlp_bytes
        + balance_changes_rlp_bytes
        + nonce_changes_rlp_bytes
        + code_changes_rlp_bytes
    )
    account_shell_rlp_bytes = len(encoded) - component_bytes

    return XatuBalSummary(
        block_number=block_number,
        read_mode=read_mode,
        touched_account_mode=touched_account_mode,
        calldata_bytes=calldata_bytes,
        bal_rlp_bytes=len(encoded),
        bandwidth_rlp_bytes=calldata_bytes + len(encoded),
        accounts=len(accounts),
        storage_write_slots=storage_write_slots,
        storage_write_changes=storage_write_changes,
        storage_reads=storage_reads,
        balance_changes=balance_changes,
        nonce_changes=nonce_changes,
        code_changes=code_changes,
        code_bytes=code_bytes,
        storage_writes_rlp_bytes=storage_writes_rlp_bytes,
        storage_reads_rlp_bytes=storage_reads_rlp_bytes,
        balance_changes_rlp_bytes=balance_changes_rlp_bytes,
        nonce_changes_rlp_bytes=nonce_changes_rlp_bytes,
        code_changes_rlp_bytes=code_changes_rlp_bytes,
        account_shell_rlp_bytes=account_shell_rlp_bytes,
    )


def build_xatu_bal_for_block(
    client,
    block_number: int,
    network: str = "mainnet",
    read_mode: StorageReadMode = "read_not_written",
    touched_account_mode: TouchedAccountMode = "balance_reads",
) -> XatuBalResult:
    frames = query_xatu_bal_frames(client, block_number=block_number, network=network)
    return build_bal_from_frames(
        block_number=block_number,
        frames=frames,
        read_mode=read_mode,
        touched_account_mode=touched_account_mode,
    )
