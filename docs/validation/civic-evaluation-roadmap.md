# Civic and provider evaluation roadmap

Baseline: PR #19 merged at `232a75478251972deb8354d08eb0304debc65deb`.
The reviewed 177 runtime/SQL/schema files still match the tested wheel manifest;
the final four-file two-pass review has no findings or coverage warnings. GitHub
CI was in progress; the operator's standing instruction waives waiting for it.

Authorized sequence: bounded interpretation diagnostic, MAT-046, then
MAT-023 → MAT-024 → MAT-037 → MAT-038 → MAT-039. MAT-040 qualification is conditional
on adequate independent held-out evidence. Its existence is not presumed.

Storage: reuse the existing environment. Free space at start was about 61 GiB;
task cap is 10 GiB, reserve 50 GiB, estimated peak growth below 1 GiB. Synthetic
provider receipts and generated check artifacts stay under ignored `data/validation/`.
No bulk corpus/media copies, new stack or container downloads are needed.

The diagnostic reuses PR18's synthetic inputs and existing MAT-033/034 question
templates through the typed renderer/executor and Matter's TypeSafe adapter.
It uses six maximum calls, `jev-1.14.0`, 30-second per-call timeout, zero retries,
240-second wall limit and 64 KiB request/response limits. The model was confirmed
in the official model reference on 2026-10-28. The expected directions are
agent-authored diagnostic notes frozen before calls, not independent evaluation
labels. This exercise does not publish core assessments or prove the StateCivics
runtime connection. No real delivery sink or action authority is installed.

The expected credential was found without printing its value or modifying `.env`.
Default diagnostic invocation performs local configuration validation only;
`--live` explicitly enables the authorized calls. Actual results follow after
the run. The installed walkthrough-schema packaging gap remains separate.

## First actual Matter/JEV interpretation diagnostic

All six calls completed in 2.069s and resolved `jev-1.14.0`; all responses were
primitive-valid. Original native/neutral response bytes, question/state digests,
pre-call expectations and capture results are retained under ignored
`data/validation/interpretation-live-20261028/`. The adapter observed 62,872 input
tokens in total; billing cost remains unavailable, not zero. There were no retries,
real deliveries or accepted-state mutations.

The model gave advisory recommendation support 0.98–0.99 while assigning only
0.01–0.02 to establishment of the compound claim that included binding adoption.
Duplicate novelty was 0.03–0.04 for the two audiences. These are useful observed
distinctions, not accuracy estimates. The privacy recommendation objective score
was 0.33 and novelty 0.27; correction objective was 0.72 but novelty 0.26. Finance
correction objective was 0.5. Those ambiguous audience results need adjudication
and tighter episode/objective definitions before any consequential policy.
The provisional expected directions are not independent ground truth. These
episodes are now exposed exploratory/tuning material, not untouched held-out
qualification cases. Successful calls do not complete MAT-039 or MAT-040.

MAT-046 follows next. Its planned `profiles/civic.py` path would collide with the
existing `profiles.py` module; use an optional `matter.civic` adapter and flat
packaged schemas, preserving the common core's import boundary. Existing
StateCivics KS-1105 uses the no-login KS-841 rehearsal and its replay transport;
that resource is reused by contract/fixtures rather than replaced or deployed.

The diagnostic inputs include authored structured facts/tags as well as synthetic
source text; this does not establish raw-document extraction accuracy. The
compound adoption claim and provisional expectation that duplicate relevance
should be high may confound the objective/novelty heads. Do not tune a release
threshold from these six exposed cases. Independent adjudication remains needed.

## Civic/query/replay/split implementation checks

The focused run `PYTHONPATH=tests .venv/bin/python -m unittest
unit.test_civic_profiles integration.test_explanation_queries
qualification.test_chronological_replay evaluation.test_splits -v` passed 29
tests in 177.891s (log `/tmp/matter-roadmap-focused.log`). A later focused run
passed the second synthetic lifecycle domain, the refusal of a self-qualified
recorded judgment, and the two existing actual policy-change/history checks
(4 tests, 31.596s; `/tmp/mat024-additional.log`). Named civic refusal assertions
passed all 13 civic tests (7.054s; `/tmp/mat046-named-refusals.log`).

MAT-023 uses one current-authorized snapshot and binds cursors to its read pins.
The concurrent split test exercises this backend's intentional rollback-journal
serialization: the writer commits after the read snapshot releases; it does not
certify WAL or arbitrary concurrency. Missing payloads remain unavailable; quiet
reasons and unobserved delivery outcomes remain distinct.

MAT-024 reuses actual claim, assessment, lifecycle, attention and query services
on fresh SQLite stores. Golden frames normalize only portable receipt aliases
and outcomes; native evidence/records are not rewritten. A late-published
cancellation with an earlier effective time cannot enter the earlier prefix.
Reference frames are authored synthetic conformance data, not independent labels.
MAT-037 groups whole episodes by source revision/hash, observation, occurrence and
provenance connectivity; records held-out exposure and refuses hidden packet
differences between principal arms. Empty/insufficient partitions do not qualify
anything.

The first two-pass source review covered 13 files without coverage warnings and
raised seven findings. Confirmed findings were fixed: assertion-specific review
currentness uses bounded existing fence history, overlapping withdrawals persist,
withheld sources fail availability, schema/runtime constraints agree, the joint
sitting example changes capacity within one recording, and refusal/mutation
tests are sharper. The fixes and new roadmap modules require independent review
before ticket closeout. Full regression and installed validation remain separate
unrun checks for this batch.

## Review boundary corrections and evaluator ports

The second two-pass review covered 22 files, with no coverage warnings. Its
confirmed corrections now retain generic control supersession as well as civic
withdrawals, restrict explanations to the selected assessment and paginate their
record detail, refuse future metadata cuts, bind recorded judgments to time/source
requirements, measure real outbox records in replay, and retain all previous
tuning assignments across split revisions. The review regression passed **36
tests in 207.091s**, log `/tmp/matter-review-regression.log`. A new source snapshot
and independent review cover these deltas plus the evaluator ports.

MAT-038's final focused run passed **2 tests in 204.921s** (`/tmp/mat038-focused-final.log`).
It runs actual fresh-store core episodes for A/B twice, plus missing-wire and
all-silent variants, and exact fixture response faults. Eight scheduled synthetic
decisions reconcile to 1 successful fixture admission, 3 abstained, 3 failed and
1 stale fixture decision. The admission callback is explicitly synthetic; it does
not turn raw results into actual qualified core judgments. Actual source-change
and missing-certificate guards remain separate existing service checks.

MAT-039's focused **5 provider-shaped tests passed in 0.200s**
(`/tmp/mat039-focused.log`). They use injected HTTP responses and a synthetic
OfflineReport schema fixture to isolate preflight/recovery; these are not live
provider trials or evidence that a new corpus passed offline. Missing/unselected
credentials, changed questions, insufficient cost, interruption, cached resume,
timeout, model mismatch and capture-only spies are covered. The only actual live
JEV calls in this task remain the six interpretation calls recorded above.

The current official model reference was checked again: Jev 1.14's published
input price is USD 0.042 per million tokens and output is free
(https://docs.typesafe.ai/models, checked 2026-10-28). The provider runner requires
an explicit dated price basis and conservative full-context reservations; native
billing remains unobserved. This does not retroactively change the first
diagnostic's recorded unknown billing/cost field.

MAT-040 has not run. Available checked-in and diagnostic cases are authored
synthetic/exposed examples; no independently adjudicated untouched held-out
qualification corpus or sufficient polarity/episode support has been established.
No thresholds/certificates are fitted or issued from these cases. The installed
walkthrough-schema lookup remains a separate packaging validation gap.

## Runner review corrections and installed boundary

The third two-pass review covered 20 files with no warnings and six findings.
Corrections preserve model/usage safety stops on resume, require A/B × corpus
episode coverage and a kind-B candidate, preflight the existing adapter's actual
wire shape/byte bound, separate non-dispatched rows from observed transport
attempts, and atomically publish private artifact files. The offline callback
checks exact candidate-row routing while keeping unqualified results shadow-only.
Ten provider-shaped tests passed in 0.445s (`/tmp/mat039-final-focused.log`),
including an interrupted result publication after an observed transport attempt.
No actual live call was made by those tests.

The complete second review also identified an authority-history availability
problem. Civic resolution now scans newest-first only since the oldest selected
review, skips older unrelated global history, and permits recovery by a fresh
host review when the bounded tail is too old. Sixteen civic tests passed in
60.925s, including 257 real unrelated scope-wide controls and successful recovery
(`/tmp/mat046-history-bound.log`). Recorded host controls now have explicit cut
bindings; their future contents are withheld from earlier replay requests.
The targeted control check passed (`/tmp/mat024-controls.log`).

The a7052be installed wheel imported 86 modules and loaded all three new schemas.
Its SHA-256 was `4363652e51513166385c383f99222b56356555e9b30393aa914458969250c532`.
The installed walkthrough default still raises FileNotFoundError; this is a
confirmed separate packaging gap, not a green installed full suite. This wheel
precedes the final review deltas and is not the final source-byte claim.
Existing actual source-currentness/missing-certificate/conflicting-head service
checks passed 3 tests in 7.242s (`/tmp/matter-existing-admission-guards.log`).

Final source freeze, full checkout discovery and review closeout follow below.
New evaluation/qualification test directories are packages so ordinary discovery
includes them. No additional provider trial or empirical qualification is implied.
