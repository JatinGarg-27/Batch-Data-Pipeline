"""
Central configuration: filesystem paths and database settings.

DB credentials are read from environment variables, which python-dotenv
populates from a local, git-ignored `.env` file. Nothing secret lives in
the repository -- only `.env.example` with placeholder values.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STAGING_DIR = DATA_DIR / "staging"      # ingest output: raw rows as Parquet, all strings
CLEAN_DIR = DATA_DIR / "clean"          # clean output: typed, validated Parquet
REJECTED_DIR = DATA_DIR / "rejected"    # rows that failed a rule, with reject_reason
REPORTS_DIR = ROOT / "reports"
LOG_DIR = ROOT / "logs"
SQL_DIR = ROOT / "sql"

CHUNK_SIZE = int(os.getenv("PIPELINE_CHUNK_SIZE", "250000"))


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def db_config() -> DBConfig:
    missing = [k for k in ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE") if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            f"Missing DB settings {missing}. Copy .env.example to .env and fill it in."
        )
    return DBConfig(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
    )
