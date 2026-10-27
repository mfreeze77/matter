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
cases and limits. No runtime/schema/test/example/workflow changes followed
the combined qualification freeze of 393 input files.

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
These remediations and their final gates are not yet claimed passed here.
Source review and synthetic checks do not establish provider accuracy or
live usefulness. No provider evaluation, model download, credential use,
native integration, assessment engine, rollout or deployment ran.
