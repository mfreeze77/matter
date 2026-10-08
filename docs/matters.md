# Persistent matter identity and metadata

MAT-005 implements `matter.matters.MatterService` on the transactional storage
port. A continuing subject has an opaque persistent ID and one or more exact
keys declared by its adapter. A question, opportunity, or problem can be a
matter; creation requires no failure, severity, or lifecycle fields.

An observation can remain unassociated, and several assessment records can
refer to one matter. Creating a user-facing ticket is not an intake requirement.
Association decisions, assessment execution, lifecycle transitions, and guarded
identity changes retain their respective backlog tickets.

## Installed API example

Run the complete synthetic example from the checkout:

```bash
python examples/matter_identity.py
```

The example also runs after copying that file outside the checkout and installing
the wheel. It creates an opportunity, reopens storage, submits the same subject
with a new run and proposed ID, revises its wording, reads both revisions, and
verifies exact command replay after backup/restore. Its actor and authority
references are explicitly synthetic host inputs, not authentication machinery.

For a host that already builds valid command envelopes:

```python
from matter.identity_keys import ExactIdentityPolicy, new_matter_id
from matter.matters import MatterService
from matter.storage import SQLiteStore

policy = ExactIdentityPolicy(key_namespaces=["example:subject"])
with SQLiteStore("matter.sqlite", scope_id="example:workspace") as store:
    subjects = MatterService(store, identity_policy=policy)
    # Allocate once while constructing the command, before preparation.
    command["body"]["matter"]["id"] = new_matter_id()
    command["body"]["identity_policy"] = policy.reference
    prepared = subjects.prepare(command)
    result = subjects.create(prepared)
    current = subjects.resolve([
        {"namespace": "example:subject", "value": "subject-17"},
    ], domain_kind="example:opportunity")
```

`command` must be a complete `create_matter` envelope, as shown in the standalone
example and the [command contract](contracts/schema-inventory.md). The host must
persist its prepared command for recovery. `new_matter_id()` supplies UUID4
values; other valid opaque host-proposed IDs remain supported. The service
never allocates an ID during preparation, handler execution, or retry.

## Identity policy and exact keys

The identity tuple is `(scope_id, key.namespace, key.value)`. The record's
namespace and opaque ID identify the stored matter; the adapter-owned key
namespace identifies a continuing subject in the adapter's external system.
`domain_kind` is immutable subject metadata. Reusing a key with a different
domain kind is a conflict, not a second domain-specific key space.

`ExactIdentityPolicy` requires a nonempty, unique set of allowed key namespaces.
Its component reference binds the complete canonical configuration and the
`matter.exact-subject-keys.v1` algorithm. Creation must name that exact configured
reference. Unsupported references or undeclared namespaces are
`E_POLICY_INVALID`; duplicate or malformed keys are `E_SCHEMA_INVALID`.

Keys are exact strings within the core identifier contract. The service does
not case-fold, trim, remove delimiters, or normalize Unicode. Canonical structured
framing prevents delimiter collisions between scope, namespace, and value.
Adapters that normalize domain identifiers must define and apply their own
versioned convention before submission. The core does not infer that a string
is a durable real-world identifier: the host's namespace declaration makes that
responsibility explicit.

Titles, descriptions, processing run IDs, purposes, audiences, and policy or
assessment versions never supply fallback identity. Two different exact keys
can therefore create two matters with the same title. A later command with the
same declared key can resolve one matter despite a different proposed ID, run,
or title.

## Creation and conflict outcomes

`prepare()` validates the envelope and scope, takes one storage snapshot, and
adds current key-index and matter pins without replacing caller-supplied pins.
It also pins any existing occupant of the proposed ID across record types and
retains explicit provenance-parent dependencies. A journaled command is only
accepted unchanged; preparation does not rebuild it against newer state.

`create(prepared)` then executes under one checked writer transaction:

| Existing state | Result |
|---|---|
| All supplied keys unbound, proposed ID free | `created`; one matter, all key projections, and the command receipt commit together |
| All supplied keys already bind to one matter of the same domain kind, proposed ID free or that same matter | `existing`; return its current revision without changing its keys, metadata, history, or creation receipt |
| A supplied key names several matters, or supplied keys disagree on the target | `E_SOURCE_IDENTITY_CONFLICT`; no winner or merge is selected |
| Some supplied keys are bound and others unbound | `E_SOURCE_IDENTITY_CONFLICT`; no implicit key or alias expansion |
| Proposed ID is occupied by a different matter, observation, projection, or other record | `E_SOURCE_IDENTITY_CONFLICT`; an occupied proposal is not silently discarded |
| A bound subject has a different `domain_kind` | `E_SOURCE_IDENTITY_CONFLICT` |
| Initial input supplies `lifecycle` or `supersedes` | `E_POLICY_INVALID`; creation cannot perform transition or replacement decisions |
| Required current record or key-index pin changed or was omitted | `E_REVISION_CONFLICT`; caller must make a fresh decision under a new command identity |

Supplying an already-bound subset of a matter's keys is valid. The existing
full key set remains unchanged. Every existing candidate is checked against its
current record and declared keys; an absent, mistyped, or inconsistent target,
or a malformed index, is `E_STORAGE_UNAVAILABLE`. Corrupt persistence must not
become a false absence or a partially successful candidate list.

Ordinary semantic failures returned by execution are journaled with no child
writes. Invalid wire envelopes raise `ContractError` before execution. Read-only
preparation can itself raise `StorageError` for invalid scope or keys, an
idempotency conflict, or index-integrity failure. Use the exact saved command to
recover an outcome; use a new command ID and idempotency key for revised inputs.
This remains true if the first response was lost after commit.

## Revisioned display metadata

The additive `update_matter_metadata` operation accepts a pinned matter and a
closed metadata object:

```json
{
  "matter": {
    "scope_id": "example:workspace", "namespace": "example",
    "record_type": "matter", "id": "an-opaque-persistent-id", "revision": 1
  },
  "metadata": {
    "title": "A clearer title",
    "description": "Reworded description of the same continuing subject"
  }
}
```

This is the body inside the normal command envelope. `metadata` is a complete
replacement of only `body.title`, `body.description`, and top-level `extensions`.
An omitted field is cleared; `{}` clears all three. Unknown namespaced extensions
remain inert schema-bound data when supplied. To retain an extension in a later
edit, include it in that replacement.

Use `subjects.update_metadata(subjects.prepare(command))`. The body pin is a
precondition: preparation preserves a stale pin instead of refreshing it to a
newer title. Changed metadata produces `updated` and exactly one new immutable
matter revision. Equal metadata produces `unchanged`, with no new matter version.
Both outcomes have their own command receipt. An exact retry returns the original
result even after subsequent metadata edits.

Scope, ID, namespace, domain kind, identity keys, lifecycle, original provenance,
supersession references, and the original creation receipt remain byte-for-byte
equivalent as values. The metadata command's actor, authority, input, and read
set live in its operation journal. `store.history(ref)` preserves previous
descriptions; `store.receipt_for(pin)` finds the command that committed a version.
An edit with a stale or missing target dependency receives
`E_REVISION_CONFLICT`, including a no-op submitted against a stale revision.

## Reads, indexes, and scope

`resolve(keys, domain_kind=None)` returns the full current matter snapshot or
`None` if every supplied key is unbound in this service's scope. A mixed
bound/unbound query, ambiguous mapping, or requested domain mismatch raises
`E_SOURCE_IDENTITY_CONFLICT`. Reads make no writes or receipts.

Each key is a schema-bound projection in `matter.identity_keys`, addressed by
`identity_key_ref(scope_id, key)`. The value contains its scope, original exact
key, and unique bare matter references. Its descriptor hashes the packaged
[`matter-identity-key.schema.json`](../schemas/matter-identity-key.schema.json).
Bare references keep the binding stable while the matter's metadata revisions
advance. A valid ambiguous binding can represent several candidates explicitly;
the service refuses to choose among them.

The service reserves `matter.identity_keys`, `matter.observations`, and
`matter.storage` as proposed matter-record namespaces. Its reads use the
scope-bound storage port, including the current cross-kind `lookup_identity`
check; no SQL queries or run-local authoritative maps live in the service.
Another scope can use the same key for an independent matter. Foreign actor,
authority, target, parent, or expected references are refused, and error
references remain scoped. Cross-scope grants are not implemented by this port;
an external reference or model judgment cannot provide such authority.

The index is a durable projection with the same atomic command boundary as the
matter. Competing first creators cannot both publish the same key: the stale
writer must receive a revision conflict and issue a fresh command to obtain the
existing identity. Competing metadata edits similarly cannot lose one another's
updates. Database backup/restore retains matters, key bindings, all versions,
and exact command results together.

## Reuse and acceptance

The implementation inspected `vnorm`, `Matters.find`, `Matters.matter`, and
`Matters.retitle` in the ticket-pinned
[StateCivics source](https://github.com/mfreeze77/state-civics-ai/blob/a34fcec27f353187e7a23d54788b203d13ac87c1/services/local-accountability/sar_tracker/core_import/matters.py).
The reusable ideas are persistent opaque IDs, zero/one/many key resolution, and
preserving identity while descriptions change. Its whitespace-removing uppercase
normalization, civic key schemes, placeholder-title rules, automatic identifier
expansion, reviewed joins, redirects, and retirement logic stay out of the
neutral core. No code or deployment in the source repository was changed.

The [MAT-005 validation receipt](validation/MAT-005.md) maps executed continuity,
scope, conflict, metadata, concurrency, crash, packaging, and restore checks to
the ticket's acceptance criteria. These establish the exact-key reference
implementation on local SQLite. Semantic clustering, association (MAT-008),
guarded merges and identity repair (MAT-009), assessment execution (MAT-015),
lifecycle (MAT-017), and purpose/audience engines (MAT-018) remain separate work.
