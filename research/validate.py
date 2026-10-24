"""Bounded, localhost-only reproduction of dateutil issue #1094.

No external targets or unbounded rules. Run: python research/validate.py all
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dateutil import __version__ as dateutil_version  # noqa: E402
from dateutil.rrule import rrulestr  # noqa: E402

START = datetime(2025, 1, 1)
QUERY_TIME = START - timedelta(minutes=1)
MAX_COUNT = 300_000
HTTP_LIMIT = 16_384
WORKER_TIMEOUT_S = 12
UPSTREAM_BASELINE = "64914d9bcf987f0a6a8de77c3d07cc26f06185c9"


def validate_rule_text(value: object) -> str:
    """Accept only a short, finite test-specific recurrence syntax."""
    if not isinstance(value, str) or len(value) > HTTP_LIMIT:
        raise ValueError("Invalid rule text or size")
    parts = value.splitlines()
    if len(parts) not in (2, 3) or parts[0] != "DTSTART:20250101T000000":
        raise ValueError("Only bounded laboratory recurrence rules are accepted")
    prefix = "RRULE:FREQ=MINUTELY;COUNT="
    if not parts[1].startswith(prefix):
        raise ValueError("RRULE format outside laboratory scope")
    count_str = parts[1][len(prefix):]
    if not count_str.isascii() or not count_str.isdecimal() or len(count_str) > 6:
        raise ValueError("Invalid finite COUNT")
    count = int(count_str)
    if count < 1 or count > MAX_COUNT:
        raise ValueError("COUNT exceeds laboratory cap")
    if len(parts) == 3 and parts[2] != f"EXRULE:FREQ=MINUTELY;COUNT={count}":
        raise ValueError("Only matching bounded EXRULE is permitted")
    return value


def rule_text(count: int, exclude: bool) -> str:
    if type(count) is not int or not (1 <= count <= MAX_COUNT):
        raise ValueError("Count outside bounded research scope")
    lines = [
        "DTSTART:20250101T000000",
        f"RRULE:FREQ=MINUTELY;COUNT={count}",
    ]
    if exclude:
        lines.append(f"EXRULE:FREQ=MINUTELY;COUNT={count}")
    return "\n".join(lines)


def evaluate(text: str) -> dict:
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    value = rrulestr(text, forceset=True).after(QUERY_TIME)
    return {
        "wall_s": round(time.perf_counter() - start_wall, 6),
        "cpu_s": round(time.process_time() - start_cpu, 6),
        "next_event": value.isoformat() if value is not None else None,
    }


class LocalHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/calendar/next":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > HTTP_LIMIT:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
            # Test source text crosses the HTTP boundary unchanged.
            # Validate it tightly so this laboratory cannot run unbounded rules.
            result = evaluate(validate_rule_text(payload["rrule_text"]))
            status = 200
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            result = {"error": str(exc)}
            status = 400
        body = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def serve():
    # Deliberately single-threaded to measure head-of-line blocking.
    # Bind only to loopback; never expose this toy service externally.
    with HTTPServer(("127.0.0.1", 0), LocalHandler) as server:
        print(json.dumps({"port": server.server_address[1]}), flush=True)
        server.serve_forever(poll_interval=0.1)


def child_worker(kind: str, count: int):
    result = evaluate(rule_text(count, exclude=(kind == "excluded")))
    result.update({"kind": kind, "count": count})
    assert (result["next_event"] is None) == (kind == "excluded")
    print(json.dumps(result))


def isolated_case(kind: str, count: int) -> dict:
    args = [
        sys.executable, str(Path(__file__).resolve()),
        "worker", "--kind", kind, "--count", str(count),
    ]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=WORKER_TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"kind": kind, "count": count, "timeout_s": WORKER_TIMEOUT_S}
    if proc.returncode:
        raise RuntimeError(f"worker {kind}/{count} failed: {proc.stderr[:600]}")
    return json.loads(proc.stdout)


def local_http_case(count: int) -> dict:
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "serve"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        info = json.loads(proc.stdout.readline())
        url = f"http://127.0.0.1:{info['port']}/calendar/next"

        def request(exclude: bool):
            payload = json.dumps({"rrule_text": rule_text(count, exclude)}).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            started = time.perf_counter()
            with urllib.request.urlopen(req, timeout=WORKER_TIMEOUT_S) as response:
                body = json.load(response)
                status = response.status
            return {"http_status": status, "client_wall_s": round(
                time.perf_counter() - started, 6), **body}

        baseline = request(False)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(request, True)
            time.sleep(0.04)
            normal_behind_slow = pool.submit(request, False)
            excluded = slow.result(timeout=WORKER_TIMEOUT_S + 2)
            delayed = normal_behind_slow.result(timeout=WORKER_TIMEOUT_S + 2)
        assert baseline["next_event"] is not None
        assert delayed["next_event"] is not None
        assert excluded["next_event"] is None
        return {
            "scope": "purpose-built single-worker service, loopback only",
            "ingress": "HTTP JSON rrule_text supplied by client, passed to rrulestr",
            "baseline": baseline,
            "excluded_request": excluded,
            "benign_request_behind_excluded": delayed,
            "observed_head_of_line_delay": delayed["client_wall_s"] >
                                          max(0.05, 4 * baseline["client_wall_s"]),
        }
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=3)


def research_all() -> dict:
    cases = []
    for count in (1000, 10000, 100000, MAX_COUNT):
        cases.append(isolated_case("normal", count))
        cases.append(isolated_case("excluded", count))
    http = local_http_case(MAX_COUNT)
    return {
        "source": "upstream dateutil master independent non-fork copy",
        "upstream_baseline_commit": UPSTREAM_BASELINE,
        "research_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True,
            check=True,
        ).stdout.strip(),
        "issue": "https://github.com/dateutil/dateutil/issues/1094",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "dateutil_version": dateutil_version,
        "max_count": MAX_COUNT,
        "per_worker_timeout_s": WORKER_TIMEOUT_S,
        "benchmarks": cases,
        "http_simulation": http,
        "security_assessment": {
            "resource_exhaustion": "bounded CPU cost confirmed if wall/CPU scaling observed",
            "http_input_to_sink": "tested on local constructed demonstration service only",
            "real_world_remote_exploit": "not established",
            "CVE_eligibility": "unverified; no CVE requested or assigned",
        },
    }


def main():
    argp = argparse.ArgumentParser()
    argp.add_argument("action", choices=["all", "worker", "serve"])
    argp.add_argument("--kind", choices=["normal", "excluded"], default="excluded")
    argp.add_argument("--count", type=int, default=1000)
    argp.add_argument("--output", default="research/results/latest.json")
    args = argp.parse_args()
    if args.action == "serve":
        return serve()
    if args.action == "worker":
        return child_worker(args.kind, args.count)
    outcome = research_all()
    file = ROOT / args.output
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")
    print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    main()
