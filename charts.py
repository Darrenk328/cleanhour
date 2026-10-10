"""Charts: pure matplotlib figures built from DataFrames passed in. Never fetches data.

Style: green (#1f7a4d) for the focus series, near-black ink for actuals, gray for
references. Every chart has a title, unit-labelled axes, a legend, and a source note.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

GREEN = "#1f7a4d"
GREEN_LIGHT = "#d6eadf"
INK = "#1f2933"
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


def forecast_chart(day: pd.DataFrame, window_start: int | None, title: str, window_len: int = 3):
    """day: index = local hour 0..23; columns forecast, optional actual, optional baseline."""
    fig, ax = plt.subplots(figsize=(10, 4.2))
    if window_start is not None:
        ax.axvspan(window_start - 0.5, window_start + window_len - 0.5, color=GREEN_LIGHT, lw=0,
                   label=f"Cleanest 3-hour window ({window_label(window_start, window_len)})")
    if "baseline" in day and day["baseline"].notna().any():
        ax.plot(day.index, day["baseline"], color=GRAY, lw=1.6, ls="--", label="Baseline: same hour yesterday")
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
    return _finish(fig, ax, "What the model relies on (permutation importance, test set)",
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
        ax.text(r["mean_max"] + 8, i, f"daily swing {r['mean_max'] - r['mean_min']:.0f}", va="center",
                fontsize=9, color=INK)
    ax.set_yticks(list(y))
    ax.set_yticklabels(d.index)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, d["mean_max"].max() + 120)
    from matplotlib.lines import Line2D
    ax.legend(handles=[
        Line2D([], [], color=GREEN, lw=8, label=f"{focus}: avg daily min to max"),
        Line2D([], [], color=GRAY, lw=8, label="Other grids: avg daily min to max"),
        Line2D([], [], color=GRAY, marker="|", ls="", ms=12, mew=2.5, label="Average (tick)"),
    ], loc="lower right", fontsize=8.5)
    return _finish(fig, ax, "Where vs when: grid choice outweighs timing",
                   "Carbon intensity (gCO2/kWh)", "Grid", SRC_EIA)
