import pandas as pd
import pytest

from shared_fee.calibration import estimate_data_multiplier
from shared_fee.floor_accounting import (
    ACCESS_LIST_ADDRESS_COST_8038,
    ACCESS_LIST_STORAGE_KEY_COST_8038,
    ACCOUNT_WRITE_8038,
    COLD_ACCOUNT_ACCESS_8038,
    COLD_STORAGE_ACCESS_8038,
    CREATE_ACCESS_8038,
    STORAGE_CLEAR_REFUND_8038,
    STORAGE_WRITE_8038,
    eip2780_floor_base,
    eip8131_content_bytes,
    eip8131_floor_gas,
    eip8279_floor_gas,
    incremental_eip8279_uplift,
)


def test_eip8038_access_and_write_schedule():
    assert COLD_ACCOUNT_ACCESS_8038 == 3_000
    assert COLD_STORAGE_ACCESS_8038 == 2_100
    assert STORAGE_WRITE_8038 == 10_000
    assert ACCOUNT_WRITE_8038 == 9_000
    assert CREATE_ACCESS_8038 == 12_000
    assert ACCESS_LIST_ADDRESS_COST_8038 == 2_900
    assert ACCESS_LIST_STORAGE_KEY_COST_8038 == 2_000
    assert STORAGE_CLEAR_REFUND_8038 == 11_616
    assert 32 * 64 < COLD_STORAGE_ACCESS_8038 < 32 * 82


def test_eip2780_floor_base_reference_transactions():
    assert eip2780_floor_base(has_recipient=True, self_transfer=True) == 12_000
    assert eip2780_floor_base(has_recipient=True) == 15_000
    assert eip2780_floor_base(has_recipient=True, transfers_value=True) == 21_000
    assert eip2780_floor_base(has_recipient=False) == 24_000
    assert (
        eip2780_floor_base(has_recipient=True, authorization_count=2)
        == 15_000 + 2 * 7_816
    )


def test_eip8131_content_bytes_uses_fixed_protocol_counts():
    assert (
        eip8131_content_bytes(
            calldata_bytes=10,
            access_list_addresses=2,
            access_list_storage_keys=3,
            authorization_count=1,
            blob_versioned_hash_count=6,
        )
        == 10 + 2 * 20 + 3 * 32 + 108 + 6 * 32
    )


def test_eip8279_adds_static_auth_bal_and_runtime_bytes():
    base = 15_000
    content = 108
    assert eip8131_floor_gas(
        intrinsic_execution_base=base, content_bytes=content
    ) == base + 64 * 108
    assert eip8279_floor_gas(
        intrinsic_execution_base=base,
        content_bytes_8131=content,
        authorization_count=1,
        runtime_bal_bytes=32,
    ) == base + 64 * (108 + 51 + 32)


def test_incremental_uplift_respects_max_operator():
    comparison = incremental_eip8279_uplift(
        execution_gas_used=25_000,
        intrinsic_execution_base=15_000,
        content_bytes_8131=100,
        runtime_bal_bytes=100,
    )
    assert comparison.eip8131_floor_gas == 21_400
    assert comparison.eip8279_floor_gas == 27_800
    assert comparison.charged_gas_8131 == 25_000
    assert comparison.charged_gas_8279 == 27_800
    assert comparison.incremental_gas_8279 == 2_800


def test_state_gas_cannot_be_passed_to_floor_accounting():
    with pytest.raises(TypeError):
        incremental_eip8279_uplift(
            execution_gas_used=25_000,
            intrinsic_execution_base=15_000,
            content_bytes_8131=100,
            state_gas_used=1_000,
        )


def test_multiplier_is_ratio_of_totals():
    result = estimate_data_multiplier(
        reference_data_gas=pd.Series([1.0, 9.0]),
        counterfactual_data_gas_8131=pd.Series([2.0, 9.0]),
        incremental_gas_8279=pd.Series([0.5, 0.5]),
    )
    assert result.data_multiplier_8131 == pytest.approx(1.1)
    assert result.incremental_multiplier_8279 == pytest.approx(0.1)
    assert result.data_multiplier_8131_8279 == pytest.approx(1.2)
