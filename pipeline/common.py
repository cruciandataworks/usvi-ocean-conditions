"""Shared helpers for the collectors: polite HTTP with retries, the Parquet "lake",
and the source-health log.

The lake is a folder of Parquet files split into partitions, for example:

    lake/tide_6min/station=9751364/year=2026/month=11/data.parquet
    lake/coral_daily/station=usvi/year=2026/data.parquet

Splitting by station and time means each run only rewrites the few small files that
received new rows. Everything older is left untouched.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
LAKE = Path(os.environ.get("LAKE_DIR", ROOT / "lake"))
STATE = LAKE / "_state"
HEADERS = {"User-Agent": "CrucianDataWorks-portfolio/1.0 (hello@cruciandataworks.com)"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------- HTTP
PAUSE = float(os.environ.get("HTTP_PAUSE", "0.6"))  # seconds between requests
RETRY_STATUS = {403, 429, 500, 502, 503, 504}  # NOAA answers 403 when it is rate limiting


def get(url, params=None, tries=4, timeout=60):
    """GET with a short pause before every request and retries after a failure.
    Waits 5, 15, 45 seconds between attempts, so a brief outage or rate limit on the
    provider's side does not fail the run. Raises after the last attempt."""
    last = None
    for attempt in range(tries):
        time.sleep(PAUSE)
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code in RETRY_STATUS:
                raise requests.HTTPError(f"HTTP {r.status_code} from {url.split('?')[0]}")
            if r.status_code >= 400:  # e.g. 404 "no data": retrying will not help
                raise LookupError(f"HTTP {r.status_code} from {url.split('?')[0]}: {r.text[:200]}")
            return r
        except (requests.RequestException, requests.HTTPError) as e:
            last = e
            if attempt < tries - 1:
                time.sleep(5 * 3 ** attempt)
    raise RuntimeError(f"{url} failed after {tries} attempts: {last}")


# ---------------------------------------------------------------------------- lake
def _partition_path(dataset, parts: dict) -> Path:
    p = LAKE / dataset
    for k, v in parts.items():
        p = p / f"{k}={v}"
    return p / "data.parquet"


def upsert(dataset: str, df: pd.DataFrame, keys: list, partition_by: list) -> int:
    """Merge new rows into the lake. Rows with the same keys are replaced by the newer
    copy, so running a collector twice never creates duplicates (it is "idempotent").
    Returns how many rows are new or changed."""
    if df.empty:
        return 0
    # chunked downloads share their boundary timestamp, so the same row can arrive twice
    # in one batch; keep one copy (the last one fetched)
    df = df.drop_duplicates(subset=list(dict.fromkeys(partition_by + keys)), keep="last").copy()
    df["ingested_at"] = now_utc().isoformat()
    con = duckdb.connect()
    changed = 0
    for values, part in df.groupby(partition_by, sort=True):
        values = values if isinstance(values, tuple) else (values,)
        path = _partition_path(dataset, dict(zip(partition_by, values)))
        path.parent.mkdir(parents=True, exist_ok=True)
        new = part.drop(columns=partition_by)
        con.register("new_rows", new)
        cols = [c for c in new.columns if c != "ingested_at"]
        if path.exists():
            con.execute(f"create or replace temp table old_rows as select * from read_parquet('{path}')")
            # rows that are genuinely new or whose values changed
            changed += con.execute(f"""
                select count(*) from (select {', '.join(cols)} from new_rows
                                      except select {', '.join(cols)} from old_rows)""").fetchall()[0][0]
            merged = f"""
                select * exclude (rn) from (
                    select *, row_number() over (partition by {', '.join(keys)} order by src desc) rn
                    from (select *, 1 as src from new_rows union all by name select *, 0 as src from old_rows)
                ) where rn = 1"""
            query = f"select * exclude (src) from ({merged}) order by {', '.join(keys)}"
        else:
            changed += len(new)
            query = f"select * from new_rows order by {', '.join(keys)}"
        # write to a temporary file first, then swap it in: a crash mid-write can never
        # leave a half-written partition behind
        tmp = path.with_suffix(".tmp")
        con.execute(f"copy ({query}) to '{tmp}' (format parquet, compression zstd)")
        os.replace(tmp, path)
        con.unregister("new_rows")
    return changed


def max_value(dataset: str, column: str, where: str = "true"):
    """Latest timestamp already in the lake (the "watermark"), or None if empty."""
    files = list((LAKE / dataset).rglob("*.parquet"))
    if not files:
        return None
    con = duckdb.connect()
    v = con.execute(f"select max({column}) from read_parquet('{LAKE / dataset}/**/*.parquet', hive_partitioning=1) where {where}").fetchall()[0][0]
    return v


# ---------------------------------------------------------------------------- health
def record_health(source: str, ok: bool, rows: int = 0, error: str = "", detail: str = ""):
    """Keep one line per source: when it last worked, how many runs in a row failed,
    and the last error. The dashboard and the alerts read this file."""
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / "health.json"
    health = json.loads(f.read_text()) if f.exists() else {}
    h = health.get(source, {"consecutive_failures": 0})
    h["last_attempt"] = now_utc().isoformat()
    if ok:
        h.update(last_success=h["last_attempt"], consecutive_failures=0, last_rows=rows, last_error="", detail=detail)
    else:
        h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1
        h["last_error"] = error[:300]
    health[source] = h
    f.write_text(json.dumps(health, indent=2, sort_keys=True))
    with open(STATE / "runs.csv", "a") as log:
        if log.tell() == 0:
            log.write("run_at,source,ok,rows,error\n")
        log.write(f"{h['last_attempt']},{source},{int(ok)},{rows},\"{error[:200].replace(chr(34), chr(39))}\"\n")


def as_utc(ts):
    """A watermark from DuckDB as a timezone-aware UTC datetime."""
    t = pd.Timestamp(ts)
    return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).to_pydatetime()
