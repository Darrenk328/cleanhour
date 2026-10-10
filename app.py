"""CleanHour: when is the PJM grid cleanest, and does it matter?  Run: streamlit run app.py"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import charts
import data
import model

ROOT = Path(__file__).resolve().parent
TZ = "America/New_York"
HOUSEHOLDS = 10_000
HERO_IMAGE = ROOT / "assets" / "princeton.jpg"
PHOTO_CREDIT = "Princeton University campus"  # replace with the photo's source

LINKS = {
    "EIA Form 930": "https://www.eia.gov/electricity/gridmonitor/",
    "Open-Meteo": "https://open-meteo.com/",
    "ERA5": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels",
    "IPCC AR5 Annex III": "https://www.ipcc.ch/site/assets/uploads/2018/02/ipcc_wg3_ar5_annex-iii.pdf",
    "PJM": "https://www.pjm.com/about-pjm/who-we-are",
    "GitHub": "https://github.com/Darrenk328/cleanhour",
}
PLOTLY_CONFIG = {"displaylogo": False, "responsive": True}

st.set_page_config(page_title="CleanHour | Princeton grid carbon forecast",
                   page_icon=str(ROOT / "static" / "leaf.png"), layout="wide")


def link(name: str, text: str | None = None) -> str:
    return f"[{text or name}]({LINKS[name]})"


# ---------------------------------------------------------------- loaders
@st.cache_resource
def artifacts():
    return model.load_artifacts()


@st.cache_data
def grid():
    return data.load_grid()


@st.cache_data(ttl=1800, show_spinner="Fetching live EIA and weather data...")
def live_forecast():
    return model.forecast_tomorrow(artifacts()[0])


@st.cache_data(ttl=1800, show_spinner=False)
def live_mix():
    return data.fetch_live_pjm(days=10)


@st.cache_data
def hero_b64() -> str | None:
    """Downscaled JPEG as base64 so the page stays light; None if the photo is missing."""
    if not HERO_IMAGE.exists():
        return None
    try:
        from PIL import Image
        im = Image.open(HERO_IMAGE).convert("RGB")
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def count_up_card(value: int, prefix: str, suffix: str, label: str, note: str, delay_ms: int = 0) -> str:
    """Self-contained HTML card whose number counts up from 0 once on load (1.2 s)."""
    return f"""
<div class="card"><div class="num" data-v="{value}" data-p="{prefix}" data-s="{suffix}">{prefix}{value:,}{suffix}</div>
<div class="label">{label}</div><div class="note">{note}</div></div>
<style>
body {{ margin: 0; font-family: "Source Sans Pro", "Source Sans 3", system-ui, -apple-system, sans-serif; }}
.card {{ background: #f3f8f5; border-radius: 12px; padding: 14px 18px; height: 152px; box-sizing: border-box; }}
.num {{ color: #1f7a4d; font-size: 2.3rem; font-weight: 700; line-height: 1.1; }}
.label {{ color: #1f2933; font-size: 0.95rem; font-weight: 600; margin-top: 4px; }}
.note {{ color: #5b6570; font-size: 0.8rem; margin-top: 2px; line-height: 1.3; }}
</style>
<script>
const el = document.querySelector(".num"), v = +el.dataset.v, p = el.dataset.p, s = el.dataset.s;
const fmt = n => p + Math.round(n).toLocaleString("en-US") + s;
if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {{
  el.textContent = fmt(0);
  setTimeout(() => {{
    const t0 = performance.now();
    const step = now => {{
      const k = Math.min(1, (now - t0) / 1200);
      el.textContent = fmt(v * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    }};
    requestAnimationFrame(step);
  }}, {delay_ms});
}}
</script>"""


def plot(fig, key: str | None = None):
    if key:  # keyed charts change with user input; animate those updates
        fig.update_layout(transition={"duration": 500, "easing": "cubic-in-out"})
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=key)
    meta = fig.layout.meta
    if isinstance(meta, dict) and meta.get("source"):
        st.caption(meta["source"])


def window_mean(values, start, length):
    return float(pd.Series(values).iloc[start:start + length].mean())


def day_from_hours(df: pd.DataFrame, date) -> pd.DataFrame:
    """Re-index a 0..23 hour frame to naive local timestamps for Plotly hover labels."""
    out = df[~df.index.duplicated()].copy()
    out.index = pd.Timestamp(date) + pd.to_timedelta(out.index.astype(int), unit="h")
    return out


def test_day_frame(date) -> pd.DataFrame:
    d = preds[preds["date_local"] == date].sort_values("ts_local")
    day = (d.set_index("hour")[["forecast", "q10", "q90", "intensity", "baseline_yesterday"]]
           .rename(columns={"intensity": "actual", "baseline_yesterday": "baseline"}))
    return day_from_hours(day, date)


def confidence_line(day: pd.DataFrame, s: int, length: int = 3) -> str:
    """High confidence if the window's upper (90%) bound sits below the day's median forecast."""
    if "q90" not in day or day["q90"].isna().all():
        return ""
    upper = window_mean(day["q90"], s, length)
    if upper < float(day["forecast"].median()):
        return ("**High confidence:** even the high end of the likely range in this window is below "
                "a typical hour.")
    return "**Close call:** several hours are similar, so the exact window matters less."


def cleanest(day: pd.DataFrame, col: str = "forecast", length: int = 3):
    s = model.cleanest_window(day[col].to_numpy(), length)
    return (s, day.index[s]) if s is not None else (None, None)


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


def yearly_tonnes(kwh: float, hours: int, runs_per_week: float) -> float:
    """Tonnes CO2/year saved by HOUSEHOLDS homes running this appliance in its cleanest window."""
    return kwh * test_period_saving(hours) * runs_per_week * 52 * HOUSEHOLDS / 1e6  # g -> tonnes


DEFAULT_APPLIANCES = pd.DataFrame([
    {"Appliance": "EV charging", "Include": True, "kWh per run": 7.0, "Hours per run": 3, "Runs per week": 7},
    {"Appliance": "Clothes dryer", "Include": True, "kWh per run": 3.0, "Hours per run": 1, "Runs per week": 3},
    {"Appliance": "Dishwasher", "Include": True, "kWh per run": 1.5, "Hours per run": 2, "Runs per week": 5},
])


# ---------------------------------------------------------------- hero
bg = hero_b64()
bg_css = f"background-image: url('data:image/jpeg;base64,{bg}');" if bg else ""
st.markdown(f"""
<style>
html {{ scroll-behavior: smooth; }}
#MainMenu, [data-testid="stToolbar"], header {{ visibility: hidden; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 2rem; }}
@keyframes chFadeUp {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes chTabIn {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes chZoom {{ from {{ transform: scale(1); }} to {{ transform: scale(1.05); }} }}
.ch-hero {{ position: relative; width: 100%; height: 300px; border-radius: 12px; overflow: hidden;
  margin-bottom: 1rem; background-color: #f3f8f5; }}
.ch-hero-photo {{ position: absolute; inset: 0; {bg_css} background-size: cover;
  background-position: center 30%; animation: chZoom 20s ease-out 1 forwards; }}
.ch-hero-veil {{ position: absolute; inset: 0; background: rgba(255,255,255,0.78); }}
.ch-hero-text {{ position: relative; height: 100%; display: flex; flex-direction: column;
  justify-content: center; padding: 0 2.25rem; }}
.ch-hero-title {{ color: #14301f; font-size: 3.4rem; font-weight: 800; line-height: 1.05; margin: 0;
  animation: chFadeUp 600ms ease-out both; }}
.ch-hero-sub {{ color: #3a4148; font-size: 1.2rem; margin: 0.6rem 0 0 0; max-width: 40rem;
  animation: chFadeUp 600ms ease-out 150ms both; }}
.ch-answer {{ font-size: 2.1rem; font-weight: 700; line-height: 1.2; margin: 0.5rem 0 0.75rem 0;
  color: #1f2933; animation: chFadeUp 500ms ease-out both; }}
.ch-answer .ch-time {{ color: #1f7a4d; }}
[role="tabpanel"] {{ animation: chTabIn 350ms ease-out both; }}
@media (max-width: 700px) {{
  .ch-hero {{ height: 200px; }}
  .ch-hero-text {{ padding: 0 1.1rem; }}
  .ch-hero-title {{ font-size: 2.3rem; }}
  .ch-hero-sub {{ font-size: 1rem; }}
  .ch-answer {{ font-size: 1.6rem; }}
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
  *, *::before, *::after {{ animation: none !important; transition: none !important; }}
}}
</style>
<div class="ch-hero" role="banner">
  <div class="ch-hero-photo"></div><div class="ch-hero-veil"></div>
  <div class="ch-hero-text">
    <div class="ch-hero-title">CleanHour</div>
    <p class="ch-hero-sub">Forecasting the cleanest hours on the grid that powers Princeton, NJ</p>
  </div>
</div>
""", unsafe_allow_html=True)

try:
    bundle, metrics, importance, preds = artifacts()
except Exception:
    st.error("Model files are missing. Run `python data.py` and then `python model.py`, "
             "then reload this page.")
    st.stop()

test_days = sorted(preds["date_local"].unique())

# ---------------------------------------------------------------- headline metrics
try:
    stats = data.daily_spread_stats(grid())
    pjm, ciso = stats.loc[data.BA_NAME["PJM"]], stats.loc[data.BA_NAME["CISO"]]
    grid_gap, timing_gain = pjm["mean"] - ciso["mean"], pjm["mean_drop"]
except Exception:
    stats = None
default_tonnes = sum(yearly_tonnes(r["kWh per run"], r["Hours per run"], r["Runs per week"])
                     for _, r in DEFAULT_APPLIANCES.iterrows())
pct = metrics["improvement_vs_yesterday_pct"]
cards = [
    (round(pct), "", "%", "More Accurate Than Yesterday's Pattern",
     "Lower error than \"same hour yesterday\", 61-day test"),
    (round(default_tonnes), "", "", f"Tonnes CO2/yr for {HOUSEHOLDS:,} Princeton Homes",
     "Scheduling the default appliances"),
]
if stats is not None and timing_gain > 0:
    cards.append((round(grid_gap / timing_gain), "~", "x", "Grid Choice vs Timing in NJ",
                  f"California: {grid_gap:.0f} g/kWh lower; best PJM hour: {timing_gain:.0f}"))
for col, (i, card) in zip(st.columns(len(cards)), enumerate(cards)):
    with col:
        components.html(count_up_card(*card, delay_ms=150 * i), height=154)

st.markdown(
    "**Why it matters.** PJM, the largest US grid, serves about 65 million people; in 2025-2026 its "
    "power was mostly gas, nuclear, and coal, averaging about 356 gCO2/kWh. Knowing the cleanest "
    f"hours a day ahead lets flexible loads avoid the dirtiest ones. Sources: {link('PJM')}, "
    f"{link('EIA Form 930')}, {link('IPCC AR5 Annex III', 'IPCC AR5')}.")

tab_tomorrow, tab_check, tab_sched, tab_where, tab_how = st.tabs(
    ["Tomorrow", "Check the AI (past days)", "Scheduler", "Where vs when", "How the AI works"])

# ---------------------------------------------------------------- Tomorrow
live_ok, live_day, live_info = False, None, {}
try:
    live_day, live_info = live_forecast()
    if live_day["forecast"].notna().sum() >= 3:
        live_ok = True
        live_day = day_from_hours(live_day, live_info["date"])
except Exception:
    live_ok = False

with tab_tomorrow:
    if live_ok:
        through = (live_info["latest_data_utc"] + pd.Timedelta(hours=1)).tz_convert(TZ)
        st.success(f"Live EIA data through {through:%b %d, %I %p} ET. "
                   f"Forecast for {live_info['date']:%A, %B %d}.")
        if live_info.get("lag_filled"):
            st.caption("EIA has not published yesterday's full data yet, so the most recent available "
                       "day stands in for \"same hour yesterday\".")
        day, title = live_day, "Tomorrow's forecast, PJM"
        base_label = ("Baseline: same hour, latest day" if live_info.get("lag_filled")
                      else "Baseline: same hour yesterday")
    else:
        st.warning("Live data is unavailable right now (no EIA_API_KEY in .env, or the EIA or weather "
                   "service did not respond). Showing the most recent test day's forecast instead.")
        day, base_label = test_day_frame(test_days[-1]).drop(columns="actual"), "Baseline: same hour yesterday"
        title = f"Forecast for {test_days[-1]:%b %d}, PJM"
    s, start_ts = cleanest(day)
    if s is None:
        st.warning("Not enough hourly data to pick a window for this day.")
    else:
        avg, best = day["forecast"].mean(), window_mean(day["forecast"], s, 3)
        st.markdown(f'<div class="ch-answer" role="heading" aria-level="2">Cleanest time to run appliances: '
                    f'<span class="ch-time">{charts.window_label(start_ts.hour)}</span></div>',
                    unsafe_allow_html=True)
        st.markdown(f"Forecast intensity in that window: **{best:.0f} gCO2/kWh**, versus a "
                    f"{avg:.0f} gCO2/kWh daily average ({100 * (avg - best) / avg:.0f}% cleaner).")
        st.markdown(confidence_line(day, s))
        plot(charts.forecast_fig(day, start_ts, title, baseline_label=base_label), key="tomorrow_chart")

    st.subheader("Play the day")
    st.markdown("Watch PJM's fuel mix hour by hour: solar rises at midday and gas fills the evening "
                "peak. Tomorrow has not happened yet, so this plays recent days with published data.")
    try:
        g = grid()
        mix = g[g["ba"] == "PJM"].dropna(subset=["intensity"])[["ts_utc", *data.FUELS]]
        try:
            mix = pd.concat([mix, live_mix()[["ts_utc", *data.FUELS]]])
        except Exception:
            pass  # bulk CSV alone is fine
        mix = mix.drop_duplicates("ts_utc", keep="last").set_index("ts_utc").sort_index()
        mix.index = mix.index.tz_convert(TZ).tz_localize(None)
        mw = mix.clip(lower=0)
        gw = pd.DataFrame({
            "Nuclear": mw["nuclear"], "Coal": mw["coal"], "Gas": mw["gas"],
            "Other": mw[["oil", "hydro", "geothermal", "other"]].sum(axis=1),
            "Wind": mw["wind"], "Solar": mw["solar"]}, index=mw.index) / 1000
        counts = gw.groupby(gw.index.date).size()
        full = sorted([d for d, n in counts.items() if n >= 23], reverse=True)[:14]
        pick = st.selectbox("Day to play", full, format_func=lambda d: f"{d:%a %b %d, %Y}")
        one = gw[gw.index.date == pick]
        plot(charts.mix_animation_fig(one, f"PJM fuel mix, {pick:%b %d}"), key="mix_chart")
    except Exception:
        st.warning("The fuel-mix animation is unavailable. Run `python data.py` to rebuild the data.")

# ---------------------------------------------------------------- Check the AI
with tab_check:
    st.markdown(f"These days ({test_days[0]:%b %d} to {test_days[-1]:%b %d, %Y}) were held out of "
                "training, so the forecast below is a fair test against what actually happened.")
    picked = st.date_input("Test day", value=test_days[-1], min_value=test_days[0],
                           max_value=test_days[-1], format="MM/DD/YYYY")
    if picked not in set(test_days):
        st.warning("No test data for that date. Pick a day between "
                   f"{test_days[0]:%b %d} and {test_days[-1]:%b %d, %Y}.")
    else:
        cday = test_day_frame(picked)
        s, start_ts = cleanest(cday)
        t, true_ts = cleanest(cday, "actual")
        err = (cday["forecast"] - cday["actual"]).abs().mean()
        base_err = (cday["baseline"] - cday["actual"]).abs().mean()
        m1, m2, m3 = st.columns(3)
        m1.metric("AI error that day", f"{err:.1f} gCO2/kWh")
        m2.metric("Baseline error", f"{base_err:.1f} gCO2/kWh",
                  help="Mean absolute error of \"same hour yesterday\" on this day.")
        if s is not None and t is not None:
            hit = "Matched" if s == t else ("Overlapped" if abs(s - t) < 3 else "Missed")
            m3.metric("Cleanest window", hit,
                      help=f"AI picked {charts.window_label(start_ts.hour)}; actual cleanest was "
                           f"{charts.window_label(true_ts.hour)}.")
        if s is not None:
            st.markdown(confidence_line(cday, s))
        inside = ((cday["actual"] >= cday["q10"]) & (cday["actual"] <= cday["q90"])).mean()
        st.caption(f"Actual values fell inside the 80% likely range in {100 * inside:.0f}% of hours that day.")
        plot(charts.forecast_fig(cday, start_ts, f"Forecast vs actual, {picked:%b %d}, PJM"), key="check_chart")

# ---------------------------------------------------------------- Scheduler
with tab_sched:
    sched_days = ([("Tomorrow (forecast)", None)] if live_ok else []) + \
                 [(f"{d:%a %b %d, %Y} (actual)", d) for d in reversed(test_days)]
    label = st.selectbox("Day to schedule", [x[0] for x in sched_days])
    sday_date = dict(sched_days)[label]
    sday = live_day if sday_date is None else test_day_frame(sday_date)
    st.markdown("Pick your appliances and edit the numbers. Each one is scheduled into its cleanest "
                "window, chosen from the AI forecast.")
    table = st.data_editor(DEFAULT_APPLIANCES, hide_index=True, num_rows="dynamic", width="stretch",
                           key="appliances")
    use_actual = "actual" in sday and sday["actual"].notna().all()
    score = sday["actual"] if use_actual else sday["forecast"]
    rows, errors, yearly_t = [], [], 0.0
    for i, r in table.iterrows():
        name = str(r.get("Appliance") or f"Row {i + 1}").strip()
        if not bool(r.get("Include")):
            continue
        try:
            kwh, hours, runs = float(r["kWh per run"]), float(r["Hours per run"]), float(r["Runs per week"])
        except (TypeError, ValueError):
            errors.append(f"{name}: a number is blank. Fill in kWh, hours, and runs per week.")
            continue
        if pd.isna(kwh) or pd.isna(hours) or pd.isna(runs):
            errors.append(f"{name}: a number is blank. Fill in kWh, hours, and runs per week.")
        elif kwh <= 0:
            errors.append(f"{name}: kWh per run must be above 0 (got {kwh:g}).")
        elif not (1 <= hours <= 12) or hours != int(hours):
            errors.append(f"{name}: hours per run must be a whole number from 1 to 12 (got {hours:g}).")
        elif runs < 0:
            errors.append(f"{name}: runs per week cannot be negative (got {runs:g}).")
        else:
            hours = int(hours)
            s = model.cleanest_window(sday["forecast"].to_numpy(), hours)
            worst = float(score.rolling(hours).mean().max())
            at = window_mean(score, s, hours)
            rows.append({
                "Appliance": name,
                "Run at": charts.window_label(sday.index[s].hour, hours),
                "kg CO2": round(kwh * at / 1000, 2),
                "Saved vs dirtiest (kg)": round(kwh * (worst - at) / 1000, 2),
                "Saved vs typical (kg)": round(kwh * (float(score.mean()) - at) / 1000, 2),
            })
            yearly_t += yearly_tonnes(kwh, hours, runs)
    if errors:
        st.error("Some rows need fixing and were skipped:\n\n" + "\n".join(f"- {e}" for e in errors))
    if rows:
        out = pd.DataFrame(rows)
        st.dataframe(out, hide_index=True, width="stretch")
        st.markdown(
            f"Scheduling saves **{out['Saved vs dirtiest (kg)'].sum():.2f} kg CO2** versus the dirtiest "
            f"time and **{out['Saved vs typical (kg)'].sum():.2f} kg** versus a typical time "
            f"(scored on {'actual' if use_actual else 'forecast'} intensity).")
        st.markdown(f"### If {HOUSEHOLDS:,} Princeton households did this: {yearly_t:,.0f} tonnes CO2/year")
        st.caption("Yearly figure: average saving versus a typical time across the 61 test days, using "
                   "the AI's picks scored against actual intensity, times runs per week, 52 weeks, and "
                   f"{HOUSEHOLDS:,} households. Average-intensity accounting; see How the AI works.")
    elif not errors:
        st.info("Tick Include on at least one appliance to see a schedule.")

# ---------------------------------------------------------------- Where vs when
with tab_where:
    if stats is None:
        st.warning("The grid comparison data is unavailable. Run `python data.py` to rebuild it.")
    else:
        plot(charts.spread_fig(stats))
        st.markdown(
            f"**Takeaway:** In PJM, picking the cleanest hour saves about {timing_gain:.0f} gCO2/kWh. "
            f"Switching to California's grid would save about {grid_gap:.0f}. "
            "For New Jersey, a cleaner grid matters more than better timing.")

# ---------------------------------------------------------------- How the AI works
with tab_how:
    st.markdown(
        "Each night the model predicts all 24 hours of the next day. It is a gradient-boosted tree "
        "ensemble (scikit-learn HistGradientBoostingRegressor) that learned from about 19 months of "
        "PJM data how the fuel mix responds to the time of day, sunlight, wind, temperature, and "
        "expected demand. It was tested on the last two months, which it never saw during training, "
        "and compared against a plain linear regression and two simple rules a person could use "
        "without any AI.")
    mrows = [{"Method": name, "Mean abs. error (gCO2/kWh)": round(m["mae_g_per_kwh"], 1),
              "Exact window hit": f"{100 * m['hit_rate_exact']:.0f}%",
              "Window overlap": f"{100 * m['hit_rate_overlap']:.0f}%",
              "Extra vs true best (gCO2/kWh)": round(m["avg_regret_g_per_kwh"], 1)}
             for name, m in metrics["models"].items()]
    st.dataframe(pd.DataFrame(mrows), hide_index=True, width="stretch")
    st.markdown(
        f"Test period {metrics['test_start']} to {metrics['test_end']} ({metrics['test_hours']:,} hours). "
        f"The model's error is **{metrics['improvement_vs_yesterday_pct']:.0f}% lower** than "
        f"\"same hour yesterday\" and **{metrics['improvement_vs_hour_avg_pct']:.0f}% lower** than the "
        "hour-of-day average. Picking the single cleanest window is harder: the model hits it exactly "
        "more often than either rule, but the overlap rate and the extra intensity paid are close to "
        "the simple rules, because PJM's hourly swing within a day is small. Gradient boosting beats "
        "linear regression because it captures non-linear effects (for example, sunlight only matters "
        "in daytime, and demand matters more in the evening); a straight-line model can only add effects "
        f"up, which shows most when picking the cleanest window "
        f"({100 * metrics['models']['Linear regression']['hit_rate_exact']:.0f}% exact hits vs "
        f"{100 * metrics['models']['AI model (gradient boosting)']['hit_rate_exact']:.0f}%).")
    st.markdown(
        f"**Uncertainty.** Two more boosted models predict the 10th and 90th percentile of each hour, "
        f"giving an \"80% likely range\". On their own they were overconfident: only "
        f"{metrics['band_raw_coverage_pct']:.0f}% of test hours fell inside. After calibrating on the last "
        f"30 training days (conformal widening by {metrics['band_pad_g_per_kwh']:.1f} gCO2/kWh), "
        f"**{metrics['band_coverage_pct']:.0f}%** of test hours fall inside the range, "
        + ("close to the 80% target." if abs(metrics["band_coverage_pct"] - 80) <= 3 else
           "under the 80% target, so treat the range as somewhat optimistic."
           if metrics["band_coverage_pct"] < 80 else "above the 80% target, so the range is cautious."))
    plot(charts.importance_fig(importance))
    st.markdown("**Limitations**")
    st.markdown(
        "- Production-based, not consumption-based: imports from neighboring grids are not counted.\n"
        "- Average, not marginal, intensity: the plant that actually responds to your extra load "
        "(usually gas) can be dirtier than the average.\n"
        "- Backtests use actual weather as a stand-in for weather forecasts, so they are somewhat "
        "optimistic.\n"
        "- Live mode uses EIA data that lags about a day, so tomorrow's forecast is less certain than "
        "the backtest.\n"
        "- Emission factors are IPCC lifecycle medians; \"other\" and unknown fuels are assumed gas-like.")

# ---------------------------------------------------------------- footer
st.divider()
st.caption(
    f"Data: {link('EIA Form 930')} hourly generation and demand forecasts; weather from "
    f"{link('Open-Meteo')} ({link('ERA5')} reanalysis); emission factors from "
    f"{link('IPCC AR5 Annex III')}; grid context from {link('PJM')}.  \n"
    + (f"Photo: {PHOTO_CREDIT}. " if bg else "")
    + f"Code: {link('GitHub', 'github.com/Darrenk328/cleanhour')}.  \n"
    + "© 2026 CleanHour, hackPHS")
