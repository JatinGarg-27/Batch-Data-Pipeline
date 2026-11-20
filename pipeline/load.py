"""
Load stage.

Applies the relational schema and loads the cleaned, validated
DataFrames into SQLite. Runs after ingestion + cleaning, in FK
dependency order (customers/products before orders/order_items).
"""

import logging
import sqlite3

import pandas as pd

from pipeline.db import apply_schema, get_connection

logger = logging.getLogger(__name__)

LOAD_ORDER = ["customers", "products", "orders", "order_items"]


def load_all(cleaned: dict[str, pd.DataFrame], conn: sqlite3.Connection) -> None:
    apply_schema(conn)
    for table in LOAD_ORDER:
        df = cleaned[table]
        df.to_sql(table, conn, if_exists="append", index=False)
        logger.info("Loaded %-12s %5d rows -> %s", table, len(df), table)
    conn.commit()
