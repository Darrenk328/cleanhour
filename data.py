"""Data layer: download, clean, and cache EIA-930 grid data and Open-Meteo weather.

This module never draws. Run `python data.py` once to build data/*.csv; everything
after that works offline (except the optional live "Tomorrow" mode).

Time convention: every table is indexed by `ts_utc`, the UTC START of the hour
(EIA reports hour-ending; we subtract one hour so "hour 13" means 1:00-2:00 PM).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"

EIA_FILES = [
    "EIA930_BALANCE_2025_Jan_Jun",
    "EIA930_BALANCE_2025_Jul_Dec",
    "EIA930_BALANCE_2026_Jan_Jun",
    "EIA930_BALANCE_2026_Jul_Dec",
]
EIA_URL = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/{}.csv"
EIA_API_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"

BAS = ["PJM", "CISO", "ERCO"]
BA_TZ = {"PJM": "America/New_York", "CISO": "America/Los_Angeles", "ERCO": "America/Chicago"}
BA_NAME = {"PJM": "PJM (NJ, PA, OH, VA...)", "CISO": "California ISO", "ERCO": "ERCOT (Texas)"}

# IPCC AR5 (2014) Annex III lifecycle medians, gCO2eq/kWh.
# "other" covers EIA "Other" and "Unknown" fuel; we assume gas-like (490), which is
# conservative for PJM where "Other" is mostly waste, biomass, and gas-fired cogeneration.
# Geothermal (CISO only) uses the IPCC median of 38.
FACTORS = {
    "coal": 820, "gas": 490, "oil": 720, "nuclear": 12, "hydro": 24,
    "solar": 48, "wind": 11, "geothermal": 38, "other": 490,
}
FUELS = list(FACTORS)

# Map real EIA-930 "(Adjusted)" CSV headers to fuel groups. Storage (pumped, battery,
# other/unknown storage) is excluded: it shifts energy in time rather than generating it.
_CSV_FUEL_MATCH = {
    "from Coal": "coal",
    "from Natural Gas": "gas",
    "from Nuclear": "nuclear",
    "from All Petroleum Products": "oil",
    "from Hydropower Excluding Pumped Storage": "hydro",
    "from Solar": "solar",
    "from Wind": "wind",
    "from Geothermal": "geothermal",
    "from Other Fuel Sources": "other",
    "from Unknown Fuel Sources": "other",
}
_API_FUEL = {"COL": "coal", "NG": "gas", "NUC": "nuclear", "OIL": "oil", "WAT": "hydro",
             "SUN": "solar", "WND": "wind", "GEO": "geothermal", "OTH": "other", "UNK": "other"}

# Weather: three points spanning PJM's footprint, averaged.
WEATHER_POINTS = {
    "Princeton NJ": (40.3573, -74.6672),
    "Columbus OH": (39.9612, -82.9988),
    "Richmond VA": (37.5407, -77.4360),
}
WEATHER_VARS = ["temperature_2m", "shortwave_radiation", "wind_speed_100m", "cloud_cover"]


# ---------------------------------------------------------------- EIA bulk CSVs
def download_eia(force: bool = False) -> list[Path]:
    RAW.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in EIA_FILES:
        path = RAW / f"{name}.csv"
        if force or not path.exists():
            print(f"downloading {name} ...")
            r = requests.get(EIA_URL.format(name), timeout=300)
            r.raise_for_status()
            path.write_bytes(r.content)
        paths.append(path)
    return paths


def _num(s: pd.Series) -> pd.Series:
    """Parse numbers that may carry comma thousands separators."""
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")


def add_intensity(df: pd.DataFrame) -> pd.DataFrame:
    """intensity = sum(MW_fuel * factor) / sum(MW_fuel), gCO2/kWh. Negative MW clipped to 0."""
    mw = df[FUELS].clip(lower=0)
    total = mw.sum(axis=1, min_count=1)
    emis = sum(mw[f].fillna(0) * FACTORS[f] for f in FUELS)
    df = df.copy()
    df["total_mw"] = total
    df["intensity"] = (emis / total).where(total > 0)
    return df


def parse_eia_csv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str)
    raw = raw[raw["Balancing Authority"].isin(BAS)]
    out = pd.DataFrame({"ba": raw["Balancing Authority"]}, index=raw.index)
    end = pd.to_datetime(raw["UTC Time at End of Hour"], format="%m/%d/%Y %I:%M:%S %p", utc=True)
    out["ts_utc"] = end - pd.Timedelta(hours=1)
    out["demand_forecast"] = _num(raw["Demand Forecast (MW)"])
    out["demand"] = _num(raw["Demand (MW) (Adjusted)"])
    for fuel in FUELS:
        cols = [c for c in raw.columns if "(Adjusted)" in c
                and any(k in c and v == fuel for k, v in _CSV_FUEL_MATCH.items())]
        out[fuel] = pd.concat([_num(raw[c]) for c in cols], axis=1).sum(axis=1, min_count=1) if cols else np.nan
    return out.reset_index(drop=True)


def build_grid() -> pd.DataFrame:
    paths = download_eia()
    df = pd.concat([parse_eia_csv(p) for p in paths], ignore_index=True)
    df = df.drop_duplicates(["ba", "ts_utc"], keep="last").sort_values(["ba", "ts_utc"])
    df = add_intensity(df)
    # Keep rows that have a generation mix, plus future rows that only carry the
    # EIA demand forecast (useful for the day-ahead model).
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- Open-Meteo
def _open_meteo(url: str, params: dict) -> pd.DataFrame:
    lats = ",".join(str(p[0]) for p in WEATHER_POINTS.values())
    lons = ",".join(str(p[1]) for p in WEATHER_POINTS.values())
    q = {"latitude": lats, "longitude": lons, "hourly": ",".join(WEATHER_VARS), "timezone": "GMT", **params}
    r = requests.get(url, params=q, timeout=120)
    r.raise_for_status()
    js = r.json()
    js = js if isinstance(js, list) else [js]
    frames = []
    for loc in js:
        h = pd.DataFrame(loc["hourly"])
        h["ts_utc"] = pd.to_datetime(h.pop("time"), utc=True)
        frames.append(h.set_index("ts_utc"))
    # Average the three points hour by hour.
    return pd.concat(frames).groupby(level=0).mean()[WEATHER_VARS]


def fetch_weather_archive(start: str, end: str) -> pd.DataFrame:
    """ERA5 reanalysis, hourly, averaged over the 3 PJM points. Chunked by year."""
    parts = []
    for s, e in _year_chunks(pd.Timestamp(start), pd.Timestamp(end)):
        print(f"weather archive {s:%Y-%m-%d} .. {e:%Y-%m-%d}")
        parts.append(_open_meteo("https://archive-api.open-meteo.com/v1/archive",
                                 {"start_date": f"{s:%Y-%m-%d}", "end_date": f"{e:%Y-%m-%d}"}))
    return pd.concat(parts).sort_index().loc[lambda d: ~d.index.duplicated()]


def fetch_weather_forecast(past_days: int = 14, forecast_days: int = 3) -> pd.DataFrame:
    """Open-Meteo forecast API (same variables and points). Used for live mode and
    to fill the last few days the ERA5 archive has not published yet."""
    return _open_meteo("https://api.open-meteo.com/v1/forecast",
                       {"past_days": past_days, "forecast_days": forecast_days})


def _year_chunks(start: pd.Timestamp, end: pd.Timestamp):
    s = start
    while s <= end:
        e = min(pd.Timestamp(year=s.year, month=12, day=31), end)
        yield s, e
        s = e + pd.Timedelta(days=1)


def build_weather(grid: pd.DataFrame) -> pd.DataFrame:
    start = grid["ts_utc"].min().tz_convert(None).normalize()
    end = grid["ts_utc"].max().tz_convert(None).normalize()
    # The archive rejects future dates; the forecast API fills the last ~2 weeks.
    end = min(end, pd.Timestamp.now(tz="UTC").tz_convert(None).normalize() - pd.Timedelta(days=2))
    archive = fetch_weather_archive(str(start.date()), str(end.date()))
    archive = archive.dropna(how="all")
    try:
        recent = fetch_weather_forecast(past_days=14, forecast_days=3)
        missing = recent.index.difference(archive.index)
        archive = pd.concat([archive, recent.loc[missing]]).sort_index()
    except requests.RequestException as exc:
        print(f"forecast fill skipped: {exc}")
    archive.index.name = "ts_utc"
    return archive


# ---------------------------------------------------------------- EIA API v2 (live)
def _api_key() -> str | None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    return os.environ.get("EIA_API_KEY") or None


def fetch_live_pjm(days: int = 10) -> pd.DataFrame:
    """Most recent ~`days` days of PJM hourly fuel mix from EIA API v2.

    Paginates 5,000 rows at a time. API `period` is the UTC hour ending; we convert
    to hour-start UTC to match the bulk CSVs. Raises RuntimeError if no key.
    """
    key = _api_key()
    if not key:
        raise RuntimeError("EIA_API_KEY not set in .env")
    start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).strftime("%Y-%m-%dT%H")
    rows, offset = [], 0
    while True:
        params = {"api_key": key, "frequency": "hourly", "data[0]": "value",
                  "facets[respondent][]": "PJM", "start": start,
                  "sort[0][column]": "period", "sort[0][direction]": "asc",
                  "offset": offset, "length": 5000}
        try:
            r = requests.get(EIA_API_URL, params=params, timeout=60)
            r.raise_for_status()
        except requests.RequestException as exc:
            # Never leak the key through an exception message that embeds the URL.
            raise RuntimeError(f"EIA API request failed ({type(exc).__name__})") from None
        resp = r.json().get("response", {})
        batch = resp.get("data", [])
        rows += batch
        offset += len(batch)
        if not batch or offset >= int(resp.get("total", 0)):
            break
    if not rows:
        raise RuntimeError("EIA API returned no rows")
    long = pd.DataFrame(rows)
    long["fuel"] = long["fueltype"].map(_API_FUEL)
    long = long.dropna(subset=["fuel"])
    long["value"] = _num(long["value"])
    long["ts_utc"] = pd.to_datetime(long["period"], format="%Y-%m-%dT%H", utc=True) - pd.Timedelta(hours=1)
    wide = long.pivot_table(index="ts_utc", columns="fuel", values="value", aggfunc="sum")
    for f in FUELS:
        if f not in wide:
            wide[f] = np.nan
    wide = wide[FUELS].reset_index()
    wide.insert(0, "ba", "PJM")
    return add_intensity(wide)


# ---------------------------------------------------------------- cached loaders
def load_grid() -> pd.DataFrame:
    df = pd.read_csv(DATA / "grid_hourly.csv")
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    return df


def load_weather() -> pd.DataFrame:
    df = pd.read_csv(DATA / "weather_pjm.csv", index_col="ts_utc")
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def main() -> None:
    DATA.mkdir(exist_ok=True)
    grid = build_grid()
    grid.to_csv(DATA / "grid_hourly.csv", index=False)
    weather = build_weather(grid)
    weather.to_csv(DATA / "weather_pjm.csv")

    has_mix = grid.dropna(subset=["intensity"])
    print(f"\ngrid rows: {len(grid):,}  (with fuel mix: {len(has_mix):,})")
    for ba, g in has_mix.groupby("ba"):
        print(f"  {ba:5s} {g['ts_utc'].min():%Y-%m-%d %H:%M} .. {g['ts_utc'].max():%Y-%m-%d %H:%M} UTC  "
              f"rows={len(g):,}  mean intensity={g['intensity'].mean():.1f} gCO2/kWh")
    print(f"weather rows: {len(weather):,}  {weather.index.min()} .. {weather.index.max()}")
    print(f"weather NaN share: {weather.isna().mean().round(3).to_dict()}")


if __name__ == "__main__":
    main()
