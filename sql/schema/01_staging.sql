-- =====================================================================
-- STAGING LAYER
-- One table per source, holding the *cleaned* rows of the current batch.
-- Rebuilt on every load (DROP + CREATE), so it never accumulates data:
-- it is just a landing area for set-based SQL merges into the star schema.
-- No foreign keys here on purpose -- integrity was enforced by the clean
-- stage and is enforced again by the star schema's FKs.
-- =====================================================================

DROP TABLE IF EXISTS stg_customers;
CREATE TABLE stg_customers (
    customer_id         INT          NOT NULL PRIMARY KEY,
    first_name          VARCHAR(50),
    last_name           VARCHAR(50),
    email               VARCHAR(120),
    gender              CHAR(1),
    city                VARCHAR(50),
    state               CHAR(2),
    signup_date         DATE,
    acquisition_channel VARCHAR(20)
) ENGINE = InnoDB;

DROP TABLE IF EXISTS stg_products;
CREATE TABLE stg_products (
    product_id   INT           NOT NULL PRIMARY KEY,
    product_name VARCHAR(150),
    brand        VARCHAR(60),
    category     VARCHAR(40),
    sub_category VARCHAR(40),
    style        VARCHAR(30),
    mrp          DECIMAL(10, 2),
    cost_price   DECIMAL(10, 2)
) ENGINE = InnoDB;

DROP TABLE IF EXISTS stg_promotions;
CREATE TABLE stg_promotions (
    promotion_id    INT          NOT NULL PRIMARY KEY,
    promo_code      VARCHAR(20),
    promo_name      VARCHAR(80),
    promo_type      VARCHAR(20),
    start_date      DATE,
    end_date        DATE,
    discount_pct    DECIMAL(5, 4),
    max_discount    DECIMAL(10, 2),
    min_order_value DECIMAL(10, 2)
) ENGINE = InnoDB;

DROP TABLE IF EXISTS stg_sessions;
CREATE TABLE stg_sessions (
    session_id   BIGINT      NOT NULL,
    customer_id  INT,
    session_date DATE        NOT NULL,
    channel      VARCHAR(20) NOT NULL,
    device       VARCHAR(10) NOT NULL,
    pages_viewed SMALLINT,
    -- InnoDB stores rows physically in PRIMARY KEY order (clustered index).
    -- Clustering on the GROUP BY columns lets the daily aggregation stream
    -- through rows already in group order instead of building a temp table
    -- (measured: 45s -> ~4s for 11.6M rows). session_id is appended to keep the
    -- key unique; it was already de-duplicated by the clean stage.
    PRIMARY KEY (session_date, channel, device, session_id)
) ENGINE = InnoDB;

DROP TABLE IF EXISTS stg_orders;
CREATE TABLE stg_orders (
    order_id       BIGINT      NOT NULL PRIMARY KEY,
    customer_id    INT         NOT NULL,
    session_id     BIGINT,
    order_date     DATE        NOT NULL,
    order_status   VARCHAR(15),
    channel        VARCHAR(20),
    device         VARCHAR(10),
    payment_method VARCHAR(10),
    coupon_code    VARCHAR(20),
    KEY idx_stg_orders_session (session_id)       -- used to flag converting sessions
) ENGINE = InnoDB;

DROP TABLE IF EXISTS stg_order_items;
CREATE TABLE stg_order_items (
    order_item_id   BIGINT         NOT NULL PRIMARY KEY,
    order_id        BIGINT         NOT NULL,
    product_id      INT            NOT NULL,
    quantity        SMALLINT       NOT NULL,
    mrp             DECIMAL(10, 2) NOT NULL,
    selling_price   DECIMAL(10, 2) NOT NULL,
    coupon_discount DECIMAL(10, 2) NOT NULL,
    KEY idx_stg_items_order (order_id)
) ENGINE = InnoDB;

DROP TABLE IF EXISTS stg_returns;
CREATE TABLE stg_returns (
    return_id     BIGINT         NOT NULL PRIMARY KEY,
    order_item_id BIGINT         NOT NULL,
    return_date   DATE           NOT NULL,
    return_reason VARCHAR(60),
    refund_amount DECIMAL(12, 2),
    UNIQUE KEY uq_stg_returns_item (order_item_id)
) ENGINE = InnoDB;
