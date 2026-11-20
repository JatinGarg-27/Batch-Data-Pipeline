-- Merge order lines into the fact table.
--   * natural keys from staging are swapped for surrogate keys via the dims
--   * the sale event is found by DATE RANGE (the order date falls inside the
--     event window) -- a range join, not an equality join
--   * the coupon is found by its code
--   * money measures are pre-computed once here so every mart uses the same
--     definitions (net_revenue = selling price x qty - coupon)
-- ON DUPLICATE KEY UPDATE on the PK (order_item_id) => re-running never
-- duplicates rows; a changed status (e.g. shipped -> delivered) is updated.
-- Return columns are NOT touched here; 21_fact_returns.sql owns them.
INSERT INTO fact_order_items
    (order_item_id, order_id, order_date_key, customer_key, product_key, sale_event_key,
     coupon_key, order_status, channel, device, payment_method, quantity, mrp_amount,
     gross_amount, coupon_discount, net_revenue, cost_amount)
-- The SELECT is wrapped in a derived table (new_row) so the ON DUPLICATE KEY
-- UPDATE clause can refer to its computed columns by name.
SELECT * FROM (
SELECT
    oi.order_item_id,
    oi.order_id,
    CAST(DATE_FORMAT(o.order_date, '%Y%m%d') AS UNSIGNED) AS order_date_key,
    c.customer_key,
    p.product_key,
    se.promotion_key                                      AS sale_event_key,
    cp.promotion_key                                      AS coupon_key,
    o.order_status,
    o.channel,
    o.device,
    o.payment_method,
    oi.quantity,
    oi.quantity * oi.mrp                                  AS mrp_amount,
    oi.quantity * oi.selling_price                        AS gross_amount,
    oi.coupon_discount,
    oi.quantity * oi.selling_price - oi.coupon_discount   AS net_revenue,
    oi.quantity * p.cost_price                            AS cost_amount
FROM stg_order_items AS oi
JOIN stg_orders      AS o  ON o.order_id    = oi.order_id
JOIN dim_customer    AS c  ON c.customer_id = o.customer_id
JOIN dim_product     AS p  ON p.product_id  = oi.product_id
LEFT JOIN dim_promotion AS se
       ON se.promo_type = 'sale_event'
      AND o.order_date BETWEEN se.start_date AND se.end_date
LEFT JOIN dim_promotion AS cp
       ON cp.promo_code = o.coupon_code
) AS new_row
ON DUPLICATE KEY UPDATE
    order_date_key  = new_row.order_date_key,
    customer_key    = new_row.customer_key,
    product_key     = new_row.product_key,
    sale_event_key  = new_row.sale_event_key,
    coupon_key      = new_row.coupon_key,
    order_status    = new_row.order_status,
    channel         = new_row.channel,
    device          = new_row.device,
    payment_method  = new_row.payment_method,
    quantity        = new_row.quantity,
    mrp_amount      = new_row.mrp_amount,
    gross_amount    = new_row.gross_amount,
    coupon_discount = new_row.coupon_discount,
    net_revenue     = new_row.net_revenue,
    cost_amount     = new_row.cost_amount;
