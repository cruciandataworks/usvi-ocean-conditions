# USVI Ocean Conditions

Portfolio project 03 · [Crucian Data Works](https://cruciandataworks.com) · Roger Simon

A small production data pipeline for the sea around the U.S. Virgin Islands: tides and high-tide flooding at the four NOAA gauges, coral bleaching heat stress since 1985, water temperature, and the CARICOOS wave buoy south of St. John. It runs every 3 hours on GitHub Actions, tests every table before publishing, and opens a GitHub issue when something needs attention.

Live dashboard: https://cruciandataworks.com/projects/ocean-conditions/

```
NOAA CO-OPS ─┐
Coral Reef   ├─► 1-3 collectors ─► Parquet lake ─► 4 DuckDB ─► 5 dbt models + tests ─► 6 dashboard JSON
Watch        │   (incremental,     (partitioned,                                    └► 7 alert issues
CARICOOS ────┘    retries, health)  idempotent)
```

## What it shows

- Water level every 6 minutes against NOAA's tide prediction, with the minor flood level and a 3-day forecast
- How far the sea is running above the tide tables right now, and yearly mean sea level against the 1983–2001 baseline
- Coral heat stress (degree heating weeks) this year against the 2005, 2023 and 2024 bleaching years, and by reef area
- Water temperature at the gauges, buoy status and 15 years of wave history
- A freshness table that flags any feed that has gone quiet

## Data engineering features

| Feature | Where |
|---|---|
| Incremental loads with a watermark and overlap window | `pipeline/step1_tides.py`, `step3_buoy.py` |
| Conditional HTTP requests (If-Modified-Since) | `pipeline/step2_coral.py` |
| Idempotent upserts into a hive-partitioned Parquet lake, atomic writes | `pipeline/common.py` |
| Polite pacing and exponential backoff on 403/429/5xx | `pipeline/common.py` |
| Per-feed health tracking (last success, failures in a row) | `lake/_state/health.json` → `raw.source_health` |
| Verified data replaces preliminary data automatically | `dbt/models/intermediate/int_water_level_hourly.sql` |
| Freshness rules per feed | `dbt/seeds/feed_expectations.csv`, `mart_feed_freshness` |
| 44 dbt tests: error tests guard correctness, warn tests flag availability | `dbt/models/**/_*.yml`, `dbt/tests/` |
| Alert issues that open, update and close themselves | `pipeline/step7_alerts.py` |
| Lake stored as a release asset, self-healing backfill if lost | `.github/workflows/refresh.yml` |

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_pipeline.py                     # first run backfills all history
python -m http.server 8802 --directory dashboard
```

The full walkthrough is in [docs/STEP_BY_STEP.md](docs/STEP_BY_STEP.md).

## Sources

- [NOAA Tides and Currents (CO-OPS) data API](https://api.tidesandcurrents.noaa.gov/api/prod/) – water level, predictions, water temperature, datums and flood levels
- [NOAA Coral Reef Watch virtual stations](https://coralreefwatch.noaa.gov/product/vs/gauges/usvi.php) – daily heat stress since 1985
- [CARICOOS ERDDAP](https://dm3.caricoos.org/erddap/) – buoy VI1 (NDBC 41052) waves, temperature and salinity
- Minor flood rule where NOAA publishes no local level: Sweet et al. (2018), [NOAA Technical Report NOS CO-OPS 086](https://tidesandcurrents.noaa.gov/publications/techrpt86_PaP_of_HTFlooding.pdf)

This is an independent analysis, not an official product of NOAA or CARICOOS, and not for navigation or emergency decisions.
