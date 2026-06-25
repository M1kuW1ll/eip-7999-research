import pandas as pd

from sim.rpc_authorizations import (
    AUTH_TUPLE_BYTES_8131,
    decode_authorization_record,
    summarize_authorizations_by_block,
)


SAMPLE_AUTH = {
    "chainId": "0x1",
    "address": "0x0000fb7702036ff9f76044a501ac1aa74cbab16b",
    "nonce": "0x0",
    "yParity": "0x1",
    "r": "0x9cd9b05930fd66f078e7b552680f7317150316c6c7346594fca65207f12062c4",
    "s": "0x512da2ff94e084ceb73dcab4f254ff0eb2859ddd18003f743c3093df0fd9d5da",
}


def test_decode_authorization_recovers_authority_and_sizes_tuple():
    record = decode_authorization_record(
        block_number=24_120_001,
        tx_index=271,
        tx_hash="0xcc1925ecdd9726ba0cffbd8c435e93c1f5a26537f445cf485ad3074869a15430",
        auth_index=0,
        auth=SAMPLE_AUTH,
    )

    assert record.authority == "0x358566d044738c064f3a66f8e55c403c71112e2e"
    assert record.target_address == "0x0000fb7702036ff9f76044a501ac1aa74cbab16b"
    assert record.authorization_tuple_rlp_bytes == 92
    assert record.authorization_tuple_8131_bytes == AUTH_TUPLE_BYTES_8131
    assert record.chain_id_valid
    assert record.nonce_valid
    assert record.signature_low_s
    assert record.recovered


def test_summarize_authorizations_counts_gross_bytes_and_state_upper_bound():
    record = decode_authorization_record(
        block_number=24_120_001,
        tx_index=271,
        tx_hash="0xcc1925ecdd9726ba0cffbd8c435e93c1f5a26537f445cf485ad3074869a15430",
        auth_index=0,
        auth=SAMPLE_AUTH,
    )
    records = pd.DataFrame([record.as_dict()])
    type4 = pd.DataFrame(
        [
            {
                "block_number": 24_120_001,
                "tx_index": 271,
                "tx_hash": "0xcc1925ecdd9726ba0cffbd8c435e93c1f5a26537f445cf485ad3074869a15430",
            }
        ]
    )

    summary = summarize_authorizations_by_block(
        records,
        block_numbers=[24_120_001, 24_120_002],
        type4_transactions=type4,
    )

    first = summary.iloc[0]
    second = summary.iloc[1]
    assert first["type4_tx_count"] == 1
    assert first["authorization_tuple_count"] == 1
    assert first["authorization_tuple_rlp_bytes"] == 92
    assert first["authorization_tuple_8131_bytes"] == 108
    assert first["authorization_state_upper_bound_authorities"] == 1
    assert second["authorization_tuple_count"] == 0
