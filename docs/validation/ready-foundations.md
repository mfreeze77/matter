# Ready foundations implementation batch

## Scope and ordering

The operator authorized implementation after the read-only backlog inspection.
The reviewed base is `1b5123a0347b9009181bff05aaf250d453c789e1`.
Canonical records still showed MAT-013, MAT-026 and MAT-036 planned with all
dependencies complete. These three Matter-owned foundations form this batch.

MAT-013 has first priority because policy definitions unlock MAT-014's graph
execution, then MAT-015 assessment publication and MAT-016 invalidation.
MAT-026 supplies the independently ready typed executor boundary. MAT-036
establishes frozen corpus and label provenance before later evaluation. Workers
own separate modules and focused tests; shared integration and final checks
are coordinated together. MAT-014–016 are subsequent work, not completed by
this batch. Cross-repository tickets, provider experiments, deployment and
branch cleanup are outside this batch. Research additions remain proposals.

## Environment and storage plan

The initial active Python 3.12.14 environment lacked `jsonschema`. A local
ignored `.venv` was created and installed editable with `requirements-test.txt`
constraints. The baseline `render --check` and `validate` both passed:
80 tickets, 104 requirements, 40 schemas and three walkthroughs, zero errors.
No dependency blocker remains for those checks.

Before qualification the destination volume reported 98 GiB available; the
checkout used 24 MiB and the existing pip cache used 690 MiB. Generated output
is budgeted below 1 GiB for this batch, within the workstation's 10 GiB task
budget and 50 GiB free-space reserve. The local environment, small test/review
logs, wheel and isolated installation are the expected outputs. No corpus or
model downloads are planned. Logs and wheel artifacts go under an external
temporary task directory; source, synthetic fixtures and validation receipts
remain in this checkout. Task-owned temporary artifacts may be removed after
review; no pre-existing data or branches will be deleted.

## Qualification

The focused behavioral suites passed: MAT-013 24 tests in 0.212 seconds,
MAT-026 32 tests in 0.201 seconds (a subsequent run took 0.215 seconds), and
MAT-036 27 tests in 0.547 seconds. Per-ticket receipts describe their acceptance
cases and limits. The combined qualification freeze of 393 input files remained
unchanged through the 824-test pass and initial independent review. Subsequent
review remediation changed only corpus error paths and two test files. A second
393-input freeze binds the final remediation qualification.

The first full regression run on 2026-10-27 ran 824 tests in 357.865 seconds:
823 passed and the unchanged storage-backup path assertion failed. The test
compared `/var/folders/...` with SQLiteStore's resolved `/private/var/folders/...`
destination on macOS. The backup test and implementation have no diff from the
reviewed base. Setting only the child process's `TMPDIR` to
`Path(tempfile.gettempdir()).resolve()` made all 12 backup tests pass in 0.626
seconds. A complete second run under that canonical temporary-directory setting
passed all **824 tests in 335.735 seconds**, from 2026-10-27T02:42:28Z through
02:48:04Z (336.072 seconds wall time). No storage source or existing test was
changed to accommodate this environment issue.

Repository validation and generated-file checks pass with 80 tickets,
104 requirements, 41 schemas and three walkthroughs. All three synthetic
walkthroughs pass; the independent JavaScript verifier matched 26 canonical
and eight exact-source vectors. Whitespace checks pass.

## Isolated package checks

Built `matter_foundation-0.1.0.dev12-py3-none-any.whl` and verified its 92
Python/schema/migration resources match the frozen checkout byte-for-byte.
Its SHA-256 is
`215c1583cb5336d7c585e5f25af55e981239211dd919e0161982d7502b204e74`.
A separate constrained environment installed that wheel; ten copied examples
passed outside the checkout in 42.394 seconds, from 2026-10-27T02:36:49Z through
02:37:31Z. The combined foundations example took 0.248 seconds and exercised
historical profile resolution and independent component fingerprints, exact
typed response normalization with consequential use disabled, and the six-episode
synthetic corpus's declared denominators and availability prefix.

The existing nine installed examples covered association, claims/citations,
identity correction, continuing matter identity, observation intake,
occurrence grouping, rule evaluation, temporal coverage and trusted controls.
The workflow now runs the combined foundations example outside the checkout
on both Python matrix versions. Local execution here used Python 3.12.14;
remote CI and local Python 3.11 results are not inferred from that run.

## Independent review and remaining gates

OpenCodeReview's subscription bridge completed its default two passes over
19 supported changed files in four deterministic rule groups. Its preview
excluded 18 Markdown/JSONL files as unsupported; repository link/projection
checks, source review and behavioral corpus tests cover those separately.
The Python group's first pass reported two confirmed low-severity test-quality
findings: malformed response fixtures could fail for an unrelated missing-answer
reason, and an equal-time parent-order test did not independently exercise
decreasing chronology. No production defect was reported by that pass.
The second pass found one additional low-severity defect: two corpus validation
error paths interpolated caller-supplied observation IDs, contrary to the safe
`ContractError.detail` contract. All three findings were confirmed against source;
all 19 selected files were reviewed, every round completed, and there were no
review warnings. The follow-up will use numeric manifest indices in error paths
with marker-redaction tests, strengthen malformed response tests to require
specific faults, and independently exercise decreasing root availability.
The remediation outcomes and final gates are recorded below.
Source review and synthetic checks do not establish provider accuracy or
live usefulness. No provider evaluation, model download, credential use,
native integration, assessment engine, rollout or deployment ran.

## Review remediation

The corpus now uses numeric observation positions in every validation error
path. New marker-ID regressions exercise parent, chronology and membership
failures and require that neither `detail` nor the exception string contains
the rejected identifier. The chronology regression first validates increasing
availability for two independent roots and then rejects descending availability
at the specific chronology path. Semantic malformed-wire cases now start from
otherwise valid complete responses and assert exact parser/primitive faults.

The revised corpus suite passed 29 tests in 0.655 seconds, and the revised
semantic suite passed 32 tests in 0.218 seconds. The focused independent
two-pass review covered all three changed Python files, returned **zero findings
and zero warnings**, and completed both rounds. The source review traced numeric
error positions, downstream callers and each strengthened failure case.

The rebuilt final dev12 wheel has SHA-256
`f95894fa0875f40f846faceb4047e88d2eccef22572d3bc3b60500b01619d4e5`.
Its 92 resources match the final frozen source. All ten copied examples passed
again after force-reinstalling that wheel into the isolated constrained
environment outside the checkout. The earlier wheel hash above identifies the
pre-remediation artifact, not the final candidate.

## Final combined result

All **826 tests passed in 344.831 seconds** on Python 3.12.14 using canonical
`TMPDIR`, from 2026-10-27T02:54:09Z through 02:59:54Z (345.171 seconds wall time).
This includes all 741 previous cases and 85 foundation cases: 24 profile,
32 semantic and 29 corpus tests. All 393 final frozen inputs were unchanged
after the run. The final input-manifest SHA-256 is
`66f6c833761eb7d80978bdcf5a5235468f6d36b845462f45050ae396f3d4f3da`.
The final isolated examples took 45.803 seconds, from 02:54:41Z to 02:55:27Z.

Canonical MAT-013, MAT-026 and MAT-036 are complete on this task branch with
local acceptance evidence. Ticket projections and repository validation are
checked again after completion metadata changes. MAT-014, MAT-015 and MAT-016
remain planned; MAT-027 and the civic contract work have their own tickets and
prerequisites. All 22 cross-repository roadmap items remain unchanged.
No remote CI result or merge is inferred from local acceptance; submitted-head
CI is reported in the PR. These interfaces are not an integrated qualified
assessment runtime, provider accuracy result or live usefulness trial.

## Retained evidence and storage

Raw local logs, frozen manifests, the final wheel and isolated installation are
retained under the external temporary task directory
`/var/folders/hn/c0zg49fj73g5bnwl67mj83mm0000gn/T/matter-ready-foundations-fvv8kp_x`.
Independent-review sessions are
`~/.ocr-bridge/sessions/20261026-213538-877203` and
`~/.ocr-bridge/sessions/20261026-215421-55f445`. These paths are local execution
evidence, not portable requirements or private-corpus destinations. The checked-in
receipts preserve the commands, outcomes, limits and final artifact identities.

After qualification the volume reported 100 GiB free. Measured logical sizes
were 46 MiB for the checkout (including its 16 MiB ignored environment and
generated build output), 19 MiB for the task directory, and about 3 MiB for the
two review sessions. Compared with the initial 24 MiB checkout, measured retained
growth is approximately 44 MiB, well below the 1 GiB planned peak. The pip cache
remained about 690 MiB. These logical directory totals are not an exact APFS
allocated-space accounting. No pre-existing files or merged branches were deleted.
