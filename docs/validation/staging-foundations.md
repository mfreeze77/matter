# Core and semantic staging foundations

## Scope and dependency audit

The operator requested merging every open Matter PR and continuing the outlined
core and semantic tickets in canonical dependency order. At the start of this
batch, the live PR inventory was empty. PR 14 was already merged at
`f1d28a65751f7caaab4723a0f7f9b3af3ed011be`; it was verified rather than merged
again. The checkout was clean on that same main commit.

MAT-014 and MAT-027 have completed dependencies and start first. MAT-015 then
MAT-016 follow the core composition milestone; MAT-028 follows question
specifications. Targeted acceptance and repository checks precede admission of
the next dependent implementation; tickets remain in progress until combined
regression, package qualification and independent review pass. No dependent
ticket is marked done before its prerequisites are done.

MAT-029 additionally requires MAT-020. MAT-020 depends on the later lifecycle,
audience, attention and scheduler chain; MAT-030–032 and provider-shadow work
retain their declared dependencies. No dependency will be removed to make a
provider adapter appear ready. Cross-repository roadmap work and speculative
research extensions remain outside this batch. Actual live calls and provider
qualification are separate unrun gates until their prerequisites and run
configuration exist.

## Environment and bounded output plan

The existing constrained Python 3.12 environment is reused. Fresh baseline
`render --check` and `validate` passed: 80 tickets, 104 requirements, 41 schemas,
three walkthroughs. The unchanged base tree's previous 826-case and isolated
package evidence is retained separately in the ready-foundations receipt; it
does not qualify the new implementation.

The destination volume initially reported 97 GiB free. The checkout measured
48 MiB including its 16 MiB ignored environment. Additional task output is
budgeted below 1 GiB, within the workstation's 10 GiB budget and 50 GiB free-space
reserve. Test/review logs, frozen input manifests and installed-wheel checks go
under the external temporary task directory
`/var/folders/hn/c0zg49fj73g5bnwl67mj83mm0000gn/T/matter-staging-foundations-5ghshtav`.
No private corpus, model or media downloads are planned. Task-owned scratch
can be discarded after review; existing evidence and merged branches are retained.
Full runs use the canonical physical temporary directory to avoid the documented
pre-existing macOS `/var` versus `/private/var` backup-path assertion.

## Execution evidence

Implementation and qualification are in progress. Per-ticket receipts will
record actual focused evidence. This receipt will record the executed combined
gates, review findings and exclusions, final artifact identity, remaining
dependencies and storage measurements before publication.

MAT-027 initially passed 30 focused tests and 62 combined semantic tests.
Root source review and a separate 30-case rerun also passed. Its first candidate
commit prematurely marked the ticket done while combined gates were pending;
independent review identified that tracking mistake. The status was restored to
in progress with completion not run; focused evidence remains in its receipt.
The same review found a renderer over-size error classified as invalid policy
and an identity validation error pointing at criteria. Both are being corrected
with specific behavioral regressions before combined qualification. It also
identified a reference to these then-uncommitted notes and a package description
advertising modules not yet committed; the notes are now committed and the
description names only existing implemented features.

MAT-014's expanded 26-case focused suite passed in 1.757 seconds after root
review required final edge qualification checks. A certificate expiring after
child execution now blocks that descendant at final consumption while retaining
the original attempts; required and conditional paths are both covered.
MAT-027's two implementation review fixes have specific regressions, and its
expanded 32-case suite passed in 0.175 seconds. MAT-028's 22 focused tests passed
in 11.273 seconds, using actual SQLite, payload and citation/provenance APIs,
separate processes over the same snapshots, and the MAT-027 renderer.

A generic storage opt-in maps initial changed/missing read pins to
`E_DEPENDENCY_STALE` without changing the default, read enforcement, command
identity or historical retry outcome. Five focused storage tests passed in
0.374 seconds, including durable refusal/restart/retry with no handler effect,
default compatibility, fresh success, missing dependencies and safe refusal of
unsupported classifications. This enables MAT-015 to retain attempted command
material in its existing journal while refusing current publication. It adds
no wire command variant, receipt schema or migration.

The completed MAT-027 review returned six findings, with no warnings. The five
tracking/rendering/diagnostic issues above were confirmed and fixed; its final
finding showed that helper functions coerced bare string paths into character
arrays. Helpers now require explicit lists or tuples before specification
validation. The expanded 33-case rendering suite passed in 0.245 seconds.

MAT-014 now reports both the admitted ceiling and a conservative true remaining
budget. A chained-run regression prevents reusing a consumed call allowance.
Independent review also found incomplete resolver precedence was rejected only
after evaluation. It is now rejected before preparation or dispatch, with a
zero-call regression. The expanded 28-case DAG suite passed in 2.462 seconds.

The optional trusted storage precommit hook needed by MAT-016 passed six
real-SQLite tests in 0.814 seconds. They cover same-transaction observer writes,
unchanged command manifests, audited reads/watches, replay suppression, rollback,
failed-handler isolation and scope/phase guards. These focused checks do not
replace combined regression or the independent review of the hook.

The composition/packet review completed two passes across all 17 selected
files with no warnings. Its second confirmed finding concerned a failed or
non-boolean cancellation poll discarding completed attempts. Polls now latch a
safe cancellation diagnostic and retain actual attempts/invocation counts.
Root review also required final-poll time to count in the budget remainder.
The 32-case DAG suite passed in a separate root rerun (2.588 seconds). A prior
31-case root rerun caught a wall-clock-sensitive five-millisecond test; a
controlled clock now verifies both retained late output and blocked descendants.

The observer/hardening review completed two passes across six selected files,
with no warnings and one low-severity performance finding: prior write heads
were decoded twice. Before-change pins now use the already-checked revision,
without an extra read. The expanded eight-case hook suite passed in 0.821
seconds after that correction, including preexisting-watch audit, atomic watch
replacement and closure of every public system-port method after its phase.
The unchanged normal storage transaction suite also passed 21 tests in 2.468
seconds. Final remediation review remains a combined publication gate.

MAT-015 reached a stable 19-case focused milestone (20.575 seconds), covering
its three acceptance criteria, unknown/expired cache results and actual stored
qualified-result expiry. Runtime/source review plus fresh render/validate checks
admitted MAT-016 development against that API. MAT-015 is adding further
negative-scope, time and staged-prerequisite cases; neither ticket is marked
done on this preliminary milestone.

Final focused milestones before combined qualification:

- MAT-015: 33 tests passed in 35.558 seconds, including complete original
  semantic-target coverage, source READ checks, mapped-claim dependencies,
  staged-target scope refusal and the MAT-016 current-registration seam.
- MAT-016: 25 tests passed in 20.177 seconds, including actual assessment
  publication/invalidation/republication, immutable correction notices,
  candidate-member changes, scoped query isolation, recomputation races and
  capacity fallback that preserves an actual operator control.
- The system observer port now bounds watch cohorts before loading records.
  Ten tests passed in 0.682 seconds, including over-limit refusal without
  partial effects and exact-limit success. The normal snapshot/handler watch
  APIs remain unchanged.
- The final graph/storage remediation review completed two passes over six
  selected files with zero findings and no warnings. MAT-015 and MAT-016
  independent reviews and the final bounded-watch change remain pending here.

Root review required the existing control contract's complete target set;
READ permission alone does not let a narrow matter token cover additional
source work. Newly discovered targets require a suitably scoped new attempt,
not token renewal. Proof-only catalog validation stays distinct from explicit
semantic reads. General freshness does not grant qualification or authority.

The tested backend for this batch is SQLite. A neutral storage port is not
evidence of an implemented or qualified PostgreSQL adapter. Provider calls,
private corpora and downstream repository changes remain outside these checks.

## Initial combined run and review remediation

The first frozen runtime/package/test input set contained 421 files. The full
suite passed **986 tests in 393.403 seconds** with the canonical physical
temporary directory. JavaScript verified 26 canonical and eight exact-source
vectors; all three synthetic walkthroughs passed. The isolated dev13 wheel ran
the ten existing examples and all seven selected new behavioral test modules
outside the checkout; all 110 Python/SQL/schema resources matched source bytes.
Rechecking the frozen inputs reported zero changes.

Those results are preliminary, because independent review then identified
three confirmed assessment/cache issues: late qualification could leave an
unmapped node's proposals/current state usable, an invalidated control context
permanently occupied a semantic cache address, and cache-result metadata was
accepted without checking actual transaction state. They are being corrected
with new behavioral regressions; the initial passing suite does not waive them.
The invalidation review also identified an unnecessary loose schema-directory
copy in the installed check. It is removed, and the installed check asserts
that only packaged schemas are available.

Root source review found that fallback itself could parse a malformed cached
scope-fence value and roll back an admitted control. The replacement fence now
needs only the verified storage revision, preserving history and fresh-pin
refusal without trusting the damaged domain payload. That remediation and its
actual control-service regressions are in progress. Final source changes
require another frozen combined run and installed-wheel verification.

The completed assessment review artifact covered nine selected files over two
passes with no warnings. Its raw findings contain seven distinct claims (the
summary merges two claims at the same cache line). Six are accepted and fixed:
fresh usability-dependent fields at commit/current, control-generation cache
slots, strict cache metadata/qualification checks, complete flat prior-basis
cause classification, one frozen view per graph, and misleading dead helper
parameters/imports. The expanded 42-case suite passed in 55.920 seconds.

The seventh claim proposes accepting a competing cache fill. The existing
checked-read contract instead conservatively refuses an assessment whose
original cache absence changed: the new entry was not an original declared
read. No undeclared-read bypass is added. The new concurrency regression
proves the refusal is durable, the winner is immutable, and a new appropriately
captured attempt publishes a hit without another computation. This limitation
is explicit in the API and ticket receipt.

## Bounded final closeout

The assessment follow-up review completed both passes with no warnings. Its
incorrect deadline cause label is fixed; temporal cache classes now produce
`temporal_transition`, verified by publication into the same lane across a
deadline. Duplicate graph verification was removed. Conservative cache misses
across different original operator/target contexts remain an explicit safe
tradeoff; projection-scoped token optimization is deferred. The final focused
assessment suite passed 43 tests in 56.072 seconds.

The invalidation review completed both passes across all 12 selected files
without warnings. The historical temporal-cohort wedge is fixed with a bounded
live, generation-scoped exact temporal index. Invalidated historical nodes no
longer consume live admission or get scanned on every transaction. The fixed
512-live admission cap and prefix-key cost are documented in the API. The
restricted-static-policy publication failure was reproduced, then fixed by
checking registered derivatives transitively instead of demanding a new source
READ grant for generated output IDs. Source READ denial still invalidates their
descendants. The final focused invalidation suite passed 34 tests in 28.103
seconds, including the malformed-fence fallback repairs. No further feature
expansion, PostgreSQL implementation or live provider work is part of closeout.

Final combined regression, wheel verification and remediation review results
will follow. Earlier passing runs are retained as preliminary evidence only.

The next combined source run passed 1005 tests in 420.880 seconds and repeated
the isolated 110-resource wheel check successfully. Its closeout review found
two further timer boundaries: already-due rows charged to live admission, and
ordinary intake parsing a damaged derivative fence. Both were reproduced and
fixed without a storage API change. Future-only admission handles bounded
due-plus-future rows; ordinary sweep uses the verified fence pin while operator
controls explicitly repair malformed metadata. The expanded 36-case invalidation
suite passed in 30.438 seconds. Final verification below applies to this last
repair, not merely to the preceding 1005-case source set.

## Final source and executed merge gates

Runtime candidate: `090a7be2a04e51c37c84a417bf55ac903ea62d67`.
The final 421-file input manifest was unchanged after installed checks; its
SHA-256 is `a603c7fad8839a3c4b4251ac0c09fcf9ef414a64225e935faa0dbc81d5851224`.

The full local suite passed 1008 tests in 440.693 seconds on the immediately
preceding `9a277c7` source. The final clock-only change then passed all 37
invalidation tests in 35.894 seconds, including the new actual-publication
boundary regression. The final installed dev13 wheel ran all ten examples and
183 selected tests (32 DAG, 33 rendering, 22 packets, 44 assessment, 37
invalidation, five conflict-classification, ten system-hook), outside the
checkout with no loose schema directory. All 110 Python/SQL/schema resources
matched final source bytes. Wheel SHA-256:
`ac54372894fb21013c9b2b574ec8111f30afa4cddec7df89c73465e54f39f4f7`.
JavaScript verified 26 canonical and eight exact-source vectors, and all three
synthetic walkthroughs passed. The canonical physical TMPDIR workaround avoids
the pre-existing macOS path-alias backup assertion; no storage behavior was
changed for that assertion. Installed jsonschema/referencing dependencies were
available; there was no missing-package blocker.

All supported implementation files were covered by the staged two-pass
independent reviews recorded above. The last cause-label follow-up reviewed
both selected files with zero findings/warnings; the final clock follow-up
reviewed both selected files with zero findings/warnings. Earlier material
findings were fixed and tested; conservative cross-context cache misses and
concurrent-fill stale refusal remain documented tradeoffs. Markdown exclusions
were read manually and local documentation links/schema inventories validated.
The operator explicitly waived waiting for GitHub CI before merge. No CI
success is inferred from the local results recorded here.

MAT-014/015/016/027/028 are complete within their bounded synthetic mechanism
scopes. MAT-029 remains waiting on MAT-020; MAT-030/031/032 retain their declared
chain, and MAT-039/040 retain provider-family, replay/split and qualification
prerequisites. MAT-017/018 then MAT-019/020 are the next core prerequisites for
that integrated path. None of the 22 cross-repository roadmap items was changed.
PostgreSQL is deferred; only SQLite is implemented here. No live JEV/TypeSafe
call, private corpus, provider qualification, production timing qualification
or downstream deployment is claimed. No retained merged branch was deleted.

## Merged closeout

PR [#15](https://github.com/mfreeze77/matter/pull/15) merged into `main` at
`c755dd991a9323fa89419a2f9a02aee011f6098b` on 2026-10-27. The operator explicitly
instructed merging without waiting for GitHub CI; that instruction supersedes
earlier CI merge-gate wording in these chronological notes. Local checks and
review evidence above remain the evidence actually executed. The merge tree
matched the reviewed head, and the local checkout was synchronized cleanly.
