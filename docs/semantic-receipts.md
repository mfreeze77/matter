# Semantic execution receipts and exact reuse

`matter.semantic.receipts.ExecutionReceiptStore` stores existing core `receipt`
records with evaluator origin. The additive `record_semantic_execution` operation
returns the stored execution pin and its actual operation receipt. It needs no
assessment placeholder, provider client or new record kind. A model answer,
normalization result or classifier never acquires source authority.

Install the scoped storage, existing payload store, ControlService, host clock
and QuestionRegistry; optional AccessService and BudgetService ports retain their
existing meanings. Raw storage/artifact handles remain privileged host machinery.
The recorder checks actual source pins and present READ rights, including
the complete bounded source closure of actual parent execution receipts. The
consumer’s own original token/access context must cover that closure; a parent’s
authority cannot substitute for the consumer’s rights. Installed access
policy requires the original context, same work token, exact source closure,
audience and provider/transport. Protected packets fail closed without that port.

## Request and execution

`request(batch, packet=..., rendered_questions=..., token=..., precision=...,
model_binding=..., access_context=..., stage=...)` binds the frozen packet/audit,
ordered executable questions and rendering manifests, trusted precision profile,
requested model/adapter and explicit stage meaning. Specifications and renderings
are reconstructed against the installed registry. The packet producer and source
selection remain trusted host inputs; recording does not prove their truth.
`model_binding={model, resolution}` is the host's current concrete-model/resolver
declaration. Missing resolution disables reuse; an old resolved-model guess never
fills it. The observed model must agree before an entry is cached.

`run(request, executor=..., token=..., logical_request_id=..., attempt_id=...,
allocation=..., parents=..., retry_of=..., dispatch=..., qualify=...)` handles
one physical attempt. It atomically records a started receipt before injected
I/O, then records completed or outcome-unknown observation. The exact committed
allocation and original work token are checked before dispatch. Calls, request
and response ceilings, retry capacity and conservative elapsed ceilings decrease
across claimed attempts; no committed or uncertain capacity is refunded. The
actual dispatch deadline is clipped to remaining elapsed capacity and allocation
expiry. `requested_deadline` preserves the submitted bound for idempotency;
recovery compares the original submission, without extending the claimed deadline.
A host can select shorter per-attempt deadlines to divide one allocation.

Only offline fixture/recorded replay use the default dispatch path. Protected or
provider-shadow execution needs an explicitly injected guarded dispatcher; the
caller can wrap actual AccessService.dispatch using its fresh-read factory and
original rendered questions. No database read transaction spans external I/O.
A synchronous injected adapter remains cooperative; no Python preemption or
exactly-once remote delivery is promised. Adapter timing/usage counters are
observations, separate from conservative reservations.

Retries require a new attempt ID, the same logical ID and an actual `retry_of`
receipt. There is no automatic retry loop. An interrupted started attempt remains
unknown and is never automatically resent. Retrying its original command returns
historical evidence. A fresh host assignment is required when original controls,
source targets or allocated capacity are no longer usable.

`record(...)` records a truthful already-observed result without pretending it
was claimed before I/O. `record_stage_batch(run,index,...,parent_executions=...)`
consumes actual MAT-029 StageRun requests, including a null result after an opaque
boundary failure. Each uncommitted parent trace must map explicitly to a real
stored execution receipt. Request stage metadata is `{plan,members}`, with each
member retaining its stage ID, transform identity and original parent traces.
Actual receipt parents are distinct core provenance pins.

## Original artifacts and replay

Neutral response bytes and optional native vendor bytes are separate immutable,
content-addressed artifacts in the existing scoped payload store, outside Git.
Receipts retain their digest, length and availability references; they omit inline
base64 payloads. Native and neutral artifacts can differ without losing either.
Back up the payload store with SQLite. Missing/corrupt artifacts fail closed and
never trigger a provider call to reconstruct evidence.

`read(pin)` returns an actual immutable core receipt; `replay(pin)` restores the
original BatchResult and validates admission again against the exact original
wire, rubric and trusted precision. Whole-batch failure remains failure even if
some diagnostic heads are valid. A timeout with parseable bytes remains a timeout.
A float-only result cannot manufacture exact admission. `normalized_digest`
hashes canonical execution status, precision, model, diagnostics, faults and
admission separately from wire evidence/timing. Equivalent decimal spellings
share normalized identity; exact wire digests remain distinct.

RawExecution accepts optional immutable `native_response` bytes and
`ExecutionInstrumentation`. Recognized ExecutionFault carries safe closed failure
codes, optional native bytes and instrumentation even for timeout/rate limiting.
`precision_unavailable` explicitly makes exact numeric admission false;
`model_unresolved` retains native diagnostics without guessing a model. Exception
traceback/context metadata remains compatible with Python context managers.
Absent bytes, token counts and prices are null with reasons. No headers,
credentials, arbitrary exception text, SDK client or pricing service are recorded.

## Exact reuse and current qualification

`lookup(request, token=..., parents=..., access_context=..., qualify=...)` checks
current source/control/access eligibility and reruns an installed classifier on
every lookup. Keys include ordered questions/criteria/rendering, packet and declared audit dependencies, adapter,
requested/concrete model binding, precision, stage plan/transforms, actual stored
parents and original semantic control generation. Logical run/attempt IDs and
captured-at timestamps are omitted. Correlation question IDs remain exact;
answers are never automatically renamed. Full protected packet/context identity
can conservatively prevent reuse across equivalent recaptures.

The classifier receives `(view,execution,request,as_of)` as keyword arguments and
returns `{status,certificate}`. It must inspect actual current certificate and
revocation state through the supplied view. `run` repeats it during reuse
preparation and the atomic writer, retaining its declared reads. A revoked,
expired, unknown or mismatched classification cannot qualify a reuse. Without a
classifier only unqualified raw computation is reused. Every BatchResult remains
unknown for semantic qualification and false for consequential use; MAT-031 owns
independent current classification at consumption, not this receipt store.

A reuse observation points to the original immutable execution receipt and its
same raw result. It adds no provider invocation, source occurrence or independent
corroboration. `history(logical_id,attempt_id)` and `attempt(idempotency_key)` expose
original observations and durable refused operation journals under present READ
and historical access grants. Ordinary source revisions/cancellation do not erase
inspectable history; revoked READ/grants still deny it. An idempotent historical
result is not a fresh qualification decision.

Optimistic races can conservatively refuse an attempt or concurrent cache fill
with `E_DEPENDENCY_STALE`; no handler reads undeclared newly published rows to
silently change its decision. Refused completion journals retain exact artifacts
and diagnostic inputs while the started observation stays outcome-unknown. A
new attempt captures the new state. No source fetch, scheduler, provider transport,
qualification issuance or action capability is introduced here.

Original result timing is historical: a reuse return retains its original
`timing.called` and batch digest. Count new physical work from the explicit
`dispatched` flag and observation phase, not from the original result's timing.

## Composing durable dispatch with staged execution

A StageExecutor dispatcher can construct the exact receipt request from its
supplied current Batch/rendered questions and the matching prepared packet,
call `receipts.run(...)` with the actual committed allocation and original token,
then return `receipts.view_result(outcome,batch)`. The protected path additionally
supplies the actual AccessService guard to `run`; a no-op callback does not
establish egress permission.

`view_result` validates the same packet, ordered question definitions and
provider/model/adapter assumptions, rechecks current transitive parent/source
eligibility, and uses the existing normalizer for current byte admission. It
returns a detached BatchResult bound to this caller's batch digest, with explicit
`execution_observation` pins to the durable event/original execution. Reuse has
`timing.called=False`, null current usage/cost and no new trial. Original failures
and uncertainty remain invalid. An expired current deadline bars consumption.
The immutable stored receipt and original result are unchanged. This derived
view is for stage consumption; it is not accepted as another physical execution
observation by the recorder. Choose the predispatch `run` path or the explicit
post-I/O stage observer according to the actual host execution path.

Recovering an existing logical/attempt ID requires the same original control token,
access context, normalized actual parent pins, allocation and retry lineage, as
well as the original submitted request. Another caller/context is refused before
returning historical data; work-lineage changes conflict with idempotency.
Unchanged original context can still inspect authorized historical evidence after
cancellation, without dispatch or fresh qualification. A requested retry satisfied
by cache preserves `retry_of` alongside `source_execution` in its reuse observation.

Reuse command identities include both logical request and physical attempt IDs,
so separate logical requests can each use attempt `1`. A guarded dispatcher is
required before claiming new protected/provider-shadow I/O; a missing dispatcher
creates no started observation or cap reservation. Authorized exact history and
cache reads remain available without a dispatcher because they perform no I/O.
The attempt journal admits only its five nonnegative integer counter keys and
known phases; started/completed/unknown phases require all five counters, while
observed/reused records may carry an empty cap object.
