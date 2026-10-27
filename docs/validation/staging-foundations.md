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
