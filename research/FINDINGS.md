# dateutil #1094 — research findings (2026-10-25)

## Scope and provenance

- Repository: public, independent non-fork copy of dateutil/dateutil
- Upstream baseline: `64914d9bcf987f0a6a8de77c3d07cc26f06185c9`
- Initial research commit: `eee7d97747f15d64a5fb3f6a6551e86351ea2a19`
- Source path: `src/dateutil/rrule.py`, in particular `rruleset._iter()`
- Existing public upstream report: https://github.com/dateutil/dateutil/issues/1094

No upstream code was modified. Experiments use finite recurrence counts, a short
per-child timeout, and a demonstration HTTP server bound exclusively to localhost.

## A. Resource consumption — locally reproduced on this copy

Mac arm64, Python 3.15.0, read source directly from this repository. These are
single observations, not multi-run statistical benchmarks.

| Count | Control (wall seconds) | All excluded (wall seconds) | All excluded CPU seconds |
|---:|---:|---:|---:|
| 1,000 | 0.040594 | 0.012633 | 0.012635 |
| 10,000 | 0.010254 | 0.033284 | 0.033258 |
| 100,000 | 0.010180 | 0.237864 | 0.237717 |
| 300,000 | 0.010152 | 0.695810 | 0.695328 |

The first control measurement appears affected by startup noise. The 10k–300k
excluded case is broadly consistent with work increasing with the number of
suppressed candidates. The control can return the first event immediately.
The excluded case returns None only after exhausting all candidates.

Conclusion: **confirmed bounded CPU cost on the copied upstream source**.
This does not establish memory exhaustion or any infinite-loop condition.

Raw evidence: `research/results/macos-python315-precommit.json`.

## B. HTTP input to sink — demonstrated only in a controlled localhost service

The initial toy handler accepted bounded count/exclusion parameters. The second
pass (below) accepts bounded client-supplied recurrence text instead. Both call
`rrulestr(..., forceset=True).after(...)` on a single-threaded demo server.
Two overlapping requests demonstrate head-of-line blocking:

| Local request | Client wall seconds | Server computation seconds |
|---|---:|---:|
| Ordinary request without exclusion | 0.034710 | 0.010656 |
| Request with 300k events all excluded | 0.677734 | 0.676865 |
| Innocent request arriving behind the expensive one | 0.627266 | 0.000068 |

Conclusion: **a purpose-built single-worker service can experience
application-level request delay from this algorithm**. This is a simulated
reachability and concurrency example, **not evidence that any real upstream
consumer is remotely exploitable**.

Further evidence would require an identified real deployment accepting
attacker-controlled recurrence rules, including verification of rate limits,
request timeouts, process model, and measurable service impact.

## B2. Second pass — client-controlled recurrence text, bounded and loopback-only

The HTTP demonstration now accepts the recurrence text itself in a JSON
`rrule_text` field, and passes that validated string to
`rrulestr(..., forceset=True).after(...)`. It does **not** simply map an HTTP
boolean to a hardcoded dangerous rule. For safety, the test server accepts
only finite `FREQ=MINUTELY` rules with `COUNT <= 300000`, and a matching
optional EXRULE. It rejects unbounded, mismatched, or unsupported syntax.

Mac arm64, Python 3.15.0, second single-run observation:

| Scenario | Client wall seconds | Server computation seconds |
| --- | ---: | ---: |
| Normal recurrence (300,000 available) | 0.028349 | 0.010955 |
| Client-supplied RRULE plus matching EXRULE (300,000) | 0.683417 | 0.682541 |
| Unrelated normal request queued behind it | 0.632044 | 0.000124 |

All three requests returned HTTP 200. Four invalid/unbounded parameter forms
were rejected in a direct input-boundary check. The new formal regression
tests also cover finite evaluation and the local HTTP input path.

Evidence: `research/results/macos-python315-raw-http.json` and
`research/test_security.py`.

**Interpretation:** the client-to-parser trust boundary is real in this
constructed loopback demonstration, and application head-of-line blocking is
reproducible here. This still does not establish a remote security flaw in any
real deployed product.

## Downstream source reconnaissance (no external execution)

Read-only GitHub code review located consumers that use dateutil's recurrence
APIs. For example:
- `lsst-sqre/times-square` has `schedule.py` code that reconstructs dateutil
  RRULE/EXRULE sets from schedule JSON and calls `rruleset.after()`.
- `boosh/django_recurring` uses dateutil `rruleset.after()` to calculate
  stored calendar occurrences.

**Neither was remotely tested.** Whether untrusted external users can supply
matching unlimited rules, and whether service-level limits permit disruption,
are **not verified**. These are code-path references, not vulnerability claims.

## C. Real downstream scheduler — local code-level integration

Local test uses the actual `lsst-sqre/times-square` modules
`timessquare.domain.schedulerule` and `timessquare.domain.schedule`
from source revision `4ed70b6c01094b7d00e20432049d4e796af6869d`.
Pydantic validates the schedule JSON and the genuine
`RunSchedule.next()` invokes dateutil's `rruleset.after()`.

The test uses only finite 1,000 / 10,000 / 100,000-candidate rules in
short-lived local child processes (eight-second timeout). macOS arm64,
Python 3.14.6, one observation per case:

| Candidates | Normal CPU seconds | Identical exclusion CPU seconds |
| ---: | ---: | ---: |
| 1,000 | 0.000322 | 0.002881 |
| 10,000 | 0.000104 | 0.027745 |
| 100,000 | 0.000100 | 0.279214 |

Evidence: `research/results/times-square-macos-python314.json`.
Reproducer: `research/integrate_times_square.py`.

This establishes algorithmic cost **inside a real downstream library's
scheduling classes**, but not an attack on its running service.

### Times Square trust-boundary review

Source inspection of the same pinned commit found:
- Schedule input comes from GitHub-backed notebook YAML sidecar files and is
  validated with Pydantic. `ScheduleFromDate` supports an optional `count`
  and `end`; the scheduler can create corresponding inclusion/exclusion
  rules, including rules without either termination parameter.
- The GitHub App webhook uses signature verification. GitHub installation
  handling is restricted to configured accepted organizations. The push
  handler processes default-branch events.
- `RunSchedulerService.schedule_due_runs()` checks stored enabled page
  schedules, with `RunSchedule.next()` doing synchronous evaluation.
  The cron scheduling job has a 60-second task timeout, but that is not
  evidence of a per-rule computation budget.
- The ordinary `POST /pages` request schema does not accept schedule
  definitions as a field. No public anonymous schedule-write API was found
  during this code review.

**Security impact remains unverified:** no permission bypass, untrusted
write path, production deployment vulnerability, or actual multi-user
denial-of-service has been demonstrated. Only local cloned code was executed.

For contrast, `boosh/django_recurring` uses `rruleset.after()` but its
reviewed rule-building path constructs `rrule()` with exclusions as
`exdate()`, not a direct `exrule()` path. The precise #1094 trigger is
therefore not established in that library.

## D. GitHub-hosted validation after repository became public

The initial GitHub run `40116088729` failed before runner execution
due to the account billing/spending-limit block. It was **not** a test result.

A new public-repository workflow-dispatch run completed successfully:
https://github.com/Johnny-Kao/dateutil-security-research/actions/runs/40117754779

Its artifact is `dateutil-rruleset-evidence`, Linux x86_64, Python
3.13.16, using the copied dateutil source. Selected single-run values:

| Scenario | CPU seconds |
| --- | ---: |
| 300,000 candidates without exclusion | 0.020392 |
| 300,000 candidates fully excluded | 2.129871 |

The loopback HTTP demonstration observed a 2.076800-second client wall
time for an unrelated normal request queued behind the expensive request,
while its own computation was 0.000224 seconds. This is a *toy service*
head-of-line delay, not a remotely exploited downstream product.

The expanded two-job workflow also passed:
https://github.com/Johnny-Kao/dateutil-security-research/actions/runs/40118291764

Both `reproduce` and `downstream-integration` completed successfully and
uploaded independent JSON artifacts. On that Linux run:
- dateutil (Python 3.13.16), 300,000 all-excluded candidates: 1.716316
  CPU seconds vs. 0.016145 for the immediate-result control.
- Actual Times Square `RunSchedule.next()` (Python 3.14.8), 100,000
  all-excluded candidates: 0.908381 CPU seconds vs. 0.000239 for the
  immediate-result control.

The pinned Times Square checkout and execution are local to the GitHub
Actions job; no third-party service was contacted or assessed as vulnerable.

## E. Prefect 3.9.0 scheduling-model integration

Reproduced with the actual public Prefect release `3.9.0`, using
`DeploymentScheduleCreate` (API action schema) and the server-side
`RRuleSchedule.get_dates()`. The Python process loads the dateutil copy
from this repository. All rules are finite (`COUNT <= 100000`);
each child has an 8-second timeout. No real server, network account, or
external service was tested.

macOS arm64, Python 3.13.16, single-run observations:

| Candidate count | Normal CPU s | Fully excluded CPU s | Normal 10ms timer s | Excluded 10ms timer s |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.000453 | 0.003264 | 0.011500 | 0.013603 |
| 10,000 | 0.000429 | 0.028589 | 0.011169 | 0.039651 |
| 100,000 | 0.000442 | 0.281569 | 0.010505 | 0.292394 |

The API action schema accepted all six tested shapes. Prefect's
`MAX_ITERATIONS=1000` check is downstream of the dateutil iterator's next
yield; it cannot interrupt candidate evaluation when no result is yielded.
The in-process benign timer is therefore delayed by the synchronous
evaluation. Evidence: `research/results/prefect39-macos-python313.json`;
reproducer: `research/integrate_prefect.py`.

The upstream `POST /deployments/{id}/schedules` route accepts
`DeploymentScheduleCreate`, and the shared background scheduler calls
`_generate_scheduled_flow_runs`, which iterates this model. This is
source-level reachability, **not** an authenticated end-to-end server
demonstration.

**Security caveat:** self-hosted Prefect OSS and Prefect Cloud have
different auth/RBAC and tenancy architectures. This experiment did
not prove an untrusted actor can affect a separate user's workload.
The result should not be described as a CVE or remotely exploitable DoS.

## F. CVE threshold — not established

- The algorithmic cost was previously disclosed in issue #1094 (2020).
- No real vulnerable downstream deployment was identified or tested.
- There is no substantiated remote attack or privilege/scope boundary crossed.
- CVE eligibility, CVSS score, and severity remain **undetermined**.
- No new CVE or private advisory was filed as part of this research.

A CVE is an identifier assigned through appropriate vulnerability coordination;
it cannot be produced or confirmed by a test-suite PASS alone.

The research workflow remains **manual dispatch only** and has a five-minute
timeout per GitHub job. Public-repository Actions ran successfully without
enabling paid runners. See section D for run links and evidence.

## Next decision

Do not open a duplicate upstream Issue or CVE request based on this result.
If the goal is security impact, investigate a consenting real downstream
application or a responsible disclosure route; otherwise the finding is best
treated as a performance/availability concern within existing #1094.
