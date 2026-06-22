"""Build raw RLP BAL bytes from an Ethereum JSON-RPC endpoint.

This follows the RLP path in nerolation/eth-bal-analysis closely, but keeps the
implementation dependency-light for notebook use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
import rlp

BEACON_ROOT_CONTRACT = "0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02"
HISTORY_CONTRACT = "0x0000F90827F1C53a10cb7A02335B175320002935"
HISTORY_BUFFER_LENGTH = 8191


@dataclass(frozen=True)
class RpcBalSummary:
    block_number: int
    include_reads: bool
    include_system_changes: bool
    calldata_source: str
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

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "block_number": self.block_number,
            "include_reads": self.include_reads,
            "include_system_changes": self.include_system_changes,
            "calldata_source": self.calldata_source,
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
class RpcBalResult:
    block_number: int
    include_reads: bool
    include_system_changes: bool
    accounts: list[list[Any]]
    rlp_bytes: bytes
    summary: RpcBalSummary


class RlpBalBuilder:
    def __init__(self) -> None:
        self.accounts: dict[bytes, dict[str, Any]] = {}

    def _ensure_account(self, address: bytes) -> None:
        if address not in self.accounts:
            self.accounts[address] = {
                "storage_writes": {},
                "storage_reads": set(),
                "balance_changes": [],
                "nonce_changes": [],
                "code_changes": [],
            }

    def add_touched_account(self, address: bytes) -> None:
        self._ensure_account(address)

    def add_storage_write(self, address: bytes, slot: bytes, tx_index: int, new_value: bytes) -> None:
        self._ensure_account(address)
        self.accounts[address]["storage_writes"].setdefault(slot, []).append(
            (int(tx_index), new_value)
        )

    def add_storage_read(self, address: bytes, slot: bytes) -> None:
        self._ensure_account(address)
        self.accounts[address]["storage_reads"].add(slot)

    def add_balance_change(self, address: bytes, tx_index: int, post_balance: int) -> None:
        self._ensure_account(address)
        self.accounts[address]["balance_changes"].append((int(tx_index), int(post_balance)))

    def add_nonce_change(self, address: bytes, tx_index: int, new_nonce: int) -> None:
        self._ensure_account(address)
        self.accounts[address]["nonce_changes"].append((int(tx_index), int(new_nonce)))

    def add_code_change(self, address: bytes, tx_index: int, new_code: bytes) -> None:
        self._ensure_account(address)
        self.accounts[address]["code_changes"].append((int(tx_index), new_code))

    def latest_balance(self, address: bytes) -> int | None:
        account = self.accounts.get(address)
        if not account or not account["balance_changes"]:
            return None
        return max(account["balance_changes"], key=lambda item: item[0])[1]

    def build_accounts(self, include_reads: bool) -> list[list[Any]]:
        accounts = []
        for address in sorted(self.accounts):
            changes = self.accounts[address]
            storage_writes = []
            for slot in sorted(changes["storage_writes"]):
                write_changes = [
                    [tx_index, value]
                    for tx_index, value in sorted(
                        changes["storage_writes"][slot], key=lambda item: item[0]
                    )
                ]
                storage_writes.append([slot, write_changes])

            if include_reads:
                written_slots = set(changes["storage_writes"])
                storage_reads = sorted(
                    slot for slot in changes["storage_reads"] if slot not in written_slots
                )
            else:
                storage_reads = []

            balance_changes = [
                [tx_index, balance]
                for tx_index, balance in sorted(
                    changes["balance_changes"], key=lambda item: item[0]
                )
            ]
            nonce_changes = [
                [tx_index, nonce]
                for tx_index, nonce in sorted(changes["nonce_changes"], key=lambda item: item[0])
            ]
            code_changes = [
                [tx_index, code]
                for tx_index, code in sorted(changes["code_changes"], key=lambda item: item[0])
            ]
            accounts.append(
                [
                    address,
                    storage_writes,
                    storage_reads,
                    balance_changes,
                    nonce_changes,
                    code_changes,
                ]
            )
        return accounts


def rpc_call(rpc_url: str, method: str, params: list[Any], timeout: int = 180) -> Any:
    response = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"RPC error for {method}: {data['error']}")
    return data.get("result")


def fetch_block_trace(rpc_url: str, block_number: int, diff_mode: bool) -> list[dict[str, Any]]:
    return rpc_call(
        rpc_url,
        "debug_traceBlockByNumber",
        [
            hex(block_number),
            {"tracer": "prestateTracer", "tracerConfig": {"diffMode": diff_mode}},
        ],
        timeout=300,
    )


def parse_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    return int(value)


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


def canonical_address(address: str) -> bytes:
    return hex_to_bytes(address.lower(), 20)


def bytes32(value: str | None) -> bytes:
    return hex_to_bytes(value, 32)


def extract_balances(state: dict[str, Any]) -> dict[str, int]:
    balances = {}
    for address, changes in state.items():
        if "balance" in changes:
            balances[address.lower()] = parse_int(changes["balance"])
    return balances


def extract_block_reads(full_trace: list[dict[str, Any]]) -> dict[str, set[str]]:
    reads: dict[str, set[str]] = {}
    for tx_trace in full_trace:
        result = tx_trace.get("result", {})
        if not isinstance(result, dict):
            continue
        for address, account_data in result.items():
            storage = account_data.get("storage", {})
            if storage:
                reads.setdefault(address.lower(), set()).update(
                    slot.lower() for slot in storage
                )
    return reads


def extract_balance_touches(full_trace: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    touches = {}
    for tx_index, tx_trace in enumerate(full_trace):
        result = tx_trace.get("result", {})
        if not isinstance(result, dict):
            continue
        tx_touches = {}
        for address, account_data in result.items():
            if "balance" in account_data:
                tx_touches[address.lower()] = account_data["balance"]
        if tx_touches:
            touches[tx_index] = tx_touches
    return touches


def collect_touched_addresses(diff_trace: list[dict[str, Any]]) -> set[str]:
    touched = set()
    for tx in diff_trace:
        result = tx.get("result")
        if not isinstance(result, dict):
            continue
        for state_key in ["pre", "post"]:
            touched.update(address.lower() for address in result.get(state_key, {}))
    return touched


def process_storage_changes(
    diff_trace: list[dict[str, Any]],
    builder: RlpBalBuilder,
    *,
    block_reads: dict[str, set[str]] | None,
    include_reads: bool,
    reverted_tx_indices: set[int],
) -> None:
    block_writes: dict[str, dict[str, list[tuple[int, str]]]] = {}
    block_read_slots: dict[str, set[str]] = {}

    for tx_index, tx in enumerate(diff_trace):
        result = tx.get("result")
        if not isinstance(result, dict) or tx_index in reverted_tx_indices:
            continue

        pre_state = result.get("pre", {})
        post_state = result.get("post", {})
        for address in set(pre_state) | set(post_state):
            pre_storage = pre_state.get(address, {}).get("storage", {})
            post_storage = post_state.get(address, {}).get("storage", {})
            for slot in set(pre_storage) | set(post_storage):
                pre_value = pre_storage.get(slot)
                post_value = post_storage.get(slot)
                address_key = address.lower()
                slot_key = slot.lower()

                if post_value is not None:
                    if bytes32(pre_value) != bytes32(post_value):
                        block_writes.setdefault(address_key, {}).setdefault(
                            slot_key, []
                        ).append((tx_index, post_value))
                    elif include_reads and slot_key not in block_writes.get(address_key, {}):
                        block_read_slots.setdefault(address_key, set()).add(slot_key)
                elif pre_value is not None and slot not in post_storage:
                    zero_value = "0x" + "00" * 32
                    block_writes.setdefault(address_key, {}).setdefault(slot_key, []).append(
                        (tx_index, zero_value)
                    )

    if include_reads and block_reads is not None:
        for address, read_slots in block_reads.items():
            written_slots = set(block_writes.get(address, {}))
            for slot in read_slots:
                if slot.lower() not in written_slots:
                    block_read_slots.setdefault(address, set()).add(slot.lower())

    for address, slots in block_writes.items():
        canonical = canonical_address(address)
        for slot, writes in slots.items():
            for tx_index, value in writes:
                builder.add_storage_write(canonical, bytes32(slot), tx_index, bytes32(value))

    for address, slots in block_read_slots.items():
        canonical = canonical_address(address)
        for slot in slots:
            builder.add_storage_read(canonical, bytes32(slot))


def process_balance_changes(
    diff_trace: list[dict[str, Any]],
    builder: RlpBalBuilder,
    *,
    touched_addresses: set[str],
    balance_touches: dict[int, dict[str, str]],
    reverted_tx_indices: set[int],
    block_info: dict[str, Any],
    receipts: list[dict[str, Any]],
    include_reads: bool,
) -> None:
    processed_per_tx: dict[int, set[str]] = {}
    transactions = block_info.get("transactions", [])
    fee_recipient = (block_info.get("miner") or block_info.get("feeRecipient") or "").lower()
    base_fee_per_gas = parse_int(block_info.get("baseFeePerGas"), 0)

    for tx_index, tx in enumerate(diff_trace):
        result = tx.get("result")
        if not isinstance(result, dict):
            continue

        if tx_index in reverted_tx_indices:
            processed = set()
            if tx_index < len(receipts) and tx_index < len(transactions):
                receipt = receipts[tx_index]
                tx_info = transactions[tx_index]
                gas_used = parse_int(receipt.get("gasUsed"), 0)
                effective_gas_price = parse_int(
                    receipt.get("effectiveGasPrice", tx_info.get("gasPrice")), 0
                )
                total_gas_fee = gas_used * effective_gas_price
                priority_fee_total = (
                    gas_used * max(effective_gas_price - base_fee_per_gas, 0)
                    if base_fee_per_gas
                    else total_gas_fee
                )
                sender = (tx_info.get("from") or "").lower()
                balance_touches_for_tx = balance_touches.get(tx_index, {})

                if sender:
                    sender_pre = parse_int(balance_touches_for_tx.get(sender), 0)
                    builder.add_balance_change(
                        canonical_address(sender), tx_index, sender_pre - total_gas_fee
                    )
                    touched_addresses.add(sender)
                    processed.add(sender)
                if fee_recipient:
                    fee_pre = parse_int(balance_touches_for_tx.get(fee_recipient), 0)
                    builder.add_balance_change(
                        canonical_address(fee_recipient),
                        tx_index,
                        fee_pre + priority_fee_total,
                    )
                    touched_addresses.add(fee_recipient)
                    processed.add(fee_recipient)
            processed_per_tx[tx_index] = processed
            continue

        pre_state = result.get("pre", {})
        post_state = result.get("post", {})
        pre_balances = extract_balances(pre_state)
        post_balances = extract_balances(post_state)
        pre_addresses = set(pre_balances)
        post_addresses = set(post_balances)
        balance_touches_for_tx = balance_touches.get(tx_index, {})

        balance_delta = {}
        for address in pre_addresses | post_addresses:
            if balance_touches_for_tx and address in balance_touches_for_tx and address not in pre_addresses:
                pre_balance = parse_int(balance_touches_for_tx[address])
            else:
                pre_balance = pre_balances.get(address, 0)
            post_balance = post_balances.get(address, pre_balance)
            if post_balance - pre_balance:
                balance_delta[address] = post_balance - pre_balance

        if balance_touches_for_tx:
            post_addresses.update(balance_touches_for_tx)
        for address in pre_addresses | post_addresses:
            touched_addresses.add(address.lower())

        processed = set()
        for address in balance_delta:
            builder.add_balance_change(
                canonical_address(address),
                tx_index,
                post_balances.get(address, 0),
            )
            processed.add(address.lower())
        processed_per_tx[tx_index] = processed

    if include_reads:
        for tx_index, tx_touches in balance_touches.items():
            processed = processed_per_tx.get(tx_index, set())
            for address in tx_touches:
                if address not in processed:
                    touched_addresses.add(address)
                    builder.add_touched_account(canonical_address(address))


def process_code_changes(
    diff_trace: list[dict[str, Any]],
    builder: RlpBalBuilder,
    *,
    reverted_tx_indices: set[int],
) -> None:
    for tx_index, tx in enumerate(diff_trace):
        result = tx.get("result")
        if not isinstance(result, dict) or tx_index in reverted_tx_indices:
            continue
        pre_state = result.get("pre", {})
        post_state = result.get("post", {})
        for address in set(pre_state) | set(post_state):
            pre_code = pre_state.get(address, {}).get("code")
            post_code = post_state.get(address, {}).get("code")
            if post_code and post_code != "0x" and post_code != pre_code:
                builder.add_code_change(canonical_address(address), tx_index, hex_to_bytes(post_code))


def process_nonce_changes(
    diff_trace: list[dict[str, Any]],
    builder: RlpBalBuilder,
) -> None:
    for tx_index, tx in enumerate(diff_trace):
        result = tx.get("result")
        if not isinstance(result, dict):
            continue
        pre_state = result.get("pre", {})
        post_state = result.get("post", {})
        for address in set(pre_state) | set(post_state):
            pre_nonce = parse_int(pre_state.get(address, {}).get("nonce"), 0)
            post_nonce = parse_int(post_state.get(address, {}).get("nonce"), 0)
            if post_nonce > pre_nonce:
                builder.add_nonce_change(canonical_address(address), tx_index, post_nonce)


def process_system_contract_changes(
    rpc_url: str,
    block_info: dict[str, Any],
    builder: RlpBalBuilder,
    tx_count: int,
) -> None:
    system_tx_index = tx_count
    block_number = parse_int(block_info.get("number"), 0)

    withdrawals = block_info.get("withdrawals", []) or []
    if withdrawals:
        withdrawal_addresses = {withdrawal["address"].lower() for withdrawal in withdrawals}
        parent_balances = {}
        for address in withdrawal_addresses:
            canonical = canonical_address(address)
            if builder.latest_balance(canonical) is None:
                parent_balances[address] = parse_int(
                    rpc_call(
                        rpc_url,
                        "eth_getBalance",
                        [address, hex(block_number - 1)],
                        timeout=60,
                    )
                )
        for withdrawal in withdrawals:
            address = withdrawal["address"].lower()
            amount_wei = parse_int(withdrawal["amount"]) * 10**9
            canonical = canonical_address(address)
            pre_balance = builder.latest_balance(canonical)
            if pre_balance is None:
                pre_balance = parent_balances.get(address, 0)
            builder.add_balance_change(
                canonical,
                system_tx_index,
                pre_balance + amount_wei,
            )

    parent_beacon_root = block_info.get("parentBeaconBlockRoot")
    if parent_beacon_root:
        timestamp = parse_int(block_info.get("timestamp"), 0)
        slot = timestamp % HISTORY_BUFFER_LENGTH
        builder.add_storage_write(
            canonical_address(BEACON_ROOT_CONTRACT),
            slot.to_bytes(32, "big"),
            system_tx_index,
            hex_to_bytes(parent_beacon_root, 32),
        )

    parent_hash = block_info.get("parentHash")
    if parent_hash and block_number > 0:
        builder.add_storage_write(
            canonical_address(HISTORY_CONTRACT),
            (block_number - 1).to_bytes(32, "big"),
            system_tx_index,
            hex_to_bytes(parent_hash, 32),
        )


def summarize_accounts(
    *,
    block_number: int,
    accounts: list[list[Any]],
    rlp_bytes: bytes,
    calldata_bytes: int,
    include_reads: bool,
    include_system_changes: bool,
    calldata_source: str = "xatu",
) -> RpcBalSummary:
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

    return RpcBalSummary(
        block_number=block_number,
        include_reads=include_reads,
        include_system_changes=include_system_changes,
        calldata_source=calldata_source,
        calldata_bytes=calldata_bytes,
        bal_rlp_bytes=len(rlp_bytes),
        bandwidth_rlp_bytes=calldata_bytes + len(rlp_bytes),
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
        account_shell_rlp_bytes=len(rlp_bytes) - component_bytes,
    )


def build_rpc_bal_from_traces(
    *,
    block_number: int,
    diff_trace: list[dict[str, Any]],
    full_trace: list[dict[str, Any]] | None,
    block_info: dict[str, Any],
    receipts: list[dict[str, Any]],
    calldata_bytes: int,
    rpc_url: str | None = None,
    include_reads: bool = True,
    include_system_changes: bool = False,
) -> RpcBalResult:
    builder = RlpBalBuilder()
    reverted_tx_indices = {
        index
        for index, receipt in enumerate(receipts)
        if receipt and receipt.get("status") == "0x0"
    }
    block_reads = extract_block_reads(full_trace or []) if include_reads and full_trace else None
    balance_touches = extract_balance_touches(full_trace or []) if full_trace else {}
    touched_addresses = collect_touched_addresses(diff_trace)

    process_storage_changes(
        diff_trace,
        builder,
        block_reads=block_reads,
        include_reads=include_reads,
        reverted_tx_indices=reverted_tx_indices,
    )
    process_balance_changes(
        diff_trace,
        builder,
        touched_addresses=touched_addresses,
        balance_touches=balance_touches,
        reverted_tx_indices=reverted_tx_indices,
        block_info=block_info,
        receipts=receipts,
        include_reads=include_reads,
    )
    process_code_changes(diff_trace, builder, reverted_tx_indices=reverted_tx_indices)
    process_nonce_changes(diff_trace, builder)

    if include_system_changes:
        if not rpc_url:
            raise ValueError("rpc_url is required when include_system_changes=True")
        process_system_contract_changes(
            rpc_url,
            block_info,
            builder,
            tx_count=len(block_info.get("transactions", [])),
        )

    if include_reads:
        for address in touched_addresses:
            builder.add_touched_account(canonical_address(address))

    accounts = builder.build_accounts(include_reads=include_reads)
    encoded = rlp.encode(accounts)
    summary = summarize_accounts(
        block_number=block_number,
        accounts=accounts,
        rlp_bytes=encoded,
        calldata_bytes=int(calldata_bytes),
        include_reads=include_reads,
        include_system_changes=include_system_changes,
    )
    return RpcBalResult(
        block_number=block_number,
        include_reads=include_reads,
        include_system_changes=include_system_changes,
        accounts=accounts,
        rlp_bytes=encoded,
        summary=summary,
    )


def build_rpc_bal_for_block(
    rpc_url: str,
    block_number: int,
    *,
    calldata_bytes: int,
    include_reads: bool = True,
    include_system_changes: bool = False,
) -> RpcBalResult:
    diff_trace = fetch_block_trace(rpc_url, block_number, diff_mode=True)
    full_trace = fetch_block_trace(rpc_url, block_number, diff_mode=False) if include_reads else None
    receipts = rpc_call(rpc_url, "eth_getBlockReceipts", [hex(block_number)], timeout=120)
    block_info = rpc_call(rpc_url, "eth_getBlockByNumber", [hex(block_number), True], timeout=120)
    return build_rpc_bal_from_traces(
        block_number=block_number,
        diff_trace=diff_trace,
        full_trace=full_trace,
        block_info=block_info,
        receipts=receipts,
        calldata_bytes=calldata_bytes,
        rpc_url=rpc_url,
        include_reads=include_reads,
        include_system_changes=include_system_changes,
    )
