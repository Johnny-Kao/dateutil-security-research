"""Bounded integration check of the genuine Times Square scheduler.

Run only on a pinned local checkout of lsst-sqre/times-square. No HTTP requests,
remote targets, or production deployments are contacted by this script.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DOWNSTREAM_SHA = "4ed70b6c01094b7d00e20432049d4e796af6869d"
MAX_COUNT = 100_000
TIMEOUT_SECONDS = 8


def execute_case(source_root: Path, count: int, exclude: bool) -> dict:
    if count not in (1_000, 10_000, MAX_COUNT):
        raise ValueError("Count outside finite research scope")
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(1, str(source_root / "src"))
    from timessquare.domain.schedule import RunSchedule

    start = "2025-01-01T00:00:00+00:00"
    rules = [{"start": start, "freq": "minutely", "count": count}]
    if exclude:
        rules.append(
            {"start": start, "freq": "minutely", "count": count, "exclude": True}
        )
    schedule = RunSchedule(json.dumps(rules), enabled=True)
    before = datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    result = schedule.next(before)
    cpu = round(time.process_time() - start_cpu, 6)
    wall = round(time.perf_counter() - start_wall, 6)
    assert (result is None) == exclude
    return {
        "count": count,
        "all_excluded": exclude,
        "cpu_s": cpu,
        "wall_s": wall,
        "next_occurrence": result.isoformat() if result else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--count", type=int)
    parser.add_argument("--exclude", action="store_true")
    args = parser.parse_args()
    source = args.source_root.resolve()
    if not (source / "src/timessquare/domain/schedule.py").is_file():
        raise RuntimeError("Missing upstream Times Square source")

    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if revision != EXPECTED_DOWNSTREAM_SHA:
        raise RuntimeError(f"Unexpected downstream revision: {revision}")

    if args.worker:
        if args.count is None:
            raise ValueError("Worker requires --count")
        print(json.dumps(execute_case(source, args.count, args.exclude)))
        return

    results = []
    for count in (1_000, 10_000, MAX_COUNT):
        for exclude in (False, True):
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--source-root",
                str(source),
                "--worker",
                "--count",
                str(count),
            ]
            if exclude:
                command.append("--exclude")
            child = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=True,
            )
            results.append(json.loads(child.stdout))

    result = {
        "classification": "local code-level integration; not a remote exploit",
        "source": "lsst-sqre/times-square",
        "source_sha": revision,
        "dateutil_upstream_baseline": "64914d9bcf987f0a6a8de77c3d07cc26f06185c9",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "timeout_per_case_s": TIMEOUT_SECONDS,
        "max_count": MAX_COUNT,
        "results": results,
    }
    if args.output:
        target = ROOT / args.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
