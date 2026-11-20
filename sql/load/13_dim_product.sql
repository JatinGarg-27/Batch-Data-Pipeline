-- Upsert products (SCD type 1). Note: cost_price is overwritten, so margin
-- is always computed with the *current* cost -- a known simplification; a
-- type-2 dimension (valid_from/valid_to) would be needed for historical cost.
INSERT INTO dim_product
    (product_id, product_name, brand, category, sub_category, style, mrp, cost_price)
SELECT product_id, product_name, brand, category, sub_category, style, mrp, cost_price
FROM stg_products AS s
ON DUPLICATE KEY UPDATE
    product_name = s.product_name,
    brand        = s.brand,
    category     = s.category,
    sub_category = s.sub_category,
    style        = s.style,
    mrp          = s.mrp,
    cost_price   = s.cost_price;
