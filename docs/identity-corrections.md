# Typed relationships and reversible identity correction

MAT-009 implements `link_matters`, `merge_matters`, `correct_merge`, and
`release_identity_separations`. Relationships preserve distinct identities. A merge
requires explicit host equivalence authority and creates a current identity
group while retaining every original matter, key, claim and evidence reference.
Undo and split restore explicit partitions and protect the separated originals
against a later indirect merge.

The implementation uses the existing scoped storage transaction, immutable
receipts, exact command journal, revision checks and projection watches. It
adds no database service, provider client or downstream integration. The
[core contract](contracts/core.md#6-association-relations-merges-and-correction)
governs these operations; the [acceptance receipt](validation/MAT-009.md)
records the executed evidence and its limits.

Run the standalone example from the checkout or an installed package:

```bash
python examples/identity_corrections.py
```

It creates synthetic related subjects and conflicting assertions, merges two
subjects, stores an explicitly incomplete historical assessment, undoes the
merge, verifies atomic validity changes, refuses an indirect remerge, and
checks exact replay after backup/restore. No evaluator or real corpus is used.

## Current identity and retained originals

Each original matter may have a private `matter.identity_groups` projection.
Its closed value records the original member, the direct survivor, the complete
member set and the immutable identity decision. All members mirror the same
complete group. A matter with no identity projection is an untouched singleton.
Reads verify every member, mirror and decision; a missing mirror inside a
declared group is an error. Redirects never form chains.

Every merge/correction increments all affected matter revisions, even when
their display fields are unchanged. Candidate proposals and other exact matter
dependencies prepared before that change therefore fail currentness checks.
The immutable snapshots and original creation receipts remain available.

| Read or operation | Meaning after a merge |
|---|---|
| `store.get(entity_ref(original))` | Current revision of that original stored matter; no implicit redirect |
| `store.get(old_pin)` | Exact historical original snapshot |
| `identities.resolve(entity_ref(original))` | Current canonical survivor record |
| `identities.view(entity_ref(original))` | Complete current group, retained child references, protection pins and guarded read set |
| `identities.historical_view(decision_pin)` | Verified immutable before/after identity decision, child routing and conflicts |
| `MatterService.resolve(original_keys)` | Current survivor through the retained original exact-key bindings |

`resolve` and `view` accept a full record as a convenience and then use its bare
identity. A supplied revision/digest reference remains an explicit currentness
condition and is never silently refreshed. Use a bare reference when asking
for today's resolution of an old stored record.

Exact-key projections continue to name their original owners. A losing matter's
keys are not transferred to the survivor or added to its original body.
`create_matter` can return the survivor for a fresh proposed ID, the original
key owner, or the canonical survivor's ID without writing an alias. An occupied
different member still conflicts. Metadata edits through a redirected original
ID refuse with `E_MERGE_CONFLICT`; a current survivor can still be edited.

## Typed relationships

The host constructs immutable rules and admits actual authority receipts:

```python
from matter.relations import RelationRule, RelationPolicy, RelationService

depends_on = RelationRule(
    "example:depends_on", namespace="example", id="dependency-link",
    version="1.0", directed=True, allow_self=False, acyclic=True,
)
links = RelationService(store, policy=RelationPolicy(
    store.scope_id, actors=[host_actor], authorities=[authority_pin],
    rules=[depends_on],
))
```

Each rule's component digest binds its kind, identity/version, directionality,
self-link permission and cycle rule. The `link_matters` body contains exact
`from_matter` and `to_matter` pins, `relation_kind`, the rule's
`relationship_schema` reference and an explicit `basis` list. The envelope
supplies the actor, admitted host authority and complete prepared read set.

The service records the original endpoint pins and its frozen rule in an
indexed `matter_relation`. Repeating an identical relationship declaration
preserves the original edge. A changed declaration cannot silently overwrite
it. This release implements active link creation and exact duplicates, not a
general relationship revocation or rule-migration operation.

Cycle checks run on the complete affected relationship-kind graph, with every
endpoint resolved through its current identity group. A merge can therefore be
refused when A→B→C would become cyclic after A and C become equivalent. A
forbidden effective self-link also refuses the merge. The caller cannot relax
an existing edge's frozen constraints by choosing another merge policy or a
more permissive relationship version. Directed and undirected semantics cannot
be mixed inside one relationship-kind graph.

A related-to rule may allow cycles or effective self-links if the host declares
that meaning. A-related-B-related-C still retains three identities until a
separate authorized merge commits. Relationship structure supplies no
equivalence authority and applies no lifecycle transition.

## Explicit merge authority and preparation

```python
from matter.identity_corrections import MergePolicy, IdentityCorrectionService

merge_policy = MergePolicy(
    store.scope_id, actors=[host_actor], authorities=[authority_pin],
    allow_correction=True,
)
identities = IdentityCorrectionService(store, policy=merge_policy)
```

The host admits the actors and actual immutable host-origin receipts at the
`authority` stage. The policy definition is immutable and content-bound. A
confidence score, evaluator receipt, related-to edge or successful association
acceptance does not grant merge authority. The identity decision preserves the
actor, actual authority pin, full policy definition and equivalence basis.

The `merge_matters` body contains:

```python
{
    "survivor": current_survivor_pin,
    "merged": [current_other_matter_pin],
    "equivalence_basis": [evidence_pin],
    "merge_policy": merge_policy.reference,
    "as_of": known_time,
}
```

The survivor must be its group's current representative. Each losing operand
expands to its complete current group. Repeated operands or multiple operands
already belonging to the same group refuse. The host's evidence basis is
audited and checked for existence/currentness; this engine does not prove its
semantic equivalence conclusion.

Call `prepared = identities.prepare(command)` once, retain the exact returned
command, then call `identities.merge(prepared)`. Preparation captures all actual
member, mirror, authority, child/index, graph and protection reads. It preserves
caller-supplied pins and freezes `as_of` when omitted. Execution repeats the
inspection inside one transaction. New watched children or protections after
preparation produce `E_REVISION_CONFLICT`, including the first new registration
where the earlier view was empty.

A successful result includes the current survivor pin, every losing original
as a bare `redirect`, the immutable `merge_receipt`, exact `identity_views`
projection pins and dependency `changes`. Exact journal retry returns the
original result without rerunning authorization or writes. A new decision
requires a new command ID and a fresh plan.

## Child preservation and movement history

The current merged view composes the existing service-owned indexes:

- Original exact-key bindings.
- Immutable claims for each original subject and their attribution.
- Verified evidence relations, original citation snapshots and their indexes.
- Accepted associations, original observation/occurrence endpoints, membership
  indexes and pair dispositions.
- Typed matter relationships and their frozen-rule indexes.
- Explicitly registered host assessment/projection dependencies.

An occurrence contributes its declared original observations when its cited
snapshot is current. An older cited occurrence remains an exact historical
reference, whose original contents can be read through the historical storage
API. It is not silently replaced with today's occurrence membership.

Every child entry records its exact `reference` and `original_matters`.
Immutable decision entries additionally record effective `before` and `after`
survivor lists and an action: retained, moved, shared or invalidated. A moved
view means its effective owner changed; its authoritative source record was
not rewritten. Shared references remain one source snapshot and do not gain
independent corroboration by appearing under multiple originals. The
`record_action` distinguishes retained snapshots from explicitly revisioned
validity projections.

Mechanical overlap remains reviewable. Receipt conflicts identify overlapping
claim predicates, shared evidence, overlapping effective attachments or links,
and differing original metadata. These explanations do not decide truth or
infer that different values are logically contradictory under an unstated
domain policy. The survivor supplies a current display identity; original
claim, decision and lifecycle differences remain intact.

This inventory is complete for those service indexes and registered host
derivatives. Arbitrary records written through a custom storage handler are not
automatically discovered or assigned an owner. Candidate catalogs retain their
own exact member pins; changed matter revisions make old catalogs stale even
though the identity service does not rewrite their records. Future services
must declare their dependencies rather than assume a global record scan.

## Undo and split

Correction requires the configured `allow_correction` capability and the latest
governing merge receipt. An old receipt cannot overwrite a later identity
operation. Later metadata edits and newly attached children are allowed when
the correction plan captures their current state.

`plan_correction(merge_receipt)` builds explicit partitions restoring the
pre-merge groups and their original representatives. For a split, supply
`partitions=[[representative, other_member], [another_representative]]` and
`correction_kind="split"`; each list's first original ID is its representative.
The helper is read-only and grants no authority.

Use the returned plan in a `correct_merge` body:

```python
{
    "merge_receipt": governing_merge_receipt_pin,
    "correction_kind": "undo",  # or "split"
    "partitions": identities.plan_correction(governing_merge_receipt_pin),
    "basis": [correction_evidence_pin],
    "as_of": known_time,
}
```

Each partition contains a bare representative `matter`, exact current
`identity_members`, and exact retained child `members`. Partitions must be
nonempty, disjoint and exhaustive over all original identities. A child remains
in every partition containing one of its original owners; shared evidence may
therefore appear in more than one partition. Missing, duplicated or silently
redistributed child references refuse. New post-merge children follow their
declared original owners without a semantic guess about where they belong.

Undo restores the actual previous groups recorded by the merge receipt, which
may already contain several identities. It does not blindly split every ID
into a singleton. Split permits a different explicit exhaustive partition.
Both operations preserve metadata edits made since the original merge and
advance all affected matter/mirror revisions. The result names every affected
original matter, the correction receipt, current identity views and changes.

Every cross-partition pair gains a durable symmetric protection in the same
transaction. Later merges inspect all original members on both sides, not
just their current representative labels. A protected A/B pair remains blocked
after A joins C, and even when both protected originals are hidden inside larger
groups. All blocked MAT-008 dispositions with `capability="merge"` also apply,
regardless of their relationship namespace or version. Attachment-only
rejections do not silently acquire equivalence scope.

## Correct a mistaken separation

A later host review can explicitly release selected universal barriers without
performing a merge. The `release_identity_separations` command requires the
configured correction capability, the exact current protected projection pins,
an auditable basis, an explicit reason and the same `merge_policy` reference.
`as_of` is optional and is frozen during preparation when omitted:

```python
{
    "separations": [current_protected_separation_pin],
    "basis": [correction_evidence_pin],
    "reason": "The host reviewed and corrected this separation decision.",
    "merge_policy": merge_policy.reference,
    "as_of": known_time,
}
```

Call `identities.release_separations(identities.prepare(command))`. The result
contains the newly revisioned `separations`, an immutable `release_receipt`,
and `disposition_change` notices. Groups, matter revisions, redirects, children
and existing derivative validity are unchanged. Each release records its exact
previous protection pin and the correction receipt that created that barrier.
Only the named barriers are released. Independent MAT-008 protections and all
other universal barriers remain effective.

A fresh ordinary merge must still pass every authority, currentness, graph and
full-group protection check. A later undo/split can protect the same pair again,
preserving the sequence protected→released→protected. `separation_history(ref)`
verifies the complete sequence and each snapshot's actual committing receipt.
An exact retry of the old successful release remains historical and cannot
release the newer protection. Current `view.protections` lists the relevant
separation projection pins, including released records whose status must remain
visible for audit.

## Atomic validity and historical assessment views

`register_identity_dependency(tx, reference, matters=[current_matter_pin])`
is an explicit hook for a trusted host transaction that stores an assessment or
host projection. It records a validity projection with exact original matter
and group dependencies. An assessment must retain those same identity pins in
its positive dependency manifest. Use a current view's `read_set` for the
transaction's complete proof guards; its `members` and `indexes` identify the
semantic identity inputs. Host projection semantics remain the host's
responsibility.

The registration returns its projection, and `dependency_ref(reference)`
computes its stable address. `require_current_identity_dependency(view, scope,
registration)` verifies the current registration, target and every identity
dependency. A historical current-status registration cannot bypass a newer
registration or invalidation.

Merge/correction changes every affected current registration to `invalidated`
inside the identity transaction and binds that change to the immutable decision.
The host must respect this validity gate before treating registered work as
current. Within a consistent snapshot, that gate refuses the old registered
result after identity changes commit. Historical registration snapshots remain
readable. Rollback restores group state and current validity together.

The historical assessment record, positive dependencies and former group
snapshots remain immutable. `historical_view` verifies the exact historical
mirrors and child pins and checks that the claimed after-state was committed
by that decision's actual operation receipt. Copying a receipt cannot claim
another receipt's old group writes.

These are direct identity-validity hooks and durable `association_correction`
notices. MAT-016 still owns general transitive dependency invalidation, and the
later lifecycle/delivery tickets own queued-work routing and transport. This
ticket neither executes an assessment nor claims to cancel external delivery.

## Refusals, bounds and compatibility

| Condition | Result |
|---|---|
| Foreign scope in an actor, authority, operand or evidence reference | `E_SCOPE_FORBIDDEN` |
| Unadmitted authority/actor or missing correction capability | `E_AUTHORITY_REQUIRED` |
| Changed prepared member, child, graph or protection | `E_REVISION_CONFLICT` |
| Protected merge, invalid partition, omitted child, stale governing receipt, or forbidden projected graph | `E_MERGE_CONFLICT` |
| Invalid new typed relationship graph | `E_RULE_CONFLICT` |
| Corrupt receipt, member mirror, index or proof binding | `E_EVIDENCE_INVALID` |
| Invalidated or historical validity registration | `E_DEPENDENCY_STALE` |
| Unavailable backend or installed schema | Explicit storage failure, never a no-match result |

The operation bounds are 128 affected original matters and 4,096 retained child
references. Typed graph traversal has a 4,096-record bound. Exceeding a bound
refuses explicitly; it never silently truncates a group, protection set or
conflict inventory. Scope is the host-bound store scope. Cross-scope read grants
and merges are not implemented.

The six new private schemas are independently content-bound assets. The core
inventory now has 22 operations and 43 successful operation/outcome pairs.
The twelve core record kinds, wire version `1.0`, canonical encoding
and SQLite migration remain unchanged. `identity_members`, `as_of`,
`identity_views` and result `changes` are additive structural fields. Updated
readers preserve older valid fixtures; runtime correction requires the explicit
identity-member plan. Earlier closed-schema readers must update before reading
new fields or the explicit release operation. See [compatibility](contracts/compatibility.md).

## Reuse

The ticket-pinned [StateCivics `matters.py`](https://github.com/mfreeze77/state-civics-ai/blob/a34fcec27f353187e7a23d54788b203d13ac87c1/services/local-accountability/sar_tracker/core_import/matters.py)
was inspected, especially `merge_blocker`, `merge`, `CHILDREN`, the full-group
operator-undo guard, direct redirect repointing, and moved/retained collision
receipts. The neutral implementation reuses those distinctions while preserving
Matter's immutable claims and independently verified association endpoints.
It does not copy civic SQL, normalization, machine-row retirement, automatic
crawler-stated merge authority or downstream code. No upstream test suite or
deployment was run.
