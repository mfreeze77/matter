# Durable storage and revision-checked commands

MAT-003 implements a scoped persistence port and an embedded SQLite reference
backend in `matter.storage`. A trusted host supplies a validated command and a
short synchronous handler. The store checks the command's dependencies and
commits record versions, current heads, projection watches, an operation
receipt, and the exact result together.

The port establishes persistence guarantees for operation handlers.
[Observation intake](observations.md) implements source-event deduplication;
[matter identity](matters.md) implements scoped subject keys and metadata
revisions. Merge/undo semantics, negative-evidence interpretation, authenticated
controls, assessment execution, and external delivery retain their own tickets.
A storage receipt records a commit; it does not establish that the host's policy
or authority was correct.

## First transaction

The package includes its schemas and migrations, so the storage API works
outside a checkout. This example reads an existing synthetic command fixture
from the repository, then exercises the installed API:

```python
from pathlib import Path
from matter.contracts import decode_command
from matter.storage import SQLiteStore, entity_ref, pin

command = decode_command(
    Path("tests/fixtures/contracts/commands/create_matter.json").read_bytes()
)

def persist_synthetic_matter(tx):
    record = tx.insert(tx.command["body"]["matter"])
    return tx.success("created", {"matter": pin(record)})

with SQLiteStore("matter.sqlite", scope_id=command["scope_id"]) as store:
    result = store.execute(command, persist_synthetic_matter)
    assert result["status"] == "success"
    current = store.get(entity_ref(command["body"]["matter"]))
    assert current["revision"] == 1
    assert store.execute(command, persist_synthetic_matter) == result
    journal = store.command_receipt(command["idempotency_key"])
    assert journal["result"] == result
```

The synthetic handler deliberately performs only structural validation and
storage. Use [MAT-005's `MatterService`](matters.md) for exact subject-key
resolution and guarded metadata updates. A host must authenticate the caller,
authorize its scope, and apply its operation-specific rules before allowing
the corresponding writes.

## Transaction and retry semantics

`Storage`, `Transaction`, and `Snapshot` are Python protocols in
[`storage/base.py`](../src/matter/storage/base.py). `SQLiteStore.execute(command,
handler)` uses these boundaries:

1. Validate and defensively copy the command; calculate the existing
   `command.<operation>.v1` canonical digest.
2. Acquire the SQLite writer transaction with `BEGIN IMMEDIATE`.
3. Look up both `(scope_id, idempotency_key)` and `(scope_id, command_id)`.
   An identical command returns its original stored result without invoking the
   handler or checking today's revisions. Reusing either identity for different
   canonical content returns `E_IDEMPOTENCY_CONFLICT`.
4. Verify every declared dependency against the current stored head. Duplicate
   identities in the read set are invalid. A mutable snapshot's digest pin is
   checked against the current head, just like its revision pin.
5. Run the handler inside a savepoint. Each read of preexisting data through
   `tx.get`, `tx.lookup_identity`, or `tx.watchers` requires its declared current pin. An absent record
   can be checked and created under the same writer lock; a record created by
   this command can be read immediately without a nonexistent earlier pin.
6. For success, append all writes and their receipt. For a terminal semantic
   refusal, roll back the savepoint and append only the failure journal and
   operation receipt. Commit the whole transaction before returning.

The handler must use local, bounded storage work. Prepare provider results,
external reads, and expensive calculations before calling `execute`; declare
the stored dependencies on which that preparation relied. The port can check
reads through its transaction API, but Python cannot prevent a trusted handler
from consulting undeclared external state. External effects cannot be rolled
back by this store.

There is no automatic handler retry. After a recorded revision conflict or
policy refusal, a new attempt with changed inputs needs a new command ID and
idempotency key. Retrying the previous command returns its previous refusal.
Nested operations on the same handle are refused; separate threads/processes
use independent operation connections. A transaction or snapshot object cannot
be reused after its context ends. Historical and journal queries belong to a
snapshot, avoiding an unchecked read route through the transaction interface.

## Records, identity, and history

An opaque ID is unique within `(scope_id, namespace)`, regardless of its record
kind. `record_type` is immutable identity metadata. Core records and internal
projections cannot reuse an existing identity to change its type. Commands have
their own scope-bound key and command-ID indexes because their wire envelope
does not declare a record namespace.

`tx.insert(record_input)` rejects caller-supplied `creation_receipt` and
`revision`, assigns the operation's receipt and initial revision where required,
then validates the completed core record. `tx.replace(full_record)` accepts
only mutable kinds, requires the exact next revision, and preserves the original
creation receipt. An identity can be written once per command. Immutable core
records require a new identity for a correction; they cannot be overwritten.

Every version is stored as canonical bytes with its kind-bound digest. Current
heads point to those versions. Journal and version rows are append-only, with
database constraints for scoped identities, revision ordering, and the atomic
command/receipt relationship. Reads validate stored JSON, identity, revision,
and digest; a broken snapshot produces an explicit storage error.

| Read API | Meaning |
|---|---|
| `store.get(entity_ref)` | Current snapshot of the readable identity with the requested kind |
| `store.get(pinned_ref)` | Exact historical revision or digest snapshot |
| `store.lookup_identity(entity_ref)` | Current occupant of the scoped ID, across record kinds; bare references only |
| `store.history(entity_ref)` | All immutable snapshots in storage revision order |
| `store.receipt_for(reference)` | Operation receipt that committed the current or pinned snapshot |
| `store.command_receipt(key)` | Original command, canonical command digest, exact result, and full receipt |
| `with store.snapshot() as view` | One consistent read boundary across these queries and watch lookups |

`pin(snapshot)` returns revision pins for mutable records/projections and digest
pins for immutable records. `snapshot_digest(snapshot)` also supports digest
pins for mutable snapshots. A historical pin is suitable for reading history;
it cannot authorize overwriting a newer head.

`lookup_identity` was added with MAT-005 so a proposed matter or key-index ID
cannot conceal an existing occupant of another record kind. It uses
`(scope_id, namespace, id)` and returns the actual typed snapshot. Its supplied
`record_type` is the proposed kind, not a filter; absence is audited using that
bare reference. `tx.lookup_identity` requires the actual occupant's declared
current pin, exactly as `tx.get` does. It never discovers and adds an implicit
pin. An occupant appearing after preparation is a revision conflict. Ordinary
typed and historical `get` behavior is unchanged; the database format remains
version 1.

There is no delete or retention API in this ticket. History and result
pagination, projections for application queries, and explanation construction
remain MAT-023 and later operational work.

## Generic projections and watch registration

`tx.put_projection(reference, domain_value, watch_keys=())` creates or advances
a revisioned, schema-bound projection. Its reference uses the reserved external
kind `matter:projection`; its namespace and ID remain explicit. Updating an
existing projection requires its current pin in the command's expected read
set. Projection values retain their supplied schema descriptor and canonical
JSON without domain interpretation.

An internal projection has exactly these fields: `schema_version: "1.0"`,
`record_type: "matter:projection"`, `scope_id`, `namespace`, `id`, `revision`,
`creation_receipt`, `value` (a core `domain_value`), and unique `watch_keys`.
This is a storage format, not a thirteenth core record kind. Its digest uses
`projection.v1` framing. It cannot be exported as a core record through
`validate_record`.

Projections can retain alias targets, current assessment pointers, future
catalog or control state, and watch descriptors. Each exact opaque watch key
has a scoped reverse index. `store.watchers(key)` returns its current registered
projections; replacing a projection atomically replaces its registrations.
`tx.watchers(key)` additionally checks the returned preexisting projections'
pins. The writer transaction prevents another writer from inserting a phantom
registration during that command.

The storage port does not interpret identity or negative-evidence predicates.
[MAT-009](identity-corrections.md) builds verified identity groups and atomic
registered-validity hooks on this port. [MAT-010](time-coverage.md) adds source
catalogs, explicit coverage and direct negative-scope invalidation using the
same checked reads, watches and atomic journal. Catalog admission revisions
verify frozen populations without a historical-read bypass inside transactions.
MAT-016 retains transitive invalidation responsibilities. Storage restore tests prove that
values and registrations survive; each domain service has separate behavioral
acceptance evidence.

## Receipts and explicit failures

An operation receipt is an ordinary immutable core receipt in the reserved
`matter.storage` namespace. Its ID is derived from the full canonical command
digest. It self-references its creation receipt by bare ID, avoiding a digest
cycle. New records and successful results reference the same receipt; mutable
replacement snapshots retain their initial creation receipt while version
metadata identifies the new operation receipt.

An ingest result may also identify an existing observation's creation receipt
in `body.observation_receipt`. For a duplicate submitted under a new command,
that body field retains the original observation receipt while the top-level
`receipt` names the newly journaled command's receipt. The storage check that
a successful result references its own command receipt remains unchanged.

Receipt evidence includes verified durable read pins and committed write pins.
A failed command never cites its rolled-back children as committed evidence.
Its details bind the command digest, result digest, declared read set, absent
reads, exact watch queries, and committed writes. The descriptor hashes the
exact packaged [`storage-receipt-details.schema.json`](../schemas/storage-receipt-details.schema.json)
bytes. Producer provenance hashes a manifest of the installed storage source
and migration resources. Result digests use `result.<operation>.v1` framing.

The public failure schema has no receipt field. A durable failure receipt is
available through `command_receipt`, alongside the exact failed result. Raised
and returned failures both filter affected references to the handle's scope.
The host must still supply safe custom details and authenticate that scope.

| Condition | Observable behavior |
|---|---|
| Invalid wire command | `ContractError` before executing or journaling |
| Identical committed retry | Original result and receipt identity; handler does not run |
| Changed command using an old ID or key | `E_IDEMPOTENCY_CONFLICT`; original journal unchanged |
| Stale or omitted current read pin | Durable `E_REVISION_CONFLICT`, with no child mutations |
| Invalid handler result or ordinary semantic refusal | Durable failed result after rolling back all attempted writes |
| Writer lock or commit timeout | `E_STORAGE_UNAVAILABLE`; active transaction is rolled back and its connection discarded |
| Failure after commit but before the reply is established | `E_STORAGE_UNAVAILABLE` or process interruption; exact retry recovers the original committed outcome |
| Missing readable identity in healthy storage | `StorageError` with `E_NOT_FOUND` |
| Missing database file, failed query, or damaged snapshot | Explicit storage error; never an empty successful query |
| Unexpected Python handler exception | Exception propagates after rollback; no invented operation result |

An unavailable result does not prove that no commit happened. Retrying the
original command is the recovery mechanism. The store never journals a
fabricated success or an outage result as a completed application decision.

## SQLite configuration and migrations

Each connection uses explicit SQL transaction control (`isolation_level=None`),
`journal_mode=DELETE`, `synchronous=EXTRA`, and `foreign_keys=ON`; the required
settings are read back and verified. Python 3.11 and 3.12 share this code path.
The lock timeout defaults to five seconds and accepts zero through sixty.
An existing handle reopens with `mode=rw`, so losing its file cannot silently
create an empty replacement database.

Rollback journaling permits concurrent readers, but a reader can delay a writer
at commit. A long snapshot may cause an explicit retriable storage failure.
Keep read contexts short. SQLite documents that `EXTRA` also synchronizes the
directory after deleting the rollback journal; this backend deliberately uses
that setting for durable commits. It does not expose a WAL mode option or depend
on which WAL fixes a Python distributor has backported. See SQLite's
[transaction rules](https://www.sqlite.org/lang_transaction.html),
[synchronization settings](https://www.sqlite.org/pragma.html#pragma_synchronous),
and [WAL version caveats](https://www.sqlite.org/wal.html#the_wal_reset_bug).

The database has an application ID (`MATT`), integer storage version, and a
ledger containing each migration's filename, exact-byte SHA-256, and application
time. Opening verifies the ledger and exact expected schema objects. A foreign
database is refused before its settings are changed. Unknown future versions
are explicit version errors; damaged metadata is not silently repaired.

Migration 1 initializes the current format. The runner supports verified known
prefixes and applies only missing sequential migrations under one writer lock.
Schema changes and all ledger/header markers commit together. Each complete
SQL statement is executed separately: Python's `executescript()` can implicitly
commit an enclosing transaction. Tests exercise both interrupted initialization
and a simulated version-2 upgrade that must preserve existing data on failure.
The shipped registry contains only version 1. See the
[migration runner](../src/matter/storage/migrations/__init__.py) and
[Python transaction documentation](https://docs.python.org/3.12/library/sqlite3.html#transaction-control).

## Backup and restore

```python
with SQLiteStore("matter.sqlite", scope_id="synthetic:mat002") as store:
    backup = store.backup_to("matter-backup.sqlite", copy_timeout=30)

with SQLiteStore.restore_from(
    backup, "matter-restored.sqlite", scope_id="synthetic:mat002",
    timeout=5, copy_timeout=30,
) as restored:
    saved = restored.command_receipt("idempotency-create_matter")
    assert saved["result"]["status"] == "success"
```

Both destinations must be new files in existing parent directories. Restore
never replaces a live database. Backup and restore are database-owner operations
that copy all stored scopes; the host controls who may invoke them. The copy has its own positive deadline
(`copy_timeout`, default five seconds), separate from a handle's lock timeout;
a zero-lock-wait handle can still back up normally.

The helper uses SQLite's [online backup API](https://www.sqlite.org/backup.html)
with a stable read snapshot. It verifies schema/ledger, database integrity,
foreign keys, and table counts before publishing the staged destination with a
no-overwrite filesystem operation. It synchronizes the file and, where the OS
supports it, its directory. An existing destination, including one created
during publication, is never overwritten. A failure after publication but before
directory synchronization is confirmed may leave the complete new file while
returning an error. The helper does not delete a published path on that basis.

The deadline bounds SQL progress and lock waits, not a filesystem syscall
already blocked in the operating system. The local filesystem must implement
the locking and synchronization SQLite requires; this is an embedded backend,
not a network filesystem or distributed consensus qualification. Process-death
tests do not substitute for physical power-loss testing.

## Reuse and acceptance

The implementation inspected
[`CognitionStore.transaction` and `RunStore.commit` in Oil](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/cognition_store.py)
at the ticket's pinned source revision. It reuses the transaction/read-version
design: freeze requests, check prior keys before current reads, and commit
history and projections together. The neutral port does not import Oil state
classes or run-scoped identity. It returns the original result on retry and
adds atomic migration markers and commit-failure cleanup.

The [MAT-003 validation receipt](validation/MAT-003.md) maps executed tests to
the ticket's three acceptance criteria. Fault tests include actual process
termination before receipt, before commit, and after commit; competing writer
processes; lock contention; and interrupted migrations. All examples and
handlers are synthetic. No downstream repository, provider, transport, or
deployed system is part of this qualification.
