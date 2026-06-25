"""Pull and decode EIP-7702 authorization lists from JSON-RPC."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import time
from typing import Any

from eth_keys import keys
from eth_utils import keccak
import pandas as pd
import rlp

from .rpc_bal import rpc_call

AUTH_TUPLE_BYTES_8131 = 108
BLOB_VERSIONED_HASH_BYTES_8131 = 32
EIP7702_MAGIC = b"\x05"
MAINNET_CHAIN_ID = 1
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
SECP256K1_N = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
)


@dataclass(frozen=True)
class AuthorizationRecord:
    block_number: int
    tx_index: int
    tx_hash: str
    auth_index: int
    chain_id: int
    target_address: str
    nonce: int
    y_parity: int
    r: int
    s: int
    authority: str | None
    is_clear: bool
    chain_id_valid: bool
    nonce_valid: bool
    signature_low_s: bool
    recovered: bool
    recover_error: str
    authorization_tuple_rlp_bytes: int
    authorization_tuple_8131_bytes: int = AUTH_TUPLE_BYTES_8131

    def as_dict(self) -> dict[str, Any]:
        return {
            "block_number": self.block_number,
            "tx_index": self.tx_index,
            "tx_hash": self.tx_hash,
            "auth_index": self.auth_index,
            "chain_id": self.chain_id,
            "target_address": self.target_address,
            "nonce": self.nonce,
            "y_parity": self.y_parity,
            "r": self.r,
            "s": self.s,
            "authority": self.authority,
            "is_clear": self.is_clear,
            "chain_id_valid": self.chain_id_valid,
            "nonce_valid": self.nonce_valid,
            "signature_low_s": self.signature_low_s,
            "recovered": self.recovered,
            "recover_error": self.recover_error,
            "authorization_tuple_rlp_bytes": self.authorization_tuple_rlp_bytes,
            "authorization_tuple_8131_bytes": self.authorization_tuple_8131_bytes,
        }


def parse_quantity(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    return int(value)


def normalize_hash(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode()
    return str(value)


def hex_to_bytes(value: str | None, length: int | None = None) -> bytes:
    text = "" if value is None else str(value)
    if text.startswith("0x"):
        text = text[2:]
    if len(text) % 2:
        text = "0" + text
    raw = bytes.fromhex(text) if text else b""
    if length is None:
        return raw
    if len(raw) > length:
        raw = raw[-length:]
    return raw.rjust(length, b"\x00")


def normalize_address(value: str) -> str:
    raw = hex_to_bytes(value, 20)
    return "0x" + raw.hex()


def encode_authorization_tuple(auth: dict[str, Any]) -> bytes:
    return rlp.encode(
        [
            parse_quantity(auth.get("chainId")),
            hex_to_bytes(auth.get("address"), 20),
            parse_quantity(auth.get("nonce")),
            parse_quantity(auth.get("yParity", auth.get("y_parity"))),
            parse_quantity(auth.get("r")),
            parse_quantity(auth.get("s")),
        ]
    )


def recover_authority(auth: dict[str, Any]) -> str:
    chain_id = parse_quantity(auth.get("chainId"))
    target_address = hex_to_bytes(auth.get("address"), 20)
    nonce = parse_quantity(auth.get("nonce"))
    y_parity = parse_quantity(auth.get("yParity", auth.get("y_parity")))
    r = parse_quantity(auth.get("r"))
    s = parse_quantity(auth.get("s"))

    message_hash = keccak(EIP7702_MAGIC + rlp.encode([chain_id, target_address, nonce]))
    signature = keys.Signature(vrs=(y_parity, r, s))
    return signature.recover_public_key_from_msg_hash(message_hash).to_checksum_address().lower()


def decode_authorization_record(
    *,
    block_number: int,
    tx_index: int,
    tx_hash: str,
    auth_index: int,
    auth: dict[str, Any],
    network_chain_id: int = MAINNET_CHAIN_ID,
) -> AuthorizationRecord:
    chain_id = parse_quantity(auth.get("chainId"))
    target_address = normalize_address(auth.get("address"))
    nonce = parse_quantity(auth.get("nonce"))
    y_parity = parse_quantity(auth.get("yParity", auth.get("y_parity")))
    r = parse_quantity(auth.get("r"))
    s = parse_quantity(auth.get("s"))

    authority = None
    recover_error = ""
    try:
        authority = recover_authority(auth)
    except Exception as exc:  # pragma: no cover - exact eth_keys errors vary.
        recover_error = str(exc)

    return AuthorizationRecord(
        block_number=int(block_number),
        tx_index=int(tx_index),
        tx_hash=normalize_hash(tx_hash),
        auth_index=int(auth_index),
        chain_id=chain_id,
        target_address=target_address,
        nonce=nonce,
        y_parity=y_parity,
        r=r,
        s=s,
        authority=authority,
        is_clear=target_address == ZERO_ADDRESS,
        chain_id_valid=chain_id in (0, int(network_chain_id)),
        nonce_valid=nonce < 2**64 - 1,
        signature_low_s=s <= SECP256K1_N // 2,
        recovered=authority is not None,
        recover_error=recover_error,
        authorization_tuple_rlp_bytes=len(encode_authorization_tuple(auth)),
    )


def query_xatu_type4_transactions(
    client,
    block_numbers: Sequence[int],
    *,
    network: str = "mainnet",
) -> pd.DataFrame:
    blocks = sorted({int(block) for block in block_numbers})
    if not blocks:
        return pd.DataFrame(columns=["block_number", "tx_index", "tx_hash"])

    out = client.query_df(
        """
        SELECT
            block_number,
            position AS tx_index,
            hash AS tx_hash
        FROM default.execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
          AND type = 4
        ORDER BY block_number, tx_index
        """,
        parameters={"network": network, "blocks": blocks},
    )
    if out.empty:
        return pd.DataFrame(columns=["block_number", "tx_index", "tx_hash"])
    out["tx_hash"] = out["tx_hash"].map(normalize_hash)
    return out


def fetch_authorization_records_for_transactions(
    rpc_url: str,
    transactions: pd.DataFrame,
    *,
    rpc_headers: dict[str, str] | None = None,
    network_chain_id: int = MAINNET_CHAIN_ID,
    max_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for tx in transactions.to_dict("records"):
        tx_hash = normalize_hash(tx["tx_hash"])
        last_error: Exception | None = None
        rpc_tx = None
        for attempt in range(max(1, int(max_retries))):
            try:
                rpc_tx = rpc_call(
                    rpc_url,
                    "eth_getTransactionByHash",
                    [tx_hash],
                    headers=rpc_headers,
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt + 1 < max(1, int(max_retries)):
                    time.sleep(float(retry_sleep_seconds))
        if rpc_tx is None and last_error is not None:
            raise last_error
        if rpc_tx is None:
            raise RuntimeError(f"RPC returned no transaction for {tx_hash}")
        auth_list = rpc_tx.get("authorizationList") or []
        for auth_index, auth in enumerate(auth_list):
            record = decode_authorization_record(
                block_number=int(tx["block_number"]),
                tx_index=int(tx["tx_index"]),
                tx_hash=tx_hash,
                auth_index=auth_index,
                auth=auth,
                network_chain_id=network_chain_id,
            )
            rows.append(record.as_dict())

    return pd.DataFrame(
        rows,
        columns=[
            "block_number",
            "tx_index",
            "tx_hash",
            "auth_index",
            "chain_id",
            "target_address",
            "nonce",
            "y_parity",
            "r",
            "s",
            "authority",
            "is_clear",
            "chain_id_valid",
            "nonce_valid",
            "signature_low_s",
            "recovered",
            "recover_error",
            "authorization_tuple_rlp_bytes",
            "authorization_tuple_8131_bytes",
        ],
    )


def summarize_authorizations_by_block(
    records: pd.DataFrame,
    *,
    block_numbers: Sequence[int],
    type4_transactions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    blocks = sorted({int(block) for block in block_numbers})
    out = pd.DataFrame({"block_number": blocks})

    if type4_transactions is not None and not type4_transactions.empty:
        type4_counts = (
            type4_transactions.groupby("block_number")
            .size()
            .rename("type4_tx_count")
            .reset_index()
        )
        out = out.merge(type4_counts, on="block_number", how="left")
    else:
        out["type4_tx_count"] = 0

    if records.empty:
        out["authorization_tuple_count"] = 0
        out["authorization_tuple_rlp_bytes"] = 0
        out["authorization_tuple_8131_bytes"] = 0
        out["authorization_set_tuple_count"] = 0
        out["authorization_clear_tuple_count"] = 0
        out["authorization_recovered_count"] = 0
        out["authorization_state_upper_bound_authorities"] = 0
    else:
        grouped = records.groupby("block_number")
        summary = grouped.agg(
            authorization_tuple_count=("auth_index", "count"),
            authorization_tuple_rlp_bytes=("authorization_tuple_rlp_bytes", "sum"),
            authorization_tuple_8131_bytes=("authorization_tuple_8131_bytes", "sum"),
            authorization_set_tuple_count=("is_clear", lambda s: int((~s).sum())),
            authorization_clear_tuple_count=("is_clear", "sum"),
            authorization_recovered_count=("recovered", "sum"),
        ).reset_index()

        state_candidates = records[
            records["recovered"]
            & records["chain_id_valid"]
            & records["nonce_valid"]
            & records["signature_low_s"]
            & ~records["is_clear"]
        ]
        if not state_candidates.empty:
            upper_bound = (
                state_candidates.drop_duplicates(["block_number", "authority"])
                .groupby("block_number")
                .size()
                .rename("authorization_state_upper_bound_authorities")
                .reset_index()
            )
            summary = summary.merge(upper_bound, on="block_number", how="left")
        else:
            summary["authorization_state_upper_bound_authorities"] = 0

        out = out.merge(summary, on="block_number", how="left")

    fill_columns = [
        "type4_tx_count",
        "authorization_tuple_count",
        "authorization_tuple_rlp_bytes",
        "authorization_tuple_8131_bytes",
        "authorization_set_tuple_count",
        "authorization_clear_tuple_count",
        "authorization_recovered_count",
        "authorization_state_upper_bound_authorities",
    ]
    for column in fill_columns:
        out[column] = out[column].fillna(0).astype("int64")
    return out.sort_values("block_number").reset_index(drop=True)


def fetch_authorization_data_for_blocks(
    *,
    raw_client,
    rpc_url: str,
    block_numbers: Sequence[int],
    network: str = "mainnet",
    rpc_headers: dict[str, str] | None = None,
    network_chain_id: int = MAINNET_CHAIN_ID,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    type4_transactions = query_xatu_type4_transactions(
        raw_client,
        block_numbers,
        network=network,
    )
    records = fetch_authorization_records_for_transactions(
        rpc_url,
        type4_transactions,
        rpc_headers=rpc_headers,
        network_chain_id=network_chain_id,
    )
    summary = summarize_authorizations_by_block(
        records,
        block_numbers=block_numbers,
        type4_transactions=type4_transactions,
    )
    return records, summary
