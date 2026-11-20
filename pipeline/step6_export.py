"""Step 6 - Export: write small JSON files the website dashboard reads.

The dashboard is a static web page (no server, no database), so we pre-compute what it
needs from the marts and save it next to it. Queries are sorted and numbers rounded, so
identical data gives identical files.

Output: dashboard/data/*.json
"""
import json
from datetime import date, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "warehouse" / "ocean.duckdb"
OUT = ROOT / "dashboard" / "data"

QUERIES = {
    # newest 6-minute reading per gauge, with the prediction for that moment
    "gauges": """
        with latest as (
            select * from staging.stg_tide_6min
            qualify row_number() over (partition by station_id order by time_utc desc) = 1),
        wt as (
            select * from staging.stg_water_temp
            qualify row_number() over (partition by station_id order by time_utc desc) = 1),
        today as (
            select station_id, max(water_level_m) as max_24h from staging.stg_tide_6min
            where time_utc >= (select max(time_utc) from staging.stg_tide_6min) - interval 24 hour
            group by 1)
        select s.station_id as id, s.name, s.island, s.lat, s.lon,
               strftime(l.time_utc, '%Y-%m-%dT%H:%M:%SZ') as time,
               round(l.water_level_m, 3) as level, round(p.predicted_m, 3) as predicted,
               round(l.water_level_m - p.predicted_m, 3) as residual,
               round(t.max_24h, 3) as max_24h,
               s.minor_flood_m as minor_flood, s.minor_flood_source as flood_source,
               s.mhhw_above_msl_m,
               round(wt.water_temp_c, 2) as water_temp,
               strftime(wt.time_utc, '%Y-%m-%dT%H:%M:%SZ') as water_temp_time
        from staging.stg_tide_stations s
        left join latest l using (station_id)
        left join wt using (station_id)
        left join today t using (station_id)
        left join staging.stg_tide_predictions p
               on p.station_id = s.station_id and p.time_utc = date_trunc('hour', l.time_utc)
        order by s.lat desc""",
    # every reading of the last 10 days plus 3 days of predictions, as compact arrays
    "tides": """
        select station_id as id,
               list(strftime(time_utc, '%Y-%m-%dT%H:%MZ') order by time_utc) as t,
               list(round(water_level_m, 3) order by time_utc) as obs,
               list(round(predicted_m, 3) order by time_utc) as pred
        from marts.mart_tide_recent group by 1 order by 1""",
    "coral_latest": """
        select station_id as id, station_name as name, island, kind,
               strftime(obs_date, '%Y-%m-%d') as date, round(sst_c, 2) as sst,
               round(ssta_c, 2) as ssta, round(dhw, 2) as dhw, alert_level as level,
               alert_label as label, alert_short as short
        from marts.mart_coral_daily
        qualify row_number() over (partition by station_id order by obs_date desc) = 1
        order by kind desc, dhw desc""",
    # daily DHW for the regional station: this year against the two big bleaching years
    "coral_years": """
        select extract(year from obs_date)::int as year,
               list(dayofyear(obs_date) order by obs_date) as doy,
               list(round(dhw, 2) order by obs_date) as dhw,
               list(alert_level order by obs_date) as level
        from marts.mart_coral_daily
        where station_id = 'usvi' and extract(year from obs_date) in (2005, 2023, 2024, 2026)
        group by 1 order by 1""",
    "coral_annual": """
        select year::int as year, max_dhw, max_alert_level as max_level,
               days_alert_1_plus as days_a1, days_alert_2_plus as days_a2
        from marts.mart_coral_annual where station_id = 'usvi' order by year""",
    "sea_level": """
        select station_id as id, station_name as name, year::int as year,
               mean_above_epoch_msl_m as msl, hours, is_complete_year as complete,
               hours_above_minor_flood as flood_hours
        from marts.mart_sea_level_annual order by id, year""",
    # daily mean water temperature at the gauges for the last 13 months
    "water_temp": """
        select station_id as id,
               list(strftime(local_date, '%Y-%m-%d') order by local_date) as d,
               list(mean_water_temp_c order by local_date) as temp
        from marts.mart_water_level_daily
        where local_date >= current_date - interval 395 day and mean_water_temp_c is not null
        group by 1 order by 1""",
    "buoy": """
        with w as (select max(time_utc) as t from staging.stg_buoy_waves),
             o as (select max(time_utc) as t from staging.stg_buoy_ocean)
        select strftime(w.t, '%Y-%m-%dT%H:%M:%SZ') as last_waves,
               strftime(o.t, '%Y-%m-%dT%H:%M:%SZ') as last_ocean,
               (select round(wave_height_m, 2) from staging.stg_buoy_waves order by time_utc desc limit 1) as last_wave_m,
               (select round(water_temp_c, 2) from staging.stg_buoy_ocean order by time_utc desc limit 1) as last_temp_c,
               (select strftime(min(time_utc), '%Y-%m-%d') from staging.stg_buoy_waves) as first_waves,
               (select count(*) from staging.stg_buoy_waves) as wave_rows
        from w, o""",
    "buoy_monthly": """
        select strftime(date_trunc('month', time_utc), '%Y-%m') as month,
               round(avg(wave_height_m), 2) as mean_wave, round(max(wave_height_m), 2) as max_wave
        from staging.stg_buoy_waves group by 1 order by 1""",
    "alerts": """
        select alert_key as key, category, severity, title, message, level,
               strftime(observed_at, '%Y-%m-%dT%H:%M:%SZ') as observed_at
        from marts.mart_alerts
        order by case severity when 'high' then 0 when 'medium' then 1 else 2 end, key""",
    "freshness": """
        select feed, dataset, station_id as id, station_name as name,
               strftime(latest_at, '%Y-%m-%dT%H:%M:%SZ') as latest, age_hours as age_h,
               max_age_hours as max_h, is_stale as stale
        from marts.mart_feed_freshness order by feed, id""",
    "health": """
        select source, feed, strftime(last_attempt, '%Y-%m-%dT%H:%M:%SZ') as last_attempt,
               strftime(last_success, '%Y-%m-%dT%H:%M:%SZ') as last_success,
               consecutive_failures as fails, last_error as error, detail
        from staging.stg_source_health order by source, feed""",
}

COUNTS = {
    "water_level_hours": "select count(*) from marts.fct_water_level_hourly",
    "six_minute_rows": "select count(*) from raw.tide_6min",
    "prediction_rows": "select count(*) from raw.tide_predictions",
    "water_temp_rows": "select count(*) from raw.water_temp_hourly",
    "coral_days": "select count(*) from raw.coral_daily",
    "buoy_rows": "select (select count(*) from raw.buoy_waves) + (select count(*) from raw.buoy_ocean)",
    "verified_through": "select strftime(max(time_utc), '%Y-%m-%d') from staging.stg_tide_hourly",
    "first_coral_date": "select strftime(min(obs_date), '%Y-%m-%d') from staging.stg_coral_daily",
}


def default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    data = {}
    for name, sql in QUERIES.items():
        rel = con.sql(sql)
        cols = rel.columns
        data[name] = [dict(zip(cols, r)) for r in rel.fetchall()]
    data["buoy"] = data["buoy"][0]
    checked = con.sql("select max(last_attempt) from staging.stg_source_health").fetchall()[0][0]
    meta = {"checked_at": checked.strftime("%Y-%m-%dT%H:%M:%SZ"),
            **{k: con.sql(q).fetchall()[0][0] for k, q in COUNTS.items()}}
    # the big tide arrays get their own file so the first paint stays light
    tides = data.pop("tides")
    files = {"summary.json": {"meta": meta, **data}, "tides.json": tides}
    for fname, obj in files.items():
        (OUT / fname).write_text(json.dumps(obj, default=default, separators=(",", ":")))
        print(f"  {fname}: {(OUT / fname).stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
