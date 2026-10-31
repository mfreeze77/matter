# Pinned StateCivics SDK handoff

Matter-side verification, 2026-10-30. These are **unmerged source candidates**,
not a deployed SDK image, receiving acceptance or provider qualification. The
owner has not authorized merging this stack. StateCivics owns its checkout,
ticket reconciliation, image build and host wiring.

## Source order and two different package gates

The reviewed stack is linear, with no GitHub-reported merge conflict:

1. #26, civic source adapter: `9cf444a86c238dc135736f7a8b6dfe7e062c2e2c`,
   based on main `b5dfc2789286e3efb960e7551b38df4b3d965757`.
2. #27, integration plan: `85284851f21b13f4eb3117dd67efb0441f807fe7`,
   based on #26.
3. #28, frozen MAT-081 contract: `f95a57e04848626237ab162ed98f8d4d25fe0b4d`,
   based on #27.
4. #29, MAT-082 adapter: initially reviewed at
   `284047ad0989cc2903883a285c345aa2ae2405ba`, based on #28. The final runtime
   candidate is `59bfed9680f60f98d4a6e4cfd16d6569c1b516c7`, including the two
   review corrections. Subsequent documentation closeout does not change that
   candidate's packaged runtime bytes.

**KS-1121's minimum gate is merged #26 and an image containing that package.**
It does not require the saved-objective runtime to start its separate study.
**KS-1124 and KS-1126 require #29 and its prerequisites in their SDK image**,
plus the host's actual controls, capture mapping and KS-1121 integration.
They cannot use the #26-only wheel as a saved-objective SDK.

Both candidates call themselves `matter-foundation==0.1.0.dev15`; pin the source
commit and SHA-256, not the shared filename/version. The exact candidate
manifest is [statecivics-sdk-candidates.json](statecivics-sdk-candidates.json).
Wheels and detailed inventories are retained locally in the gitignored
`data/validation/sdk-handoff-20261030/` directory:

- `wheels/ks1121/matter_foundation-0.1.0.dev15-py3-none-any.whl`:
  SHA-256 `20c317c6a45a372adcfbe3078e8eaf3601fc71648f0c79da95b78b05cdbeff46`;
  531,463 bytes; 200 packaged runtime/SQL/schema files.
- `wheels/saved-objectives-handoff/matter_foundation-0.1.0.dev15-py3-none-any.whl`:
  SHA-256 `13f6b3156bb33664300597aaa533a71764a700bda3a810d8a569989809b4ca37`;
  546,565 bytes; 202 packaged runtime/SQL/schema files. The earlier baseline
  wheel from `284047a` is retained for its test receipts and is superseded.

Every packaged runtime file byte-matches the named immutable Git commit.
The wheel contains only the package and distribution metadata: no credentials,
real evidence corpus, database or private client data. After an authorized
merge, record the **actual merged source commit** and image digest on the host;
do not label these branch candidates as merged releases. A changed build backend,
source metadata or archive timestamp can change the wheel digest: rebuild and
record the new digest, then compare the source-file inventory and rerun the
installed checks. Do not expect a version string to prove equivalence.

## Required imports and frozen boundary

The #26 package provides:

- `matter.civic_exports`: `PreparedCivicExport`, `CivicImportService`,
  `prepare_export`, `citation_text`; export version `matter.civic-export/1.0`.
- `matter.civic_attention`: `source_questions`, `project_source` (four
  source-only questions).

The #29 package additionally provides `matter.statecivics_monitoring`:
`HostMonitoringState`, `MonitoringHost`, `AdmittedMonitoring`,
`validate_handoff`, `monitoring_questions`, `monitoring_refusal`.
The two monitoring questions have distinct, unqualified civic identities.
They do not inherit qualification from MAT-034 or earlier JEV calls.

The wire version is `monitoring-handoff/1.0.0`, governed by the
[specification](../contracts/monitoring-handoff.md) and
[Decision 0002](../decisions/0002-monitoring-handoff.md).
Portable and installed schema SHA-256 is
`3defba5be4fc88627086b18488ce7f0e4494b139734c5e824f2a8bb9fa7d3a0b`.
The [contract lock](../../tests/fixtures/civic/handoff/contract-lock.json)
SHA-256 is `ffe1dc889b50dec3a7efb07e4796ee62e194569be826e8f53b303f96203f1fa7`;
all 60 locked artifacts were rechecked. Its examples, including the 16 invented
users, are compatibility illustrations, not independent evaluation labels.

The owner-approved capture gate requires **both a real owned watchlist and
item**, with actual factual/user activity associations, before evaluation.
Neither a wire assertion nor one foreign key grants access. Broad objectives
retain their own identity and receive actual authorized candidate records;
they must not masquerade as synthetic bills.

## Host configuration and execution obligations

Use the existing [adapter setup and flow](statecivics-monitoring.md), rather
than building another client, permission engine, queue or rehearsal stack:

1. Construct the trusted `MonitoringHost` server-side with the authenticated
   user/workspace/optional-client/one-place binding, real AccessService and
   AccessContext, current read factory/state resolver, clock and AttentionService.
   The host verifies current approval, lifecycle, capture ownership/mute and
   actual record relationships. Request JSON cannot supply its own access grants.
2. Resolve immutable approved intent and five consumed context components,
   current candidate, source finding, exact packet/source cut, dispositions and
   observed output baseline. Pass actual budget/price reservations, not guessed
   cost values. Unresolved prior outcomes remain unknown. Use the existing
   registered profile/rules/admission/assessment pipeline for real decisions.
   Authorize the historical records needed to verify declared source-correction
   ancestry; unrelated readable records are not correction links. Denied or
   unavailable history withholds rather than guessing a relationship.
3. Share authorized source-only findings. Only allowlisted approved intent and
   verified prior material enter audience context. Keep contact details, unrelated
   client notes and credentials outside the boundary. Preference-only reuse may
   use the documented separate semantic/output access contexts; both retain
   current real guards. Source cutoff and reconstructed intent time are separate;
   replay never imports future-available source evidence or claims past preferences.
4. Explicitly select `TypeSafeHTTPExecutor(model=..., timeout=..., max_calls=...,
   max_retries=0, ...)` if using JEV. Its fixed endpoint is
   `https://api.typesafe.ai/v1/systemone`; adapter identity is
   `matter-typesafe-http/1.0`, provider `typesafe`, transport `http`, mode
   `provider_shadow`. The host supplies `TYPESAFE_API_KEY` through server-side
   secret loading or an explicit `api_key`; **the transport does not load `.env`**.
   Never place that value in handoff JSON, logs, commits or browser state.
5. Pin the model and question identities in the Batch. The frozen envelope
   bounds calls to 1–64, timeout to 1–120 seconds, wall time to 1–3,600 seconds,
   request/response bytes to 1–65,536, with a positive reserved USD ceiling and
   verified price-basis pin. These maxima are not a spend authorization; use the
   host-approved lower limits and native committed BudgetService allocation.
   Preserve the exact original token/allocation and Batch/deadline for recovery;
   do not renew cancelled or unresolved attempts into automatic resends.
6. Use the actual ExecutionReceiptStore and pre/post-I/O access gates. Persist
   actual assessment dependencies, then project the current AttentionService
   decision. Withhold obsolete results after relevant edits/revocation. A partial
   source scope or failed provider call is not confident irrelevance.
7. Send capture-only proposals to the existing isolated in-app sink. That sink
   must recheck the supplied guard within its own authorized atomic write and
   enforce the material/audience/objective key. Silence does not invoke the sink.
   Record observed capture separately from delivery, reading or action. An opaque
   or partial write remains unknown; no fabricated receipt or automatic resend.

## Reproducing the package checks

The candidates were built with Python 3.12.14, pip 25.0.1, setuptools 84.2.1 and
wheel 0.46.3, from `git archive` of `pyproject.toml README.md LICENSE src schemas`.
Set `SOURCE_DATE_EPOCH` to the selected commit's `%ct`, then run the existing
environment's `python -m pip wheel SOURCE --no-deps --no-build-isolation
--no-index -w WHEEL_DIR`. Runtime dependencies are `jsonschema>=4.23,<5` and
`referencing>=0.35,<1`; the check environment used 4.26.0 and 0.37.0 respectively.
Install the selected wheel into an empty target with `pip install --no-index
--no-deps --target TARGET WHEEL` and supply those dependencies from the host's
locked environment.

Run imports and default-schema civic `matter.demo.run_fixture` outside the
checkout, with no `schemas/` directory and installed package first. Remove the
Matter editable-install meta finder as well as using isolated Python: `-I`
alone does not remove editable `.pth` hooks. Assert all imported `matter` modules
come from the installed target. The retained smoke scripts and test harness
enforced network denial and checked these import origins. See the
[validation receipt](../validation/dashboard-matter-handoff.md) for actual test
results, review coverage, CI failures and evidence boundaries.

The earlier installed walkthrough-schema failure was repaired before this
stack; fresh checks of both candidates confirm the bundled civic schema works.
This is a verified status correction, **no new packaging fix**. The repository
CLI's explicit checkout/`--root` requirement remains documented scaffold scope.
Broader MAT-077 distribution work and the unresolved SQLite race are separate.

## Receiving acceptance still belongs to StateCivics

This SDK does not implement the host gaps recorded in the pinned contract
baseline: real host-backed `access_context`, draft/pause/revoke lifecycle, broad
objective scope beyond the record-plus-one-place API, actual owned watchlist/item
and activity associations, or the production assessment seam that deliberately
returned 503. StateCivics may advance these independently; this closeout did not
re-inspect or modify that checkout, and does not assert those gaps still match
its newest main. Its receiving receipts must identify its actual source/image.

KS-701 acceptance precedes KS-1122 acceptance; KS-1122 need not wait on KS-1121.
KS-1123 supplies activation UX; KS-1124 maps real dispatch and capture;
KS-1125 maps explanations/feedback before KS-1126's two saved-objective rehearsal.
Use the existing no-login rehearsal/fast-forward and isolated capture sink.
KS-1127 subsequently shadows incoming live events through the same boundary.

The pilot place/workspace/two objectives and dashboard activation/pause/reactivate/
undo interactions remain host/owner choices. This handoff does not approve them.
MAT-081/082 tests use authored recorded answers; prior KS-1121 live calls do not
prove this saved-objective path. Host receiving evidence, new live interpretations,
independent held-out labels/MAT-040 qualification and production alert authority
remain distinct milestones. No StateCivics implementation or image was changed.
