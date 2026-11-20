"""
Measure one heavy query before/after adding a composite index, with EXPLAIN ANALYZE.

    python scripts/benchmark_index.py          # needs a loaded warehouse

The query: "new customers per month", which needs every customer's FIRST
order date -- the building block of cohort and acquisition analysis -- over
the whole fact table.

  BEFORE: fact_order_items only has the single-column index on customer_key
          that a foreign key needs. MySQL must read every fact row (~1M) to
          find each customer's MIN(order_date_key).
  AFTER:  composite index (customer_key, order_date_key). Inside it, each
          customer's dates are already sorted, so MIN() is simply the first
          entry per customer: MySQL can do a "loose index scan" that jumps
          from customer to customer without reading the table at all.

Writes reports/index_benchmark.md and leaves the schema as sql/schema/02_star.sql
defines it (composite index present).
"""

from __future__ import annotations

import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import config  # noqa: E402
from pipeline.db import connect  # noqa: E402

QUERY = """
SELECT LEFT(first_date_key, 6) AS yyyymm, COUNT(*) AS new_customers
FROM (
    SELECT customer_key, MIN(order_date_key) AS first_date_key
    FROM fact_order_items
    GROUP BY customer_key
) AS firsts
GROUP BY yyyymm
ORDER BY yyyymm"""
RUNS = 5


def indexes(cur) -> set[str]:
    cur.execute("SHOW INDEX FROM fact_order_items")
    return {r[2] for r in cur.fetchall()}


def measure(cur) -> dict:
    cur.execute(QUERY)                     # warm-up: both cases measured with a warm buffer pool
    cur.fetchall()
    times = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        cur.execute(QUERY)
        rows = cur.fetchall()
        times.append(time.perf_counter() - t0)
    cur.execute("EXPLAIN " + QUERY)
    cols = [d[0] for d in cur.description]
    explain = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.execute("EXPLAIN ANALYZE " + QUERY)
    analyze = cur.fetchone()[0]
    return {"median_s": statistics.median(times), "times": times, "rows": len(rows),
            "result": rows, "explain": explain, "analyze": analyze}


def main():
    conn = connect(autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM fact_order_items")
    fact_rows = cur.fetchone()[0]

    # ---- BEFORE: single-column FK index only
    if "idx_foi_customer" not in indexes(cur):
        cur.execute("ALTER TABLE fact_order_items ADD INDEX idx_foi_customer (customer_key)")
    if "idx_foi_customer_date" in indexes(cur):
        cur.execute("ALTER TABLE fact_order_items DROP INDEX idx_foi_customer_date")
    cur.execute("ANALYZE TABLE fact_order_items"); cur.fetchall()
    before = measure(cur)

    # ---- AFTER: composite index
    t0 = time.perf_counter()
    cur.execute("ALTER TABLE fact_order_items ADD INDEX idx_foi_customer_date (customer_key, order_date_key)")
    build_s = time.perf_counter() - t0
    # the composite index's leftmost column already serves the FK -> drop the redundant one
    cur.execute("ALTER TABLE fact_order_items DROP INDEX idx_foi_customer")
    cur.execute("ANALYZE TABLE fact_order_items"); cur.fetchall()
    after = measure(cur)
    assert before["result"] == after["result"], "index changed the query result!"
    conn.close()

    speedup = before["median_s"] / after["median_s"]
    fmt_times = lambda r: ", ".join(f"{t * 1000:.0f}" for t in r["times"])
    extra = lambda r: "; ".join(f"{e['table']}: type={e['type']}, key={e['key']}, rows={e['rows']}, "
                                f"Extra={e['Extra']}" for e in r["explain"])
    md = f"""# Index benchmark (measured)

Run: {datetime.now():%Y-%m-%d %H:%M} on `fact_order_items` with **{fact_rows:,} rows**,
MySQL 8.0 in Docker (innodb_buffer_pool_size=1G), warm buffer pool, median of {RUNS} runs
after one warm-up. Produced by `python scripts/benchmark_index.py`.

## Query: new customers per first-order month

```sql{QUERY}
;
```

| | Index on `fact_order_items` | Median time | Runs (ms) |
|---|---|---:|---|
| Before | `idx_foi_customer (customer_key)` (FK index only) | **{before['median_s'] * 1000:.0f} ms** | {fmt_times(before)} |
| After | `idx_foi_customer_date (customer_key, order_date_key)` | **{after['median_s'] * 1000:.0f} ms** | {fmt_times(after)} |

**Speed-up: {speedup:.1f}x.** Building the composite index took {build_s:.1f}s. Both versions return
the same {after['rows']} rows (asserted by the script).

### Why it is faster
`MIN(order_date_key) ... GROUP BY customer_key` needs the earliest date per customer. In the
composite index the entries are sorted by customer, then by date, so the first entry of each
customer *is* the answer. MySQL can jump from one customer to the next ("loose index scan",
shown as `Using index for group-by`) instead of reading all {fact_rows:,} fact rows.

### EXPLAIN (before)
{extra(before)}

### EXPLAIN (after)
{extra(after)}

### EXPLAIN ANALYZE (before)
```
{before['analyze']}
```

### EXPLAIN ANALYZE (after)
```
{after['analyze']}
```
"""
    config.REPORTS_DIR.mkdir(exist_ok=True)
    out = config.REPORTS_DIR / "index_benchmark.md"
    out.write_text(md)
    print(f"before {before['median_s'] * 1000:.0f} ms -> after {after['median_s'] * 1000:.0f} ms "
          f"({speedup:.1f}x); report: {out}")


if __name__ == "__main__":
    main()
