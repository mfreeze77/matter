# Occurrences and evidence dependence

MAT-006 implements `matter.occurrences.OccurrenceService` and
`matter.provenance_groups` on the existing transactional storage port. The
service records a host's accepted grouping of immutable observations into
identified happenings and preserves the reasons evidence may be dependent.

| Quantity | Meaning | What does not establish it |
|---|---|---|
| Observation | One retained source report, log, summary, requirement, or other evidence record | A new delivery of the same source revision |
| Occurrence | A happening identified by adapter execution/event keys | Different wording, a different payload digest, or one more report |
| Provenance group | An explicit root evidence-dependence declaration inherited by derived reports | A new execution, a summary, or an assertion of independent corroboration |

A log and a report can be two observations of one execution. Identical
diagnostics under a new execution key can describe another occurrence while
remaining in the same declared provenance group. A standing requirement need
not describe an occurrence. One source or summary can describe several.

The complete synthetic example runs from an installed package:

```bash
python examples/occurrence_grouping.py
```

## Configure a scope and explicit policy

```python
from matter.occurrences import ExactGroupingPolicy, OccurrenceService, new_occurrence_id
from matter.storage import SQLiteStore

policy = ExactGroupingPolicy(
    key_namespaces=["example:execution"],
    group_namespaces=["example:lineage"],
)
with SQLiteStore("matter.sqlite", scope_id="example:workspace") as store:
    service = OccurrenceService(store, grouping_policy=policy)
    proposed_id = new_occurrence_id()
    policy_reference = policy.reference
```

The host supplies authentication, scope authority, and truthful adapter key
semantics. An allowed namespace is a host declaration, not proof of real-world
identity or independence. The policy is immutable; its reference binds the
complete versioned configuration, including membership set semantics and the
4,096-reference limit for a lineage resolution. Returned configuration and
references are detached copies.

Keys are exact structured `(scope_id, namespace, value)` identities. There is no
case folding, whitespace trimming, delimiter splitting, Unicode normalization,
similarity matching, or digest fallback. Unlike a continuing matter key, an
execution key intentionally distinguishes another happening. Allocate an opaque
occurrence ID before command preparation and retain it for retries.

Key, membership, and computed-group arrays have set semantics. Duplicate keys
or members in mutation input are refused; snapshots store unique values in
ascending Matter canonical JSON byte order. Reordering an otherwise identical
membership is a no-op. Command hashes still preserve the supplied array order:
reordered input is a different command, not an exact retry.

## Accept or correct grouping atomically

`commit_occurrence_grouping` uses the common command envelope: schema version,
command ID, idempotency key, scope, actor, authority receipt, expected revisions,
and this closed body:

```python
body = {
    "creates": [occurrence_input],
    "replacements": [
        {"occurrence": current_occurrence_pin, "observations": [observation_pin]},
    ],
    "provenance_assignments": [
        {
            "observation": root_observation_pin,
            "status": "declared",
            "group": {"namespace": "example:lineage", "value": "source-family-a"},
        },
    ],
    "grouping_policy": policy.reference,
    "basis": {"schema": host_basis_schema_reference, "value": host_review_basis},
}
prepared = service.prepare(command)
result = service.commit(prepared)
```

All five body fields are required; at least one of the three mutation arrays
must be nonempty. The [standalone example](../examples/occurrence_grouping.py)
supplies complete valid envelopes and records. A typed basis, actor, and
authority reference are retained in the command journal; a source's text cannot
issue this trusted host operation by containing control-like words.

An occurrence input uses the existing core schema: namespaced `kind`, one or
more execution/event `identity_keys`, zero or more pinned `observations`, and
exactly one of `occurred_at` or `occurred_interval`. Unknown time is explicit.
The required `provenance_groups` input is an empty placeholder. The host computes
its stored value from verified report lineage and declarations. A caller cannot
inject an unsupported group through an occurrence input.

`occurrence.body.observations` is the authoritative accepted membership. A
replacement supplies its complete new list, including an empty list when
appropriate. It preserves occurrence ID, keys, kind, time, original provenance,
extensions, and creation receipt. It appends a new occurrence revision only
when membership or resolved provenance dependencies change. An empty historical
shell remains readable, and counts over reports omit it.

To split a mistaken grouping, replace the old occurrence's membership and
create another occurrence for the newly distinguished execution in the same
command. The original observation snapshots and payloads remain unchanged.
Several replacements, creations, and root assignments commit with the same
operation receipt or none do. A target may appear only once in the batch.

An exact event-key hit can return an existing occurrence only when its complete
key set, kind, time, membership, and extensions match the proposal. It preserves
the existing identity and original provenance. Changed membership requires an
explicit replacement. Mixed bound/unbound keys cannot add aliases; keys naming
multiple targets, occupied proposed IDs, and conflicting event details are
explicit conflicts. Key rebinding and occurrence identity merging are outside
this operation.

Success has outcome `committed` or `unchanged` and a closed result body:

- `occurrences`: current pins of every affected occurrence, including those
  reached through provenance corrections.
- `previous`: old pins of the existing occurrences that actually received
  another revision. It is empty for `unchanged`.
- `provenance_assignments`: current pins of all root-assignment projections
  supplied by the command, including unchanged declarations.

Every new valid command receives its own operation receipt, even for a no-op.
`store.history(ref)` retains occurrence and assignment revisions;
`store.receipt_for(pin)` identifies the command that committed a revision. The
original creation receipt remains in each continuing record.

## Preserve evidence dependence and unresolved lineage

A root observation can receive exactly one declared group or an explicit
unknown declaration:

```python
{"observation": root_pin, "status": "unknown", "reason": "source_chain_not_verified"}
```

A root has no parents and is not declared `derived` or `evaluator`. There is no
automatic default group for an unassigned root. An explicitly unknown root
retains its reason and assignment revision. A group label declares dependence;
two different labels do not by themselves establish statistical or substantive
independence.

Any observation with parents inherits the union of its observation parents'
resolved groups, even if its origin was mislabeled as a source. It cannot
receive a root assignment. A summary of groups A and B inherits `{A, B}`: it
does not create C and does not collapse A and B into one group. Transitive
summaries retain the same rule.

Lineage follows pinned observation parents only. A non-observation parent is
retained as `non_observation_parent`; the resolver does not reinterpret a
judgment, assessment, or receipt as an original source. Missing ancestor
evidence is `missing_parent`. Roots can be `unassigned_root`, `unknown_root`, or
`non_source_root`. An unresolved entry identifies its observation, reason, and
when applicable its exact parent or the host's unknown reason. Known groups may
coexist with unresolved lineage, yielding partial provenance coverage.

A missing directly requested observation remains an error. Cross-scope lineage
is forbidden, detected cycles are invalid evidence, exceeding the bounded
lineage budget is `E_BUDGET_EXHAUSTED`, and storage failures propagate. None of
these failures produces a successful zero count.

Correcting a root assignment atomically refreshes every dependent occurrence,
including those containing only transitive summaries. The occurrence revision
also changes when an unknown reason or dependency pin changes while the visible
group set remains equal. This preserves the revised basis of the projection.
Unrelated occurrences and immutable reports remain untouched.

## Count an explicit report cohort with coverage

```python
report = service.counts(
    [log_pin, derived_report_pin],
    coverage={"status": "complete", "snapshot": source_selection_reference},
)
assert report["counts"] == {
    "observations": 2, "occurrences": 1, "provenance_groups": 1,
}
```

`counts` requires the host's source-selection coverage. It preserves the core
coverage object exactly, including snapshot and reasons for partial, failed,
not-yet-expected, unpublished, or manual-review coverage. It queries one
consistent storage snapshot and counts distinct selected observations, current
occurrences with accepted direct membership from that selection, and the union
of groups resolved for those selected observations. Repeated identical input
pins count once; conflicting pins for one identity are refused.

Reports on the same occurrence but outside the selected cohort do not increase
its observation or provenance-group counts. Ancestors loaded to resolve lineage
do not increase observation count. An unassociated root can still have a
declared provenance group; association is not a prerequisite for evidence.

The report returns `observations`, `occurrences`, `provenance_groups`,
`unassociated_observations`, `unresolved_provenance`, source `coverage`, separate
`provenance_coverage`, and the verified `dependencies` used by the read. The
provenance coverage snapshot digest binds the selected lineage and declarations.
Complete source coverage can coexist with partial provenance coverage. An
empty or failed source selection cannot turn a zero into established absence.

`service.resolve(keys, kind=...)` returns a full current occurrence or `None`
for wholly unbound keys, with explicit conflict on partial or ambiguous hits.
`service.occurrences_for(observation_pin)` returns all full current occurrence
snapshots containing that report. These are current grouping queries;
historical group decisions remain accessible through stored versions and
receipts. A knowledge-time occurrence query is not introduced here.

## Transactions, watches, and persistence

Preparation reads one snapshot, retains caller-supplied pins, and adds every
verified dependency that the decision reads. It can refuse invalid inputs before
journaling. Commit uses only the storage port, checks current revisions, and
re-enumerates ancestry watches under the write transaction. A dependent added
after preparation causes a revision conflict; it cannot escape a provenance
correction. A concurrent root-assignment correction likewise invalidates a
prepared membership command.

After a conflict, make a fresh decision under a new command ID and idempotency
key. Retain and retry the exact old command to recover its original success or
durable refusal, including after later splits, restart, or acknowledgement loss.
The service never automatically reparses or refreshes a stale write.

The implementation reuses MAT-003's revisioned projections, exact watch keys,
atomic receipts, history, and SQLite recovery. It adds three packaged projection
schemas:

- [Exact occurrence keys](../schemas/occurrence-key.schema.json) use stable bare
  target references and preserve an explicit multi-candidate representation.
- [Membership projections](../schemas/occurrence-membership.schema.json) bind the
  current occurrence pin, provenance dependency pins, and a lineage digest.
  Their watches index direct membership and every traversed observation lineage.
- [Root assignments](../schemas/provenance-root-assignment.schema.json) retain
  one immutable observation pin and its versioned declaration.

Projection contents, schema digests, scope, actual typed occupants, dependency
pins, computed groups, and watches are verified on use. Inconsistent stored
grouping is invalid evidence, not absence. Built-in projection namespaces are
reserved. Database format and migrations remain unchanged. SQLite backup and
new-file restore include grouping records, indexes, assignments, and receipts;
payload bytes retain the separate backup boundary documented for observation
intake.

The [MAT-006 validation receipt](validation/MAT-006.md) records acceptance. The
bounded host grouping does not implement MAT-007 claim/evidence semantics,
MAT-008 semantic association proposals, or MAT-016 transitive assessment and
queued-delivery invalidation. It makes no acoustic, independence, source-truth,
causal, or live-provider qualification claim.
