"""Unit tests for the cleaning rules: no database needed."""

import numpy as np
import pandas as pd
import pytest

from pipeline.clean import parse_date
from pipeline.quality import IdSet


def customer(cid="1", **kw):
    row = dict(customer_id=cid, first_name="aditi", last_name="sharma",
               email=f"a{cid}@example.com", gender="F", city="Mumbai", state="MH",
               signup_date="2024-01-05", acquisition_channel="organic_search")
    row.update(kw)
    return row


def product(pid="1", **kw):
    row = dict(product_id=pid, product_name="Kaveri Solid Kurtas", brand="Kaveri",
               category="Ethnic Wear", sub_category="Kurtas", style="Ethnic", mrp="1999",
               cost_price="700")
    row.update(kw)
    return row


def order(oid="1", **kw):
    row = dict(order_id=oid, customer_id="1", session_id="", order_date="2025-03-01",
               order_status="delivered", channel="direct", device="app",
               payment_method="UPI", coupon_code="")
    row.update(kw)
    return row


def item(iid="1", **kw):
    row = dict(order_item_id=iid, order_id="1", product_id="1", quantity="1", mrp="1999",
               selling_price="1199", coupon_discount="0")
    row.update(kw)
    return row


# ------------------------------------------------------------------ helpers
def test_parse_date_handles_iso_and_dd_mm_yyyy():
    parsed, n_alt = parse_date(pd.Series(["2025-03-01", "05-01-2024", "2025-02-30", "N/A", ""]))
    assert parsed[0] == pd.Timestamp("2025-03-01")
    assert parsed[1] == pd.Timestamp("2024-01-05")       # day first, never guessed as May 1st
    assert parsed[2:].isna().all()                        # impossible date, garbage, blank
    assert n_alt == 1


def test_idset_detects_keys_across_chunks():
    s = IdSet(capacity=4)
    s.add([1, 2, 3])
    s.add([10_000])                                       # grows automatically
    assert s.contains([3, 4, 10_000, -1]).tolist() == [True, False, True, False]


# ------------------------------------------------------------------ customers
def test_missing_email_is_kept_as_null_not_rejected(run_clean, report):
    out = run_clean("customers", [customer("1", email=""), customer("2", email="bad at mail.com")])
    assert len(out) == 2
    assert out["email"].isna().all()
    assert report.repaired["customers"]["missing_email_kept_as_null"] == 1
    assert report.repaired["customers"]["malformed_email_set_null"] == 1


def test_duplicate_and_missing_customer_ids_are_rejected(run_clean, report):
    out = run_clean("customers", [customer("1"), customer("1"), customer("")])
    assert out["customer_id"].tolist() == [1]
    assert report.rejected["customers"] == {"missing_or_invalid_customer_id": 1,
                                            "duplicate_customer_id": 1}


def test_city_casing_and_whitespace_are_standardised(run_clean):
    out = run_clean("customers", [customer("1", city=" mUMBAI "), customer("2", city="DELHI")])
    assert out["city"].tolist() == ["Mumbai", "Delhi"]


def test_bad_signup_date_becomes_null_but_row_is_kept(run_clean):
    out = run_clean("customers", [customer("1", signup_date="2024-02-30"),
                                  customer("2", signup_date="15-03-2024")])
    assert pd.isna(out.loc[0, "signup_date"])
    assert out.loc[1, "signup_date"] == pd.Timestamp("2024-03-15")


# ------------------------------------------------------------------ products
def test_negative_mrp_rejected_and_category_casing_fixed(run_clean, report):
    out = run_clean("products", [product("1", mrp="-999"), product("2", category=" ethnic WEAR ")])
    assert out["product_id"].tolist() == [2]
    assert out.loc[0, "category"] == "Ethnic Wear"
    assert report.rejected["products"]["invalid_mrp"] == 1


def test_missing_cost_price_is_imputed_from_category_ratio(run_clean, report):
    out = run_clean("products", [product("1", mrp="1000", cost_price="400"),
                                 product("2", mrp="2000", cost_price="")])
    assert out.loc[1, "cost_price"] == pytest.approx(800.0)     # 2000 x median ratio 0.40
    assert report.repaired["products"]["cost_price_imputed_category_median_ratio"] == 1


# ------------------------------------------------------------------ orders
@pytest.fixture
def parents(run_clean, report):
    run_clean("customers", [customer("1"), customer("2"), customer("3", customer_id="x")])
    run_clean("promotions", [dict(promotion_id="1", promo_code="NEW15", promo_name="New",
                                  promo_type="coupon", start_date="2024-01-01",
                                  end_date="2025-12-31", discount_pct="0.15",
                                  max_discount="300", min_order_value="499")])
    run_clean("products", [product("1")])


def test_order_rules(run_clean, report, parents):
    out = run_clean("orders", [
        order("1", order_status=" Delivered ", coupon_code="new15"),
        order("2", customer_id="999"),                     # customer never existed
        order("3", order_date="2025-02-30"),               # impossible date
        order("4", order_date="2031-01-15"),               # in the future
        order("5", order_status="test"),
        order("6", coupon_code="FAKE50"),                  # unknown coupon -> NULL, keep order
        order("1"),                                        # duplicate key
    ])
    assert out["order_id"].tolist() == [1, 6]
    assert out.loc[0, "order_status"] == "delivered"
    assert out.loc[0, "coupon_code"] == "NEW15"
    assert pd.isna(out.loc[1, "coupon_code"])
    assert report.rejected["orders"] == {
        "duplicate_order_id": 1, "orphan_customer_id": 1, "unparseable_order_date": 1,
        "order_date_out_of_range": 1, "invalid_order_status": 1}


def test_order_of_rejected_customer_is_attributed_to_parent(run_clean, report, ctx):
    run_clean("customers", [customer("1"), customer("1", city="dup")])
    ctx.seen["customers"].add([7])          # customer 7 appeared in source but was rejected
    run_clean("orders", [order("1", customer_id="7")])
    assert report.rejected["orders"] == {"parent_customer_rejected": 1}


def test_dedupe_works_across_chunks(run_clean, report, parents):
    run_clean("orders", [order("1")])
    out = run_clean("orders", [order("1"), order("2")])  # second chunk
    assert out["order_id"].tolist() == [2]
    assert report.rejected["orders"]["duplicate_order_id"] == 1


# ------------------------------------------------------------------ order items + returns
def test_order_item_price_and_quantity_rules(run_clean, report, parents):
    run_clean("orders", [order("1")])
    out = run_clean("order_items", [
        item("1"),
        item("2", quantity="0"),
        item("3", selling_price="-1199"),
        item("4", selling_price="5997"),                 # above MRP
        item("5", selling_price=""),
        item("6", order_id="42"),                         # orphan order
    ])
    assert out["order_item_id"].tolist() == [1]
    assert report.rejected["order_items"] == {
        "orphan_order_id": 1, "non_positive_quantity": 1, "missing_selling_price": 1,
        "non_positive_selling_price": 1, "selling_price_above_mrp": 1}


def test_return_rules(run_clean, report, parents):
    run_clean("orders", [order("1", order_date="2025-03-01")])
    run_clean("order_items", [item("1", selling_price="1000"), item("2", selling_price="1000")])
    out = run_clean("returns", [
        dict(return_id="1", order_item_id="1", return_date="2025-03-10",
             return_reason="Size too small", refund_amount="1000"),
        dict(return_id="2", order_item_id="2", return_date="2025-02-01",    # before the order
             return_reason="x", refund_amount="1000"),
        dict(return_id="3", order_item_id="1", return_date="2025-03-11",    # same line again
             return_reason="x", refund_amount="10"),
    ])
    assert out["return_id"].tolist() == [1]
    assert report.rejected["returns"] == {"return_before_order": 1, "duplicate_return_for_item": 1}


def test_refund_cannot_exceed_line_value(run_clean, report, parents):
    run_clean("orders", [order("1")])
    run_clean("order_items", [item("1", selling_price="1000", coupon_discount="100")])
    run_clean("returns", [dict(return_id="1", order_item_id="1", return_date="2025-03-05",
                               return_reason="x", refund_amount="950")])
    assert report.rejected["returns"] == {"refund_exceeds_line_value": 1}   # line value is 900


def test_rejected_rows_are_written_with_reason_and_raw_values(run_clean, report, tmp_path):
    run_clean("customers", [customer("1"), customer("1")])
    rejected = pd.read_csv(tmp_path / "customers_rejected.csv", dtype=str)
    assert rejected["reject_reason"].tolist() == ["duplicate_customer_id"]
    assert rejected["_source_row"].tolist() == ["3"]     # traceable to the raw CSV line
