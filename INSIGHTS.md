# Insights & recommendations

> **Read this first.** The dataset is **synthetic** (see `scripts/generate_data.py`). The *patterns*
> below were produced by the generator's assumptions (sale-driven demand, category return rates,
> channel conversion rates...), so their exact sizes say nothing about any real company. What this
> document demonstrates is the analytics workflow: every number was computed by the SQL marts
> (`sql/marts/`) and `analysis/make_charts.py` on the 1M-order-line run, then turned into a
> recommendation the way I would for a merchandising or growth team.
> Numbers: `analysis/outputs/metrics.json`, `reports/forecast_results.md`.

**Business at a glance (Jan 2024 – Dec 2025, cancelled orders excluded):** ₹101.9 Cr net revenue
from 573,593 orders by 241,658 customers · AOV ₹1,777 · average discount 42.4% off MRP ·
gross margin 39.3% (before returns) · conversion 5.43% of sessions.

---

### 1. Sale events buy revenue with margin, so the discount depth matters more than the event
| Metric | Sale days | Regular days |
|---|---:|---:|
| Share of days | 48 of 731 (6.6%) | 683 |
| Avg daily net revenue | ₹37.8 L | ₹12.3 L |
| Discount (% of MRP) | 52.4% | 39.7% |
| Gross margin % | 26.6% | 42.1% |

Sale days bring **17.8% of revenue but only 12.1% of gross margin**. Big Fashion Days 2025 lifted
daily revenue **+289%** over its 28-day baseline, but margin fell from 42.0% to **22.9%**. It still
added ₹51.2 L of incremental gross margin, because the higher volume more than made up for the lower
margin per order.

**What it means:** events are profitable in rupees, but every extra point of markdown during an event costs margin at 3x the usual volume.
**Action:** keep the events, but test a shallower extra markdown (e.g. 10% instead of 15%) on
categories that sell well anyway and on high-return categories (finding 2). Also measure the pre-sale dip: the baseline does not
capture shoppers who delay purchases for the sale, so the uplift is an upper bound.
*(mart_sale_event_effectiveness, mart_sale_vs_regular_days, chart 07)*

### 2. Dresses and Footwear make the most money and lose the most to returns, mostly over size
| Category | Revenue share | Return rate | Margin before → after returns |
|---|---:|---:|---:|
| Footwear (#1 by revenue) | 18.2% | 21.6% | 39.5% → **30.5%** |
| Dresses | 11.2% | **31.8%** | 38.8% → **26.8%** |
| Beauty (for contrast) | 6.6% | 2.4% | 39.5% → 38.6% |

Worst sub-categories: Bodycon Dresses 35.6%, Maxi Dresses 31.8%, Heels 28.8%. In the size-based
categories, **~65% of returns give a size reason**. Refunds total ₹16.2 Cr, **15.9% of net revenue**.
COD orders are returned more often than prepaid ones (16.4% vs 13.7%).

**What it means:** at a 32% return rate, a dress sale is worth much less than its gross margin suggests.
**Action:** start with Dresses and Heels: add size guides with garment measurements, "runs small/large" prompts based on
past return reasons, and size exchange instead of refund. Test a small prepaid incentive to shift orders
away from COD. Track *margin after returns*, not just margin.
*(mart_product_performance, chart 05; return-reason split from the cleaned returns data)*

### 3. Social media brings a third of traffic but the weakest customers
| Channel | Sessions | Conversion | New customers re-ordering within 90 days |
|---|---:|---:|---:|
| Social | 3.68 M (32.7%) | **2.46%** | **29.4%** |
| Paid search | 2.25 M | 4.59% | 40.1% |
| Organic search | 2.39 M | 6.15% | 45.6% |
| Direct | 1.63 M | 10.25% | 51.7% |

**What it means:** social visitors are 4x less likely to order than direct visitors, and the customers social does bring are
much less likely to come back. Judged on cost per acquisition alone, social looks better than it is.
**Action:** judge acquisition channels on 90-day customer value, not first-order cost per acquisition. Move part of
the social budget to retargeting existing visitors, and to search, which brings customers who come back.
*(mart_conversion_daily_channel, mart_customer_acquisition, chart 03)*

### 4. Retention drops after the first month, and returning customers now drive most revenue
Average cohort retention is **22.5% in month 1 and 16.5% by month 3**. Returning customers' share of
monthly revenue rose from 42.3% (Jun 2024) to **58.2% (Dec 2025)**, and email, the CRM channel,
converts at **8.69%**, second only to direct.

**What it means:** the existing base is now the bigger revenue engine, and most of the drop-off
happens between the first and third month.
**Action:** set up an automated sequence 20–40 days after the first order (recommendations based
on the first purchase, plus a reminder of the size exchange policy), and track month-1 to month-3 retention
by cohort in `mart_cohort_retention`.
*(mart_cohort_retention, mart_new_vs_returning, charts 04 and 08)*

### 5. The new-customer coupon is the most expensive promotion and nobody has tested whether it is needed
| Coupon | Orders | Coupon cost (% of gross) | AOV | Margin % |
|---|---:|---:|---:|---:|
| No coupon | 459,099 | – | ₹1,722 | 40.7% |
| NEW15 (first order) | 89,349 | 10.5% (₹1.94 Cr) | ₹1,854 | **34.3%** |
| FEST25 (festive, min ₹1,499) | 5,509 | 13.9% | ₹2,742 | 30.8% |

**What it means:** NEW15 costs ₹1.94 Cr and cuts margin by 6 points on first orders. Festive coupons
push baskets up (AOV ₹2,742 vs ₹1,722) because of the ₹1,499 minimum, but at the lowest margin of any
promotion. This data can't tell whether those customers would have ordered anyway.
**Action:** run an A/B test of NEW15 against a lower cap (₹200) or no coupon for a holdout group, and
measure first-order conversion and 90-day value, not just redemption.
*(mart_coupon_performance)*

### 6. Year-over-year by month is misleading in festive months, so compare event-aligned windows
FY2025 net revenue was ₹61.4 Cr vs ₹40.5 Cr in FY2024 (+51.6%). That is inflated because the business
launched in Jan 2024, so **H2 2025 vs H2 2024 (+29.8%)** is the fairer read. October 2025 shows
**−15.5% YoY** only because Big Fashion Days moved from October (2024) to September (2025). September
+ October combined grew **+29.7%** (₹10.4 Cr → ₹13.5 Cr).

**Action:** report festive-season performance on event-aligned windows (or Sep+Oct together), and
annotate dashboards with the sale calendar so a calendar shift isn't read as a drop in demand.
*(mart_monthly_sales, chart 02)*

### 7. Demand forecast: good enough for Footwear planning, not yet for seasonal categories
30-day holdout (2–31 Dec 2025, includes the End of Reason Sale), MAPE on daily units:

| Category | Seasonal naive (baseline) | 28-day average | Regression (trend + weekday + sale flag) |
|---|---:|---:|---:|
| Footwear | 20.7% | 24.5% | **7.9%** |
| Topwear | **20.8%** | 23.7% | 34.7% |
| Ethnic Wear | 63.8% | 66.7% | 53.2% |

The regression wins clearly on Footwear, mostly because it knows the sale calendar (7.7% MAPE on
sale days vs 68.5% for the naive baseline). It **loses to the naive baseline on Topwear** and nothing
works for Ethnic Wear. Both categories have yearly seasonality (winter sweatshirts, festive ethnic
wear) that a model with no yearly term cannot learn from one year of history. I fixed the model before
looking at the holdout and did not tune it afterwards.

**Action:** use the regression for Footwear stock planning around sales. For Topwear and Ethnic Wear
keep the naive baseline, and add a "same period last year" feature once there are two full years of
history to train on.
*(analysis/forecast.py, reports/forecast_results.md, chart 09)*
