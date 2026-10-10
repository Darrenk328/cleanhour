"""CleanHour: when is the PJM grid cleanest, and does it matter?  Run: streamlit run app.py"""
from __future__ import annotations

import base64
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
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
BG_IMAGE = ROOT / "assets" / "nature.jpg"
BG_CREDIT = ("Waldemar Brandt", "https://unsplash.com/photos/white-wind-turbines-on-green-grass-field-under-blue-and-white-cloudy-sky-during-daytime-8NBACfGMFtw")
HERO_IMAGE = ROOT / "assets" / "princeton.jpg"
HERO_CREDIT = "Blair Hall, Princeton University"  # source not yet known
FONTS_CSS = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700"
             "&family=Nunito+Sans:wght@400;600;700&display=swap")

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


LIVE_TTL_S, LIVE_WAIT_S = 1800, 6


@st.cache_resource
def _live_jobs() -> dict:
    """Shared state for background live fetches: name -> {t, result, future}."""
    return {"pool": ThreadPoolExecutor(max_workers=2)}


def _live(name: str, fn):
    """Run a slow network call in a background thread so the page never blocks on it.
    Waits up to LIVE_WAIT_S; if it is still running, raises and the caller falls back,
    and a later rerun picks up the finished result. Results are reused for LIVE_TTL_S."""
    jobs = _live_jobs()
    job = jobs.setdefault(name, {"t": 0.0, "result": None, "future": None})
    if job["result"] is not None and time.time() - job["t"] < LIVE_TTL_S:
        return job["result"]
    if job["future"] is None:
        job["future"] = jobs["pool"].submit(fn)
    try:
        result = job["future"].result(timeout=LIVE_WAIT_S)
    except FutureTimeout:
        raise RuntimeError("live data is still loading") from None
    except Exception:
        job["future"] = None
        raise
    job.update(t=time.time(), result=result, future=None)
    return result


def live_forecast():
    bundle = artifacts()[0]
    return _live("forecast", lambda: model.forecast_tomorrow(bundle))


def live_mix():
    return _live("mix", lambda: data.fetch_live_pjm(days=10))


@st.cache_data
def bg_b64() -> str | None:
    """Background photo as base64 (embedded so no static file server is needed)."""
    try:
        return base64.b64encode(BG_IMAGE.read_bytes()).decode()
    except OSError:
        return None


@st.cache_data
def hero_b64() -> str | None:
    """Princeton header photo as base64; None if the file is missing."""
    try:
        return base64.b64encode(HERO_IMAGE.read_bytes()).decode()
    except OSError:
        return None


PARALLAX_JS = """
<script>
// Parallax: the page content scrolls normally; the background moves at 30% speed.
(() => {
  const P = window.parent, doc = P.document;
  if (P.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const bg = doc.querySelector(".ch-bg"), sc = doc.querySelector('[data-testid="stMain"]');
  if (!bg || !sc) return;  // CSS fallback: background stays fixed while content scrolls
  if (P.__chParallaxOff) P.__chParallaxOff();
  const size = () => {
    const extra = Math.max(0, sc.scrollHeight - sc.clientHeight) * 0.3;
    bg.style.height = (P.innerHeight + extra) + "px";
  };
  let queued = false;
  const onScroll = () => {
    if (queued) return;
    queued = true;
    P.requestAnimationFrame(() => {
      bg.style.transform = "translate3d(0," + (-sc.scrollTop * 0.3) + "px,0)";
      queued = false;
    });
  };
  const ro = new P.ResizeObserver(size);
  ro.observe(sc.firstElementChild || sc);
  sc.addEventListener("scroll", onScroll, {passive: true});
  P.addEventListener("resize", size);
  P.__chParallaxOff = () => { ro.disconnect(); sc.removeEventListener("scroll", onScroll); P.removeEventListener("resize", size); };
  size(); onScroll();
})();
</script>
"""


def stat_strip(stats: list[tuple]) -> str:
    """Three figures in a row on the hero photo, separated by thin rules. Each counts up from 0
    once on load (1.2 s, staggered 150 ms). stats: (value, prefix, suffix, label, note)."""
    cells = "".join(
        f'<div class="cell{" lead" if i == 0 else ""}"><div class="num" data-v="{v}" data-p="{p}" data-s="{x}">'
        f'{p}{v:,}{x}</div><div class="label">{label}</div><div class="note">{note}</div></div>'
        for i, (v, p, x, label, note) in enumerate(stats))
    return f"""
<div class="strip">{cells}</div>
<style>
@import url("{FONTS_CSS}");
body {{ margin: 0; font-family: "Nunito Sans", "Segoe UI", system-ui, sans-serif; color: #fbf8f1; }}
.strip {{ display: flex; align-items: flex-start; }}
.cell {{ flex: 1 1 0; padding: 4px 18px; border-left: 1px solid rgba(251, 248, 241, 0.35); min-width: 0;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.5), 0 2px 14px rgba(0, 0, 0, 0.45); }}
.cell:first-child {{ padding-left: 0.5rem; border-left: 0; flex-grow: 1.3; }}
.num {{ font-family: Fraunces, Georgia, serif; font-weight: 700; font-size: 2.1rem; line-height: 1.05; }}
.lead .num {{ font-size: 3.2rem; }}
.label {{ font-size: 0.92rem; font-weight: 700; margin-top: 4px; }}
.note {{ font-size: 0.78rem; opacity: 0.85; margin-top: 2px; line-height: 1.3; }}
@media (max-width: 520px) {{
  .cell {{ padding: 2px 8px; }}
  .num {{ font-size: 1.45rem; }}
  .lead .num {{ font-size: 2.1rem; }}
  .label {{ font-size: 0.74rem; }}
  .note {{ display: none; }}
}}
</style>
<script>
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
document.querySelectorAll(".num").forEach((el, i) => {{
  const v = +el.dataset.v, p = el.dataset.p, s = el.dataset.s;
  const fmt = n => p + Math.round(n).toLocaleString("en-US") + s;
  if (reduce) return;
  el.textContent = fmt(0);
  setTimeout(() => {{
    const t0 = performance.now();
    const step = now => {{
      const k = Math.min(1, (now - t0) / 1200);
      el.textContent = fmt(v * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    }};
    requestAnimationFrame(step);
  }}, 150 * i);
}});
</script>"""


WORD_S, MAX_TYPE_S = 0.025, 1.5


def word_stream(text: str):
    """Yield the message a few words at a time: ~25 ms per word, capped near 1.5 s."""
    words = text.split(" ")
    per = max(1, -(-int(len(words) * WORD_S * 1000) // int(MAX_TYPE_S * 1000)))
    for i in range(0, len(words), per):
        yield " ".join(words[i:i + per]) + " "
        time.sleep(WORD_S * per)


def ai_bubble(bubble_id: str, text: str, header_html: str = "") -> None:
    """A CleanHour AI message, written from the model's outputs. Types itself once per
    session (only the Tomorrow bubble on first load, to keep the page fast); otherwise instant."""
    typed = st.session_state.setdefault("typed_bubbles", set())
    animate = bubble_id not in typed and bubble_id in TYPE_ON_FIRST_LOAD and FIRST_LOAD
    typed.add(bubble_id)
    with st.container(key=f"bubble_{bubble_id}"):
        st.markdown(f'<div class="ch-ai-label">CleanHour AI</div>{header_html}',
                    unsafe_allow_html=True)
        if animate:
            dots = st.empty()
            dots.markdown('<div class="ch-typing" aria-label="typing"><i></i><i></i><i></i></div>',
                          unsafe_allow_html=True)
            time.sleep(0.4)
            dots.empty()
            st.write_stream(word_stream(text))
        else:
            st.markdown(text)


def echart(build, fallback, source: str) -> None:
    """Animated ECharts chart in an iframe; falls back to the Plotly figure if building fails."""
    try:
        html, height = build()
    except Exception:
        plot(fallback())
        return
    components.html(html, height=height)
    st.caption(source)


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


# ---------------------------------------------------------------- page style + hero
bg = bg_b64()
bg_css = f"background-image: url('data:image/jpeg;base64,{bg}');" if bg else "background: #1f4d33;"
hero = hero_b64()
hero_css = f"background-image: url('data:image/jpeg;base64,{hero}');" if hero else ""
st.markdown(f"""
<style>
@import url("{FONTS_CSS}");
html {{ scroll-behavior: smooth; }}
#MainMenu, [data-testid="stToolbar"], header {{ visibility: hidden; }}
/* Nature background (fixed, moved at 30% scroll speed by the parallax script). */
[data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"], header {{ background: transparent; }}
.ch-bg {{ position: fixed; top: 0; left: 0; right: 0; height: 100vh; z-index: -1; {bg_css}
  background-size: cover; background-position: center 40%; filter: saturate(0.95); will-change: transform;
  pointer-events: none; }}
.ch-bg::after {{ content: ""; position: absolute; inset: 0; background: rgba(14, 30, 42, 0.34); }}
[data-testid="stMainBlockContainer"] {{ position: relative; z-index: 1; padding-top: 1.5rem; }}
/* Cream panels with a soft shadow; the photo shows in the gaps. */
[class*="st-key-panel"] {{ background: rgba(251, 248, 241, 0.95); border-radius: 4px;
  border: 1px solid rgba(29, 42, 34, 0.12); padding: 1.5rem 1.75rem; }}
/* No hover animations anywhere. */
button, a, [role="tab"], [data-baseweb="tab"], [data-baseweb="tab-highlight"] {{ transition: none !important; }}
/* Skeleton placeholder while data loads. */
.ch-skel {{ background: #ebe5d6; border-radius: 4px; animation: chSkel 1.2s ease-in-out infinite alternate; }}
@keyframes chSkel {{ from {{ opacity: 1; }} to {{ opacity: 0.45; }} }}
/* Fonts. */
html, body, [data-testid="stApp"], .stMarkdown, p, li, label, input, textarea, button,
[data-baseweb="tab"], [data-testid="stCaptionContainer"] {{ font-family: "Nunito Sans", "Segoe UI", system-ui, sans-serif; }}
h1, h2, h3, h4, .ch-hero-title, .ch-answer {{ font-family: Fraunces, Georgia, serif !important; font-style: normal; }}
a {{ color: #1f4d33; }}
@keyframes chFadeUp {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes chTabIn {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}
/* Princeton banner: photo under a white veil (low opacity), text on top. */
@keyframes chZoom {{ from {{ transform: scale(1); }} to {{ transform: scale(1.05); }} }}
.ch-hero {{ position: relative; width: 100%; height: 300px; border-radius: 4px; overflow: hidden;
  border: 1px solid rgba(29, 42, 34, 0.12); background-color: #f3f8f5; margin-top: 0.5rem; }}
.ch-hero-photo {{ position: absolute; inset: 0; {hero_css} background-size: cover;
  background-position: center 45%; animation: chZoom 20s ease-out 1 forwards; }}
.ch-hero-veil {{ position: absolute; inset: 0; background: rgba(255, 255, 255, 0.78); }}
.ch-hero-text {{ position: relative; height: 100%; display: flex; flex-direction: column;
  justify-content: center; padding: 0 2.25rem; }}
.ch-hero-title {{ color: #14301f; font-size: 3.4rem; font-weight: 700; line-height: 1.05; margin: 0;
  animation: chFadeUp 600ms ease-out both; }}
.ch-hero-sub {{ color: #3a4148; font-size: 1.2rem; margin: 0.6rem 0 0 0; max-width: 40rem;
  animation: chFadeUp 600ms ease-out 150ms both; }}
.ch-answer {{ font-size: 2.1rem; font-weight: 700; line-height: 1.2; margin: 0.5rem 0 0.75rem 0;
  color: #1d2a22; animation: chFadeUp 500ms ease-out both; }}
.ch-answer .ch-time {{ color: #3f8f5a; }}
[role="tabpanel"] {{ animation: chTabIn 350ms ease-out both; }}
[class*="st-key-bubble"] {{ background: #f3eddf; border-radius: 4px; padding: 0.85rem 1.15rem 0.4rem;
  max-width: 48rem; border: 1px solid rgba(29, 42, 34, 0.12); gap: 0.25rem; margin: 0.25rem 0 0.75rem; }}
.ch-ai-label {{ color: #1f4d33; font-size: 0.85rem; font-variant: small-caps;
  font-weight: 700; letter-spacing: 0.03em; line-height: 1.4; margin-bottom: 0.4rem; }}
[class*="st-key-bubble"] .stMarkdown {{ margin-bottom: 0; }}
[class*="st-key-bubble"] [data-testid="stMarkdownContainer"] {{ overflow: visible; }}
.ch-typing {{ display: flex; gap: 5px; padding: 6px 0 4px; }}
.ch-typing i {{ width: 7px; height: 7px; border-radius: 50%; background: #5a7d4f; opacity: 0.25;
  animation: chDot 400ms ease-out both; }}
.ch-typing i:nth-child(2) {{ animation-delay: 120ms; }}
.ch-typing i:nth-child(3) {{ animation-delay: 240ms; }}
@keyframes chDot {{ to {{ opacity: 1; }} }}
@media (max-width: 700px) {{
  .ch-hero {{ height: 200px; }}
  .ch-hero-text {{ padding: 0 1.1rem; }}
  .ch-hero-title {{ font-size: 2.3rem; }}
  .ch-hero-sub {{ font-size: 1rem; }}
  .ch-answer {{ font-size: 1.6rem; }}
  [class*="st-key-panel"] {{ padding: 1.1rem 1rem; }}
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
  *, *::before, *::after {{ animation: none !important; transition: none !important; }}
}}
</style>
<div class="ch-bg" aria-hidden="true"></div>
<div class="ch-hero" role="banner">
  <div class="ch-hero-photo"></div><div class="ch-hero-veil"></div>
  <div class="ch-hero-text">
    <div class="ch-hero-title">CleanHour</div>
    <p class="ch-hero-sub">Forecasting the cleanest hours on the grid that powers Princeton, NJ</p>
  </div>
</div>
""", unsafe_allow_html=True)
components.html(PARALLAX_JS, height=0)

try:
    bundle, metrics, importance, preds = artifacts()
except Exception:
    st.error("Model files are missing. Run `python data.py` and then `python model.py`, "
             "then reload this page.")
    st.stop()

test_days = sorted(preds["date_local"].unique())
FIRST_LOAD = "typed_bubbles" not in st.session_state
# Typing all five bubbles would add ~8 s on first load; only the Tomorrow answer types.
TYPE_ON_FIRST_LOAD = {"tomorrow"}

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
    (round(pct), "", "%", "More accurate than yesterday's pattern",
     "Lower error than \"same hour yesterday\", 61-day test"),
    (round(default_tonnes), "", "", f"Tonnes CO2/yr for {HOUSEHOLDS:,} Princeton homes",
     "Scheduling the default appliances"),
]
if stats is not None and timing_gain > 0:
    cards.append((round(grid_gap / timing_gain), "~", "x", "Grid choice vs timing in NJ",
                  f"California: {grid_gap:.0f} g/kWh lower; best PJM hour: {timing_gain:.0f}"))
components.html(stat_strip(cards), height=130)

with st.container(key="panel_why"):
    st.markdown(
        "**Why it matters.** PJM, the largest US grid, serves about 65 million people; in 2025-2026 its "
        "power was mostly gas, nuclear, and coal, averaging about 356 gCO2/kWh. Knowing the cleanest "
        f"hours a day ahead lets flexible loads avoid the dirtiest ones. Sources: {link('PJM')}, "
        f"{link('EIA Form 930')}, {link('IPCC AR5 Annex III', 'IPCC AR5')}.")

with st.container(key="panel_tabs"):
    tab_tomorrow, tab_check, tab_sched, tab_where, tab_how = st.tabs(
        ["Tomorrow", "Check the AI (past days)", "Scheduler", "Where vs when", "How the AI works"])

# ---------------------------------------------------------------- Tomorrow
with tab_tomorrow:
    loading = st.empty()
    loading.markdown('<div class="ch-skel" style="height:470px" aria-label="Loading forecast"></div>',
                     unsafe_allow_html=True)
live_ok, live_day, live_info = False, None, {}
try:
    live_day, live_info = live_forecast()
    if live_day["forecast"].notna().sum() >= 3:
        live_ok = True
        live_day = day_from_hours(live_day, live_info["date"])
except Exception:
    live_ok = False
loading.empty()

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
        st.warning("Live data is still loading or unavailable (slow EIA or weather service, or no "
                   "EIA_API_KEY in .env). Showing the most recent test day's forecast for now; reload "
                   "in a minute for tomorrow's.")
        day, base_label = test_day_frame(test_days[-1]).drop(columns="actual"), "Baseline: same hour yesterday"
        title = f"Forecast for {test_days[-1]:%b %d}, PJM"
    s, start_ts = cleanest(day)
    if s is None:
        st.warning("Not enough hourly data to pick a window for this day.")
    else:
        avg, best = day["forecast"].mean(), window_mean(day["forecast"], s, 3)
        ai_bubble(
            "tomorrow",
            f"Forecast intensity in that window: **{best:.0f} gCO2/kWh**, versus a {avg:.0f} gCO2/kWh "
            f"daily average ({100 * (avg - best) / avg:.0f}% cleaner). {confidence_line(day, s)}",
            header_html=(f'<div class="ch-answer" role="heading" aria-level="2">Cleanest time to run '
                         f'appliances: <span class="ch-time">{charts.window_label(start_ts.hour)}</span></div>'))
        echart(lambda: charts.forecast_echarts(day, start_ts, title, baseline_label=base_label),
               lambda: charts.forecast_fig(day, start_ts, title, baseline_label=base_label), charts.SRC_MODEL_MD)

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
        inside = ((cday["actual"] >= cday["q10"]) & (cday["actual"] <= cday["q90"])).mean()
        verdict = (f"On {picked:%A, %B %d}, my forecast was off by **{err:.1f} gCO2/kWh** on average, "
                   f"versus {base_err:.1f} for \"same hour yesterday\". ")
        if s is not None and t is not None:
            verdict += (f"I picked **{charts.window_label(start_ts.hour)}**; the actual cleanest window was "
                        f"{charts.window_label(true_ts.hour)}, so the pick {hit.lower()} it. ")
        verdict += f"Actual values fell inside my 80% likely range in {100 * inside:.0f}% of hours."
        if s is not None:
            verdict += f" {confidence_line(cday, s)}"
        ai_bubble("check", verdict)
        check_title = f"Forecast vs actual, {picked:%b %d}, PJM"
        echart(lambda: charts.forecast_echarts(cday, start_ts, check_title),
               lambda: charts.forecast_fig(cday, start_ts, check_title), charts.SRC_MODEL_MD)

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
        ai_bubble(
            "scheduler",
            f"Running these in their cleanest windows saves **{out['Saved vs dirtiest (kg)'].sum():.2f} kg CO2** "
            f"versus the dirtiest time and **{out['Saved vs typical (kg)'].sum():.2f} kg** versus a typical "
            f"time (scored on {'actual' if use_actual else 'forecast'} intensity). If {HOUSEHOLDS:,} Princeton "
            f"households did this, that is about **{yearly_t:,.0f} tonnes CO2 a year**.")
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
        echart(lambda: charts.spread_echarts(stats), lambda: charts.spread_fig(stats), charts.SRC_EIA_MD)
        ai_bubble(
            "where",
            f"In PJM, picking the cleanest hour saves about **{timing_gain:.0f} gCO2/kWh**. Switching to "
            f"California's grid would save about **{grid_gap:.0f}**. For New Jersey, a cleaner grid matters "
            "more than better timing.")

# ---------------------------------------------------------------- How the AI works
with tab_how:
    ai_bubble(
        "how",
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
    echart(lambda: charts.importance_echarts(importance), lambda: charts.importance_fig(importance),
           charts.SRC_MODEL_MD)
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
with st.container(key="panel_footer"):
    st.caption(
        f"Data: {link('EIA Form 930')} hourly generation and demand forecasts; weather from "
        f"{link('Open-Meteo')} ({link('ERA5')} reanalysis); emission factors from "
        f"{link('IPCC AR5 Annex III')}; grid context from {link('PJM')}.  \n"
        + (f"Header photo: {HERO_CREDIT}. " if hero else "")
        + f"Background photo: [{BG_CREDIT[0]}]({BG_CREDIT[1]}) on [Unsplash](https://unsplash.com/license). "
        f"Code: {link('GitHub', 'github.com/Darrenk328/cleanhour')}.  \n"
        "© 2026 CleanHour, hackPHS")
    with st.expander("About & privacy"):
        st.markdown(
            "- CleanHour asks for no personal data and has no accounts, tracking, or advertising cookies. "
            "Streamlit's usage statistics are turned off; Streamlit may set one technical security cookie.\n"
            "- Scheduler inputs exist only in your current session and are discarded when you close the tab.\n"
            "- Forecasts are estimates from a statistical model and should not be taken as advice.\n"
            "- Fonts load from Google Fonts, which sees your IP address like any web request.\n"
            f"- Sources and licenses: {link('EIA Form 930')} (U.S. government, public domain); "
            f"{link('Open-Meteo')} (CC BY 4.0); {link('ERA5')} (Copernicus license); "
            f"{link('IPCC AR5 Annex III', 'IPCC AR5')} emission factors; background photo under the "
            "Unsplash License; charts by Apache ECharts (Apache 2.0) and Plotly (MIT).")
