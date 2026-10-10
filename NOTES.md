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
- Uncertainty band: raw 10%/90% quantile boosting models covered only 52% of test hours
  (overconfident). Added split-conformal widening (CQR): quantile models refit without the
  last 30 training days, the miss distance on those days sets a pad (4.8 gCO2/kWh) added to
  both sides. Test coverage after calibration: 75%, reported as-is in the app. The test
  set is never used for calibration.
- Linear regression baseline: median imputation + standardization + OLS on the same
  features (OLS cannot take NaNs). Its MAE is close to boosting (9.0 vs 8.7) but it picks
  the cleanest window far less well (15% vs 31% exact hits).
- Confidence line: "High confidence" when the mean of the 90% upper bound over the chosen
  window is below the day's median forecast.
- Animations: CSS keyframes in one injected style block; count-up cards are three small
  components.html iframes (one per column, so they stack on mobile). Plotly charts get
  layout.transition (500 ms cubic-in-out) and stable keys. Not confirmed: whether Streamlit
  updates the chart in place on a date change (needed for the transition to show); in one
  test the chart element was rebuilt. Plotly's JS transitions are not covered by the CSS
  prefers-reduced-motion rule; the count-up cards do check it.
- Final polish: Streamlit's menu, toolbar, and header are hidden with CSS. Plotly
  transitions are applied only to charts that change with user input (Tomorrow, Check the
  AI, Play the day), not to the static comparison and importance charts.
- README figures: the EIA "about 31% of U.S. energy-related CO2" (electric power sector,
  2022) was checked on the linked EIA FAQ. The "NJ warmed about 4°F since 1900, about twice
  the global average" figure is as provided and attributed to the Office of the NJ State
  Climatologist (Rutgers); its home page was checked to load but does not state the figure.
- Photo credit is still unknown; the footer and README say "Princeton University campus"
  instead of inventing a source.
- Verification caveat: the in-app browser reported the page as hidden, which pauses
  animation frames, so some screenshots showed stale or mid-animation frames. Final states
  were confirmed through the DOM (animations finished, chart data correct, no exceptions,
  no horizontal scroll at 400 px).
- Redesign (tag pre-nature marks the version before): background photo "Trees on forest
  with sun rays" by Sebastian Unrau on Unsplash (Unsplash License; page
  https://unsplash.com/photos/trees-on-forest-with-sun-rays-sp-p7uuT0tw), downloaded at
  1920 px and re-encoded to 317 KB. The Princeton photo (unknown license) was removed from
  the repo.
- Parallax: Streamlit scrolls `section[data-testid="stMain"]`, not the window. A
  zero-height components.html script moves a fixed background layer at 30% of the scroll
  and sizes it to viewport + 30% of the scroll range. Without the script (or with reduced
  motion) the background simply stays fixed while content scrolls.
- Panels use `st.container(key="panel_*")`, which Streamlit exposes as a `st-key-panel_*`
  class for styling. The fixed background sits at z-index -1 inside the content's stacking
  context so panel backgrounds paint above it.
- Fonts: Google Fonts Fraunces (600/700) and Nunito Sans (400/600/700) via @import, also set
  as theme font/headingFont so tables and widgets use them; Plotly layout fonts match.
- Live data is fetched in a background thread with a 6 s wait. If EIA or Open-Meteo is
  slow, the page shows the fallback day instead of blocking, and the next rerun picks up
  the finished result (cached 30 min). Added after the EIA API stalled page load during
  testing.
- AI message bubbles: five "CleanHour AI" bubbles (Tomorrow answer + confidence, Check the
  AI verdict, Scheduler savings, Where vs when takeaway, How the AI works explanation). Text
  is built from model outputs with f-strings, not generated by a chatbot. Typing uses
  st.write_stream (~25 ms/word, capped ~1.5 s) after a 400 ms dots indicator. Typing all five
  on first load would add ~8 s, so only the Tomorrow bubble types; all bubbles are marked as
  shown in st.session_state and render instantly on every rerun. The headline itself is HTML
  (green time range), so it appears at once and only the sentences after it type.
- Animated charts: Tomorrow, Check the AI, Where vs when, and Feature importance are ECharts
  5.5.1 (jsDelivr; cdnjs does not host 5.5.1) in components.html iframes. Each starts when
  scrolled into view (IntersectionObserver), plays once with cubic-out easing, follows
  prefers-reduced-motion, and resizes with its frame. The forecast chart stages the line
  draw (1.2 s), then the 80% range fades in, then the cleanest window appears. It uses a
  category hour axis because ECharts only stacks the band on category or time axes. If a
  chart fails to build in Python, the Plotly version is shown; if the CDN is unreachable in
  the browser, the frame shows a short "could not load" message. "Play the day" stays Plotly.
- Not verified: how the motion looks on screen. The in-app browser kept the page in a
  hidden state that pauses animation frames, so the chart sequences, typing, and parallax
  were confirmed through the DOM and chart state (series loaded, band opacity reached 1,
  window markArea added, background translateY = 30% of scroll), not by watching them.
