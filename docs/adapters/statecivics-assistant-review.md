# StateCivics slice 2: receiving the Matter assistant-review SDK

SDK package: `matter-foundation==0.1.0.dev19`. The runtime/wheel hashes and
actual checks are recorded in [MAT-088/089 validation](../validation/MAT-088-089.md).
The [1.0 review contract](../contracts/assistant-review.md) is additive; frozen
monitoring 1.0/1.1 and dev18 public helpers remain unchanged.

## Existing host entry point

Source inspected read-only at StateCivics
`f87d509c2ff2b132628f7c6e45c27f16559ad205`:
`src/kansas_accountability/services/assistant_review.py`,
`AssistantReviewService.review(*, user_id, intent_id, assessment_id, why, wake_key=...)`.
It supplies the assistant, own objective/lens session, read-only exposure,
proposal, labelled findings and context-change checks. It is not replaced by the
SDK. Review sessions/rows and recovery/deployment wiring stay StateCivics-owned.

## SDK entry points

```python
from matter.assistant_review import (
    AssistantReviewService as MatterReviews,
    ReviewHost, ReviewRequest, ReviewResult,
    host_artifact_reference, pressure_contribution, review_ledger_digest,
    pressure_ref, review_ref,
)
```

Construct MatterReviews over the **existing** Matter store/control/access
services. Install authenticated `ReviewHost` guards/readers over the actual host
projection. The guard gets the entire request, references and availability cut;
it must check the actual identity and native audience/provider/context binding,
not merely match an objective ID. No permissive default guards are shipped.

The host constructs canonical views of existing assessment/evidence,
`assistant_reviews`, review sessions, feedback, report/delivery and
`watch_intent_controls` records. IDs use strings at this wire boundary. Compute
view digests with the public helper; contributions also carry the actual stable
source material-version identity, shared by reprints and changed by a genuine
revision/reversion; do not substitute an ORM timestamp or a
model-supplied digest. No new client, memory or source database is needed.

The host ledger has four primary inputs (judgments, reviews, conveyed output,
feedback) plus derived findings. Matter persists the exact references, not the
view bodies. Preserve quote/judgment/interpretation distinctions and actual
communication states. KS-1125's host feedback is **not yet a native Matter
DispositionService control**; it can enter this ledger as host feedback, with
its actor and current/withdrawn status. No global suppression is implied.

## Async sequence around the existing service

```python
# Existing trusted host state provides these objects and authenticated guards.
request = ReviewRequest(canonical_request)
matter_reviews.record_pressure(
    request, token=original_token, access_context=original_access,
    command_id=stable_pressure_command,
)
acquired, attempt = matter_reviews.claim(
    request, token=original_token, access_context=original_access,
)
if acquired:
    # Outside Matter's write transaction. Exact typed host ID mapping only.
    host_result = await host_reviews.review(
        user_id=owned_user_id, intent_id=owned_intent_id,
        assessment_id=owned_assessment_id, why=rendered_internal_reason,
        wake_key=request.wake_id,  # 64 characters, within the host's 120-character bound
    )
    # Host receiving work: persist the wake/result binding and construct the
    # verified result from actual stored status, tool/evidence receipts and
    # host-approved controls. Do not infer reviewed=all_requested from success.
    completed = matter_reviews.complete(
        request, ReviewResult(canonical_verified_result),
        token=original_token, access_context=original_access,
    )
# acquired=False or a refusal NEVER calls host_reviews.review again.
```

The host adapter must enforce the request's real tool/time/read/byte limits
around existing execution. The SDK does not interrupt Python callbacks or make
an unenforced limit true. Follow the current owner-approved study cost policy;
this handoff does not reintroduce a per-user chat charge or a new spend ceiling.

Do not create a wrapper endpoint with a browser-supplied actor or a shortcut
around current host grants. Before linking a proposal, recheck current objective,
client/account/grants, original control history and source state inside the host
transaction. A pause followed by resume must not revive an old call. Matter and
Postgres do not form one distributed transaction.

## Receiving responsibilities and verification

StateCivics slice 2b now implements the narrow live-origin path below. Its
[retained receiving run](../validation/dev19-receiving.md) demonstrates two wakes
and prior-ledger reuse; reuse that implementation. These responsibilities still
apply, while broader KS-1126 and slice 2c remain open.

1. Reuse the actual canonical host views/guards and the claim/call/complete
   sequence around the existing review engine (KS-1150 slice 2b). Claim identity
   must survive restart. A host exception/crash may have reached the assistant:
   preserve unknown, do not automatically rerun it. The SDK keeps one active
   wake per lens; while one is unresolved, queue new contributions and rebuild
   the next request from pending material plus authorized ledger context after
   completion. Unknown-outcome reconciliation remains an explicit host workflow,
   not a new provider call or an implemented dashboard action in this SDK. The SDK provides an explicit
   correction-authorized `reconcile` method using a real host no-inflight witness;
   the lookup and operator interaction remain host work. This operator control
   works after native cancellation or revision without renewing assessment
   authority, clearing pressure or resuming monitoring. For a rotated operator
   or retired provider, use `history_context` with the current authenticated
   operator and read audience. This admits exact old pins for local READ under
   present grants; no retired provider egress grant or old worker identity is
   needed. Correction capability and active denials are still enforced.
2. Bind the returned review to this exact wake and actual reviewed source pins,
   session pointer and any already-authorized rule updates. Existing ReviewResult
   IDs alone do not prove the reviewed-set contract. Exact tool read/citation
   receipts are required; string citations must be mapped to actual versions.
3. Expose the authorized ledger and let subsequent existing packet construction
   call `resolve_ledger`. Keep all source/derivation labels and egress guards;
   derived notes cannot become independent source claims or qualification.
4. Carry the request availability cut into the existing exact readers during
   replay. The review service alone does not establish that cut.
   Reuse the no-login rehearsal isolation and refuse unsupported cuts.
5. KS-1126 receiving acceptance: `MONITORING_ASSISTANT_TOOLS_ENABLED` and
   `ASSISTANT_REVIEW_ENABLED` on in isolated rehearsal only, actual assistant turn and
   exact image/source/SDK identities, contrasting objectives, duplicate/reprint,
   quiet then new material, correction, in-flight pause/resume/revoke, new arrival
   during review, unknown recovery and foreign-client refusal. All output stays
   unsent; a proposal is not a report delivery or actual user read.

Slice 3 owns Report Studio cards and prepared report/notice mapping. County
meeting report `alert_deliveries` is the later claim-before-send pattern, not
hearing broadcast, and raw conversational replies are never notices. KS-1152
memory recovery and schema-pin deployment remain with StateCivics, not gates
that silently expand this SDK implementation.

## Portable authored vectors

```bash
python examples/assistant_review_vectors.py tests/fixtures/assistant-review/vectors.json
```

Six vectors cover the proposal vocabulary, unknown, dual-route identity and
contrasting lens identities. They are authored synthetic wire/identity checks,
not assistant execution, source interpretation, receiving acceptance or accuracy
measurements. SDK integration tests separately use real SQLite/control/access
with a synthetic host. A passing vector never qualifies JEV or enables delivery.

The host should select bounded ledger slices before dispatch, not append all
history to every request. Up to 96 request roots (within the selected read budget)
and a 128-version pending window are admitted; overflow is explicit backpressure
with upstream evidence retained. Completion verification has an independent SDK
256-artifact/1 MiB ceiling. Pressure is per matter; the objective session lock
spans matters and approved revisions. `pressure()` and `history()` return
present-authorized pointer metadata without rereading the whole body backlog.
They are not authorized source packets and must not be fed straight to a model;
resolving/reusing their pointers still checks current access, availability,
source integrity and input budgets. A consumed source version remains bound to
its original material digest after reset; contradictory content is refused.

Metadata reads and append/retry returns authorize all retained native selections,
including pending material inherited from older writes. Revoked history refuses
rather than returning the protected pointers under a narrower latest selection.
Keep unaccepted evidence in the existing host ledger; do not interpret a refusal
as quiet, delete pressure or renew the old work token to bypass it.

## Slice 2a receiving update

StateCivics `f87d509c2` adds per-account `assistant_reviews.wake_key`, bound to the
objective and assessment. Pass the exact Matter `request.wake_id`; do not create
a second retry key. The host returns `repeated=True` for an existing key and
refuses cross-objective/outcome reuse. This is a second idempotency guard, not
permission for a second assistant turn or a shortcut around current read guards.

`GET /tracking/intents/{intent_id}/reviews` is the host-owned review ledger view,
alongside `/outcomes` for judgments, conveyed output and feedback. It is private,
owner-only and place-granted. Use these existing owners, retaining canonical
version/citation/availability projections and exact actual read receipts. The
list/row IDs alone do not supply every digest/binding in Matter's contract.

A running or interrupted/transport-uncertain host attempt maps to SDK unknown,
never quiet. A lease-expiry `failed/interrupted` label by itself is not proof
that no process or provider call remains in flight. Use actual host lookup/proof
for reconciliation. Definite stopped/failed completion also never clears pressure.
Host `repeated` reads must still pass present grants and original-control checks.

The owner reports slice-2a software checks; Matter inspected these entry points
read-only. Matter has not run its assistant, migrated the shared rehearsal store,
changed its image/flags or independently reproduced those host test counts.
The real, unsent KS-1126 turn remains the receiving acceptance step.

Pressure `command_id` is a persisted native registration-attempt ID, distinct
from the stable semantic `wake_id`/host `wake_key`. After a known recorded
backpressure refusal, draining the window permits a fresh local registration ID
for the bounded batch; an exact retry preserves its immutable refusal. Keep the
same semantic wake and never renew IDs to bypass an unknown assistant outcome.

Project actual deterministic host-rule outcomes as judgment-kind
`host_rule_judgment`, with their real rule/version and original citations.
Project JEV answers as `jev_judgment` with their actual unqualified/qualified
status. The adapter accepts both for review; do not relabel a host rule as model
interpretation or promote either to a source fact or delivery permission.

## Receiving status after slice 2b

StateCivics main `f1e6cb4256486aa57ff1ec6cb5c4f7c3183653f0` contains the wired
adapter and receiving fixes. Run 5 provides narrow live-origin assistant-review
receiving evidence. The full UI/API/timeline contrasts of KS-1126, accumulation,
operator reconciliation and production activation are separate; see the
[receiving receipt](../validation/dev19-receiving.md). Matter made no new assistant/JEV application
calls or shared-stack changes to inspect those records.
