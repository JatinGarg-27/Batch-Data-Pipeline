"""
Stage 1 - Ingestion.

Reads every raw CSV in data/raw/ *in chunks* (never the whole file in
memory), checks the header against the source contract in schemas.py, and
lands each chunk unchanged (all values kept as strings) as a Parquet file
under data/staging/<table>/part-NNNNN.parquet.

Why land to Parquet instead of passing DataFrames straight on?
  * each stage can be re-run on its own (`--stage clean` doesn't re-read CSV)
  * Parquet is columnar + compressed, so later stages read it much faster
  * a `_source_row` column (line number in the CSV) is added for lineage, so
    any rejected row can be traced back to the exact line of the raw file.

No cleaning happens here: the goal is a faithful copy plus row counts.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pandas as pd

from pipeline import config
from pipeline.schemas import RAW_SCHEMAS, TABLE_ORDER

logger = logging.getLogger(__name__)


class SchemaError(Exception):
    pass


def check_header(path: Path, expected: list[str]) -> None:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    missing = [c for c in expected if c not in header]
    extra = [c for c in header if c not in expected]
    if missing:
        raise SchemaError(f"{path.name}: missing required column(s) {missing}; found {header}")
    if extra:
        logger.warning("  %s: ignoring unexpected column(s) %s", path.name, extra)


def ingest_table(table: str, raw_dir: Path, staging_dir: Path, chunk_size: int) -> int:
    path = raw_dir / f"{table}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing raw source file {path}. Run: python scripts/generate_data.py")
    columns = RAW_SCHEMAS[table]
    check_header(path, columns)

    out_dir = staging_dir / table
    shutil.rmtree(out_dir, ignore_errors=True)          # re-running ingest replaces, never appends
    out_dir.mkdir(parents=True)

    total = 0
    reader = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=columns,
                         chunksize=chunk_size)
    for i, chunk in enumerate(reader):
        chunk = chunk[columns]
        # +2: CSV line 1 is the header and pandas rows are 0-based
        chunk.insert(0, "_source_row", range(total + 2, total + 2 + len(chunk)))
        chunk.to_parquet(out_dir / f"part-{i:05d}.parquet", index=False)
        total += len(chunk)
    logger.info("  ingested %-12s %12s rows in %d chunk(s)", table, f"{total:,}", i + 1)
    return total


def run(raw_dir: Path = config.RAW_DIR, staging_dir: Path = config.STAGING_DIR,
        chunk_size: int = config.CHUNK_SIZE) -> dict[str, int]:
    return {t: ingest_table(t, raw_dir, staging_dir, chunk_size) for t in TABLE_ORDER}


def iter_staged(table: str, staging_dir: Path = config.STAGING_DIR):
    """Yield the landed chunks of a table one at a time (bounded memory)."""
    parts = sorted((staging_dir / table).glob("part-*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No staged data for {table}. Run --stage ingest first.")
    for p in parts:
        yield pd.read_parquet(p)
