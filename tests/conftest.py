import pandas as pd
import pytest

from pipeline.clean import CLEANERS, Chunk, Context
from pipeline.quality import DQReport


@pytest.fixture
def report(tmp_path):
    return DQReport(tmp_path)


@pytest.fixture
def ctx():
    return Context(max_date=pd.Timestamp("2026-01-31"))


@pytest.fixture
def run_clean(report, ctx):
    """Push a list-of-dicts 'raw CSV' through one table's cleaner."""
    def _run(table, rows):
        raw = pd.DataFrame(rows).astype(str)
        raw.insert(0, "_source_row", range(2, len(raw) + 2))
        ch = Chunk(table, raw, report)
        CLEANERS[table](ch, ctx)
        return ch.df.reset_index(drop=True)
    return _run
