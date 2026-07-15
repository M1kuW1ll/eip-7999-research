import pandas as pd

from sim.xatu_refunds import recover_eip8038_refunds


def _row(**updates):
    row = {
        "block_number": 1,
        "transaction_hash": "0x01",
        "transaction_type": 2,
        "sstore_count": 1,
        "sstore_gas_current": 2_900,
        "sstore_cold_count": 0,
        "refund_counter_current": 4_800,
        "changed_slots": 1,
        "zero_to_nonzero_slots": 0,
        "original_nonzero_changed": 1,
        "net_cleared_slots": 1,
        "calldata_zero_bytes": 0,
        "calldata_nonzero_bytes": 0,
        "receipt_gas_used": 50_000,
    }
    row.update(updates)
    return row


def test_recovers_clear_and_reset_refunds():
    rows = [
        _row(transaction_hash="clear"),
        _row(
            transaction_hash="zero-reset",
            sstore_count=2,
            sstore_gas_current=20_100,
            refund_counter_current=19_900,
            changed_slots=0,
            original_nonzero_changed=0,
            net_cleared_slots=0,
        ),
        _row(
            transaction_hash="nonzero-reset",
            sstore_count=2,
            sstore_gas_current=3_000,
            refund_counter_current=2_800,
            changed_slots=0,
            original_nonzero_changed=0,
            net_cleared_slots=0,
        ),
        _row(
            transaction_hash="auth-reset",
            transaction_type=4,
            sstore_count=2,
            sstore_gas_current=3_000,
            refund_counter_current=15_300,
            changed_slots=0,
            original_nonzero_changed=0,
            net_cleared_slots=0,
        ),
    ]
    result = recover_eip8038_refunds(pd.DataFrame(rows)).set_index(
        "transaction_hash"
    )

    assert result.loc["clear", "refund_counter_8038"] == 12_480
    assert result.loc["zero-reset", "refund_counter_8038"] == 10_000
    assert result.loc["nonzero-reset", "refund_counter_8038"] == 10_000
    assert result.loc["auth-reset", "refund_counter_8038"] == 22_500
    assert set(result["refund_identification"]) == {"unique"}


def test_marks_calldata_floor_and_current_cap():
    rows = [
        _row(
            transaction_hash="floor",
            calldata_nonzero_bytes=1_000,
            receipt_gas_used=61_000,
        ),
        _row(
            transaction_hash="cap",
            refund_counter_current=19_900,
            sstore_count=2,
            sstore_gas_current=20_100,
            changed_slots=0,
            original_nonzero_changed=0,
            net_cleared_slots=0,
            receipt_gas_used=40_000,
        ),
    ]
    result = recover_eip8038_refunds(pd.DataFrame(rows)).set_index(
        "transaction_hash"
    )

    assert bool(result.loc["floor", "current_7623_floor_proxy"])
    assert result.loc["floor", "current_refund_cap_status"] == "floor-proxied"
    assert result.loc["cap", "current_refund_cap_status"] == "cap-binding"
    assert result.loc["cap", "refund_applied_current"] <= 10_000
