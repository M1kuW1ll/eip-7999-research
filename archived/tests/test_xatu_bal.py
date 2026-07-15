import unittest
from pathlib import Path
import sys

import pandas as pd
import rlp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xatu_bal import build_bal_from_frames


class XatuBalBuilderTest(unittest.TestCase):
    def test_builds_account_grouped_rlp_and_filters_written_reads(self):
        address = "0x" + "11" * 20
        slot_written = "0x" + "aa" * 32
        slot_read = "0x" + "bb" * 32
        value = "0x" + "01" * 32

        frames = {
            "txs": pd.DataFrame([{"position": 0, "hash": "0x1", "call_data_size": 7}]),
            "storage_diffs": pd.DataFrame(
                [
                    {
                        "transaction_index": 0,
                        "internal_index": 0,
                        "address": address,
                        "slot": slot_written,
                        "to_value": value,
                    }
                ]
            ),
            "storage_reads": pd.DataFrame(
                [
                    {
                        "transaction_index": 0,
                        "internal_index": 0,
                        "address": address,
                        "slot": slot_written,
                    },
                    {
                        "transaction_index": 0,
                        "internal_index": 1,
                        "address": address,
                        "slot": slot_read,
                    },
                ]
            ),
            "balance_diffs": pd.DataFrame(
                [
                    {
                        "transaction_index": 0,
                        "internal_index": 0,
                        "address": address,
                        "to_value": 9,
                    }
                ]
            ),
            "balance_reads": pd.DataFrame([{"address": address}]),
            "nonce_diffs": pd.DataFrame(
                [
                    {
                        "transaction_index": 0,
                        "internal_index": 0,
                        "address": address,
                        "to_value": 2,
                    }
                ]
            ),
            "contracts": pd.DataFrame(),
            "address_appearances": pd.DataFrame(),
        }

        result = build_bal_from_frames(block_number=1, frames=frames)
        decoded = rlp.decode(result.rlp_bytes)

        self.assertEqual(len(decoded), 1)
        account = decoded[0]
        self.assertEqual(len(account), 6)
        self.assertEqual(len(account[1]), 1)
        self.assertEqual(len(account[2]), 1)
        self.assertEqual(result.summary.storage_reads, 1)
        self.assertEqual(result.summary.storage_write_changes, 1)
        self.assertEqual(result.summary.balance_changes, 1)
        self.assertEqual(result.summary.nonce_changes, 1)
        self.assertEqual(result.summary.calldata_bytes, 7)
        self.assertEqual(
            result.summary.bandwidth_rlp_bytes,
            result.summary.bal_rlp_bytes + 7,
        )


if __name__ == "__main__":
    unittest.main()
