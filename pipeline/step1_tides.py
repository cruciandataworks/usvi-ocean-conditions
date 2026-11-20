"""Step 1 - Tide gauges: water level, tide predictions and water temperature from NOAA
CO-OPS (Center for Operational Oceanographic Products and Services) for the four
USVI gauges.

    9751639  Charlotte Amalie, St. Thomas
    9751381  Lameshur Bay, St. John
    9751364  Christiansted Harbor, St. Croix
    9751401  Lime Tree Bay, St. Croix

API docs: https://api.tidesandcurrents.noaa.gov/api/prod/

Every number is stored in metres above MHHW (mean higher high water: the average of
each day's higher high tide). Zero means "an ordinary high tide"; the minor flood level
at these gauges is about +0.5 m.

Two kinds of water level:
  * water_level (6-minute, "preliminary"): available within minutes, not yet reviewed.
  * hourly_height ("verified"): reviewed by NOAA, published 1-2 months later.
dbt prefers verified values and falls back to preliminary ones.

Each run asks only for what is new since the last run (the "watermark"), plus an
overlap so late or revised values are picked up.
"""
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from common import as_utc, get, max_value, now_utc, record_health, upsert

API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
META = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{}.json"
STATIONS = ["9751639", "9751381", "9751364", "9751401"]
HISTORY_START = datetime(2016, 1, 1, tzinfo=timezone.utc)
BASE = {"units": "metric", "time_zone": "gmt", "format": "json", "application": "cruciandataworks.com"}

# product -> (lake dataset, request chunk, overlap re-fetched each run, extra params)
PRODUCTS = {
    "water_level":       ("tide_6min",        timedelta(days=30),  timedelta(days=2),  {"datum": "MHHW"}),
    "hourly_height":     ("tide_hourly",      timedelta(days=364), timedelta(days=75), {"datum": "MHHW"}),
    "predictions":       ("tide_predictions", timedelta(days=364), timedelta(days=1),  {"datum": "MHHW", "interval": "h"}),
    "water_temperature": ("water_temp_hourly", timedelta(days=364), timedelta(days=3), {"interval": "h"}),
}
FIRST_FETCH = {"water_level": timedelta(days=60)}  # 6-minute history: start with 60 days


def fetch(product, station, start, end, extra):
    params = {**BASE, **extra, "product": product, "station": station,
              "begin_date": start.strftime("%Y%m%d %H:%M"), "end_date": end.strftime("%Y%m%d %H:%M")}
    body = get(API, params).json()
    if "error" in body:
        msg = body["error"].get("message", "")
        if "No data was found" in msg:  # a gap (gauge down, product not offered) - not a failure
            return []
        raise RuntimeError(msg)
    return body.get("data") or body.get("predictions") or []


def to_frame(rows, product, station):
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time_utc"] = pd.to_datetime(df["t"], utc=True)
    df["value"] = pd.to_numeric(df["v"], errors="coerce")
    df = df.dropna(subset=["value"])
    out = pd.DataFrame({"station": station, "time_utc": df["time_utc"], "value": df["value"]})
    if product == "water_level":
        out["quality"] = df.get("q", "p")  # p = preliminary, v = verified
        out["sigma"] = pd.to_numeric(df.get("s"), errors="coerce")
        # flags "a,b,c,d": b = flat tolerance, c = rate of change, d = max/min limit exceeded
        out["flags"] = df.get("f", "")
    out["year"] = out["time_utc"].dt.year
    if product == "water_level":
        out["month"] = out["time_utc"].dt.month
    return out


def collect_station(station, now):
    added = {}
    for product, (dataset, chunk, overlap, extra) in PRODUCTS.items():
        wm = max_value(dataset, "time_utc", f"station = '{station}'")
        if wm is None:
            start = now - FIRST_FETCH[product] if product in FIRST_FETCH else HISTORY_START
        else:
            start = as_utc(wm) - overlap
        end = now + timedelta(days=7) if product == "predictions" else now
        frames = []
        while start < end:
            stop = min(start + chunk, end)
            frames.append(to_frame(fetch(product, station, start, stop, extra), product, station))
            start = stop
        df = pd.concat([f for f in frames if not f.empty], ignore_index=True) if any(not f.empty for f in frames) else pd.DataFrame()
        parts = ["station", "year", "month"] if product == "water_level" else ["station", "year"]
        added[dataset] = upsert(dataset, df, ["time_utc"], parts) if not df.empty else 0
    return added


def collect_metadata():
    rows = []
    for s in STATIONS:
        d = get(META.format(s), {"expand": "details,datums,floodlevels", "units": "metric"}).json()["stations"][0]
        datums = {x["name"]: x["value"] for x in d["datums"]["datums"]}
        fl = d.get("floodlevels") or {}
        # flood levels are heights above the station datum (STND), in metres with units=metric
        ft = lambda k: float(fl[k]) if fl.get(k) not in (None, "") else None
        rows.append({"station": s, "name": d["name"], "lat": float(d["lat"]), "lon": float(d["lng"]),
                     "mhhw_stnd_m": datums.get("MHHW"), "msl_stnd_m": datums.get("MSL"),
                     "great_diurnal_range_m": datums.get("GT"), "datum_epoch": d["datums"].get("epoch"),
                     "nos_minor_stnd_m": ft("nos_minor"), "nos_moderate_stnd_m": ft("nos_moderate"),
                     "nos_major_stnd_m": ft("nos_major")})
    return upsert("tide_stations", pd.DataFrame(rows).assign(part="all"), ["station"], ["part"])


def main():
    now = now_utc()
    ok_any = False
    try:
        collect_metadata()
    except Exception as e:  # metadata is cached in the lake from earlier runs
        print(f"  station metadata: {e}")
    for s in STATIONS:
        try:
            added = collect_station(s, now)
            record_health(f"tide:{s}", True, sum(added.values()), detail=", ".join(f"{k} +{v}" for k, v in added.items()))
            print(f"  {s}: " + ", ".join(f"{k} +{v}" for k, v in added.items()))
            ok_any = True
        except Exception as e:
            record_health(f"tide:{s}", False, error=str(e))
            print(f"  {s}: FAILED - {e}")
    sys.exit(0 if ok_any else 1)


if __name__ == "__main__":
    main()
