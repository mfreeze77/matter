# Immutable observation intake

MAT-004 implements ordinary source-data intake on the [MAT-003 storage port](storage.md).
Its public modules, payload implementation, and source-index schema ship in the
installed Python package. Source observations remain independent of matters and
occurrences until a later operation associates or groups them.
The [MAT-004 validation receipt](validation/MAT-004.md) records executed
acceptance tests, installed-package checks, and the qualification boundary.

## Public API

```python
from matter.observations import ObservationIngestor, source_index_ref
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore

payloads = FilePayloadStore("./payloads", scope_id="my-scope")
with SQLiteStore("./matter.sqlite", scope_id="my-scope") as store:
    intake = ObservationIngestor(store, payloads)
    prepared = intake.prepare(command)  # Valid ingest_observation envelope.
    result = intake.ingest(prepared, payload=original_bytes)
    # Retain prepared, including its expected_revisions, for exact retries.
```

The host supplies an authorized scope, actor, and authority reference. As with
the underlying storage port, these are host admission inputs, not credentials
that this module authenticates. The observation, command, payload handle, and
all locally read references must belong to that scope.

The [complete executable example](../examples/observation_intake.py) constructs
a synthetic command, commits bytes, redelivers the event, appends a correction,
queries both knowledge boundaries, and verifies restart continuity. It uses no
fixture files, credentials, external service, or repository-only import.

## Command retries and source redelivery

Two identities answer different questions:

| Identity | Meaning | Result |
|---|---|---|
| Scope plus command idempotency key, checked against the entire canonical command | Is this the exact same attempted operation? | Replay its saved result before dependency or payload checks. Changed content with that key returns `E_IDEMPOTENCY_CONFLICT`. |
| Scope plus source namespace plus event ID, with an optional explicit revision ID | Has this declared source evidence already been committed? | A new command can return `duplicate` with the original observation pin and creation receipt. Incompatible evidence requires a correction or returns `E_SOURCE_IDENTITY_CONFLICT`. |

`prepare` validates the command and reads the source index and prior observations
in one consistent snapshot. It adds exact dependency pins and retains every
caller-supplied pin without replacing stale pins with current ones. Explicit
parent and supersession pins are also included. Missing or stale dependencies
produce a durable revision refusal during execution. Foreign-scope preparation
fails before those records are read.

Preparation is read-only. Save its returned command before execution and retry
that exact value after a timeout or uncertain storage outcome. Calling `prepare`
on an already journaled command returns it only when it still matches the saved
command exactly; it cannot silently rebuild a historical operation against a
new index. When a source index changes between preparation and execution, the
loser receives `E_REVISION_CONFLICT`. To act on the new state, begin a new command
with new command and idempotency IDs, then prepare that command.

Source redelivery uses a new command identity. Changing delivery metadata while
reusing an old idempotency key is still a command conflict. A duplicate creates
an operation receipt for the new delivery, with no new observation or projection
revision. Its success body contains:

- `observation`: the exact original immutable observation pin;
- `observation_receipt`: that observation's original `creation_receipt`.

The result's top-level `receipt` identifies the current command's operation
receipt. An exact command retry returns the exact saved result, including both
receipt roles. The new body field is optional in the structural schema for old
journals, but always emitted by this handler. Earlier closed-schema consumers
need the updated result schema; see [compatibility](contracts/compatibility.md).

## What counts as unchanged evidence

The canonical command journal uses the complete command digest from MAT-002.
The source index separately records an evidence-comparison digest and the
SHA-256 digest of exact original payload bytes. The evidence digest uses
`matter-json-v1` framing with kind `observation.evidence.v1`.

The following delivery fields are excluded from evidence comparison:

- the proposed observation ID and record namespace;
- `provenance.recorded_at` and `provenance.run_id`;
- `body.ingested_at`;
- `body.content.availability.checked_at`.

Everything else in the declared observation evidence participates, including
scope, source identity and revision, exact byte digest, locator, optional byte
length, media type, availability status/reason, occurrence and publication
times, earliest `available_at`, producer, extraction descriptor, pinned parents,
supersession, and optional namespaced extensions. Arrays retain their order.
Command delivery metadata does not alter the source comparison.

`available_at` is earliest evidenced availability to the system or replay corpus;
it is not the latest transport timestamp. Changing that assertion or an evidence
locator is a declared evidence change and requires an explicit revision or
correction. Unknown occurrence, publication, and availability times remain
unknown, with their reasons preserved. Intake never fills them from wall time.

This applies the unchanged-evidence discipline inspected in the ticket-pinned
[StateCivics intake implementation](https://github.com/mfreeze77/state-civics-ai/blob/a34fcec27f353187e7a23d54788b203d13ac87c1/services/local-accountability/sar_tracker/core_import/matters.py):
unchanged evidence retains its prior citation and causes no evidence write. The
implementation uses Matter's strict canonical encoding and storage port; it
does not import civic logic or complete-snapshot retirement into incremental
intake.

## Conflicts, source revisions, and corrections

An incompatible submission for an already bound source revision returns
`E_SOURCE_IDENTITY_CONFLICT`. Its attempted command, command digest, explicit
failure, original observation dependencies, and operation receipt remain in the
storage journal. `store.command_receipt(key)` retrieves that audit after restart.
The original record, payload reference, availability, and source-index revision
remain unchanged. Raw conflicting bytes are not required to be retained; their
declared digest and submission metadata are retained in the attempted command.

There are two explicit ways to introduce new evidence:

1. Supply a distinct `source_identity.revision_id` and a new observation ID.
   Revision IDs are opaque. Their spelling, source publication dates, and commit
   order establish no automatic supersession or independent corroboration.
2. Supply a new observation ID and `supersedes` containing exact pins of
   existing observations in the same scoped source family. This can correct a
   source that has no revision IDs, or accompany a newly declared revision ID.
   Reusing a revision ID with changed evidence must explicitly supersede an
   observation bound to that revision; citing a different revision alone does
   not resolve the source-identity conflict.

A correction appends a new immutable observation and one source-index projection
revision in the same SQL transaction as its receipt. Its predecessor references
are the supersession records: there is no in-place rewrite or hidden retirement.
Duplicate predecessors, self-reference, wrong record kinds, foreign families,
and foreign scopes are refused. Every superseded observation must already occur
in the family history, so accepted append order cannot form a correction cycle.
A subsequent delivery of an earlier revision still resolves to that original
observation when its declared evidence is unchanged.

## Lineage and unassociated evidence

Adapters declare an observation's origin and exact producer/extraction versions.
A derived summary uses `provenance.origin = "derived"` with nonempty pinned
parents. Intake checks each declared parent's local scope and existence through
the transaction read set. Immutable parent pins remain exact; mutable parents
are subject to the storage port's current-revision check.

The declared lineage and extractor are preserved. A summary does not create an
extra occurrence, accepted claim, independent corroboration, or matter. Intake
does not classify raw text to detect a dishonest adapter's origin declaration.
Host instructions and stop signals still belong to the host's immediate control
path; text contained in an ordinary payload is only stored evidence.

## Payload bytes and availability

`PayloadStore` is a small port with a readable `scope_id`, `put(data: bytes)`
returning the exact SHA-256 digest, and `read(source_content)` returning a frozen
`PayloadRead(status, digest, data, reason)`. `FilePayloadStore` implements it
using scope-separated content-addressed files. It never follows a locator URI or
performs network retrieval.

For a new observation declared `available`, provide exact bytes to `ingest`, or
preload them using `payloads.put` and omit the payload argument. Digest and any
declared byte length must match; a mismatch returns `E_EVIDENCE_INVALID`. If
required local bytes are missing, intake returns `E_EVIDENCE_UNAVAILABLE` with a
durable failure receipt. A fresh command can later commit after bytes become
available; an exact retry of the refused command returns its original refusal.

An observation whose source digest is known may explicitly declare `unavailable`
or `withheld`, with a reason, and commit metadata without bytes. Supplying bytes
with those declarations is refused as inconsistent. A missing artifact with no
known digest cannot be invented as an observation; the core content contract
requires a real digest.

`intake.read_payload(observation_ref)` returns exact local bytes when eligible
and present. Missing bytes return `status="unavailable"`; declared unavailable
or withheld references retain their reason without opening a blob. Corrupted
bytes or a length mismatch raise `E_EVIDENCE_INVALID`; filesystem failure raises
`E_STORAGE_UNAVAILABLE`. These results do not mutate the observation's historical
availability declaration. Source duplicates and exact command retries can return
the original evidence receipt even if its bytes are currently unavailable; use
the payload read API when current availability is required.

The file store publishes fully written blobs without replacing existing files,
verifies an existing blob on repeat publication, and keeps non-UTF-8 bytes intact.
Blob publication precedes the SQL evidence reference. A failed or interrupted
SQL command can leave an unreferenced immutable blob; garbage collection is
outside this ticket. The database's record/index/receipt mutation is atomic.

Payloads are intentionally outside SQLite's database-only backup. Back up or
retain the immutable scope payload directory alongside a database backup. A
restored database can use that retained directory; without it, its historical
records and receipts remain readable and payload reads report unavailable.
The reference file store is for a host-controlled local directory. Filesystem
permissions and durability assumptions follow the local operating system.

## Revision queries and knowledge boundaries

`intake.revisions(source_identity)` returns every committed immutable observation
in that source family, in commit order. A supplied `revision_id` does not narrow
the family. An empty list means no locally indexed observations, not complete
coverage or proof of absence.

`intake.revisions(source_identity, as_of=known_time)` includes only observations
whose known `available_at` is at or before the inclusive boundary. Unknown
availability remains visible in unfiltered history and ineligible for a dated
view. UTC timestamps compare at their exact precision through nanoseconds;
ingestion time and source publication time do not substitute for knowledge time.

`intake.heads(source_identity, as_of=known_time)` removes only predecessors that
are explicitly superseded by corrections eligible in that selected view. Before
a correction becomes available, the original can remain a head; after that
boundary, the correction can replace it in the selected head set while both
records remain in history. Unlinked explicit revisions can yield several heads.

The [internal source-index schema](../schemas/observation-source-index.schema.json)
binds the family key, original observation pins, evidence digests, payload
digests, and optional revision IDs. Its exact schema digest is recorded in each
projection. History reads validate the index against immutable records and fail
explicitly if its content cannot be verified.

This is a bounded source-history facility. MAT-010 still owns general temporal
dependencies, completeness, coverage, negative evidence, and retirement rules;
MAT-005 through MAT-007 own continuing matter identity, occurrences, and claims.
