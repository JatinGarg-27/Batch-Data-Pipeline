-- int_customer_month (intermediate): one row per customer per month they
-- bought in, tagged with their cohort (month of first purchase).
-- Shared by the new-vs-returning and cohort-retention marts.
-- A customer is "acquired" by their first NON-cancelled order.
DROP TABLE IF EXISTS int_customer_month;
CREATE TABLE int_customer_month AS
WITH cm AS (
    SELECT f.customer_key, d.month_start,
           COUNT(DISTINCT f.order_id) AS orders,
           SUM(f.net_revenue)         AS net_revenue
    FROM fact_order_items AS f
    JOIN dim_date AS d ON d.date_key = f.order_date_key
    WHERE f.order_status <> 'cancelled'
    GROUP BY f.customer_key, d.month_start
)
SELECT
    cm.*,
    -- MIN() as a WINDOW function: every row of a customer gets that customer's
    -- first month, without collapsing the rows the way GROUP BY would.
    MIN(month_start) OVER (PARTITION BY customer_key)                              AS cohort_month,
    TIMESTAMPDIFF(MONTH, MIN(month_start) OVER (PARTITION BY customer_key), month_start) AS month_number
FROM cm;

ALTER TABLE int_customer_month
    ADD PRIMARY KEY (customer_key, month_start),
    ADD KEY idx_icm_cohort (cohort_month, month_number);
