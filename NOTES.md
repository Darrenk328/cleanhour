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
