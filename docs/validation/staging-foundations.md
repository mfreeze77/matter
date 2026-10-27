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
