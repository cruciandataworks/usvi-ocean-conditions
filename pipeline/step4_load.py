"""Step 4 - Load: expose the Parquet lake to the warehouse as raw tables.

The lake (Parquet files) is the permanent store. The DuckDB file is a disposable
copy rebuilt every run, so it can never drift from the lake. DuckDB reads the
partition folders (station=..., year=...) back into ordinary columns.
"""
import json
from pathlib import Path

import duckdb

from common import LAKE, ROOT, STATE

DB = ROOT / "warehouse" / "ocean.duckdb"
DATASETS = ["tide_6min", "tide_hourly", "tide_predictions", "water_temp_hourly", "tide_stations",
            "coral_daily", "buoy_waves", "buoy_ocean"]


def main():
    DB.parent.mkdir(exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    con.execute("create schema raw")
    for ds in DATASETS:
        files = list((LAKE / ds).rglob("*.parquet"))
        if not files:
            raise SystemExit(f"lake/{ds} is empty - run the collectors first")
        con.execute(f"""create table raw.{ds} as
            select * from read_parquet('{LAKE / ds}/**/*.parquet', hive_partitioning = true, union_by_name = true)""")
        n = con.execute(f"select count(*) from raw.{ds}").fetchall()[0][0]
        print(f"  raw.{ds}: {n:,} rows from {len(files)} files")
    health = json.loads((STATE / "health.json").read_text())
    rows = [(k.split(":")[0], k.split(":")[1], v.get("last_attempt"), v.get("last_success"),
             v.get("consecutive_failures", 0), v.get("last_error", ""), v.get("detail", ""))
            for k, v in health.items()]
    con.execute("""create table raw.source_health (source varchar, feed varchar, last_attempt timestamptz,
                   last_success timestamptz, consecutive_failures int, last_error varchar, detail varchar)""")
    con.executemany("insert into raw.source_health values (?, ?, ?, ?, ?, ?, ?)", rows)
    print(f"  raw.source_health: {len(rows)} feeds")
    con.close()


if __name__ == "__main__":
    main()
