"""
Query the marts and produce the analysis charts + a metrics file.

    python analysis/make_charts.py

Outputs
  analysis/charts/*.png          8 charts used in README / INSIGHTS
  analysis/outputs/metrics.json  every number quoted in INSIGHTS.md, computed here

Charts are static PNGs (matplotlib). Design rules followed: one y-axis per
panel (two measures -> two panels, never a dual axis), fixed categorical
colour order, thin marks, recessive grid, direct labels only where they help.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator, MultipleLocator, PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.db import engine  # noqa: E402

CHART_DIR = ROOT / "analysis" / "charts"
OUT_DIR = ROOT / "analysis" / "outputs"

# Validated categorical palette (fixed order) + text/surface tokens
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
SALE_BAND = "#f3efe6"
SEQ_BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.titlepad": 22, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "font.size": 10, "legend.frameon": False, "figure.dpi": 100,
})


def rupees(v, _=None) -> str:
    """Indian units: Cr = 1e7, L (lakh) = 1e5."""
    if abs(v) >= 1e7:
        return f"₹{v / 1e7:.1f} Cr"
    if abs(v) >= 1e5:
        return f"₹{v / 1e5:.0f} L"
    return f"₹{v:,.0f}"


def save(fig, name: str) -> None:
    fig.savefig(CHART_DIR / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  chart ->", f"analysis/charts/{name}")


def subtitle(ax, text: str) -> None:
    ax.text(0, 1.015, text, transform=ax.transAxes, color=INK_2, fontsize=9, va="bottom")


def main() -> None:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    e = engine()
    q = lambda sql: pd.read_sql(sql, e)  # noqa: E731
    m: dict = {}

    # ------------------------------------------------------------------ 1. daily revenue
    daily = q("SELECT full_date, net_revenue, net_revenue_7d_ma, is_sale_day, sale_event_code "
              "FROM mart_daily_sales ORDER BY full_date")
    daily["full_date"] = pd.to_datetime(daily["full_date"])
    fig, ax = plt.subplots(figsize=(11, 4.6))
    for code, g in daily[daily.is_sale_day == 1].groupby("sale_event_code"):
        ax.axvspan(g.full_date.min() - pd.Timedelta(hours=12), g.full_date.max() + pd.Timedelta(hours=12),
                   color=SALE_BAND, lw=0, zorder=0)
        if code.startswith(("BFD", "EORS")):
            peak = daily.loc[g.index, "net_revenue"].max()
            ax.annotate(code, (g.full_date.mean(), peak), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=8, color=INK_2)
    ax.plot(daily.full_date, daily.net_revenue, color=MUTED, lw=0.8, alpha=0.7, label="Daily net revenue")
    ax.plot(daily.full_date, daily.net_revenue_7d_ma, color=BLUE, lw=2, label="7-day moving average")
    ax.yaxis.set_major_formatter(FuncFormatter(rupees))
    ax.set_title("Daily net revenue: sale events drive the spikes")
    subtitle(ax, "Shaded = sale-event days. Cancelled orders excluded.")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 0.97))
    ax.set_ylim(0, daily.net_revenue.max() * 1.12)
    save(fig, "01_daily_revenue_7d_ma.png")

    # ------------------------------------------------------------------ 2. monthly revenue + margin
    mon = q("SELECT month_start, net_revenue, margin_pct, discount_pct_of_mrp, aov, "
            "orders_per_customer, mom_growth_pct, yoy_growth_pct FROM mart_monthly_sales ORDER BY month_start")
    mon["month_start"] = pd.to_datetime(mon["month_start"])
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True,
                                 gridspec_kw={"height_ratios": [1.6, 1], "hspace": 0.25})
    a1.bar(mon.month_start, mon.net_revenue, width=22, color=BLUE)
    a1.yaxis.set_major_formatter(FuncFormatter(rupees))
    a1.set_title("Monthly net revenue and gross margin %")
    subtitle(a1, "Two panels, one y-axis each. Margin drops in sale months (Jun, Sep/Oct, Dec).")
    a2.plot(mon.month_start, mon.margin_pct, color=ORANGE, lw=2, marker="o", ms=4)
    a2.yaxis.set_major_locator(MultipleLocator(2))
    a2.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    a2.set_ylabel("Gross margin %")
    a1.set_ylabel("Net revenue")
    save(fig, "02_monthly_revenue_and_margin.png")

    # ------------------------------------------------------------------ 3. channel quality
    conv = q("SELECT channel, SUM(sessions) sessions, SUM(orders) orders FROM mart_conversion_daily_channel "
             "WHERE channel <> 'unknown' GROUP BY channel")
    conv["cr"] = 100 * conv.orders / conv.sessions
    acq = q("SELECT acquisition_channel channel, SUM(new_customers) new_customers, "
            "SUM(repeat_within_90d) rep FROM mart_customer_acquisition WHERE is_90d_window_complete = 1 "
            "GROUP BY acquisition_channel")
    acq["repeat_90d_pct"] = 100 * acq.rep / acq.new_customers
    conv = conv.sort_values("cr")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"wspace": 0.45})
    a1.barh(conv.channel, conv.cr, color=BLUE, height=0.6)
    for y, v in enumerate(conv.cr):
        a1.text(v + 0.15, y, f"{v:.1f}%", va="center", fontsize=9, color=INK)
    a1.set_title("Conversion rate (orders / sessions)")
    a1.xaxis.set_major_formatter(PercentFormatter(decimals=0))
    a1.grid(axis="y", visible=False)
    acq = acq.sort_values("repeat_90d_pct")
    a2.barh(acq.channel, acq.repeat_90d_pct, color=BLUE, height=0.6)
    for y, v in enumerate(acq.repeat_90d_pct):
        a2.text(v + 0.6, y, f"{v:.1f}%", va="center", fontsize=9, color=INK)
    a2.set_title("New customers ordering again within 90 days")
    a2.xaxis.set_major_formatter(PercentFormatter(decimals=0))
    a2.grid(axis="y", visible=False)
    a1.set_xlim(0, conv.cr.max() * 1.2)
    a2.set_xlim(0, acq.repeat_90d_pct.max() * 1.2)
    fig.suptitle("Channel quality: social brings traffic but converts and retains worst",
                 x=0.06, ha="left", fontweight="bold", fontsize=12, y=1.08)
    save(fig, "03_channel_conversion_and_repeat.png")
    m["conversion_by_channel_pct"] = conv.set_index("channel").cr.round(2).to_dict()
    m["sessions_by_channel"] = conv.set_index("channel").sessions.astype(int).to_dict()
    m["repeat_90d_by_acq_channel_pct"] = acq.set_index("channel").repeat_90d_pct.round(1).to_dict()
    m["new_customers_by_acq_channel"] = acq.set_index("channel").new_customers.astype(int).to_dict()
    tot = conv[["sessions", "orders"]].sum()
    m["overall_conversion_pct"] = round(100 * tot.orders / tot.sessions, 2)

    # ------------------------------------------------------------------ 4. cohort retention heatmap
    coh = q("SELECT cohort_month, month_number, retention_pct, cohort_size FROM mart_cohort_retention "
            "WHERE month_number BETWEEN 1 AND 12")
    piv = coh.pivot(index="cohort_month", columns="month_number", values="retention_pct").astype(float)
    piv.index = pd.to_datetime(piv.index).strftime("%b %Y")
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("blues", SEQ_BLUES)
    fig, ax = plt.subplots(figsize=(11, 7.5))
    im = ax.imshow(piv.values, cmap=cmap, aspect="auto", vmin=0, vmax=np.nanmax(piv.values))
    ax.set_xticks(range(piv.shape[1]), [f"M{c}" for c in piv.columns])
    ax.set_yticks(range(piv.shape[0]), piv.index)
    ax.grid(False)
    for (i, j), v in np.ndenumerate(piv.values):
        if not np.isnan(v):
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7,
                    color="white" if v > np.nanmax(piv.values) * 0.55 else INK)
    ax.set_title("Monthly cohort retention: % of each cohort buying again N months later")
    subtitle(ax, "Cohort = month of first purchase. Month 0 (always 100%) omitted. Blank = not observable yet.")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, format=PercentFormatter(decimals=0))
    cb.outline.set_visible(False)
    save(fig, "04_cohort_retention_heatmap.png")
    m1 = coh[coh.month_number == 1]
    m["avg_m1_retention_pct"] = round(float((m1.retention_pct * m1.cohort_size).sum() / m1.cohort_size.sum()), 1)
    m3 = coh[coh.month_number == 3]
    m["avg_m3_retention_pct"] = round(float((m3.retention_pct * m3.cohort_size).sum() / m3.cohort_size.sum()), 1)

    # ------------------------------------------------------------------ 5. category revenue vs returns
    cat = q("SELECT name category, net_revenue, contribution_pct, margin_pct, margin_after_returns_pct, "
            "return_rate_pct FROM mart_product_performance WHERE level = 'category' ORDER BY net_revenue")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True, gridspec_kw={"wspace": 0.08})
    a1.barh(cat.category, cat.net_revenue, color=BLUE, height=0.6)
    a1.xaxis.set_major_locator(MaxNLocator(4))
    a1.xaxis.set_major_formatter(FuncFormatter(rupees))
    a1.set_title("Net revenue")
    a1.grid(axis="y", visible=False)
    colors = [ORANGE if r >= 15 else "#f2b49b" for r in cat.return_rate_pct]
    a2.barh(cat.category, cat.return_rate_pct, color=colors, height=0.6)
    for y, v in enumerate(cat.return_rate_pct):
        a2.text(v + 0.4, y, f"{v:.1f}%", va="center", fontsize=9, color=INK)
    a2.set_title("Return rate (lines, mature orders)")
    a2.xaxis.set_major_formatter(PercentFormatter(decimals=0))
    a2.set_xlim(0, cat.return_rate_pct.max() * 1.18)
    a2.grid(axis="y", visible=False)
    fig.suptitle("Categories: Footwear and Dresses pair high revenue with high returns",
                 x=0.11, ha="left", fontweight="bold", fontsize=12, y=1.08)
    save(fig, "05_category_revenue_vs_returns.png")
    m["category"] = cat.set_index("category").round(2).to_dict(orient="index")

    # ------------------------------------------------------------------ 6. brand pareto
    br = q("SELECT name brand, net_revenue, contribution_pct, cumulative_contribution_pct, revenue_rank "
           "FROM mart_product_performance WHERE level = 'brand' ORDER BY revenue_rank")
    fig, ax = plt.subplots(figsize=(11, 4.6))
    x = np.arange(len(br))
    ax.bar(x, br.contribution_pct, color=BLUE, width=0.75, label="Share of revenue")
    ax.plot(x, br.cumulative_contribution_pct, color=ORANGE, lw=2, label="Cumulative share")
    ax.set_xticks(x, br.brand, rotation=75, ha="right", fontsize=7)
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_ylim(0, 105)
    ax.grid(axis="x", visible=False)
    top10 = float(br.loc[br.revenue_rank <= 10, "contribution_pct"].sum())
    ax.axvline(9.5, color=MUTED, lw=1, ls="--")
    ax.annotate(f"Top 10 of {len(br)} brands = {top10:.0f}% of revenue", (9.7, top10),
                xytext=(14, top10 - 12), fontsize=9, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED))
    ax.set_title("Brand Pareto: revenue is concentrated in a few brands")
    ax.legend(loc="center right")
    save(fig, "06_brand_pareto.png")
    m["n_brands"] = int(len(br))
    m["top10_brand_share_pct"] = round(top10, 1)
    m["top_brands"] = br.head(5)[["brand", "contribution_pct"]].to_dict(orient="records")

    # ------------------------------------------------------------------ 7. sale events
    ev = q("SELECT * FROM mart_sale_event_effectiveness ORDER BY start_date")
    sv = q("SELECT * FROM mart_sale_vs_regular_days")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"wspace": 0.3})
    y = np.arange(len(ev))
    a1.barh(y, ev.revenue_uplift_pct, color=BLUE, height=0.6)
    a1.set_yticks(y, ev.promo_code)
    for i, v in enumerate(ev.revenue_uplift_pct):
        a1.text(v + 5, i, f"+{v:.0f}%", va="center", fontsize=9)
    a1.set_xlim(0, ev.revenue_uplift_pct.max() * 1.2)
    a1.xaxis.set_major_formatter(PercentFormatter(decimals=0))
    a1.set_title("Daily revenue uplift vs 28-day baseline")
    a1.grid(axis="y", visible=False)
    a1.invert_yaxis()
    h = 0.38
    a2.barh(y - h / 2, ev.margin_pct_baseline, height=h, color=MUTED, label="Baseline")
    a2.barh(y + h / 2, ev.margin_pct_during, height=h, color=ORANGE, label="During sale")
    a2.set_yticks(y, ev.promo_code)
    a2.xaxis.set_major_formatter(PercentFormatter(decimals=0))
    a2.set_title("Gross margin %")
    a2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2)
    a2.grid(axis="y", visible=False)
    a2.invert_yaxis()
    fig.suptitle("Sale events: big revenue uplift, paid for with margin",
                 x=0.06, ha="left", fontweight="bold", fontsize=12, y=1.08)
    save(fig, "07_sale_event_uplift_vs_margin.png")
    m["sale_events"] = ev[["promo_code", "event_days", "revenue_uplift_pct", "incremental_revenue",
                           "margin_pct_during", "margin_pct_baseline", "discount_pct_during",
                           "incremental_margin", "margin_uplift_pct"]].to_dict(orient="records")
    m["sale_vs_regular"] = sv.set_index("day_type").to_dict(orient="index")

    # ------------------------------------------------------------------ 8. new vs returning
    nr = q("SELECT month_start, new_customer_revenue, returning_customer_revenue, returning_revenue_pct, "
           "returning_customer_pct, orders_per_customer FROM mart_new_vs_returning ORDER BY month_start")
    nr["month_start"] = pd.to_datetime(nr["month_start"])
    fig, ax = plt.subplots(figsize=(11, 4.4))
    ax.bar(nr.month_start, nr.returning_customer_revenue, width=22, color=BLUE, label="Returning customers")
    ax.bar(nr.month_start, nr.new_customer_revenue, width=22, bottom=nr.returning_customer_revenue,
           color=AQUA, label="New customers", edgecolor=SURFACE, linewidth=1)
    ax.yaxis.set_major_formatter(FuncFormatter(rupees))
    ax.set_title("Monthly revenue from new vs returning customers")
    subtitle(ax, "Synthetic business launches Jan 2024, so 2024 is a ramp-up year for the returning base.")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 0.97))
    ax.grid(axis="x", visible=False)
    save(fig, "08_new_vs_returning_revenue.png")
    m["returning_revenue_pct_by_month"] = {d.strftime("%Y-%m"): float(v) for d, v in
                                           zip(nr.month_start, nr.returning_revenue_pct)}

    # ------------------------------------------------------------------ headline numbers
    tot = q("""SELECT COUNT(DISTINCT order_id) orders, SUM(net_revenue) rev, SUM(net_revenue - cost_amount) gm,
                      SUM(mrp_amount - net_revenue) disc, SUM(mrp_amount) mrp, COUNT(DISTINCT customer_key) cust
               FROM fact_order_items WHERE order_status <> 'cancelled'""").iloc[0]
    m["total_net_revenue"] = float(tot.rev)
    m["total_orders"] = int(tot.orders)
    m["aov"] = round(float(tot.rev / tot.orders), 2)
    m["margin_pct"] = round(float(100 * tot.gm / tot.rev), 2)
    m["discount_pct_of_mrp"] = round(float(100 * tot.disc / tot.mrp), 2)
    m["buying_customers"] = int(tot.cust)
    m["orders_per_customer"] = round(float(tot.orders / tot.cust), 3)
    m["monthly"] = mon.assign(month_start=mon.month_start.dt.strftime("%Y-%m")).to_dict(orient="records")
    h2 = mon[mon.month_start.dt.month >= 7].groupby(mon.month_start.dt.year).net_revenue.sum()
    m["h2_revenue"] = {int(k): float(v) for k, v in h2.items()}
    m["h2_yoy_growth_pct"] = round(float(100 * (h2[2025] / h2[2024] - 1)), 1)
    fy = mon.groupby(mon.month_start.dt.year).net_revenue.sum()
    m["fy_revenue"] = {int(k): float(v) for k, v in fy.items()}
    cpn = q("SELECT * FROM mart_coupon_performance")
    m["coupons"] = cpn.set_index("coupon_code").to_dict(orient="index")
    (OUT_DIR / "metrics.json").write_text(json.dumps(m, indent=2, default=str))
    print("  metrics -> analysis/outputs/metrics.json")


if __name__ == "__main__":
    main()
