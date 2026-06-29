from glamsterdam.calldata_floor import (
    access_list_bytes,
    access_list_cost_2930,
    access_list_data_cost_7981,
    calldata_tokens,
    current_7623_floor_gas,
    glamsterdam_7976_floor_gas,
    glamsterdam_regular_gas_from_receipt,
    glamsterdam_regular_gas_tx,
    historical_state_creation_gas,
    standard_calldata_gas,
)


def test_calldata_token_and_floor_math():
    assert calldata_tokens(10, 20) == 90
    assert standard_calldata_gas(10, 20) == 360
    assert current_7623_floor_gas(10, 20) == 900
    assert glamsterdam_7976_floor_gas(10, 20) == 1_920


def test_access_list_costs_include_old_cost_and_7981_data_surcharge():
    assert access_list_bytes(1, 2) == 84
    assert access_list_cost_2930(1, 2) == 2_400 + 2 * 1_900
    assert access_list_data_cost_7981(1, 2) == 84 * 64


def test_historical_state_creation_gas_uses_existing_08_convention():
    assert historical_state_creation_gas(
        new_storage_slots=1,
        new_accounts=2,
        code_bytes=3,
        new_delegation_indicators=4,
    ) == 20_000 + 2 * 25_000 + 3 * 200 + 4 * 12_500


def test_glamsterdam_regular_gas_tx_floor_branch():
    result = glamsterdam_regular_gas_tx(
        execution_gas_used_adjusted=100,
        calldata_zero_bytes=0,
        calldata_nonzero_bytes=100,
    )

    assert result["standard_branch"] == 1_600 + 100
    assert result["floor_branch"] == 6_400
    assert result["floor_binds"]
    assert result["regular_gas_glamsterdam"] == 21_000 + 6_400


def test_glamsterdam_regular_gas_tx_standard_branch_with_access_list():
    result = glamsterdam_regular_gas_tx(
        execution_gas_used_adjusted=100_000,
        calldata_zero_bytes=0,
        calldata_nonzero_bytes=100,
        access_list_address_count=1,
        access_list_storage_key_count=2,
    )

    assert not result["floor_binds"]
    assert result["access_list_data_cost_7981"] == 84 * 64
    assert result["regular_gas_glamsterdam"] == (
        21_000
        + 84 * 64
        + 1_600
        + 100_000
        + 2_400
        + 2 * 1_900
    )


def test_receipt_repricing_subtracts_state_before_glamsterdam_floor():
    result = glamsterdam_regular_gas_from_receipt(
        receipt_gas_used=121_000,
        calldata_zero_bytes=0,
        calldata_nonzero_bytes=2_000,
        historical_state_creation_gas_used=30_000,
    )

    assert result.receipt_body_gas == 100_000
    assert result.standard_branch_after_state == 70_000
    assert result.floor_branch == 128_000
    assert result.floor_binds
    assert result.regular_gas_glamsterdam == 21_000 + 128_000


def test_receipt_repricing_handles_current_floor_bound_transactions():
    result = glamsterdam_regular_gas_from_receipt(
        receipt_gas_used=61_000,
        calldata_zero_bytes=0,
        calldata_nonzero_bytes=1_000,
        historical_state_creation_gas_used=50_000,
    )

    assert result.current_floor_binds_observed
    assert result.current_7623_floor_gas == 40_000
    assert result.floor_branch == 64_000
    assert result.regular_gas_glamsterdam == 21_000 + 64_000
