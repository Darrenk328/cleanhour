"""Charts: pure matplotlib figures built from DataFrames passed in. Never fetches data.

Style: green (#1f7a4d) for the focus series, near-black ink for actuals, gray for
references. Every chart has a title, unit-labelled axes, a legend, and a source note.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

GREEN = "#1f4d33"  # forest
GREEN_LIGHT = "#dfe9d6"  # pale moss (cleanest-window shading)
LEAF = "#3f8f5a"
MOSS = "#5a7d4f"
FONT_BODY = "Nunito Sans, Segoe UI, system-ui, sans-serif"
FONT_HEAD = "Fraunces, Georgia, serif"
BAND = "rgba(63, 143, 90, 0.22)"  # forecast uncertainty ribbon
INK = "#1d2a22"
GRAY = "#8a939b"
GRID = "#e6e9ec"

SRC_EIA = "Source: EIA Form 930 (Hourly Electric Grid Monitor); IPCC AR5 lifecycle emission factors."
SRC_MODEL = SRC_EIA + " Weather: Open-Meteo (ERA5)."

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": GRAY, "axes.labelcolor": INK, "axes.titlecolor": INK,
    "xtick.color": INK, "ytick.color": INK, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "legend.frameon": False,
})


def _finish(fig, ax, title: str, xlabel: str, ylabel: str, source: str):
    ax.set_title(title, loc="left")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_axisbelow(True)
    fig.text(0.01, 0.01, source, fontsize=7.5, color=GRAY, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return fig


def hour_label(h: int) -> str:
    h = int(h) % 24
    suffix = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12} {suffix}"


def window_label(start_hour: int, length: int = 3) -> str:
    """e.g. (13, 3) -> '1-4 PM'; (10, 3) -> '10 AM-1 PM'."""
    a, b = hour_label(start_hour), hour_label(start_hour + length)
    a_num, a_sfx = a.split()
    b_num, b_sfx = b.split()
    return f"{a_num}-{b}" if a_sfx == b_sfx else f"{a}-{b}"


def sanity_chart(pjm: pd.DataFrame):
    """Daily mean PJM intensity with the daily min-max range. Expects columns
    ts_local (tz-aware) and intensity."""
    d = pjm.set_index("ts_local")["intensity"].resample("D").agg(["mean", "min", "max"]).dropna()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.fill_between(d.index, d["min"], d["max"], color=GREEN_LIGHT, lw=0, label="Daily min-max range")
    ax.plot(d.index, d["mean"], color=GREEN, lw=2, label="Daily mean")
    ax.legend(loc="upper right")
    return _finish(fig, ax, "PJM hourly carbon intensity, 2025-2026",
                   "Date (US Eastern)", "Carbon intensity (gCO2/kWh)", SRC_EIA)


def forecast_chart(day: pd.DataFrame, window_start: int | None, title: str, window_len: int = 3,
                   baseline_label: str = "Baseline: same hour yesterday"):
    """day: index = local hour 0..23; columns forecast, optional actual, optional baseline."""
    fig, ax = plt.subplots(figsize=(10, 4.2))
    if window_start is not None:
        ax.axvspan(window_start - 0.5, window_start + window_len - 0.5, color=GREEN_LIGHT, lw=0,
                   label=f"Cleanest 3-hour window ({window_label(window_start, window_len)})")
    if "baseline" in day and day["baseline"].notna().any():
        ax.plot(day.index, day["baseline"], color=GRAY, lw=1.6, ls="--", label=baseline_label)
    if "actual" in day and day["actual"].notna().any():
        ax.plot(day.index, day["actual"], color=INK, lw=2, marker="o", ms=3.5, label="Actual")
    ax.plot(day.index, day["forecast"], color=GREEN, lw=2.4, label="AI forecast")
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels([hour_label(h) for h in range(0, 24, 3)])
    ax.set_xlim(-0.5, 23.5)
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    return _finish(fig, ax, title, "Hour starting (US Eastern time)",
                   "Carbon intensity (gCO2/kWh)", SRC_MODEL)


def importance_chart(imp: pd.DataFrame, top: int = 10):
    """imp: columns feature, importance (MAE increase, gCO2/kWh), std."""
    d = imp.sort_values("importance").tail(top)
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(d) + 1.4))
    ax.barh(d["feature"], d["importance"], xerr=d.get("std"), color=GREEN, height=0.6,
            error_kw={"ecolor": GRAY, "lw": 1}, label="Increase in error when feature is shuffled")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    return _finish(fig, ax, "Feature importance (permutation, test set)",
                   "MAE increase when shuffled (gCO2/kWh)", "Feature", SRC_MODEL)


def spread_chart(stats: pd.DataFrame, focus: str = "PJM"):
    """stats: index = grid label; columns mean_min, mean, mean_max (avg daily min/mean/max).
    Range bars from average daily minimum to average daily maximum, one per grid."""
    d = stats.sort_values("mean")
    fig, ax = plt.subplots(figsize=(9, 3.6))
    y = range(len(d))
    for i, (name, r) in enumerate(d.iterrows()):
        color = GREEN if name.startswith(focus) else GRAY
        ax.plot([r["mean_min"], r["mean_max"]], [i, i], color=color, lw=10, solid_capstyle="round")
        ax.plot(r["mean"], i, marker="|", color="white", ms=14, mew=2.5)
        ax.text(r["mean_max"] + 8, i, f"daily swing {r['mean_max'] - r['mean_min']:.0f} gCO2/kWh", va="center",
                fontsize=9, color=INK)
    ax.set_yticks(list(y))
    ax.set_yticklabels(d.index)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, d["mean_max"].max() + 170)
    ax.set_ylim(-0.6, len(d) - 0.4)
    from matplotlib.lines import Line2D
    ax.legend(handles=[
        Line2D([], [], color=GREEN, lw=8, label=f"{focus}: avg daily min to max"),
        Line2D([], [], color=GRAY, lw=8, label="Other grids: avg daily min to max"),
        Line2D([], [], color=GRAY, marker="|", ls="", ms=12, mew=2.5, label="Daily average"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=3, fontsize=8.5)
    fig.set_size_inches(9, 4.2)
    return _finish(fig, ax, "Where vs when: grid choice outweighs timing",
                   "Carbon intensity (gCO2/kWh)", "Grid", SRC_EIA)


# ================================================================ interactive (Plotly)
# The app uses these; the matplotlib versions above produce the static README figures.
import plotly.graph_objects as go

LINK_EIA = "https://www.eia.gov/electricity/gridmonitor/"
LINK_IPCC = "https://www.ipcc.ch/site/assets/uploads/2018/02/ipcc_wg3_ar5_annex-iii.pdf"
LINK_METEO = "https://open-meteo.com/"
SRC_EIA_HTML = (f'Source: <a href="{LINK_EIA}">EIA Form 930</a>; '
                f'<a href="{LINK_IPCC}">IPCC AR5</a> emission factors')
SRC_MODEL_HTML = SRC_EIA_HTML + f'; weather <a href="{LINK_METEO}">Open-Meteo</a>'
SRC_EIA_MD = f"Source: [EIA Form 930]({LINK_EIA}); [IPCC AR5]({LINK_IPCC}) emission factors"
SRC_MODEL_MD = SRC_EIA_MD + f"; weather [Open-Meteo]({LINK_METEO})"

# Fuel-mix colors (validated for colorblind separation in stacking order). Coal and
# "other" are deliberately gray; the legend and hover name every fuel.
FUEL_COLORS = {"Nuclear": "#8b6bc4", "Coal": "#4b4b4b", "Gas": "#c07a2c",
               "Other": "#9aa3ab", "Wind": "#3a7fc1", "Solar": "#d9a400"}


def _layout(fig, title: str, xlabel: str, ylabel: str, source: str, height: int = 420):
    fig.update_layout(
        title={"text": title, "x": 0, "xanchor": "left", "font": {"size": 18, "color": INK, "family": FONT_HEAD}},
        xaxis_title=xlabel, yaxis_title=ylabel, height=height,
        template="plotly_white", font={"color": INK, "size": 12, "family": FONT_BODY},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
        legend={"orientation": "h", "yanchor": "top", "y": -0.25, "x": 0, "xanchor": "left"},
        hoverlabel={"bgcolor": "white"},
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=GRAY)
    fig.update_yaxes(gridcolor=GRID, linecolor=GRAY)
    fig.update_layout(meta={"source": source})  # shown as a linked caption by app.plot
    return fig


def forecast_fig(day: pd.DataFrame, window_start, title: str, window_len: int = 3,
                 baseline_label: str = "Baseline: same hour yesterday"):
    """day: index = local hour-start timestamps (naive, US Eastern); columns forecast,
    optional actual, optional baseline. window_start: timestamp or None."""
    fig = go.Figure()
    if window_start is not None:
        end = window_start + pd.Timedelta(hours=window_len)
        fig.add_vrect(x0=window_start, x1=end, fillcolor=GREEN_LIGHT, opacity=1, layer="below", line_width=0)
        # Legend entry for the shaded window.
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=(
            f"Cleanest 3-hour window ({window_label(window_start.hour, window_len)})"),
            marker={"symbol": "square", "size": 14, "color": GREEN_LIGHT}, hoverinfo="skip"))
    hover = "%{x|%b %d, %I:%M %p}<br>%{y:.0f} gCO2/kWh<extra>%{fullData.name}</extra>"
    if {"q10", "q90"} <= set(day.columns) and day["q10"].notna().any():
        fig.add_trace(go.Scatter(x=day.index, y=day["q90"], mode="lines", line={"width": 0},
                                 showlegend=False, name="90% upper", legendgroup="band",
                                 hovertemplate="%{y:.0f} gCO2/kWh<extra>90% upper</extra>"))
        fig.add_trace(go.Scatter(x=day.index, y=day["q10"], mode="lines", line={"width": 0},
                                 fill="tonexty", fillcolor=BAND, name="80% likely range", legendgroup="band",
                                 hovertemplate="%{y:.0f} gCO2/kWh<extra>10% lower</extra>"))
    if "baseline" in day and day["baseline"].notna().any():
        fig.add_trace(go.Scatter(x=day.index, y=day["baseline"], name=baseline_label, mode="lines",
                                 line={"color": GRAY, "width": 2, "dash": "dash"}, hovertemplate=hover))
    if "actual" in day and day["actual"].notna().any():
        fig.add_trace(go.Scatter(x=day.index, y=day["actual"], name="Actual", mode="lines+markers",
                                 line={"color": INK, "width": 2}, marker={"size": 6}, hovertemplate=hover))
    fig.add_trace(go.Scatter(x=day.index, y=day["forecast"], name="AI forecast", mode="lines",
                             line={"color": GREEN, "width": 3}, hovertemplate=hover))
    fig.update_xaxes(type="date", tickformat="%-I %p", dtick=3 * 3600 * 1000)
    fig.update_layout(hovermode="x unified")
    return _layout(fig, title, "Hour starting (US Eastern time)", "Carbon intensity (gCO2/kWh)", SRC_MODEL_MD)


def mix_animation_fig(mix: pd.DataFrame, title: str):
    """Animated stacked area of the fuel mix through one day.
    mix: index = local hour-start timestamps (naive); columns = FUEL_COLORS keys, in GW."""
    fuels = [f for f in FUEL_COLORS if f in mix]
    x = list(mix.index)
    ymax = float(mix[fuels].sum(axis=1).max()) * 1.08

    def traces(k):
        sub = mix.iloc[:k + 1]
        return [go.Scatter(x=sub.index, y=sub[f], name=f, mode="lines", stackgroup="mix",
                           line={"width": 0.8, "color": "white"}, fillcolor=FUEL_COLORS[f],
                           hovertemplate="%{x|%I %p}: %{y:.1f} GW<extra>" + f + "</extra>")
                for f in fuels]

    frames = [go.Frame(data=traces(k), name=str(k)) for k in range(len(x))]
    # Start on the full day so the chart is readable before Play; Play restarts from midnight.
    fig = go.Figure(data=traces(len(x) - 1), frames=frames)
    anim = {"frame": {"duration": 450, "redraw": True}, "transition": {"duration": 300, "easing": "cubic-in-out"},
            "fromcurrent": False, "mode": "immediate"}
    fig.update_layout(
        updatemenus=[{"type": "buttons", "showactive": False, "x": 0, "y": 1.02, "xanchor": "left",
                      "yanchor": "bottom", "direction": "left", "pad": {"r": 6},
                      "buttons": [
                          {"label": "Play the day", "method": "animate", "args": [None, anim]},
                          {"label": "Pause", "method": "animate",
                           "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]},
                      ]}],
        sliders=[{"active": len(x) - 1, "x": 0, "len": 1, "y": -0.12, "pad": {"t": 10},
                  # Hide the 24 crowded tick labels; the current hour shows above the slider.
                  "font": {"color": "rgba(0,0,0,0)"}, "ticklen": 3,
                  "currentvalue": {"prefix": "Hour: ", "font": {"color": INK}},
                  "steps": [{"label": pd.Timestamp(t).strftime("%-I %p"), "method": "animate",
                             "args": [[str(k)], {"frame": {"duration": 0, "redraw": True},
                                                 "transition": {"duration": 200}, "mode": "immediate"}]}
                            for k, t in enumerate(x)]}],
    )
    fig.update_xaxes(type="date", range=[x[0], x[-1]], tickformat="%-I %p", dtick=3 * 3600 * 1000)
    fig.update_yaxes(range=[0, ymax])
    _layout(fig, title, "Hour starting (US Eastern time)", "Generation (GW)", SRC_EIA_MD, height=520)
    fig.update_layout(margin={"t": 90}, legend={"y": -0.38})
    return fig


def importance_fig(imp: pd.DataFrame, top: int = 10):
    d = imp.sort_values("importance").tail(top)
    fig = go.Figure(go.Bar(
        x=d["importance"], y=d["feature"], orientation="h", marker_color=GREEN,
        error_x={"type": "data", "array": d["std"], "color": GRAY, "thickness": 1},
        name="MAE increase when shuffled",
        hovertemplate="%{y}: +%{x:.2f} gCO2/kWh error when shuffled<extra></extra>"))
    fig.update_layout(showlegend=True)
    return _layout(fig, "Feature importance (test set)", "MAE increase when shuffled (gCO2/kWh)",
                   "", SRC_MODEL_MD, height=460)


def spread_fig(stats: pd.DataFrame, focus: str = "PJM"):
    """Range bars: average daily min to max per grid, with the daily average marked."""
    d = stats.sort_values("mean", ascending=False)
    fig = go.Figure()
    for is_focus, name in [(True, f"{focus}: avg daily min to max"), (False, "Other grids: avg daily min to max")]:
        sub = d[[n.startswith(focus) == is_focus for n in d.index]]
        fig.add_trace(go.Bar(
            y=sub.index, x=sub["mean_max"] - sub["mean_min"], base=sub["mean_min"], orientation="h",
            name=name, marker_color=GREEN if is_focus else GRAY, width=0.45,
            customdata=sub[["mean_min", "mean_max"]].to_numpy(),
            hovertemplate="%{y}<br>avg daily min %{customdata[0]:.0f}, max %{customdata[1]:.0f} gCO2/kWh"
                          "<br>daily swing %{x:.0f} gCO2/kWh<extra></extra>"))
    fig.add_trace(go.Scatter(y=d.index, x=d["mean"], mode="markers", name="Daily average",
                             marker={"symbol": "line-ns-open", "size": 22, "color": INK, "line": {"width": 3, "color": INK}},
                             hovertemplate="%{y}<br>daily average %{x:.0f} gCO2/kWh<extra></extra>"))
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(range=[0, float(d["mean_max"].max()) * 1.1])
    fig.update_yaxes(categoryorder="array", categoryarray=list(d.index[::-1]))
    return _layout(fig, "Where vs when: grid choice outweighs timing", "Carbon intensity (gCO2/kWh)",
                   "", SRC_EIA_MD, height=400)


# ================================================================ animated (ECharts)
# Self-contained HTML pages for st.components.v1.html. Each chart animates in once when it
# scrolls into view (IntersectionObserver), honours prefers-reduced-motion, and resizes
# with its frame. The app falls back to the Plotly versions above if building one fails.
import html
import json

ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700"
             "&family=Nunito+Sans:wght@400;600;700&display=swap")


def _hour_labels() -> list[str]:
    return [hour_label(h) for h in range(24)]


def _echarts_page(payload: dict, script: str, height: int, aria: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{FONTS_URL}">
<style>
html, body {{ margin: 0; background: transparent; font-family: {FONT_BODY}; color: {INK}; }}
h3 {{ font-family: {FONT_HEAD}; font-size: 17px; font-weight: 700; color: {INK}; margin: 2px 0 6px;
  line-height: 1.25; }}
#c {{ width: 100%; height: {height}px; }}
.err {{ font-size: 14px; color: {INK}; padding: 12px 4px; }}
</style></head><body>
<h3>{html.escape(payload["title"])}</h3>
<div id="c" role="img" aria-label="{html.escape(aria)}"></div>
<script src="{ECHARTS_URL}"></script>
<script>
(() => {{
  const el = document.getElementById("c");
  if (!window.echarts) {{ el.innerHTML = '<p class="err">This chart could not load. Check your connection and reload.</p>'; return; }}
  const D = {json.dumps(payload)};
  const C = {{green: "{GREEN}", leaf: "{LEAF}", moss: "{MOSS}", ink: "{INK}", gray: "{GRAY}",
             grid: "{GRID}", windowFill: "{GREEN_LIGHT}", band: "{BAND}"}};
  const FONT = "{FONT_BODY}", HEAD = "{FONT_HEAD}";
  const TOP = 12;  // the title is an HTML heading above the chart
  const narrow = () => el.clientWidth < 560;
  let relayout = () => {{}};  // set by each chart: width-dependent grid and labels
  const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const chart = echarts.init(el, null, {{renderer: "canvas"}});
  const base = {{
    textStyle: {{fontFamily: FONT, color: C.ink}},
    legend: {{bottom: 0, left: 0, itemGap: 14, textStyle: {{fontFamily: FONT, fontSize: 12, color: C.ink}}}},
    animation: !REDUCE, animationEasing: "cubicOut", animationEasingUpdate: "cubicOut",
  }};
  const later = (ms, fn) => REDUCE ? fn() : setTimeout(fn, ms);
  let started = false, inView = false;
  // A chart in a hidden tab has zero width; wait until it is both visible and laid out.
  const tryStart = () => {{
    if (started || !inView || el.clientWidth === 0) return;
    started = true;
    chart.resize();
    {script}
    relayout();
  }};
  if ("IntersectionObserver" in window) {{
    new IntersectionObserver(es => es.forEach(e => {{ inView = e.isIntersecting && e.intersectionRect.width > 0; tryStart(); }}),
                             {{threshold: [0, 0.2]}}).observe(el);
  }} else {{ inView = true; }}
  new ResizeObserver(() => {{ chart.resize(); if (started) relayout(); else tryStart(); }}).observe(el);
  tryStart();
}})();
</script></body></html>"""


def forecast_echarts(day: pd.DataFrame, window_start, title: str, window_len: int = 3,
                     baseline_label: str = "Baseline: same hour yesterday") -> tuple[str, int]:
    """Forecast line draws itself, then the 80% band fades in, then the cleanest window grows in.
    day: index = naive local timestamps (one per hour); columns forecast, q10, q90, baseline,
    optional actual."""
    hours = [int(t.hour) for t in day.index]
    col = lambda c: [None if pd.isna(v) else round(float(v), 1) for v in day[c]] if c in day else None
    payload = {
        "title": title, "hours": hours, "labels": _hour_labels(),
        "date": pd.Timestamp(day.index[0]).strftime("%b %d"),
        "forecast": col("forecast"), "q10": col("q10"), "q90": col("q90"),
        "baseline": col("baseline"), "actual": col("actual") if "actual" in day and day["actual"].notna().any() else None,
        "baselineLabel": baseline_label,
        "window": None if window_start is None else [int(window_start.hour), int(window_start.hour) + window_len],
        "windowLabel": None if window_start is None else
            f"Cleanest 3-hour window ({window_label(window_start.hour, window_len)})",
    }
    script = """
  const cats = D.hours.map(h => D.labels[h]);
  const xy = arr => arr || [];
  const diff = D.q10 ? D.q10.map((lo, i) => (lo == null || D.q90[i] == null) ? null : +(D.q90[i] - lo).toFixed(1)) : [];
  const fmt = v => v == null ? "n/a" : Math.round(v) + " gCO2/kWh";
  const series = [];
  if (D.window) series.push({name: D.windowLabel, type: "line", data: [], itemStyle: {color: C.windowFill},
      lineStyle: {width: 0}, markArea: {silent: true, itemStyle: {color: "rgba(0,0,0,0)"}, data: []}});
  if (D.q10) {
    series.push({name: "band-low", type: "line", stack: "band", data: xy(D.q10), symbol: "none",
                 lineStyle: {width: 0}, silent: true, tooltip: {show: false}});
    series.push({name: "80% likely range", type: "line", stack: "band", data: diff, symbol: "none",
                 lineStyle: {width: 0}, itemStyle: {color: C.band}, areaStyle: {color: C.band, opacity: 0}});
  }
  if (D.baseline) series.push({name: D.baselineLabel, type: "line", data: xy(D.baseline), symbol: "none",
      lineStyle: {color: C.gray, width: 2, type: "dashed"}, itemStyle: {color: C.gray},
      animationDuration: 1200});
  if (D.actual) {
    series.push({name: "Actual", type: "line", data: xy(D.actual), symbol: "none",
                 lineStyle: {color: C.ink, width: 2}, itemStyle: {color: C.ink}, animationDuration: 1200});
    series.push({name: "Actual", type: "scatter", data: xy(D.actual), symbolSize: 7, itemStyle: {color: C.ink},
                 animationDuration: 500, animationDelay: i => 1200 + i * 30, tooltip: {show: false}});
  }
  series.push({name: "AI forecast", type: "line", data: xy(D.forecast), symbol: "none", z: 5,
               lineStyle: {color: C.green, width: 3}, itemStyle: {color: C.green}, animationDuration: 1200});
  const legendData = series.map(s => s.name).filter((n, i, a) => n !== "band-low" && a.indexOf(n) === i);
  chart.setOption(Object.assign({}, base, {
    grid: {left: 52, right: 16, top: TOP, bottom: 96},
    legend: Object.assign({}, base.legend, {data: legendData.map(n => (n === D.windowLabel || n === "80% likely range") ? {name: n, icon: "rect"} : n)}),
    tooltip: {trigger: "axis", backgroundColor: "#fbf8f1", borderColor: C.grid, textStyle: {fontFamily: FONT, color: C.ink},
      formatter: ps => {
        const i = ps[0].dataIndex;
        const rows = [`<b>${D.date}, ${D.labels[D.hours[i]]}</b>`];
        rows.push(`AI forecast: ${fmt(D.forecast[i])}`);
        if (D.q10) rows.push(`80% likely range: ${fmt(D.q10[i])} to ${fmt(D.q90[i])}`);
        if (D.actual) rows.push(`Actual: ${fmt(D.actual[i])}`);
        if (D.baseline) rows.push(`${D.baselineLabel}: ${fmt(D.baseline[i])}`);
        return rows.join("<br>");
      }},
    xAxis: {type: "category", data: cats, boundaryGap: false, name: "Hour starting (US Eastern time)",
            nameLocation: "middle", nameGap: 28, axisLabel: {interval: 2},
            splitLine: {show: true, interval: 2, lineStyle: {color: C.grid}}},
    yAxis: {type: "value", scale: true, name: "Carbon intensity (gCO2/kWh)", nameLocation: "middle", nameGap: 40,
            splitLine: {lineStyle: {color: C.grid}}},
    series,
  }));
  relayout = () => chart.setOption({grid: {bottom: narrow() ? 150 : 96}, xAxis: {axisLabel: {interval: narrow() ? 5 : 2}}});
  // Stage 2: the likely range fades in once the lines have drawn.
  later(1250, () => D.q10 && chart.setOption({series: [{name: "80% likely range", areaStyle: {opacity: 1}}]},
                                             {lazyUpdate: false}));
  // Stage 3: the cleanest window grows in.
  later(1800, () => D.window && chart.setOption({series: [{name: D.windowLabel, markArea: {
      itemStyle: {color: C.windowFill}, animationDuration: 700,
      data: [[{xAxis: D.labels[D.window[0]]}, {xAxis: cats[Math.min(cats.length - 1, D.hours.indexOf(D.window[0]) + 3)]}]]}}]}));
"""
    return _echarts_page(payload, script, 440, title), 510


def spread_echarts(stats: pd.DataFrame, focus: str = "PJM") -> tuple[str, int]:
    """Range bars grow from zero one grid at a time; the daily-average ticks appear last."""
    d = stats.sort_values("mean")
    names = list(d.index)
    is_focus = [n.startswith(focus) for n in names]
    payload = {
        "title": "Where vs when: grid choice outweighs timing", "names": names,
        "min": [round(float(v), 1) for v in d["mean_min"]], "max": [round(float(v), 1) for v in d["mean_max"]],
        "mean": [round(float(v), 1) for v in d["mean"]], "focus": is_focus,
        "focusLabel": f"{focus}: avg daily min to max",
    }
    script = """
  const n = D.names.length, delay = i => i * 220;
  const span = D.names.map((_, i) => +(D.max[i] - D.min[i]).toFixed(1));
  const pick = want => span.map((v, i) => D.focus[i] === want ? v : "-");
  const tip = i => `<b>${D.names[i]}</b><br>avg daily min ${Math.round(D.min[i])}, max ${Math.round(D.max[i])} gCO2/kWh`
                 + `<br>daily swing ${Math.round(D.max[i] - D.min[i])} gCO2/kWh<br>daily average ${Math.round(D.mean[i])} gCO2/kWh`;
  chart.setOption(Object.assign({}, base, {
    grid: {left: 8, right: 24, top: TOP, bottom: 72, containLabel: true},
    tooltip: {trigger: "item", backgroundColor: "#fbf8f1", borderColor: C.grid, textStyle: {fontFamily: FONT, color: C.ink},
              formatter: p => tip(p.dataIndex)},
    legend: Object.assign({}, base.legend, {data: [{name: D.focusLabel, icon: "rect"},
            {name: "Other grids: avg daily min to max", icon: "rect"},
            {name: "Daily average", icon: "path://M0,0 L3,0 L3,16 L0,16 Z"}]}),
    xAxis: {type: "value", min: 0, name: "Carbon intensity (gCO2/kWh)", nameLocation: "middle", nameGap: 28,
            splitLine: {lineStyle: {color: C.grid}}},
    yAxis: {type: "category", data: D.names, axisTick: {show: false}},
    series: [
      {name: "base", type: "bar", stack: "r", data: D.min, itemStyle: {color: "rgba(0,0,0,0)"}, silent: true,
       tooltip: {show: false}, animationDuration: 1000, animationDelay: delay, barWidth: "45%"},
      {name: D.focusLabel, type: "bar", stack: "r", data: pick(true), itemStyle: {color: C.green, borderRadius: 4},
       animationDuration: 1000, animationDelay: delay},
      {name: "Other grids: avg daily min to max", type: "bar", stack: "r", data: pick(false),
       itemStyle: {color: C.gray, borderRadius: 4}, animationDuration: 1000, animationDelay: delay},
      {name: "Daily average", type: "scatter", data: D.mean.map((v, i) => [v, i]), symbol: "rect",
       symbolSize: [3, 26], itemStyle: {color: C.ink}, z: 5, animationDuration: 400,
       animationDelay: i => 1000 + n * 220 + i * 80},
    ],
  }));
  relayout = () => chart.setOption({grid: {bottom: narrow() ? 110 : 72}});
"""
    return _echarts_page(payload, script, 340, "Where vs when"), 410


def importance_echarts(imp: pd.DataFrame, top: int = 10) -> tuple[str, int]:
    """Bars grow from zero, staggered top to bottom; error whiskers follow."""
    d = imp.sort_values("importance").tail(top)
    payload = {
        "title": "Feature importance (test set)", "names": list(d["feature"]),
        "imp": [round(float(v), 3) for v in d["importance"]], "std": [round(float(v), 3) for v in d["std"]],
    }
    script = """
  const n = D.names.length, delay = i => (n - 1 - i) * 90;  // top bar first
  chart.setOption(Object.assign({}, base, {
    grid: {left: 8, right: 24, top: TOP, bottom: 64, containLabel: true},
    tooltip: {trigger: "item", backgroundColor: "#fbf8f1", borderColor: C.grid, textStyle: {fontFamily: FONT, color: C.ink},
              formatter: p => `<b>${D.names[p.dataIndex]}</b><br>+${D.imp[p.dataIndex].toFixed(2)} gCO2/kWh error when shuffled`
                              + ` (± ${D.std[p.dataIndex].toFixed(2)})`},
    legend: Object.assign({}, base.legend, {data: [{name: "MAE increase when shuffled", icon: "rect"}]}),
    xAxis: {type: "value", min: 0, name: "MAE increase when shuffled (gCO2/kWh)", nameLocation: "middle", nameGap: 28,
            splitLine: {lineStyle: {color: C.grid}}},
    yAxis: {type: "category", data: D.names, axisTick: {show: false}},
    series: [
      {name: "MAE increase when shuffled", type: "bar", data: D.imp, barWidth: "60%",
       itemStyle: {color: C.green, borderRadius: [0, 4, 4, 0]}, animationDuration: 1000, animationDelay: delay},
      {name: "spread", type: "custom", silent: true, tooltip: {show: false}, z: 5,
       data: D.imp.map((v, i) => [i, Math.max(0, v - D.std[i]), v + D.std[i]]),
       renderItem: (params, api) => {
         const y = api.coord([0, api.value(0)])[1], a = api.coord([api.value(1), 0])[0], b = api.coord([api.value(2), 0])[0];
         const s = {stroke: C.gray, lineWidth: 1.2};
         return {type: "group", children: [
           {type: "line", shape: {x1: a, y1: y, x2: b, y2: y}, style: s},
           {type: "line", shape: {x1: a, y1: y - 4, x2: a, y2: y + 4}, style: s},
           {type: "line", shape: {x1: b, y1: y - 4, x2: b, y2: y + 4}, style: s}]};
       },
       animationDuration: 400, animationDelay: 1000 + n * 90},
    ],
  }));
  relayout = () => chart.setOption({grid: {bottom: narrow() ? 84 : 64}});
"""
    return _echarts_page(payload, script, 420, "Feature importance"), 490
