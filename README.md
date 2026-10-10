# CleanHour

CleanHour forecasts hourly grid carbon intensity (gCO2/kWh) for PJM, the grid that
serves Princeton, NJ. It recommends the cleanest 3-hour window to run appliances, says
how confident it is, and shows that for New Jersey, which grid you are on matters more
than when you plug in.

![Forecast vs actual](figures/forecast_example.png)

## What it does

The Streamlit app sits on a forest background with cream content panels. Five tabs sit under a header with three live headline numbers, and short "CleanHour AI" messages explain each result in plain language (written from the model's outputs):

- **Tomorrow.** A day-ahead forecast from the latest EIA data (API v2) and the Open-Meteo
  weather forecast, with an "80% likely range" band, the cleanest 3-hour window, and a
  plain-language confidence line. "Play the day" animates PJM's fuel mix hour by hour
  (solar rising at midday, gas filling the evening peak).
- **Check the AI (past days).** Pick any day in the held-out test period to compare the
  forecast, its likely range, and the "same hour yesterday" baseline with what actually
  happened, plus that day's error.
- **Scheduler.** Pick appliances (EV 7 kWh, dryer 3 kWh, dishwasher 1.5 kWh, all
  editable). Each is scheduled into its cleanest window, with kg CO2 saved versus the
  dirtiest and typical times, and a scale-up to 10,000 Princeton households per year.
- **Where vs when.** Average daily swing in PJM compared with California (CISO) and
  Texas (ERCOT).
- **How the AI works.** Metrics against all baselines, uncertainty calibration,
  permutation feature importance, and limitations.

## Why it matters

New Jersey has warmed about 4°F since 1900, roughly twice the global average, according to
the [Office of the New Jersey State Climatologist at Rutgers](https://climate.rutgers.edu/stateclim/).
Electricity is about 31% of U.S. energy-related CO2 emissions
([EIA](https://www.eia.gov/tools/faqs/faq.php?id=77)).
PJM, the largest US grid operator, serves about 65 million people; in 2025-2026 its
generation was about 42% natural gas, 31% nuclear, and 17% coal, averaging about
356 gCO2/kWh. Shifting flexible loads to cleaner hours is free, but in PJM the gain is
modest: the cleanest hour is only about 24 gCO2/kWh below a typical hour on an average
day, while California's grid averages 139 gCO2/kWh lower than PJM.

![Where vs when](figures/where_vs_when.png)

## How to run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

The cleaned data (`data/*.csv`) and trained models (`models/`) are committed, so the app
works offline. To rebuild from scratch (downloads ~170 MB of EIA CSVs):

```bash
.venv/bin/python data.py
.venv/bin/python model.py
```

Optional live mode: put a free EIA API key in `.env` as `EIA_API_KEY=...`
(get one at https://www.eia.gov/opendata/). Without it the app still runs, and the
Tomorrow tab shows the most recent test day with a notice.

## Code layout

| File | Role |
|---|---|
| `data.py` | Downloads and cleans EIA-930 data and Open-Meteo weather, computes intensity, live API fetches. Never draws. |
| `features.py` | Day-ahead feature frame (only information available at midnight before the day). |
| `model.py` | Training, quantile band and calibration, linear baseline, metrics, importance, live forecast. |
| `charts.py` | Animated ECharts charts and Plotly figures for the app, matplotlib figures for this README. Never fetches data. |
| `app.py` | Streamlit app. |

## Model and metrics

- **Target:** hourly PJM intensity for each of the 24 hours of the next day.
- **Features:** hour, day of week, month, intensity 24h and 168h earlier, yesterday's
  mean, last observed hour before midnight, temperature, solar radiation, 100 m wind
  speed, cloud cover (average of Princeton NJ, Columbus OH, Richmond VA), and EIA's
  day-ahead demand forecast.
- **Model:** scikit-learn `HistGradientBoostingRegressor` (absolute-error loss).
- **Split:** by time. Train 2025-01-08 to 2026-08-09; test 2026-08-10 to 2026-10-09
  (61 days, 1,464 hours). No random split.

| Method | MAE (gCO2/kWh) | Cleanest window exact hit | Window overlap | Extra vs true best (gCO2/kWh) |
|---|---|---|---|---|
| Gradient boosting (CleanHour) | **8.7** | **31%** | 70% | **3.5** |
| Linear regression | 9.0 | 15% | 75% | 5.0 |
| Same hour yesterday | 14.3 | 26% | 72% | 3.6 |
| Hour-of-day average | 24.7 | 11% | 80% | 5.1 |

Boosting's error is **39% lower** than "same hour yesterday" and **65% lower** than the
hour-of-day average. Linear regression comes close on average error but picks the
cleanest window far less often, because effects like sunlight only matter in daytime and
a straight-line model can only add effects up. Picking the single best window is hard for
every method: the overlap rate and extra intensity paid are close to persistence, and the
hour-of-day average, which always picks the same midday block, overlaps most often but
pays the most extra.

**Uncertainty band.** Two more boosted models (quantile loss, 10th and 90th percentile)
give an "80% likely range". Uncalibrated, they covered only **52%** of test hours. After
split-conformal calibration on the last 30 training days (widening both sides by
4.8 gCO2/kWh), the band covers **75%** of test hours: close to, but still under, the
80% target.

![Feature importance](figures/importance.png)

## Limitations

- **Production-based, not consumption-based.** Imports from neighboring grids are not counted.
- **Average, not marginal, intensity.** The plant that responds to extra load (usually gas)
  can be dirtier than the average, so real savings from load shifting may differ.
- **Actual weather stands in for forecasts in the backtest,** so test metrics are somewhat
  optimistic.
- **Live mode uses EIA data that lags about a day,** so tomorrow's forecast is less certain
  than the backtest; the "yesterday" features fall back to the latest available day.
- **The likely range is slightly overconfident** (75% coverage for a nominal 80%).
- **Emission factors are lifecycle medians.** "Other" and unknown fuels are assumed
  gas-like (490 gCO2/kWh); storage is excluded. Geothermal (CISO only) uses 38.
- The yearly scale-up assumes the stated runs per week and the test-period average saving.

See `NOTES.md` for every judgment call made during the build.

## Data credits

- **U.S. Energy Information Administration, [Form EIA-930](https://www.eia.gov/electricity/gridmonitor/)**
  (Hourly Electric Grid Monitor): six-month balance files and API v2 hourly fuel mix and
  demand forecast.
- **[Open-Meteo](https://open-meteo.com/):** historical weather from the
  [ERA5 reanalysis](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
  (Copernicus/ECMWF) and the forecast API.
- **[IPCC AR5 (2014), Annex III](https://www.ipcc.ch/site/assets/uploads/2018/02/ipcc_wg3_ar5_annex-iii.pdf):**
  lifecycle emission factors (gCO2eq/kWh): coal 820, gas 490, oil 720, nuclear 12,
  hydro 24, solar 48, wind 11, geothermal 38.
- **[PJM Interconnection](https://www.pjm.com/about-pjm/who-we-are):** service territory context.
- **Background photo:** [Sebastian Unrau](https://unsplash.com/photos/trees-on-forest-with-sun-rays-sp-p7uuT0tw) on Unsplash (Unsplash License).
- **Charts:** Apache ECharts 5.5.1 and Plotly; fonts Fraunces and Nunito Sans (Google Fonts).

© 2026 CleanHour, hackPHS
