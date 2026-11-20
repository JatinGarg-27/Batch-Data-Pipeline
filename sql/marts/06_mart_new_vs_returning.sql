-- mart_new_vs_returning: per month, customers buying for the first time (new)
-- vs customers who had bought in an earlier month (returning).
DROP TABLE IF EXISTS mart_new_vs_returning;
CREATE TABLE mart_new_vs_returning AS
SELECT
    month_start,
    SUM(month_number = 0)                                                    AS new_customers,
    SUM(month_number > 0)                                                    AS returning_customers,
    SUM(CASE WHEN month_number = 0 THEN net_revenue ELSE 0 END)              AS new_customer_revenue,
    SUM(CASE WHEN month_number > 0 THEN net_revenue ELSE 0 END)              AS returning_customer_revenue,
    ROUND(100 * SUM(month_number > 0) / COUNT(*), 2)                         AS returning_customer_pct,
    ROUND(100 * SUM(CASE WHEN month_number > 0 THEN net_revenue ELSE 0 END)
              / NULLIF(SUM(net_revenue), 0), 2)                              AS returning_revenue_pct,
    ROUND(SUM(orders) / COUNT(*), 3)                                         AS orders_per_customer
FROM int_customer_month
GROUP BY month_start;

ALTER TABLE mart_new_vs_returning ADD PRIMARY KEY (month_start);
