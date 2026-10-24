# dateutil security research — bounded reproduction

This is an **independent public non-fork copy** of dateutil/dateutil, made
to test [dateutil issue #1094](https://github.com/dateutil/dateutil/issues/1094)
against the current source without changing upstream. The initial upstream
baseline is commit 64914d9bcf987f0a6a8de77c3d07cc26f06185c9.

## Research questions / evidence thresholds

| Question | What this research can establish | What it does not establish |
| --- | --- | --- |
| CPU/resource exhaustion | Wall/CPU cost vs. bounded RRULE+EXRULE event counts, including a normal-rule control | Infinite execution, arbitrary memory exhaustion, or unbounded DoS |
| HTTP-triggered impact | Locally controlled HTTP request reaches rrulestr(...).after(...) and can delay an unrelated request on a single-worker *demonstration server* | That any real third-party service is deployed with this arrangement |
| CVE | Technical observations relevant to a future report and upstream's existing public issue | CVE assignment, real-world victim, exploitability across applications, or severity rating |

## Boundaries

- Every recurrence rule includes COUNT, with a hard maximum of 300,000.
- Work runs in child processes with 12-second timeouts.
- The demonstration server binds **only** to 127.0.0.1 on an ephemeral port.
- No external service, domain, credential, or live production target is accessed.
- GitHub Actions is capped at five minutes and uploads only the JSON observations.
- No attempt is made to label an uncaught exception or a slow algorithm as a
  confirmed security vulnerability without the application's threat model.

## Run

From this repository root:

~~~shell
python3 -m unittest discover -s research -p 'test_*.py' -v
python3 research/validate.py all --output research/results/latest.json
~~~

The script imports the checked-out src/dateutil directly; it uses only the
Python standard library. In an Actions run, the CI JSON artifact contains
platform, Python version, results and limits. Read values rather than inferring
them from a passing workflow check alone.

## Reproduce actual downstream scheduler code locally

The optional Times Square integration test uses the actual source code of
`lsst-sqre/times-square`, pinned to commit
`4ed70b6c01094b7d00e20432049d4e796af6869d`.
It needs Python 3.14 and Pydantic 2.14.1, but does not run its server or
contact an external target. The GitHub workflow checks out the pinned source
and runs this case separately. Maximum 100,000 finite candidates; each child
has an eight-second timeout.

~~~shell
python research/integrate_times_square.py \
  --source-root research/third-party/times-square \
  --output research/results/times-square-latest.json
~~~

This is a code-level downstream compatibility/availability reproduction,
**not** proof of a remotely exploitable Times Square deployment.

## Interpreting the HTTP test

The included server is purpose-built and deliberately single-threaded. It
accepts strictly bounded recurrence text via HTTP JSON and models one
*possible* downstream misuse to test input-to-sink reachability
and head-of-line blocking. Its exposure is loopback-only and it is **not** a
real, identified vulnerable product. A real-world remote DoS claim requires
separate evidence of an attacker-controlled ingress, resource limits, process
architecture, and disruption of other users.

## Disclosure and next decision

This issue was publicly reported in 2020 and remains an existing upstream
discussion. Do not open a duplicate vulnerability report or request a CVE solely
on the basis of this lab. If concrete new evidence appears, first determine
whether it belongs in #1094 as a performance concern or should be submitted
privately via the repository's security reporting mechanism.

Findings should distinguish *confirmed*, *simulated*, and *not yet verified*.
