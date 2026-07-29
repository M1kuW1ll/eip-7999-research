import pandas as pd
import pytest

import sim.rpc_static_data as static_data


def _full_transaction(*, tx_hash: str = "0xabc", tx_index: int = 0):
    return {
        "blockNumber": "0xa",
        "transactionIndex": hex(tx_index),
        "hash": tx_hash,
        "type": "0x4",
        "input": "0x00010203",
        "accessList": [
            {
                "address": "0x" + "11" * 20,
                "storageKeys": ["0x" + "22" * 32, "0x" + "33" * 32],
            },
            {"address": "0x" + "44" * 20, "storageKeys": []},
        ],
        "authorizationList": [{}, {}],
        "blobVersionedHashes": ["0x" + "01" * 32],
    }


def test_decode_static_data_transaction_includes_every_static_component():
    record = static_data.decode_static_data_transaction_record(
        block_number=10,
        tx_index=0,
        tx=_full_transaction(),
    )

    access_bytes = 2 * 20 + 2 * 32
    authorization_bytes = 2 * 108
    blob_hash_bytes = 32
    expected = 4 + access_bytes + authorization_bytes + blob_hash_bytes

    assert record.calldata_bytes == 4
    assert record.access_list_address_count == 2
    assert record.access_list_storage_key_count == 2
    assert record.access_list_bytes == access_bytes
    assert record.authorization_tuple_count == 2
    assert record.authorization_tuple_bytes == authorization_bytes
    assert record.blob_versioned_hash_count == 1
    assert record.blob_versioned_hash_bytes == blob_hash_bytes
    assert record.static_data_bytes == expected
    assert record.static_data_gas == 16 * expected


def test_decode_static_data_transaction_rejects_position_mismatch():
    with pytest.raises(ValueError, match="index"):
        static_data.decode_static_data_transaction_record(
            block_number=10,
            tx_index=1,
            tx=_full_transaction(tx_index=0),
        )


def test_fetch_static_data_uses_one_full_block_call_per_block(monkeypatch):
    calls = []

    def fake_rpc_call(url, method, params, timeout, headers):
        calls.append((url, method, params, timeout, headers))
        block_number = int(params[0], 16)
        return {
            "number": params[0],
            "transactions": [
                {
                    **_full_transaction(
                        tx_hash=f"0x{block_number:064x}", tx_index=0
                    ),
                    "blockNumber": params[0],
                }
            ],
        }

    monkeypatch.setattr(static_data, "rpc_call", fake_rpc_call)
    records = static_data.fetch_static_data_records_for_blocks(
        "https://rpc.invalid",
        [11, 10],
        rpc_headers={"X-Test": "1"},
        max_workers=1,
    )

    assert records["block_number"].tolist() == [10, 11]
    assert len(calls) == 2
    assert all(call[1] == "eth_getBlockByNumber" for call in calls)
    assert all(call[2][1] is True for call in calls)


def test_summarize_static_data_retains_requested_empty_blocks():
    record = static_data.decode_static_data_transaction_record(
        block_number=10,
        tx_index=0,
        tx=_full_transaction(),
    ).as_dict()
    summary = static_data.summarize_static_data_by_block(
        pd.DataFrame([record]), [10, 11]
    )

    first, second = summary.iloc[0], summary.iloc[1]
    assert first["transactions"] == 1
    assert first["static_data_8131_bytes"] == record["static_data_8131_bytes"]
    assert first["static_data_gas_7999"] == 16 * record["static_data_8131_bytes"]
    assert second["transactions"] == 0
    assert second["static_data_gas_7999"] == 0
