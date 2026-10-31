# Dashboard handoff: MAT-081 candidate receipt

**Current SDK handoff:** see the [pinned package handoff](../adapters/statecivics-sdk-handoff.md)
and the closeout below. Earlier checkpoint statements that the installed
walkthrough-schema failure remained open were stale: the repair predates this
stack, and fresh installed civic walkthrough checks of both SDK candidates pass.
See [the original repair receipt](civic-followthrough.md#final-executed-package-and-core-checks).
This correction is separate from current CI failures and host receiving acceptance.

2026-10-29. Matter baseline `8528485` (planning PR #27, stacked on #26).
StateCivics code inspected read-only at
`e349713e62e35d65cbfb8585a76361f0230cf2b0`. No StateCivics checkout files were
changed, and no provider, container, migration or delivery was run in this slice.

## Prepared and checked

- [Candidate specification](../contracts/monitoring-handoff.md), version
  `monitoring-handoff/1.0.0-candidate.1`, with exact portable wire schema and
  separately required trusted host/PreparedPacket bindings.
- Thirteen authored synthetic request/response pairs and nineteen invalid-shape
  vectors. A/B share selected source data and a source-finding reference while
  illustrating different audience consequences. Fixtures also distinguish
  personal/record/broad scope, unknown outcome, duplicate, explicit analyst-error
  correction, and semantic refusals. They instantiate no real records or controls.
- Nine `tests.contract.test_monitoring_handoff` tests passed: schema validity,
  example admission/rejection, exact compatible core fragments, inventory hashes,
  separate audience contexts and strict time encoding. The five semantic-refusal
  examples deliberately pass wire validation; their expected refusal is not a
  recorded runtime check.
- Canonical MAT-081 is `in_progress`, completion `not_run`; MAT-082 stays planned.
  The plan and canonical records name current host gaps and corrected cross-repo
  ordering. Generated ticket Markdown/index regenerated successfully.

An initial repository validation failed because this new receipt's link existed
before its file was written. That authoring-order failure is corrected by adding
this file; final validation and review results are recorded below when run.

## Host facts and unresolved freeze gate

At the pinned host commit ownership checks and immutable approved revisions
exist. Production host-backed MAT-072 controls, draft/pause/revoke, broad scope,
record-free capture provisioning and live assessment configuration do not.
The live provider seam intentionally returns 503. Current capture requires owned
watchlist/item/event associations; the candidate proposes requiring that binding
before evaluation. Provisioning and lifecycle/access mapping plus affected D1-D7
choices await recorded StateCivics agreement. This is a concrete candidate for
review, **not a frozen specification or MAT-081 completion**.

MAT-082 starts after contract freeze and reuses #26's civic modules by merge or
stacking. KS-1121's unmerged study code and SDK rebuild directly gate KS-1124/1126,
not MAT-081 or KS-1122 scope design. The StateCivics owner offered to correct the
incorrect KS-1121 done record and missing host plan links. This receipt does not
claim those host corrections have occurred.

## Limits and subsequent evidence

No runtime adapter, saved-objective host run, current-authority enforcement,
capture outcome, replay/live parity or actual JEV interpretation is established
by these shape checks. MAT-082 must execute semantic guards/failure paths;
KS-1126 owns actual no-login saved-objective receiving acceptance. Existing
source-first study calls remain exploratory, not proof of this new connection.
MAT-040 qualification and independent labels, wider civic acceptance and installed
walkthrough-schema packaging remain separate, unresolved by this work.

## Executed checks

- `.venv/bin/python -m matter render --check`: passed.
- `.venv/bin/python -m matter validate`: passed, 82 tickets / 104 requirements /
  106 existing runtime schemas / three walkthroughs. The candidate schema lives
  in docs and does not claim a new installed runtime schema.
- `.venv/bin/python -m unittest discover -s tests/contract -t tests -v`:
  175 tests passed. An earlier invocation without `-t tests` produced two
  existing module-import errors; the corrected discovery root resolved them.
  Initially seven of these tests exercise this new contract's shape/inventory; none
  executes future host semantics.
- Initial OpenCodeReview found Python `$` anchors accepting terminal newlines in
  the three new custom patterns. Confirmed and replaced with strict end guards;
  added invalid ID/entity-type/cost-newline and zero-cost vectors. Targeted seven
  tests passed after the fix. Final review receipt is recorded after completion.

Review also exposed copy-derived fixture ownership ambiguity (personal and second
objective reused client pins), incidental-error-only negative assertions, a stale
reason renamed away from MAT-072's `context_changed`, and no representation for
uncorrelatable malformed requests. Corrected independent synthetic identity/
audience/capture bindings; added valid base and expected field-path metadata for
negative examples; retained the core stale reason; and admitted null correlation
only for schema/version errors. Eight targeted tests now pass. A follow-up review
checks these corrections; no runtime authorization claim follows from the fixes.

A sixth initial comment identified record-scope/version pin aliasing and reused
logical command keys across the illustrative cases. Gave the record example its
own intent/revision/hash/scope pin and each distinct command its own key; added
an assertion covering the whole manifest. Nine targeted tests passed after all
six initial comments were addressed. The initial two-round review covered five
selected files, with six comments and no coverage warnings; Markdown and fixture
files are excluded by its default rules and were checked manually/by the local
contract tests instead.

Final local rerun after the record/key corrections: `render --check` and
`validate` passed; `unittest discover -s tests/contract -t tests -v` passed all
177 tests (nine new contract tests). Full repository/runtime/provider suites were
not run for this specification-only change. The earlier 175/176 counts above
record intermediate runs, not the final total.

The follow-up review identified three further structural gaps: missing reasons
for partial/unavailable coverage, derived sources without parents, and control
characters in jurisdiction keys. Added conditional shape constraints and four
negative vectors (partial/unavailable separately). All nine targeted tests pass
with nineteen invalid vectors. Verified parent identity/closure and current
jurisdiction ownership still require runtime host checks.

## Review disposition

Two default two-pass OpenCodeReview runs completed, each selecting five files
(four schema/ticket JSON files and the Python test), with no coverage warnings.
The follow-up returned six comments. Confirmed and addressed all: conditional
coverage reason, derived parents, jurisdiction control characters, exact negative
mutation paths, avoiding an unapproved one-item-per-objective requirement, and
core attention-reason compatibility/documented coverage summary mapping. The
last corrections were checked by the author and local tests; this is not a claim
of a separate clean independent verdict on those final edits. Markdown/fixture
content remains outside default OCR selection. Raw local receipts:
`data/validation/civic-source-integration-20261028/mat081-review.json` and
`mat081-review-final.json` (gitignored); the specification and fixture inventory
are the retained reviewable artifacts in Git.

No runtime source, host checkout, provider configuration or deployment changed.
MAT-081 remains in progress and unfrozen; the PR is a candidate review handoff.

## StateCivics record correction verified

Read-only follow-up confirmed `e2dcb04cc` is an ancestor of StateCivics main
`8955f16d8`. KS-1121 is blocked; KS-1122's dependency is KS-701; KS-1124 and
KS-1126 directly include KS-1121; the referenced integration plan exists again.
KS-701 remains in_review and gates KS-1122 acceptance, not MAT-081 design.
A path-limited diff from `e349713e6` through that inspected main returned no
changes in the six host intent/schema/router/watchlist/planner files on which
the candidate is based. The original pending-record-correction note above is
historical and now resolved. These documentation corrections do not merge
KS-1121 implementation, rebuild an SDK image or configure the live host seam.

The host reports the rehearsal stack is free; it was not started or changed by
this read-only verification/documentation follow-up. Capture-target selection
remains awaiting the owner's answer. No freeze, MAT-082 execution or production
committee repair is claimed. This follow-up changes only Matter Markdown notes;
its local rendering/validation checks are recorded with the commit/PR update.

Follow-up checks: `.venv/bin/python -m matter render --check` and
`.venv/bin/python -m matter validate` passed (82 tickets, 104 requirements,
106 runtime schemas, three walkthroughs). `git diff --check` passed. Review
selection contained zero eligible files because all three changes are Markdown;
the diff was manually checked against the cited host records, not represented
as an independent code review. Runtime tests were not repeated for this factual
Markdown-only update.

## Owner-approved capture target and version 1 freeze

Owner explicitly approved a real owned watchlist/item and refusal until it exists
and is authorized, then directed contract freeze and MAT-082. Decision 0002
separates that product approval from bounded engineering D2–D7 dispositions and
host implementation work. Version `monitoring-handoff/1.0.0` and contract-lock
pin the specification, decision, portable/installed schema and authored synthetic
examples: fifteen request/response pairs and nineteen invalid wire vectors.
Nine targeted tests, render/check and validation passed (82 tickets, 104
requirements, 107 schemas, three walkthroughs). No live/provider/host receiving
acceptance is established by freeze. Independent review disposition follows.

Sixteen invented use cases are documented in the separate research catalog with
ten primary workflow references, explicit access limitations and an inference/
fiction label. Research does not establish buyer demand, integrations or useful
provider accuracy; it adds no mandatory new crawler feed or runtime scenario.

Storage: free disk measured 29 GiB, below the standing 50 GiB reserve. Continue
only lightweight source work and bounded targeted SQLite tests using the existing
environment. Task artifacts under data/validation/monitoring-adapter-20261030
and test scratch are budgeted below 100 MiB; no full qualification, bulk copies,
container rebuilds or full stress suite are launched. Retain review summaries
and actual run receipts, with synthetic examples in Git; temporary test stores
use their existing cleanup. No other session's evidence is removed.

Freeze review completed two passes over six selected files, no coverage warnings.
Its one medium finding was confirmed: intent-wide handled status had no exact
contribution scope. Removed that boolean, added bounded references to existing
scoped dispositions outside the immutable intent, and added handled-then-correction
and forbidden-global-boolean examples. Ten targeted tests now pass with sixteen
request/response pairs and twenty invalid vectors. The earlier fifteen/nineteen
counts are the pre-review checkpoint. Review of the corrected boundary continues
with MAT-082; no clean independent verdict on the last correction is claimed here.

Post-correction contract suite: 178 tests passed in the existing environment;
render/check and repository validation passed at the freeze checkpoint. The
specification freeze is a component interface milestone; no StateCivics runtime
file or deployment was changed. MAT-082 proceeds on a separate stacked branch.


Freeze follow-up review: two passes reviewed all six selected files, one low test
finding, no warnings. Added a paired availability assertion: the identical late
source is refused at the early cut and has a result at the later cut. The later
example now has a distinct illustrative packet ID/digest for its changed cutoff;
these remain authored wire examples, not actual prepared packets. Regenerated
the contract inventory; eleven targeted contract tests pass. Wire shape and
adopted semantics are unchanged at 1.0.0. Updated the plan's old candidate/
unresolved-target passages to the current frozen decision.

## MAT-082 bounded component closeout

Implemented `matter.statecivics_monitoring` against frozen version 1.0.0, stacked
on the MAT-081 freeze/correction (`3aeb564`, `f95a57e`). This optional adapter
composes existing context/control/access, source packets, committed allocations,
durable executor receipts and current attention services. It adds no database,
queue, retriever, JEV client or production delivery route. The host still supplies
its actual registered assessment/admission policy; a primitive probability is
not converted into a qualified assertion by this adapter.

**Executed software evidence:** 24 distinct component test methods have passing
receipts across bounded segments and affected-case reruns, plus 179 contract
tests and two existing regressions for late availability and new candidate
watches. This is not a claim of one clean whole-repository discovery run. The
current environment has Python 3.12.14, jsonschema 4.26.0 and referencing 0.37.0;
the earlier missing-package limitation does not apply to these checks.

- Two authored objectives share one actual stored source finding but produce
  separate native positive/quiet decisions. Personal binding and foreign audience
  grants are checked; pausing one objective leaves the other current.
- Missing/unauthorized/muted targets, drafts, pause/revocation, stale intent,
  expiry and price/budget limits refuse. Current grant revocation was exercised
  both at dispatch (zero fixture transport invocations) and during I/O (one
  invocation); answers are withheld and regrant does not cause a blind resend.
- Exact body retry recovers one actual durable execution; a changed body under
  the same key conflicts. Completed and unknown attempts recover correctly past
  their original deadline without needing a configured executor. Cancellation
  remains cancellation after resume. Failed recording never releases an
  unrecorded answer as durable success.
- An actual native output milestone suppresses repeat material. Omitting known
  history refuses; an explicit linked retraction still produces correction with
  uncertainty. Scoped acknowledgement of the old assessment does not silence a
  new declared deadline. These are synthetic typed-claim/host-milestone cases,
  not government source-revision accuracy measurements.
- A real new candidate created after broad context activation is accepted when
  granted; removing its grant refuses. Preference editing during an actual
  fixture executor invocation withholds the old handoff while retaining the
  completed execution. A new output command reuses the identical semantic result
  with no second invocation under still-current semantic grants.
- Replay and live-input serialization both ran through actual guarded packets,
  durable recorded execution and native attention evaluation. Two authored
  responses produced equivalent treatment/material/capture keys. Context-policy
  fields remain honestly distinct. A real stored future-available source is
  excluded from the packets and both provider requests (canary checked). The
  actual assessment's selected-source set and observation availability are
  checked before projection; current assessment status cannot widen the cutoff.
- A forged projection cannot be captured. Quiet never calls the sink. Known
  pre-write guard refusal stays a refusal; opaque failure, skipped/swallowed
  guard or possible partial write stays unknown. The sink callback is a fixture,
  not StateCivics AlertPlanner receiving evidence. Atomic writes, persistent
  outcome reconciliation and capture-key deduplication remain the real host's
  responsibility.

**Review:** each review used two passes and covered all selected files. The
initial adapter review had nine comments (one duplicate); follow-up had five
(one duplicate); final review had eight (four duplicates). Confirmed findings
were corrected: budget-code preservation, received-response retention, truthful
capture/recording outcomes, guard misuse/partial writes, resumed cancellation,
deadline recovery, foreign-grant checking and stronger actual transport/parity
checks. Warnings reported unpinned comment positions, not unreviewed files;
findings were matched manually. The final corrections have targeted passing
checks and manual source review; no separate clean independent verdict after
those corrections is claimed. Freeze review's handled-scope and availability
pair findings were also corrected as recorded above.

Early runs failed for fixture assembly/import/discovery mistakes and the budget
error bug; they are not passes. The first 24-test checkpoint (ten contract plus
fourteen component tests) had two failures. History was mistakenly nominated as
a current assessment dependency, then omitted from the attention reader's
authorized history; these assembly errors were corrected separately. The
expanded revocation case first exhausted its ten-second fixture reservation;
the second distinct command now receives its own real committed allocation.
The parity setup first reused a reservation with an old token after source
selection changed; it now reserves against the exact refreshed token. No gate
was disabled to obtain the passing receipts.

Raw logs/reviews and the code/test hashes are retained externally under
`data/validation/monitoring-adapter-20261030/` (gitignored). Tests use authored
responses and a declared synthetic 2050 clock/window; their wall times are not
provider latency evidence. **Zero live JEV calls** were made in this slice; the
two parity invocations are recorded-fixture execution. Research examples are
invented planning material, not independent labels or qualification evidence.

The current wheel was built without dependency downloads and its monitoring
module, bundled schema, question construction and refusal mapping were loaded
outside the checkout. Render/check, repository validation and diff whitespace
checks passed. This limited packaging smoke does **not** fix or clear the
separate installed walkthrough-schema failure. The entire installed walkthrough
and whole-repository/stress/qualification suites were not rerun here. Free disk
was about 46 GiB at closeout, below the standing 50 GiB reserve; task artifacts
remain below the declared 100 MiB budget and only bounded work was run.

**External acceptance remains:** merge/build the source-adapter/SDK stack and
implement StateCivics real controls, broad-scope mapping, lifecycle, capture
associations and registered dispatcher configuration. KS-1122 still needs KS-701
acceptance; KS-1124/1126 need KS-1121 and the rebuilt SDK. KS-1126 owns the actual
two saved-objective receiving/rehearsal run; KS-1127 owns subsequent incoming-live
shadow use. MAT-048/049 wider scope, MAT-040 qualification/human-reviewed labels,
production alerts, the custom writer, DIAT and PostgreSQL are not completed by
this component evidence. StateCivics files, containers and deployment were not
changed. No loose worktree was created; only the current Matter worktree remains.

## SDK review and pinned handoff, 2026-10-30

The owner authorized Matter-side review closeout, package verification and a
pinned handoff, explicitly **without merging** or changing StateCivics. The
[SDK handoff](../adapters/statecivics-sdk-handoff.md) and
[candidate manifest](../adapters/statecivics-sdk-candidates.json) separate the
#26-only KS-1121 package from the #29 saved-objective package needed by
KS-1124/1126. StateCivics owns its image and receiving acceptance.

### PR and review evidence

The inspected heads were #26 `9cf444a`, #27 `8528485`, #28 `f95a57e`, and #29
`284047a`, based on main `b5dfc27`. The base-to-head chain is linear and GitHub
reported all four mergeable with `mergeable_state: unstable`, no submitted
reviews or review comments. No merge was attempted. GitHub mergeability is not
a clean validation verdict or owner authorization.

The two-pass independent review of all 16 eligible files across #26–29 completed
with no coverage warnings. It found three confirmed adapter issues: native
pre-dispatch recording failures were clamped to invalid request before the wire
mapper, a redundant selected-source subset check could never fail, and readable
correction references were not checked against actual supersedes ancestry.
The first correction is committed at `c32ea6374129cbbab074bab4546b485d72654457`;
its extended recording-failure regression passed (one test, 254.384s).
The existing post-dispatch unknown/no-resend assertions remain in that test.
The correction-lineage fix is committed at
`6ae021456207b3cb2ba56c13e2c62d456d250069`; its extended native baseline/correction
regression passed (one test, 262.125s). It verifies an actual linked correction,
then refuses an authorized unrelated claim, the current claim itself and a
selected observation without a supersedes relationship before provider I/O.
The check follows only persisted ancestor edges with current access, bounded
reads, candidate/type compatibility and observation availability checks.
Review of the initial failure-mapping delta found a real handoff preparation hazard: the preliminary
manifest still named the earlier runtime. Candidate pins must be rebuilt after
the final runtime fixes; the initial manifest was never a published SDK release.

### Installed-schema investigation: stale warning corrected

The warning in earlier checkpoints above was stale. Main `b5dfc27` already uses
`importlib.resources.files("matter._schemas")` for the default walkthrough schema
in `matter.demo._schema`. The repair and actual installed receipts were recorded
in [live-roadmap](live-roadmap.md#installed-schema-follow-through-2026-10-28)
and [civic follow-through](civic-followthrough.md#final-executed-package-and-core-checks).
Fresh #26 and baseline #29 wheels both passed the default-schema civic walkthrough
outside the checkout, under isolated Python with no local schema directory,
with editable Matter import hooks removed and provider network denied. This is
installed evidence, not a checkout-test inference. No schema/package code was
changed in this closeout. The repository CLI still intentionally requires a
checkout or explicit `--root`; broader MAT-077 scope remains planned.

### Existing CI validation gap

The Python 3.11/3.12 pull-request jobs on all four inspected heads failed at
behavioral regression tests. The recurring failure is
`integration.test_dispatch_races.DispatchRaces.test_distinct_equivalent_intents_compete_across_real_sqlite_handles`:
the losing queue operation returns `E_STORAGE_UNAVAILABLE` rather than a withheld
or stale result. The single-test local reproduction failed in 30.536s with the
same result. The delivery implementation, SQLite implementation and this test
are unchanged by #26–29; that does not establish the root cause or dismiss it.
No neutral outbox/storage refactor or CI-only repair was added to this slice.

Additional failures appear in #26/Python 3.12 and #27/Python 3.11:
`test_cancelled_never_authorized_work_can_be_withdrawn_then_replaced_without_renewing_old_token`
(withheld instead of ready) and
`test_one_expired_member_does_not_abort_compatible_independent_member`
(blocked instead of completed). Those were inspected in retained logs, not
locally reproduced or cleared. The #28/#29 logs in both Python versions report
the one recurring race failure. These failures block claiming an all-green
merge gate; they are separate from the repaired walkthrough resource lookup.

Raw receipts, immutable source inventories, wheels, installed targets and review
JSON are retained in gitignored `data/validation/sdk-handoff-20261030/`.
The existing environment is reused; this is not a fresh dependency environment
or a new multi-version local suite. There are zero live JEV calls in these
checks; authored responses and real software guards are component evidence,
not JEV interpretation, host receiving acceptance or MAT-040 qualification.

### Package and contract receipts

Built #26 source `9cf444a` and final saved-objective runtime `59bfed9` without
dependency downloads; both version strings are `0.1.0.dev15`, so the manifest
pins separate source commits and wheel SHA-256 values. All 200/#26 and 202/#29
runtime/SQL/schema files byte-match their immutable source commits. Imports
of all 92/#26 and 93/#29 package modules came from the installed targets, with
106/#26 and 107/#29 bundled schemas. Frozen monitoring schema, two question
construction and native refusal mapping checks pass in the final saved-objective
wheel. Civic default-schema walkthroughs pass for #26, baseline #29 and final
#29 outside checkout with no schema directory or provider access.

- Fresh installed #26 civic export/attention selection: **14 tests, 2.896s**,
  zero failures/errors/skips, network denied.
- Checkout contract suite: **179 tests, 9.411s**, zero failures/errors/skips.
  All 60 frozen lock entries match; no specification/decision/schema bytes changed.
- JavaScript portable canonical check: **26 canonical and eight exact-source
  vectors** passed.

No full repository/stress/qualification suite or new live call was run for this
closeout. Harness preparation errors (wrong interpreter for the build backend,
editable import leakage and a socket monkeypatch incompatible with SSL import)
were corrected before the reported final checks; they are not successful checks
or new product defects. Final isolated runs explicitly exclude the Matter
editable finder, verify every Matter import path and deny provider network I/O.

### Correction guard follow-through

Review of `6ae0214` found over-broad history reads: a valid claim correction
could be refused because an unrelated observation ancestor lacked permission
or availability. `9745941` restricts roots to the declared correction types,
prioritizes declared targets, stops once their paths are proved, and skips
ungranted unused branches without retrieving their bodies. `59bfed9` also
allows a separately verifiable path beside unavailable unused history, while
never treating that unavailable history as a proving link. The search remains
bounded at 128 visited references. Native intake and current access remain the
owners of record validity and permission; these checks create no source authority.

The two-pass review at `9745941` covered all three selected Python files;
its only finding was a test taking the wrong rejection path. The two-pass
availability-delta review covered both selected files; its only finding was a
missing unavailable-intermediate negative control. Both were corrected in
`aa2ab934a35f705d402062865cd291b1736e30dc`, with explicit read-trace assertions.
The handoff/manifest/canonical-ticket two-pass review covered all three selected
files with zero findings or warnings. These are separate review scopes, not a
claim that the earlier full-stack review had no findings.

The final test-only delta received a separate two-pass review of its one selected
file, with zero findings or warnings. All confirmed findings in the review
chain are addressed; this is not a green verdict on the unrelated failing CI tests.

The current `59bfed9` wheel passes **10 focused boundary tests in 0.022s** under
the installed, network-denied harness. They cover available source correction,
unrelated references, subject/type refusal, required transitive paths,
unused ungranted/unavailable history, unavailable or future targets and
intermediates, and the search bound. Their trusted-view fragments are unit
evidence; they do not impersonate persisted StateCivics records. The earlier
`6ae0214` wheel passed the three native SQLite recording/correction/projection
regressions in **639.412s**. The later runtime and full baseline installed runs
have their own receipts below; no earlier wheel is relabelled as the current one.

The final handoff wheel is built from `59bfed9`, SHA-256
`13f6b3156bb33664300597aaa533a71764a700bda3a810d8a569989809b4ca37`.
All 202 packaged files match that source. Later test/documentation commits do
not alter the packaged runtime, README, license, schema or build configuration.

The `9745941` installed wheel selection passed **11 tests in 617.705s**, with
zero failures/errors/skips: eight ancestor-boundary units and three native
SQLite recording/correction/projection regressions. Its final availability-only
runtime delta is covered by the current `59bfed9` wheel's ten focused checks,
including the new available-side-branch and unavailable-intermediate controls.
The two later test-only changes strengthen branch/read-trace assertions. This
is explicit change-specific evidence, not a full-suite rerun of the final wheel.
The environment used Python 3.12.14, SQLite 3.53.1, Darwin/arm64 and the existing
dependency environment. Host Linux/image acceptance still needs its own receipt.

The complete **original-head installed adapter run passed 24 tests in
2,402.718s**, with zero failures/errors/skips. It used the immutable `284047a`
wheel and its original test module loaded before the closeout edits, outside
the checkout with network denied. This replaces the earlier segmented-only
baseline receipt, not the final wheel's change-specific receipts. Exact
runtime/test-source hashes for the 24/11/10 selections are retained in
`test-provenance.json`; individual summaries are `monitoring-tests.json`,
`reviewed-installed-regressions.json` and `handoff-installed-boundary.json`.

Final render/check, repository validation (82 tickets, 104 requirements, 107
schemas, three walkthroughs), package/source hash comparison and diff whitespace
checks pass. All four PRs remain open; no merge, StateCivics edit or image build
was performed. Only this Matter task worktree exists. Disposable task build
scratch was removed, with wheels/inventories/receipts preserved; local task
artifacts occupy about 30 MiB, within the 100 MiB budget. Free disk remains
below the standing 50 GiB reserve, so no full repository/stress/qualification
or image build was attempted.
