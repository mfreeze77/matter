# StateCivics contextual monitoring replay checkpoint

Date: October 27, 2026 (execution receipts extend into October 28 UTC).
Matter preparation: PR #18, `a6bb1776aa73`; SDK core unchanged from `acc7b0cad2`.
StateCivics implementation: local branch `feat/matter-monitoring-replay`, tested
commit `f412e3415`. This is bounded mechanism evidence, not civic/provider
qualification or production deployment.

## Actual runtime evidence

The existing KS-698 PostgreSQL proof controller ran the actual replay runtime,
existing county event writer and subscriber feed, private intent/assessment
records, installed Matter attention policy and existing in-app delivery planner.
It reused run schemas, transactions, custody/cutoff rules, retry/reset handling
and authority rechecks. No second database backend, queue, retrieval system or
notification service was introduced.

The separate [runtime inputs](../../examples/civic/purpose-comparison/runtime-inputs.json)
contain authored structured source interpretations and declarative context
policies. They are separate from the [expected-result oracle](../../examples/civic/purpose-comparison/monitoring-scenarios.json).
The installer consumes only runtime inputs. This does not test whether a model
can infer those facts from the prose; no JEV or LLM provider was called.

Observed main trace:

- Twelve source/context checkpoints and four audience/work lanes: **48 actual
  decisions**, compared with the unchanged authored expected trace.
- **23 quiet, 10 update, 9 digest and 6 correction** decisions.
- **19 observed in-app captures**: cloud company 6, privacy coalition 6,
  district IT 5 and district finance 2. Eligibility alone did not advance a
  delivered baseline; digests required an explicit capture checkpoint.
- **40 canonical activity associations** remained readable, including factual
  developments whose optional intelligent interruption was quiet.
- A separate regression inserted another minutes reprint before digest capture
  and changed an already-informed client's context. Pending digests survived the
  reprint, and the original delivered record remained unchanged beside the new
  context's capture.

Capture is a trusted operator command at the current cutoff. Source evidence
cannot request a flush/send. The late-correction test captured the earlier
digests before advancing the correction release. Context revisions, duplicate
observations, different-jurisdiction identifiers and source metadata remain
separate; no procurement record was represented as a bill.

## Executed checks and source identity

- Existing controller, Matter opt-in: **30 PostgreSQL cases passed**, exact
  identities, no skips/errors/failures. Includes the 26 existing cases and four
  Matter integration cases (complete trace, retry/reset/future-evidence fencing,
  revoked-authority rollback and reprint/context capture history).
- Existing controller, ordinary image with no Matter SDK: **26 original cases
  passed**, exact identities, no skips/errors/failures. The optional binding does
  not make the original replay require Matter.
- Focused frozen-archive Docker manifest/projection/adapter/API admission and
  delivery checks at `f412e3415`: **199 passed**, with 10 existing SQLite
  FK-cycle cleanup warnings. This reused the gate image and protected entrypoint
  without switching or mounting the shared checkout; it is a supplemental
  pinned-source check, not a new canonical-checkout gate receipt.
- Frontend frozen-archive validation at `f412e3415`: full TypeScript check
  passed and **25 replay-console tests passed**, including the latest capture
  interface. Dependency-image freshness passed before the run. No authenticated
  browser walkthrough was performed.
- Matter preparation: `render --check`, `validate`, and **39 repository and
  hardening tests passed**. The runtime input bytes match the executed
  StateCivics fixture exactly (SHA-256
  `84b574973ece97ccdc96d718d2a07f5c737b8a92c5c459dcc2bad6ce2e27aa21`).

Controller command for the 30-case run (from the canonical StateCivics checkout):

```sh
KS698_WITH_MATTER=1 KS698_NETWORK_SUBNET=10.231.98.0/28 \
KS698_TEST_IMAGE=ks-test-runner:matter-ks1105 \
KS698_EXPECTED_COMMIT=f412e3415f183bb0064e1b16b974430721bae79e \
bash scripts/operator/historical_replay/controller.sh
```

The actual invocation used `KS698_EXPECTED_COMMIT=$(git rev-parse HEAD)` at that
commit; the receipt stores the same full source pin.

The existing gate image was extended only by installing the Matter wheel
offline with `--no-index --no-deps`, with no application rebuild or network
dependency installation. Wheel SHA-256:
`39134fed09e92bfc8b75b1f120c74371c4f3e9b795a2ffdf8a5258ccb63c5c06`.
SDK test image ID:
`sha256:41828b97df928f49cd34a2c116b1673534178692e8a56eea2a62042745338b25`.

Private local StateCivics receipt directory:
`.release/ks698-replay-runtime-reports-20261028011423-90873-8921/`.
`matter-timeline.json` retains the actual snapshot (170,324 bytes); its adjacent
JUnit SHA-256 is
`bf0895719d0cd0b6130ba46d28962f1c4be02281c75d2c167c818d083062c6ff`.
The original replay proof's JUnit SHA-256 is
`a45e07ad054a4f4273feba6c4162d564022c8672099a943bf7dc854e46937be1`.
Source/harness stability and disposal of owned test resources passed in both.
The trace's SHA-256 at this documentation inspection is
`ac705468d04009ec3020d6f703078fe669e818fde43618a70b6de90f3fdd5d12`;
this was calculated after the run, not recorded by the controller itself.

Supplemental final-interface logs are retained locally at
`/tmp/ks1105-final-frozen-backend.log` (199 tests) and
`/tmp/ks1105-final-frozen-frontend.log` (TypeScript and 25 tests). These checks
streamed the exact `f412e3415` Git archive to the existing Docker test recipes;
they did not change the branch checked out by the other session. Backend
freshness was compared with the target commit's four baked dependency inputs;
frontend freshness inputs/helper were unchanged and its existing freshness
check passed. Backend selection was the adapter, manifest, projection, replay
API and alert-delivery test modules. No alternate checkout was created.

## Limitations and remaining work

- These are deterministic structured-source checks, not recorded executor tests,
  new live JEV calls, independent civic labels or provider qualification.
- Owner correction after this checkpoint: replay must run in the existing
  KS-841 rehearsal **without a login**. Its README and Compose configuration
  confirm sign-in is already disabled and copied accounts/sessions are excluded.
  The older KS-698 admin route requires a native session and a different database
  identity; that is an integration mismatch to fix, not a login prerequisite for
  the user. Rehearsal must reuse the replay mechanisms with synthetic run
  isolation and capture-only delivery. No-login browser acceptance remains
  untested. The PostgreSQL proof uses a controlled authority callback; route
  admission tests control native transport seams. Neither proves rehearsal
  browser access.
- The LLM writer, real/private evidence and external alert delivery remain out
  of this slice. MAT-046/047/048/049/050 and their canonical prerequisites remain
  separate; this host fixture binding does not complete them.
- The installed walkthrough-schema failure remains unresolved. Checkout or
  replay success does not establish installed walkthrough success.
- The shared StateCivics checkout was switched by another session to `main` at
  `9a27309ad` after both frozen-source proofs. Implementation is safely committed
  on its feature branch. Checkout ownership must be coordinated before further
  edits, per that repository's AGENTS.md; no concurrent work was overwritten.

Initial independent review covered nine code files in two rounds, with 15
findings and no skipped groups/warnings. Confirmed findings were addressed,
including optional-SDK admission, immutable capture history, pending digest
selection, meaningful cutoff probes, default gate compatibility, and Mac shell
array handling. Final source review subsequently completed: 14 files, four
groups, two rounds, eight findings, no skipped groups or warnings. The findings
below remain unresolved while checkout ownership is pending:

- The shared replay banner still describes retained history and the legacy
  detector during the synthetic Matter mode; its mode-specific disclosure must
  agree with the contextual-monitoring panel.
- Malformed installed context IDs/timestamps or deeply nested input can escape
  the sanitized admission error, although admission still fails closed.
- Context/client name limits accepted by the installer exceed existing database
  column limits; a longer valid-looking installation can fail during seeding.
- Baseline context IDs need an enforced match to their manifest subject IDs,
  which the capture button uses. The supplied installer already produces a
  match, but admission does not require it.
- The frontend snapshot contract comment and archive refusal message need small
  corrections.
- The controller records JUnit identity but does not require or hash its emitted
  `matter-timeline.json`. That trace's existence/counts were inspected separately;
  controller-bound artifact identity remains an open receipt gap.
- In an SDK-free image, the bad-context admission test can pass on the unrelated
  missing-SDK refusal. It needs a direct assertion of the intended context
  validation error. The 199-test run above used the SDK image; this finding does
  not invalidate that run, but weakens the ordinary-image regression check.

Final review result is retained locally at `/tmp/ks1105-review-final.json`.

The separate Matter JSON review covered both changed JSON files in two rounds:
zero findings or warnings. Its applicable rule checks key spelling; it is not
behavioral integration evidence.

Storage: 69 GiB free initially, 64 GiB at the last check, above the 50 GiB reserve.
The retained private traces/logs are small; no real corpus or production copy was
made. Test PostgreSQL used bounded tmpfs and cleaned up its owned resources.
