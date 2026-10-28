# Sensitivity and worktree follow-through

Start: clean `main` at `f12c6ce` (PR #21 merged). The access-revocation assertion
already uses a real committed allocation, checks `E_AUTHORITY_REQUIRED`, and
verifies restoration succeeds. A fresh execution passed (1 test, 3.590s);
the prior retained guard-removal mutation confirms it detects the intended guard.
Prior source/delta/closeout reviews are complete; they are not pending work.

Selected next Matter-owned work: MAT-041, whose canonical prerequisites are done.
It addresses controlled repeats, outcome remapping, meaning changes and
coherence using the existing question renderer, typed execution, offline episode
runner and optional provider runner. No new client, retrieval, replay or delivery
infrastructure is planned. MAT-040 empirical qualification remains blocked on
independently reviewed held-out labels and approved targets. Crawler-owned
MAT-047 and deferred cross-repository work are outside this implementation.

Storage: about 59 GiB free at start; 50 GiB reserve and 10 GiB task-growth cap.
Expected growth below 100 MiB. Reuse `.venv`; no container, bulk corpus or OCR
work. Software receipts stay under ignored
`data/validation/sensitivity-followthrough-20261028/`; any actual provider
receipts will remain in the external private validation root. Only synthetic
control facts are checked in. Fresh calls, recorded replay, synthetic fixture
oracles and independent qualification remain distinct.

## Worktree cleanup

Four previous task worktrees were clean, had no unique commits, were ancestors
of `main`, and had no open files or active processes in the bounded audit.
They were removed with `git worktree remove`; no branch was deleted:

- `matter-delivery-397gli05/review-checkout`, `2a0ff0e`, branch retained.
- `matter-live-roadmap-heevp_pv/foundation-checkout`, `ba59098`.
- `matter-live-roadmap-heevp_pv/semantic-checkout`, `b1b490d`.
- `matter-live-roadmap-heevp_pv/timer-checkout`, `60b0e75`.

The first two contained only ignored build/cache/egg-info files. All 414 ignored
files (about 7.6 MB logical bytes) were archived before removal and each archive
member's SHA-256 was verified against the original. Archives, original commit
IDs, member hashes and cleanup receipts are retained in the task's ignored
validation directory. Recreate a worktree at the recorded commit and restore its
archive to recover those generated files. Parent scratch directories and their
validation evidence were left intact. Only the primary worktree remains.

## Controlled probes and exploratory provider evidence

The new module creates a frozen thirteen-call schedule with twenty-five head
observations: two identical bundled repeats, reversed/rotated options, neutral
labels, name/definition swaps, and seven single heads. The synthetic fixture
distinguishes same-topic/different-matter from same-matter/new-occurrence.
Reference outcomes and their origins stay outside the provider input. The
definition-based oracle independently selects labels; deliberate first-option,
stubborn-answer, incoherence, missing-response and model-change faults exercise
the report's negative paths. Unsupported probability multiplication is tested
at the existing common composition boundary, without adding another API.

Actual live execution used the existing MAT-039 runner and TypeSafe adapter with
explicit `jev-1.14.0`: **13 fresh calls, zero retries, zero incomplete attempts**.
The protocol capped calls at thirteen, per-call timeout at thirty seconds, wall
time at six hundred seconds and conservative cost reservations at $0.04.
Reservation consumed $0.035782656. Reported usage was 17,295 input and 718 output
tokens; the price-basis input-cost estimate is $0.000726390, with billing
unobserved. No credentials are retained in the protocol or artifacts.

The external root is
`/Users/mfrieson/.local/share/matter-validation/sensitivity-20261028/`.
It contains `suite.json`, `corpus.json`, `protocol.json`, actual offline episode
reports, thirteen `live/*-started.json` / `*-result.json` pairs, the original
`live/report-923743656271083.json`, append-only sensitivity analyses, and
`summary.json`. The run uses synthetic facts, no independently reviewed labels,
no accepted learned state, no real delivery and no qualification. Both actual
offline replay arms passed; all thirteen candidate cases explicitly abstained.

JEV selected `same_topic_only` in both baselines, with probability 1 for that
outcome and 0 for `same_matter`. It assigned topic 0.99, matter 0.01, recurring
matter 0.99 and same occurrence 0.01. Definition remapping preserved the selected
semantic outcome through each order/label variant. Both bundled repeats were
identical on every measured head. The equivalent proposition was 0.02 versus
matter 0.01 in the bundle, and 0.03 versus 0.01 separately. Complement residuals
were zero; cross-primitive residuals were 0.01. These twenty-five exploratory
checks flagged no deviation beyond the declared 0.1 diagnostic tolerance or
repeat envelope. That tolerance is not an approved release threshold. These
obvious, authored controls establish neither real-world accuracy nor robustness
over diverse civic cases; MAT-040 still requires independent held-out evidence.

All thirteen calls completed before a post-run decoder error: it passed a
serialized precision profile to a constructor that expects its explicit fields.
The decoder was corrected, covered by a zero-dispatch regression, and analysis
was rebuilt from retained neutral response bytes. **No live call was repeated**
to repair reporting. Started/result binding and precision-profile identity are
checked before reconstruction. The provider's original execution receipts remain
the authority for actual calls, costs, faults and usage. If a retained execution
has a timeout, budget fault or invalid admission despite available response
bytes, the example refuses analysis and leaves the original failure report
intact. Parsing bytes cannot erase an execution failure. This is covered with
an actual offline post-dispatch timeout; no network call is used for that check.

The current append-only analysis is
`live-sensitivity-925369216460708.json`, SHA-256
`4f255381133ad414ff15a18c61d2afced5c353a487039d3dbbfcc5d70ecffe17`.
Earlier analyses are retained as checkpoints, not additional provider runs.

## Software verification and review

Initial sensitivity tests exposed two test-harness mistakes (deep-copying an
immutable specification and asking the live adapter to render an offline-mode
batch). They were corrected without weakening the execution boundary. The next
run passed eight focused oracle/fault tests. The first complete two-pass review
covered both initial Python files and reported six comments (five distinct
issues; one duplicate), with no missing review group. Confirmed findings were
fixed: unanchored successes were mislabeled after both baselines failed; the
single Choice check was misclassified; cross-primitive comparisons omitted repeat
spread; one assertion was vacuous; and the outside-envelope bundling failure
needed an explicit negative test. Current focused tests include the recorded
decoder/binding regression. Final check and review receipts follow below.

The next complete two-pass review covered all three Python files and both
canonical/index JSON files. Its four comments represented two distinct findings:
the recorded-response execution-fault issue above, and a bundling confound in
the order/label comparison. Both were confirmed and fixed. Altered Choice
requests now compare with the unchanged single-Choice request; bundling is
scored separately against bundled baselines. A deliberate bundling-only fault
must flag bundling while all four mapped order/label controls pass. A missing
singleton control makes those comparisons not evaluated. The schedule still
has thirteen calls; repeat noise is measured on bundled requests, a stated
limitation rather than a singleton variance estimate. Reanalysis of the same
retained live responses still flags no exploratory deviation.

Final context/failure-path source checks passed twelve tests
(`sensitivity-context-final.log`), and the rebuilt installed wheel passed the
same twelve tests outside the checkout in 0.735s
(`installed-sensitivity-closeout.log`). Earlier eleven-test receipts below are
retained checkpoints. The final source receives another full two-pass review.

The old installed walkthrough-schema lookup failure was already narrowly fixed
and verified in PR #21, as recorded in
[the prior closeout](civic-followthrough.md). It is not being silently resolved by
these checkout tests. MAT-077's broader distribution scope remains planned.

Fresh check receipts in the task's ignored validation directory:

- Access-revocation baseline: 1 test, 3.590s, passed; the intended guard and
  restoration path were already present in merged PR #21.
- Final focused controls/decoder/execution-fault tests: 11 tests, 0.563s, passed
  (`sensitivity-execution-guard.log`). A missing timeout/call-limit argument in
  the new synthetic test's adapter construction was corrected before this run.
- Selected evaluation regressions: 93 tests, 337.728s, passed
  (`evaluation-regression.log`). Selection used unittest's `-k evaluation`,
  which includes matching existing rule-evaluation cases. This run froze the
  earlier ten-test sensitivity suite; the eleventh post-dispatch regression was
  subsequently verified separately.
- Semantic/rendering/adapter/canonical regressions: 105 tests, 72.714s, passed
  (`semantic-regression.log`).
- Installed runner/guard/offline/plan/sensitivity checks outside the checkout:
  35 tests, 317.015s, passed (`installed-focused.log`). The final eleventh
  sensitivity regression is additionally covered in
  `installed-sensitivity-final.log`.
- A fresh wheel was built and installed without replacing the existing env.
  Its 197 source-corresponding runtime/SQL/schema files byte-match checkout
  (`installed-source-inventory.json`; the generated schema-package marker is
  separate). Three packaged walkthroughs passed under isolated Python in a
  temporary directory outside the checkout, without a schema directory
  (`installed-walkthroughs-isolated.log`). The initial smoke check used an
  ignored checkout subdirectory; the explicit outside-checkout run supersedes
  its location claim.
- Value-level credential audit: 67 files checked, including decoded response
  bodies, zero matches and no disclosed secret values (`credential-audit.json`).

The prior 1,348-test installed full run is historical PR #21 evidence. This
additive module does not change core execution, access, storage or delivery; no
new full discovery is claimed. Current broad and installed focused checks,
actual A/B offline replay, and thirteen actual provider calls are distinct
evidence classes.

## Final closeout

MAT-041 is complete as a controlled sensitivity mechanism and exploratory probe
milestone. The third full two-pass subscription review covered all five selected
files (three Python, two ticket/index JSON), with **no warnings or uncovered
groups**. It identified one further concrete case: a timeout without raw bytes
was skipped before the execution-fault guard. The filter was corrected during
the review; known returned executions now all pass through the same refusal
check. The review was static; the test executions are our separate receipts.
No separate clean post-correction review is asserted. The correction passed
the twelve-test final suite in checkout (0.632s) and installed runtime (0.591s).
An isolated in-memory mutation restoring the old skip fails the exact no-bytes
case with one failure and zero errors. It changed no source file and allowed no
network dispatch (`recorded-fault-mutation.json`). All confirmed findings from
the three reviews are addressed.

The current wheel SHA-256 is
`50d70662b68ae4e70fbc0e9e8ed7d9bad15fdc69e235265af1f40a2ef4d478ba`.
Its 197 source-corresponding files match checkout
(`installed-source-inventory-closeout.json`); the three walkthroughs also passed
from that target under isolated Python outside the checkout
(`installed-walkthroughs-closeout.log`). Canonical JavaScript verification passed
26 canonical and eight exact-source vectors; checkout walkthroughs, generated
ticket checks and validation passed (80 tickets, 104 requirements, 106 schemas,
three walkthroughs). The final value-level credential audit checked 70 files,
including decoded response bytes, and found zero matches.

Measured retained task output plus external provider artifacts and all three
review-session directories was about 13.3 MiB logical / 14.7 MiB allocated at
the storage checkpoint, with about 58.4 GiB free. Later closeout text is small
additional growth. APFS shared-block accounting is not a claim of reclaimed
physical bytes. All archived worktree artifacts remain retained; only the
primary worktree remains. No branches were deleted.

MAT-040 remains blocked on genuinely independent held-out labels, adequate
support, approved targets and defensible results. These authored controls do
not supply them. MAT-042's useful-silence/outcome qualification consequently
retains that prerequisite. MAT-077's broader distribution acceptance remains
planned, although the narrow installed schema failure is separately fixed and
rechecked. No cross-repository, production delivery or deployment work is claimed.
