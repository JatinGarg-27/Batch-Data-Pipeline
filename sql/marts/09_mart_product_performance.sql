-- mart_product_performance: revenue, margin, return rate and rankings for
-- categories, sub-categories, brands and styles in one table (`level` column).
--
-- Return rate only counts "mature" lines: ordered >= 30 days before the last
-- order date. Lines from the final weeks haven't finished their return window
-- yet, so including them would understate the return rate.
DROP TABLE IF EXISTS mart_product_performance;
CREATE TABLE mart_product_performance AS
WITH line_facts AS (
    SELECT p.category, p.sub_category, p.brand, p.style,
           f.quantity, f.net_revenue, f.cost_amount, f.mrp_amount, f.is_returned,
           f.order_date_key <= (SELECT CAST(DATE_FORMAT(MAX(full_date) - INTERVAL 30 DAY, '%Y%m%d') AS UNSIGNED)
                                FROM dim_date AS d JOIN fact_order_items AS x ON x.order_date_key = d.date_key)
                                                                     AS is_mature
    FROM fact_order_items AS f
    JOIN dim_product AS p ON p.product_key = f.product_key
    WHERE f.order_status <> 'cancelled'
),
by_level AS (
    -- the same aggregation at four levels, stacked with UNION ALL
    SELECT 'category' AS level, category AS name, SUM(quantity) AS units, SUM(net_revenue) AS net_revenue,
           SUM(net_revenue - cost_amount) AS gross_margin,
           SUM(CASE WHEN is_returned = 0 THEN net_revenue - cost_amount ELSE 0 END) AS margin_after_returns,
           SUM(is_mature) AS mature_lines, SUM(is_mature AND is_returned = 1) AS mature_returned_lines
    FROM line_facts GROUP BY category
    UNION ALL
    SELECT 'sub_category', sub_category, SUM(quantity), SUM(net_revenue), SUM(net_revenue - cost_amount),
           SUM(CASE WHEN is_returned = 0 THEN net_revenue - cost_amount ELSE 0 END),
           SUM(is_mature), SUM(is_mature AND is_returned = 1)
    FROM line_facts GROUP BY sub_category
    UNION ALL
    SELECT 'brand', brand, SUM(quantity), SUM(net_revenue), SUM(net_revenue - cost_amount),
           SUM(CASE WHEN is_returned = 0 THEN net_revenue - cost_amount ELSE 0 END),
           SUM(is_mature), SUM(is_mature AND is_returned = 1)
    FROM line_facts GROUP BY brand
    UNION ALL
    SELECT 'style', style, SUM(quantity), SUM(net_revenue), SUM(net_revenue - cost_amount),
           SUM(CASE WHEN is_returned = 0 THEN net_revenue - cost_amount ELSE 0 END),
           SUM(is_mature), SUM(is_mature AND is_returned = 1)
    FROM line_facts GROUP BY style
),
metrics AS (
    SELECT by_level.*,
           ROUND(100 * gross_margin / NULLIF(net_revenue, 0), 2)               AS margin_pct,
           ROUND(100 * margin_after_returns / NULLIF(net_revenue, 0), 2)       AS margin_after_returns_pct,
           ROUND(100 * mature_returned_lines / NULLIF(mature_lines, 0), 1)     AS return_rate_pct
    FROM by_level
)
SELECT
    metrics.*,
    -- RANK vs DENSE_RANK: with a tie for 2nd, RANK gives 1,2,2,4 (skips 3)
    -- while DENSE_RANK gives 1,2,2,3. Revenue rarely ties; return rates are
    -- rounded to 0.1% so they do tie, and DENSE_RANK keeps the ranks compact.
    RANK()       OVER (PARTITION BY level ORDER BY net_revenue DESC)           AS revenue_rank,
    DENSE_RANK() OVER (PARTITION BY level ORDER BY return_rate_pct DESC)       AS return_rate_rank,
    -- share of the level's total revenue: SUM() OVER the whole partition
    ROUND(100 * net_revenue / SUM(net_revenue) OVER (PARTITION BY level), 2)   AS contribution_pct,
    -- running total in revenue order -> Pareto curve ("top N brands = X%")
    ROUND(100 * SUM(net_revenue) OVER (PARTITION BY level ORDER BY net_revenue DESC
                                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
              / SUM(net_revenue) OVER (PARTITION BY level), 2)                  AS cumulative_contribution_pct
FROM metrics;

ALTER TABLE mart_product_performance ADD PRIMARY KEY (level, name);
