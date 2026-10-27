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

A full local regression run is checking committed `e974bf0` in an isolated
checkout while MAT-019 implementation proceeds. Its result will be recorded
when the command finishes. No hosted CI rerun or further live call is required
by this run. These checks establish synthetic local behavior, not empirical
provider accuracy, real evidence egress or a qualified deployed runtime.
