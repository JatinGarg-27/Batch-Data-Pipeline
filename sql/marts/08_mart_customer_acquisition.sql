-- mart_customer_acquisition: new customers per month and acquisition channel,
-- plus how many came back for a 2nd order within 90 days (a quick read on
-- channel QUALITY, not just volume).
DROP TABLE IF EXISTS mart_customer_acquisition;
CREATE TABLE mart_customer_acquisition AS
WITH cust_orders AS (                       -- order-level rows per customer
    SELECT f.customer_key, f.order_id, MIN(d.full_date) AS order_date
    FROM fact_order_items AS f
    JOIN dim_date AS d ON d.date_key = f.order_date_key
    WHERE f.order_status <> 'cancelled'
    GROUP BY f.customer_key, f.order_id
),
ranked AS (                                 -- 1 = first order, 2 = second order, ...
    SELECT customer_key, order_date,
           ROW_NUMBER() OVER (PARTITION BY customer_key ORDER BY order_date, order_id) AS rn
    FROM cust_orders
),
first_two AS (                              -- pivot the first two orders onto one row
    SELECT customer_key,
           MAX(CASE WHEN rn = 1 THEN order_date END) AS first_order_date,
           MAX(CASE WHEN rn = 2 THEN order_date END) AS second_order_date
    FROM ranked
    WHERE rn <= 2
    GROUP BY customer_key
)
SELECT
    DATE_FORMAT(ft.first_order_date, '%Y-%m-01')                       AS acquisition_month,
    c.acquisition_channel,
    COUNT(*)                                                           AS new_customers,
    -- DATEDIFF is NULL when there is no 2nd order; SUM ignores NULLs
    SUM(DATEDIFF(ft.second_order_date, ft.first_order_date) <= 90)     AS repeat_within_90d,
    ROUND(100 * SUM(DATEDIFF(ft.second_order_date, ft.first_order_date) <= 90) / COUNT(*), 2)
                                                                       AS repeat_90d_pct,
    -- Customers acquired in the last ~3 months haven't had 90 days to come back
    -- yet; flag those months so nobody reads their low repeat rate as churn.
    LAST_DAY(MAX(ft.first_order_date)) + INTERVAL 90 DAY
        <= (SELECT MAX(full_date) FROM dim_date)                       AS is_90d_window_complete
FROM first_two AS ft
JOIN dim_customer AS c ON c.customer_key = ft.customer_key
GROUP BY acquisition_month, c.acquisition_channel;

ALTER TABLE mart_customer_acquisition ADD PRIMARY KEY (acquisition_month, acquisition_channel);
