# MAT-084 frozen 1.1 SDK handoff to StateCivics

Status: **1.1 frozen and receiving-accepted**, 2026-10-31.
See the [freeze record](../contracts/monitoring-handoff-v1.1.md) and
[final receiving receipt](../validation/MAT-084-receiving.md).
This extends the merged MAT-082 adapter. It does not activate StateCivics,
Workbench/state-intel, delivery, a production model or a qualification certificate.
KS-1124's deterministic approved-fields-and-event fallback stays on 1.0; model
notes must stay outside that rule.

## Exact package

- Source/runtime commit: `1f525c6a66593573f2ae5d2af1eaf2bd00460a35` on PR #31.
  Later test/receipt/vector-only commits may advance the PR without changing SDK bytes.
- Package and runtime version: `matter-foundation==0.1.0.dev16`.
- Existing wire: `monitoring-handoff/1.0.0`, unchanged.
- Optional frozen wire: `monitoring-handoff/1.1.0`.
- Retained wheel on this shared checkout:
  `data/validation/MAT-084/wheel-bounded/matter_foundation-0.1.0.dev16-py3-none-any.whl`.
- Full wheel SHA-256:
  `6fae4d57c9d8115d43c21e5d708ee94799c4fed43f2753324c3ee6e9ccc774bb`.
- 204 runtime files match the pinned commit byte for byte. Built with Python
  3.12.14, without network/dependency resolution; `Requires-Python >=3.11`.
  A consumer rebuild can have a different wheel digest; compare every packaged
  source/schema/migration file and record its own full digest, not a prefix.
- Machine-readable inventory: `data/validation/MAT-084/package-manifest.json`.
  The frozen 1.0 inventory's 60 artifacts match their lock; lock SHA-256
  `ffe1dc889b50dec3a7efb07e4796ee62e194569be826e8f53b303f96203f1fa7`.

The wheel is a retained local build artifact, not a published package-index
release. StateCivics owns its SDK image build/install and image digest. KS-1121's
minimum remains merged #26. Saved objectives need merged #29's prerequisites
plus this explicitly selected candidate; the existing merged `10a7d9a` image
alone does not contain MAT-084. No SQLite repair is hidden in this package.

## API, policy and wire migration

The [implementation handoff](statecivics-capture.md) describes exact callable
names, server-owned configuration and responsibility boundaries. Imports are
from `matter.statecivics_capture`; the shared `conveyed_capture_identity` is the
same function also exported by `matter.statecivics_monitoring`.

Required host additions:

1. Install an immutable `MonitoringCapturePolicy` through the real controls.
   Supply exact monitoring question identities, an explicit native
   `PrecisionProfile.value`, independent decimal positive/negative regions,
   stable source material paths, and an explicit native baseline mapping when
   needed. There are **no threshold defaults**; test values are illustrative.
2. Add the real policy pin as `HostMonitoringState.capture_policy` and configure
   `MonitoringHost.capture_service` over the existing receipt/control/storage
   owners. Include `proposal_basis` in the trusted 1.1 projection. Preserve
   authorized owned watchlist **and item**, activity associations and lifecycle.
3. Select 1.0 or 1.1 per objective. Model-driven 1.1 uses `admit_capture()` and
   `project_capture()`, never `project()` with a forged native assessment.
   Decode `decision_basis`, `capture_key`, `consequential_use: false` and nullable
   `assessment_reference`. Preserve unqualified provenance and unknown judgments.
4. Map actual captured host history through `ObservedMonitoringCapture`.
   Native baselines retain real native assessments; study baselines retain real
   capture-admission references and actual isolated capture receipts. Do not
   invent a native delivered milestone or turn unknown capture into no history.
5. Call the SDK identity function and existing atomic sink guard. Keep all
   results capture-only. A reused source reading is a real source-only receipt;
   each audience still needs current access to its transitive protected roots,
   its own objective/novelty execution, original token and budget.

## Capture-control attempt recovery

The host can supply `command_id` and `idempotency_key` to `admit_capture` and
persist them with its control attempt. An exact retry preserves that attempt's
recorded result, including a definite transaction conflict. After a **confirmed
failed** control transaction with still-current inputs, choose a new control
attempt ID/key and pass the **same execution pin**; the SDK rechecks all current
source/context/access bindings. No new `execute()` call or provider attempt is
needed. Do not change keys to hide an uncertain storage/sink result; reconcile
it through the existing receipts/history. The installed conflict test verifies
this path against an actual unrelated control inserted between prepare and commit.

## Consumer conformance before freeze

The [recorded candidate vectors](../../tests/fixtures/civic/handoff-v1.1/manifest.json)
ship before freeze. They cover the same source with two audiences (positive,
quiet and unknown) and actual native-to-study baseline comparison. These are
recorded synthetic component traces; opaque pins do not rehydrate records,
authority or captures in another database. Use the real host projection and
records for admission, and use the wires for decoder/mapping conformance.

The portable check is `contract.test_monitoring_capture_vectors` from this
checkout's tests. It checks hashes, installed/published schema parity, 1.0
refusal of 1.1, explicit unknown and baseline/result provenance. Run it with
`matter` imported from the SDK image, not an editable checkout. The retained
`data/validation/sdk-handoff-20261030/run-installed-tests.py` harness disables
editable import finders and provider network and checks every loaded Matter
module's installed path; the current receipts are in
`data/validation/MAT-084/installed-*.json`.

KS-1124 should record image identity, wheel/source identity, checked vectors and
actual host outcomes: both capture targets exist and are authorized; model
positives stay unqualified; quiet/unknown don't become irrelevance or captures;
duplicate rows are suppressed; changed context/access withholds pending output;
corrections survive old handled feedback; unknown sink acknowledgements are
reconciled, not resent. Return that receipt before freezing 1.1. KS-1125 owns
host explanations/feedback and KS-1126 owns the two-objective receiving run.

Actual Matter-side results and remaining gates are maintained in
[the validation receipt](../validation/MAT-084.md). Passing these checks is not
live JEV interpretation quality, StateCivics receiving acceptance or MAT-040
qualification. No new live calls were made for this implementation.

## Receiving closeout, 2026-10-31

StateCivics KS-1146 accepted this exact runtime in image
`ks-test-runner:matter-1f525c6`, ID
`sha256:e6d1f7c98e5735e5dde8e74d121f4067391f40d18d65e8c1c4e5752eec72ef6e`.
Its Python 3.11 rebuilt dev16 wheel SHA-256 is
`19b1dfe6253d5912119436b623de9bf85cf848454186de35482a9a338e545aa2`;
all 204 packaged runtime files match `1f525c6`. Reported receiving checks:
29 Matter checks, four model-path checks, seven host-rule checks on each SDK,
and 35 PostgreSQL proof cases. Final StateCivics code is `bccca8b17`, with
closeout on main at `d34fcf291`. The statewide suite retains its known baseline
failures. The receipt above supplies the complete attribution and limitations.

The pre-freeze instructions above are retained as the conformance procedure;
the receiving gate is now satisfied. The recorded vector manifest retains its
historical candidate-generation status. New StateCivics features (corrections,
shared source reading and indexed-candidate handoff) are not freeze blockers.
After merge, rebuild from the merged commit and compare packaged files with
`1f525c6`. This freeze changes docs, tickets and the compatibility check only;
`src`, `schemas` and `pyproject.toml` remain byte-identical. Performance and public
milestone API changes must ship in a separate SDK build without changing 1.1 wire.

## Separate dev17 performance and public API follow-up

The later `matter-foundation==0.1.0.dev17` build leaves frozen 1.0/1.1 wires and
HostMonitoringState unchanged. Its source pin is `eb6f563a6ce064e76eea50e5f864cf0353c1bb01`; the
[SDK performance handoff](../validation/sdk-performance.md) records its full
wheel digest, 205-file inventory, unprofiled timings, final tests and public
`matter.attention.build_delivery_milestone_details` API.

For the dev16 freeze comparison, use merged commit
`35f330ae44657db46bc443aff6823a088501c693`: its 204 runtime files match `1f525c6`.
For dev17, compare the rebuilt image with the later source pin, not `1f525c6`;
the performance/API file differences are deliberate. The consumer owns its
image rebuild and dev17 receiving checks. Existing dev16 acceptance does not
imply those later checks have run. No deployment/activation or qualification is
introduced by either build.

## Later receiving and public API closeout

StateCivics' dev17 receiving check is now recorded in the [dev17 receipt](../validation/dev17-receiving.md); the earlier instruction to obtain that receipt is satisfied. Matter verified the exact image ID and all 205 runtime file hashes. SDK dev18 adds the public source-target classifier without changing either frozen wire or HostMonitoringState; its exact migration and package pins are in [MAT-087](../validation/MAT-087.md). Neither receiving acceptance nor this additive API releases production delivery or qualifies JEV.
