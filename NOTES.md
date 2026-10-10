# CleanHour build notes (decisions made without asking)

- Project lives in `Desktop/com/AI-ML` (own git repo + `.venv`). `Desktop/AI:ML` was
  empty and the later instruction said to work only in AI-ML, so it is unused.
- EIA bulk files used: 2025 Jan-Jun, 2025 Jul-Dec, 2026 Jan-Jun, 2026 Jul-Dec (partial,
  through 2026-10-10). Raw CSVs (~170 MB) are gitignored in `data/raw/`; cleaned
  `data/grid_hourly.csv` and `data/weather_pjm.csv` are committed so the app runs offline.
- Time convention: EIA reports hour-ending UTC. All tables use hour-START UTC
  (`ts_utc`), so local hour 13 means 1:00-2:00 PM. EIA API v2 `period` was verified to
  match the bulk CSV exactly on 223 overlapping PJM hours after the same shift.
- Fuel mapping: solar and wind include both "with" and "without integrated battery"
  columns. Storage (pumped, battery, other/unknown storage) is excluded from the
  intensity calculation because it shifts energy rather than generating it. Negative
  MW values are clipped to 0.
- Emission factors: IPCC AR5 lifecycle medians as specified. "Other" and "Unknown" fuel
  assumed 490 (gas-like). Geothermal (only CISO) was not in the spec; IPCC median 38 used.
- Weather: Open-Meteo ERA5 archive for history; the archive lags a few days, so the last
  ~2 weeks come from the Open-Meteo forecast API (`past_days=14`).
- Charts: a 3-hue categorical palette (green/orange/blue) failed the colorblind check,
  so no chart uses one. Green marks the focus series, near-black the actuals, gray the
  references and other grids, and line style also separates series.
- No GitHub remote URL was provided (placeholder text only) and `gh` is not logged in,
  so the push step will need the URL.
- Model features add two day-ahead-safe extras beyond the spec: yesterday's mean intensity
  and the last observed hour before midnight. "Last observed hour" turned out to be the
  most important feature in backtests.
- Honest result: the model cuts MAE by ~39% vs same-hour-yesterday, but its cleanest-window
  picks are only slightly better than persistence (31% vs 26% exact hits, similar regret).
  The hour-of-day average baseline overlaps the true window more often (80%) because it
  always picks the same midday block. PJM's within-day swing is small, which is the
  "where vs when" story.
- LIVE mode: EIA API data lags (latest hour is usually last night), so for tomorrow the
  24h lag falls back to the same hour on the latest available day, and "last observed hour"
  is staler than in the backtest. EIA's day-ahead demand forecast for tomorrow is usually
  not published yet; missing hours reuse today's same-hour forecast. Live accuracy is
  therefore expected to be worse than the backtest MAE.
- UI (pre-ui tag marks the version before this): tabs, Plotly charts, "Play the day"
  fuel-mix animation, hero banner. `st.plotly_chart(..., width="stretch")` is used instead
  of `use_container_width=True`, which Streamlit 1.65 deprecates; same effect.
- "Play the day" shows recent days with published fuel-mix data, since tomorrow's mix
  has not happened yet. It starts on the full day so it reads before Play is pressed.
- Chart source notes are linked captions under each chart (Plotly annotations below the
  legend were clipped on narrow screens).
- Hero photo `assets/princeton.jpg` came from the chat upload (800x534). Its source is
  unknown, so the footer credit reads "Princeton University campus" until a real
  source is supplied (`PHOTO_CREDIT` in app.py).
