# MART LAYER - analysis-ready tables built from the star schema.
Files run in name order; each one DROPs and re-CREATEs its tables, so the
transform stage is idempotent (marts are always fully derived from facts).

Business definitions shared by every mart:
  realised line   : order_status <> 'cancelled' (delivered + shipped)
  net_revenue     : what the customer paid = selling price x qty - coupon
  discount_cost   : MRP value - net_revenue (markdown + coupon given away)
  gross_margin    : net_revenue - cost of goods, BEFORE returns
  margin_pct      : gross_margin / net_revenue
  AOV             : net_revenue / number of orders
  conversion rate : orders / sessions
Every ratio uses NULLIF(denominator, 0) so an empty day/segment yields NULL
instead of a division-by-zero error.
=====================================================================
