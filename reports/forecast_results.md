# Demand forecast results (measured)

Holdout: 2025-12-02 to 2025-12-31 (30 days, contains the End of Reason Sale). Metric: MAPE on daily units. Produced by `python analysis/forecast.py`.

| Category | Seasonal naive | 28-day moving avg | Regression | Regression, sale days | Seasonal naive, sale days | Regression, regular days |
|---|---:|---:|---:|---:|---:|---:|
| Footwear | 20.7% | 24.5% | **7.9%** | 7.7% | 68.5% | 7.9% |
| Ethnic Wear | 63.8% | 66.7% | **53.2%** | 82.7% | 49.0% | 45.8% |
| Topwear | 20.8% | 23.7% | **34.7%** | 30.5% | 69.2% | 35.7% |

Model: least-squares regression on log(units) with a linear trend, day-of-week dummies and a sale-day flag, trained on the 365 days before the holdout. The forward 30-day forecast (`analysis/outputs/forecast_next_30_days.csv`) assumes no sale in that window.
