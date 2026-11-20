-- mart_daily_sales: one row per calendar day.
DROP TABLE IF EXISTS mart_daily_sales;
CREATE TABLE mart_daily_sales AS
WITH daily AS (
    SELECT
        d.date_key, d.full_date, d.day_name, d.is_weekend, d.week_start, d.month_start,
        d.is_sale_day, d.sale_event_code,
        COUNT(DISTINCT f.order_id)                         AS orders,
        COALESCE(SUM(f.quantity), 0)                       AS units,
        COALESCE(SUM(f.mrp_amount), 0)                     AS mrp_value,
        COALESCE(SUM(f.net_revenue), 0)                    AS net_revenue,
        COALESCE(SUM(f.mrp_amount - f.net_revenue), 0)     AS discount_cost,
        COALESCE(SUM(f.net_revenue - f.cost_amount), 0)    AS gross_margin
    -- Start from dim_date and LEFT JOIN the facts so a day with zero orders
    -- still gets a row. That matters for the moving average below: "6 rows
    -- back" must mean "6 days back", which is only true with no gaps.
    FROM dim_date AS d
    LEFT JOIN fact_order_items AS f
           ON f.order_date_key = d.date_key
          AND f.order_status <> 'cancelled'   -- in ON (not WHERE) so the LEFT JOIN keeps empty days
    WHERE d.date_key BETWEEN (SELECT MIN(order_date_key) FROM fact_order_items)
                         AND (SELECT MAX(order_date_key) FROM fact_order_items)
    GROUP BY d.date_key, d.full_date, d.day_name, d.is_weekend, d.week_start, d.month_start,
             d.is_sale_day, d.sale_event_code
)
SELECT
    daily.*,
    ROUND(100 * gross_margin / NULLIF(net_revenue, 0), 2)              AS margin_pct,
    ROUND(net_revenue / NULLIF(orders, 0), 2)                          AS aov,
    -- 7-day moving average: mean of this day and the 6 before it.
    -- (The first 6 days of the data average over fewer days.)
    ROUND(AVG(net_revenue) OVER w7, 2)                                 AS net_revenue_7d_ma,
    ROUND(AVG(orders) OVER w7, 1)                                      AS orders_7d_ma,
    -- LAG(x, 364): the value 364 rows (= 52 weeks) earlier -> same weekday last
    -- year, which avoids comparing a Saturday with a Tuesday.
    ROUND(100 * (net_revenue / NULLIF(LAG(net_revenue, 364) OVER (ORDER BY full_date), 0) - 1), 2)
                                                                       AS yoy_growth_pct_same_weekday
FROM daily
WINDOW w7 AS (ORDER BY full_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW);

ALTER TABLE mart_daily_sales ADD PRIMARY KEY (date_key);
