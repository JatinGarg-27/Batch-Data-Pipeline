"""
Stage 4 - Transform.

Runs every sql/marts/*.sql file in name order against the star schema. The
SQL lives in .sql files (not Python strings) so it can be read, reviewed and
run on its own in any MySQL client. Each file DROPs and re-CREATEs its
tables, so this stage is idempotent.
"""

from __future__ import annotations

import logging
import re
import time

from pipeline import config
from pipeline.db import connect, run_sql_file

logger = logging.getLogger(__name__)
MARTS_DIR = config.SQL_DIR / "marts"


def run() -> dict:
    conn = connect(autocommit=True)
    built = {}
    try:
        with conn.cursor() as cur:
            for f in sorted(MARTS_DIR.glob("*.sql")):
                t0 = time.perf_counter()
                run_sql_file(conn, f)
                for table in re.findall(r"CREATE TABLE (\w+)", f.read_text()):
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    built[table] = cur.fetchone()[0]
                    logger.info("  built %-34s %10s rows  (%s, %.1fs)", table, f"{built[table]:,}",
                                f.name, time.perf_counter() - t0)
    finally:
        conn.close()
    return {"tables": len(built), "rows": sum(built.values())}
