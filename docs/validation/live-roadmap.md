# Live connectivity and the next Matter roadmap

## Scope and baseline

The current batch starts from PR #15 merged at `c755dd9`. It implements
Matter-owned MAT-017/018, then MAT-019/020 and MAT-029/030/031/032 in canonical
dependency order, with MAT-072 access/egress guards before real/private input.
PostgreSQL, civic/DIAT work and MAT-039/040 evaluation remain out of scope.
All nine tickets are now recorded done after their acceptance, review and
verification contexts below. Hosted CI is informative; the operator does not require
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
integration in `e974bf0`. At this development milestone MAT-017/018/072 remained in progress while
combined checks and independent review findings were reconciled.

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
The contract declares no implicit positive-only intent. The completed adapter/remediation two-pass review is recorded in the final
closeout below.

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
suite supersedes them for the final gate. Completed final regression and two-pass remediation results are recorded below.

The receipt remediation passed 33 focused checks in 78.406 seconds and 91
portable checks in 6.647 seconds. Its final three-file two-pass review covers
`ba59098..60b0e75`. The local task footprint is approximately 49 MiB, below the
1-GiB task budget and with more than 50 GiB free reserve.

## Final completion and remaining limits

Completed: **MAT-017, MAT-018, MAT-019, MAT-020, MAT-029, MAT-030, MAT-031,
MAT-032 and MAT-072**. [PR #16](https://github.com/mfreeze77/matter/pull/16)
tracks this batch; hosted CI is informational under the operator's merge instruction.
The backlog now has **29 done and 51 planned**, with no in-progress/blocked records.
Of the 51 planned items, 29 belong to Matter and 22 are cross-repository roadmap
tracking. Those repositories were not implemented or deployed by this batch.

Final runtime/schema source is `60b0e75`. Its isolated dev14 wheel SHA-256 is
`e0689ca870017dc6ad4ad89cbb374366985d6ffcccc67e59a23921e934f396cd`.
All 162 Python/SQL/schema files match source bytes, including 88 packaged schemas;
73 Matter modules import within the fresh environment with no provider SDK.
The runtime dependencies/jsonschema were available. The root build environment
initially lacked setuptools; cached setuptools 84.2.1 supplied the existing build
requirement. No environment blocker remains for the completed ticket scope.

Full installed discovery ran **1,196 tests in 1,555.793 seconds**, exit 1, with
**29 errors**. Every error is the existing checkout-only walkthrough default's
`schemas/walkthrough.schema.json` lookup under the installed interpreter's library
directory, in `test_hardening` or `test_repository`. This is not a green full run.
The other **1,157 tests passed**. The two affected modules contain 39 tests;
`PYTHONPATH=tests .venv/bin/python -m unittest test_hardening test_repository -v`
passed all **39 in 0.931 seconds** in the supported checkout context. Their fixture
lookup behavior was not changed into a broader packaging implementation. The
installed CLI with an explicit `--root` passed validation and all three synthetic
walkthroughs. The combined receipt, original failure trace and successful rerun
remain in external `combined-validation.json`, `roadmap-final-full.*` and
`checkout-scaffold-rerun.log`; the failure is retained rather than relabeled a pass.

`b1b490d` is a test/documentation-only delta: each of ten malformed journal cases
now independently exercises its intended counter/shape failure. The affected
behavioral test passed in 2.733 seconds. Runtime and schemas stayed byte-identical
to the tested wheel. The initial receipt/admission review covered 28 selected files
with four findings: three confirmed defects were fixed and the inferred positive-only
stage restriction was rejected against the explicit host predicate contract.
The adapter/admission follow-up reviewed all 9 files in two passes with zero
findings/warnings. Receipt remediation reviewed all 3 files in two passes and
found the masked test assertion; its final one-file two-pass review returned zero
findings/warnings. No review group was skipped. Earlier foundation, attention,
timer and stage review remediations are recorded above and in each ticket receipt.

Repository render/validation and the independent JavaScript verifier passed
(26 canonical and 8 exact-source vectors). Source review, synthetic checks,
recorded replay, live connectivity and empirical qualification remain separate.
The single earlier Oil live smoke succeeded; **the new Matter adapter has only
synthetic/injected and recorded-response tests, with zero additional live calls**.
MAT-039/040 empirical evaluation/qualification, PostgreSQL, MAT-046 and DIAT remain
deferred. Full delivery/outbox and other later backlog work are not completed by
this segment. Real/private evidence was not sent; future egress requires installed
MAT-072 policy and current original host authority. Credentials remain outside Git.


## MAT-021 delivery milestone

MAT-021 is implemented and validated; integration is tracked in
[PR #17](https://github.com/mfreeze77/matter/pull/17). The canonical backlog now
contains **30 done and 50 planned**, with none in progress or blocked. Of the
remaining tickets, **28 belong to Matter** and 22 track other repositories.

The [delivery guide](../delivery.md) covers immutable intents, exact caller and
attention-allocation binding, finite leases/fences, original-context withdrawal
of never-authorized work, one injected send, lookup-only reconciliation and
independent observed outcomes. Unknown sends block equivalent redispatch; an
actual milestone alone advances delivered knowledge. No native channel adapter,
resend scheduler, civic profile or downstream integration was introduced.

The [MAT-021 receipt](MAT-021.md) records **1,237 passing tests in 2,787.687s** on
frozen base `dcf1a79`, with unchanged runtime/schema/test manifests. Final bounded
outcome delta `1590446` passed **2 checkout and 2 installed targeted checks**;
those checks are separate from the base full run. Eight corrected-base installed
checks also passed. All **174** runtime/SQL/schema files match the final wheel and
integrated source, including **98 schemas**; all 74 submodules import from the
installed environment with no provider SDK. The final three-file independent
review completed in two passes with zero findings or warnings. Earlier findings,
failed development probes and the interrupted first full attempt remain recorded.

The installed walkthrough default schema lookup was rechecked on the final wheel
and still fails; the prior 29 installed-full errors remain a packaging gap.
Checkout passes do not resolve it. No new live JEV call, real notification,
private evidence or empirical qualification occurred. StateCivics profiles and
receiving integration, MAT-039/040 evaluation, PostgreSQL and cross-repository work
remain outside this completed slice. MAT-022 and the MAT-023 → 024 → 025 chain
retain their canonical scope and prerequisites.

## MAT-033/034 shadow question families

The [family guide](../semantic-families.md) and
[validation receipt](MAT-033-034.md) track 15 versioned association, independent
claim/evidence, explicit change-cause, matching recovery and audience-contribution
questions. They reuse the existing registry, prepared packets, executor, budgets,
receipts and host lifecycle/attention services. A bounded context transform adds
exact as-of host definitions and authority dependencies; a diagnostic projection
preserves unknown qualification and grants no action authority.

Final checks passed 186 semantic and 17 access methods, plus 56 selected installed
methods including all 17 family cases. The final four-file delta review completed
two passes with zero findings or warnings. Preparation 1.1 pins nested reference
metadata at the original cut, preserves unknown-source coverage, and keeps later
matter edits out of rebuilt historical packets. The receipt separately records
the pre-fix full run's macOS temporary-path failure and its successful targeted
rerun; no clean full final-source run is claimed. Reused PR18 context inputs remain authored
synthetic fixtures. They do not establish a StateCivics runtime connection or
observed JEV usefulness. Current source-head tracking must be explicitly declared
by the host/profile so a correction invalidates queued advice; this reuses the
existing dependency machinery and belongs in MAT-046's integration contract.

The installed walkthrough-schema lookup still fails separately. No new live
provider call, qualification, real alert, native delivery adapter or receiving
application change is part of these shadow families.
