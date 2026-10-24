"""Bounded Prefect 3.9.0 scheduling integration in an isolated Python process.

Uses the real Prefect DeploymentScheduleCreate API schema and RRuleSchedule
get_dates implementation. No network, no account credentials, no Prefect Cloud.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_COUNT = 100_000
CHILD_TIMEOUT_SECONDS = 8.0
PREFECT_REQUIRED_VERSION = "3.9.0"


async def _measure(count: int, excluded: bool) -> dict:
    import prefect
    from prefect.server.schemas.actions import DeploymentScheduleCreate

    if prefect.__version__ != PREFECT_REQUIRED_VERSION:
        raise RuntimeError(f"Expected Prefect {PREFECT_REQUIRED_VERSION}; got {prefect.__version__}")
    if count not in (1_000, 10_000, MAX_COUNT):
        raise ValueError("Outside finite laboratory scope")

    text = f"DTSTART:20250101T000000Z\nRRULE:FREQ=MINUTELY;INTERVAL=1;COUNT={count}"
    if excluded:
        text += f"\nEXRULE:FREQ=MINUTELY;INTERVAL=1;COUNT={count}"
    api_action = DeploymentScheduleCreate(schedule={"rrule": text, "timezone": "UTC"})
    schedule = api_action.schedule

    t = time.perf_counter()
    start_cpu = time.process_time()
    record: dict = {}

    async def schedule_job() -> None:
        dates = await schedule.get_dates(
            n=1, start=datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc)
        )
        record["date_count"] = len(dates)
        record["schedule_wall_s"] = round(time.perf_counter() - t, 6)
        record["schedule_cpu_s"] = round(time.process_time() - start_cpu, 6)

    async def benign_timer() -> None:
        await asyncio.sleep(.01)
        record["ten_ms_timer_wall_s"] = round(time.perf_counter() - t, 6)

    await asyncio.gather(asyncio.create_task(schedule_job()), asyncio.create_task(benign_timer()))
    assert record["date_count"] == (0 if excluded else 1)
    return {"count": count, "all_excluded": excluded, "api_schema_accepted": True, **record}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path)
    p.add_argument("--child", action="store_true")
    p.add_argument("--count", type=int)
    p.add_argument("--exclude", action="store_true")
    args = p.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    import dateutil

    if Path(dateutil.__file__).resolve().parents[1] != (ROOT / "src").resolve():
        raise RuntimeError("Not executing the copied dateutil source")

    if args.child:
        if args.count is None:
            raise ValueError("Missing count")
        print(json.dumps(asyncio.run(_measure(args.count, args.exclude))))
        return

    import prefect

    if prefect.__version__ != PREFECT_REQUIRED_VERSION:
        raise RuntimeError("Pin Prefect to the tested release for reproducibility")
    data = []
    for n in (1_000, 10_000, MAX_COUNT):
        for exc in (False, True):
            cmd = [sys.executable, str(Path(__file__).resolve()), "--child", "--count", str(n)]
            if exc:
                cmd.append("--exclude")
            proc = subprocess.run(cmd, text=True, capture_output=True,
                                  timeout=CHILD_TIMEOUT_SECONDS, check=True)
            data.append(json.loads(proc.stdout))

    results = {
        "classification": "real Prefect API model and asyncio schema-level integration, not an end-to-end service or cross-user exploit",
        "prefect_version": prefect.__version__,
        "dateutil_upstream_baseline": "64914d9bcf987f0a6a8de77c3d07cc26f06185c9",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "max_candidate_count": MAX_COUNT,
        "child_timeout_seconds": CHILD_TIMEOUT_SECONDS,
        "results": data,
    }
    if args.output:
        target = ROOT / args.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
