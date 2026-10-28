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
