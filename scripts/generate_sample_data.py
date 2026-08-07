"""
Generates synthetic, deliberately messy raw source data for the pipeline
(data/raw/*.csv). Run this once before running the pipeline:

    python scripts/generate_sample_data.py

The messiness (duplicates, nulls, inconsistent casing/date formats,
orphan foreign keys, bad values) mirrors what a real raw data drop
looks like and gives the cleaning stage real work to do.
"""

import csv
import os
import random
from datetime import date, timedelta

random.seed(42)

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

FIRST_NAMES = ["Aditi", "Rohan", "Meera", "Karan", "Isha", "Vivek", "Priya", "Arjun", "Neha", "Sanjay"]
LAST_NAMES = ["Sharma", "Verma", "Iyer", "Khan", "Gupta", "Nair", "Reddy", "Chopra", "Malhotra", "Bose"]
CITIES = ["Delhi", "mumbai", "BANGALORE", "Chennai ", "kolkata", "Pune", "Hyderabad", "Jaipur"]
STATES = ["DL", "MH", "KA", "TN", "WB", "MH", "TG", "RJ"]

CATEGORIES = ["Electronics", "Apparel", "Home & Kitchen", "Books", "Sports", "Beauty"]
PRODUCT_NAMES = {
    "Electronics": ["Wireless Earbuds", "Smart Watch", "Bluetooth Speaker", "Power Bank", "USB-C Cable"],
    "Apparel": ["Cotton T-Shirt", "Denim Jacket", "Running Shoes", "Wool Sweater", "Formal Shirt"],
    "Home & Kitchen": ["Non-Stick Pan", "Blender", "Table Lamp", "Storage Box", "Ceramic Mug Set"],
    "Books": ["Data Engineering Basics", "Python Crash Course", "SQL for Beginners", "Clean Code", "Atomic Habits"],
    "Sports": ["Yoga Mat", "Dumbbell Set", "Cricket Bat", "Football", "Resistance Bands"],
    "Beauty": ["Face Serum", "Sunscreen SPF50", "Shampoo", "Lip Balm", "Face Wash"],
}

STATUSES = ["completed", "Completed", "COMPLETED", "pending", "cancelled", "Cancelled", "shipped"]


def random_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def fmt_date_messy(d: date) -> str:
    fmt = random.choice(["iso", "us_slash", "us_slash"])
    if fmt == "iso":
        return d.isoformat()
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


# ---------------------------------------------------------------- customers
customers = []
for cid in range(1, 121):
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    email = f"{first.lower()}.{last.lower()}{cid}@example.com"
    if random.random() < 0.06:
        email = ""  # missing email
    city = random.choice(CITIES)
    state = random.choice(STATES)
    signup = random_date(date(2023, 1, 1), date(2025, 12, 31))
    customers.append({
        "customer_id": cid,
        "first_name": first,
        "last_name": last,
        "email": email,
        "city": city,
        "state": state,
        "signup_date": fmt_date_messy(signup),
    })

# inject exact-duplicate rows
for _ in range(6):
    customers.append(dict(random.choice(customers[:100])))

random.shuffle(customers)

with open(os.path.join(RAW_DIR, "customers.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(customers[0].keys()))
    w.writeheader()
    w.writerows(customers)

# ----------------------------------------------------------------- products
products = []
pid = 1
for category in CATEGORIES:
    for name in PRODUCT_NAMES[category]:
        price = round(random.uniform(150, 4500), 2)
        products.append({
            "product_id": pid,
            "product_name": name,
            "category": category if random.random() > 0.05 else "",
            "unit_price": price,
        })
        pid += 1

# a couple of bad rows: negative price, duplicate product_id
products.append({"product_id": 5, "product_name": "Smart Watch (reissue)", "category": "Electronics", "unit_price": -999})
products.append(dict(products[3]))

with open(os.path.join(RAW_DIR, "products.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(products[0].keys()))
    w.writeheader()
    w.writerows(products)

valid_customer_ids = [c["customer_id"] for c in customers]
valid_product_ids = [p["product_id"] for p in products]

# ------------------------------------------------------------------- orders
orders = []
oid = 1
for _ in range(400):
    cust_id = random.choice(valid_customer_ids)
    if random.random() < 0.02:
        cust_id = 9999  # orphan FK, no such customer
    order_date = random_date(date(2024, 1, 1), date(2025, 12, 31))
    orders.append({
        "order_id": oid,
        "customer_id": cust_id if random.random() > 0.015 else "",
        "order_date": fmt_date_messy(order_date),
        "status": random.choice(STATUSES),
    })
    oid += 1

with open(os.path.join(RAW_DIR, "orders.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(orders[0].keys()))
    w.writeheader()
    w.writerows(orders)

# -------------------------------------------------------------- order_items
order_items = []
item_id = 1
for o in orders:
    if o["customer_id"] == "":
        continue
    for _ in range(random.randint(1, 4)):
        prod_id = random.choice(valid_product_ids)
        qty = random.randint(1, 5)
        if random.random() < 0.02:
            qty = -1  # bad quantity
        if random.random() < 0.01:
            prod_id = 8888  # orphan FK, no such product
        price = next((p["unit_price"] for p in products if p["product_id"] == prod_id), 0)
        order_items.append({
            "order_item_id": item_id,
            "order_id": o["order_id"],
            "product_id": prod_id,
            "quantity": qty,
            "unit_price": price,
        })
        item_id += 1

# inject a few duplicate line items
for _ in range(8):
    order_items.append(dict(random.choice(order_items)))

with open(os.path.join(RAW_DIR, "order_items.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(order_items[0].keys()))
    w.writeheader()
    w.writerows(order_items)

print(f"Generated {len(customers)} customers, {len(products)} products, "
      f"{len(orders)} orders, {len(order_items)} order_items -> {os.path.abspath(RAW_DIR)}")
