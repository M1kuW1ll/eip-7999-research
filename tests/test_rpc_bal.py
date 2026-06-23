import unittest
from unittest.mock import patch

import rlp

from sim.rpc_bal import (
    BEACON_ROOT_CONTRACT,
    HISTORY_BUFFER_LENGTH,
    HISTORY_CONTRACT,
    build_rpc_bal_from_traces,
    canonical_address,
)


def rlp_int(value):
    return int.from_bytes(value, "big") if value else 0


class RpcBalBuilderTest(unittest.TestCase):
    def test_builds_rlp_bal_from_prestate_traces(self):
        address = "0x" + "11" * 20
        contract = "0x" + "22" * 20
        write_slot = "0x" + "aa" * 32
        read_slot = "0x" + "bb" * 32

        diff_trace = [
            {
                "result": {
                    "pre": {
                        address: {
                            "balance": "0x0a",
                            "nonce": "0x00",
                            "storage": {write_slot: "0x01"},
                        }
                    },
                    "post": {
                        address: {
                            "balance": "0x07",
                            "nonce": "0x01",
                            "storage": {write_slot: "0x02"},
                        },
                        contract: {"code": "0x6000"},
                    },
                }
            }
        ]
        full_trace = [
            {
                "result": {
                    address: {
                        "balance": "0x0a",
                        "storage": {write_slot: "0x01", read_slot: "0x04"},
                    }
                }
            }
        ]
        block_info = {
            "number": "0x1",
            "transactions": [{"from": address, "input": "0xabcdef"}],
        }
        receipts = [{"status": "0x1"}]

        result = build_rpc_bal_from_traces(
            block_number=1,
            diff_trace=diff_trace,
            full_trace=full_trace,
            block_info=block_info,
            receipts=receipts,
            calldata_bytes=3,
            include_reads=True,
        )
        decoded = rlp.decode(result.rlp_bytes)

        self.assertEqual(len(decoded), 2)
        account_by_address = {account[0]: account for account in decoded}
        tx_account = account_by_address[canonical_address(address)]
        storage_change = tx_account[1][0][1][0]
        balance_change = tx_account[3][0]
        nonce_change = tx_account[4][0]

        self.assertEqual(rlp_int(storage_change[0]), 1)
        self.assertEqual(rlp_int(balance_change[0]), 1)
        self.assertEqual(rlp_int(nonce_change[0]), 1)
        self.assertEqual(result.summary.calldata_bytes, 3)
        self.assertEqual(result.summary.storage_write_changes, 1)
        self.assertEqual(result.summary.storage_reads, 1)
        self.assertEqual(result.summary.balance_changes, 1)
        self.assertEqual(result.summary.nonce_changes, 1)
        self.assertEqual(result.summary.code_changes, 1)
        self.assertEqual(result.summary.code_bytes, 2)
        self.assertEqual(
            result.summary.bandwidth_rlp_bytes,
            result.summary.bal_rlp_bytes + 3,
        )

    def test_system_changes_use_eip7928_pre_and_post_indices(self):
        withdrawal_address = "0x" + "33" * 20
        block_number = 12_345
        timestamp = 1_234_567
        parent_beacon_root = "0x" + "44" * 32
        parent_hash = "0x" + "55" * 32

        block_info = {
            "number": hex(block_number),
            "timestamp": hex(timestamp),
            "transactions": [{"hash": "0x1"}, {"hash": "0x2"}],
            "parentBeaconBlockRoot": parent_beacon_root,
            "parentHash": parent_hash,
            "withdrawals": [
                {
                    "address": withdrawal_address,
                    "amount": "0x2",
                }
            ],
        }

        with patch("sim.rpc_bal.rpc_call", return_value="0x0"):
            result = build_rpc_bal_from_traces(
                block_number=block_number,
                diff_trace=[],
                full_trace=None,
                block_info=block_info,
                receipts=[],
                calldata_bytes=0,
                rpc_url="unused",
                include_reads=True,
                include_system_changes=True,
            )

        account_by_address = {account[0]: account for account in rlp.decode(result.rlp_bytes)}
        beacon_account = account_by_address[canonical_address(BEACON_ROOT_CONTRACT)]
        history_account = account_by_address[canonical_address(HISTORY_CONTRACT)]
        withdrawal_account = account_by_address[canonical_address(withdrawal_address)]

        beacon_slots = {slot: changes for slot, changes in beacon_account[1]}
        timestamp_slot = (timestamp % HISTORY_BUFFER_LENGTH).to_bytes(32, "big")
        root_slot = (timestamp % HISTORY_BUFFER_LENGTH + HISTORY_BUFFER_LENGTH).to_bytes(
            32, "big"
        )
        self.assertEqual(set(beacon_slots), {timestamp_slot, root_slot})
        self.assertTrue(all(rlp_int(changes[0][0]) == 0 for changes in beacon_slots.values()))

        history_slot, history_changes = history_account[1][0]
        self.assertEqual(
            history_slot,
            ((block_number - 1) % HISTORY_BUFFER_LENGTH).to_bytes(32, "big"),
        )
        self.assertEqual(rlp_int(history_changes[0][0]), 0)

        withdrawal_change = withdrawal_account[3][0]
        self.assertEqual(rlp_int(withdrawal_change[0]), 3)
        self.assertEqual(rlp_int(withdrawal_change[1]), 2 * 10**9)


if __name__ == "__main__":
    unittest.main()
