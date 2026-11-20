"""
Raw source contracts: the columns each raw CSV must have, and the order the
tables are processed in (parents before children, so foreign keys can be
checked against already-cleaned parents).
"""

RAW_SCHEMAS: dict[str, list[str]] = {
    "customers": ["customer_id", "first_name", "last_name", "email", "gender", "city",
                  "state", "signup_date", "acquisition_channel"],
    "products": ["product_id", "product_name", "brand", "category", "sub_category", "style",
                 "mrp", "cost_price"],
    "promotions": ["promotion_id", "promo_code", "promo_name", "promo_type", "start_date",
                   "end_date", "discount_pct", "max_discount", "min_order_value"],
    "sessions": ["session_id", "customer_id", "session_date", "channel", "device",
                 "pages_viewed"],
    "orders": ["order_id", "customer_id", "session_id", "order_date", "order_status", "channel",
               "device", "payment_method", "coupon_code"],
    "order_items": ["order_item_id", "order_id", "product_id", "quantity", "mrp",
                    "selling_price", "coupon_discount"],
    "returns": ["return_id", "order_item_id", "return_date", "return_reason", "refund_amount"],
}

# Dependency order: every table's parents appear before it.
TABLE_ORDER = list(RAW_SCHEMAS)

CATEGORIES = ["Topwear", "Bottomwear", "Dresses", "Ethnic Wear", "Footwear", "Sportswear",
              "Accessories", "Beauty"]
ORDER_STATUSES = {"delivered", "shipped", "cancelled"}
CHANNELS = {"organic_search", "paid_search", "social", "referral", "direct", "email"}
DEVICES = {"app", "mweb", "desktop"}
PAYMENT_METHODS = {"COD", "UPI", "card", "wallet"}
PROMO_TYPES = {"sale_event", "coupon"}
