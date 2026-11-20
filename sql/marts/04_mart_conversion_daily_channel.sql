-- mart_conversion_daily_channel: conversion rate = orders / sessions, by day and channel.
-- Orders include cancelled ones here: conversion measures the visit -> order
-- step, and the cancellation happens later.
DROP TABLE IF EXISTS mart_conversion_daily_channel;
CREATE TABLE mart_conversion_daily_channel AS
WITH s AS (
    SELECT session_date_key AS date_key, channel,
           SUM(sessions) AS sessions, SUM(converted_sessions) AS converted_sessions
    FROM fact_sessions_daily
    GROUP BY session_date_key, channel          -- collapse the device split
),
o AS (
    SELECT order_date_key AS date_key, channel, COUNT(DISTINCT order_id) AS orders
    FROM fact_order_items
    GROUP BY order_date_key, channel
),
joined AS (
    SELECT d.full_date, d.is_sale_day, s.channel, s.sessions, s.converted_sessions,
           COALESCE(o.orders, 0) AS orders
    FROM s
    JOIN dim_date AS d ON d.date_key = s.date_key
    LEFT JOIN o ON o.date_key = s.date_key AND o.channel = s.channel
)
SELECT
    joined.*,
    ROUND(100 * orders / NULLIF(sessions, 0), 3)                       AS conversion_rate_pct,
    -- Rolling 7-day conversion per channel as a RATIO OF SUMS (total orders /
    -- total sessions over 7 days), not an average of 7 daily ratios -- the
    -- latter would give a quiet Tuesday the same weight as a sale Saturday.
    ROUND(100 * SUM(orders) OVER w7 / NULLIF(SUM(sessions) OVER w7, 0), 3) AS conversion_rate_7d_pct
FROM joined
WINDOW w7 AS (PARTITION BY channel ORDER BY full_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW);

ALTER TABLE mart_conversion_daily_channel ADD PRIMARY KEY (full_date, channel);
