"""Run every step in order. This is what the 3-hourly schedule calls.

    python run_pipeline.py            # full run
    python run_pipeline.py --from 4   # skip the downloads, rebuild from the lake

Steps 1-3 each talk to a different agency. One of them being down must not stop the
other two, so a collector failure is recorded (step 4 loads it into source_health and
the alerts pick it up) and the run carries on. The run fails only if every collector
fails, or if anything from step 4 on fails - then bad data never reaches the dashboard.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
STEPS = [
    (1, "Collect tides (NOAA CO-OPS)", [PY, "pipeline/step1_tides.py"], True),
    (2, "Collect coral heat stress (NOAA Coral Reef Watch)", [PY, "pipeline/step2_coral.py"], True),
    (3, "Collect buoy (CARICOOS)", [PY, "pipeline/step3_buoy.py"], True),
    (4, "Load DuckDB", [PY, "pipeline/step4_load.py"], False),
    (5, "dbt build (models + tests)", ["dbt", "build", "--profiles-dir", "."], False),
    (6, "Export dashboard data", [PY, "pipeline/step6_export.py"], False),
    (7, "Sync alert issues", [PY, "pipeline/step7_alerts.py"], False),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=1)
    args = ap.parse_args()
    if os.environ.get("TEST_FAILURE") == "true":
        print("TEST_FAILURE is set - failing on purpose to test the failure alert.")
        sys.exit(1)
    collectors_run = collectors_failed = 0
    for n, label, cmd, tolerant in STEPS:
        if n < args.start:
            continue
        print(f"\n=== Step {n}: {label} ===", flush=True)
        # dbt resolves the DuckDB path relative to where it runs, so run it inside dbt/
        cwd = ROOT / "dbt" if cmd[0] == "dbt" else ROOT
        result = subprocess.run(cmd, cwd=cwd, env=os.environ.copy())
        if tolerant:
            collectors_run += 1
            if result.returncode != 0:
                collectors_failed += 1
                print(f"Step {n} failed - carrying on; the failure is recorded in source health.")
            if n == 3 and collectors_run and collectors_failed == collectors_run:
                print("Every collector failed - stopping.")
                sys.exit(1)
        elif result.returncode != 0:
            print(f"Step {n} failed - stopping so bad data never reaches the dashboard.")
            sys.exit(result.returncode)
    print("\nAll steps finished.")


if __name__ == "__main__":
    main()
