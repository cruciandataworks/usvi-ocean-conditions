"""Step 2 - Coral bleaching heat stress from NOAA Coral Reef Watch (CRW).

CRW estimates daily sea surface temperature from satellites and turns it into
bleaching heat stress:

  * HotSpot (HS): how far today's temperature is above the warmest normal month.
  * Degree Heating Weeks (DHW): HotSpots added up over the last 12 weeks, in degC-weeks.
    Corals start bleaching around 4 DHW; widespread bleaching and death above 8.
  * Bleaching Alert Area (BAA): 0 No stress, 1 Watch, 2 Warning, 3-7 Alert Levels 1-5.

We read one regional station for the whole territory and six single-pixel (5 km)
stations around the islands. Each file contains the full history back to 1985, so
there is no backfill: we download the file and merge it. CRW updates once a day, so
the collector asks "has it changed since last time?" (If-Modified-Since) and skips
the download when it has not.
"""
import io
import json
import sys

import pandas as pd
import requests

from common import HEADERS, STATE, record_health, upsert

REGIONAL = "https://coralreefwatch.noaa.gov/product/vs/data/usvi.txt"
PIXEL = "https://coralreefwatch.noaa.gov/product/vs_single_pixel_exp/data/AtlanticOcean_Caribbean_VirginIslands_{}.txt"
STATIONS = {
    "usvi": ("Virgin Islands (regional)", REGIONAL),
    "sw_st_thomas": ("Southwest St. Thomas", PIXEL.format("SouthwestStThomas")),
    "n_st_thomas": ("North St. Thomas", PIXEL.format("NorthStThomas")),
    "s_st_john": ("South St. John", PIXEL.format("SouthStJohn")),
    "e_st_john": ("East St. John", PIXEL.format("EastStJohn")),
    "w_st_croix": ("West St. Croix", PIXEL.format("WestStCroix")),
    "ne_st_croix": ("Northeast St. Croix", PIXEL.format("NortheastStCroix")),
}


def download(url, cache):
    """Conditional GET: returns None when the file has not changed since last run."""
    h = dict(HEADERS)
    if cache.get(url):
        h["If-Modified-Since"] = cache[url]
    for attempt in range(3):
        try:
            r = requests.get(url, headers=h, timeout=90)
            if r.status_code == 304:
                return None
            r.raise_for_status()
            cache[url] = r.headers.get("Last-Modified", "")
            return r.text
        except requests.RequestException as e:
            if attempt == 2:
                raise RuntimeError(f"{url}: {e}")


def parse(text, station):
    """Both file layouts: a header block, then a line starting with YYYY, then data."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("YYYY"))
    header = lines[start].replace(",", " ").split()
    body = "\n".join(ln.replace(",", " ") for ln in lines[start + 1:] if ln.strip())
    df = pd.read_csv(io.StringIO(body), sep=r"\s+", names=header, engine="python")
    df["date"] = pd.to_datetime(dict(year=df["YYYY"], month=df["MM"], day=df["DD"]))
    if "SST" in df.columns:  # single-pixel layout
        out = pd.DataFrame({"date": df["date"], "sst_c": df["SST"], "ssta_c": df["SSTA"], "hotspot_c": df["HS"],
                            "dhw": df["DHW"], "baa": df["BAA"], "baa_7day_max": df["BAA_7Day_Max"]})
    else:  # regional layout: statistics over the region's pixels
        out = pd.DataFrame({"date": df["date"], "sst_c": df["SST@90th_HS"], "ssta_c": df["SSTA@90th_HS"],
                            "hotspot_c": df["90th_HS>0"], "dhw": df["DHW_from_90th_HS>1"],
                            "baa": pd.NA, "baa_7day_max": df["BAA_7day_max"],
                            "sst_min_c": df["SST_MIN"], "sst_max_c": df["SST_MAX"]})
    # CRW writes missing values as large negative numbers
    for c in [c for c in out.columns if c.endswith("_c") or c == "dhw"]:
        out.loc[out[c] < -50, c] = pd.NA
    # climatology lines in the header: warmest normal month, used for the bleaching threshold
    mmm = None
    for i, ln in enumerate(lines[:start]):
        if "Maximum Monthly Mean" in ln:
            mmm = float(lines[i + 1].split()[0])
    out["mmm_c"] = mmm
    out["station"] = station
    out["year"] = out["date"].dt.year
    return out


def main():
    cache_file = STATE / "http_cache.json"
    STATE.mkdir(parents=True, exist_ok=True)
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    ok_any = False
    for sid, (name, url) in STATIONS.items():
        try:
            text = download(url, cache)
            if text is None:
                record_health(f"coral:{sid}", True, 0, detail="not modified since last run")
                print(f"  {sid}: not modified")
            else:
                df = parse(text, sid)
                n = upsert("coral_daily", df, ["date"], ["station", "year"])
                record_health(f"coral:{sid}", True, n, detail=f"latest {df['date'].max():%Y-%m-%d}")
                print(f"  {sid}: +{n} rows, latest {df['date'].max():%Y-%m-%d}, DHW {df['dhw'].iloc[-1]}")
            ok_any = True
        except Exception as e:
            record_health(f"coral:{sid}", False, error=str(e))
            print(f"  {sid}: FAILED - {e}")
    cache_file.write_text(json.dumps(cache, indent=2))
    sys.exit(0 if ok_any else 1)


if __name__ == "__main__":
    main()
