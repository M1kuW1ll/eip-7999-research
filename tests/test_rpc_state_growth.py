from sim.rpc_state_growth import summarize_rpc_state_growth_from_traces


def test_summarize_rpc_state_growth_counts_eip8037_components():
    delegation_code = "0xef0100" + "11" * 20
    diff_trace = [
        {
            "result": {
                "pre": {
                    "0x1000000000000000000000000000000000000000": {
                        "code": "0x60",
                        "storage": {},
                    }
                },
                "post": {
                    "0x1000000000000000000000000000000000000000": {
                        "storage": {
                            "0x" + "00" * 31 + "01": "0x01",
                        }
                    }
                },
            }
        },
        {
            "result": {
                "pre": {},
                "post": {
                    "0x2000000000000000000000000000000000000000": {
                        "code": "0x60016002",
                    }
                },
            }
        },
        {
            "result": {
                "pre": {},
                "post": {
                    "0x3000000000000000000000000000000000000000": {
                        "code": delegation_code,
                    }
                },
            }
        },
        {
            "result": {
                "pre": {},
                "post": {
                    "0x4000000000000000000000000000000000000000": {
                        "balance": "0x01",
                    }
                },
            }
        },
    ]
    receipts = [
        {"status": "0x1"},
        {"status": "0x1"},
        {"status": "0x1"},
        {"status": "0x0"},
    ]

    summary = summarize_rpc_state_growth_from_traces(
        block_number=123,
        diff_trace=diff_trace,
        receipts=receipts,
        cpsb=1530,
    )

    assert summary.new_storage_slots == 1
    assert summary.storage_slot_state_bytes == 64
    assert summary.storage_slot_state_gas == 64 * 1530
    assert summary.new_accounts == 2
    assert summary.new_account_state_bytes == 2 * 120
    assert summary.new_account_state_gas == 2 * 120 * 1530
    assert summary.code_bytes == 4
    assert summary.code_deposit_state_bytes == 4
    assert summary.code_deposit_state_gas == 4 * 1530
    assert summary.new_delegation_indicators == 1
    assert summary.delegation_indicator_state_bytes == 23
    assert summary.delegation_indicator_state_gas == 23 * 1530
    assert summary.state_bytes_equivalent == 64 + 2 * 120 + 4 + 23
    assert summary.state_gas_used == summary.state_bytes_equivalent * 1530
