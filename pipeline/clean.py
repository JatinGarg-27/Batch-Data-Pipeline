"""
Validation & cleaning stage.

Takes the raw DataFrames from the ingestion stage and produces
clean, typed DataFrames that are safe to load into the relational
database: dedupe, required-field checks, type coercion, date
normalization, and foreign-key sanity checks.

Every drop is logged with a reason so data-quality issues in the
source are visible rather than silently swallowed.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

VALID_STATUSES = {"pending", "completed", "cancelled", "shipped"}


def _log_drop(entity: str, reason: str, before: int, after: int) -> None:
    dropped = before - after
    if dropped:
        logger.info("  [%s] dropped %d row(s): %s", entity, dropped, reason)


def _parse_date(series: pd.Series) -> pd.Series:
    # Raw dates arrive in a mix of ISO (YYYY-MM-DD) and US slash (MM/DD/YYYY)
    # formats -- try ISO first, then fall back to slash format.
    parsed = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
    fallback_mask = parsed.isna()
    if fallback_mask.any():
        parsed.loc[fallback_mask] = pd.to_datetime(
            series[fallback_mask], format="%m/%d/%Y", errors="coerce"
        )
    return parsed


def clean_customers(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    before = len(df)

    df = df.drop_duplicates()
    _log_drop("customers", "exact duplicate rows", before, len(df))

    before = len(df)
    df["email"] = df["email"].str.strip().str.lower()
    df = df[(df["customer_id"] != "") & (df["email"] != "")]
    _log_drop("customers", "missing customer_id/email", before, len(df))

    before = len(df)
    df["customer_id"] = pd.to_numeric(df["customer_id"], errors="coerce")
    df = df.dropna(subset=["customer_id"])
    df["customer_id"] = df["customer_id"].astype(int)
    _log_drop("customers", "non-numeric customer_id", before, len(df))

    df["city"] = df["city"].str.strip().str.title()
    df["state"] = df["state"].str.strip().str.upper()

    before = len(df)
    df["signup_date"] = _parse_date(df["signup_date"])
    df = df.dropna(subset=["signup_date"])
    _log_drop("customers", "unparseable signup_date", before, len(df))

    before = len(df)
    df = df.drop_duplicates(subset=["customer_id"], keep="first")
    _log_drop("customers", "duplicate customer_id after cleaning", before, len(df))

    df["signup_date"] = df["signup_date"].dt.strftime("%Y-%m-%d")
    return df[["customer_id", "first_name", "last_name", "email", "city", "state", "signup_date"]]


def clean_products(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()

    before = len(df)
    df["product_id"] = pd.to_numeric(df["product_id"], errors="coerce")
    df = df.dropna(subset=["product_id"])
    df["product_id"] = df["product_id"].astype(int)
    _log_drop("products", "non-numeric product_id", before, len(df))

    before = len(df)
    df = df.drop_duplicates(subset=["product_id"], keep="first")
    _log_drop("products", "duplicate product_id", before, len(df))

    before = len(df)
    df["product_name"] = df["product_name"].str.strip()
    df = df[df["product_name"] != ""]
    _log_drop("products", "missing product_name", before, len(df))

    df["category"] = df["category"].str.strip().replace("", "Uncategorized")

    before = len(df)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df = df[df["unit_price"] > 0]
    _log_drop("products", "missing/non-positive unit_price", before, len(df))

    return df[["product_id", "product_name", "category", "unit_price"]]


def clean_orders(raw: pd.DataFrame, valid_customer_ids: set[int]) -> pd.DataFrame:
    df = raw.copy()

    before = len(df)
    df["order_id"] = pd.to_numeric(df["order_id"], errors="coerce")
    df["customer_id"] = pd.to_numeric(df["customer_id"], errors="coerce")
    df = df.dropna(subset=["order_id", "customer_id"])
    df["order_id"] = df["order_id"].astype(int)
    df["customer_id"] = df["customer_id"].astype(int)
    _log_drop("orders", "missing/non-numeric order_id or customer_id", before, len(df))

    before = len(df)
    df = df[df["customer_id"].isin(valid_customer_ids)]
    _log_drop("orders", "orphan customer_id (no matching customer)", before, len(df))

    before = len(df)
    df["status"] = df["status"].str.strip().str.lower()
    df = df[df["status"].isin(VALID_STATUSES)]
    _log_drop("orders", "unrecognized status value", before, len(df))

    before = len(df)
    df["order_date"] = _parse_date(df["order_date"])
    df = df.dropna(subset=["order_date"])
    _log_drop("orders", "unparseable order_date", before, len(df))

    before = len(df)
    df = df.drop_duplicates(subset=["order_id"], keep="first")
    _log_drop("orders", "duplicate order_id", before, len(df))

    df["order_date"] = df["order_date"].dt.strftime("%Y-%m-%d")
    return df[["order_id", "customer_id", "order_date", "status"]]


def clean_order_items(
    raw: pd.DataFrame, valid_order_ids: set[int], valid_product_ids: set[int]
) -> pd.DataFrame:
    df = raw.copy()

    before = len(df)
    df = df.drop_duplicates()
    _log_drop("order_items", "exact duplicate rows", before, len(df))

    before = len(df)
    for col in ["order_item_id", "order_id", "product_id", "quantity"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df = df.dropna(subset=["order_item_id", "order_id", "product_id", "quantity", "unit_price"])
    for col in ["order_item_id", "order_id", "product_id", "quantity"]:
        df[col] = df[col].astype(int)
    _log_drop("order_items", "missing/non-numeric fields", before, len(df))

    before = len(df)
    df = df[(df["order_id"].isin(valid_order_ids)) & (df["product_id"].isin(valid_product_ids))]
    _log_drop("order_items", "orphan order_id/product_id", before, len(df))

    before = len(df)
    df = df[df["quantity"] > 0]
    _log_drop("order_items", "non-positive quantity", before, len(df))

    before = len(df)
    df = df.drop_duplicates(subset=["order_item_id"], keep="first")
    _log_drop("order_items", "duplicate order_item_id", before, len(df))

    return df[["order_item_id", "order_id", "product_id", "quantity", "unit_price"]]


def clean_all(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Clean every entity in dependency order (customers/products first,
    since orders/order_items are validated against their id sets)."""
    customers = clean_customers(frames["customers"])
    products = clean_products(frames["products"])
    orders = clean_orders(frames["orders"], set(customers["customer_id"]))
    order_items = clean_order_items(
        frames["order_items"], set(orders["order_id"]), set(products["product_id"])
    )
    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "order_items": order_items,
    }
