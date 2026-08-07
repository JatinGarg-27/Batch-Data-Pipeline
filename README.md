# Batch Data Pipeline

An end-to-end batch ETL pipeline: ingest raw source data, validate and
clean it with Python/Pandas, load it into a structured relational
database, and run SQL transformations (joins, aggregations, window
functions) to produce analysis-ready tables.

The project is deliberately structured around three clear stages —
**ingestion → transformation (clean/validate) → load** — followed by a
SQL analytics transform, to mirror real-world ETL design.

## Architecture

```
data/raw/*.csv                 raw, messy source data (dupes, nulls,
   │                           inconsistent formats, orphan FKs)
   ▼
src/ingest.py                  Stage 1: read raw CSVs -> pandas DataFrames
   ▼
src/clean.py                   Stage 2: validate & clean with Pandas
   │                           (dedupe, type coercion, date parsing,
   │                           FK integrity checks) -> typed DataFrames
   ▼
src/load.py + sql/schema.sql   Stage 3: load into SQLite relational schema
   │                           (customers, products, orders, order_items)
   ▼
src/transform.py +             Analytics: SQL joins, aggregations, and
sql/transformations.sql        window functions -> analysis-ready tables
   ▼
output/pipeline.db
```

### Source data

| Table          | Description                              |
|----------------|-------------------------------------------|
| `customers`    | customer_id, name, email, city, state, signup_date |
| `products`     | product_id, product_name, category, unit_price |
| `orders`       | order_id, customer_id, order_date, status |
| `order_items`  | order_item_id, order_id, product_id, quantity, unit_price |

The generated raw data intentionally includes duplicate rows, missing
emails, inconsistent date formats (`YYYY-MM-DD` vs `MM/DD/YYYY`),
mixed-case city/status values, negative prices/quantities, and orphan
foreign keys — so the cleaning stage has real validation work to do.

### Analytics tables (output)

| Table                                  | Built with |
|-----------------------------------------|------------|
| `analytics_order_line_items`            | JOIN across all 4 tables (fact table) |
| `analytics_revenue_by_category`         | JOIN + GROUP BY aggregation |
| `analytics_customer_ltv`                | GROUP BY + `RANK() OVER` window function |
| `analytics_monthly_revenue_trend`       | GROUP BY + running total via `SUM() OVER` |
| `analytics_top_products_by_category`    | `RANK() OVER (PARTITION BY category ...)` |

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Generate the synthetic raw data (once):

```bash
python scripts/generate_sample_data.py
```

Run the full pipeline:

```bash
python -m src.pipeline
```

This ingests `data/raw/*.csv`, cleans and validates it, loads it into
`output/pipeline.db` (SQLite), and builds the analytics tables. Row
counts and every cleaning decision (what was dropped and why) are
logged at each stage.

Inspect the results:

```bash
sqlite3 output/pipeline.db "SELECT * FROM analytics_revenue_by_category;"
```

## Project structure

```
data/raw/                  raw source CSVs (generated)
scripts/generate_sample_data.py   synthetic raw data generator
src/ingest.py               Stage 1: ingestion
src/clean.py                 Stage 2: validation & cleaning
src/db.py                    SQLite connection helper
src/load.py                  Stage 3: load into relational DB
sql/schema.sql                relational schema (customers/products/orders/order_items)
src/transform.py             SQL analytics transform runner
sql/transformations.sql       joins / aggregations / window functions
src/pipeline.py               orchestrates all stages end-to-end
output/pipeline.db            pipeline output (SQLite)
```

## Tech stack

Python, Pandas, SQL (SQLite), with a design that maps directly onto
Postgres/MySQL or an Airflow-orchestrated pipeline (each stage is a
pure function that takes and returns DataFrames/DB connections, so
it can be dropped into task nodes as-is).
