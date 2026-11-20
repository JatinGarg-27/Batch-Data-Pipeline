-- Upsert promotions (sale events + coupons). Type-1 dimension: a changed
-- attribute simply overwrites the old value (no history kept).
-- INSERT ... ON DUPLICATE KEY UPDATE makes the load idempotent: re-running it
-- with the same staging data updates rows in place instead of duplicating them.
INSERT INTO dim_promotion
    (promotion_id, promo_code, promo_name, promo_type, start_date, end_date,
     discount_pct, max_discount, min_order_value)
SELECT promotion_id, promo_code, promo_name, promo_type, start_date, end_date,
       discount_pct, max_discount, min_order_value
FROM stg_promotions AS s
ON DUPLICATE KEY UPDATE
    promo_code      = s.promo_code,
    promo_name      = s.promo_name,
    promo_type      = s.promo_type,
    start_date      = s.start_date,
    end_date        = s.end_date,
    discount_pct    = s.discount_pct,
    max_discount    = s.max_discount,
    min_order_value = s.min_order_value;
