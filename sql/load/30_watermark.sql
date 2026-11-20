-- Advance the incremental watermark to the latest order date merged.
-- GREATEST(...) means it never moves backwards, even if an older batch is re-run.
INSERT INTO etl_watermark (table_name, high_watermark)
SELECT * FROM (
    SELECT 'fact_order_items' AS table_name, MAX(order_date) AS hw FROM stg_orders
) AS new_row
WHERE new_row.hw IS NOT NULL
ON DUPLICATE KEY UPDATE
    high_watermark = GREATEST(etl_watermark.high_watermark, new_row.hw);
