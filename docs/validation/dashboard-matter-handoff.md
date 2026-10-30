# Dashboard handoff: MAT-081 candidate receipt

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
