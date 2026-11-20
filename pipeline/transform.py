"""
Transformation stage.

Runs sql/transformations.sql against the loaded relational tables to
build analysis-ready tables (joins, aggregations, window functions).
Runs after load, since it reads from the tables load.py populates.
"""

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

TRANSFORM_SQL_PATH = os.path.join(os.path.dirname(__file__), "..", "sql", "transformations.sql")

ANALYTICS_TABLES = [
    "analytics_order_line_items",
    "analytics_revenue_by_category",
    "analytics_customer_ltv",
    "analytics_monthly_revenue_trend",
    "analytics_top_products_by_category",
]


def run_transformations(conn: sqlite3.Connection, sql_path: str = TRANSFORM_SQL_PATH) -> None:
    with open(sql_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()

    for table in ANALYTICS_TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        logger.info("Built %-34s %5d rows", table, count)
