"""
Stage 3 - Load.

1. (Re)create the staging tables and create the star schema if missing.
2. Bulk-load the cleaned Parquet into staging with LOAD DATA LOCAL INFILE
   (MySQL's fastest import path, ~10-50x faster than row-by-row INSERTs).
3. Run the merge SQL in sql/load/ (dimension upserts, then facts).
4. Advance the watermark and record the run in etl_load_log.

Idempotent: every merge is an upsert on a primary/unique key, so loading the
same data twice leaves the warehouse unchanged (no duplicates).

Incremental mode (--incremental): reads the watermark (latest order_date
already merged) and only stages orders/sessions dated on or after
`watermark - lookback_days`, plus the lines and returns that belong to them.
The lookback re-merges a few already-loaded days so late-arriving rows (e.g.
a status change) are picked up; upserts make that overlap harmless.
Dimensions are small and are always fully upserted.
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from pipeline import config
from pipeline.clean import iter_clean
from pipeline.db import connect, run_sql_file
from pipeline.quality import IdSet
from pipeline.schemas import RAW_SCHEMAS, TABLE_ORDER

logger = logging.getLogger(__name__)
TMP_DIR = config.DATA_DIR / "staging" / "_load_tmp"


def _to_arrow(df: pd.DataFrame) -> pa.Table:
    t = pa.Table.from_pandas(df, preserve_index=False)
    for i, field in enumerate(t.schema):
        if pa.types.is_timestamp(field.type):         # write DATEs as YYYY-MM-DD
            t = t.set_column(i, field.name, pc.cast(t.column(i), pa.date32()))
    return t


def export_csv(table: str, keep=None) -> tuple[str, int]:
    """Write a table's clean parts (optionally filtered) to one CSV for LOAD DATA."""
    path = TMP_DIR / f"{table}.csv"
    cols = RAW_SCHEMAS[table]
    writer, rows = None, 0
    for df in iter_clean(table):
        if keep is not None:
            df = df.loc[keep(df)]
        t = _to_arrow(df[cols])
        if writer is None:
            writer = pacsv.CSVWriter(str(path), t.schema)
        writer.write_table(t)
        rows += t.num_rows
    if writer is None:  # no parts at all
        raise FileNotFoundError(f"No clean data for {table}")
    writer.close()
    return str(path), rows


def load_data_infile(cur, table: str, path: str) -> None:
    cols = RAW_SCHEMAS[table]
    # Read every field into a user variable and convert '' -> NULL, so missing
    # values become real NULLs instead of 0 / '0000-00-00'.
    variables = ", ".join(f"@{c}" for c in cols)
    sets = ", ".join(f"{c} = NULLIF(@{c}, '')" for c in cols)
    cur.execute(f"""
        LOAD DATA LOCAL INFILE %s INTO TABLE stg_{table}
        CHARACTER SET utf8mb4
        FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
        LINES TERMINATED BY '\\n'
        IGNORE 1 LINES
        ({variables})
        SET {sets}""", (path,))
    warnings = cur.execute("SHOW WARNINGS")
    if warnings:
        sample = cur.fetchall()[:3]
        raise RuntimeError(f"LOAD DATA into stg_{table} produced {warnings} warning(s): {sample}")


def incremental_filters(cutoff: pd.Timestamp) -> dict:
    """Row filters that keep only the incremental window (and dependent rows)."""
    batch_orders, batch_items = IdSet(), IdSet()
    for df in iter_clean("orders"):
        batch_orders.add(df.loc[df["order_date"] >= cutoff, "order_id"].to_numpy())
    for df in iter_clean("order_items"):
        batch_items.add(df.loc[batch_orders.contains(df["order_id"].to_numpy()),
                               "order_item_id"].to_numpy())
    return {
        "sessions": lambda d: d["session_date"] >= cutoff,
        "orders": lambda d: d["order_date"] >= cutoff,
        "order_items": lambda d: batch_orders.contains(d["order_id"].to_numpy()),
        # returns of older orders can arrive late: keep any return dated in the window
        "returns": lambda d: (d["return_date"] >= cutoff).to_numpy()
        | batch_items.contains(d["order_item_id"].to_numpy()),
    }


def run(incremental: bool = False, lookback_days: int = 3) -> dict:
    started = datetime.now()
    conn = connect()
    try:
        cur = conn.cursor()
        for f in sorted((config.SQL_DIR / "schema").glob("*.sql")):
            run_sql_file(conn, f)

        mode, cutoff, filters = "full", None, {}
        if incremental:
            cur.execute("SELECT high_watermark FROM etl_watermark WHERE table_name = 'fact_order_items'")
            row = cur.fetchone()
            if row:
                mode = "incremental"
                cutoff = pd.Timestamp(row[0]) - timedelta(days=lookback_days)
                filters = incremental_filters(cutoff)
                logger.info("  incremental: watermark %s, re-merging from %s", row[0], cutoff.date())
            else:
                logger.info("  incremental requested but no watermark yet -> full load")

        # 1) bulk-load staging
        shutil.rmtree(TMP_DIR, ignore_errors=True)
        TMP_DIR.mkdir(parents=True)
        staged = {}
        for table in TABLE_ORDER:
            t0 = time.perf_counter()
            path, n = export_csv(table, filters.get(table))
            load_data_infile(cur, table, path)
            staged[table] = n
            logger.info("  staged   stg_%-12s %12s rows  %5.1fs", table, f"{n:,}", time.perf_counter() - t0)

        # 2) merge into the star schema -- one transaction, so a failure part-way
        #    leaves the warehouse exactly as it was before this run
        for f in sorted((config.SQL_DIR / "load").glob("*.sql")):
            for first_line, rows, secs in run_sql_file(conn, f):
                logger.info("  merged   %-24s %12s rows affected  %5.1fs", f.name, f"{rows:,}", secs)
        conn.commit()

        # 3) integrity check: every staged order line must now be in the fact table
        cur.execute("""SELECT COUNT(*) FROM stg_order_items s
                       LEFT JOIN fact_order_items f USING (order_item_id)
                       WHERE f.order_item_id IS NULL""")
        missing = cur.fetchone()[0]
        if missing:
            raise RuntimeError(f"{missing:,} staged order lines did not reach fact_order_items")

        for t in ("dim_customer", "dim_product", "dim_date", "fact_order_items",
                  "fact_sessions_daily"):
            cur.execute(f"ANALYZE TABLE {t}")   # refresh optimizer statistics
            cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM fact_order_items")
        fact_rows = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*), SUM(sessions) FROM fact_sessions_daily")
        session_rows, session_total = cur.fetchone()
        cur.execute("""INSERT INTO etl_load_log (started_at, finished_at, mode, cutoff_date,
                       rows_staged, fact_rows_after) VALUES (%s, NOW(), %s, %s, %s, %s)""",
                    (started, mode, cutoff.date() if cutoff is not None else None,
                     sum(staged.values()), fact_rows))
        conn.commit()
        logger.info("  fact_order_items now %s rows; fact_sessions_daily %s rows (%s sessions)",
                    f"{fact_rows:,}", f"{session_rows:,}", f"{int(session_total):,}")
        return {"mode": mode, "rows": sum(staged.values()), "fact_order_items": fact_rows,
                "fact_sessions_daily": session_rows}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        shutil.rmtree(TMP_DIR, ignore_errors=True)
