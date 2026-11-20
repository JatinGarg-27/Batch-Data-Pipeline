-- mart_monthly_sales: monthly KPIs with month-over-month and year-over-year growth.
DROP TABLE IF EXISTS mart_monthly_sales;
CREATE TABLE mart_monthly_sales AS
WITH monthly AS (
    SELECT
        d.month_start,
        COUNT(DISTINCT f.order_id)                 AS orders,
        COUNT(DISTINCT f.customer_key)             AS active_customers,
        SUM(f.quantity)                            AS units,
        SUM(f.mrp_amount)                          AS mrp_value,
        SUM(f.net_revenue)                         AS net_revenue,
        SUM(f.mrp_amount - f.net_revenue)          AS discount_cost,
        SUM(f.net_revenue - f.cost_amount)         AS gross_margin,
        SUM(f.refund_amount)                       AS refunds
    FROM fact_order_items AS f
    JOIN dim_date AS d ON d.date_key = f.order_date_key
    WHERE f.order_status <> 'cancelled'
    GROUP BY d.month_start
)
SELECT
    month_start, orders, active_customers, units, net_revenue, gross_margin, discount_cost, refunds,
    net_revenue - refunds                                              AS net_revenue_after_returns,
    ROUND(100 * gross_margin / NULLIF(net_revenue, 0), 2)              AS margin_pct,
    ROUND(100 * discount_cost / NULLIF(mrp_value, 0), 2)               AS discount_pct_of_mrp,
    ROUND(net_revenue / NULLIF(orders, 0), 2)                          AS aov,
    ROUND(orders / NULLIF(active_customers, 0), 3)                     AS orders_per_customer,
    ROUND(100 * (net_revenue / NULLIF(LAG(net_revenue, 1) OVER w, 0) - 1), 2) AS mom_growth_pct,
    -- LAG(x, 12) is "12 rows back". That is only "same month last year" if no
    -- month is missing, so we check the lagged month really is 1 year earlier.
    CASE WHEN LAG(month_start, 12) OVER w = month_start - INTERVAL 1 YEAR
         THEN ROUND(100 * (net_revenue / NULLIF(LAG(net_revenue, 12) OVER w, 0) - 1), 2)
    END                                                                AS yoy_growth_pct
FROM monthly
WINDOW w AS (ORDER BY month_start);

ALTER TABLE mart_monthly_sales ADD PRIMARY KEY (month_start);
