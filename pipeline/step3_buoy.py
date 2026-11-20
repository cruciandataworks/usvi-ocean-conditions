"""Step 3 - Offshore waves and water temperature from CARICOOS buoy VI1 (NDBC 41052),
moored south of St. John. Data comes from the CARICOOS ERDDAP server, a standard
scientific data service that answers queries like a small database over HTTP:

    .../tabledap/VI1_waves_merged.csv?time,significant_wave_height&time>=2026-06-01

Every value carries a QARTOD quality flag: 1 pass, 2 not evaluated, 3 suspect, 4 fail,
9 missing. We store the flag and let dbt decide what to show.

The buoy has been offline since 2 July 2026. The collector still checks it every run,
so when it comes back the gap fills itself from the last value we have.
"""
import io
import sys
from datetime import timedelta

import pandas as pd

from common import as_utc, get, max_value, record_health, upsert

ERDDAP = "https://dm3.caricoos.org/erddap/tabledap"
DATASETS = {
    "buoy_waves": ("VI1_waves_merged", {
        "significant_wave_height": "wave_height_m", "max_wave_height": "max_wave_height_m",
        "dominant_wave_period": "wave_period_s", "mean_wave_direction": "wave_direction_deg"},
        "significant_wave_height_qc_agg"),
    "buoy_ocean": ("VI1_ocean_0001m_merged", {
        "temperature": "water_temp_c", "salinity": "salinity_psu"}, "temperature_qc_agg"),
}
OVERLAP = timedelta(days=3)


def query(dataset, cols, since):
    q = ",".join(["time", *cols])
    if since is not None:
        q += f"&time>={since:%Y-%m-%dT%H:%M:%SZ}"
    r = get(f"{ERDDAP}/{dataset}.csv?{q}", timeout=180)
    df = pd.read_csv(io.StringIO(r.text), skiprows=[1])  # row 2 holds units
    return df


def info(dataset):
    """When ERDDAP says the dataset ends (to report an offline buoy clearly)."""
    r = get(f"{ERDDAP}/{dataset}.csv?time&orderByMax(%22time%22)")
    return pd.read_csv(io.StringIO(r.text), skiprows=[1])["time"].iloc[0]


def main():
    ok_any = False
    for lake_name, (dataset, mapping, qc_col) in DATASETS.items():
        try:
            wm = max_value(lake_name, "time_utc")
            since = None if wm is None else as_utc(wm) - OVERLAP
            df = query(dataset, [*mapping, qc_col], since)
            # ERDDAP answers "no data" with HTTP 404 inside get(); an empty frame is fine too
            df = df.rename(columns={"time": "time_utc", qc_col: "qc_flag", **mapping})
            df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
            df["station"] = "VI1"
            df["year"] = df["time_utc"].dt.year
            n = upsert(lake_name, df, ["time_utc"], ["station", "year"]) if len(df) else 0
            last = info(dataset)
            record_health(f"buoy:{lake_name}", True, n, detail=f"ERDDAP latest {last}")
            print(f"  {dataset}: +{n} rows, latest on server {last}")
            ok_any = True
        except Exception as e:
            msg = str(e)
            if "404" in msg and wm is not None:  # no rows after our watermark: buoy still offline
                last = info(dataset)
                record_health(f"buoy:{lake_name}", True, 0, detail=f"ERDDAP latest {last}")
                print(f"  {dataset}: no new rows, latest on server {last}")
                ok_any = True
                continue
            record_health(f"buoy:{lake_name}", False, error=msg)
            print(f"  {dataset}: FAILED - {msg}")
    sys.exit(0 if ok_any else 1)


if __name__ == "__main__":
    main()
