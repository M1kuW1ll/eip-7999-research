import pandas as pd

from sim.rpc_calibration import (
    calibration_row_from_block_data,
    sample_blocks_per_day,
)

ZERO32 = "0x" + "00" * 32
ADDR_A = "0x" + "aa" * 20
ADDR_B = "0x" + "bb" * 20
ADDR_C = "0x" + "cc" * 20
ADDR_D = "0x" + "dd" * 20
SLOT_1 = "0x" + "00" * 31 + "01"
SLOT_2 = "0x" + "00" * 31 + "02"


def fake_block_data():
    diff_trace = [
        {
            "result": {
                "pre": {
                    ADDR_A: {"balance": "0x10", "nonce": "0x1"},
                    ADDR_D: {"balance": "0x0", "nonce": "0x5"},
                },
                "post": {
                    ADDR_A: {
                        "balance": "0x5",
                        "nonce": "0x2",
                        "storage": {SLOT_1: "0x" + "00" * 31 + "2a"},
                    },
                    ADDR_B: {"balance": "0x9"},
                    ADDR_C: {"code": "0x600160"},
                    ADDR_D: {
                        "code": "0xef0100" + "ee" * 20,
                        "nonce": "0x6",
                    },
                },
            }
        },
        {
            # Reverted transaction: state effects must not count.
            "result": {
                "pre": {},
                "post": {
                    ADDR_B: {"storage": {SLOT_2: "0x" + "00" * 31 + "07"}},
                },
            }
        },
    ]
    receipts = [{"status": "0x1"}, {"status": "0x0"}]
    block_info = {
        "number": hex(24_500_000),
        "miner": "0x" + "11" * 20,
        "baseFeePerGas": "0x3b9aca00",
        "parentHash": "0x" + "22" * 32,
        "withdrawals": [],
        "transactions": [
            {
                "hash": "0x" + "01" * 32,
                "type": "0x2",
                "from": ADDR_A,
                "input": "0x1234",
                "accessList": [
                    {
                        "address": ADDR_C,
                        "storageKeys": [SLOT_1, SLOT_2],
                    }
                ],
            },
            {
                "hash": "0x" + "02" * 32,
                "type": "0x4",
                "from": ADDR_B,
                "input": "0x",
                "blobVersionedHashes": ["0x" + "03" * 32],
                "authorizationList": [
                    {
                        "chainId": "0x1",
                        "address": ADDR_D,
                        "nonce": "0x6",
                        "yParity": "0x0",
                        "r": "0x1",
                        "s": "0x1",
                    },
                    {
                        "chainId": "0x1",
                        "address": "0x" + "00" * 20,
                        "nonce": "0x1",
                        "yParity": "0x1",
                        "r": "0x2",
                        "s": "0x2",
                    },
                ],
            },
        ],
    }
    return diff_trace, receipts, block_info


def test_calibration_row_combines_state_bal_access_auth():
    diff_trace, receipts, block_info = fake_block_data()

    row = calibration_row_from_block_data(
        block_number=24_500_000,
        diff_trace=diff_trace,
        full_trace=None,
        block_info=block_info,
        receipts=receipts,
        cpsb=1530,
        include_reads=False,
        include_system_changes=True,
        rpc_url="http://unused.invalid",
    )

    # State side (reverted tx excluded; ADDR_D pre-exists via nonce).
    assert row["rpc_new_storage_slots"] == 1
    assert row["rpc_new_accounts"] == 2
    assert row["rpc_code_bytes"] == 3
    assert row["rpc_new_delegation_indicators"] == 1
    expected_bytes = 64 * 1 + 120 * 2 + 3 + 23 * 1
    assert row["rpc_state_bytes_equivalent"] == expected_bytes
    assert row["rpc_state_gas_used"] == expected_bytes * 1530
    assert row["reverted_tx_count"] == 1

    # BAL side: encoded and non-trivial.
    assert row["bal_rlp_bytes"] > 0
    assert row["bal_storage_write_slots"] >= 1
    assert row["bal_accounts"] >= 1

    # Access lists decoded from block_info transactions.
    assert row["tx_access_list_tx_count"] == 1
    assert row["tx_access_list_address_count"] == 1
    assert row["tx_access_list_storage_key_count"] == 2
    assert row["tx_access_list_bytes"] == 20 + 2 * 32
    assert row["tx_access_list_gas_7981"] == (20 + 2 * 32) * 64

    # Authorization tuples counted gross (even on the reverted tx).
    assert row["type4_tx_count"] == 1
    assert row["authorization_tuple_count"] == 2
    assert row["authorization_set_tuple_count"] == 1
    assert row["authorization_clear_tuple_count"] == 1
    assert row["authorization_tuple_8131_bytes"] == 2 * 108

    assert row["calldata_bytes_rpc"] == 2
    assert row["blob_versioned_hash_count"] == 1
    assert row["blob_versioned_hash_bytes"] == 32


def test_calibration_row_can_skip_bal_work():
    diff_trace, receipts, block_info = fake_block_data()

    row = calibration_row_from_block_data(
        block_number=24_500_000,
        diff_trace=diff_trace,
        full_trace=None,
        block_info=block_info,
        receipts=receipts,
        cpsb=1530,
        include_bal=False,
        rpc_url="http://unused.invalid",
    )

    assert row["rpc_new_storage_slots"] == 1
    assert row["tx_access_list_bytes"] == 20 + 2 * 32
    assert row["authorization_tuple_8131_bytes"] == 2 * 108
    assert row["calldata_bytes_rpc"] == 2
    assert "bal_rlp_bytes" not in row


def test_sample_blocks_per_day_is_deterministic_and_in_bounds():
    days = pd.DataFrame(
        [
            {"date": "2026-02-01", "min_block": 1_000, "max_block": 1_099},
            {"date": "2026-02-02", "min_block": 1_100, "max_block": 1_199},
        ]
    )

    plan_a = sample_blocks_per_day(days, n_per_day=10, seed=7)
    plan_b = sample_blocks_per_day(days, n_per_day=10, seed=7)

    pd.testing.assert_frame_equal(plan_a, plan_b)
    assert len(plan_a) == 20
    for day, group in plan_a.groupby("date"):
        assert sorted(group["sample_rank"]) == list(range(10))
        assert group["block_number"].is_unique
        low = int(days.loc[days["date"] == day, "min_block"].iloc[0])
        high = int(days.loc[days["date"] == day, "max_block"].iloc[0])
        assert group["block_number"].between(low, high).all()

    plan_c = sample_blocks_per_day(days, n_per_day=10, seed=8)
    assert not plan_a["block_number"].equals(plan_c["block_number"])


def test_sample_blocks_caps_at_day_size():
    days = pd.DataFrame(
        [{"date": "2026-02-01", "min_block": 1, "max_block": 5}]
    )
    plan = sample_blocks_per_day(days, n_per_day=10, seed=1)
    assert len(plan) == 5
    assert sorted(plan["block_number"]) == [1, 2, 3, 4, 5]


def test_per_tx_bal_attribution():
    from sim.rpc_calibration import per_tx_bal_bytes

    diff_trace, receipts, block_info = fake_block_data()
    per_tx = per_tx_bal_bytes(
        block_number=24_500_000,
        diff_trace=diff_trace,
        full_trace=None,
        block_info=block_info,
        receipts=receipts,
        include_reads=False,
    )
    # Both transactions get an entry; tx 0 touches storage/accounts/code, so
    # it carries more BAL than the reverted tx 1 (whose only committed state
    # is the gas payment).
    assert set(per_tx) == {0, 1}
    assert per_tx[0] > per_tx[1]
    assert per_tx[0] > 0
