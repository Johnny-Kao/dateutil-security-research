# dateutil #1094 — research findings (2026-10-25)

## Scope and provenance

- Repository: private, independent non-fork copy of dateutil/dateutil
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

## C. CVE threshold — not established

- The algorithmic cost was previously disclosed in issue #1094 (2020).
- No real vulnerable downstream deployment was identified or tested.
- There is no substantiated remote attack or privilege/scope boundary crossed.
- CVE eligibility, CVSS score, and severity remain **undetermined**.
- No new CVE or private advisory was filed as part of this research.

A CVE is an identifier assigned through appropriate vulnerability coordination;
it cannot be produced or confirmed by a test-suite PASS alone.

## GitHub Actions status

A workflow run was triggered after commit `eee7d97`:

https://github.com/Johnny-Kao/dateutil-security-research/actions/runs/40116088729

**FAILED before runner execution**: the GitHub job shows runner_id 0, an empty
runner name, and zero execution steps. The GitHub CLI run annotation explicitly
states: "The job was not started because recent account payments have failed or
your spending limit needs to be increased. Please check the 'Billing & plans'
section in your settings." Consequently this is **not** a GitHub-hosted
validation result and cannot be called CI PASS. We did not enable paid runners.

The research workflow has been changed to **manual dispatch only** to prevent
automatic retry/failure on each research commit. It can be triggered when a
runner is available.

## Next decision

Do not open a duplicate upstream Issue or CVE request based on this result.
If the goal is security impact, investigate a consenting real downstream
application or a responsible disclosure route; otherwise the finding is best
treated as a performance/availability concern within existing #1094.
