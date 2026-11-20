"""
Sanity checks on the loaded warehouse and marts (needs MySQL + a completed
`python -m pipeline run --stage all`; skipped otherwise).

These are reconciliation tests: the same number computed two different ways
must agree. If a join fans out or a filter is missing, they fail.
"""

import pytest

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def q():
    try:
        from pipeline.db import connect
        conn = connect(autocommit=True)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM mart_daily_sales")
    except Exception as exc:  # no DB / not loaded yet
        pytest.skip(f"warehouse not available: {exc}")

    def run(sql):
        cur.execute(sql)
        return cur.fetchall()
    yield run
    conn.close()


REALISED = "order_status <> 'cancelled'"


def test_daily_mart_revenue_equals_fact_revenue(q):
    (mart,), = q("SELECT SUM(net_revenue) FROM mart_daily_sales")
    (fact,), = q(f"SELECT SUM(net_revenue) FROM fact_order_items WHERE {REALISED}")
    assert mart == fact


def test_monthly_and_weekly_marts_reconcile_with_daily(q):
    (daily_rev, daily_orders), = q("SELECT SUM(net_revenue), SUM(orders) FROM mart_daily_sales")
    (m_rev, m_orders), = q("SELECT SUM(net_revenue), SUM(orders) FROM mart_monthly_sales")
    (w_rev,), = q("SELECT SUM(net_revenue) FROM mart_weekly_sales")
    assert m_rev == daily_rev == w_rev
    assert m_orders == daily_orders


def test_category_revenue_sums_to_total_and_contributions_to_100(q):
    (cat_rev,), = q("SELECT SUM(net_revenue) FROM mart_product_performance WHERE level = 'category'")
    (fact,), = q(f"SELECT SUM(net_revenue) FROM fact_order_items WHERE {REALISED}")
    assert cat_rev == fact
    for level, total in q("SELECT level, SUM(contribution_pct) FROM mart_product_performance GROUP BY level"):
        assert abs(float(total) - 100) < 0.5, level


def test_fact_measures_are_internally_consistent(q):
    (bad,), = q("""SELECT COUNT(*) FROM fact_order_items
                   WHERE net_revenue <> gross_amount - coupon_discount
                      OR net_revenue <= 0 OR gross_amount > mrp_amount
                      OR (is_returned = 1 AND refund_amount > net_revenue + 0.01)""")
    assert bad == 0


def test_conversion_rates_are_valid_and_sessions_reconcile(q):
    (max_cr, sessions), = q("SELECT MAX(conversion_rate_pct), SUM(sessions) FROM mart_conversion_daily_channel")
    (fact_sessions,), = q("SELECT SUM(sessions) FROM fact_sessions_daily")
    assert 0 < max_cr <= 100
    assert sessions == fact_sessions


def test_every_cohort_starts_at_100_pct_and_never_exceeds_it(q):
    rows = q("SELECT MIN(retention_pct), MAX(retention_pct) FROM mart_cohort_retention WHERE month_number = 0")
    assert rows[0] == (100, 100)
    (over,), = q("SELECT COUNT(*) FROM mart_cohort_retention WHERE retention_pct > 100")
    assert over == 0


def test_new_customers_counted_exactly_once(q):
    (new_total,), = q("SELECT SUM(new_customers) FROM mart_new_vs_returning")
    (buyers,), = q(f"SELECT COUNT(DISTINCT customer_key) FROM fact_order_items WHERE {REALISED}")
    (acquired,), = q("SELECT SUM(new_customers) FROM mart_customer_acquisition")
    assert new_total == buyers == acquired
