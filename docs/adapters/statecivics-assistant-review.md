# StateCivics slice 2: receiving the Matter assistant-review SDK

Candidate package: `matter-foundation==0.1.0.dev19`. The runtime/wheel hashes and
actual checks are recorded in [MAT-088/089 validation](../validation/MAT-088-089.md).
The [1.0 review contract](../contracts/assistant-review.md) is additive; frozen
monitoring 1.0/1.1 and dev18 public helpers remain unchanged.

## Existing host entry point

Source inspected read-only at StateCivics
`b87c6027f4e85cd77d4a8d0e2d65e151caf1ac5f`:
`src/kansas_accountability/services/assistant_review.py`,
`AssistantReviewService.review(user_id, intent_id, assessment_id, why)`.
It supplies the assistant, own objective/lens session, read-only exposure,
proposal, labelled findings and context-change checks. It is not replaced by the
SDK. Review sessions/rows and recovery/deployment wiring stay StateCivics-owned.

## SDK entry points

```python
from matter.assistant_review import (
    AssistantReviewService as MatterReviews,
    ReviewHost, ReviewRequest, ReviewResult,
    host_artifact_reference, pressure_contribution,
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
view digests with the public helper; do not substitute an ORM timestamp or a
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

## What remains on the StateCivics side

1. Build the actual canonical host views/guards and wire this claim/call/complete
   sequence around the existing review engine (KS-1150 slice 2). Claim identity
   must survive restart. A host exception/crash may have reached the assistant:
   preserve unknown, do not automatically rerun it. The SDK keeps one active
   wake per lens; while one is unresolved, queue new contributions and rebuild
   the next request from pending material plus authorized ledger context after
   completion. Unknown-outcome reconciliation remains an explicit host workflow,
   not a new provider call or an implemented dashboard action in this SDK.
2. Bind the returned review to this exact wake and actual reviewed source pins,
   session pointer and any already-authorized rule updates. Existing ReviewResult
   IDs alone do not prove the reviewed-set contract. Exact tool read/citation
   receipts are required; string citations must be mapped to actual versions.
3. Expose the authorized ledger and let subsequent existing packet construction
   call `resolve_ledger`. Keep all source/derivation labels and egress guards;
   derived notes cannot become independent source claims or qualification.
4. Carry the request availability cut into the existing exact readers during
   replay. The four-argument review service alone does not establish that cut.
   Reuse the no-login rehearsal isolation and refuse unsupported cuts.
5. KS-1126 receiving acceptance: both host flags on, actual assistant turn and
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
