"""
Pipeline orchestrator.

Runs the batch pipeline end to end through three clear stages that
mirror real-world ETL design:

    ingestion -> transformation (clean/validate) -> load -> analytics transform

Usage:
    python -m pipeline.pipeline
"""

import logging
import time

from pipeline.clean import clean_all
from pipeline.db import get_connection
from pipeline.ingest import ingest_raw_data
from pipeline.load import load_all
from pipeline.transform import run_transformations

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def run_pipeline() -> None:
    start = time.time()

    logger.info("=== Stage 1/3: Ingestion ===")
    raw_frames = ingest_raw_data()

    logger.info("\n=== Stage 2/3: Validation & Cleaning ===")
    cleaned_frames = clean_all(raw_frames)
    for name in raw_frames:
        before, after = len(raw_frames[name]), len(cleaned_frames[name])
        logger.info("  %-12s %5d -> %5d rows kept (%d dropped total)", name, before, after, before - after)

    logger.info("\n=== Stage 3/3: Load & Transform ===")
    conn = get_connection()
    try:
        load_all(cleaned_frames, conn)
        run_transformations(conn)
    finally:
        conn.close()

    elapsed = time.time() - start
    logger.info("\nPipeline completed in %.2fs -> output/pipeline.db", elapsed)


if __name__ == "__main__":
    run_pipeline()
