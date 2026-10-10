"""CleanHour: when is the PJM grid cleanest, and does it matter?  Run: streamlit run app.py"""
from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import charts
import data
import model

st.set_page_config(page_title="CleanHour", layout="wide")
TOMORROW = "Tomorrow (live forecast)"


# ---------------------------------------------------------------- loaders
@st.cache_resource
def artifacts():
    return model.load_artifacts()


@st.cache_data
def grid():
    return data.load_grid()


@st.cache_data(ttl=1800, show_spinner="Fetching live EIA and weather data...")
def live_forecast():
    bundle = artifacts()[0]
    return model.forecast_tomorrow(bundle)


def show(fig):
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


# ---------------------------------------------------------------- header
st.title("CleanHour")
st.caption("Forecasting hourly carbon intensity on the PJM grid, the grid that serves Princeton, NJ.")

st.subheader("Why it matters")
st.markdown(
    "PJM runs the largest power grid in the US, serving about 65 million people in 13 states and "
    "Washington, DC. In 2025-2026 its power came mostly from natural gas (42%), nuclear (31%), and "
    "coal (17%), so a kilowatt-hour drawn in Princeton averaged about 356 gCO2. Some hours are "
    "cleaner than others, and an AI forecast can tell you which ones before the day starts.  \n"
    "<small>Sources: PJM Interconnection (pjm.com, service territory); EIA Form 930 hourly "
    "generation by fuel; IPCC AR5 lifecycle emission factors.</small>",
    unsafe_allow_html=True,
)

try:
    bundle, metrics, importance, preds = artifacts()
except Exception:
    st.error("Model files are missing. Run `python data.py` and then `python model.py`, "
             "then reload this page.")
    st.stop()


# ---------------------------------------------------------------- day picker
test_days = sorted(preds["date_local"].unique(), reverse=True)
options = [TOMORROW] + [d.strftime("%a %b %d, %Y") for d in test_days]
choice = st.selectbox("Pick a day", options, index=0,
                      help="Tomorrow uses live EIA data and the Open-Meteo weather forecast. "
                           "Past days come from the held-out test period, so you can compare the "
                           "forecast with what actually happened.")

day, info = None, {}
is_live = choice == TOMORROW
if is_live:
    try:
        day, info = live_forecast()
        if day["forecast"].isna().all():
            raise ValueError("empty forecast")
        st.caption(
            f"Forecast for {info['date']:%A, %B %d}. Latest EIA data: "
            f"{info['latest_data_utc'].tz_convert('America/New_York'):%b %d, %I %p} ET."
            + (" Yesterday's values are not published yet, so the most recent available day "
               "stands in for them." if info["lag_filled"] else ""))
    except Exception:
        st.warning("The live forecast is unavailable right now (no EIA_API_KEY in .env, or the EIA "
                   "or weather service did not respond). Showing the most recent test day instead.")
        is_live = False
        choice = options[1]

if day is None:
    date = test_days[options.index(choice) - 1]
    d = preds[preds["date_local"] == date].sort_values("ts_local")
    day = (d.set_index("hour")[["forecast", "intensity", "baseline_yesterday"]]
           .rename(columns={"intensity": "actual", "baseline_yesterday": "baseline"}))
    day = day[~day.index.duplicated()]  # DST fall-back repeats an hour

if len(day) < model.WINDOW or day["forecast"].isna().all():
    st.warning("Not enough hourly data for this day. Please pick another day.")
    st.stop()

start = model.cleanest_window(day["forecast"].to_numpy())
start_hour = int(day.index[start]) if start is not None else None
label = charts.window_label(start_hour) if start_hour is not None else "not available"
st.markdown(f"## Cleanest time to run appliances: {label}")
avg, best = day["forecast"].mean(), day["forecast"].iloc[start:start + 3].mean()
st.markdown(f"Forecast intensity in that window: **{best:.0f} gCO2/kWh**, versus a "
            f"{day['forecast'].mean():.0f} gCO2/kWh daily average ({100 * (avg - best) / avg:.0f}% cleaner).")

title = ("Tomorrow's forecast" if is_live else f"Forecast vs actual, {choice}") + ", PJM"
base_label = ("Baseline: same hour, latest available day" if is_live and info.get("lag_filled")
              else "Baseline: same hour yesterday")
show(charts.forecast_chart(day, start_hour, title, baseline_label=base_label))
if not is_live and "actual" in day:
    true = model.cleanest_window(day["actual"].to_numpy())
    if true is not None:
        hit = "matched" if true == start else ("overlapped" if abs(true - start) < 3 else "missed")
        st.caption(f"Actual cleanest window that day: {charts.window_label(int(day.index[true]))}. "
                   f"The forecast {hit} it.")


# ---------------------------------------------------------------- scheduler
HOUSEHOLDS = 10_000
DEFAULT_APPLIANCES = pd.DataFrame([
    {"Appliance": "EV charging", "Include": True, "kWh per run": 7.0, "Hours per run": 3, "Runs per week": 7},
    {"Appliance": "Clothes dryer", "Include": True, "kWh per run": 3.0, "Hours per run": 1, "Runs per week": 3},
    {"Appliance": "Dishwasher", "Include": True, "kWh per run": 1.5, "Hours per run": 2, "Runs per week": 5},
])


def window_mean(values, start, length):
    return float(pd.Series(values).iloc[start:start + length].mean())


@st.cache_data
def test_period_saving(hours: int) -> float:
    """Average gCO2/kWh saved on test days by running in the model's cleanest `hours`
    window instead of at a typical (day-average) time, measured on actual intensity."""
    saved = []
    for _, d in preds.groupby("date_local"):
        if len(d) < 23:
            continue
        d = d.sort_values("ts_local")
        s = model.cleanest_window(d["forecast"].to_numpy(), hours)
        if s is not None:
            saved.append(d["intensity"].mean() - window_mean(d["intensity"].to_numpy(), s, hours))
    return float(sum(saved) / len(saved)) if saved else 0.0


st.divider()
st.subheader("Appliance scheduler")
st.markdown("Pick your appliances and edit the numbers. Each one is scheduled into its cleanest "
            "window on the chosen day.")
try:
    table = st.data_editor(
        DEFAULT_APPLIANCES, hide_index=True, num_rows="dynamic", width="stretch",
        column_config={
            "kWh per run": st.column_config.NumberColumn(min_value=0.0, max_value=200.0, step=0.5),
            "Hours per run": st.column_config.NumberColumn(min_value=1, max_value=12, step=1),
            "Runs per week": st.column_config.NumberColumn(min_value=0, max_value=21, step=1),
        })
    # Score with actual intensity when we have it (past days), otherwise the forecast.
    use_actual = not is_live and "actual" in day and day["actual"].notna().all()
    score = day["actual"] if use_actual else day["forecast"]
    rows, skipped, yearly_t = [], [], 0.0
    for _, r in table.iterrows():
        try:
            name = str(r["Appliance"]).strip() or "Appliance"
            kwh, hours, runs = float(r["kWh per run"]), int(r["Hours per run"]), float(r["Runs per week"])
        except (TypeError, ValueError):
            skipped.append(str(r.get("Appliance", "a row")))
            continue
        if not bool(r["Include"]):
            continue
        if not (kwh > 0 and 1 <= hours <= min(12, len(day)) and runs >= 0):
            skipped.append(name)
            continue
        s = model.cleanest_window(day["forecast"].to_numpy(), hours)
        sums = score.rolling(hours).mean().dropna()
        worst = float(sums.max())
        typical = float(score.mean())
        at = window_mean(score.to_numpy(), s, hours)
        rows.append({
            "Appliance": name,
            "Run at": charts.window_label(int(day.index[s]), hours),
            "kg CO2 at that time": round(kwh * at / 1000, 2),
            "Saved vs dirtiest time (kg)": round(kwh * (worst - at) / 1000, 2),
            "Saved vs typical time (kg)": round(kwh * (typical - at) / 1000, 2),
        })
        yearly_t += kwh * test_period_saving(hours) * runs * 52 * HOUSEHOLDS / 1e6  # g -> tonnes
    if skipped:
        st.warning("Skipped rows with missing or out-of-range numbers: " + ", ".join(skipped)
                   + ". Use kWh above 0 and 1 to 12 hours.")
    if rows:
        out = pd.DataFrame(rows)
        st.dataframe(out, hide_index=True, width="stretch")
        basis = "actual" if use_actual else "forecast"
        st.markdown(
            f"On this day, scheduling saves **{out['Saved vs dirtiest time (kg)'].sum():.2f} kg CO2** "
            f"versus the dirtiest time and **{out['Saved vs typical time (kg)'].sum():.2f} kg** versus a "
            f"typical time (scored on {basis} intensity).")
        st.markdown(f"### If {HOUSEHOLDS:,} Princeton households did this: {yearly_t:,.0f} tonnes CO2/year")
        st.caption("Yearly figure: average saving versus a typical time across the 61 test days, using "
                   "the model's picks scored against actual intensity, times runs per week, 52 weeks, "
                   f"and {HOUSEHOLDS:,} households. Average-intensity accounting; see Limitations.")
    else:
        st.info("Select at least one appliance to see a schedule.")
except Exception:
    st.warning("The scheduler could not run with these inputs. Try resetting the table by reloading the page.")


# ---------------------------------------------------------------- where vs when
st.divider()
st.subheader("Where vs when")
try:
    stats = data.daily_spread_stats(grid())
    pjm = stats.loc[data.BA_NAME["PJM"]]
    ciso = stats.loc[data.BA_NAME["CISO"]]
    erco = stats.loc[data.BA_NAME["ERCO"]]
    show(charts.spread_chart(stats))
    st.markdown(
        f"**Takeaway:** in PJM, picking the cleanest hour beats a typical hour by only "
        f"{pjm['mean_drop']:.0f} gCO2/kWh on an average day, while California's grid averages "
        f"{pjm['mean'] - ciso['mean']:.0f} lower and even Texas's averages {pjm['mean'] - erco['mean']:.0f} "
        "lower. For New Jersey, which grid you are on matters more than when you plug in.")
except Exception:
    st.warning("The grid comparison data is unavailable. Run `python data.py` to rebuild it.")


# ---------------------------------------------------------------- how the AI works
st.divider()
st.subheader("How the AI works")
st.markdown(
    "Each night the model predicts all 24 hours of the next day. It is a gradient-boosted tree "
    "ensemble (scikit-learn HistGradientBoostingRegressor) that learned from about 19 months of "
    "PJM data how the fuel mix responds to the time of day, sunlight, wind, temperature, and "
    "expected demand. It was tested on the last two months, which it never saw during training, "
    "and compared against two simple rules a person could use without any AI."
)
rows = []
for name, m in metrics["models"].items():
    rows.append({"Method": name, "Mean abs. error (gCO2/kWh)": round(m["mae_g_per_kwh"], 1),
                 "Cleanest window exact hit": f"{100 * m['hit_rate_exact']:.0f}%",
                 "Window overlap hit": f"{100 * m['hit_rate_overlap']:.0f}%",
                 "Extra intensity vs true best (gCO2/kWh)": round(m["avg_regret_g_per_kwh"], 1)})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
st.markdown(
    f"Test period {metrics['test_start']} to {metrics['test_end']} ({metrics['test_hours']:,} hours). "
    f"The model's error is **{metrics['improvement_vs_yesterday_pct']:.0f}% lower** than "
    f"\"same hour yesterday\" and **{metrics['improvement_vs_hour_avg_pct']:.0f}% lower** than the "
    "hour-of-day average. Picking the single cleanest window is harder: the model hits it exactly "
    "more often than either rule, but the overlap rate and the extra intensity paid are close to "
    "the simple rules, because PJM's hourly swing within a day is small."
)
show(charts.importance_chart(importance))

st.markdown("**Limitations**")
st.markdown(
    "- Production-based, not consumption-based: imports from neighboring grids are not counted.\n"
    "- Average, not marginal, intensity: the plant that actually responds to your extra load "
    "(usually gas) can be dirtier than the average.\n"
    "- Backtests use actual weather as a stand-in for weather forecasts, so they are somewhat "
    "optimistic. The live Tomorrow mode uses a real forecast and EIA data that can lag a day.\n"
    "- Emission factors are IPCC lifecycle medians; \"other\" and unknown fuels are assumed gas-like."
)
