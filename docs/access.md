# Host scope, source access and provider egress

MAT-072 adds an explicit adapter over [trusted controls](controls.md), exact
source snapshots and the existing [packet](semantic-packets.md),
[assessment](assessments.md) and semantic-cache APIs. The host authenticates
principals and supplies current sharing policy. Matter does not add an identity
service, discover permissions from source text, redact evidence, or construct a
provider client.

## Host policy and immutable context

`HostAccessPolicy(scope_id=..., audiences=[exact_component_refs],
providers=[{"reference": exact_component_ref, "provider": protocol_name,
"transport": transport_name}], grants=[...])` is immutable trusted
configuration. A grant contains an exact `reference`, allowed `audiences` and
allowed `providers`. Empty lists deny. Provider `None` in a context means local
consumption, and does not authorize remote execution. Audience selectors are
opaque exact component references; this module defines no audience preferences
or responsibility semantics.

All public source references must belong to the policy scope. This adapter does
not implement cross-scope sharing. Explicit source grants bind exact mutable
revisions or immutable digests; matching content hashes alone do not grant
another source identity access. Source metadata, model judgments, confidence,
qualification, and copied sharing labels cannot construct or expand a grant.

Actual public `provenance.parents` restrict every derivation conjunctively.
An explicitly permissive child grant cannot weaken a parent. A derived or
evaluator record, assessment, or judgment can inherit permission from its
nonempty verified parent closure, with any explicit child restriction applied
as an additional gate. Missing parents, cycles, excessive closure, changed
snapshots and inaccessible sources fail closed. Receipt/control/internal
projection bookkeeping retains the existing control exclusions and does not
become source authority.

`AccessService(policy=..., controls=existing_control_service,
current_read=None)` uses the original control token:

```python
with store.snapshot() as view:
    context = access.capture(
        view, token=original_token, audience=exact_audience,
        provider=exact_provider, references=selected_input_pins,
    )
```

The host must capture a token covering the complete source/parent target set
before work begins. This service never recaptures, narrows or renews that token.
Static host authority and present READ restrictions are checked separately from
audience/provider sharing eligibility. A source becoming unreadable invalidates
reuse even if its bytes and digest have not changed.

`AccessContext.value` is detached serializable private audit material containing
only admitted exact references, the original token and selectors.
`.reference` is its immutable component identity. It carries no source text or
credential. The host must use currently configured policy: a different policy
reference refuses an old context. External grant changes must update that
configuration and reach the existing control path for in-flight work. A
long-lived obsolete host configuration cannot discover a change by itself.

## Current checks and integration

`require_current(view, context, references=(), audience=None, provider=None)`
verifies exact selectors, required pins, parent closure, host grants, READ
permission and original control fences. It uses a supplied current transaction
directly. A detached `FrozenAssessmentView` additionally requires the optional
`current_read` factory to open a fresh, scoped host snapshot. Dispatch always
requires that fresh check.

The existing store's `.snapshot` can be the factory when no operation is already
open on that handle. A host can instead borrow an independent scoped read handle
when its storage port requires one. No new storage implementation is supplied.
Do not hold a database read transaction across provider work; dispatch can use
the detached preparation view and brief fresh reads before and after execution.
The factory is trusted host infrastructure and must return actual current reads,
not a historical or detached view.

Install the same access boundary at each protected port:

- `AssessmentService(..., access=access)` requires
  `prepare(..., access_context=context)`, matching the original assessment token
  and exact requested audience. Its captured inputs retain the context. Graph
  currentness, atomic publication, current consumption, historical attempt reads
  and staged prerequisites recheck it. A serialized foreign-source rule attempt
  cannot acquire eligibility through a model answer.
- `SemanticCache(..., access=access)` requires a context at `capture`.
  Assessment cache queries forward their original context. The identity enters
  the projected cache key; the callback receives its opaque reference, not token
  or grant material. Capture, hits, computation results and transaction staging
  check current source access. A more restrictive audience cannot relabel an
  old result into permission. Old raw attempts remain immutable private history.
- `prepare_packet(..., access=access, access_context=context)` checks every
  public read through the access view and binds the context reference into the
  selected state. A denial returns no partially prepared packet. Its exact
  digest therefore binds effective access as well as source eligibility.
- `render_question(..., access=access, access_context=context,
  access_view=current_view)` checks the entire selected state before rendering
  and before returning. An already access-bound state cannot fall back to an
  unconfigured renderer. The manifest binds the same context reference.

Once an access boundary is installed, missing contexts fail closed. An
access-bound assessment/cache cannot be read by removing its installed boundary.
Legacy synthetic hosts without access configuration retain their earlier APIs;
that compatibility does not imply permission to process real private evidence.

## Provider and explanation output

`access.dispatch(detached_view, context, batch, injected_executor,
rendered_questions=[guarded_rendered_question, ...], clock=..., precision=None)`
checks scope, the exact question objects and manifests, the original assessment
capability, and the host's exact provider/transport mapping. It checks current
eligibility immediately before calling the existing executor seam. No denied
request reaches the injected executor. If access changes during execution, the
response is withheld after another fresh check.

This does not retract an already transmitted request or preempt synchronous
Python. I/O after the authorization point remains the host transport's
responsibility. Hosts must route protected provider work through this gate;
direct calls to the lower-level executor are privileged host operations.

`access.explain(current_view, context, exact_assessment_pin)` reads an actual
stored assessment under present permission, verifies its source/derivation
closure and exact audience, then returns only its assessment reference,
propositions, proposals, causes, limitations and access identity. It does not
render raw attempt journals. Revocation blocks this output and access-bound
assessment history reads while leaving privileged immutable storage intact.

## Public outcomes and trust boundary

An admitted empty context reports `permitted_empty`. An admitted nonempty
context reports `permitted`. `access.public_failure(error)` exposes only fixed
`forbidden/access_forbidden` or `unavailable/source_unavailable` outcomes.
Cross-scope references use `E_SCOPE_FORBIDDEN`; missing or revoked access uses
`E_AUTHORITY_REQUIRED`; an admitted source that cannot be read uses
`E_EVIDENCE_UNAVAILABLE`. No failure includes denied source IDs, locators,
quotations, provider exceptions or partial source manifests. This module emits
no content logs.

These are trusted host ports, not a Python sandbox or universal protection for
raw storage, payload handles, arbitrary source strings or legacy APIs. The host
must preserve provenance, admit templates/configuration, and avoid inserting
unattributed private content into free-form fields. Access checks cannot prove
that an arbitrary string's provenance was honestly declared. Qualified model
output remains a judgment and grants neither source authority nor action rights.

The [validation receipt](validation/MAT-072.md) records synthetic local evidence
separately from authentication, live provider behavior and production assurance.
