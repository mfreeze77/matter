# Evidence-backed lifecycle

MAT-017 implements versioned domain transitions over the existing storage,
claim, occurrence, assessment and control ports. A matter keeps its identity;
its per-condition lifecycle projection records what the installed profile's
current evidence establishes. Acknowledgement and attention are separate.

## Install an explicit policy

Install `lifecycle_schema()` in the host's `SchemaRegistry`, then construct a
`LifecycleDefinition(value, schemas=schemas)`. Add its exact `extension` to the
`lifecycle_extensions` of a `ProfileDefinition`'s lifecycle component. The
component declares the actual allowed data scope. Its dependencies can name
the evidence component without copying or rerunning its rules.

A definition contains an exact namespace, identity, semantic version,
description, named states with roles (`open`, `resolved`, `unknown`,
`withdrawn`), an unknown initial state, and explicit edges. Each edge declares:

- Its identity/version, permitted source states, target state and trigger.
- An installed claim schema, predicate, JSON Pointers selecting the complete
  condition and signal, and accepted signal values.
- Accepted assessed-proposition and evaluation states, admitted claim/source
  origins, and whether an applicable host decision is required.
- The effective-time rule (`claim_start`) and whether past effectiveness is
  admitted.

Pointers are data selectors, with RFC 6901 escaping. They execute no code.
The selected condition can include circumstances such as an operation's exact
scope; matching a topical name alone supplies no implied correspondence.
Origin selectors use the actual core vocabulary, including `evaluator`.
Admitting evaluator evidence still supplies no host authority or capability.
Changing any declaration changes its definition and edge fingerprints.
`definition.edge_reference(edge_id)` returns the exact request selector.
Duplicate state or edge identities, undeclared states, unavailable schemas and
contradictory retraction semantics are refused during installation. The
definition and its returned JSON values are detached and immutable.

## Prepare and apply

Construct `LifecycleService` with the actual scoped storage, profile/schema
registries, installed definitions, `ClaimService`, `OccurrenceService`,
`AssessmentService`, `ControlService` and trusted clock. It uses the same
control service as assessment consumption.

The existing `request_transition` operation body supplies the exact matter
revision, logical lifecycle revision, edge, evidence pins, current assessment
pin and proposed effective time. Then prepare once:

```python
prepared = lifecycle.prepare(
    command,
    profile=profile.reference,
    condition={"key": "synthetic-operation", "circumstance": "required"},
    claim=pin(qualifying_claim),
    occurrence=pin(accepted_occurrence),
    token=original_transition_token,
)
result = lifecycle.transition(prepared)
```

The host captures `original_transition_token` before preparation, for capability
`transition` and every public target that the complete decision will read.
Preparation discovers and retains the exact read set; it never expands or
recaptures that token. A narrow token which covers the request body but omits a
source, assessment judgment or claim-correction dependency is refused. A
different same-epoch capability or target token does not renew the request.

The first unseen condition has logical lifecycle revision 1 and unknown state.
Its first applied edge writes storage projection revision 1 with logical
lifecycle revision 2. These counters describe different histories. Callers
subsequently use the logical revision from the projection; they do not infer it
from a matter or storage revision.

Preparation validates the accepted subject identity, exact installed edge,
current assessment and original controls. It uses
`AssessmentService.read_current` within the same caller snapshot or transaction,
including assessment registration, qualification and freshness guards. The
claim must be a current, unbranched correction head, concern that exact subject
and typed compound condition, and have exactly one qualifying assessed
proposition under the profile's exact evidence component. Both claim and
occurrence must be declared semantic assessment dependencies. Actual occurrence
membership is checked through `OccurrenceService`; an arbitrary record with a
matching shape is insufficient. At least one attributed claim source must be
an admitted observation of that occurrence.

Ordinary establishment, resolution and recurrence require a complete supported
assessment. Missing correspondence is `held_for_evidence`; conflicting state
or proposition is `held_for_conflict`. Undeclared edges or absent authority are
explicit failures. A model's confidence never supplies a host capability.

`transition` reruns these checks under the storage write lock against the
original read pins, prior lifecycle state, registration generation, clock and
control token. It writes an immutable operation-stage receipt with typed
`lifecycle-transition` details, the `matter.lifecycle` state projection, an
occurrence deduplication slot and dependency registration in one transaction.
Install the existing `InvalidationHook` on every participating store handle to
invalidate registered attention or queued host derivatives in that same commit.
This ticket implements the registration seam; it sends no advice or message.

The receipt retains the exact original publication proof copied from that
selected lane. The lifecycle's semantic dependencies include the admitted
assessment and its actual sources, rather than the replaceable current-lane
pointer. Reassessing equivalent evidence in the same lane therefore does not
change an already established domain fact or its logical lifecycle revision.

An exact command retry returns its durable journal result. A fresh command
for precisely the same currently valid basis and edge returns
`already_applied` without a new transition. Different evidence, effectivity or
control state still requires admission. Semantic refusal never changes the
lifecycle state. A failed receipt/registration write rolls back all domain
changes.

## Resolution, recurrence and correction

A matching supported success can resolve an open condition automatically.
Neither an acknowledgement nor a missing user closeout receipt prevents an
ordinary automatic edge.

Each applied occurrence is retained in a stable per-condition deduplication
slot. Redelivering an original event, or merely reassessing it today, does not
reopen a resolved condition. A recurrence edge requires a distinct accepted
occurrence with a known happening time later than the prior basis occurrence,
and an effective time at or after the previous condition transition. A new ID
for an older happening does not pass this guard.
Routine revision of the prior occurrence's membership does not permanently
block recurrence. The service reads its current accepted grouping, retains that
revision in the transaction read set, and compares its happening time against
the original snapshot retained in the transition proof. A changed happening
time requires explicit correction rather than a guessed chronology.

A retraction edge must explicitly leave a resolved state for unknown or open,
accept an `unknown` assessed proposition, and select a new claim which
supersedes the corresponding prior basis. An unrelated retraction is held;
`refuted` is not substituted for `unknown`. A correction edge likewise requires
a corresponding superseding claim; its declared evidence standard controls the
new state. Old claims, assessments and transition receipts remain inspectable.

An edge with `requires_decision` additionally requires an actual active
`decision` control with typed `disposition` effect, present in the original
token's active controls. The host installs `decision_validator(view, control,
profile=..., edge=..., matter=..., condition=...)` to validate that decision's
exact domain payload and scope. Only literal `True` admits it; missing,
failed or negative validation refuses the transition. The validator is trusted
host code. It cannot replace evidence, assessment, control or scope guards.
This seam can adapt a MAT-018 disposition without coupling the core to its
domain meaning. An acknowledgement cannot satisfy it.

## Effective time, knowledge and reads

An edge explicitly uses the claim applicability interval's known closed start
as its effective time. The interval must contain that instant; the request
must supply the exact same value. The occurrence timestamp is not silently
promoted into proposition effectivity. Future effectivity is held, and source
availability must be known and no later than the assessment's knowledge cut.
When `allow_past_effective` is false, effectivity cannot precede that fixed
assessment knowledge cut. It need not equal two changing preparation/commit
clock readings. The exact claim-start equality and no-future-effectivity guard
still apply.
A late-discovered recovery can therefore be effective yesterday while its
receipt records today's actual commit knowledge time. Clock regression between
preparation and commit is refused.

`current(matter, profile=..., condition=...)` returns the actual current
projection, or `None` for an unseen condition. It checks registered transitive
freshness, the originally admitted assessment and the current claim correction
head. The original publication's source, qualification, time, context and
control guards are rerun at the actual read time. An expired original
certificate, corrected source, changed negative watch or revoked original
control stays stale even if a new assessment or certificate exists. Selecting a
new current assessment lane alone does not invalidate the domain state. New
transitions still require the selected current assessment.

Stale state is a failure rather than a resolved answer. `read_current(view,
matter, *, profile, condition, ...)` performs the same guards through a caller's
consistent view and opens no fallback snapshot. Callers retain all discovered
reads when committing a dependent operation. `state_role(profile, state)`
interprets a state only through that exact installed definition.

`history(..., knowledge_at=..., effective_at=...)` returns immutable transition
receipts in commitment order. A knowledge cut excludes subsequently learned
resolution or correction; an effective cut filters declared effectivity.
Historical receipts are not rewritten and do not assert present validity.
Only the selected exact profile's receipts are returned. No automatic version
migration or certificate transfer is performed.

Retained publication proofs count against the existing 8-MiB unique-record read
budget and 4,096-record limit, including history traversal. A large history is
refused explicitly when that budget is exceeded; it is not silently truncated.

Reads audit present host read permission. A caller may supply an original
`read_token` to current/history, including an enclosing operation's original
assessment work token. Its captured capability and scope are checked unchanged,
and the caller's actor/authority separately needs present READ permission over
the actual proof and discovered public read closure. The service never converts
or recaptures a work token. Raw storage and service handles remain trusted host
machinery. With an installed MAT-072 access boundary, transition
preparation additionally requires an `access_context` bound to the original
transition token. Current/history additionally require the original read token
and matching read access context. Missing contexts fail closed. Stored original
assessment access guards are retained and rechecked during consumption.

## Evidence and limits

The [MAT-017 validation receipt](validation/MAT-017.md) records actual synthetic
SQLite checks. They cover corresponding and unrelated success, genuine versus
old recurrence, unknown retraction, past-effective knowledge, original target
coverage, cancellation races, authority refusal, idempotency, atomic rollback
and transitive queue invalidation. They do not measure a provider's accuracy,
domain-specific legal authority or live attention usefulness. Runtime scheduling,
attention policy, transports and full corpus replay remain separately scoped
roadmap work.
