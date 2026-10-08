# Association proposals and authorized acceptance

MAT-008 implements a durable decision boundary between candidate nomination
and an accepted attachment. `AssociationService` publishes explicit candidate
catalogs, records immutable exact-key or externally evaluated proposals, and
accepts a selected candidate only under a separately configured host policy.
Scoped rejection, protected separation, and explicit correction survive new
proposal IDs, command replay, restarts, and backup/restore.

Run the complete synthetic example:

```bash
python examples/association_acceptance.py
```

The [validation receipt](validation/MAT-008.md) records the acceptance evidence.
The governing [core contract](contracts/core.md#6-association-relations-merges-and-correction)
continues to distinguish association, relatedness, and identity equivalence.

## Host configuration and authority

```python
from matter.associations import AssociationPolicy, AssociationService
from matter.storage import pin

policy = AssociationPolicy(
    store.scope_id,
    actors=[reviewer_actor],
    authorities=[pin(admitted_host_authority_receipt)],
    matching_rules=[matching_rule],
    relations=[attachment_relation],
    allow_semantic=False,
    allow_correction=False,
)
service = AssociationService(store, policy=policy)
```

The host supplies this immutable configuration through a separate Python
constructor. Its definition is detached from caller-owned dictionaries, and
its versioned reference hashes the complete scope and allowlists. Each command
must name an admitted actor and authority. The admitted authority is an exact
immutable receipt pin; the service reads it and verifies `stage: authority`
and `provenance.origin: host`. An operation, source, or evaluation receipt does
not satisfy that requirement merely because it is placed in `authority`.

This is a local capability boundary for an authenticated host. The host owns
actor authentication and receipt admission. It must not construct a policy
from observation text, evaluator output, or untrusted request fields. The
installed example creates a synthetic authority through a trusted local
bootstrap transaction; it does not implement an identity provider. General
host control epochs and immediate stop/cancellation routing remain MAT-011.

`allow_semantic=True` allows an explicit host decision about an external
semantic proposal. It does not qualify a provider or turn the submitted
confidence or certificate into permission. The proposed uncertainty and
qualification remain inspectable, including failed or unqualified claims.
No automatic confidence threshold or qualification service is supplied here.
`allow_correction=True` permits an explicit release of an earlier association
disposition. Every operation still checks scope, admitted actor/authority,
allowed rule and relation, current pins, and applicable persistent decisions.

The supported acceptance capabilities are `attach` and `relate`. They both
create a bounded two-member `accepted_association`; neither changes either
member's identity. `merge` always returns `E_AUTHORITY_REQUIRED` at acceptance.
The host may record a protected `merge` disposition for the later identity
correction engine, but MAT-008 never performs a merge, creates a redirect, moves
children, or grants permission for an indirect merge. Those operations and
full merged-group protection belong to MAT-009.

## Publish the candidate universe explicitly

`publish_association_candidates` has this closed body:

```python
{
    "query": {
        "source": source_adapter,
        "subject": subject_identity,  # Bare observation/occurrence/matter ref.
        "candidate_type": "matter",
        "mode": "exact_keys",
        "matching_rule": matching_rule,
        "selector": schema_bound_query_description,
        "keys": [{"namespace": "example:catalog-key", "value": "item-7"}],
    },
    "entries": [{
        "candidate": candidate_pin,
        "keys": [{"namespace": "example:catalog-key", "value": "item-7"}],
        "basis": [evidence_pin],
    }],
    "coverage": {"status": "complete", "snapshot": source_snapshot},
    "evidence": [evidence_pin],
    "as_of": publication_time,
    "previous": None,  # Current catalog pin is required for a replacement.
}
```

Use the standard command envelope, then call
`service.publish_candidates(service.prepare(command))`. A successful result
is `published` or `unchanged` and includes `body.candidate_set` and `changes`.

The catalog's stable projection identity hashes the declared scoped query,
including source, subject identity, candidate type, matching rule, selector,
mode, and normalized key set. Candidate keys use exact namespace/value equality:
there is no trimming, case folding, Unicode normalization, or inferred join.
Arbitrary selector JSON retains canonical distinctions such as `true` versus
`1`. A matching key belongs to this candidate catalog; it does not expand or
rebind the continuing identity keys owned by `MatterService`.

Publication reads the current subject and every declared candidate, evidence,
and basis reference. Members must be distinct from the subject, unique by
scoped identity, of the declared candidate type, and present at their exact
pins. Unknown IDs, wrong kinds, foreign scopes, duplicate entries or keys, and
stale references are refused. Only observations, occurrences, and matters may
be association members. Claims, receipts, controls, and judgments can remain
evidence or decisions, and cannot be promoted into membership candidates.

The closed stored snapshot preserves the subject pin, complete entries,
coverage, evidence, publication time, publishing policy and authority.
Empty catalogs are valid. Existing catalogs require their exact `previous`
revision or snapshot digest; two publishers cannot silently replace each
other's work. Canonically unchanged publications retain their revision.

**Coverage is relative to this explicit host catalog/query.** The host must
republish it when the covered membership or source coverage changes. The
service does not scan every matter, discover remote records, invoke retrieval,
or prove that a supplied list is globally complete. An unpublished external
candidate cannot be detected by a local revision check. New matching entries
in a published catalog advance its revision and invalidate proposals pinned
to the old set. Nonmatching additions also conservatively advance that revision.

## Record a proposal

`propose_association` retains the existing `subject`, `candidates`,
`matching_rule`, `evidence`, and `assessed_as_of` fields and requires a
`candidate_set` pin at runtime. Each considered candidate is
`{"candidate": exact_pin, "basis": [...]}`. The command must preserve all
nominees from its catalog and their basis; it cannot remove a rival or switch
queries. The `exact_candidates(catalog_record)` helper returns that list.

For `exact_keys`, any identical namespace/value key nominates an entry. The
service computes the outcome without a model:

| Current covered evidence | Proposal outcome | Selection |
|---|---|---|
| Complete usable query, zero exact nominees | `no_match` | Empty |
| Complete usable query, one exact nominee | `matched` | That nominee |
| Complete usable query, two or more nominees | `ambiguous` | Empty; retain every alternative |
| Incomplete coverage, no declared matching evidence, or unavailable declared observation evidence | `insufficient_evidence` | Empty |

Availability uses the pinned observation metadata on explicitly declared
`evidence` and candidate `basis`. Being an identity member does not implicitly
make that record evidence. No payload bytes or URLs are read by this service,
and it does not establish the truth of declared keys. Source access or
semantic interpretation requires the appropriate host adapter. Malformed
storage or a backend outage remains an explicit error; neither becomes an
empty candidate list or `no_match`.

For `semantic`, every catalog entry is an eligible considered candidate, and
the command supplies a closed `evaluation` declaration:

```python
{
    "producer": evaluator_version,
    "outcome": "matched",
    "selected": [candidate_pin],
    "uncertainty": schema_bound_uncertainty,
    "qualification": qualification_declaration,
    "reason": "The external evaluator's stated reason.",
    "missing_evidence": [],
}
```

The runtime supports one selected candidate per matched proposal. It refuses
unknown selection IDs, selection outside the frozen set, incompatible pins,
or a declaration of ambiguity without two alternatives. A declared
`evaluation_failed` stays distinct and selects nothing. An external match or
no-match claim under insufficient available evidence becomes an effective
`insufficient_evidence` proposal while preserving the submitted evaluation.
An external declaration cannot override an exact-key result.

The service atomically writes an immutable evaluation receipt and immutable
proposal. The receipt binds the entire input decision: subject, catalog pin,
considered candidates and their basis, rule version, explicit evidence,
coverage, assessment time, submitted evaluation, and effective outcome and
selection. The recorded evaluator descriptor is a declaration, not a signature
or authority grant. Proposal provenance names the service that admitted that
declaration and links the exact receipt.

Every semantic outcome persists a proposal. The result outcome for a match is
`proposal`; the other outcomes are `no_match`, `ambiguous`,
`insufficient_evidence`, and `evaluation_failed`. Each result includes exact
`proposal` and `candidate_set` pins. Negative outcomes also preserve their
appropriate coverage, alternatives, or reason. A successful proposal operation
creates no accepted association and does not change any member.

## Accept against the original current snapshot

An `accept_association` command carries:

```python
{
    "proposal": proposal_pin,
    "candidates": all_considered_candidate_pins,
    "candidate_set": original_candidate_set_pin,
    "acceptance_policy": policy.reference,
    "relation": attachment_relation,
    "capability": "attach",
    "as_of": host_decision_time,
}
```

`prepare` fills `as_of` if omitted and collects current dependency guards.
Retain the exact prepared command before calling `service.accept(command)`.
The service first verifies the immutable proposal/receipt bindings and then
reconstructs the decision from its original catalog. Matching copies of two
malformed records are not sufficient proof: catalog subject, mode, rule,
coverage, candidates, evidence, selection, and outcome must all agree.

Acceptance rechecks the current catalog **and every published member and
evidence dependency**, including alternatives that were not selected. Both
aggregate revisions and exact mutable snapshot digests are supported.
Preparation never refreshes an old proposal to a newer catalog or member.
An identity metadata update, new published matching candidate, coverage
replacement, changed basis, or conflicting expected revision refuses the old
acceptance with an explicit conflict. The caller must make a new decision
against current evidence; it cannot drop a rival from `body.candidates`.

Acceptance then checks the current scoped policy and durable pair disposition.
The accepted association and its immutable host-decision receipt commit with
its subject lookup index in the same transaction. The record preserves the
proposal, original members and catalog pin, relation version, capability,
authority, policy reference, and decision receipt. Its ID is stable for the
scoped subject/target/relation identity/capability pair. Subsequent authorized
acceptances append revisions to that record rather than creating duplicate
active edges under new proposal IDs.

## Rejection, protected separation, and correction

`decide_association` supplies current member pins, a relation, and a capability:

```python
{
    "subject": current_subject_pin,
    "target": current_target_pin,
    "relation": attachment_relation,
    "capability": "attach",
    "decision": "reject",  # reject, protect, or release
    "previous": None,
    "reason": "The host's explicit reason.",
    "as_of": host_decision_time,
    "acceptance_policy": policy.reference,
}
```

A rejection or protection persists a blocked disposition and, when that pair
has an active accepted association, revokes it atomically. The accepted
record, lookup index, new disposition and immutable decision receipt either
all commit or none do. Original proposals and every old association revision
remain available.

Disposition identity uses the member identities, relation namespace and ID,
and capability. Candidate or proposal revisions, run metadata, confidence,
query changes, and relation version/digest changes cannot evade it. Attachment
and relatedness are directional. Merge separation is symmetric across the
pair. A merge-only protection does not block an attachment; a protection
against `attach` applies to that declared relation and direction. General
transitive protection across merged groups is a separate MAT-009 operation.

Releasing a disposition requires `allow_correction=True`, its current
`previous` pin, an admitted host command, and an explicit reason. A stale
release loses the revision race. Release changes the disposition to
`released` and preserves its history; **release alone does not reactivate an
association**. A subsequent authorized acceptance must still satisfy all
current proposal/catalog checks. Correcting a mistaken target therefore means
rejecting the old pair and accepting a separately reviewed proposal for the
new target. These are explicit scoped decisions, without an implicit merge or
automatic transfer of evidence.

An exact retry of an old successful acceptance returns its original saved
result even after rejection. That result is historical fact and does not run
the handler or reactivate the edge. A new command, idempotency key, or proposal
ID must pass today's disposition and revision checks. The transaction re-reads
the deterministic disposition address even when no decision existed at
preparation, detecting a first rejection that races acceptance.

## Read current decisions and history

- `service.for_subject(subject_identity, relation=None, status=None)` returns
  current accepted-association records, optionally limited to `active` or
  `revoked` status and an exact relation descriptor.
- `service.disposition(subject, target, relation, capability="attach")`
  returns the verified current disposition or `None`.
- `service.history(association_identity)` returns every association revision
  after verifying each immutable proposal and decision binding.
- `store.get(proposal_pin)` and `store.get(evaluation_receipt_pin)` expose
  the immutable proposal and complete evaluation declaration.
- The standard storage history API exposes every candidate catalog and
  disposition revision; command receipts expose exact commands and results.

Historical verification uses immutable receipts. It does not require an old
mutable candidate/catalog snapshot to remain current merely to inspect or
revoke an earlier decision. This allows correction after member metadata has
advanced while preserving exactly what the earlier host accepted.

`changes` notices name exact before/after pins with `new_evidence`,
`association_correction`, or `disposition_change`. They do not implement
transitive assessment invalidation or cancel deliveries. An association's
`active` status records the latest host decision; a later catalog publication
does not itself revoke that historical decision. Fresh acceptance requires
current inputs, and assessment/queue invalidation remains MAT-016.

## Reuse and bounded evidence

The implementation reuses Matter's existing transactional port, canonical
encoding, typed records, versioned private projections, exact revision guards,
receipts, and schema-bound evidence pattern. It adds no storage migration,
database platform, retrieval stack, provider client, or external orchestration.

The pinned civic
[Matters matching and rejection implementation](https://github.com/mfreeze77/state-civics-ai/blob/a34fcec27f353187e7a23d54788b203d13ac87c1/services/local-accountability/sar_tracker/core_import/matters.py)
was inspected, specifically `find`, `rejected`, the conflict paths in `matter`,
and `merge_blocker`. Useful distinctions are exact nominations versus
conflicting identifiers, operator rejection surviving import replay, and
explicit protected-undo checks. Matter implements those association boundaries
independently over its neutral scoped records. No upstream code was copied,
no upstream test suite was run, and no civic importer or merge behavior is
qualified by these synthetic checks.

The five new packaged private schemas are `candidate-set`,
`association-evaluation`, `association-decision`, `association-disposition`,
and `association-membership`. The public envelope remains version `1.0` with
additive operations and optional stored/runtime fields. The
[compatibility notes](contracts/compatibility.md) distinguish structural
acceptance by older envelopes from the stricter MAT-008 runtime requirements.
