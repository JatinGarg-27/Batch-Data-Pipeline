-- Transformation stage: turns the normalized raw tables into
-- analysis-ready tables using joins, aggregations, and window functions.
-- Only 'completed' and 'shipped' orders count as realized revenue.

DROP TABLE IF EXISTS analytics_order_line_items;
DROP TABLE IF EXISTS analytics_revenue_by_category;
DROP TABLE IF EXISTS analytics_customer_ltv;
DROP TABLE IF EXISTS analytics_monthly_revenue_trend;
DROP TABLE IF EXISTS analytics_top_products_by_category;

-- 1. Fact table: one row per order line item, joined & flattened for
--    downstream aggregation. (JOIN)
CREATE TABLE analytics_order_line_items AS
SELECT
    oi.order_item_id,
    o.order_id,
    o.order_date,
    o.status,
    c.customer_id,
    c.first_name || ' ' || c.last_name AS customer_name,
    c.city,
    c.state,
    p.product_id,
    p.product_name,
    p.category,
    oi.quantity,
    oi.unit_price,
    ROUND(oi.quantity * oi.unit_price, 2) AS line_revenue
FROM order_items oi
JOIN orders o     ON o.order_id = oi.order_id
JOIN customers c  ON c.customer_id = o.customer_id
JOIN products p   ON p.product_id = oi.product_id
WHERE o.status IN ('completed', 'shipped');

-- 2. Revenue by category. (JOIN + GROUP BY aggregation)
CREATE TABLE analytics_revenue_by_category AS
SELECT
    category,
    COUNT(DISTINCT order_id)        AS order_count,
    SUM(quantity)                   AS units_sold,
    ROUND(SUM(line_revenue), 2)     AS total_revenue,
    ROUND(AVG(line_revenue), 2)     AS avg_line_revenue
FROM analytics_order_line_items
GROUP BY category
ORDER BY total_revenue DESC;

-- 3. Customer lifetime value, ranked by spend. (GROUP BY + window function)
CREATE TABLE analytics_customer_ltv AS
SELECT
    customer_id,
    customer_name,
    COUNT(DISTINCT order_id)                                        AS order_count,
    ROUND(SUM(line_revenue), 2)                                     AS lifetime_value,
    ROUND(SUM(line_revenue) / COUNT(DISTINCT order_id), 2)          AS avg_order_value,
    RANK() OVER (ORDER BY SUM(line_revenue) DESC)                   AS spend_rank
FROM analytics_order_line_items
GROUP BY customer_id, customer_name
ORDER BY spend_rank;

-- 4. Monthly revenue trend with a running total. (GROUP BY + window function)
CREATE TABLE analytics_monthly_revenue_trend AS
SELECT
    strftime('%Y-%m', order_date)                                            AS month,
    ROUND(SUM(line_revenue), 2)                                              AS monthly_revenue,
    ROUND(SUM(SUM(line_revenue)) OVER (ORDER BY strftime('%Y-%m', order_date)), 2)
                                                                              AS running_total_revenue
FROM analytics_order_line_items
GROUP BY month
ORDER BY month;

-- 5. Top 3 products per category by revenue. (window function partitioned by category)
CREATE TABLE analytics_top_products_by_category AS
WITH product_revenue AS (
    SELECT
        category,
        product_name,
        ROUND(SUM(line_revenue), 2) AS product_revenue,
        RANK() OVER (PARTITION BY category ORDER BY SUM(line_revenue) DESC) AS category_rank
    FROM analytics_order_line_items
    GROUP BY category, product_name
)
SELECT category, product_name, product_revenue, category_rank
FROM product_revenue
WHERE category_rank <= 3
ORDER BY category, category_rank;
