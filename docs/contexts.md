# Independent contexts and scoped dispositions

MAT-018 implements versioned context components and explicit host dispositions.
A context describes a purpose, objective, audience, responsibility or preference.
It does not change the source evidence, establish a global importance score,
grant an actor a capability, or send a message. Contexts remain independent of
domain lifecycle and of the later attention policy.

## Define and persist a context

`ContextDefinition(value)` accepts an exact immutable definition with:

- `schema_version: "1.0"`, a host `namespace`, `id`, `semantic_version`, `kind`
  and `description`;
- explicit public `applies_to` entity references;
- a half-open `effective_from`/`effective_until` interval. An unknown end must
  explicitly mean `not_applicable` (no automatic expiry);
- strict content for its kind: purpose objective/constraint references,
  objective statements/constraints, audience identity/kind and explicit linked
  components, responsibility owner/capabilities/purposes, or delivery preference,
  channels and a typed interruption-budget declaration.

`definition.reference` is an exact component reference. Purpose, objective,
audience, responsibility and preference versions are separate definitions;
changing a preference does not mutate an audience or an evidence interpretation.
Linked component references are data and are never silently hydrated as latest.
Responsibility names a scoped owner; its capabilities describe the responsibility
and never expand the host authority policy.

```python
from matter.contexts import ContextDefinition, ContextService, context_ref

contexts = ContextService(store, controls=controls)
definition = ContextDefinition({
    "schema_version": "1.0", "namespace": "example:contexts",
    "id": "monitoring-purpose", "semantic_version": "1.0", "kind": "purpose",
    "description": "Follow the explicitly scoped objective.",
    "applies_to": [matter_reference],
    "effective_from": host_clock(),
    "effective_until": {"state": "unknown", "reason": "not_applicable"},
    "content": {"objectives": [], "constraints": []},
})
command = contexts.prepare(
    definition, command_id="purpose-1", idempotency_key="purpose-1",
    actor=authenticated_actor, authority=host_authority,
)
result = contexts.commit(command)
```

Prepare once, retain the returned command, and retry it exactly. An update must
pass `previous=exact_current_pointer_pin`. Its new host control explicitly
supersedes the pointer's prior governing control. Concurrent stale updates
refuse; they never publish a new current context and repair it later.

The implementation uses the existing `record_control` transaction, an immutable
version projection and one public current pointer. A changed definition cannot
reuse its existing semantic version, even after another version became current.
Re-selecting an already stored exact version retains that version's original
bytes and provenance. Every old pointer, version and control remains readable.
No new core command, storage backend, directory or query index is introduced.

## Consume only the components a computation uses

```python
selection = contexts.capture(
    original_read_token,
    [context_ref(store.scope_id, definition)],
)
component = selection.value["components"][0]
assert component["reference"] == definition.reference
# Bind the exact components and these pins to the actual consuming computation:
context_dependencies = selection.dependencies
interval_guards = selection.time_conditions
```

Capture reads only explicit selected public context slots. Its detached values
include exact current pointer/version pins, definition/reference, governing
control and current interval applicability. It refuses a historical pointer
passed as current. `read(token, exact_reference, at=...)` separately supports
historical bindings. The optional data time changes interval interpretation;
current host READ authorization still uses the actual host clock.

Intervals preserve nanoseconds. An inactive future context exposes its start
as its next reconsideration; an active expiring context exposes its end. An
expired objective is not evidence that the matter was repaired or resolved.

Pass `selection.dependencies` to the actual assessment's declared semantic
inputs (for example, `AssessmentService.prepare(..., extra_dependencies=...)`)
and its exact purpose/audience component selectors. A rule's packet should name
only components that affect that rule. Declared temporal conditions also belong
in its actual temporal input. General dependency capture/registration accepts
the selection's pins and interval guards for host projections.

An evidence-only judgment can therefore remain audience-independent. Different
consequence/attention consumers may reference the same stored evidence
assessment and independently consume human preferences or working-agent
responsibilities. Changing one selected preference invalidates its consumers;
it does not reclassify unchanged facts or invalidate an unrelated audience.
This module does not itself decide attention treatment; MAT-019 owns that policy.

## Record an exact disposition

`DispositionDefinition(value)` names `kind` (`acknowledgement`, `deferral`,
`rejection` or `decision`), host namespace, matter identity, exact purpose and
audience links, exact `subject` pin, effective interval, reason, `status`
(`active` or explicitly `withdrawn`) and `decision`.

Each purpose/audience link is `{reference: component_reference,
context: exact_public_context_pointer_pin}`. At prepare/commit the service checks
the actual persisted kind, exact component reference, current pointer and active
interval. A disposition cannot silently cross to another audience or purpose
version. The public slot address binds kind, matter, both exact context links,
and the exact subject snapshot.

```python
from matter.dispositions import DispositionDefinition, DispositionService, disposition_ref

dispositions = DispositionService(store, controls=controls)
definition = DispositionDefinition({
    "schema_version": "1.0", "namespace": "example:dispositions",
    "kind": "deferral", "status": "active", "matter": matter_reference,
    "purpose": {"reference": purpose_component, "context": purpose_pointer_pin},
    "audience": {"reference": audience_component, "context": audience_pointer_pin},
    "subject": exact_subject_pin,
    "effective_from": host_clock(), "effective_until": reconsider_at,
    "reason": "Defer this subject for this audience until the checkpoint.",
    "decision": None,
})
command = dispositions.prepare(
    definition, command_id="deferral-1", idempotency_key="deferral-1",
    actor=authenticated_actor, authority=host_authority,
)
result = dispositions.commit(command)
selected = dispositions.read(original_read_token, disposition_ref(definition))
```

A deferral requires a known end. At that exact boundary `active` becomes false,
and an earlier consumer's declared interval condition becomes stale and requires
reconsideration. A rejection names an exact association proposal or exact
host-owned proposal projection; it cannot reject a source observation as fact.
A later proposal snapshot or another audience has a different slot. A host
projection used this way must represent the one declared proposal being rejected.

Only a `decision` carries a typed decision value; other kinds require `None`.
Acknowledgement never implies factual agreement, action, usefulness or repair.
Decision meaning remains domain-owned; this module does not perform a lifecycle
transition. Superseding a disposition requires its exact prior slot revision.
An authorized `status: "withdrawn"` replacement preserves the original record
and does not fabricate recovery evidence.

`read` returns applicability, exact disposition dependency and future interval
guards. To compute current work, use the current slot and bind those dependencies
to the consumer. A historical read remains historical evidence. Absence is an
explicit `E_NOT_FOUND`, not a completeness claim over all dispositions. Hosts
that depend on absence must derive their exact candidate slots and retain the
corresponding original control-fence guards; no global disposition scan exists.

## Host authority, reads and replay

The host supplies an actual `ControlService` bound to the same store. The
authenticated actor, admitted original authority and complete public-reference
targets are checked during prepare, commit, read and exact replay. The established
`command_targets` traversal includes public references nested inside typed
payloads. Static target restrictions can predeclare the public slot plus every
referenced matter/context/subject scope. Current READ denial blocks disclosure
of historical results too; it preserves the original journal.

Only the exact public context/disposition slot enters the generic control's
fence scope. Putting its matter there would stale unrelated audience-independent
evidence tokens. The complete actual public target set is still separately
authorized and READ-audited. Public slot namespaces cannot use `matter.*`
internal projection namespaces. Raw source/model-origin records cannot mint a
context mutation. No token is silently recaptured or expanded.

Install the existing invalidation observer on participating stores for atomic
registered consumer updates, as documented in [dependencies](dependencies.md).
Raw store access remains a privileged host interface. Context/disposition
services do not create a delivery directory, settings UI, budget-reservation
engine, scheduler, provider call or external action. See the
[MAT-018 validation receipt](validation/MAT-018.md) for executed evidence and
the synthetic boundary.
