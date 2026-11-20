"""MySQL connection helpers + a small runner for .sql files."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import pymysql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from pipeline.config import db_config

logger = logging.getLogger(__name__)


def connect(autocommit: bool = False) -> pymysql.connections.Connection:
    cfg = db_config()
    try:
        return pymysql.connect(host=cfg.host, port=cfg.port, user=cfg.user, password=cfg.password,
                               database=cfg.database, charset="utf8mb4", autocommit=autocommit,
                               local_infile=True)
    except pymysql.err.OperationalError as exc:
        raise ConnectionError(
            f"Cannot connect to MySQL at {cfg.host}:{cfg.port} ({exc.args[-1]}). "
            "Is it running? Try: docker compose up -d") from exc


def engine() -> Engine:
    """SQLAlchemy engine for pandas.read_sql (analysis, tests)."""
    cfg = db_config()
    url = URL.create("mysql+pymysql", username=cfg.user, password=cfg.password,
                     host=cfg.host, port=cfg.port, database=cfg.database)
    return create_engine(url, connect_args={"charset": "utf8mb4"})


def split_sql(text: str) -> list[str]:
    """Split a .sql file into statements. Comments are stripped first, so
    explanatory comments may contain anything except a quote character."""
    text = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in text.split(";") if s.strip()]


def run_sql_file(conn, path: Path) -> list[tuple[str, int, float]]:
    """Execute every statement in a file; returns (first line, rows affected, seconds)."""
    results = []
    with conn.cursor() as cur:
        for stmt in split_sql(path.read_text()):
            t0 = time.perf_counter()
            try:
                rows = cur.execute(stmt)
            except pymysql.MySQLError as exc:
                raise RuntimeError(f"{path.name}: {exc.args[-1]}\n--- statement ---\n{stmt[:400]}") from exc
            results.append((stmt.splitlines()[0][:70], rows, time.perf_counter() - t0))
    return results
