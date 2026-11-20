-- mart_weekly_sales: ISO weeks (Monday start), rolled up from the daily mart.
-- Summing daily orders is safe because every order belongs to exactly one day.
DROP TABLE IF EXISTS mart_weekly_sales;
CREATE TABLE mart_weekly_sales AS
WITH weekly AS (
    SELECT
        week_start,
        COUNT(*)            AS days_in_data,
        SUM(orders)         AS orders,
        SUM(net_revenue)    AS net_revenue,
        SUM(gross_margin)   AS gross_margin,
        SUM(discount_cost)  AS discount_cost,
        SUM(mrp_value)      AS mrp_value,
        MAX(is_sale_day)    AS has_sale_day
    FROM mart_daily_sales
    GROUP BY week_start
)
SELECT
    weekly.*,
    days_in_data < 7                                                     AS is_partial_week,
    ROUND(100 * gross_margin / NULLIF(net_revenue, 0), 2)                AS margin_pct,
    ROUND(net_revenue / NULLIF(orders, 0), 2)                            AS aov,
    -- LAG(x) = previous row's value in week order -> week-over-week growth
    ROUND(100 * (net_revenue / NULLIF(LAG(net_revenue) OVER (ORDER BY week_start), 0) - 1), 2)
                                                                         AS wow_growth_pct
FROM weekly;

ALTER TABLE mart_weekly_sales ADD PRIMARY KEY (week_start);
