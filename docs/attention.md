# Attention eligibility and delivered baselines

MAT-019 evaluates a neutral attention treatment for one current assessment,
purpose and audience. It records a decision and its actual inputs; it neither
sends a message nor creates an outbox. A treatment is not delivery permission,
a lifecycle transition or a universal importance score.

## Explicit semantic policy

Install immutable `AttentionPolicy` definitions in `AttentionService`. A policy
pins the actual assessment profile and a bounded list of named semantic fields.
Each field declares an exact installed claim-value schema, predicate, JSON
Pointers for condition/value, an exact condition and accepted values/statuses.
Fields can contribute material, relevance, critical or owned-next-step meaning.
This is a bounded comparison over admitted assessment propositions, not a query
language or a free-form model response interpreter.

The service first calls the shared `AssessmentService.read_current` gate. It
never treats a raw unqualified judgment, confidence value or old immutable
assessment as current admission. It reads the actual selected claims, checks
their original subject/schema/condition, and projects named semantic values
plus admitted proposition statuses. Equivalent current claims collapse;
incompatible matches remain unknown. Selected claim pins remain in the receipt
and dependencies, but do not become the material identity.

An auxiliary critical, ownership or decision field with no selected assertion is
inactive, rather than automatically making the entire assessment inadequate.
Selected unknown/conflicting auxiliary evidence still records an evidence gap;
missing material/relevance fields remain insufficient. Conditions, accepted
values and material comparisons use canonical typed JSON equality, so `false`
and `0` (including nested values) are distinct.

Material comparison therefore ignores source paraphrases, new claim IDs,
attempt IDs, internal computation time and wording outside the declared value
selectors. The material contract binds the named selectors; policy IDs and
delivery cadence do not manufacture uninformed audiences. Different material
contracts are recorded explicitly as `material_contract_change` rather than
being labeled new external evidence.

An actual selected claim correction can follow bounded explicit supersession
links to the same named field in the delivered decision. Every intermediate
assertion must retain the same subject, schema, predicate and condition; traversal
is bounded to 128 links per field. This permits a retraction/unknown correction
without a new positive event. An unrelated new unknown assertion without that
correspondence does not become a correction merely because a coarse assessment
cause changed.
The correspondence must belong to the material field whose value actually
changed. A reassertion of unchanged field A cannot classify an ordinary or
uncertain change in field B as a correction.

## Prepare, evaluate and inspect

```python
from matter.attention import AttentionService, RESULT_EXTENSION

attention = AttentionService(
    store, assessments=assessments, policies=[attention_policy],
    controls=controls, clock=host_clock,
    lifecycle=lifecycle_service, access=access_service,
)
prepared = attention.prepare(
    assess_command, policy=attention_policy,
    assessment=exact_current_assessment_pin,
    contexts={
        "purpose": purpose_pointer_pin, "audience": audience_pointer_pin,
        "responsibilities": responsibility_pointer_pins,
        "preferences": preference_pointer_pins,
    },
    token=original_assessment_work_token,
    lifecycle={"profile": lifecycle_profile_reference, "condition": condition},
    access_context=original_access_context,
)
result = attention.evaluate(prepared)
decision = result["extensions"][RESULT_EXTENSION]["value"]
```

The existing `assess` envelope is used. Its success body references the actual
current assessment; the strict result extension contains actual treatment,
all applicable reasons, decision receipt and dependency pins. Exact retries
return the original journal after present READ/access checks.

Context pointers must be current, apply to the original matter scope and match
the actual purpose/audience versions. Linked objectives already consumed by an
assessment remain guarded by that assessment's original dependencies; the
attention service does not hydrate arbitrary latest context components. An
inactive purpose/audience, applicable disposition, material equivalence,
inadequate evidence, incomplete coverage, recovery or an already-owned next step
can produce distinct quiet reasons. Reasons are retained together.

Responsibility is read as a host declaration, not an action grant. An explicitly
assigned working-agent audience can receive `host_hint` while a human stays
quiet. A host-agent audience must actually name the selected responsibility
component to count as that owner; another agent does not inherit the assignment.
A single admitted critical fact requires no universal recurrence threshold.

Routine treatments are explicit policy/preference choices (`host_hint`, `digest`
or `update`). A decisive correction for an informed audience can produce
`correction` while retaining uncertainty reasons. `decision_request` additionally
requires an admitted decision-need field, the exact reserved person/role audience,
concrete options, a prompt and a declared reason ordinary authorized host work
cannot settle it. Low confidence alone never creates that request. A preference
cannot independently mint a correction or decision request.

`subject=...` can scope dispositions to a particular exact proposal/assessment;
the default is the selected assessment. The service derives all four relevant
acknowledgement/deferral/rejection/decision slots itself. Their original control
fence absences are included in the original work token. A pre-existing deferral
cannot be omitted by a caller, and creating one after preparation fences that
attempt. No global disposition scan or recipient directory is introduced.

`attention_ref(matter, policy=..., purpose=..., audience=...)` addresses the
registered current decision. `current(..., read_token=..., access_context=...)`
checks registered freshness and the actual current assessment/lifecycle gates.
`read(read_token, decision_receipt, access_context=...)` is separate authorized
historical inspection; it does not renew an old work token or decision.

## Advance knowledge only from an actual delivery milestone

The delivered baseline belongs to the matter/purpose/audience identity, shared
across equivalent attention-policy IDs. It retains the exact policy, context
versions, actual delivered assessment, material contract/value/digest, decision
and host receipt. An initial empty guard row (`delivered: None`) is not a
delivery. It lets the first actual baseline update invalidate earlier eligible
decisions atomically.

To record a milestone, call `prepare` with `delivery_receipt=exact_receipt_pin`
and an original `delivery` work token, then `evaluate` that prepared command.
The selected assessment in the command remains actually current; the receipt
can describe a historical decision delivered before a later correction. The
service records what was actually delivered without requalifying that old
assessment as current.

The receipt must already exist in the store, have host origin, stage `delivered`,
and the exact configured producer/outcome. Its strict
`attention-delivery-milestone` details bind:

- the actual persisted attention decision and its assessment;
- matter and exact purpose/audience versions;
- the actual material digest and `milestone: "delivered"`;
- a nonfuture delivery time no earlier than that decision.

Quiet decisions, queued/unknown/consumed acknowledgements, internal reassessments,
unadmitted producers and inferred success cannot advance the baseline. An exact
prior-baseline revision is checked atomically. Older or ambiguous same-time
milestones cannot overwrite newer delivered knowledge; exact command replay
remains idempotent. All historical baseline revisions remain available.

These are verified declared host receipts, not a promise that this package
observed real network transport. The host adapter remains responsible for its
actual milestone evidence. MAT-021 owns transport/outbox concurrency and the
irreversible send boundary.

## Authority, access and atomic timer integration

The original authenticated actor, authority, complete public target set,
control fences and access context are rechecked inside the actual transaction.
No token is recaptured or expanded. This is the original token for the
attention attempt; the assessment
publication's own original token is independently checked by its shared gate.
With MAT-072 installed, public context
metadata needs its own exact host grants; derived assessment/source ancestry
must also be permitted to the selected audience. Present READ denial blocks
publication and historical disclosure, preserving the original journal rather
than relabeling denial as quiet/no relevant matter.
Omitting `access=` inherits the assessment service's boundary. An explicit
conflicting boundary or later boundary drift is refused; omission cannot disable
audience/source checks for evaluation, current reads, history or replay.

`stage(transaction, prepared_attention_command)` is the view-local deterministic
seam used by `evaluate` and by the timer service. The enclosing trusted command
must preserve actor/authority and include all original attention read pins in
its checked read set. Stage reruns actual freshness/control/access/context
guards and returns staged decision/current/dependency references. It opens no
nested transaction and makes zero semantic/provider calls. The enclosing timer
can commit its firing and the new decision together; it cannot mark a failed
or stale computation successfully fired.

No transport, private corpus, adaptive source discovery, new identity directory
or qualification issuer is included. The [MAT-019 validation receipt](validation/MAT-019.md)
separates synthetic interface evidence from provider accuracy and live usefulness.
