# MAT-083 bounded follow-up, 2026-10-31

Status: **closeout candidate, post-fix review pending on 2026-11-02**; see the final
section below. The earlier dated checkpoints remain historical. The observed
SQLite timeout mechanism is repaired by the already-merged MAT-085 validation
cache; PR #43 removes the demonstrated functional-clock exposure. This is not
forensic certainty about the uninstrumented historical schedules. No new
storage retry, contention classifier or weaker assertion is introduced.

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

Closeout: all **18 repository-integrity checks** passed in 0.677s;
`render --check`, `validate` (90 tickets, 107 requirements, 109 schemas,
three walkthroughs) and `git diff --check` passed. The independent subscription
review completed its default **two rounds**, reviewing the new Python test and
canonical ticket JSON: **zero findings, zero warnings**, 411.1s. The configured
rules excluded four Markdown files; those were checked manually against the
actual logs and referenced host records, not described as independently reviewed.
The raw result is `data/validation/MAT-083-current/review.json`. The subsequent
closeout edit adds only this validation paragraph; reviewed Python/JSON did not
change.


## Controlled functional-test clocks, 2026-11-02

Starting code was `447a55bec7669488108e7641cdc380982c862564` (dev20).
A bounded probe now reproduces both retained semantic **symptoms** under
controlled elapsed exhaustion, without a provider or production data:

- Advancing the stage envelope's monotonic clock to 11s after the selection
  prerequisite expires preserves `b_recovery=E_DEPENDENCY_STALE` but blocks
  independent `c_contradiction` with `E_BUDGET_EXHAUSTED`, `elapsed_limit`.
- Letting the replacement assessment's graph finish after its one-second
  profile envelope (1.001s), while remaining inside the separate ten-second
  publication request budget, retains an unusable timed-out attempt. The
  replacement enqueue returns `withheld`, `insufficient_evidence`, matching
  the retained failure's observable symptom. This is not a SQLite error.

The original CI logs do not retain enough attempt diagnostics to establish that
these were their actual causes. The clocks are a demonstrated test exposure,
not retrospective proof. Initial probe drafts crossed the wrong budget or
tried to replace a read-only evaluator method; those harness errors are retained
and are not runtime defects or passing checks. The corrected probe uses the
existing typed graph and evaluator with a bounded class-level test patch.

The cancellation/withdrawal test now injects a fixed graph clock only for its
replacement evidence attempt. The qualification-expiry stage fixture also uses
an explicit monotonic clock. Assertions are unchanged: replacement must be
ready, independent work must complete, and old work tokens remain unusable.
A new counterpart exhausts the stage envelope deliberately and requires the
independent branch to remain blocked with no contradiction-provider invocation.
The existing late-graph diagnostic test and real SQLite lock-expiry tests pass.
No production time limit, SQLite timeout, retry or error classification changed.

Affected selection: full dispatch-race file, controlled contention pair, full
stage file and late-graph deadline check: **38 tests passed in 81.125s**.
Raw metadata and the probe stay under ignored `data/validation/MAT-083-clock/`:
`clock_probe.py`, `diagnostic4.log`, `affected.log` and the earlier draft outputs.
The original SQLite interleaving still lacks a reproduced cause, so MAT-083
remains in progress. This test repair does not clear that separate requirement.

The two-round independent review covered 4/4 selected files with zero findings
and warnings. Documentation was checked manually against the retained probes
and 38-test receipt. The trailing whitespace found by the first diff check was
removed before closeout; runtime source and production limits are unchanged.


## Final causal comparison and disposition, 2026-11-02

The new [bounded diagnostic](../../conformance/sqlite_contention.py) reuses the
**unchanged equivalent-intent race assertion**, real handles, native services,
control/budget checks and injected synthetic transport. It traces transaction
verbs, synthetic command IDs, numeric SQLite errors and durations, never SQL
values. The profiler deliberately increases execution cost. It is not an
unprofiled speedup benchmark or a production/throughput qualification.

### Reproduced failure and isolated cause

1. Existing dev16 image `ks-test-runner:matter-1f525c6`, Python 3.11.17 / SQLite
   3.46.1: **original test failed** in 33.519s. The waiting `BEGIN IMMEDIATE`
   raised **SQLITE_BUSY (5)** after 5.155s; its result stayed honest retriable
   `E_STORAGE_UNAVAILABLE`. The other worker committed ready after holding the
   writer lock about 12.356s. No sleeps, reduced timeout, SQL change or retry.
2. Existing dev20 image `ks-test-runner:matter-401f1a4`, same Python/SQLite:
   the same profiled old fixture **passed in 9.195s**, ready/stale and one send.
3. Causal control on that **same dev20 image**: disable only successful
   structural-validation caching (`ValidationCache(max_entries=0)`), leaving
   all validations and native checks enabled. The initial comparison failed in
   32.274s with SQLITE_BUSY at 5.110s. The final committed diagnostic repeated
   the failure in **30.128s**, writer lock **10.890s**, SQLITE_BUSY at **5.173s**.
4. Restore normal caching in that same image; the final diagnostic passed
   **twice**, **9.147s and 9.002s**. Writer locks were **1.478s and 1.451s**.
   Both preserve the original ready/stale assertion and the winner's one send.

The dev20 image is pinned to
`sha256:a240d63c2b62498ca0b1f1532f664203576a4e22d1c8b19e1ad3ebd0d56f68a0`.
Both same-image conditions use the exact tests archived from `1f525c6`, isolated
network-disabled read-only containers with a 64 MiB temporary filesystem.
Only the in-process cache setting differs. No image, host stack or installed
package was modified. The final comparisons used the committed diagnostic's
logic; its subsequent interpreter guard does not change the Python 3.11 path.

This demonstrates an avoidable writer-lock pressure cause: repeated schema
validation can make a normal bounded waiter expire. **MAT-085's existing cache
already repairs that cause**; this follow-up adds diagnosis and preserves the
strict regression, not speculative persistence logic. It does not prove the
old uninstrumented 30.536s incident had exactly this schedule. Genuine timeout,
I/O and indeterminate commits still require honest unavailable results and exact
original-command recovery, never automatic success or a transport retry.

### Other findings and current-runtime verification

The two retained intermittent fixtures demonstrably mix functional assertions
with short wall-clock envelopes. The controlled exhaustion probes and PR #43's
fixed test clocks give their evidenced disposition: functional intent tests no
longer depend on machine speed; separate actual-expiry tests still require the
independent branch to be blocked and late graph output to be unusable. Old CI
logs lack attempt telemetry, so their precise historical schedules remain unknown.
Those original failed receipts are not relabelled passes or attributed to SQLite.

The full suite against `892d030` passed **1,566 tests in 1,307.074s**, including
those strict cases, controlled real lock expiry/recovery, validation-cache
integrity/revocation tests and delivery-unknown controls. Runtime source is
unchanged by the diagnostic/closeout. The final diagnostic also passed on the
checkout **without profiling**, dev21 / Python 3.12.14 / SQLite 3.53.1, in
**6.264s**, writer lock **0.449s**, ready/stale and one send.

An initial checkout profiler run errored because Python 3.12 refused concurrent
cProfile instances ("Another profiling tool is already active"). This was an
instrumentation error, not a storage outcome. The diagnostic now refuses profiler
mode outside the validated Python 3.11 interpreter before constructing a fixture;
transaction tracing remains available on the supported SDK interpreters. No
failed instrumented run is counted as a pass.

Reproduce on a suitable checkout/interpreter:

```sh
PYTHONPATH=tests python conformance/sqlite_contention.py
# Python 3.11 only; deliberately instrumented comparison:
PYTHONPATH=tests python conformance/sqlite_contention.py --profile
PYTHONPATH=tests python conformance/sqlite_contention.py --profile --disable-validation-cache
```

The cache-disabled profiled comparison is expected to fail the original race
assertion when the writer exceeds the real default timeout. It is diagnostic
evidence, not an acceptable normal result. No default test assertion was changed.
The prior controlled-timeout case separately verifies exact-command recovery,
one charged delivery, no held quota and no duplicate send.

Raw receipts and old test archive remain under ignored
`data/validation/MAT-083-profile/`: `before.log`, `after.log`,
`current-cache-off.log`, `final-cache-off.log`, `final-cache-on-1.log`,
`final-cache-on-2.log`, `checkout-profile.log` (instrumentation failure) and
`checkout-traced-final.log`. The earlier raw scripts remain historical drafts.
This closes the bounded neutral regression investigation; it establishes no
new provider interpretation, qualification, physical power-loss guarantee,
arbitrary-load concurrency SLA, receiving deployment or activation authority.


### Diagnostic review corrections

The initial two-round review completed **4/4 selected files**, no warnings.
Its four confirmed findings were repaired: JSON now distinguishes assertion
failures, errors and skips/missing execution with separate exit statuses;
commit-time SQLite errors retain their numeric code/name and duration; the
unsupported-interpreter test now fails if a patch stack or runner starts; and
canonical completion stays in progress until closeout evidence is recorded.

**Four new diagnostic tests passed in 8.514s**. They include the unchanged real
unprofiled race, deliberate setup error/assertion/skip classification, a real
native transaction with an injected commit I/O fault (no transport, honest
unavailable, explicit COMMIT error, no false commit exit), and the early guard.
Expected nested diagnostic failures in that log are negative controls, not
passing runtime races; the enclosing four-test verdict is OK.

The repaired script repeated the same-image profiled control: cache disabled
**30.296s**, `assertion_failure`, one failure/zero errors/zero skips; cache
normal **8.973s**, `passed`, zero failures/errors/skips. Logs:
`review-fixed-cache-off.log`, `review-fixed-cache-on.log`,
`diagnostic-tests-postfix.log`. Post-fix review is pending; no production source
or frozen SDK wire changed.
