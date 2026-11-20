"""The generator must be reproducible and hit the requested size."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "generate_data", Path(__file__).resolve().parent.parent / "scripts" / "generate_data.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


@pytest.fixture(scope="module")
def small():
    return gen.generate(rows=4000, seed=7)[0]


def test_same_seed_gives_identical_data(small):
    again = gen.generate(rows=4000, seed=7)[0]
    for name, df in small.items():
        assert df.equals(again[name]), name


def test_rows_flag_controls_clean_order_items(small):
    assert len(small["order_items"]) == 4000


def test_keys_are_consistent(small):
    assert small["orders"]["customer_id"].isin(small["customers"]["customer_id"]).all()
    assert small["order_items"]["order_id"].isin(small["orders"]["order_id"]).all()
    assert (small["order_items"]["selling_price"] <= small["order_items"]["mrp"]).all()
    assert (small["products"]["cost_price"] < small["products"]["mrp"]).all()


def test_dirty_injection_is_recorded(small):
    raw, issues = gen.dirty(small, np.random.default_rng(1))
    assert issues["order_items"]["exact_duplicate_rows"] > 0
    assert len(raw["order_items"]) > len(small["order_items"])
