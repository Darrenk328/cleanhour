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
