# StateCivics contextual monitoring replay checkpoint

Date: October 27, 2026 (execution receipts extend into October 28 UTC).
Matter preparation: PR #18, `a6bb1776aa73`; SDK core unchanged from `acc7b0cad2`.
StateCivics implementation: local branch `feat/matter-monitoring-replay`, tested
commit `f412e3415`. This is bounded mechanism evidence, not civic/provider
qualification or production deployment.

## No-login rehearsal closeout (October 28 UTC)

The existing KS-841 stack now serves `http://localhost:8080/rehearsal/replay`
without credentials or a login redirect. StateCivics source `5af45f817` was
walked in Chrome using the shared replay console. Its original native-admin
route remains separate. The KS-1106 work at `ca7b9a3aa` was merged into the task
branch, retaining both ticket rows and the other session's ignored evidence.

Local StateCivics `main` now contains this integration at `c2325ba89`, with a
clean checkout. It also preserves `795aa1d2c`'s newer owner decision: KS-574 is
superseded; workstation hearing/provider work belongs to crawler CR-148, while
StateCivics retains receiver/import/publication work under KS-1104. No KS-574
implementation was started here. Runtime/source bytes are unchanged from the
walked `5af45f817` checkpoint. This is a local merge, not a hosted push.

The final browser run (`941f5cec-6238-4447-8270-1515eab1343a`) completed all
12 releases: **48 decisions, 19 in-app captures and 40 factual activity
associations**, matching the independent expected trace. A separate HTTP read
sent no cookie or bearer token and verified the same result. Run creation,
Next, explicit digest capture, completion, reset and paced Play/Pause were
exercised in the actual rehearsal. Before s09, only eight releases/32 decisions
were available and its evidence returned 404. Foreign/missing-origin writes
returned 403.

Admission requires development mode, the explicit local rehearsal flag, local
host/same-origin writes, the uncached marker and the actual PostgreSQL cluster
identifier. A deliberately wrong cluster ID rejected catalog reads and run
creation with 503 before effects; restoring it restored access. This is stronger
than comparing database/role names, which rehearsal and production share.
No copied product users were created. Effects remain in replay control/run
schemas and the existing capture sink.

Latest executed checks:

- **339 backend tests passed** at `8a3e9df9c`, including native authority,
  manifest/projection, API/route inventories, admission and delivery. Eleven
  existing deprecation/SQLite cleanup warnings; no failures.
- **29 targeted tests passed** at `d04479d5b`, including the async connection
  guard's actual runtime dispatch and installed-input verification.
- Full TypeScript check and **92 frontend tests passed** at `8a3e9df9c`.
- **26 original SDK-free PostgreSQL cases passed** at `5af45f817` (the four
  optional Matter cases were deselected), with no skips/errors/failures.
- **30 PostgreSQL cases passed** at `8a3e9df9c`, no skips/errors/failures;
  source/harness stability and owned-resource cleanup passed. The controller
  now requires/hashes its actual decision trace.

Private StateCivics artifacts: `.release/ks1105-matter-replay/` contains the
browser/API receipts, cutoff snapshot and negative checks. Final actual trace
SHA-256: `6f449b2a4eeca9cfb6e738a6e621a081eade298b668dfce2f9bddc5a66433314`.
The 30-case proof is
`.release/ks698-replay-runtime-reports-20261028021339-8061-30379/`; JUnit SHA-256:
`917c72bc1aee1fc04f23d3fed84252706b04dd68e348548f19da9a3a6ddaa468`.
Its controller-recorded trace SHA-256:
`22eec8172db2ad4725c600370f049d173ccb40a91145f40222f5fcd651f21f4c`.

## Earlier runtime checkpoint


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

## Remaining limits and review disposition

- This is deterministic structured-source mechanism evidence. No new JEV,
  recorded executor or LLM writer call occurred; no provider qualification,
  real/private evidence, external delivery or production deployment is claimed.
- MAT-046/047/048/049/050 and their canonical prerequisites remain separate.
  MAT-049 stays planned; this bounded host integration does not complete civic
  source adaptation or receiving-system acceptance for real evidence.
- The installed walkthrough-schema failure remains unresolved and separate.
- Rehearsal enablement reuses the existing archive freshness helper and requires
  a clean tracked commit. After enabling, normal hot reload remains available;
  the initial check does not qualify later source edits. Stale installed inputs
  fail verification with preservation instructions, rather than being deleted.

Initial nine-file and later fourteen-file reviews produced 15 and eight
findings respectively; those confirmed findings were fixed. The no-login change
and follow-ups received two-round independent reviews covering 17, eight, eight
and four files, with 14, five, five and two findings respectively. All groups
completed with no warnings. Confirmed fixes include truthful mode labels,
malformed-input refusal/column limits, immutable capture and pending digests,
artifact hashing, optional-SDK test specificity, route inventories, async
connection dispatch, real cluster identity, client withdrawal handling and
launcher cleanup/recovery. Clean-at-enable is the documented limitation above;
no replacement gate was added. The final small wording corrections were
manually checked against these findings.

Review results remain locally in `/tmp/ks1105-no-login-review.json`,
`/tmp/ks1105-rehearsal-followup-review.json`, `/tmp/ks1105-cluster-review.json`
and `/tmp/ks1105-launcher-final-review.json`.

The separate Matter JSON review covered both changed JSON files in two rounds:
zero findings or warnings. Its applicable rule checks key spelling; it is not
behavioral integration evidence.

Storage: 69 GiB free initially, 63 GiB at the last check, above the 50 GiB reserve.
The retained private traces/logs are small; no real corpus or production copy was
made. Test PostgreSQL used bounded tmpfs and cleaned up its owned resources.
