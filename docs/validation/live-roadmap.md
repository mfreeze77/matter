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
confirmed findings were reconciled in the committed foundation fixes. These include
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
regression before a committed governing restriction. The 32 existing control integration checks subsequently passed in 18.200 seconds
(`/tmp/matter-current-control-regression.log`). The advancing-clock fix was also
included in the later 1,132-test snapshot below.

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
attention limits, direct stop, and access-protected timer replay. Later review fixes added scoped replay and orphaned-timer checks; the final
boundary-drift delta and combined snapshot are recorded below. Four additive
operations preserve the old 24, with 28 operations and 58 success pairs total.

MAT-029 staged semantic execution was committed in `02e4c13`, with review
remediation in `8aa71b6`. Its 19 focused checks passed in 35.210 seconds. The
completed two-pass attention, scheduling and stage reviews had no skipped groups
or warnings; confirmed findings were fixed in `c137031`, `d934647` and
`8aa71b6`. The subsequent remediation review found one timer/access-boundary
drift case, fixed in `c9a0e76`. Hosted CI is not a merge gate.


The detached-code `d934647` snapshot passed **1,132 tests in 1,335.361
seconds**, exit 0, with physical `TMPDIR`. Logs and the command receipt are
`attention-scheduling-stages-full.log` and `.json` in the external task directory.
It includes the lifecycle, access, attention, timer and stage review fixes,
and predates MAT-030/031/032. The last timer boundary-drift delta subsequently
passed its two targeted checks in 28.405 seconds; later semantic additions still
require their combined regression and package checks.

## Durable semantic execution and admission milestone

`6a978cc` integrates MAT-030 and MAT-031 over the existing storage, controls,
budgets and dependency registration. MAT-030 passed 27 behavioral checks in
54.337 seconds, including actual durable pre-I/O claiming, protected dispatch,
transitive parent-source access and stage reuse with zero new calls. MAT-031
passed 12 checks in 54.006 seconds, including failed held-out rejection, exact
identity matching, separate abstention and actual assessment invalidation after
certificate revocation. The shared portable contracts passed 106 checks in
6.871 seconds: 12 core kinds, 30 operations, 60 success pairs, 224 synthetic
vectors and 88 schemas. Their [receipt](MAT-030.md) and
[admission](MAT-031.md) validation records give the exact commands and limits.

At this milestone, two-pass source review of `d934647..6a978cc` and the
injected-only MAT-032 adapter were still in progress. Their subsequent gates
are recorded below. No new
live call or real/private evidence was sent, and no empirical certificate was
issued.

## Integrated adapter and final gates

`ba59098` integrates MAT-032's one optional stdlib HTTP adapter. Its 16 focused
checks passed in 68.842 seconds, including actual SQLite execution, budgets,
access and admission services with synthetic injected responses. Offline replay
of the earlier live response preserved all 120 native bytes and their digest,
resolved `jev-1.14.0`, and remained unqualified. It made zero new live requests.
See the [adapter validation receipt](MAT-032.md). The new Matter adapter has not
itself been tested against the live endpoint.

Read-only integration review found and fixed certificate backdating and too-small
accepted polarity support in `f313444`, followed by 14 passing admission checks
in 61.268 seconds. Attempt recovery now requires its original consumer/context
and actual lineage (`856096d`): 30 receipt checks passed in 59.496 seconds.
`6a27cff` additionally rejects float/integer lookalikes in recovery allocation
pins; its two affected checks passed in 5.391 seconds.

The two-pass `d934647..6a978cc` review completed: all 28 selected files reviewed,
four findings, no warnings or skipped groups. Three receipt/journal findings
were verified and fixed in `60b0e75`: logical request ID collisions on reuse, missing guarded dispatch
checked after claiming work, and under-specified attempt counters. The polarity
finding was rejected after source/contract review: a host edge can deliberately
consume reviewed negative evidence, its exact predicate still applies, abstention
is excluded, and qualification grants no affirmative conclusion or action power.
The contract declares no implicit positive-only intent. The adapter/remediation
range has its own two-pass review in flight.

A wheel at `6a27cff` built successfully and was installed in a fresh environment
with constrained runtime dependencies and no provider SDK. Its 232 selected
portable, semantic and timer checks passed in 419.746 seconds. A subsequent
`60b0e75` wheel includes the receipt/journal review fixes. All 162 packaged Python/SQL/schema
files match their sources byte for byte, including 88 schemas; all 73 imported
Matter modules resolve inside that installed environment. The initial byte-proof
script omitted the existing `schemas/__init__.py` package mapping; correcting
the verifier made the exact comparison pass without a source change. The final full suite now uses the `60b0e75` wheel in that fresh environment and
an exact Git archive of matching repository assets, with no editable import
mapping. Both code and schema import paths were verified inside the fresh
environment before dispatch. The earlier `ba59098` attempt was deliberately
stopped after 536.546 seconds because editable package mapping resolved
`matter._schemas` from the active root. Its aborted log/receipt remain external
as `roadmap-editable-aborted.*`; it is not a passing gate. The earlier 1,051/1,132
counts are observed development results with detached code and editable schema
resources, not fully isolated release snapshots. The corrected installed full
suite supersedes them for the final gate. Final regression and two-pass
remediation review remain pending.

The receipt remediation passed 33 focused checks in 78.406 seconds and 91
portable checks in 6.647 seconds. Its final three-file two-pass review covers
`ba59098..60b0e75`. The local task footprint is approximately 49 MiB, below the
1-GiB task budget and with more than 50 GiB free reserve.
