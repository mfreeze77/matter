# MAT-083 bounded follow-up, 2026-10-31

Status: investigated, **not repaired or closed**. MAT-083 already covers the
SQLite dispatch-race failure observed on main; a duplicate ticket was not added.
No new storage retry, contention classifier or weaker assertion is introduced.

## Executed evidence

The unchanged installed dev16 (`1f525c6`, runtime identical to frozen main
`35f330a`) cross-handle equivalent-intent race passed in 53.027s. A second
unchanged run recorded transaction-boundary traces with Python 3.11.17 and
SQLite 3.46.1: both handles entered concurrently, intent-b committed ready, and
intent-a waited then returned E_DEPENDENCY_STALE. The writer's locked section
was 3.901s; the stale loser's transaction was 3.693s. Both returned truthfully,
with one observed send. No original failure was reproduced.

The same diagnostic on the dev17 wheel held the writer lock for 0.552s and the
loser's transaction for 0.476s, again ready/stale with exactly one send. This
reduces lock pressure; it does not prove the retained failure's cause. Normal
SQLite lock waits remain bounded at the configured timeout (five seconds by
default). An actual timeout or uncertain durable outcome must remain honest
E_STORAGE_UNAVAILABLE, not be relabelled duplicate suppression.

The three exact retained tests (equivalent intents, replacement after cancelled
work, and independent-stage qualification expiry) passed in one current-candidate
run (21.331s), then three bounded repeat trials, all **nine checks passed**,
with no errors/skips. Trial elapsed times were 25.20s, 23.23s and 22.41s;
Python 3.12.14, SQLite 3.53.1. Assertions were unchanged. The expiry stage still
must complete the independent branch; replacement still cannot renew the old
token, double-send or double-charge.

## What is unresolved

The original race returned E_STORAGE_UNAVAILABLE; the two earlier CI failures
returned insufficient_evidence for the replacement and blocked the independent
stage. Their exact retained evidence remains in [the intake](MAT-083-intake.md).
The writer-lock measurements establish a plausible five-second contention
mechanism, not the actual failed interleaving. The two intermittent semantic
failures have no demonstrated common cause and are not dismissed as flaky.
No unsupported SQLite implementation change was made. A controlled failing
interleaving or demonstrated independent cause is still needed before closure.

Small raw receipts, trace harness and stdout are retained under
`data/validation/manager-closeout-20261031/`: `race-before.log`,
`race-before-traced.log`, `race-after-traced.log`, `mat083-targets-final.log`,
`mat083-repeated.json/log`, and `race-trace.py`. The trace logs record only
transaction verbs, synthetic command IDs, outcomes and durations, not SQL values.
Live JEV interpretation, empirical qualification and production activation are
outside this follow-up.

## Controlled current-runtime checks, 2026-11-02

Starting main was `d1f311b42ddf2ec24919e6f74cb4b0de515f7a27`
(dev19). The three exact retained tests passed unchanged in **20.417s** on
Python 3.12.14, SQLite 3.53.1, macOS 26.6.2/arm64. Neither the original race
failure nor either intermittent semantic failure was reproduced.

New [controlled contention tests](../../tests/integration/test_dispatch_contention.py)
use independent real SQLite handles and events at the existing transaction
fault seam and the waiter's `BEGIN IMMEDIATE` entry. They do not use sleeps,
change runtime code, extend the normal timeout or relax the original assertion:

- Release the writer after the contender reaches its transaction entry: one
  ready winner, one `E_DEPENDENCY_STALE` loser.
- Keep the writer locked while a deliberately short **test-only 0.05s** waiter
  timeout expires: honest retriable `E_STORAGE_UNAVAILABLE`, no losing command
  journal. After releasing the writer, retry the exact original losing command:
  stale, then an identical journal replay. This is an intentionally induced real
  timeout, **not reproduction or repair of the historical unexplained failure**.
- Both schedules verify one winner send, exact send retry without another
  transport call, a delivered baseline, one charged delivery and no held quota.

The pair passed in **14.618s**, then passed again in the affected **24-test**
run (**104.439s**, no failures/errors/skips). That run includes the complete
dispatch-race file, storage interruption/fault tests, crash-after-external-send
and timeout-without-transport-recovery checks, and the named independent-stage
expiry case. The original three-test baseline and this affected run both cover
the cancelled-work replacement. No whole-repository suite or provider call ran.

An initial draft of the new tests reached their final quota assertion and
errored twice because it read `attention_budget` from the delivered result
instead of the authorization's reservation. That test error was corrected
before the passing runs; it is not a runtime storage failure.

Raw receipts are retained in `data/validation/MAT-083-current/`:
`baseline.log`, `controlled.log` (the draft errors), `controlled-final.log` and
`affected.log`. MAT-083 remains **in progress**, completion `not_run`:
controlled ordinary contention and genuine timeout now have executable evidence,
but the old failing interleaving and the two intermittent causes remain unknown.
No speculative persistence repair, automatic retry or failure reclassification
is justified by these results.
