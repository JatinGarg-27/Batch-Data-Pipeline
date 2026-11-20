# Index benchmark (measured)

Run: 2026-11-20 14:12 on `fact_order_items` with **982,081 rows**,
MySQL 8.0 in Docker (innodb_buffer_pool_size=1G), warm buffer pool, median of 5 runs
after one warm-up. Produced by `python scripts/benchmark_index.py`.

## Query: new customers per first-order month

```sql
SELECT LEFT(first_date_key, 6) AS yyyymm, COUNT(*) AS new_customers
FROM (
    SELECT customer_key, MIN(order_date_key) AS first_date_key
    FROM fact_order_items
    GROUP BY customer_key
) AS firsts
GROUP BY yyyymm
ORDER BY yyyymm
;
```

| | Index on `fact_order_items` | Median time | Runs (ms) |
|---|---|---:|---|
| Before | `idx_foi_customer (customer_key)` (FK index only) | **1462 ms** | 1638, 1561, 1462, 1410, 1429 |
| After | `idx_foi_customer_date (customer_key, order_date_key)` | **491 ms** | 491, 440, 456, 534, 591 |

**Speed-up: 3.0x.** Building the composite index took 1.2s. Both versions return
the same 24 rows (asserted by the script).

### Why it is faster
`MIN(order_date_key) ... GROUP BY customer_key` needs the earliest date per customer. In the
composite index the entries are sorted by customer, then by date, so the first entry of each
customer *is* the answer. MySQL can jump from one customer to the next ("loose index scan",
shown as `Using index for group-by`) instead of reading all 982,081 fact rows.

### EXPLAIN (before)
<derived2>: type=ALL, key=None, rows=974368, Extra=Using temporary; Using filesort; fact_order_items: type=index, key=idx_foi_customer, rows=974368, Extra=None

### EXPLAIN (after)
<derived2>: type=ALL, key=None, rows=246540, Extra=Using temporary; Using filesort; fact_order_items: type=range, key=idx_foi_customer_date, rows=246540, Extra=Using index for group-by

### EXPLAIN ANALYZE (before)
```
-> Sort: yyyymm  (actual time=1674..1674 rows=24 loops=1)
    -> Table scan on <temporary>  (actual time=1674..1674 rows=24 loops=1)
        -> Aggregate using temporary table  (actual time=1674..1674 rows=24 loops=1)
            -> Table scan on firsts  (cost=221140..224179 rows=242881) (actual time=1599..1622 rows=248579 loops=1)
                -> Materialize  (cost=221140..221140 rows=242881) (actual time=1599..1599 rows=248579 loops=1)
                    -> Group aggregate: min(fact_order_items.order_date_key)  (cost=196852 rows=242881) (actual time=7.14..1578 rows=248579 loops=1)
                        -> Index scan on fact_order_items using idx_foi_customer  (cost=99416 rows=974368) (actual time=7.14..1494 rows=982081 loops=1)

```

### EXPLAIN ANALYZE (after)
```
-> Sort: yyyymm  (actual time=586..586 rows=24 loops=1)
    -> Table scan on <temporary>  (actual time=586..586 rows=24 loops=1)
        -> Aggregate using temporary table  (actual time=586..586 rows=24 loops=1)
            -> Table scan on firsts  (cost=112843..115927 rows=246540) (actual time=506..530 rows=248579 loops=1)
                -> Materialize  (cost=112843..112843 rows=246540) (actual time=506..506 rows=248579 loops=1)
                    -> Covering index skip scan for grouping on fact_order_items using idx_foi_customer_date  (cost=88189 rows=246540) (actual time=0.0336..483 rows=248579 loops=1)

```
