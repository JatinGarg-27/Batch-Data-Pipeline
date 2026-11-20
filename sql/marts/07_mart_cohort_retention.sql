-- mart_cohort_retention: for each acquisition cohort (first-purchase month),
-- the % of its customers who bought again N months later.
DROP TABLE IF EXISTS mart_cohort_retention;
CREATE TABLE mart_cohort_retention AS
SELECT
    cohort_month,
    month_number,
    COUNT(*)                                                         AS active_customers,
    -- A window function over an aggregate: GROUP BY runs first, then
    -- FIRST_VALUE picks the month-0 count (the cohort size) for every row of
    -- the same cohort. Month 0 always exists: it is the cohort's defining month.
    FIRST_VALUE(COUNT(*)) OVER (PARTITION BY cohort_month ORDER BY month_number) AS cohort_size,
    ROUND(100 * COUNT(*) /
          FIRST_VALUE(COUNT(*)) OVER (PARTITION BY cohort_month ORDER BY month_number), 2)
                                                                     AS retention_pct,
    SUM(net_revenue)                                                 AS net_revenue
FROM int_customer_month
GROUP BY cohort_month, month_number;

ALTER TABLE mart_cohort_retention ADD PRIMARY KEY (cohort_month, month_number);
