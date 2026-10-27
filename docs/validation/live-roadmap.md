# Live connectivity and the next Matter roadmap

## Scope and baseline

The current batch starts from PR #15 merged at `c755dd9`. It implements
Matter-owned MAT-017/018, then MAT-019/020 and MAT-029/030/031/032 in canonical
dependency order, with MAT-072 access/egress guards before real/private input.
PostgreSQL, civic/DIAT work and MAT-039/040 evaluation remain out of scope.
Tickets remain in progress until their actual acceptance evidence and relevant
checks are recorded. Hosted CI is informative; the operator does not require
waiting for it before authorized merges.

## Bounded synthetic live diagnostic

A single Noul question asked whether an explicitly synthetic message stated
that a lamp was on. The selected model was `jev-1.14.0`, verified against the
[official model reference](https://docs.typesafe.ai/models). Timeout: 30 seconds;
maximum provider calls: one; retries: zero; redirects disabled.

The existing Oil `SystemOneHTTPBackend.ask` at local source revision
`14772cd10b4fc3d3b54768a131de3acb45b5fde4` was inspected and used read-only.
The first configuration check was blocked by absent `TYPESAFE_API_KEY` and made
zero provider calls. After the operator supplied the ignored, untracked local
`.env`, the credential was loaded into the diagnostic process only. No key or
other secret value was printed, logged or committed, and the file was not edited.

The sole live provider call succeeded in 0.365 seconds. The response resolved
`jev-1.14.0` and contained the requested Noul with a numeric value in [0,1].
This confirms connectivity/authentication and one response shape only: it is
not provider qualification, empirical accuracy, live usefulness or completion
of MAT-032. No host state or delivery action was driven by the answer.

Synthetic request, original response bytes and the receipt are retained outside
Git at `/var/folders/hn/c0zg49fj73g5bnwl67mj83mm0000gn/T/matter-live-roadmap-heevp_pv/live-attempt-1/`.
The earlier zero-call blocked receipt remains in the parent directory. Raw bytes
were checked for accidental credential inclusion before writing. No additional
live calls are part of default tests or assumed necessary for later ticket
completion. Exact response digest and source digest are in the external receipt.

## Storage and verification budget

The existing constrained Python environment is reused. Initial free space was
87 GiB, with a 50 GiB reserve and below-1-GiB planned additional task output.
Small source/test/review logs are retained in the external task directory above;
no corpus, media, model or container downloads are planned. Focused behavioral
checks precede dependent development, followed by relevant combined checks and
independent review. No repeated hosted reruns or CI-only debugging is planned.

## Integrated foundation milestones

The task branch records context/disposition implementation in `1796790`, access
controls and the shared current-assessment reader in `e134e9d`, and lifecycle
integration in `e974bf0`. Canonical MAT-017/018/072 remain in progress until the
combined checks and independent review findings have been reconciled.

Focused local evidence on 2026-10-27:

- MAT-017: 15 actual SQLite lifecycle episodes passed in 246.451 seconds after
  integration with the common assessment gate.
- MAT-018: 14 scoped context/disposition checks passed in 21.334 seconds.
- MAT-072: 110 access, assessment, packet and renderer checks passed across the
  focused runs recorded in its receipt.
- The shared view-local current reader passed two new behavioral checks in
  2.939 seconds, then five targeted current/profile/source/read-denial regression
  checks passed in 6.257 seconds after the public reader adopted the same gate.

The full local regression run on committed `e974bf0` passed **1,051 tests in
707.244 seconds**, exit 0, in an isolated checkout while MAT-019 implementation
proceeded. The command used the existing `.venv` with the physical temporary
path to avoid the known macOS `/var` versus `/private/var` backup-path alias.
Its log and command receipt are retained as `foundation-full-suite.log` and
`foundation-full-suite.json` in the external task directory. This run predates
the independent-review remediations and MAT-019; those changes require their
own subsequent checks. No hosted CI rerun or further live call is required
by this run. These checks establish synthetic local behavior, not empirical
provider accuracy, real evidence egress or a qualified deployed runtime.

The two-pass independent reviews completed without skipped groups or warnings:
MAT-018 reviewed 10 files, MAT-072 reviewed 8, and MAT-017 reviewed 11. Their
findings are being reconciled against the actual code. Confirmed fixes include
context/disposition version and expiry handling, exact declaration namespaces,
pre-evaluation access coverage, historical access versus work freshness,
timeless access-aware cache identity, and lifecycle basis independence from
mere current-assessment replacement. None is represented as completed merely
because the preceding regression run passed.

## Current authority under advancing host clocks

Timer integration exposed an existing MAT-011 availability defect: current
control checks required a caller's earlier clock sample to equal a new clock
read exactly. A microsecond-advancing host clock could therefore refuse valid
work. The shared guard now always uses freshly sampled host time; an earlier
hint cannot backdate authority, and a future hint remains refused. No authority
window, token recapture or new clock service was introduced.

Four targeted behavioral checks passed in **3.278 seconds**
(`/tmp/matter-current-clock.log`): actual assessment publication/current reading
with a clock advancing on every read, later source READ denial including replay,
a past hint against a present stop/denial, a refused future hint, and clock
regression before a committed governing restriction. The full control suites
and independent follow-up review remain integration checks.

## Attention and scheduling development milestones

MAT-019 was committed in `9691f11`: 5 pure projection checks and 11 actual SQLite
integration checks passed, the latter in 255.876 seconds. The integrated access,
metadata, derived assessment and resolved lifecycle case retained all original
work contexts and refused publication/replay after a real source READ denial.
MAT-018's remediation passed all 16 focused checks; MAT-072's remediation passed
118 focused checks. Their receipts record individual commands and overlap.

MAT-020's development evidence is 9 runtime checks in 76.232 seconds, 77 portable
contract checks in 4.278 seconds, then 3 final targeted checks in 41.335 seconds.
These cover actual deadline attention with unchanged semantics, cross-connection
quota races, restart/catch-up, conservative precharge, expiry/release, independent
attention limits, direct stop, and access-protected timer replay. Its runtime
file now has 11 tests; a final combined run is still required. Four additive
operations preserve the old 24, with 28 operations and 58 success pairs total.

The next implementation milestone is MAT-029 staged semantic execution over
actual committed resource allocations. A frozen follow-up review is checking
`880a887..9691f11` in the isolated checkout while this work continues; its result
has not yet been reported as clean. Hosted CI is not a merge gate.


The frozen committed `d934647` snapshot passed **1,132 tests in 1,335.361
seconds**, exit 0, with physical `TMPDIR`. Logs and the command receipt are
`attention-scheduling-stages-full.log` and `.json` in the external task directory.
It includes the lifecycle, access, attention, timer and stage review fixes,
and predates MAT-030/031/032. The last timer boundary-drift delta subsequently
passed its two targeted checks in 28.405 seconds; later semantic additions still
require their combined regression and package checks.
