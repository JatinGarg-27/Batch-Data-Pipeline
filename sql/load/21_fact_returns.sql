-- Apply returns to their order line. An UPDATE ... JOIN (not part of the
-- insert above) so that a return arriving days after its order -- i.e. in a
-- later incremental batch than the order itself -- still lands on the right row.
UPDATE fact_order_items AS f
JOIN stg_returns AS r ON r.order_item_id = f.order_item_id
SET f.is_returned     = 1,
    f.return_date_key = CAST(DATE_FORMAT(r.return_date, '%Y%m%d') AS UNSIGNED),
    f.refund_amount   = r.refund_amount;
