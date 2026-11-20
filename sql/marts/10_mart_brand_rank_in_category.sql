-- mart_brand_rank_in_category: top 5 brands inside each category.
-- PARTITION BY category restarts the ranking for every category. The rank
-- can't be filtered in the same SELECT's WHERE (window functions run after
-- WHERE), hence the CTE + outer WHERE.
DROP TABLE IF EXISTS mart_brand_rank_in_category;
CREATE TABLE mart_brand_rank_in_category AS
WITH brand_cat AS (
    SELECT p.category, p.brand,
           SUM(f.net_revenue)                  AS net_revenue,
           SUM(f.net_revenue - f.cost_amount)  AS gross_margin
    FROM fact_order_items AS f
    JOIN dim_product AS p ON p.product_key = f.product_key
    WHERE f.order_status <> 'cancelled'
    GROUP BY p.category, p.brand
),
ranked AS (
    SELECT brand_cat.*,
           RANK() OVER (PARTITION BY category ORDER BY net_revenue DESC)                   AS rank_in_category,
           ROUND(100 * net_revenue / SUM(net_revenue) OVER (PARTITION BY category), 2)     AS share_of_category_pct,
           ROUND(100 * gross_margin / NULLIF(net_revenue, 0), 2)                            AS margin_pct
    FROM brand_cat
)
SELECT * FROM ranked WHERE rank_in_category <= 5;

ALTER TABLE mart_brand_rank_in_category ADD PRIMARY KEY (category, brand);
