WITH
blocks AS
(
    SELECT block_number, toDate(block_date_time) AS date
    FROM default.canonical_execution_block FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {min_block:UInt64} AND {max_block:UInt64}
),
ops AS
(
    SELECT
        block_number,
        transaction_hash,
        sumIf(opcode_count, operation = 'SSTORE') AS sstore_count,
        sumIf(gas, operation = 'SSTORE') AS sstore_gas,
        sumIf(cold_access_count, operation = 'SSTORE') AS sstore_cold,
        maxIf(ifNull(gas_refund, 0), operation = '' AND call_frame_id = 0) AS refund_current
    FROM default.canonical_execution_transaction_structlog_agg FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {min_block:UInt64} AND {max_block:UInt64}
      AND (operation = 'SSTORE' OR (operation = '' AND call_frame_id = 0))
    GROUP BY block_number, transaction_hash
    HAVING refund_current > 0
),
storage AS
(
    SELECT
        block_number,
        transaction_hash,
        count() AS changed_slots,
        countIf(lower(from_value) = {zero:String} AND lower(to_value) != {zero:String}) AS new_slots,
        countIf(lower(from_value) != {zero:String}) AS original_nonzero_changed,
        countIf(lower(from_value) != {zero:String} AND lower(to_value) = {zero:String}) AS net_clears
    FROM default.canonical_execution_storage_diffs FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {min_block:UInt64} AND {max_block:UInt64}
    GROUP BY block_number, transaction_hash
),
transactions AS
(
    SELECT
        block_number,
        hash AS transaction_hash,
        type AS transaction_type,
        n_input_zero_bytes AS zero_bytes,
        n_input_nonzero_bytes AS nonzero_bytes
    FROM default.execution_transaction FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {min_block:UInt64} AND {max_block:UInt64}
),
receipts AS
(
    SELECT block_number, transaction_hash, gas_used AS receipt_gas
    FROM default.canonical_execution_transaction FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {min_block:UInt64} AND {max_block:UInt64}
),
base AS
(
    SELECT
        b.date,
        o.block_number AS block_number,
        o.transaction_hash AS transaction_hash,
        toInt64(o.sstore_count) AS sstore_count,
        toInt64(o.sstore_gas) AS sstore_gas,
        toInt64(o.sstore_cold) AS sstore_cold,
        toInt64(o.refund_current) AS refund_current,
        toInt64(ifNull(s.changed_slots, 0)) AS changed_slots,
        toInt64(ifNull(s.new_slots, 0)) AS new_slots,
        toInt64(ifNull(s.original_nonzero_changed, 0)) AS original_nonzero_changed,
        toInt64(ifNull(s.net_clears, 0)) AS net_clears,
        toInt64(t.transaction_type) AS transaction_type,
        toInt64(t.zero_bytes) AS zero_bytes,
        toInt64(t.nonzero_bytes) AS nonzero_bytes,
        toInt64(r.receipt_gas) AS receipt_gas
    FROM ops AS o
    GLOBAL INNER JOIN blocks AS b USING block_number
    GLOBAL LEFT JOIN storage AS s USING (block_number, transaction_hash)
    GLOBAL INNER JOIN transactions AS t USING (block_number, transaction_hash)
    GLOBAL INNER JOIN receipts AS r USING (block_number, transaction_hash)
),
expanded AS
(
    SELECT
        *,
        arrayJoin(
            if(
                transaction_type = 4,
                range(toUInt32(intDiv(greatest(refund_current - 4800 * net_clears, 0), 12500) + 1)),
                [toUInt32(0)]
            )
        ) AS auth_refunds
    FROM base
),
calc1 AS
(
    SELECT *, refund_current - 4800 * net_clears - 12500 * auth_refunds AS residual_sstore_refund
    FROM expanded
),
calc2 AS
(
    SELECT
        *,
        residual_sstore_refund >= 0 AND modulo(residual_sstore_refund, 100) = 0 AS valid_division,
        if(valid_division, intDiv(residual_sstore_refund, 100), 0) AS refund_units
    FROM calc1
),
calc3 AS
(
    SELECT
        *,
        modulo(19 * refund_units, 28) AS zero_reset_base,
        intDiv(refund_units - 199 * zero_reset_base, 28) AS nonzero_reset_base,
        intDiv(greatest(sstore_count - changed_slots, 0), 2) AS reset_budget
    FROM calc2
),
calc4 AS
(
    SELECT
        *,
        zero_reset_base + nonzero_reset_base AS reset_sum_base,
        intDiv(nonzero_reset_base, 199) AS k_max,
        if(
            zero_reset_base + nonzero_reset_base > reset_budget,
            intDiv(zero_reset_base + nonzero_reset_base - reset_budget + 170, 171),
            0
        ) AS k_min
    FROM calc3
),
candidates AS
(
    SELECT
        *,
        valid_division AND nonzero_reset_base >= 0 AND k_min <= k_max AS feasible,
        reset_sum_base - 171 * k_max AS reset_sum_low,
        reset_sum_base - 171 * k_min AS reset_sum_high,
        12500 * auth_refunds + 12480 * net_clears + 10000 * reset_sum_low AS refund_future_low,
        12500 * auth_refunds + 12480 * net_clears + 10000 * reset_sum_high AS refund_future_high,
        abs(
            sstore_gas
            - (
                100 * sstore_count
                + 2100 * sstore_cold
                + 19900 * new_slots
                + 2800 * original_nonzero_changed
                + residual_sstore_refund
            )
        ) AS gas_error
    FROM calc4
),
ranked AS
(
    SELECT
        *,
        minIf(gas_error, feasible) OVER (
            PARTITION BY transaction_hash
        ) AS best_gas_error
    FROM candidates
),
recovered AS
(
    SELECT
        any(c.date) AS date,
        any(c.block_number) AS block_number,
        c.transaction_hash,
        any(c.sstore_count) AS sstore_count,
        any(c.sstore_gas) AS sstore_gas,
        any(c.sstore_cold) AS sstore_cold,
        any(c.refund_current) AS refund_current,
        any(c.changed_slots) AS changed_slots,
        any(c.new_slots) AS new_slots,
        any(c.zero_bytes) AS zero_bytes,
        any(c.nonzero_bytes) AS nonzero_bytes,
        any(c.receipt_gas) AS receipt_gas,
        min(c.refund_future_low) AS refund_future_low,
        max(c.refund_future_high) AS refund_future_high,
        min(c.reset_sum_low) AS reset_sum_low,
        max(c.reset_sum_high) AS reset_sum_high,
        sum(c.k_max - c.k_min + 1) AS solution_count
    FROM ranked AS c
    WHERE c.feasible AND c.gas_error = c.best_gas_error
    GROUP BY c.transaction_hash
),
metrics1 AS
(
    SELECT
        *,
        (refund_future_low + refund_future_high) / 2 AS refund_future,
        (reset_sum_low + reset_sum_high) / 2 AS reset_sum,
        zero_bytes + 4 * nonzero_bytes AS current_tokens,
        zero_bytes + nonzero_bytes AS calldata_bytes,
        21000 + 10 * (zero_bytes + 4 * nonzero_bytes) AS current_floor,
        21000 + 64 * (zero_bytes + nonzero_bytes) AS future_floor_7976,
        least(refund_current, intDiv(receipt_gas, 4)) AS current_refund_applied_cap_proxy,
        receipt_gas <= 21000 + 10 * (zero_bytes + 4 * nonzero_bytes) AND (zero_bytes + nonzero_bytes) > 0 AS current_floor_proxy
    FROM recovered
),
metrics2 AS
(
    SELECT
        *,
        if(current_floor_proxy, receipt_gas, receipt_gas + current_refund_applied_cap_proxy) AS gross_current,
        if(current_floor_proxy, 0, current_refund_applied_cap_proxy) AS effective_refund_current,
        100 * (sstore_count - sstore_cold)
            + 3000 * sstore_cold
            + 10000 * (changed_slots + reset_sum) AS sstore_regular_future,
        97920 * new_slots AS storage_state_gas_future
    FROM metrics1
),
metrics3 AS
(
    SELECT
        *,
        greatest(
            gross_current
            + sstore_regular_future
            + storage_state_gas_future
            - sstore_gas
            + {other_rate:Float64} * greatest(gross_current - sstore_gas, 0),
            0
        ) AS gross_future
    FROM metrics2
),
metrics4 AS
(
    SELECT
        *,
        least(refund_future, toFloat64(intDiv(toInt64(gross_future), 5))) AS refund_future_capped,
        greatest(
            gross_future
                - least(refund_future, toFloat64(intDiv(toInt64(gross_future), 5))),
            toFloat64(current_floor)
        ) AS gas_after_refund_current_floor,
        greatest(
            gross_future
                - least(refund_future, toFloat64(intDiv(toInt64(gross_future), 5))),
            toFloat64(future_floor_7976)
        ) AS gas_after_refund_7976_floor
    FROM metrics3
),
daily_base AS
(
    SELECT date, count() AS refund_txs_total, sum(refund_current) AS refund_counter_total
    FROM base
    GROUP BY date
),
daily_recovered AS
(
    SELECT
        date,
        count() AS refund_txs_identified,
        sum(refund_current) AS refund_counter_identified,
        sum(refund_future_low) AS refund_future_low_sum,
        sum(refund_future) AS refund_future_sum,
        sum(refund_future_high) AS refund_future_high_sum,
        sum(effective_refund_current) AS effective_refund_current_sum,
        sum(gross_future - gas_after_refund_current_floor - effective_refund_current) AS extra_refund_current_floor,
        sum(gross_future - gas_after_refund_7976_floor - effective_refund_current) AS extra_refund_7976_floor,
        countIf(refund_future > intDiv(toInt64(gross_future), 5)) AS future_cap_bound_txs,
        countIf(current_floor_proxy) AS current_floor_proxy_txs,
        countIf(solution_count > 1) AS bounded_txs
    FROM metrics4
    GROUP BY date
)
SELECT *
FROM daily_base
LEFT JOIN daily_recovered USING date
ORDER BY date
