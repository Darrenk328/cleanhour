"""Feature engineering for the PJM day-ahead carbon intensity model.

Forecast setup: at local midnight before day D we predict all 24 hours of D. Every
feature must be knowable at that moment: calendar fields, intensity lags (24h, 168h),
yesterday's mean, the last observed hour, weather, and EIA's day-ahead demand forecast.
Weather uses actual (reanalysis) values as a stand-in for a weather forecast.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data import WEATHER_VARS

TZ = "America/New_York"

FEATURES = [
    "hour", "dow", "month",
    "lag_24h", "lag_168h", "prev_day_mean", "last_obs",
    *WEATHER_VARS,
    "demand_forecast",
]

FEATURE_LABELS = {
    "hour": "Hour of day", "dow": "Day of week", "month": "Month",
    "lag_24h": "Intensity same hour yesterday", "lag_168h": "Intensity same hour last week",
    "prev_day_mean": "Yesterday's average intensity", "last_obs": "Last observed hour (midnight)",
    "temperature_2m": "Temperature", "shortwave_radiation": "Sunlight (solar radiation)",
    "wind_speed_100m": "Wind speed at 100 m", "cloud_cover": "Cloud cover",
    "demand_forecast": "EIA demand forecast",
}


def _lookup(hist: pd.Series, idx: pd.DatetimeIndex, hours: int, fill_back_days: int = 0) -> np.ndarray:
    """hist value `hours` before each timestamp. If fill_back_days > 0, missing values fall
    back to the same hour on earlier days (used in live mode when EIA data lags)."""
    vals = hist.reindex(idx - pd.Timedelta(hours=hours)).to_numpy(dtype=float)
    for k in range(1, fill_back_days + 1):
        miss = np.isnan(vals)
        if not miss.any():
            break
        back = hist.reindex(idx - pd.Timedelta(hours=hours + 24 * k)).to_numpy(dtype=float)
        vals[miss] = back[miss]
    return vals


def make_features(hist: pd.Series, target_idx: pd.DatetimeIndex, weather: pd.DataFrame,
                  demand_fc: pd.Series | None = None, live: bool = False) -> pd.DataFrame:
    """Build the feature frame for `target_idx` (hour-start UTC timestamps).

    hist: observed intensity indexed by ts_utc (only data known before each target day
    should matter; lags >= 24h and day-level aggregates guarantee that).
    live: allow fallbacks for data that EIA has not published yet.
    """
    hist = hist.dropna().sort_index()
    local = target_idx.tz_convert(TZ)
    X = pd.DataFrame(index=target_idx)
    X["ts_local"] = local
    X["date_local"] = local.date
    X["hour"] = local.hour
    X["dow"] = local.dayofweek
    X["month"] = local.month

    fill = 7 if live else 0
    X["lag_24h"] = _lookup(hist, target_idx, 24, fill)
    X["lag_168h"] = _lookup(hist, target_idx, 168, 1 if live else 0)

    hist_local_date = pd.Series(hist.index.tz_convert(TZ).date, index=hist.index)
    daily_mean = hist.groupby(hist_local_date.values).mean()
    daily_n = hist.groupby(hist_local_date.values).size()
    daily_mean = daily_mean[daily_n >= 20]
    day_start = pd.DatetimeIndex(pd.to_datetime(X["date_local"])).tz_localize(TZ, ambiguous="NaT",
                                                                              nonexistent="shift_forward")
    prev_dates = [d - pd.Timedelta(days=1) for d in pd.to_datetime(X["date_local"])]
    X["prev_day_mean"] = [daily_mean.get(d.date(), np.nan) for d in prev_dates]
    if live and X["prev_day_mean"].isna().any() and len(daily_mean):
        X["prev_day_mean"] = X["prev_day_mean"].fillna(daily_mean.iloc[-1])
    # Last observed value strictly before the target day starts.
    pos = hist.index.searchsorted(day_start.tz_convert("UTC"), side="left") - 1
    last = np.where(pos >= 0, hist.to_numpy()[np.clip(pos, 0, None)], np.nan)
    if not live:
        # In backtests require the observation to be the hour right before midnight.
        stale = (day_start.tz_convert("UTC") - hist.index[np.clip(pos, 0, None)]) > pd.Timedelta(hours=1)
        last = np.where(stale, np.nan, last)
    X["last_obs"] = last

    w = weather.reindex(target_idx)
    for c in WEATHER_VARS:
        X[c] = w[c].to_numpy()
    X["demand_forecast"] = demand_fc.reindex(target_idx).to_numpy() if demand_fc is not None else np.nan
    return X


def training_frame(grid: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Feature frame + target for every PJM hour that has an observed intensity."""
    pjm = grid[grid["ba"] == "PJM"].set_index("ts_utc").sort_index()
    hist = pjm["intensity"]
    idx = pd.DatetimeIndex(hist.dropna().index)
    X = make_features(hist, idx, weather, pjm["demand_forecast"])
    X["intensity"] = hist.reindex(idx).to_numpy()
    return X
