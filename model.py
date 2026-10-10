"""Train and evaluate the PJM day-ahead carbon intensity model.

Run `python model.py` to train on data/*.csv and write models/model.joblib,
models/metrics.json, models/importance.csv, and models/test_predictions.csv.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

import data
from features import FEATURE_LABELS, FEATURES, TZ, make_features, training_frame

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
TEST_DAYS = 61  # ~2 months
WINDOW = 3


def cleanest_window(values, length: int = WINDOW) -> int | None:
    """Start index of the contiguous `length`-hour block with the lowest total."""
    v = np.asarray(values, dtype=float)
    if len(v) < length or np.isnan(v).all():
        return None
    sums = np.convolve(np.nan_to_num(v, nan=np.inf), np.ones(length), mode="valid")
    if not np.isfinite(sums).any():
        return None
    return int(np.argmin(sums))


def new_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="absolute_error", learning_rate=0.05, max_iter=600, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, categorical_features=None,
        early_stopping=False, random_state=0,
    )


def split(frame: pd.DataFrame):
    """Time split: last TEST_DAYS complete local days are the test set. Never random."""
    counts = frame.groupby("date_local").size()
    full_days = counts[counts >= 23].index
    test_days = sorted(full_days)[-TEST_DAYS:]
    is_test = frame["date_local"].isin(test_days)
    return frame[~is_test], frame[is_test], test_days[0]


def window_stats(df: pd.DataFrame, col: str) -> dict:
    """Cleanest-3h-window hit rates and the extra intensity paid vs the true best window."""
    exact, overlap, regret = [], [], []
    for _, d in df.groupby("date_local"):
        if len(d) < 23:
            continue
        d = d.sort_values("ts_local")
        true = cleanest_window(d["intensity"].to_numpy())
        pred = cleanest_window(d[col].to_numpy())
        if true is None or pred is None:
            continue
        act = d["intensity"].to_numpy()
        exact.append(pred == true)
        overlap.append(abs(pred - true) < WINDOW)
        regret.append(act[pred:pred + WINDOW].mean() - act[true:true + WINDOW].mean())
    return {"hit_rate_exact": float(np.mean(exact)), "hit_rate_overlap": float(np.mean(overlap)),
            "avg_regret_g_per_kwh": float(np.mean(regret)), "days": len(exact)}


def train() -> dict:
    grid, weather = data.load_grid(), data.load_weather()
    frame = training_frame(grid, weather)
    frame = frame.dropna(subset=["lag_24h", "lag_168h"])
    train_df, test_df, test_start = split(frame)

    model = new_model().fit(train_df[FEATURES], train_df["intensity"])
    test_df = test_df.copy()
    test_df["forecast"] = model.predict(test_df[FEATURES])
    test_df["baseline_yesterday"] = test_df["lag_24h"]
    hour_avg = train_df.groupby("hour")["intensity"].mean()
    test_df["baseline_hour_avg"] = test_df["hour"].map(hour_avg)

    def mae(col):
        return float((test_df[col] - test_df["intensity"]).abs().mean())

    rows = {}
    for col, name in [("forecast", "AI model (gradient boosting)"),
                      ("baseline_yesterday", "Baseline: same hour yesterday"),
                      ("baseline_hour_avg", "Baseline: hour-of-day average")]:
        rows[name] = {"mae_g_per_kwh": mae(col), **window_stats(test_df, col)}
    m = rows["AI model (gradient boosting)"]["mae_g_per_kwh"]
    metrics = {
        "train_start": str(train_df["date_local"].min()), "train_end": str(train_df["date_local"].max()),
        "test_start": str(test_start), "test_end": str(test_df["date_local"].max()),
        "train_hours": int(len(train_df)), "test_hours": int(len(test_df)),
        "test_mean_intensity": float(test_df["intensity"].mean()),
        "models": rows,
        "improvement_vs_yesterday_pct": 100 * (1 - m / rows["Baseline: same hour yesterday"]["mae_g_per_kwh"]),
        "improvement_vs_hour_avg_pct": 100 * (1 - m / rows["Baseline: hour-of-day average"]["mae_g_per_kwh"]),
    }

    pi = permutation_importance(model, test_df[FEATURES], test_df["intensity"],
                                scoring="neg_mean_absolute_error", n_repeats=5, random_state=0)
    importance = pd.DataFrame({"feature_key": FEATURES, "importance": pi.importances_mean,
                               "std": pi.importances_std})
    importance["feature"] = importance["feature_key"].map(FEATURE_LABELS)
    importance = importance.sort_values("importance", ascending=False)

    MODELS.mkdir(exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES, "hour_avg": hour_avg}, MODELS / "model.joblib")
    (MODELS / "metrics.json").write_text(json.dumps(metrics, indent=2))
    importance.to_csv(MODELS / "importance.csv", index=False)
    out = test_df[["ts_local", "date_local", "hour", "intensity", "forecast",
                   "baseline_yesterday", "baseline_hour_avg"]].copy()
    out.index.name = "ts_utc"
    out.to_csv(MODELS / "test_predictions.csv")
    return metrics, importance


def load_artifacts():
    bundle = joblib.load(MODELS / "model.joblib")
    metrics = json.loads((MODELS / "metrics.json").read_text())
    importance = pd.read_csv(MODELS / "importance.csv")
    preds = pd.read_csv(MODELS / "test_predictions.csv", parse_dates=["ts_utc"])
    preds["ts_utc"] = pd.to_datetime(preds["ts_utc"], utc=True)
    preds["date_local"] = pd.to_datetime(preds["date_local"]).dt.date
    return bundle, metrics, importance, preds


def forecast_tomorrow(bundle) -> tuple[pd.DataFrame, dict]:
    """LIVE mode: forecast tomorrow (US Eastern) from the latest EIA API data and the
    Open-Meteo weather forecast. Returns a 24-row frame (index = local hour) and info."""
    live = data.fetch_live_pjm(days=10)
    grid = data.load_grid()
    hist = pd.concat([grid.loc[grid["ba"] == "PJM", ["ts_utc", "intensity"]],
                      live[["ts_utc", "intensity"]]]).dropna()
    hist = hist.drop_duplicates("ts_utc", keep="last").set_index("ts_utc")["intensity"].sort_index()

    today = pd.Timestamp.now(tz=TZ).normalize()
    tomorrow = today + pd.Timedelta(days=1)
    idx = pd.date_range(tomorrow, tomorrow + pd.Timedelta(days=1), freq="h", inclusive="left").tz_convert("UTC")
    weather = data.fetch_weather_forecast(past_days=1, forecast_days=3)
    try:
        demand = data.fetch_live_demand_forecast(days=3)
        # EIA publishes tomorrow's forecast late in the day; until then reuse the
        # same-hour forecast from today.
        demand = demand.reindex(demand.index.union(idx))
        demand = demand.fillna(demand.shift(24, freq="h").reindex(demand.index))
    except Exception:
        demand = None
    X = make_features(hist, idx, weather, demand, live=True)
    X["forecast"] = bundle["model"].predict(X[bundle["features"]])
    X["baseline"] = X["lag_24h"]
    day = X.set_index("hour")[["forecast", "baseline"]]
    info = {"date": tomorrow.date(), "latest_data_utc": hist.index.max(),
            "lag_filled": bool(hist.reindex(idx - pd.Timedelta(hours=24)).isna().any()),
            "demand_forecast_used": demand is not None and X["demand_forecast"].notna().any()}
    return day, info


if __name__ == "__main__":
    metrics, importance = train()
    print(f"train {metrics['train_start']} .. {metrics['train_end']} ({metrics['train_hours']:,} h)")
    print(f"test  {metrics['test_start']} .. {metrics['test_end']} ({metrics['test_hours']:,} h), "
          f"mean intensity {metrics['test_mean_intensity']:.1f} gCO2/kWh\n")
    table = pd.DataFrame(metrics["models"]).T
    print(table.round(3).to_string())
    print(f"\nimprovement vs same-hour-yesterday: {metrics['improvement_vs_yesterday_pct']:.1f}%")
    print(f"improvement vs hour-of-day average: {metrics['improvement_vs_hour_avg_pct']:.1f}%")
    print("\npermutation importance (MAE increase, gCO2/kWh):")
    print(importance[["feature", "importance", "std"]].round(2).to_string(index=False))
