# Civic and provider evaluation roadmap

Later public-source checkpoint (October 28): the bounded MAT-048/MAT-049 slice
now imports a retained crawler recommendation and separates source-only reading
from two audience judgments through the existing rehearsal. Five live calls,
eight decisions and four isolated captures (including two synthetic error
controls) ran; stage/adoption restraint was useful, but stance and positive
land-use relevance were underconfident. No qualification or production alert.
[Exact source, connected receipts and open scope](civic-source-integration.md).
DIAT is explicitly excluded.

Current connected checkpoint (October 28): StateCivics KS-1118 now exercises the
existing no-login rehearsal route → actual JEV → Matter attention → existing
capture sink. The final guarded run made 45 live `jev-1.14.0` calls, 48 decisions
and 15 in-app captures, with no production alerts. Initial plus post-hardening
runs made 90 actual calls in total; repeated cases are not independent support.
Eight illustrative treatment differences and threshold variation remain visible.
See the [connected receipts and quality limits](statecivics-monitoring-replay.md).
Those later results do not retroactively make the historical diagnostics below
connected runtime evidence, nor do they qualify MAT-040.

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

At the diagnostic checkpoint MAT-046 followed next; its implementation and later checks are recorded below. Its planned `profiles/civic.py` path would collide with the
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
before ticket closeout. At that checkpoint full regression and installed validation remained separate
unrun checks; later results are recorded below.

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
timeout, model mismatch and capture-only spies are covered. At that checkpoint the only actual live
JEV calls were the six interpretation calls recorded above.

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

## Frozen validation checkpoint

Runtime source is `c0de7ad`. The final two-pass delta review completed with
**14 selected/reviewed files, zero findings and zero coverage warnings**
(`data/validation/roadmap-final-review.json`). Earlier reviewed files retained
unchanged bytes; the sequence of review receipts above records corrected findings.

The final wheel SHA-256 is
`5daf7cd5925c06b34dc953e5c0ee1c24a7e461dcf518534bc36351587cabdee9`.
All **189 runtime/SQL/schema files** match source, wheel and installation exactly.
The final installed target passed **19 focused checks in 11.720s**
(`data/validation/roadmap-final-installed.log`). JavaScript verified 26 canonical
and 8 exact-source vectors; all three checkout walkthroughs passed. The installed
walkthrough default remains broken separately. `jsonschema` 4.26.0, `referencing`
and setuptools 84.2.1 are available; no dependency-install blocker persists.

A retained actual offline run passed on the frozen synthetic fault/episode suite:
8 scheduled decisions, 1 successful fixture admission, 3 abstained, 3 failed and
1 stale. Its report digest is
`091a972c4ed7375cb6b05e65c37c5372d75054ccb44adcb18783eab088a544d3`;
original report bytes hash to
`443ccdb46b07e863ff754ff2a3e41f115fb31ad3dc375c9903c3837bdf375acf`.
Inputs/report and a real-credential no-call preflight are retained under ignored
`data/validation/roadmap-retained-offline/`. The preflight returned ready with
zero dispatches. This is a synthetic contract workload, not an independent
StateCivics accuracy corpus or a new actual provider trial.

The full checkout discovery on this frozen source ran with
`TMPDIR=/private/tmp .venv/bin/python -m unittest discover -s tests -v`;
`data/validation/roadmap-full-checkout.log` records its result: **1305 tests passed in 3328.017s**, exit 0.
The additional f192e20 negative policy test passed separately (1 test, 52.047s);
it was added after discovery and is not part of the 1305-test count. Runtime
files remain byte-identical to c0de7ad.

## Canonical closeout before live completion

MAT-046, MAT-023, MAT-024, MAT-037, MAT-038 and MAT-039 are complete for their
recorded implementation/conformance scope. MAT-039 completion means the optional
configured runner and its failure paths are implemented; the retained preflight
made zero requests, and no systematic held-out provider trial is claimed.
MAT-040 is blocked on verified independent held-out inputs and supporting actual
provider results. Its targets/support must be predeclared; no threshold fitting
or certificate issuance has run. The open corpus-location question remains an
input request, not approval inferred from elapsed time.

The StateCivics rehearsal/fast-forward resource was inspected/reused by contract
and existing synthetic inputs; it was not rebuilt, deployed or requalified here.
Crawler-owned MAT-047 and receiving-system integration/acceptance retain their
own owners and work. The 22 cross-repository roadmap items remain unchanged.
The installed-schema packaging gap remains open independently.

The extra all-quiet negative test received its own two-pass review: **1 selected
file, zero findings and zero warnings** (`data/validation/roadmap-silence-review.json`).
Canonical regeneration/validation passed after closeout, and all **39 repository
metadata/hardening checks passed in 0.862s**. The secret scan found no actual
credential material in tracked changes; `.env` is ignored and untracked.

Retained checkout artifacts use about 10.3 MiB allocated; the five review sessions
use about 7.3 MiB more (about **17.6 MiB total retained allocation**). The volume
had about **60.5 GiB free** at closeout, above the 50 GiB reserve. APFS allocated
blocks do not imply additive free-space recovery. No cleanup or branch deletion
was performed.

The final completion-record/index review also completed two passes: **8 selected
JSON files, zero findings and zero coverage warnings**
(`data/validation/roadmap-closeout-review.json`). Canonical status is 38 done,
41 planned and 1 blocked (MAT-040); 20 Matter-owned items and the unchanged
22 cross-repository roadmap items remain open. This closeout does not turn the
optional provider runner into a completed held-out provider study.

## Actual provider runner and public-evidence live completion — 2026-10-28

This checkpoint supersedes the earlier **no-call** runner preflight. Twenty new
HTTP attempts actually reached JEV in this pass: eight on the retained synthetic
schedule and two six-call exploratory runs on one real public document. The six
synthetic interpretation calls from the earlier checkpoint are additional, older
calls. None of these exposed/tuning cases constitutes MAT-040 qualification.

### Retained synthetic schedule: eight live calls

Executed `.venv/bin/python data/validation/live-completion-20261028/run_synthetic.py`
using the existing `run_provider(..., live=True)` and its default real TypeSafe
HTTP transport, not an injected response. Inputs are the retained
`roadmap-retained-offline/inputs.json` and actual passed `report.json`; their
frozen packets/questions and offline digest are unchanged. The explicit model
was `jev-1.14.0`, maximum eight calls, zero retries, one worker, 30 seconds per
call, 360 seconds wall time, 64 KiB request/response bounds and USD 0.03 maximum
reservation. The credential came from ignored `.env:TYPESAFE_API_KEY`; its value
was neither printed nor stored.

All eight attempts completed, were primitive-valid and resolved `jev-1.14.0`:
zero cached replays, incomplete attempts, non-dispatched rows or unscheduled
retries. Artifacts: ignored `data/validation/live-completion-20261028/synthetic/`,
including starts, exact neutral batches, native/neutral response bytes and
`report-908193908689125.json` (SHA-256
`28be698b77c60d8a4fa4203859732722b082d214fa246e9bdabf0d5537afc98a`).
Observed input usage was 4,347 tokens, giving an input-price estimate of
USD 0.000182574; the conservative reservation was USD 0.022020096. Billing was
not observed. Names such as `timeout`, `malformed` and `partial` identify the
**offline fixture cases**, not live faults: all eight actual responses completed.
This proves the new runner can dispatch and reconcile its matched workload; it
is not a provider-accuracy experiment.

### Selected real evidence and existing access boundary

Reused the saved extraction from the latest Shawnee dropoff ZIP
`Statecivicsai/docs/local-crawler-captures/ks_county_wyandotte/ks_county_shawnee-seed-20261022-r2q.zip`,
SHA-256 `5936d0a01f06faf63f37736955b24ac72d0c674eb38cfeb4c27982b265f86b3b`.
The selected source is the public three-page FY23 SS4A grant close-out amendment
packet, attachment 9267, associated with the May 14 commission agenda. The
[official attachment](https://shawneecoks.api.civicclerk.com/v1/Meetings/GetAttachmentFile(fileId=9267))
returned HTTP 200 without credentials; its 1,271,491 bytes matched the crawler's
PDF SHA-256 `ef4c88ba21f430aca5c7f69a435aedc933ad398ef41b27424addf3ee69fd7042`.
The saved 5,446-byte machine extraction matched SHA-256
`db37eed59fa863964139334645d32ccb55b026f7f54af342f66a0280434f1a7f`.
No new OCR, crawler run, stack, deployment or bulk archive extraction was needed.
The crawler's redistribution field is unknown; this authorized public-source
provider diagnostic does not assert a general redistribution license.

Real source bytes, provenance, SQLite host records, requests and responses stay
**outside the repository** under
`/Users/mfrieson/.local/share/matter-validation/live-20261028/` (private directory).
`provenance.json` retains the selected row, custody receipt, ZIP/public-fetch
hashes, extraction origin and permission basis. The original PDF is an actual
source observation; the saved text is an actual derived observation with that
PDF as its provenance parent. The explicit `HostAccessPolicy` grants both exact
pins to two experimental audience versions and the selected TypeSafe provider.
The existing original `ControlService` assessment token covers both targets.
Preparation and rendering use MAT-072; actual dispatch uses
`AccessService.dispatch`, with detached views and independent short current
SQLite reads before and after I/O. No database read transaction spans HTTP.
A model answer cannot expand those grants.

The added `run_guarded_diagnostic` reuses the provider runner's existing execution,
budgets, durable starts/results and resume accounting. It requires real access
service/context bindings and exactly the guarded rendered questions. It is an
**exploratory** entry point, not a fabricated passed `OfflineReport` or a bypass
of the paired runner's offline/held-out contracts. A revocation prevents result release; known pre-I/O refusal is definite
non-dispatch, while an observed request with a withheld response has an unknown
outcome. Original reservations and markers survive report-only revoked resume;
no attempt is silently resent. Qualification, corpus/split and
paired-arm fields remain unknown/null where not applicable.

### Twelve actual public-source calls, with limitations retained

Both runs used `.venv/bin/python examples/guarded_evidence_diagnostic.py --evidence
/Users/mfrieson/.local/share/matter-validation/live-20261028 --env .env --model
jev-1.14.0 --run-id <run-id> --live`. Each allowed at most six calls, zero retries,
one worker, 30 seconds per call, 300 seconds wall time, 64 KiB request/response
bounds and USD 0.02 maximum reservation. No other live runs were made in this
pass. Official model price basis was checked on 2026-10-28 at
[TypeSafe's model reference](https://docs.typesafe.ai/models): USD 0.042 per
million input tokens, output free. These estimates are not invoices.

Each run covered proposal, exact duplicate and analyst interpretation correction
for **grant oversight** versus **school technology procurement**. The correction
changes an experimental prior reading of the memo as a new grant opportunity;
it does not invent a government correction, a new source revision, a historical
client action or actual audience delivery. Comparison histories are explicitly
experimental capture contexts. Both document/event dates and the October 18
extraction time remain provenance; actual diagnostic availability is current
October 28 ingestion. An earlier cut really refused the source with
`E_EVIDENCE_UNAVAILABLE`. Actual redelivery returned `duplicate` and the same
source pin, rather than manufacturing corroboration.

The first run, `public-live`, included an authored summary in its current-input
comparison. Its six real calls are retained, not discarded: all completed and
were primitive-valid; input usage 128,685 tokens, estimated USD 0.005404770,
reservation USD 0.016515072. Report `report-909077422621833.json` has SHA-256
`3edfc226b5e74e8dd7de85bdf678250094a5d63dd1fcf6967784be957708bf72`.
Grant-oversight correction novelty was 0.45 despite relevance 0.96.

That summary could prime interpretation. One final bounded run,
`public-source-only-live`, removed the authored current interpretation and did
not tell the model the prior analyst reading was wrong. The source bytes,
question definitions and explicit experimental audience/history still supplied
the evidence and comparison task. All six calls completed, were primitive-valid
and resolved `jev-1.14.0`: no cache replay, incomplete attempts, non-dispatch or
retry. Input usage was 129,069 tokens; estimated input cost USD 0.005420898,
reservation USD 0.016515072; billing remains unknown.

Observed scores on that final run (descriptions are diagnostic, not accuracy):

- Proposal support: 0.96–0.97; proof of execution by both parties: 0.02–0.05.
  The proposed terms and signature fields were not upgraded to proven execution.
- First proposal objective contribution: grant oversight 0.81, school procurement
  0.03. Initial novelty was 0.76 versus 0.38.
- Exact duplicate novelty: 0.06 and 0.04; objective contribution 0.20 and 0.04.
  Those scores are consistent with expected silence, alongside actual intake
  deduplication. No qualified attention/outbox decision was published.
- Analyst correction: grant oversight objective 0.96, novelty 0.77; school
  procurement objective 0.35, novelty 0.58. Relevance and novelty remain separate.
  The difference from the first run illustrates prompt/context sensitivity; it
  does not prove a correction detection rate or justify fitting thresholds.

All twenty new calls were capture-only: no accepted assessments/judgments,
certificates, StateCivics client actions or real deliveries. Source ingestion
and isolated host bootstrap records are deliberate setup, not admitted model
conclusions. Expectations were agent-authored and frozen before each run; there
are no independently reviewed held-out labels or defensible accuracy estimates.
Actual real evidence and actual provider interpretation have now been exercised;
a production monitoring/usefulness trial and MAT-040 qualification remain open.
The installed walkthrough-schema failure is still a separate unresolved
packaging gap, unaffected by these calls or checkout checks.

The final real-data report is
`public-source-only-live/report-909278195010666.json`, SHA-256
`4875f57b595d8b432b5ca70554c0f015ffb6fe1b4492843c9868a51ff65ac5b4`.
The external `executed-source-hashes.json` records the six source files at the
final live checkpoint; later review corrections are separately tested below.
Each run also retains `wire-reconstruction.json`: exact deterministic adapter
rendering of the recorded pre-call batch, with its byte length reconciled to
actual transport instrumentation. That supplement is a reconstruction, not an
independent network tap. Native response bytes were captured by the adapter;
authentication headers were never retained.

The first two-pass independent review selected/reviewed three Python files and
reported five comments (four distinct issues): require literal `live=True`,
execute/check host setup even under `python -O`, bind the example's verified
price to a fixed model/date, and distinguish configuration errors from access
refusals. All were confirmed and corrected. Its three warnings concerned
unpositioned comments, not omitted review groups. The actual calls used literal
True, ordinary Python and the verified `jev-1.14.0` price; these fixes do not turn
those calls into an untested different-model run or require paid repetition.
The optimized-Python example preflight subsequently prepared the actual public
packet and passed its checks with zero calls. No fake fresh price check is
stamped onto future runs: the example now fixes the price record to
`jev-1.14.0`, checked at `2026-10-28T13:59:12Z`, and refuses other models before
setup. Original live receipts retain their original configuration bytes.

Validation uses the existing `.venv`; the ambient `python` does not have Matter
installed, and an initial security discovery without `PYTHONPATH=tests` could
not import checkout helpers. Corrected invocations are recorded, not treated as
product regressions. The pre-review provider/guarded suite passed 16 checks in
10.534s; the existing MAT-072 suite passed 17 checks in 22.927s. Interim new-test
failures were corrected before the final run. Final checks/review follow below.

The two atomic source questions are explicitly named diagnostic specifications
(proposal support and proven execution); the objective/novelty questions reuse
MAT-034's existing templates. This is not a qualification of every MAT-033/034
head. Duplicate packets were deliberately submitted to measure model behavior
after actual intake deduplication; this does not claim a production duplicate
would automatically trigger another provider call. One source, its derivation,
two audiences and repeated runs remain one connected provenance unit.

Final checkout validation ran
`PYTHONPATH=tests .venv/bin/python -m unittest evaluation.test_provider_runner
evaluation.test_guarded_provider test_repository test_hardening -v`:
**57 passed in 13.505s** (`live-completion-20261028/final-regression-verified.log`).
This includes eight new guarded tests, ten existing provider-runner tests and
39 repository/hardening checks. The 17 existing access checks passed separately.
`matter render --check`, `matter validate` (80 tickets, 104 requirements,
101 schemas, three walkthroughs) and `git diff --check` passed. The actual-key
scan found no credential in the eleven changed/nonignored files; `.env` remains
ignored and untracked.

Built with existing dependencies and no dependency/network installation:
`.venv/bin/python -m pip wheel . --no-deps --no-build-isolation --wheel-dir
 data/validation/live-completion-20261028/wheels`. Wheel SHA-256:
`ce170d23f79129d6031d90538da7e9ac6e3430e0934da2de47ca3c5e0d48eca1`.
All **189 Python/SQL/schema files** match checkout, wheel and installed bytes
(`installed-byte-match.json`). With the installed target first on `PYTHONPATH`,
**35 provider/guarded/access checks passed in 36.053s**
(`installed-focused.log`); the imported provider path was verified to be inside
that target. These installed checks do not replace a full installed test run.
The default installed `Walkthrough` was explicitly retried and still raises
`FileNotFoundError` at its checkout-style schema path; exact path/exception are
recorded in `installed-walkthrough-gap.json`. No fix or green installed-full-suite
claim is included. The earlier 1,305-test discovery predates this delta; it was
not rerun or relabeled as validation of this new source.

Across the twenty actual new calls, input usage totals **262,101 tokens**;
the published input-price estimate totals **USD 0.011008242**, conservative
reservations total USD 0.055050240 (sum of configured run maxima USD 0.07).
Actual billing remains unknown. No unreviewed labels were promoted, thresholds
fitted, certificates issued, real sinks attached or downstream systems changed.

A recorded resume using the **final** runner read all eight original live
synthetic results with a transport spy that refuses dispatch: zero fresh calls,
eight cached replays, completed accounting (`recorded-resume.json`). This checks
compatibility with receipts written before the shared-loop change; it is not
another live-provider trial and adds no cost or independent support.

The second two-pass review covered six selected Python/JSON files with no
warnings and one confirmed finding: an access failure after a durable start
withheld the result but escaped before the aggregate report, while a revoked
resume returned a misleading zero-attempt preflight. This is a remaining
failure-path correction at this checkpoint, not a defect observed in the twenty
successful calls. Closeout requires explicit refusal/unknown accounting and a
source-free report-only resume that cannot make new calls or release responses.

The accounting correction now writes a fixed refusal marker and an aggregate
report instead of escaping after a guarded dispatch failure. Known pre-I/O
refusal counts as definite non-dispatch. Observed I/O followed by a withheld
response counts as a fresh observed request **and** an incomplete outcome (these
two measures overlap; they are not extra independent attempts). Reservations
remain charged conservatively. A subsequent revoked resume reports only
source-free ledger counts under the exact original manifest: no response bodies,
source/job identifiers, renewed token, cached-result release or new HTTP call.
Previously completed results in the same prefix are also withheld from that
aggregate response. A start interrupted before its refusal/result record remains
unknown rather than being reported as zero historical attempts.

Twenty provider/guarded checks passed in 17.459s after this correction
(`accounting-focused.log`), including multi-case prefix reconciliation, pre-I/O
refusal, in-flight revocation and interrupted-start recovery. These are injected
HTTP mechanism checks, not additional live calls. The final regression, wheel
and independent correction review follow below.

## Live-testing closeout

The correction received a two-pass review of both changed Python files:
`accounting-review.json` records two reviewed files, no warnings and one low
report-label issue. It was confirmed and fixed by forwarding the specific
`provider_access_mismatch` reason into report-only resume, with that behavior
added to the existing provider-binding regression. This final small forwarding
fix was tested after the review; no extra independent review of that final
reporting-only edit is claimed. No known review findings remain unaddressed.

Final-source checkout: **59 tests passed in 16.039s**
(`closeout-checkout.log`). Final-source installed provider/guarded/access suite:
**37 tests passed in 37.150s** (`closeout-installed.log`). Final wheel SHA-256:
`c5f05abfee4d90985aedcb0cf92775ae2b65f77cdd16323a3397d3b0c66200c1`;
provider source SHA-256:
`12c73fa64db01e416a02e3f2abf4516e092c6962f0d14214c7df21773721f6bc`.
All 189 checkout/wheel/installed runtime/schema files match
(`closeout-installed-byte-match.json`). Earlier wheel hashes and test counts in
this receipt are historical checkpoints. No full discovery was repeated on this
delta. Canonical rendering/validation and diff checks pass; ticket statuses stay
38 done, 41 planned, one blocked. MAT-039/MAT-072 record the actual live evidence;
MAT-040 explicitly retains its independent-label/support blocker.

The actual credential audit checked 50 provider-artifact JSON files and 116
encoded request/response bodies, finding no credential; authentication headers
were never retained (`credential-audit.json`). Real evidence/results remain in
the external private directory. At the measured storage checkpoint the task
artifacts used about 9 MiB in the checkout and 10 MiB externally, with about
60 GiB free, above the 50 GiB reserve. Review logs and later small closeout files
are additional bounded artifacts; no bulk media work, new environment, cleanup
or branch deletion occurred.

There is **no remaining access/configuration blocker to exploratory live JEV
calls** in this completed slice. Provider qualification needs independent held-out
labels, adequate episode/polarity support and defensible results; real-client
monitoring/delivery usefulness needs the receiving integration and its own
acceptance. Neither follows from these twenty calls. The installed walkthrough
schema failure remains open independently.

## Follow-through after PR #20

PR #20 merged as `838f00bb3162fe9cf5c706b8cdfab3cefb395fd8`.
The [follow-through receipt](civic-followthrough.md) records 24 additional actual
JEV calls on four custody-verified public documents from the existing latest
crawler dropoffs, reusing MAT-072 and the existing runner. It also records the
separate installed-schema repair and MAT-022/calibration implementation checks.
The 24 calls are distinct from the earlier 20 calls above. Their exposed cases
supply findings and a score-blind review handoff, not held-out labels, approved
thresholds, provider qualification or production StateCivics acceptance.

## Sensitivity follow-through after PR #21

PR #21 merged as `f12c6ce0978092c6fb0fa0de03abfa8230bb81dd`.
The [MAT-041 receipt](sensitivity-followthrough.md) records controlled question
remapping, meaning changes, repeat variation and coherence checks through the
existing offline and provider runners, including thirteen additional actual
JEV calls on explicitly synthetic facts. These calls establish no independent
held-out accuracy or qualification. The same receipt records verified cleanup
of four obsolete worktrees, preserving branches and generated artifacts.
The narrow installed walkthrough-schema repair was verified separately in PR
#21; the earlier open-failure statement above describes its historical checkpoint.
