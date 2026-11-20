"""
Stage 2 - Validation & cleaning.

Reads the staged (raw, all-string) chunks one at a time, applies named
rules, and writes typed, validated Parquet to data/clean/<table>/.

Two kinds of rule:
  * REJECT  -- the row can't be trusted (bad key, unparseable order date,
               negative price, orphan foreign key...). It is removed and
               written to data/rejected/<table>_rejected.csv with the rule
               name in `reject_reason`, using the *raw* values.
  * REPAIR  -- the problem is fixable without losing the row (casing,
               whitespace, date format, a missing email). The row is kept
               and the repair is counted.

Choosing reject vs repair is a business decision. Example: the original
version of this project dropped customers with a missing email, which then
silently dropped all their (perfectly valid) orders as "orphans". Here a
missing email just becomes NULL.

Rules run in a fixed order and a row is attributed to the first rule it
fails. Tables are processed parents-first (see schemas.TABLE_ORDER) so
foreign keys are checked against already-cleaned parents. Orphans are split
into two reasons:
  * orphan_<fk>            -- the parent key never existed in the source
  * parent_<x>_rejected    -- the parent existed but was itself rejected
"""

from __future__ import annotations

import logging
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import config
from pipeline.ingest import iter_staged
from pipeline.quality import DQReport, IdSet, IdValues
from pipeline.schemas import (CATEGORIES, CHANNELS, DEVICES, ORDER_STATUSES, PAYMENT_METHODS,
                              PROMO_TYPES, TABLE_ORDER)

pd.options.mode.copy_on_write = True
logger = logging.getLogger(__name__)

MIN_VALID_DATE = pd.Timestamp("2015-01-01")
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
EPOCH = np.datetime64("1970-01-01", "D")


# --------------------------------------------------------------------------- helpers
def to_num(s: pd.Series) -> pd.Series:
    """String -> float; blanks and garbage become NaN (never raise)."""
    return pd.to_numeric(s.astype("string").str.strip(), errors="coerce").astype("float64")


def parse_date(s: pd.Series) -> tuple[pd.Series, int]:
    """Parse ISO (YYYY-MM-DD) first, then Indian DD-MM-YYYY.

    Formats are explicit on purpose: guessing would read 05-01-2024 as May 1st
    for some rows and Jan 5th for others. Returns (parsed, n_rows_in_alt_format).
    """
    s = s.astype("string").str.strip()
    parsed = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    alt = parsed.isna() & s.str.match(r"^\d{2}-\d{2}-\d{4}$").fillna(False)
    if alt.any():
        parsed.loc[alt] = pd.to_datetime(s[alt], format="%d-%m-%Y", errors="coerce")
    return parsed, int((alt & parsed.notna()).sum())


def standardise(series: pd.Series, how: str) -> tuple[pd.Series, int]:
    """Strip + recase; returns the new series and how many values changed."""
    s = series.astype("string").str.strip()
    s = {"lower": s.str.lower, "upper": s.str.upper, "title": s.str.title}[how]()
    return s, int((s != series.astype("string")).fillna(False).sum())


class Context:
    """State shared across chunks and tables (all memory-light, see quality.py)."""

    def __init__(self, max_date: pd.Timestamp):
        self.max_date = max_date
        self.seen = defaultdict(IdSet)     # every key that appeared in the raw source
        self.valid = defaultdict(IdSet)    # keys that survived cleaning
        self.order_day = IdValues(np.int32)                    # order_id -> order date (days)
        self.item_day = IdValues(np.int32)                     # order_item_id -> order date
        self.item_value = IdValues(np.float64, missing=np.nan)  # order_item_id -> net line value
        self.coupon_codes: set[str] = set()


class Chunk:
    """One raw chunk moving through the rules."""

    def __init__(self, table: str, raw: pd.DataFrame, report: DQReport):
        self.table, self.raw, self.report = table, raw, report
        self.df = raw.drop(columns="_source_row")

    def reject(self, mask, rule: str) -> None:
        mask = np.asarray(mask, dtype=bool)
        if mask.any():
            self.report.reject(self.table, rule, self.raw.loc[self.df.index[mask]])
            self.df = self.df.loc[~mask]

    def repair(self, n: int, rule: str) -> None:
        self.report.repair(self.table, rule, n)


def days(ts: pd.Series) -> np.ndarray:
    return (ts.to_numpy().astype("datetime64[D]") - EPOCH).astype(np.int32)


# ------------------------------------------------------------------ shared rules
def rule_primary_key(ch: Chunk, ctx: Context, col: str) -> None:
    ids = to_num(ch.df[col])
    ch.reject(ids.isna() | (ids <= 0) | (ids % 1 != 0), f"missing_or_invalid_{col}")
    ids = ids.loc[ch.df.index].astype(np.int64)
    ch.df[col] = ids
    arr = ids.to_numpy()
    # duplicate inside this chunk OR already seen in an earlier chunk
    dup = ids.duplicated().to_numpy() | ctx.seen[ch.table].contains(arr)
    ctx.seen[ch.table].add(arr)
    ch.reject(dup, f"duplicate_{col}")


def rule_foreign_key(ch: Chunk, ctx: Context, col: str, parent: str, *, required: bool,
                     on_orphan: str = "reject") -> None:
    """Check `col` against the cleaned keys of `parent`.

    required=True rejects blanks; on_orphan="null" keeps the row but sets the
    reference to NULL (used where the link is optional, e.g. session.customer_id).
    """
    ids = to_num(ch.df[col])
    if required:
        ch.reject(ids.isna(), f"missing_{col}")
        ids = ids.loc[ch.df.index]
    arr = ids.fillna(-1).to_numpy(np.int64)
    present = ids.notna().to_numpy()
    ok = ctx.valid[parent].contains(arr)
    existed = ctx.seen[parent].contains(arr)
    singular = parent[:-1] if parent.endswith("s") else parent
    if on_orphan == "null":
        bad = present & ~ok
        ids[bad] = np.nan
        ch.repair(int(bad.sum()), f"orphan_{col}_set_null")
        ch.df[col] = ids.astype("Int64")
        return
    parent_rejected = present & ~ok & existed
    orphan = present & ~ok & ~existed
    # record both reasons against the same frame, then drop them together
    for mask, rule in ((parent_rejected, f"parent_{singular}_rejected"), (orphan, f"orphan_{col}")):
        if mask.any():
            ch.report.reject(ch.table, rule, ch.raw.loc[ch.df.index[mask]])
    keep = ~(parent_rejected | orphan)
    ch.df = ch.df.loc[keep]
    ch.df[col] = ids[keep].astype("Int64" if not required else np.int64)


def rule_date(ch: Chunk, ctx: Context, col: str, *, on_bad: str) -> None:
    """Parse a date column; bad/out-of-range values are rejected or set NULL."""
    parsed, n_alt = parse_date(ch.df[col])
    ch.repair(n_alt, f"{col}_dd_mm_yyyy_normalised")
    blank = ch.df[col].astype("string").str.strip().fillna("") == ""
    unparseable = (parsed.isna() & ~blank).to_numpy()
    out_of_range = (parsed.notna() & ((parsed < MIN_VALID_DATE) | (parsed > ctx.max_date))).to_numpy()
    if on_bad == "reject":
        ch.df[col] = parsed
        ch.reject(unparseable | blank.to_numpy(), f"unparseable_{col}")
        out_of_range = (ch.df[col] < MIN_VALID_DATE) | (ch.df[col] > ctx.max_date)
        ch.reject(out_of_range.to_numpy(), f"{col}_out_of_range")
    else:
        parsed[unparseable | out_of_range] = pd.NaT
        ch.repair(int(unparseable.sum() + out_of_range.sum()), f"bad_{col}_set_null")
        ch.df[col] = parsed


def rule_allowed(ch: Chunk, col: str, allowed: set[str], how: str, *, on_bad: str,
                 default: str | None = None, mapping: dict | None = None) -> None:
    """Standardise casing/whitespace, then enforce an allowed set of values."""
    s, _ = standardise(ch.df[col], how)
    if mapping:
        s = s.replace(mapping)
    changed = int((s != ch.df[col].astype("string")).fillna(False).sum())
    ch.repair(changed, f"{col}_standardised")
    bad = ~s.isin(allowed).to_numpy()
    if on_bad == "reject":
        ch.df[col] = s
        ch.reject(bad, f"invalid_{col}")
    else:
        s[bad] = default
        ch.repair(int(bad.sum()), f"invalid_{col}_set_{default}")
        ch.df[col] = s


# ------------------------------------------------------------------ table cleaners
def clean_customers(ch: Chunk, ctx: Context) -> None:
    rule_primary_key(ch, ctx, "customer_id")
    d = ch.df
    email = d["email"].astype("string").str.strip().str.lower()
    blank = email.fillna("") == ""
    malformed = ~blank & ~email.str.match(EMAIL_RE).fillna(False)
    email[blank | malformed] = pd.NA
    ch.repair(int(blank.sum()), "missing_email_kept_as_null")
    ch.repair(int(malformed.sum()), "malformed_email_set_null")
    d["email"] = email
    d["city"], n = standardise(d["city"], "title"); ch.repair(n, "city_standardised")
    d["state"], _ = standardise(d["state"], "upper")
    for c in ("first_name", "last_name"):
        d[c] = d[c].astype("string").str.strip().str.title()
    gender, _ = standardise(d["gender"], "upper")
    d["gender"] = gender.where(gender.isin(["F", "M"]))
    ch.df = d
    rule_date(ch, ctx, "signup_date", on_bad="null")
    rule_allowed(ch, "acquisition_channel", CHANNELS, "lower", on_bad="default", default="unknown")
    ctx.valid["customers"].add(ch.df["customer_id"].to_numpy())


def clean_products(ch: Chunk, ctx: Context) -> None:
    # products is a small dimension (one chunk), so batch-level medians are table-level here
    rule_primary_key(ch, ctx, "product_id")
    mrp = to_num(ch.df["mrp"])
    ch.reject((mrp.isna() | (mrp <= 0)).to_numpy(), "invalid_mrp")
    d = ch.df
    d["mrp"] = mrp.loc[d.index]
    canonical = {c.lower(): c for c in CATEGORIES}
    cat_key = d["category"].astype("string").str.strip().str.lower()
    new_cat = cat_key.map(canonical).fillna("Other")
    ch.repair(int((new_cat != d["category"]).sum()), "category_standardised")
    d["category"] = new_cat
    brand = d["brand"].astype("string").str.strip()
    no_brand = brand.fillna("") == ""
    d["brand"] = brand.mask(no_brand, "Unknown")
    ch.repair(int(no_brand.sum()), "missing_brand_set_unknown")
    for c in ("product_name", "sub_category", "style"):
        d[c] = d[c].astype("string").str.strip()
    # Missing cost: impute MRP x the category's median cost/MRP ratio so margin can
    # still be computed, and count it so the imputation is visible.
    cost = to_num(d["cost_price"])
    bad = cost.isna() | (cost <= 0)
    ratio = (cost / d["mrp"]).where(~bad)
    median_ratio = ratio.groupby(d["category"]).transform("median").fillna(ratio.median())
    d["cost_price"] = cost.mask(bad, (d["mrp"] * median_ratio).round(2))
    ch.repair(int(bad.sum()), "cost_price_imputed_category_median_ratio")
    ch.df = d
    ctx.valid["products"].add(d["product_id"].to_numpy())


def clean_promotions(ch: Chunk, ctx: Context) -> None:
    rule_primary_key(ch, ctx, "promotion_id")
    d = ch.df
    d["promo_code"] = d["promo_code"].astype("string").str.strip().str.upper()
    d["promo_name"] = d["promo_name"].astype("string").str.strip()
    ch.df = d
    rule_allowed(ch, "promo_type", PROMO_TYPES, "lower", on_bad="reject")
    d = ch.df
    start, _ = parse_date(d["start_date"])
    end, _ = parse_date(d["end_date"])
    pct = to_num(d["discount_pct"])
    ch.reject((start.isna() | end.isna() | (end < start)).to_numpy(), "invalid_promo_dates")
    idx = ch.df.index
    ch.reject((pct[idx].isna() | (pct[idx] < 0) | (pct[idx] > 0.9)).to_numpy(), "invalid_discount_pct")
    d = ch.df
    d["start_date"], d["end_date"] = start[d.index], end[d.index]
    d["discount_pct"] = pct[d.index]
    d["max_discount"] = to_num(d["max_discount"])
    d["min_order_value"] = to_num(d["min_order_value"])
    ch.df = d
    ctx.valid["promotions"].add(d["promotion_id"].to_numpy())
    ctx.coupon_codes |= set(d.loc[d["promo_type"] == "coupon", "promo_code"])


def clean_sessions(ch: Chunk, ctx: Context) -> None:
    rule_primary_key(ch, ctx, "session_id")
    rule_date(ch, ctx, "session_date", on_bad="reject")
    # blank channels fail the allowed-set check and become 'unknown'
    rule_allowed(ch, "channel", CHANNELS | {"unknown"}, "lower", on_bad="default", default="unknown")
    rule_allowed(ch, "device", DEVICES | {"unknown"}, "lower", on_bad="default", default="unknown")
    rule_foreign_key(ch, ctx, "customer_id", "customers", required=False, on_orphan="null")
    pages = to_num(ch.df["pages_viewed"])
    ch.df["pages_viewed"] = pages.where(pages >= 0).astype("Int64")
    ctx.valid["sessions"].add(ch.df["session_id"].to_numpy())


def clean_orders(ch: Chunk, ctx: Context) -> None:
    rule_primary_key(ch, ctx, "order_id")
    rule_foreign_key(ch, ctx, "customer_id", "customers", required=True)
    rule_date(ch, ctx, "order_date", on_bad="reject")
    rule_allowed(ch, "order_status", ORDER_STATUSES, "lower", on_bad="reject")
    rule_allowed(ch, "channel", CHANNELS | {"unknown"}, "lower", on_bad="default", default="unknown")
    rule_allowed(ch, "device", DEVICES | {"unknown"}, "lower", on_bad="default", default="unknown")
    pay_map = {p.lower(): p for p in PAYMENT_METHODS}
    rule_allowed(ch, "payment_method", PAYMENT_METHODS | {"unknown"}, "lower", on_bad="default",
                 default="unknown", mapping=pay_map)
    rule_foreign_key(ch, ctx, "session_id", "sessions", required=False, on_orphan="null")
    d = ch.df
    code = d["coupon_code"].astype("string").str.strip()
    upper = code.str.upper()
    ch.repair(int((upper != code).fillna(False).sum()), "coupon_code_standardised")
    upper = upper.mask(upper.fillna("") == "")
    unknown = upper.notna() & ~upper.isin(ctx.coupon_codes)
    ch.repair(int(unknown.sum()), "unknown_coupon_code_set_null")
    d["coupon_code"] = upper.mask(unknown)
    ch.df = d
    ctx.valid["orders"].add(d["order_id"].to_numpy())
    ctx.order_day.set(d["order_id"].to_numpy(), days(d["order_date"]))


def clean_order_items(ch: Chunk, ctx: Context) -> None:
    rule_primary_key(ch, ctx, "order_item_id")
    rule_foreign_key(ch, ctx, "order_id", "orders", required=True)
    rule_foreign_key(ch, ctx, "product_id", "products", required=True)
    d = ch.df
    qty, mrp, sp = to_num(d["quantity"]), to_num(d["mrp"]), to_num(d["selling_price"])
    for mask, rule in (
        (qty.isna() | (qty <= 0) | (qty % 1 != 0), "non_positive_quantity"),
        (mrp.isna() | (mrp <= 0), "invalid_mrp"),
        (sp.isna(), "missing_selling_price"),
        (sp <= 0, "non_positive_selling_price"),
        (sp > mrp, "selling_price_above_mrp"),
    ):
        ch.reject(mask.loc[ch.df.index].to_numpy(), rule)
    d = ch.df
    d["quantity"] = qty[d.index].astype(np.int64)
    d["mrp"], d["selling_price"] = mrp[d.index], sp[d.index]
    disc = to_num(d["coupon_discount"])
    ch.repair(int(disc.isna().sum()), "missing_coupon_discount_set_0")
    disc = disc.fillna(0.0)
    ch.df = d
    ch.reject(((disc < 0) | (disc > d["selling_price"] * d["quantity"] + 0.01)).to_numpy(),
              "invalid_coupon_discount")
    d = ch.df
    d["coupon_discount"] = disc[d.index]
    ch.df = d
    ids = d["order_item_id"].to_numpy()
    ctx.valid["order_items"].add(ids)
    ctx.item_day.set(ids, ctx.order_day.get(d["order_id"].to_numpy()))
    ctx.item_value.set(ids, (d["selling_price"] * d["quantity"] - d["coupon_discount"]).to_numpy())


def clean_returns(ch: Chunk, ctx: Context) -> None:
    rule_primary_key(ch, ctx, "return_id")
    rule_foreign_key(ch, ctx, "order_item_id", "order_items", required=True)
    # an order line can only be returned once
    item = ch.df["order_item_id"].to_numpy()
    dup = pd.Series(item).duplicated().to_numpy() | ctx.seen["returns_item"].contains(item)
    ctx.seen["returns_item"].add(item)
    ch.reject(dup, "duplicate_return_for_item")
    rule_date(ch, ctx, "return_date", on_bad="reject")
    d = ch.df
    item = d["order_item_id"].to_numpy()
    ch.reject(days(d["return_date"]) < ctx.item_day.get(item), "return_before_order")
    d = ch.df
    refund = to_num(d["refund_amount"])
    line_value = pd.Series(ctx.item_value.get(d["order_item_id"].to_numpy()), index=d.index)
    ch.reject((refund.isna() | (refund < 0)).to_numpy(), "invalid_refund_amount")
    keep = ch.df.index
    ch.reject((refund[keep] > line_value[keep] + 0.01).to_numpy(), "refund_exceeds_line_value")
    d = ch.df
    d["refund_amount"] = refund[d.index]
    d["return_reason"] = d["return_reason"].astype("string").str.strip()
    ch.df = d
    ctx.valid["returns"].add(d["return_id"].to_numpy())


CLEANERS = {
    "customers": clean_customers, "products": clean_products, "promotions": clean_promotions,
    "sessions": clean_sessions, "orders": clean_orders, "order_items": clean_order_items,
    "returns": clean_returns,
}


def run(staging_dir: Path = config.STAGING_DIR, clean_dir: Path = config.CLEAN_DIR,
        rejected_dir: Path = config.REJECTED_DIR, reports_dir: Path = config.REPORTS_DIR,
        max_date: pd.Timestamp | None = None) -> DQReport:
    max_date = max_date or pd.Timestamp(date.today())
    rejected_dir.mkdir(parents=True, exist_ok=True)
    for old in rejected_dir.glob("*_rejected.csv"):   # keep .gitkeep, replace last run's files
        old.unlink()
    report, ctx = DQReport(rejected_dir), Context(max_date)
    for table in TABLE_ORDER:
        out_dir = clean_dir / table
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)
        for i, raw in enumerate(iter_staged(table, staging_dir)):
            report.rows_in[table] += len(raw)
            ch = Chunk(table, raw, report)
            CLEANERS[table](ch, ctx)
            report.rows_out[table] += len(ch.df)
            ch.df.reset_index(drop=True).to_parquet(out_dir / f"part-{i:05d}.parquet", index=False)
        rej = sum(report.rejected[table].values())
        logger.info("  cleaned  %-12s %12s in -> %12s out (%s rejected)", table,
                    f"{report.rows_in[table]:,}", f"{report.rows_out[table]:,}", f"{rej:,}")
    path = report.write(reports_dir, staging_dir.parent / "raw" / "_generation_manifest.json")
    logger.info("  data-quality report -> %s", path.relative_to(config.ROOT) if path.is_relative_to(config.ROOT) else path)
    return report


def iter_clean(table: str, clean_dir: Path = config.CLEAN_DIR):
    parts = sorted((clean_dir / table).glob("part-*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No clean data for {table}. Run --stage clean first.")
    for p in parts:
        yield pd.read_parquet(p)
