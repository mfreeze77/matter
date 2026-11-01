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
