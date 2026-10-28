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
