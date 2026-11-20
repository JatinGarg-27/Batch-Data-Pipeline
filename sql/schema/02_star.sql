-- =====================================================================
-- STAR SCHEMA (the warehouse layer the marts read from)
--
-- CREATE TABLE IF NOT EXISTS (never DROP): this layer persists between runs
-- so loads can be idempotent upserts and incremental.
--
-- Dimensions use a surrogate key (customer_key...) plus a UNIQUE natural key
-- (customer_id...). The fact table stores surrogate keys. Why bother?
--   * the warehouse is insulated from source-system id changes/reuse
--   * small INT keys keep the 1M-row fact table and its indexes compact
--
-- Grain of fact_order_items: ONE ROW PER ORDER LINE (order_item_id).
-- Returns are folded into the same row (is_returned, refund_amount) because
-- an order line can be returned at most once -- same grain, no extra fact.
-- Sessions have a different grain -> fact_sessions_daily.
-- =====================================================================

CREATE TABLE IF NOT EXISTS dim_date (
    date_key        INT         NOT NULL PRIMARY KEY,  -- yyyymmdd, e.g. 20251206
    full_date       DATE        NOT NULL UNIQUE,
    day_of_week     TINYINT     NOT NULL,              -- 1 = Monday ... 7 = Sunday
    day_name        VARCHAR(9)  NOT NULL,
    is_weekend      TINYINT(1)  NOT NULL,
    week_start      DATE        NOT NULL,              -- Monday of that ISO week
    month_start     DATE        NOT NULL,
    month_num       TINYINT     NOT NULL,
    month_name      VARCHAR(9)  NOT NULL,
    quarter_num     TINYINT     NOT NULL,
    year_num        SMALLINT    NOT NULL,
    is_sale_day     TINYINT(1)  NOT NULL DEFAULT 0,
    sale_event_code VARCHAR(20) NULL,
    KEY idx_dim_date_month (month_start)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS dim_promotion (
    promotion_key   INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
    promotion_id    INT            NOT NULL UNIQUE,
    promo_code      VARCHAR(20)    NOT NULL UNIQUE,
    promo_name      VARCHAR(80)    NOT NULL,
    promo_type      VARCHAR(20)    NOT NULL,           -- 'sale_event' | 'coupon'
    start_date      DATE           NOT NULL,
    end_date        DATE           NOT NULL,
    discount_pct    DECIMAL(5, 4)  NOT NULL,
    max_discount    DECIMAL(10, 2) NULL,
    min_order_value DECIMAL(10, 2) NULL,
    updated_at      TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_dim_promotion_type_dates (promo_type, start_date, end_date)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS dim_customer (
    customer_key        INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
    customer_id         INT          NOT NULL UNIQUE,
    first_name          VARCHAR(50),
    last_name           VARCHAR(50),
    email               VARCHAR(120) NULL,             -- NULL when missing/malformed in source
    gender              CHAR(1)      NULL,
    city                VARCHAR(50),
    state               CHAR(2),
    signup_date         DATE         NULL,
    acquisition_channel VARCHAR(20)  NOT NULL,
    updated_at          TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS dim_product (
    product_key  INT            NOT NULL AUTO_INCREMENT PRIMARY KEY,
    product_id   INT            NOT NULL UNIQUE,
    product_name VARCHAR(150)   NOT NULL,
    brand        VARCHAR(60)    NOT NULL,
    category     VARCHAR(40)    NOT NULL,
    sub_category VARCHAR(40)    NOT NULL,
    style        VARCHAR(30)    NOT NULL,
    mrp          DECIMAL(10, 2) NOT NULL,
    cost_price   DECIMAL(10, 2) NOT NULL,
    updated_at   TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_dim_product_category (category, sub_category),
    KEY idx_dim_product_brand (brand)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS fact_order_items (
    order_item_id   BIGINT         NOT NULL PRIMARY KEY,
    order_id        BIGINT         NOT NULL,            -- degenerate dimension
    order_date_key  INT            NOT NULL,
    customer_key    INT            NOT NULL,
    product_key     INT            NOT NULL,
    sale_event_key  INT            NULL,                -- role-playing dim_promotion: sale running that day
    coupon_key      INT            NULL,                -- role-playing dim_promotion: coupon on the order
    order_status    VARCHAR(15)    NOT NULL,
    channel         VARCHAR(20)    NOT NULL,
    device          VARCHAR(10)    NOT NULL,
    payment_method  VARCHAR(10)    NOT NULL,
    quantity        SMALLINT       NOT NULL,
    mrp_amount      DECIMAL(12, 2) NOT NULL,            -- quantity * MRP  (list-price value, "GMV at MRP")
    gross_amount    DECIMAL(12, 2) NOT NULL,            -- quantity * selling price (after markdown)
    coupon_discount DECIMAL(12, 2) NOT NULL,
    net_revenue     DECIMAL(12, 2) NOT NULL,            -- gross_amount - coupon_discount (what the customer paid)
    cost_amount     DECIMAL(12, 2) NOT NULL,            -- quantity * cost price
    is_returned     TINYINT(1)     NOT NULL DEFAULT 0,
    return_date_key INT            NULL,
    refund_amount   DECIMAL(12, 2) NOT NULL DEFAULT 0,
    loaded_at       TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    -- InnoDB automatically creates an index on every FK column below
    CONSTRAINT fk_foi_date     FOREIGN KEY (order_date_key)  REFERENCES dim_date (date_key),
    CONSTRAINT fk_foi_customer FOREIGN KEY (customer_key)    REFERENCES dim_customer (customer_key),
    CONSTRAINT fk_foi_product  FOREIGN KEY (product_key)     REFERENCES dim_product (product_key),
    CONSTRAINT fk_foi_sale     FOREIGN KEY (sale_event_key)  REFERENCES dim_promotion (promotion_key),
    CONSTRAINT fk_foi_coupon   FOREIGN KEY (coupon_key)      REFERENCES dim_promotion (promotion_key),
    CONSTRAINT fk_foi_retdate  FOREIGN KEY (return_date_key) REFERENCES dim_date (date_key),
    KEY idx_foi_order (order_id),
    -- Composite index for "customer history" queries (cohorts, new vs returning):
    -- lets MySQL find each customer's first order without touching the table.
    KEY idx_foi_customer_date (customer_key, order_date_key)
) ENGINE = InnoDB;

-- Sessions are aggregated to ONE ROW PER DAY x CHANNEL x DEVICE (a "periodic
-- snapshot" fact). Conversion analysis only needs counts, so keeping 11.6M
-- visit rows in the warehouse would cost load time and storage for no benefit;
-- the visit-level rows still exist in stg_sessions for the batch being loaded.
CREATE TABLE IF NOT EXISTS fact_sessions_daily (
    session_date_key   INT         NOT NULL,
    channel            VARCHAR(20) NOT NULL,
    device             VARCHAR(10) NOT NULL,
    sessions           INT         NOT NULL,
    logged_in_sessions INT         NOT NULL,            -- sessions with a known customer
    converted_sessions INT         NOT NULL,            -- sessions in which an order was placed
    pages_viewed       BIGINT      NOT NULL,
    PRIMARY KEY (session_date_key, channel, device),
    CONSTRAINT fk_fsd_date FOREIGN KEY (session_date_key) REFERENCES dim_date (date_key)
) ENGINE = InnoDB;

-- Bookkeeping for incremental loads: the latest order_date merged so far.
CREATE TABLE IF NOT EXISTS etl_watermark (
    table_name     VARCHAR(40) NOT NULL PRIMARY KEY,
    high_watermark DATE        NOT NULL,
    updated_at     TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE = InnoDB;

-- One row per load run: what was staged and merged (audit trail).
CREATE TABLE IF NOT EXISTS etl_load_log (
    run_id        INT         NOT NULL AUTO_INCREMENT PRIMARY KEY,
    started_at    DATETIME    NOT NULL,
    finished_at   DATETIME    NULL,
    mode          VARCHAR(12) NOT NULL,                 -- 'full' | 'incremental'
    cutoff_date   DATE        NULL,
    rows_staged   BIGINT      NULL,
    fact_rows_after BIGINT    NULL
) ENGINE = InnoDB;
