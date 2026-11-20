-- Aggregate the batch's visit-level sessions to day x channel x device.
--
-- Two aggregates joined together:
--   s_agg : sessions per day/channel/device. stg_sessions is clustered on
--           exactly these columns, so GROUP BY reads rows in group order.
--   c_agg : converting sessions = distinct session_ids that placed an order.
--           An order's channel/device/date are attributed from the session
--           that placed it, so they can be grouped from stg_orders directly
--           (615k rows) instead of joining back into 11.6M sessions.
-- LEFT JOIN keeps day/channel/device combinations that had no orders (0).
--
-- Idempotent: PK is (date, channel, device); a re-run overwrites the day's
-- numbers. Incremental batches always contain whole days (filtered on
-- date >= cutoff), so an overwritten day is never partial.
INSERT INTO fact_sessions_daily
    (session_date_key, channel, device, sessions, logged_in_sessions, converted_sessions,
     pages_viewed)
SELECT * FROM (
    WITH s_agg AS (
        SELECT session_date, channel, device,
               COUNT(*)                          AS sessions,
               SUM(customer_id IS NOT NULL)      AS logged_in_sessions,  -- TRUE counts as 1
               SUM(COALESCE(pages_viewed, 0))    AS pages_viewed
        FROM stg_sessions
        GROUP BY session_date, channel, device
    ),
    c_agg AS (
        SELECT order_date AS session_date, channel, device,
               COUNT(DISTINCT session_id)        AS converted_sessions
        FROM stg_orders
        WHERE session_id IS NOT NULL
        GROUP BY order_date, channel, device
    )
    SELECT
        CAST(DATE_FORMAT(s.session_date, '%Y%m%d') AS UNSIGNED) AS session_date_key,
        s.channel,
        s.device,
        s.sessions,
        s.logged_in_sessions,
        COALESCE(c.converted_sessions, 0)                        AS converted_sessions,
        s.pages_viewed
    FROM s_agg AS s
    LEFT JOIN c_agg AS c
           ON c.session_date = s.session_date
          AND c.channel      = s.channel
          AND c.device       = s.device
) AS new_row
ON DUPLICATE KEY UPDATE
    sessions           = new_row.sessions,
    logged_in_sessions = new_row.logged_in_sessions,
    converted_sessions = new_row.converted_sessions,
    pages_viewed       = new_row.pages_viewed;
