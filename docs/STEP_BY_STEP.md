# USVI Ocean Conditions: Step-by-Step Guide

Portfolio project 03 · Crucian Data Works · Roger Simon

This guide walks through the project in the order it was built. Each step says what the goal is, why it is done that way, the command to run, and what you should see. Follow it from top to bottom and you can rebuild the whole thing yourself and explain every decision in an interview or a client meeting.

Sources: [NOAA Tides and Currents](https://api.tidesandcurrents.noaa.gov/api/prod/), [NOAA Coral Reef Watch](https://coralreefwatch.noaa.gov/product/vs/gauges/usvi.php) and the [CARICOOS ERDDAP server](https://dm3.caricoos.org/erddap/). The project is an independent analysis, not an official product of those agencies, and not for navigation or emergency decisions.

---

## The big picture

Projects 01 and 02 refresh weekly or monthly, from one source each. This one is closer to a real production pipeline:

- **Three independent sources**, each with its own format, update rhythm and failure modes.
- **Near real time**: the tide gauges post every 6 minutes, so the pipeline runs every 3 hours.
- **Data that changes after it arrives**: NOAA first publishes "preliminary" water levels, then replaces them with "verified" ones 1–2 months later.
- **Sensors that go quiet**: the wave buoy has sent nothing since July 2026 and one thermometer stopped in March. The pipeline has to notice that on its own and say so.
- **Alerts**: when something needs a human (bleaching heat stress, flooding, a dead feed, a failing collector) it opens a GitHub issue, and closes it again when the condition clears.

```
NOAA CO-OPS (tides) ─────► 1 collect ─┐
NOAA Coral Reef Watch ───► 2 collect ─┼─► Parquet lake ─► 4 load DuckDB ─► 5 dbt models + tests
CARICOOS buoy VI1 ───────► 3 collect ─┘   (history)                              │
                                                     dashboard ◄─ 6 export JSON ◄─┤
                                                 GitHub issues ◄─ 7 sync alerts ◄─┘
```

### Final results (first full build, 19 November 2026)

| Measure | Result |
|---|---|
| Hourly water levels, 4 gauges since January 2016 | 360,600 (verified where NOAA has released it, preliminary after) |
| 6-minute readings | 57,601 (the first run fetches 60 days; the lake keeps everything after that) |
| Tide predictions | 382,384 hourly values, running 7 days ahead |
| Water temperature at the gauges | 256,799 hourly values |
| Coral heat stress | 107,054 daily values, 7 stations, since 1 January 1985 |
| Buoy VI1 | 363,431 wave and ocean readings since 15 April 2011 |
| Parquet lake on disk | about 6–7 MB |
| dbt | 3 seeds, 18 models, 44 data tests, all passing |
| Full pipeline run (incremental) | about 30 seconds |

What it found on the first run:

- The Virgin Islands are at **Bleaching Alert Level 4** with 16.3 degree heating weeks (18 Nov 2026). Only 2024 (22.3) and 2023 (18.7) peaked higher since satellite records began in 1985.
- All four gauges read **19–23 cm above their tide predictions**, and every complete year since 2016 averaged 6–12 cm above the 1983–2001 mean sea level that the tide tables are built on.
- **Buoy VI1 has been offline since 2 July 2026**, and the **Charlotte Amalie thermometer stopped on 20 March 2026**. Both became automatic alerts.
- NOAA's hand-verified water levels run through 31 October 2026, about three weeks behind.

---

## Step 0: Set up your machine

**Goal:** a working Python environment with the tools installed.

```bash
cd usvi-ocean-conditions
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
dbt --version                      # should list dbt-core and the duckdb adapter
```

| Tool | Job in this project |
|---|---|
| `requests` | Talks to the three agencies over HTTP |
| `pandas` | Holds each download as a table while we clean it |
| `duckdb` | Reads and writes Parquet files, and is the warehouse. No server |
| `dbt` | Runs the SQL models in the right order and tests the results |

### Project layout

```
usvi-ocean-conditions/
├── run_pipeline.py              runs steps 1-7 in order
├── pipeline/
│   ├── common.py                shared helpers: polite HTTP, upsert, health tracking
│   ├── step1_tides.py           NOAA CO-OPS tide gauges
│   ├── step2_coral.py           NOAA Coral Reef Watch
│   ├── step3_buoy.py            CARICOOS buoy VI1
│   ├── step4_load.py            lake -> DuckDB raw tables
│   ├── step6_export.py          marts -> dashboard JSON
│   └── step7_alerts.py          marts -> GitHub issues
├── lake/                        Parquet files (not in git - see Step 8)
├── warehouse/ocean.duckdb       rebuilt every run (not in git)
├── dbt/                         models, tests, seeds
├── dashboard/                   the web page
└── .github/workflows/refresh.yml   the 3-hourly schedule
```

---

## Step 1: Collect the tides

**Goal:** water level, predictions and water temperature for the four USVI gauges, plus each gauge's datums and flood levels.

| Station | Name | Island |
|---|---|---|
| 9751639 | Charlotte Amalie | St. Thomas |
| 9751381 | Lameshur Bay | St. John |
| 9751364 | Christiansted Harbor | St. Croix |
| 9751401 | Lime Tree Bay | St. Croix |

All four come from one service, the [NOAA CO-OPS data API](https://api.tidesandcurrents.noaa.gov/api/prod/). A request looks like this:

```
https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?station=9751364
  &product=water_level&datum=MHHW&units=metric&time_zone=gmt&format=json
  &begin_date=20261101&end_date=20261119
```

### Key ideas

**One reference level for everything.** Every height is asked for in metres above **MHHW** (mean higher high water: the average of each day's higher high tide). Zero means "an ordinary high tide". Flood levels, predictions and observations are then directly comparable.

**Two kinds of water level.**

| Product | Arrives | Reviewed? | Stored as |
|---|---|---|---|
| `water_level` (6-minute) | within minutes | No ("preliminary", quality letter `p`) | `tide_6min` |
| `hourly_height` | 1–2 months later | Yes ("verified") | `tide_hourly` |

We keep both and let dbt pick the best one for each hour (Step 5).

**Incremental loading with a watermark.** On each run the collector looks up the newest timestamp already in the lake for that station and product (the "watermark") and asks only for data after it, minus an overlap:

| Product | Chunk size per request | Overlap | Why the overlap |
|---|---|---|---|
| 6-minute water level | 30 days | 2 days | NOAA fills gaps and corrects recent values |
| Verified hourly | 364 days | 75 days | verified data is released in monthly batches |
| Predictions | — | — | always refetched to 7 days ahead |
| Water temperature | — | 3 days | late values |

The first run has no watermark, so it backfills: verified hourly data from January 2016, 6-minute data for the last 60 days. NOAA limits how much you can ask for at once, which is why long ranges are split into chunks.

**Being polite.** The first build hit HTTP 403 from NOAA after many fast requests. `common.get()` now waits 0.6 seconds before every request and retries 403, 429 and 5xx errors after 5, 15 and 45 seconds. Other 4xx errors (a real mistake in the request) fail immediately. A "No data was found" reply is treated as an empty result, not an error.

**Flood levels.** The station metadata endpoint (`.../mdapi/prod/webapi/stations/{id}.json?expand=datums,floodlevels&units=metric`) returns datums and NOAA's flood levels. One trap: flood levels are heights above the **station datum** (the gauge's own zero), not above MHHW. We store both and convert in dbt.

```bash
python pipeline/step1_tides.py
```

You should see one line per station, for example `9751364: tide_6min +240, tide_hourly +0, tide_predictions +24, water_temp_hourly +24`.

---

## Step 2: Collect coral heat stress

**Goal:** daily bleaching heat stress for the territory since 1985.

NOAA Coral Reef Watch (CRW) estimates sea surface temperature from satellites and publishes, for each "virtual station":

- **HotSpot**: how far today's temperature is above the warmest normal month (°C).
- **Degree Heating Weeks (DHW)**: HotSpots of at least 1 °C added up over the last 12 weeks. Bleaching is likely from about 4 DHW, and severe, widespread bleaching and coral death from 8.
- **Bleaching Alert Area (BAA)**: 0 No stress, 1 Watch, 2 Warning, 3–7 Alert Levels 1–5.

We read one regional station for the whole territory and six 5 km single-pixel stations (Southwest and North St. Thomas, South and East St. John, West and Northeast St. Croix). Each is a plain-text file with the full history:

```
https://coralreefwatch.noaa.gov/product/vs/data/usvi.txt
https://coralreefwatch.noaa.gov/product/vs_single_pixel_exp/data/AtlanticOcean_Caribbean_VirginIslands_WestStCroix.txt
```

### Key idea: conditional requests

CRW updates once a day but we run every 3 hours. Downloading seven full files eight times a day would be wasteful. The collector remembers each file's `Last-Modified` header (in `lake/_state/http_cache.json`) and sends it back as `If-Modified-Since`. If the file has not changed, the server answers `304 Not Modified` with no body, and the collector records "not modified since last run".

```bash
python pipeline/step2_coral.py
```

---

## Step 3: Collect the buoy

**Goal:** offshore waves, water temperature and salinity from CARICOOS buoy VI1 (NDBC 41052), moored south of St. John.

CARICOOS serves its data through **ERDDAP**, a standard scientific data server that answers queries in the URL like a small database:

```
https://dm3.caricoos.org/erddap/tabledap/VI1_waves_merged.csv
  ?time,significant_wave_height,significant_wave_height_qc_agg&time>=2026-06-29T00:00:00Z
```

Every value carries a **QARTOD quality flag**: 1 pass, 2 not evaluated, 3 suspect, 4 fail, 9 missing. The collector stores the flag; dbt keeps only 1 and 2.

**When the buoy is offline.** ERDDAP answers 404 when there is nothing after the time you asked for. Since the buoy stopped on 2 July 2026, that is what every run gets. The collector treats a 404 after the watermark as "healthy, no new rows" and records the newest time on the server. Whether the feed is stale is a separate question that dbt answers (Step 5), so a quiet sensor becomes a data alert, not a pipeline failure.

```bash
python pipeline/step3_buoy.py
```

---

## Step 3½: How the lake works

All three collectors save through one function, `upsert()` in `pipeline/common.py`. It is the most important piece of plumbing in the project.

**Partitioned Parquet.** Each dataset is a folder of Parquet files split by station and year (and month for the 6-minute data):

```
lake/tide_hourly/station=9751364/year=2026/data.parquet
lake/coral_daily/station=usvi/year=2026/data.parquet
```

This is called hive partitioning. A run that brings in two days of data rewrites only the files for those two days' partitions, not the whole history.

**Idempotent merges.** "Idempotent" means running the same thing twice gives the same result as running it once. For each partition, `upsert()` reads the existing file, adds the new rows, and keeps one row per key (for example station + time), with the newly downloaded copy winning. Overlap windows and re-runs can therefore never create duplicates, and NOAA's corrections replace old values.

**Atomic writes.** The merged partition is written to a `.tmp` file and then swapped in with `os.replace`. If the job is killed halfway through a write, the old file is still intact.

**A bug the tests caught.** The first dbt build failed a uniqueness test: 40 duplicate predictions and 36 duplicate hourly heights, all on the last day of a 364-day chunk. When a backfill is split into chunks, each chunk's end time is the next chunk's start time, so the boundary hour arrives twice in one batch, and the merge only removed duplicates between old and new rows, not within the new rows. The fix is one line in `upsert()` that drops duplicates inside the batch first, plus a one-off clean-up of the existing files. This is exactly what tests are for.

**Health tracking.** After every station or feed, `record_health()` writes the outcome to `lake/_state/health.json`: last attempt, last success, rows added, consecutive failures and the last error. Each run is also appended to `lake/_state/runs.csv`.

---

## Step 4: Load into DuckDB

```bash
python pipeline/step4_load.py
```

DuckDB reads the Parquet folders directly (`read_parquet('lake/tide_hourly/**/*.parquet', hive_partitioning = true)`) and creates one `raw.*` table per dataset, plus `raw.source_health` from the health file. The database is rebuilt from the lake every run, so it never drifts from the files.

One detail: DuckDB reads the `station=9751364` folder name as a number. The staging models cast it back to text so station IDs match everywhere.

---

## Step 5: Model and test with dbt

```bash
cd dbt
dbt build --profiles-dir .
```

`dbt build` loads the seed files, builds every model in dependency order, and runs every test right after the table it checks. If an error-level test fails, everything downstream is skipped, so bad data never reaches the dashboard.

### Seeds (small reference tables kept in git)

| Seed | What it holds |
|---|---|
| `stations.csv` | Every station: ID, name, island, kind (gauge, coral region, coral pixel, buoy) |
| `bleaching_levels.csv` | CRW alert codes 0–7 with labels |
| `feed_expectations.csv` | How old each feed's newest value may be before it counts as stale |

The freshness rules are a business decision, so they live in a seed anyone can read and change: 6 hours for 6-minute water levels, 24 hours for water temperature, 72 hours for coral data, 48 hours for the buoy, and 100 days for verified tides (NOAA reviews them by hand).

### The layers

| Layer | Models | Job |
|---|---|---|
| Staging (views) | `stg_tide_6min`, `stg_tide_hourly`, `stg_tide_predictions`, `stg_water_temp`, `stg_tide_stations`, `stg_coral_daily`, `stg_buoy_waves`, `stg_buoy_ocean`, `stg_source_health` | Rename, cast, decode flags, drop failed quality checks |
| Intermediate | `int_water_level_hourly` | One water level per gauge per hour, verified where possible |
| Marts (tables) | `fct_water_level_hourly`, `mart_water_level_daily`, `mart_tide_recent`, `mart_sea_level_annual`, `mart_coral_daily`, `mart_coral_annual`, `mart_feed_freshness`, `mart_alerts` | What the dashboard and the alerts read |

### Key idea 1: verified data wins

`int_water_level_hourly` takes every verified hourly value, then adds the preliminary 6-minute reading taken exactly on the hour for hours NOAA has not verified yet (an "anti join": rows with no match in the other table). That is how NOAA itself defines the hourly height, so the two line up. An `is_verified` column says which is which. When NOAA releases a new month of verified data, the next run swaps it in automatically.

### Key idea 2: flood thresholds on the same scale

`stg_tide_stations` converts NOAA's flood levels from "above the station's zero" to "above MHHW" by subtracting MHHW. Charlotte Amalie and Lime Tree Bay have published minor flood levels (0.51 m above MHHW). Christiansted Harbor and Lameshur Bay do not, so we use NOAA's national rule for high-tide flooding: 0.04 × the tide range + 0.50 m ([Sweet et al. 2018, NOAA Technical Report NOS CO-OPS 086](https://tidesandcurrents.noaa.gov/publications/techrpt86_PaP_of_HTFlooding.pdf)). The rule's two numbers are dbt variables in `dbt_project.yml`, and a `minor_flood_source` column records which method each gauge uses.

A test checks the rule against the two gauges that do have a published level. Both match it to the millimetre (NOAA evidently set them with the same rule), which justifies using it at the other two.

### Key idea 3: residuals and the 1983–2001 baseline

`fct_water_level_hourly` adds `residual_m` = observed − predicted. Predictions only know about the moon and sun. Everything else (wind, swell, warm water expanding, sea level rise) shows up in the residual.

NOAA's datums, and therefore its tide tables, are tied to the 1983–2001 period (the "National Tidal Datum Epoch"). `mart_sea_level_annual` converts each year's mean water level to "metres above 1983–2001 mean sea level". Every complete year since 2016 sits 6–12 cm above it. Years with less than 90% of hours are flagged incomplete and left off the chart.

### Key idea 4: freshness is not the same as success

`mart_feed_freshness` compares the newest value of each feed and station with the time of the run. A collector can succeed (the request worked) while the feed is stale (nothing new came back), as the buoy has done since July. Keeping those two questions separate is what lets the page say "the pipeline is fine, the sensor is not".

### Key idea 5: alerts as a table

`mart_alerts` lists every condition that needs attention right now, one row each, with a stable key:

| Key | Raised when | Severity |
|---|---|---|
| `bleaching:usvi` | Regional 7-day maximum alert is Alert Level 1 or higher | high from Alert Level 3, otherwise medium |
| `flood:<station>` | Any 6-minute reading in the last 24 hours reached the minor flood level | high |
| `stale:<feed>:<station>` | `mart_feed_freshness` says stale | low |
| `collector:<source>:<feed>` | 4 runs in a row failed (12 hours) | medium |

Because the logic is SQL, it is tested and documented like everything else, and the dashboard and the GitHub issues read the same table.

### Tests

The rule used throughout: **error tests guard correctness, warn tests flag availability.** A duplicate or an impossible value stops the run. A sensor going quiet is reported (by a warning and by the alerts) but never blocks the rest of the page from updating.

| Kind | Examples |
|---|---|
| Uniqueness | one row per station and time in every time series; one row per alert key |
| Not null | water level, station ID, flood threshold, alert label |
| Ranges | water level −1.5 to 2.5 m; predictions −1 to 1 m; flood level 0.2–1.0 m; sea surface temperature 20–34 °C; DHW 0–40; waves 0–15 m; residual −1 to 1.5 m |
| Accepted values | quality letter `p` or `v`; alert levels 0–7; station kinds; alert severities |
| `assert_predictions_run_ahead` (error) | every gauge has predictions at least 2 days past its newest reading |
| `assert_flood_levels_match_national_rule` (error) | published flood levels agree with NOAA's rule within 3 cm |
| `assert_some_gauge_is_reporting` (error) | at least one gauge reported in the 12 hours before the run |
| `assert_bleaching_levels_follow_dhw` (warn) | recomputes CRW's alert level from its own published rule and compares |
| Freshness (warn) | no gauge's 6-minute feed is stale |

The bleaching test is a nice example of checking a source against itself. CRW's rule: HotSpot ≤ 0 is No stress; under 1 °C is Watch; at least 1 °C with DHW under 4 is Warning; then Alert Levels 1–5 at 4, 8, 12, 16 and 20 DHW. The first version flagged two days out of 107,054. Both had DHW printed as 7.996 and 19.997: CRW works from unrounded values, so a number printed just under a boundary can belong on either side. The test now accepts either reading, and passes.

---

## Step 6: Export for the dashboard

```bash
python pipeline/step6_export.py
python -m http.server 8802 --directory dashboard
# open http://localhost:8802
```

The page is static: no server and no database, just HTML, CSS, JavaScript and two JSON files.

| File | Size | Contents |
|---|---|---|
| `summary.json` | about 70 KB | current readings, coral, sea level, temperature, buoy, alerts, freshness, health |
| `tides.json` | about 300 KB | 10 days of 6-minute readings and 13 days of predictions per gauge |

The large tide arrays sit in their own file so the first paint stays fast.

---

## Step 7: Alert issues on GitHub

```bash
python pipeline/step7_alerts.py        # without GH_TOKEN: dry run, prints what it would do
```

For each row in `mart_alerts`, the script looks for an open issue labelled `ocean-alert` whose title starts with the alert key in brackets, for example `[bleaching:usvi] Coral bleaching heat stress: Bleaching Alert Level 4`.

| Situation | Action |
|---|---|
| New alert, no open issue | Open one, assigned to the repository admin. GitHub emails them |
| Alert still active, same title | Nothing. No repeat emails every 3 hours |
| Alert still active, title changed (for example Alert Level 3 → 4) | Rename the issue and add a comment |
| Open issue whose alert has gone | Comment "cleared" and close it |

This "one key, one issue" design is called deduplication. A sensor that is offline for months produces one email, not 700.

---

## Step 8: Run everything with one command

```bash
python run_pipeline.py            # all 7 steps
python run_pipeline.py --from 4   # rebuild from the lake without downloading
```

Steps 1–3 talk to three different agencies, and one of them being down must not stop the other two. So a collector failure is recorded (it shows up in source health and, after 4 in a row, as an alert) and the run carries on. The run fails only if every collector fails, or if anything from step 4 on fails.

---

## Step 9: Schedule it every 3 hours

`.github/workflows/refresh.yml` runs at 17 minutes past every third hour (UTC). Each run:

1. Downloads the lake from a GitHub release called `lake`.
2. Runs the pipeline.
3. Uploads the updated lake back to the same release, replacing the old file.
4. Once a day (the first automatic run of the day, or any manual run) commits `dashboard/data/summary.json`.
5. Uploads the dashboard to cruciandataworks.com over FTP, once the FTP secrets exist.
6. If anything failed, opens or updates one "refresh failed" issue.

**A backup for GitHub's scheduler.** GitHub can take a long time to start firing schedules in a new repository, and it sometimes drops runs. So every run that was not started by the schedule ends with a small second job, `next-run`. That job waits until 3 hours after the run began and then starts the next run itself (`chained=true`). It first checks whether any newer run has started in the meantime (a scheduled run, a manual run or another chain); if one has, it stops. That keeps only one chain going, and once the schedule fires, the chain ends on its own. The wait runs in its own job so it never blocks the refresh. It uses runner time, which is free in a public repository. Set the repository variable `CHAIN_RUNS` to `false` to turn the backup off.

**Why the lake is not in git.** It changes every 3 hours. Committing it would add thousands of binary versions to the repository's history. A release asset is a single file that gets replaced, so the repository stays small.

**Self-healing.** If the release file is ever missing or deleted, the collectors find an empty lake, have no watermark, and backfill the full history from the agencies. We tested this by running the collectors against an empty folder: the full history came back in about 2½ minutes with the same row counts as the original lake (the 6-minute table differs by a few rows only because its 60-day starting window had moved on).

**Why the daily commit.** GitHub pauses scheduled workflows in repositories with no commits for 60 days. One small commit a day prevents that, and gives a day-by-day history of the summary.

**Concurrency.** `concurrency: refresh` makes a new run wait for the previous one to finish, so two runs can never write the lake at the same time.

**Testing the failure alert.** In GitHub: Actions → Ocean conditions refresh → Run workflow → tick "Fail on purpose".

### Setup checklist in GitHub

| Setting | Where | Value |
|---|---|---|
| `FTP_SERVER`, `FTP_USERNAME`, `FTP_PASSWORD` | Settings → Secrets and variables → Actions → Secrets | Same as projects 01 and 02 |
| `FTP_SERVER_DIR` | Variables | `/public_html/projects/ocean-conditions/` |
| `ALERT_ASSIGNEE` (optional) | Variables | GitHub user who should get alert emails |

---

## Talking about this project

**In one sentence:** "A tested, self-healing pipeline that pulls tides, coral heat stress and buoy data for the Virgin Islands from three agencies every three hours, and opens a ticket when the reefs are under heat stress, the water reaches flood level or a sensor goes quiet."

Points worth making:

- **Incremental and idempotent.** Watermarks and overlap windows mean each run downloads minutes of data, not years, and re-runs never duplicate anything. That is what makes running every 3 hours cheap.
- **Late-arriving data.** Verified tides replace preliminary ones automatically, and the table says which is which.
- **Partial failure.** One agency being down does not stop the others. Collector failures and stale feeds are tracked separately and surface as alerts, not crashes.
- **Tests caught a real bug** (duplicate boundary hours from chunked backfills) and checked a source against its own published rules.
- **Operations.** Deduplicated alert issues, a failure alert, a keep-alive commit, and a lake that can rebuild itself from scratch.

For a client: the same pattern fits any business that depends on outside data feeds, such as marina and harbour operators watching water levels, dive and snorkel operators watching reef stress, hotels and insurers watching flooding, or utilities watching any sensor network.

---

## Publishing to cruciandataworks.com

The workflow uploads the `dashboard/` folder to `/public_html/projects/ocean-conditions/` on Hostinger after every successful run, so the live page is never more than about 3 hours behind. A Project 03 card on the homepage links to it, following the same pattern as projects 01 and 02.
