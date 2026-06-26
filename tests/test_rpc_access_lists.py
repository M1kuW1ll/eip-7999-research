from sim.rpc_access_lists import (
    ACCESS_LIST_DATA_GAS_PER_BYTE,
    access_list_bytes,
    decode_access_list_transaction_record,
    summarize_access_lists_by_block,
)


def test_access_list_bytes_uses_eip7981_units():
    assert access_list_bytes(address_count=1, storage_key_count=2) == 20 + 2 * 32


def test_decode_access_list_transaction_record_counts_addresses_and_keys():
    record = decode_access_list_transaction_record(
        block_number=1,
        tx_index=0,
        tx={
            "hash": "0xabc",
            "type": "0x2",
            "accessList": [
                {
                    "address": "0x1111111111111111111111111111111111111111",
                    "storageKeys": ["0x" + "22" * 32, "0x" + "33" * 32],
                },
                {
                    "address": "0x4444444444444444444444444444444444444444",
                    "storageKeys": [],
                },
            ],
        },
    )

    assert record.access_list_address_count == 2
    assert record.access_list_storage_key_count == 2
    assert record.access_list_bytes == 2 * 20 + 2 * 32
    assert record.access_list_gas == record.access_list_bytes * ACCESS_LIST_DATA_GAS_PER_BYTE


def test_summarize_access_lists_by_block_fills_empty_blocks():
    records = [
        decode_access_list_transaction_record(
            block_number=10,
            tx_index=0,
            tx={
                "hash": "0xabc",
                "type": "0x1",
                "accessList": [
                    {
                        "address": "0x1111111111111111111111111111111111111111",
                        "storageKeys": ["0x" + "22" * 32],
                    }
                ],
            },
        ).as_dict(),
        decode_access_list_transaction_record(
            block_number=10,
            tx_index=1,
            tx={
                "hash": "0xdef",
                "type": "0x2",
                "accessList": [],
            },
        ).as_dict(),
    ]

    import pandas as pd

    summary = summarize_access_lists_by_block(pd.DataFrame(records), [10, 11])

    first = summary[summary["block_number"] == 10].iloc[0]
    second = summary[summary["block_number"] == 11].iloc[0]
    assert first["tx_access_list_tx_count"] == 1
    assert first["tx_access_list_address_count"] == 1
    assert first["tx_access_list_storage_key_count"] == 1
    assert first["tx_access_list_bytes"] == 20 + 32
    assert first["tx_access_list_gas"] == (20 + 32) * 64
    assert second["tx_access_list_tx_count"] == 0
    assert second["tx_access_list_bytes"] == 0
