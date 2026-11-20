-- Build every calendar day covered by the batch with a RECURSIVE CTE.
-- The anchor row is the earliest date seen; each recursive step adds one day
-- until the latest date. (cte_max_recursion_depth is raised in docker-compose.)
-- Weekend/sale flags are attributes of the DATE, so they live here, not in facts.
INSERT INTO dim_date
    (date_key, full_date, day_of_week, day_name, is_weekend, week_start, month_start,
     month_num, month_name, quarter_num, year_num, is_sale_day, sale_event_code)
SELECT * FROM (
WITH RECURSIVE bounds AS (
    SELECT LEAST(
               (SELECT MIN(order_date)   FROM stg_orders),
               (SELECT MIN(session_date) FROM stg_sessions)) AS d_min,
           GREATEST(
               (SELECT MAX(order_date)   FROM stg_orders),
               (SELECT MAX(session_date) FROM stg_sessions),
               COALESCE((SELECT MAX(return_date) FROM stg_returns), '1900-01-01')) AS d_max
),
days AS (
    SELECT d_min AS d FROM bounds
    UNION ALL
    SELECT d + INTERVAL 1 DAY FROM days, bounds WHERE d < bounds.d_max
)
SELECT
    CAST(DATE_FORMAT(d, '%Y%m%d') AS UNSIGNED)          AS date_key,
    d                                                   AS full_date,
    WEEKDAY(d) + 1                                      AS day_of_week,   -- WEEKDAY: Mon=0
    DAYNAME(d)                                          AS day_name,
    WEEKDAY(d) >= 5                                     AS is_weekend,
    d - INTERVAL WEEKDAY(d) DAY                         AS week_start,
    DATE_FORMAT(d, '%Y-%m-01')                          AS month_start,
    MONTH(d)                                            AS month_num,
    MONTHNAME(d)                                        AS month_name,
    QUARTER(d)                                          AS quarter_num,
    YEAR(d)                                             AS year_num,
    p.promotion_id IS NOT NULL                          AS is_sale_day,
    p.promo_code                                        AS sale_event_code
FROM days
LEFT JOIN dim_promotion AS p
       ON p.promo_type = 'sale_event'
      AND days.d BETWEEN p.start_date AND p.end_date
) AS new_row
ON DUPLICATE KEY UPDATE
    is_sale_day     = new_row.is_sale_day,
    sale_event_code = new_row.sale_event_code;
