import unittest

import rlp

from sim.rpc_bal import build_rpc_bal_from_traces


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


if __name__ == "__main__":
    unittest.main()
