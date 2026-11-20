-- mart_sale_event_effectiveness: each sale event vs a BASELINE.
-- Baseline = the 28 days before the event, excluding any other sale days.
-- Uplift compares AVERAGE DAILY numbers, because events and baselines have
-- different lengths.
-- Caveat (worth saying in an interview): shoppers often hold off buying just
-- before a big sale, which depresses the baseline and flatters the uplift.
DROP TABLE IF EXISTS mart_sale_event_effectiveness;
CREATE TABLE mart_sale_event_effectiveness AS
WITH events AS (
    SELECT promo_code, promo_name, start_date, end_date,
           DATEDIFF(end_date, start_date) + 1 AS event_days
    FROM dim_promotion
    WHERE promo_type = 'sale_event'
),
during AS (
    SELECT e.promo_code,
           AVG(m.net_revenue) AS avg_daily_revenue, AVG(m.gross_margin) AS avg_daily_margin,
           AVG(m.orders) AS avg_daily_orders,
           SUM(m.net_revenue) AS net_revenue, SUM(m.gross_margin) AS gross_margin,
           SUM(m.discount_cost) AS discount_cost, SUM(m.mrp_value) AS mrp_value
    FROM events AS e
    JOIN mart_daily_sales AS m ON m.full_date BETWEEN e.start_date AND e.end_date   -- range join
    GROUP BY e.promo_code
),
baseline AS (
    SELECT e.promo_code,
           AVG(m.net_revenue) AS avg_daily_revenue, AVG(m.gross_margin) AS avg_daily_margin,
           AVG(m.orders) AS avg_daily_orders,
           SUM(m.net_revenue) AS net_revenue, SUM(m.gross_margin) AS gross_margin,
           SUM(m.discount_cost) AS discount_cost, SUM(m.mrp_value) AS mrp_value
    FROM events AS e
    JOIN mart_daily_sales AS m
      ON m.full_date BETWEEN e.start_date - INTERVAL 28 DAY AND e.start_date - INTERVAL 1 DAY
     AND m.is_sale_day = 0
    GROUP BY e.promo_code
)
SELECT
    e.promo_code, e.promo_name, e.start_date, e.end_date, e.event_days,
    ROUND(d.avg_daily_revenue, 0)                                          AS avg_daily_revenue,
    ROUND(b.avg_daily_revenue, 0)                                          AS baseline_avg_daily_revenue,
    ROUND(100 * (d.avg_daily_revenue / NULLIF(b.avg_daily_revenue, 0) - 1), 1) AS revenue_uplift_pct,
    ROUND(100 * (d.avg_daily_orders / NULLIF(b.avg_daily_orders, 0) - 1), 1)   AS orders_uplift_pct,
    ROUND((d.avg_daily_revenue - b.avg_daily_revenue) * e.event_days, 0)   AS incremental_revenue,
    ROUND(100 * d.discount_cost / NULLIF(d.mrp_value, 0), 1)               AS discount_pct_during,
    ROUND(100 * b.discount_cost / NULLIF(b.mrp_value, 0), 1)               AS discount_pct_baseline,
    ROUND(d.discount_cost, 0)                                              AS discount_cost_during,
    ROUND(100 * d.gross_margin / NULLIF(d.net_revenue, 0), 1)              AS margin_pct_during,
    ROUND(100 * b.gross_margin / NULLIF(b.net_revenue, 0), 1)              AS margin_pct_baseline,
    ROUND(100 * (d.avg_daily_margin / NULLIF(b.avg_daily_margin, 0) - 1), 1) AS margin_uplift_pct,
    ROUND((d.avg_daily_margin - b.avg_daily_margin) * e.event_days, 0)     AS incremental_margin
FROM events AS e
JOIN during   AS d ON d.promo_code = e.promo_code
JOIN baseline AS b ON b.promo_code = e.promo_code;

ALTER TABLE mart_sale_event_effectiveness ADD PRIMARY KEY (promo_code);

-- mart_sale_vs_regular_days: all sale days vs all regular days, side by side.
DROP TABLE IF EXISTS mart_sale_vs_regular_days;
CREATE TABLE mart_sale_vs_regular_days AS
SELECT
    CASE WHEN is_sale_day = 1 THEN 'sale day' ELSE 'regular day' END       AS day_type,
    COUNT(*)                                                               AS days,
    ROUND(AVG(net_revenue), 0)                                             AS avg_daily_revenue,
    ROUND(AVG(orders), 0)                                                  AS avg_daily_orders,
    ROUND(SUM(net_revenue) / SUM(orders), 2)                               AS aov,
    ROUND(100 * SUM(discount_cost) / SUM(mrp_value), 1)                    AS discount_pct_of_mrp,
    ROUND(100 * SUM(gross_margin) / SUM(net_revenue), 1)                   AS margin_pct,
    ROUND(AVG(gross_margin), 0)                                            AS avg_daily_margin
FROM mart_daily_sales
GROUP BY day_type;

-- mart_coupon_performance: order-level coupon economics (incl. 'NO_COUPON').
DROP TABLE IF EXISTS mart_coupon_performance;
CREATE TABLE mart_coupon_performance AS
WITH orders AS (                        -- collapse lines to one row per order first
    SELECT f.order_id, f.coupon_key,
           SUM(f.net_revenue)                  AS net_revenue,
           SUM(f.coupon_discount)              AS coupon_cost,
           SUM(f.net_revenue - f.cost_amount)  AS gross_margin
    FROM fact_order_items AS f
    WHERE f.order_status <> 'cancelled'
    GROUP BY f.order_id, f.coupon_key
)
SELECT
    COALESCE(p.promo_code, 'NO_COUPON')                                    AS coupon_code,
    COUNT(*)                                                               AS orders,
    ROUND(SUM(o.net_revenue), 0)                                           AS net_revenue,
    ROUND(AVG(o.net_revenue), 2)                                           AS aov,
    ROUND(SUM(o.coupon_cost), 0)                                           AS coupon_cost,
    ROUND(100 * SUM(o.coupon_cost) / NULLIF(SUM(o.net_revenue + o.coupon_cost), 0), 2) AS coupon_cost_pct,
    ROUND(100 * SUM(o.gross_margin) / NULLIF(SUM(o.net_revenue), 0), 2)    AS margin_pct
FROM orders AS o
LEFT JOIN dim_promotion AS p ON p.promotion_key = o.coupon_key
GROUP BY coupon_code;
