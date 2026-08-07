"""
Ingestion stage.

Reads the raw CSV drops from data/raw/ into pandas DataFrames.
This stage does no validation or transformation -- it only loads
what's on disk and reports what came in, so downstream stages have
a clear "before" baseline to compare against.
"""

import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

RAW_FILES = {
    "customers": "customers.csv",
    "products": "products.csv",
    "orders": "orders.csv",
    "order_items": "order_items.csv",
}


def ingest_raw_data(raw_dir: str = RAW_DIR) -> dict[str, pd.DataFrame]:
    """Read every raw CSV source into a DataFrame, keyed by entity name."""
    frames: dict[str, pd.DataFrame] = {}
    for name, filename in RAW_FILES.items():
        path = os.path.join(raw_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Missing raw source file: {path}. "
                "Run scripts/generate_sample_data.py first."
            )
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        logger.info("Ingested %-12s %5d rows  <- %s", name, len(df), filename)
        frames[name] = df
    return frames


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ingest_raw_data()
