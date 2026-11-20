"""
30-day demand forecast (units per day) for the top categories.

    python analysis/forecast.py

Set-up (fixed BEFORE looking at holdout results, so the comparison is honest):
  * demand     = units sold per day per category (cancelled orders excluded)
  * holdout    = the last 30 days of data; models only see days before it
  * baselines  = (a) seasonal naive: same weekday last week, i.e. repeat the
                     final 7 training days
                 (b) 28-day moving average: flat line at the last 28-day mean
  * model      = linear regression on log(units) with: trend (days),
                 day-of-week dummies and a sale-day flag. Trained on the last
                 365 training days. The sale flag is legitimate at forecast
                 time because the sale calendar is planned in advance.
  * metric     = MAPE (mean absolute percentage error) on the holdout days.
Then the model is refit on ALL data to produce the next 30 days.

Outputs: reports/forecast_results.md, analysis/outputs/forecast_*.csv,
analysis/charts/09_forecast_holdout.png
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
from make_charts import BLUE, INK_2, MUTED, ORANGE, AQUA, SALE_BAND, save, subtitle  # noqa: E402,F401
from pipeline.db import engine  # noqa: E402

HOLDOUT_DAYS, HORIZON, TRAIN_WINDOW, TOP_N = 30, 30, 365, 3


def mape(actual, pred) -> float:
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    return float(np.mean(np.abs(actual - pred) / actual) * 100)


def features(dates: pd.DatetimeIndex, sale: np.ndarray, t0: pd.Timestamp) -> np.ndarray:
    trend = (dates - t0).days.values.astype(float)
    dow = np.zeros((len(dates), 6))
    for k in range(6):                       # Monday is the reference day
        dow[:, k] = dates.dayofweek == k + 1
    return np.column_stack([np.ones(len(dates)), trend, dow, sale.astype(float)])


def fit_predict(train: pd.DataFrame, future_dates, future_sale) -> np.ndarray:
    t0 = train.index.min()
    X = features(train.index, train.is_sale_day.values, t0)
    beta, *_ = np.linalg.lstsq(X, np.log(train.units.values), rcond=None)
    return np.exp(features(future_dates, future_sale, t0) @ beta)


def main() -> None:
    e = engine()
    df = pd.read_sql("""
        SELECT d.full_date, p.category, SUM(f.quantity) AS units
        FROM fact_order_items f
        JOIN dim_product p ON p.product_key = f.product_key
        JOIN dim_date d    ON d.date_key    = f.order_date_key
        WHERE f.order_status <> 'cancelled'
        GROUP BY d.full_date, p.category""", e, parse_dates=["full_date"])
    cal = pd.read_sql("SELECT full_date, is_sale_day FROM dim_date", e, parse_dates=["full_date"]
                      ).set_index("full_date")
    top = (pd.read_sql("SELECT name FROM mart_product_performance WHERE level='category' "
                       "ORDER BY revenue_rank LIMIT %d" % TOP_N, e)["name"].tolist())

    last = df.full_date.max()
    split = last - pd.Timedelta(days=HOLDOUT_DAYS - 1)          # first holdout day
    rows, holdout_frames, future_frames = [], [], []
    for cat in top:
        s = (df[df.category == cat].set_index("full_date").units
             .reindex(pd.date_range(df.full_date.min(), last), fill_value=0).astype(float))
        data = pd.DataFrame({"units": s}).join(cal)
        train, test = data[data.index < split], data[data.index >= split]
        train_w = train.iloc[-TRAIN_WINDOW:]

        naive = np.resize(train.units.values[-7:], len(test))   # repeats last week, weekday-aligned
        ma28 = np.full(len(test), train.units.values[-28:].mean())
        reg = fit_predict(train_w, test.index, test.is_sale_day.values)
        sale = test.is_sale_day.values == 1
        res = {"category": cat}
        for name, pred in (("seasonal_naive", naive), ("moving_avg_28d", ma28), ("regression", reg)):
            res[f"{name}_mape"] = round(mape(test.units, pred), 1)
            res[f"{name}_mape_sale_days"] = round(mape(test.units[sale], pred[sale]), 1)
            res[f"{name}_mape_regular_days"] = round(mape(test.units[~sale], pred[~sale]), 1)
        rows.append(res)
        holdout_frames.append(pd.DataFrame({"date": test.index, "category": cat, "actual": test.units.values,
                                            "seasonal_naive": naive, "moving_avg_28d": ma28,
                                            "regression": reg.round(1)}))

        # next 30 days: refit on the last 365 days of ALL data
        fut = pd.date_range(last + pd.Timedelta(days=1), periods=HORIZON)
        fut_sale = np.zeros(HORIZON)        # no sale announced for this window in the calendar
        pred = fit_predict(data.iloc[-TRAIN_WINDOW:], fut, fut_sale)
        future_frames.append(pd.DataFrame({"date": fut, "category": cat, "forecast_units": pred.round(0)}))

    res = pd.DataFrame(rows)
    hold = pd.concat(holdout_frames)
    fut = pd.concat(future_frames)
    out = ROOT / "analysis" / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    hold.to_csv(out / "forecast_holdout.csv", index=False)
    fut.to_csv(out / "forecast_next_30_days.csv", index=False)
    (out / "forecast_metrics.json").write_text(json.dumps(rows, indent=2))

    # ---- chart: holdout for the top category
    cat = top[0]
    h = hold[hold.category == cat]
    s = df[(df.category == cat) & (df.full_date >= split - pd.Timedelta(days=45))]
    fig, ax = plt.subplots(figsize=(11, 4.6))
    for d in cal[(cal.index >= s.full_date.min()) & (cal.is_sale_day == 1)].index:
        ax.axvspan(d - pd.Timedelta(hours=12), d + pd.Timedelta(hours=12), color=SALE_BAND, lw=0, zorder=0)
    ax.plot(s.full_date, s.units, color=MUTED, lw=1.5, label="Actual units")
    ax.plot(h.date, h.seasonal_naive, color=ORANGE, lw=2, ls="--", label="Seasonal naive (baseline)")
    ax.plot(h.date, h.regression, color=BLUE, lw=2, label="Regression: trend + weekday + sale flag")
    ax.axvline(split, color=INK_2, lw=1)
    ax.text(split, ax.get_ylim()[1] * 0.97, "holdout starts  ", color=INK_2, fontsize=9, va="top", ha="right")
    r = res.set_index("category").loc[cat]
    ax.set_title(f"{cat}: 30-day holdout forecast of daily units")
    subtitle(ax, f"MAPE: seasonal naive {r.seasonal_naive_mape}%, 28-day avg {r.moving_avg_28d_mape}%, "
                 f"regression {r.regression_mape}%. Shaded = sale days.")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 0.92))
    ax.set_ylim(0, None)
    save(fig, "09_forecast_holdout.png")

    # ---- report
    lines = ["# Demand forecast results (measured)", "",
             f"Holdout: {split:%Y-%m-%d} to {last:%Y-%m-%d} ({HOLDOUT_DAYS} days, contains the "
             "End of Reason Sale). Metric: MAPE on daily units. Produced by `python analysis/forecast.py`.", "",
             "| Category | Seasonal naive | 28-day moving avg | Regression | Regression, sale days | "
             "Seasonal naive, sale days | Regression, regular days |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['category']} | {r['seasonal_naive_mape']}% | {r['moving_avg_28d_mape']}% | "
                     f"**{r['regression_mape']}%** | {r['regression_mape_sale_days']}% | "
                     f"{r['seasonal_naive_mape_sale_days']}% | {r['regression_mape_regular_days']}% |")
    lines += ["", "Model: least-squares regression on log(units) with a linear trend, day-of-week dummies and "
              "a sale-day flag, trained on the 365 days before the holdout. The forward 30-day forecast "
              "(`analysis/outputs/forecast_next_30_days.csv`) assumes no sale in that window."]
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "forecast_results.md").write_text("\n".join(lines) + "\n")
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
