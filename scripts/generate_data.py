"""
Synthetic fashion e-commerce data generator.

    python scripts/generate_data.py                 # ~1M order_items (default)
    python scripts/generate_data.py --rows 50000    # quick small run

THE DATA IS SYNTHETIC. Every number it produces comes from the
assumptions written in this file (demand curves, conversion rates,
return rates...). It exists so the pipeline has realistic *shape* to work
on: festive-sale spikes, weekend seasonality, a long tail of products,
repeat vs new customers, category-specific returns, cost prices and
discounts that public datasets don't have.

Output: data/raw/*.csv (7 tables) + data/raw/_generation_manifest.json,
which records exactly how many dirty rows were injected per issue so the
cleaning stage's catch rate can be checked.

Everything is vectorised with NumPy and driven by one seeded
np.random.Generator, so the same --seed and --rows give byte-identical files.
Dates are handled internally as an integer "day index" (0 = START) which
keeps the maths simple and fast.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
START, END = "2024-01-01", "2025-12-31"

# --------------------------------------------------------------------------
# Business calendar. Sale events drive both demand (multiplier) and deeper
# markdowns (extra discount on top of the product's everyday markdown).
# (code, name, start, end, demand multiplier, extra markdown)
# --------------------------------------------------------------------------
SALE_EVENTS = [
    ("RDS24", "Republic Day Sale 2024", "2024-01-20", "2024-01-23", 1.6, 0.05),
    ("EORS24S", "End of Reason Sale - Summer 2024", "2024-06-01", "2024-06-06", 2.8, 0.12),
    ("BFD24", "Big Fashion Days 2024", "2024-10-03", "2024-10-10", 3.4, 0.15),
    ("EORS24W", "End of Reason Sale - Winter 2024", "2024-12-07", "2024-12-12", 2.6, 0.12),
    ("RDS25", "Republic Day Sale 2025", "2025-01-18", "2025-01-21", 1.6, 0.05),
    ("EORS25S", "End of Reason Sale - Summer 2025", "2025-06-05", "2025-06-10", 2.9, 0.12),
    ("BFD25", "Big Fashion Days 2025", "2025-09-20", "2025-09-27", 3.6, 0.15),
    ("EORS25W", "End of Reason Sale - Winter 2025", "2025-12-06", "2025-12-11", 2.7, 0.12),
]
# Coupons: (code, name, start, end, pct, max discount, min order value)
COUPONS = [
    ("NEW15", "New customer 15% off", START, END, 0.15, 300, 499),
    ("STYLE10", "10% off on 999+", START, END, 0.10, 250, 999),
    ("FEST24", "Festive 20% off 2024", "2024-09-15", "2024-11-15", 0.20, 500, 1499),
    ("FEST25", "Festive 20% off 2025", "2025-09-10", "2025-11-10", 0.20, 500, 1499),
]

DOW_FACTOR = np.array([0.92, 0.88, 0.90, 0.93, 1.02, 1.22, 1.28])          # Mon..Sun
MONTH_FACTOR = np.array([0.95, 0.85, 0.92, 0.95, 1.00, 1.05, 0.95, 0.92,   # Jan..Dec
                         1.00, 1.18, 1.15, 1.08])

# --------------------------------------------------------------------------
# Catalogue: category -> [(sub_category, mrp_low, mrp_high, styles, return_rate)]
# Return rates are the generator's ASSUMPTION (fit/size-driven categories high).
# --------------------------------------------------------------------------
CATALOG = {
    "Topwear": [("T-Shirts", 399, 1499, ["Casual", "Streetwear", "Athleisure"], 0.09),
                ("Shirts", 799, 2999, ["Casual", "Formal"], 0.11),
                ("Sweatshirts", 999, 3499, ["Casual", "Streetwear"], 0.10)],
    "Bottomwear": [("Jeans", 999, 3999, ["Casual", "Streetwear"], 0.21),
                   ("Trousers", 899, 2999, ["Formal", "Casual"], 0.17),
                   ("Shorts", 399, 1299, ["Casual", "Athleisure"], 0.10)],
    "Dresses": [("Maxi Dresses", 999, 4499, ["Party", "Casual"], 0.29),
                ("Bodycon Dresses", 799, 2999, ["Party"], 0.32),
                ("A-Line Dresses", 799, 2999, ["Casual"], 0.26)],
    "Ethnic Wear": [("Kurtas", 599, 2999, ["Ethnic"], 0.14),
                    ("Sarees", 999, 7999, ["Ethnic"], 0.12),
                    ("Lehengas", 2999, 14999, ["Ethnic"], 0.16)],
    "Footwear": [("Sneakers", 1499, 7999, ["Streetwear", "Athleisure"], 0.22),
                 ("Formal Shoes", 1999, 5999, ["Formal"], 0.20),
                 ("Heels", 999, 3999, ["Party"], 0.26),
                 ("Sandals", 499, 1999, ["Casual"], 0.15)],
    "Sportswear": [("Track Pants", 699, 2499, ["Athleisure"], 0.09),
                   ("Sports Bras", 499, 1999, ["Athleisure"], 0.12),
                   ("Running Tees", 499, 1799, ["Athleisure"], 0.08)],
    "Accessories": [("Watches", 1499, 9999, ["Casual", "Formal"], 0.06),
                    ("Handbags", 999, 5999, ["Party", "Casual"], 0.07),
                    ("Belts", 399, 1499, ["Formal", "Casual"], 0.04),
                    ("Sunglasses", 699, 3999, ["Casual"], 0.05)],
    "Beauty": [("Lipsticks", 299, 1499, ["Everyday"], 0.02),
               ("Skincare", 299, 1999, ["Everyday"], 0.02),
               ("Fragrances", 699, 3999, ["Everyday"], 0.03)],
}
CATEGORY_DEMAND = {"Topwear": 1.3, "Bottomwear": 1.1, "Dresses": 0.9, "Ethnic Wear": 1.0,
                   "Footwear": 1.0, "Sportswear": 0.6, "Accessories": 0.6, "Beauty": 0.5}

# Invented brand names (no real brands). tier -> price multiplier, cost ratio, markdown
BRANDS = ["Urban Thread", "Kaveri", "Northpeak", "Saffron Lane", "Indigo Mile", "Brick & Loom",
          "Monsoon Edit", "Velvet Crow", "Tara Jaipur", "Coastline", "Highstreet Co", "Neon Fable",
          "Mulberry Row", "Rangrez", "Stride Lab", "Peakform", "Lumen", "Old Delhi Mills",
          "Chai & Denim", "Paper Kite", "Sole Theory", "Maple & Moss", "Ironleaf", "Dhaaga",
          "Blue Tusk", "Fernway", "Zest Active", "Kora Studio", "Hazel Street", "Ember & Ash",
          "Nomad Knit", "Silk Route", "Glow Theory", "Pebble", "Banyan", "Copperfield",
          "Wildgrass", "Moti Bagh", "Echo Park", "Tidal", "Avani", "Sutra", "Fable & Fig",
          "Grey Harbour", "Rustic Rani"]
TIERS = {"budget": (0.80, 0.40, (0.30, 0.60)), "mid": (1.00, 0.35, (0.25, 0.55)),
         "premium": (1.60, 0.30, (0.10, 0.40))}
ADJECTIVES = ["Classic", "Slim Fit", "Printed", "Solid", "Oversized", "Embroidered", "Textured",
              "Relaxed", "Striped", "Graphic", "Floral", "Regular Fit", "Self-Design", "Woven"]

CITIES = [("Bengaluru", "KA", 9), ("Mumbai", "MH", 9), ("Delhi", "DL", 9), ("Hyderabad", "TG", 7),
          ("Chennai", "TN", 6), ("Pune", "MH", 6), ("Kolkata", "WB", 5), ("Ahmedabad", "GJ", 4),
          ("Gurugram", "HR", 4), ("Noida", "UP", 3), ("Jaipur", "RJ", 3), ("Lucknow", "UP", 3),
          ("Chandigarh", "CH", 2), ("Kochi", "KL", 2), ("Indore", "MP", 2), ("Surat", "GJ", 2),
          ("Nagpur", "MH", 2), ("Coimbatore", "TN", 2), ("Bhubaneswar", "OD", 1.5),
          ("Guwahati", "AS", 1.5), ("Patna", "BR", 1.5), ("Bhopal", "MP", 1.5)]
FIRST_NAMES = ["Aarav", "Aditi", "Ananya", "Arjun", "Diya", "Ishaan", "Kabir", "Kavya", "Meera",
               "Neha", "Nikhil", "Priya", "Rahul", "Riya", "Rohan", "Saanvi", "Sanjay", "Shreya",
               "Tanvi", "Varun", "Vivek", "Zoya", "Aman", "Pooja", "Karan", "Isha", "Farhan",
               "Nandini", "Harsh", "Simran"]
LAST_NAMES = ["Sharma", "Verma", "Iyer", "Khan", "Gupta", "Nair", "Reddy", "Chopra", "Malhotra",
              "Bose", "Patel", "Singh", "Das", "Mehta", "Joshi", "Rao", "Kulkarni", "Banerjee",
              "Menon", "Agarwal"]

ACQ_CHANNELS = ["organic_search", "paid_search", "social", "referral", "direct"]
ACQ_PROBS = [0.30, 0.24, 0.22, 0.08, 0.16]
# Expected repeat orders over the 2-year horizon by acquisition channel (assumption:
# social-acquired customers churn faster, referral/direct are stickier).
ACQ_REPEAT_LAMBDA = {"organic_search": 2.4, "paid_search": 1.9, "social": 1.2,
                     "referral": 2.7, "direct": 3.0}
SESSION_CHANNELS = ["organic_search", "paid_search", "social", "referral", "direct", "email"]
REPEAT_CHANNEL_PROBS = [0.20, 0.12, 0.10, 0.03, 0.35, 0.20]
# Session -> order conversion rate by channel (assumption, app-heavy fashion traffic)
CHANNEL_CR = np.array([0.060, 0.045, 0.024, 0.065, 0.100, 0.085])
DEVICES = ["app", "mweb", "desktop"]
PAYMENTS = ["COD", "UPI", "card", "wallet"]
RETURN_REASONS_SIZE = ["Size too small", "Size too large"]
RETURN_REASONS_OTHER = ["Quality not as expected", "Did not like the style",
                        "Damaged or defective", "Colour different from image"]
SIZE_SENSITIVE = {"Bottomwear", "Dresses", "Footwear", "Topwear", "Sportswear"}


def build_calendar():
    dates = pd.date_range(START, END, freq="D")
    n = len(dates)
    event_idx = np.full(n, -1)
    event_mult = np.ones(n)
    event_markdown = np.zeros(n)
    for i, (_, _, s, e, mult, md) in enumerate(SALE_EVENTS):
        m = (dates >= s) & (dates <= e)
        event_idx[m], event_mult[m], event_markdown[m] = i, mult, md
    base = DOW_FACTOR[dates.dayofweek.values] * MONTH_FACTOR[dates.month.values - 1]
    return dates, event_idx, event_mult, event_markdown, base


def make_products(rng, n_products):
    rows = [(cat, *sub) for cat, subs in CATALOG.items() for sub in subs]
    sub_idx = rng.integers(0, len(rows), n_products)
    n_brands = len(BRANDS)
    brand_pop = 1.0 / np.arange(1, n_brands + 1) ** 0.9            # Zipf-like brand popularity
    tier_names = np.array(list(TIERS))
    brand_tier = rng.choice(tier_names, n_brands, p=[0.35, 0.45, 0.20])
    brand_idx = rng.choice(n_brands, n_products, p=brand_pop / brand_pop.sum())
    tier = brand_tier[brand_idx]
    price_mult = np.array([TIERS[t][0] for t in tier])
    cost_ratio = np.array([TIERS[t][1] for t in tier]) * rng.uniform(0.9, 1.1, n_products)
    md_lo = np.array([TIERS[t][2][0] for t in tier])
    md_hi = np.array([TIERS[t][2][1] for t in tier])

    lo = np.array([rows[i][2] for i in sub_idx])
    hi = np.array([rows[i][3] for i in sub_idx])
    # MRPs in fashion end in 9 (e.g. 1299); round to nearest 100 then subtract 1
    mrp = np.round(rng.uniform(lo, hi) * price_mult / 100) * 100 - 1
    mrp = np.maximum(mrp, 199)
    cost = np.round(mrp * cost_ratio, 2)
    markdown = rng.uniform(md_lo, md_hi)

    style = np.array([rows[i][4][rng.integers(len(rows[i][4]))] for i in sub_idx])
    category = np.array([rows[i][0] for i in sub_idx])
    sub_category = np.array([rows[i][1] for i in sub_idx])
    adjective = np.array(ADJECTIVES)[rng.integers(0, len(ADJECTIVES), n_products)]
    brand = np.array(BRANDS)[brand_idx]
    name = pd.Series(brand) + " " + pd.Series(adjective) + " " + pd.Series(sub_category)

    # Long tail: lognormal per-SKU popularity x brand popularity x category demand,
    # damped by price (a Rs 12,000 lehenga sells fewer units than a Rs 600 tee).
    popularity = (rng.lognormal(0, 1.1, n_products) * brand_pop[brand_idx]
                  * np.array([CATEGORY_DEMAND[c] for c in category])
                  * (mrp / 1000.0) ** -0.8)
    return_rate = np.array([rows[i][5] for i in sub_idx])
    return pd.DataFrame({
        "product_id": np.arange(1, n_products + 1), "product_name": name.values,
        "brand": brand, "category": category, "sub_category": sub_category, "style": style,
        "mrp": mrp, "cost_price": cost,
    }), popularity, markdown, return_rate


def seasonal_category_multiplier(products, month, is_bfd):
    """Per-product demand multiplier for a given month / event (shifts category mix)."""
    m = np.ones(len(products))
    sub, cat = products["sub_category"].values, products["category"].values
    if month in (11, 12, 1, 2):
        m[sub == "Sweatshirts"] = 2.5
    elif month not in (3, 10):
        m[sub == "Sweatshirts"] = 0.35
    if month in (3, 4, 5, 6):
        m[np.isin(sub, ["Shorts", "Sandals", "A-Line Dresses"])] *= 1.6
    if month in (10, 11):
        m[cat == "Ethnic Wear"] *= 1.8      # Navratri / Diwali / wedding season
    if is_bfd:
        m[cat == "Ethnic Wear"] *= 2.0
    return m


def simulate_customers(rng, n, acq_weight, thin_weight):
    """Signup + order dates for n customers. Returns customer frame + order arrays."""
    D = len(acq_weight)
    p = acq_weight / acq_weight.sum()
    signup = np.sort(rng.choice(D, n, p=p))                     # ids assigned by signup order
    channel = rng.choice(len(ACQ_CHANNELS), n, p=ACQ_PROBS)
    purchases = rng.random(n) < 0.88                            # 12% register but never buy
    first = np.minimum(signup + rng.geometric(0.45, n) - 1, D - 1)

    # Repeat orders: Poisson count; each lands at first + 7 + Exp(tau) days, accepted
    # with probability w(day)/max(w) ("thinning") so repeats also cluster on sale days.
    # Slots that fall after END are censored -- late cohorts naturally have fewer repeats.
    lam = np.array([ACQ_REPEAT_LAMBDA[ACQ_CHANNELS[c]] for c in channel])
    lam = lam * rng.lognormal(-0.4, 0.9, n)                     # heterogeneous loyalty
    k = np.where(purchases, rng.poisson(lam), 0)
    tau = rng.lognormal(np.log(170), 0.5, n)
    owner = np.repeat(np.arange(n), k)
    days = np.full(owner.size, -1)
    pending = np.arange(owner.size)
    wmax = thin_weight.max()
    w_future = thin_weight.mean()       # assumed demand weight for days after END
    for _ in range(80):
        if pending.size == 0:
            break
        o = owner[pending]
        cand = first[o] + 7 + rng.exponential(tau[o]).astype(int)
        inside = cand < D
        u = rng.random(pending.size)
        # Thinning must treat days after END like any other day (accept with
        # their own weight) -- otherwise every retry is a fresh chance to fall
        # off the end, and later cohorts would lose far more repeat orders.
        acc_in = inside & (u < thin_weight[np.minimum(cand, D - 1)] / wmax)
        acc_out = ~inside & (u < w_future / wmax)              # accepted, but after END: censored
        days[pending[acc_in]] = cand[acc_in]
        pending = pending[~(acc_in | acc_out)]
    keep = days >= 0
    order_cust = np.concatenate([np.where(purchases)[0], owner[keep]])
    order_day = np.concatenate([first[purchases], days[keep]])
    is_first = np.concatenate([np.ones(purchases.sum(), bool), np.zeros(keep.sum(), bool)])
    return signup, channel, order_cust, order_day, is_first


def generate(rows: int, seed: int):
    rng = np.random.default_rng(seed)
    dates, event_idx, event_mult, event_md, base = build_calendar()
    D = len(dates)
    t = np.arange(D) / D
    # New-customer acquisition grows ~40% over 2 years and spikes harder in sales.
    acq_weight = base * (1 + 0.4 * t) * event_mult ** 1.15
    thin_weight = base * event_mult
    is_event = event_idx >= 0
    items_lambda = 0.55 + 0.35 * is_event                     # bigger baskets in sales

    # ---- calibrate customer count from a pilot so we land near `rows` items
    pilot_n = 20000
    _, _, pc, pd_, _ = simulate_customers(np.random.default_rng(seed + 1), pilot_n,
                                          acq_weight, thin_weight)
    items_per_cust = (1 + np.minimum(rng.poisson(items_lambda[pd_]), 5)).sum() / pilot_n
    n_customers = int(np.ceil(rows / items_per_cust * 1.04))

    signup, acq_ch, order_cust, order_day, is_first = simulate_customers(
        rng, n_customers, acq_weight, thin_weight)
    n_items = 1 + np.minimum(rng.poisson(items_lambda[order_day]), 5)

    # Trim whole random orders so the clean total is exactly `rows` items
    perm = rng.permutation(order_day.size)
    csum = np.cumsum(n_items[perm])
    keep_n = np.searchsorted(csum, rows, side="left") + 1
    sel = np.sort(perm[:keep_n])
    order_cust, order_day, is_first, n_items = (order_cust[sel], order_day[sel],
                                                is_first[sel], n_items[sel])
    overshoot = n_items.sum() - rows
    if overshoot > 0:                                          # shave the excess off one order
        j = np.argmax(n_items > overshoot)
        n_items[j] -= overshoot
    # is_first must mean "customer's first order" after trimming, recompute it
    o = np.lexsort((order_day, order_cust))
    order_cust, order_day, n_items = order_cust[o], order_day[o], n_items[o]
    is_first = np.r_[True, order_cust[1:] != order_cust[:-1]]
    # Order ids increase with time (like a real OLTP sequence)
    o = np.lexsort((rng.random(order_day.size), order_day))
    order_cust, order_day, n_items, is_first = (order_cust[o], order_day[o], n_items[o],
                                                is_first[o])
    n_orders = order_day.size

    # ---------------------------------------------------------------- products
    n_products = int(np.clip(rows // 50, 300, 20000))
    products, popularity, markdown, ret_rate = make_products(rng, n_products)

    # ---------------------------------------------------------------- order lines
    item_order = np.repeat(np.arange(n_orders), n_items)
    item_day = order_day[item_order]
    months = dates.month.values
    group = (dates.year.values[item_day] - 2024) * 24 + (months[item_day] - 1) * 2 + is_event[item_day]
    product_idx = np.empty(item_order.size, dtype=np.int64)
    bfd_days = np.isin(event_idx, [i for i, e in enumerate(SALE_EVENTS) if e[0].startswith("BFD")])
    for g in np.unique(group):
        m = group == g
        any_day = item_day[m][0]
        w = popularity * seasonal_category_multiplier(products, months[any_day],
                                                      bool(bfd_days[item_day[m]].any()))
        product_idx[m] = rng.choice(n_products, m.sum(), p=w / w.sum())
    cat = products["category"].values[product_idx]
    qty = np.where(cat == "Beauty", rng.choice([1, 2, 3], item_order.size, p=[.75, .2, .05]),
                   rng.choice([1, 2, 3], item_order.size, p=[.92, .07, .01]))
    mrp = products["mrp"].values[product_idx]
    disc = np.minimum(markdown[product_idx] + event_md[item_day], 0.80)
    selling = np.round(mrp * (1 - disc))
    line_gross = selling * qty

    # ---------------------------------------------------------------- orders
    # First order comes through the customer's acquisition channel; repeats mostly
    # through direct/app and email (CRM).
    acq_name = np.array(ACQ_CHANNELS)
    ch_index = {c: i for i, c in enumerate(SESSION_CHANNELS)}
    first_ch = np.array([ch_index[c] for c in acq_name])[acq_ch[order_cust]]
    repeat_ch = rng.choice(len(SESSION_CHANNELS), n_orders, p=REPEAT_CHANNEL_PROBS)
    channel = np.where(is_first, first_ch, repeat_ch)
    device = rng.choice(3, n_orders, p=[0.62, 0.28, 0.10])
    payment = rng.choice(4, n_orders, p=[0.38, 0.35, 0.17, 0.10])
    cancel_p = np.where(payment == 0, 0.09, 0.045)
    cancelled = rng.random(n_orders) < cancel_p
    status = np.where(cancelled, "cancelled", "delivered").astype(object)
    status[(order_day >= D - 5) & ~cancelled] = "shipped"     # still in transit at cut-off

    order_gross = np.bincount(item_order, weights=line_gross, minlength=n_orders)
    coupon = np.full(n_orders, "", dtype=object)
    cdates = {c[0]: (dates.get_loc(pd.Timestamp(c[2])), dates.get_loc(pd.Timestamp(c[3]))) for c in COUPONS}
    u = rng.random(n_orders)
    coupon[is_first & (u < 0.45)] = "NEW15"
    for code in ("FEST24", "FEST25"):
        s, e = cdates[code]
        coupon[~is_first & (order_day >= s) & (order_day <= e) & (u < 0.25)] = code
    in_fest = np.isin(coupon, ["FEST24", "FEST25"])
    coupon[~is_first & ~in_fest & (u < 0.10)] = "STYLE10"
    spec = {c[0]: c for c in COUPONS}
    pct = np.array([spec[c][4] if c else 0 for c in coupon])
    cap = np.array([spec[c][5] if c else 0 for c in coupon])
    min_val = np.array([spec[c][6] if c else 0 for c in coupon])
    eligible = order_gross >= min_val
    coupon[~eligible] = ""
    order_disc = np.where(eligible, np.minimum(pct * order_gross, cap), 0)
    # Allocate the order-level coupon to lines pro-rata to line value
    share = line_gross / order_gross[item_order]
    line_coupon = np.round(order_disc[item_order] * share, 2)

    # ---------------------------------------------------------------- returns
    sub_rr = ret_rate[product_idx]
    p_ret = sub_rr * np.where(is_event[item_day], 1.25, 1.0) * np.where(payment[item_order] == 0, 1.2, 1.0)
    p_ret[status[item_order] == "cancelled"] = 0
    returned = rng.random(item_order.size) < p_ret
    ret_day = item_day + 4 + rng.poisson(6, item_order.size)
    returned &= ret_day < D                                    # return window not over yet -> censored
    r_idx = np.where(returned)[0]
    size_sensitive = np.isin(cat[r_idx], list(SIZE_SENSITIVE))
    reason = np.where(size_sensitive & (rng.random(r_idx.size) < 0.65),
                      np.array(RETURN_REASONS_SIZE)[rng.integers(0, 2, r_idx.size)],
                      np.array(RETURN_REASONS_OTHER)[rng.integers(0, 4, r_idx.size)])

    # ---------------------------------------------------------------- sessions
    # Converting sessions: one per order. Non-converting: orders/cr - orders per day/channel.
    dc = order_day * 6 + channel
    orders_dc = np.bincount(dc, minlength=D * 6).reshape(D, 6)
    cr = CHANNEL_CR[None, :] * np.where(is_event, 1.25, 1.0)[:, None] \
        * rng.lognormal(0, 0.08, (D, 6))
    nonconv = np.round(orders_dc * (1 / cr - 1)).astype(np.int64).ravel()
    nc_day = np.repeat(np.repeat(np.arange(D), 6), nonconv)
    nc_ch = np.repeat(np.tile(np.arange(6), D), nonconv)
    n_nc = nc_day.size
    signed_by_day = np.searchsorted(signup, np.arange(D), side="right")
    logged_in = rng.random(n_nc) < 0.45
    pool = signed_by_day[nc_day]
    nc_cust = np.where(logged_in & (pool > 0), (rng.random(n_nc) * pool).astype(np.int64), -1)
    s_day = np.concatenate([order_day, nc_day])
    s_ch = np.concatenate([channel, nc_ch])
    s_cust = np.concatenate([order_cust, nc_cust])
    s_dev = np.concatenate([device, rng.choice(3, n_nc, p=[0.55, 0.33, 0.12])])
    s_pages = np.concatenate([5 + rng.poisson(7, n_orders), 1 + rng.poisson(2.5, n_nc)])
    s_order = np.concatenate([np.arange(n_orders), np.full(n_nc, -1)])
    o = np.lexsort((rng.random(s_day.size), s_day))
    s_day, s_ch, s_cust, s_dev, s_pages, s_order = (a[o] for a in
                                                    (s_day, s_ch, s_cust, s_dev, s_pages, s_order))
    session_id = np.arange(1, s_day.size + 1)
    order_session = np.empty(n_orders, dtype=np.int64)
    conv = s_order >= 0
    order_session[s_order[conv]] = session_id[conv]

    # ---------------------------------------------------------------- frames
    iso = dates.strftime("%Y-%m-%d").values
    ff = np.array(FIRST_NAMES)[rng.integers(0, len(FIRST_NAMES), n_customers)]
    ll = np.array(LAST_NAMES)[rng.integers(0, len(LAST_NAMES), n_customers)]
    cust_ids = np.arange(1, n_customers + 1)
    city_w = np.array([c[2] for c in CITIES], float)
    city_i = rng.choice(len(CITIES), n_customers, p=city_w / city_w.sum())
    customers = pd.DataFrame({
        "customer_id": cust_ids, "first_name": ff, "last_name": ll,
        "email": (pd.Series(ff).str.lower() + "." + pd.Series(ll).str.lower()
                  + cust_ids.astype(str) + "@example.com").values,
        "gender": rng.choice(["F", "M"], n_customers, p=[0.58, 0.42]),
        "city": np.array([c[0] for c in CITIES])[city_i],
        "state": np.array([c[1] for c in CITIES])[city_i],
        "signup_date": iso[signup],
        "acquisition_channel": acq_name[acq_ch],
    })
    promotions = pd.DataFrame(
        [(i + 1, c, n, "sale_event", s, e, md, None, None) for i, (c, n, s, e, _, md) in enumerate(SALE_EVENTS)]
        + [(len(SALE_EVENTS) + i + 1, c, n, "coupon", s, e, p, cap_, mv)
           for i, (c, n, s, e, p, cap_, mv) in enumerate(COUPONS)],
        columns=["promotion_id", "promo_code", "promo_name", "promo_type", "start_date",
                 "end_date", "discount_pct", "max_discount", "min_order_value"])
    orders = pd.DataFrame({
        "order_id": np.arange(1, n_orders + 1), "customer_id": order_cust + 1,
        "session_id": order_session, "order_date": iso[order_day], "order_status": status,
        "channel": np.array(SESSION_CHANNELS)[channel], "device": np.array(DEVICES)[device],
        "payment_method": np.array(PAYMENTS)[payment], "coupon_code": coupon,
    })
    order_items = pd.DataFrame({
        "order_item_id": np.arange(1, item_order.size + 1), "order_id": item_order + 1,
        "product_id": product_idx + 1, "quantity": qty, "mrp": mrp,
        "selling_price": selling, "coupon_discount": line_coupon,
    })
    sessions = pd.DataFrame({
        "session_id": session_id,
        "customer_id": pd.array(np.where(s_cust >= 0, s_cust + 1, 0), dtype="Int64"),
        "session_date": iso[s_day], "channel": np.array(SESSION_CHANNELS)[s_ch],
        "device": np.array(DEVICES)[s_dev], "pages_viewed": s_pages,
    })
    sessions.loc[s_cust < 0, "customer_id"] = pd.NA
    returns = pd.DataFrame({
        "return_id": np.arange(1, r_idx.size + 1), "order_item_id": r_idx + 1,
        "return_date": iso[ret_day[r_idx]], "return_reason": reason,
        "refund_amount": np.round(line_gross[r_idx] - line_coupon[r_idx], 2),
    })
    return {"customers": customers, "products": products, "promotions": promotions,
            "orders": orders, "order_items": order_items, "sessions": sessions,
            "returns": returns}, iso


# --------------------------------------------------------------------------
# Dirty-data injection. Every injected problem is counted in the manifest.
# All columns become strings first, exactly like a raw CSV export.
# --------------------------------------------------------------------------
def _pick(rng, n, frac):
    k = max(1, int(round(n * frac))) if n else 0
    return rng.choice(n, k, replace=False)


def _to_dmy(iso_vals):
    s = pd.Series(iso_vals)
    return (s.str[8:10] + "-" + s.str[5:7] + "-" + s.str[0:4]).values


def _messy_case(rng, vals):
    out = vals.copy()
    style = rng.integers(0, 3, len(vals))
    out[style == 0] = pd.Series(vals[style == 0]).str.lower().values
    out[style == 1] = pd.Series(vals[style == 1]).str.upper().values
    out[style == 2] = (" " + pd.Series(vals[style == 2]) + " ").values
    return out


def dirty(tables, rng):
    issues = {}

    def log(table, issue, n):
        issues.setdefault(table, {})[issue] = int(n)

    def dup_rows(df, table, frac):
        idx = _pick(rng, len(df), frac)
        log(table, "exact_duplicate_rows", len(idx))
        out = pd.concat([df, df.iloc[idx]])
        # keep near-sorted order (dups land next to the original), as real re-sent rows do
        return out.sort_values(df.columns[0], kind="stable").reset_index(drop=True)

    out = {}
    # customers
    df = tables["customers"].astype(str)
    n = len(df)
    i = _pick(rng, n, 0.02); df.loc[i, "email"] = ""; log("customers", "null_email", len(i))
    i = _pick(rng, n, 0.003); df.loc[i, "email"] = df.loc[i, "email"].str.replace("@", " at "); log("customers", "malformed_email", len(i))
    i = _pick(rng, n, 0.08); df.loc[i, "city"] = _messy_case(rng, df.loc[i, "city"].values); log("customers", "city_casing_whitespace", len(i))
    i = _pick(rng, n, 0.25); df.loc[i, "signup_date"] = _to_dmy(df.loc[i, "signup_date"].values); log("customers", "date_format_dd_mm_yyyy", len(i))
    i = _pick(rng, n, 0.002); df.loc[i, "signup_date"] = rng.choice(["N/A", "2024-02-30", "00-00-0000"], len(i)); log("customers", "unparseable_signup_date", len(i))
    i = _pick(rng, n, 0.0005); df.loc[i, "customer_id"] = ""; log("customers", "missing_customer_id", len(i))
    out["customers"] = dup_rows(df, "customers", 0.004)

    # products
    df = tables["products"].astype(str)
    n = len(df)
    i = _pick(rng, n, 0.06); df.loc[i, "category"] = _messy_case(rng, df.loc[i, "category"].values); log("products", "category_casing_whitespace", len(i))
    i = _pick(rng, n, 0.003); df.loc[i, "mrp"] = "-" + df.loc[i, "mrp"]; log("products", "negative_mrp", len(i))
    i = _pick(rng, n, 0.005); df.loc[i, "brand"] = ""; log("products", "null_brand", len(i))
    i = _pick(rng, n, 0.005); df.loc[i, "cost_price"] = ""; log("products", "null_cost_price", len(i))
    out["products"] = dup_rows(df, "products", 0.003)

    # promotions: one re-sent row and a casing issue
    df = tables["promotions"].astype(str).replace({"None": ""})
    df.loc[2, "promo_type"] = "Sale_Event"; log("promotions", "promo_type_casing", 1)
    out["promotions"] = dup_rows(df, "promotions", 0.01)

    # orders
    df = tables["orders"].astype(str)
    n = len(df)
    max_cust = len(tables["customers"])
    i = _pick(rng, n, 0.30); df.loc[i, "order_date"] = _to_dmy(df.loc[i, "order_date"].values); log("orders", "date_format_dd_mm_yyyy", len(i))
    i = _pick(rng, n, 0.002); df.loc[i, "order_date"] = rng.choice(["2025-02-30", "", "31/31/2024", "not available"], len(i)); log("orders", "unparseable_order_date", len(i))
    i = _pick(rng, n, 0.0005); df.loc[i, "order_date"] = "2031-01-15"; log("orders", "order_date_out_of_range", len(i))
    i = _pick(rng, n, 0.10); df.loc[i, "order_status"] = _messy_case(rng, df.loc[i, "order_status"].values); log("orders", "status_casing_whitespace", len(i))
    i = _pick(rng, n, 0.001); df.loc[i, "order_status"] = rng.choice(["unknown", "test"], len(i)); log("orders", "invalid_status", len(i))
    i = _pick(rng, n, 0.002); df.loc[i, "customer_id"] = ""; log("orders", "null_customer_id", len(i))
    i = _pick(rng, n, 0.003); df.loc[i, "customer_id"] = (max_cust + rng.integers(1, 5000, len(i))).astype(str); log("orders", "orphan_customer_id", len(i))
    has_coupon = np.where(df["coupon_code"].values != "")[0]
    i = rng.choice(has_coupon, max(1, int(len(has_coupon) * 0.05)), replace=False) if len(has_coupon) else []
    df.loc[i, "coupon_code"] = df.loc[i, "coupon_code"].str.lower(); log("orders", "coupon_code_casing", len(i))
    out["orders"] = dup_rows(df, "orders", 0.008)

    # order_items
    df = tables["order_items"].astype(str)
    n = len(df)
    i = _pick(rng, n, 0.0015); df.loc[i, "order_id"] = (len(tables["orders"]) + rng.integers(1, 9999, len(i))).astype(str); log("order_items", "orphan_order_id", len(i))
    i = _pick(rng, n, 0.0015); df.loc[i, "product_id"] = (len(tables["products"]) + rng.integers(1, 999, len(i))).astype(str); log("order_items", "orphan_product_id", len(i))
    i = _pick(rng, n, 0.001); df.loc[i, "quantity"] = rng.choice(["0", "-1", "-2"], len(i)); log("order_items", "non_positive_quantity", len(i))
    i = _pick(rng, n, 0.001); df.loc[i, "selling_price"] = "-" + df.loc[i, "selling_price"]; log("order_items", "negative_selling_price", len(i))
    i = _pick(rng, n, 0.001); df.loc[i, "selling_price"] = ""; log("order_items", "null_selling_price", len(i))
    i = _pick(rng, n, 0.0005); df.loc[i, "selling_price"] = (tables["order_items"].loc[i, "mrp"] * 3).astype(str).values; log("order_items", "selling_price_above_mrp", len(i))
    out["order_items"] = dup_rows(df, "order_items", 0.008)

    # sessions (large: string ops only on the touched rows)
    df = tables["sessions"].astype(str).replace({"<NA>": ""})
    n = len(df)
    i = _pick(rng, n, 0.05); df.loc[i, "channel"] = _messy_case(rng, df.loc[i, "channel"].values); log("sessions", "channel_casing_whitespace", len(i))
    i = _pick(rng, n, 0.005); df.loc[i, "channel"] = ""; log("sessions", "null_channel", len(i))
    i = _pick(rng, n, 0.001); df.loc[i, "customer_id"] = (len(tables["customers"]) + rng.integers(1, 5000, len(i))).astype(str); log("sessions", "orphan_customer_id", len(i))
    i = _pick(rng, n, 0.0005); df.loc[i, "session_date"] = "not available"; log("sessions", "unparseable_session_date", len(i))
    out["sessions"] = dup_rows(df, "sessions", 0.003)

    # returns
    df = tables["returns"].astype(str)
    n = len(df)
    i = _pick(rng, n, 0.003); df.loc[i, "order_item_id"] = (len(tables["order_items"]) + rng.integers(1, 9999, len(i))).astype(str); log("returns", "orphan_order_item_id", len(i))
    i = _pick(rng, n, 0.003); df.loc[i, "return_date"] = "2023-12-01"; log("returns", "return_before_order", len(i))
    i = _pick(rng, n, 0.002); df.loc[i, "refund_amount"] = (tables["returns"].loc[i, "refund_amount"] * 10 + 1000).round(2).astype(str).values; log("returns", "refund_exceeds_line_value", len(i))
    out["returns"] = dup_rows(df, "returns", 0.005)
    return out, issues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=1_000_000, help="target clean order_items rows (default 1,000,000)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "raw")
    args = ap.parse_args()

    t0 = time.perf_counter()
    tables, _ = generate(args.rows, args.seed)
    raw, issues = dirty(tables, np.random.default_rng(args.seed + 7))
    args.out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, df in raw.items():
        df.to_csv(args.out / f"{name}.csv", index=False)
        counts[name] = {"clean_rows_generated": len(tables[name]), "raw_rows_written": len(df)}
        print(f"  {name:<12} {len(df):>11,} rows -> {name}.csv")
    manifest = {"seed": args.seed, "rows_arg": args.rows, "date_range": [START, END],
                "synthetic": True, "tables": counts, "injected_issues": issues}
    (args.out / "_generation_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Generated in {time.perf_counter() - t0:.1f}s -> {args.out}")


if __name__ == "__main__":
    main()
