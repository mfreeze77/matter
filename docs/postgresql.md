# PostgreSQL ledger and host payload integration — MAT-092

The optional `PostgreSQLStore` implements Matter's synchronous `Storage` port.
It shares command, canonical history, read guards, savepoints, observer behavior
and receipts with `SQLiteStore`. PostgreSQL owns transactions and scope locks;
SQLite retains its original file format, migrations and backup APIs. Actual
acceptance evidence is recorded in [MAT-092 validation](validation/MAT-092.md).

[Decision 0003](decisions/0003-permanent-host-storage.md) requires this permanent
ledger path **and host-backed payload persistence** before StateCivics production
activation. The SDK supplies no interim production mount or temporary
deployment/file-backup plumbing. Keep the existing SQLite rehearsal intact.

## Install and supply an owned connection

Install `matter-foundation[postgres]` for the psycopg 3 interface. The host
selects its system libpq, `psycopg[c]` or `psycopg[binary]` implementation; Matter
does not force bundled client libraries into the host. See
[psycopg installation choices](https://www.psycopg.org/psycopg3/docs/basic/install.html).
The backend admits
PostgreSQL 15–17. The host chooses the database, role and private lowercase schema;
there is no default DSN, environment lookup or implicit production connection.
`public`, `information_schema` and `pg_*` schema names are refused.

```python
import psycopg
from matter.storage import PostgreSQLStore

# Obtain dsn and authorized_scope from the existing host configuration/authority.
store = PostgreSQLStore(
    lambda: psycopg.connect(dsn, connect_timeout=5),
    schema="matter_place", scope_id=authorized_scope, timeout=5,
)
```

The factory supplies an **idle, exclusively leased synchronous connection** for
each operation. Matter temporarily selects autocommit for explicit transaction
control, then restores the original setting after rollback/commit and cleanup.
By default it closes the supplied connection. For a host-owned psycopg pool:

```python
store = PostgreSQLStore(
    pool.getconn, release=pool.putconn,
    schema="matter_place", scope_id=authorized_scope,
)
```

Matter does not own or close the pool. `release(connection)` receives the idle
connection, or a closed connection if cleanup failed, so the pool can replace
it. A factory that supplies an already active transaction is refused **before
ownership transfers**: Matter neither commits, rolls back, closes nor releases
that connection. The factory retains responsibility for this invalid lease.
Do not pass a caller's in-flight host transaction or a `pool.connection()`
context manager as the factory result. psycopg's normal connection contexts can
commit on exit; Matter instead needs explicit transaction ownership.
[Psycopg transaction behavior](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

The host bounds connection acquisition and provider/callback execution.
`timeout` is a database lock wait from zero through sixty seconds, not an
overall command deadline. Nested operations on one handle are refused; a held
snapshot/transaction expires when its context ends. A successful return means
the database commit completed. Failure after commit acknowledgment is lost
returns an unavailable/uncertain result; retry the **identical** command to
retrieve its durable outcome. Never automatically rerun the handler or assistant.

## Schema, transactions and coordination

The constructor initializes an empty private schema transactionally or verifies
the existing schema. `initialize=False` is a verification-only open: a missing
schema is refused, never interpreted as an empty ledger. Initialization is
serialized by a schema advisory lock. Schema version 1 stores canonical JSON in
`bytea`; database JSON rendering is not used for identity or content hashes.
Generated SHA-256 index keys allow long opaque identifiers without exceeding
PostgreSQL btree tuple limits. Lookups also compare the complete original text;
a hash collision can cause refusal but cannot substitute another identity.
The packaged SQL checksum and catalog manifest bind tables, columns, constraints,
indexes, trigger state and function bodies. An unknown manifest version is
unsupported; damage is an explicit storage failure. The host supplies a role
with the required schema/table/function permissions. SDK scope checks are not
a replacement for host authorization or database-role isolation.

Each writer uses a transaction-scoped advisory lock keyed by database-local
schema and Matter scope. It acquires the lock before reading the command journal
or dependencies. READ COMMITTED then sees the preceding writer's commit,
including a formerly absent identity or watch. Independent scopes do not share
that writer lock. Read snapshots use REPEATABLE READ, are read-only, and establish
their view on entry; a committed writer does not change an already-open snapshot.
These choices follow PostgreSQL's [lock lifetime](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS)
and [snapshot rules](https://www.postgresql.org/docs/17/transaction-iso.html).

Raw writes outside the SDK do not participate in its advisory-lock protocol.
The trusted host must not bypass command/dependency guards. Schema verification
does not turn an untrusted SQL writer into a permitted Matter actor.
Required settings include `fsync=on`, `full_page_writes=on`, UTF-8 server encoding
and normal trigger enforcement; transactions select `synchronous_commit=on`.

The internal scope lock ends with the database transaction. It does not cover
external assistant calls or atomically combine host and Matter commits. Keep the
existing durable claim/wake identity, per-lens exclusion across revisions and
matters, and explicit unknown-wake reconciliation. StateCivics must wire its
backend and worker to the same database/schema/scope and preserve any wider host
coordination needed around its workflow. No filesystem lock is supplied here.

## Host-owned payload persistence

`PayloadStore` remains the existing scope-bound `put(bytes)` / `read(content)`
port. A successful put durably publishes exact bytes before a ledger reference
is committed. A failed ledger command can leave an unreferenced host artifact;
it must not delete or rewrite another command's evidence. Reads respect declared
availability, current host access and exact digest/length checks.

StateCivics' required mapping is:

1. Locate the authorized packet row by `packet_hash`.
2. Reconstruct `canonical_bytes(row.exact_material)` using Matter's canonicaliser.
3. Derive `source_digest(bytes)` and verify that SHA-256 and byte length against
   the Matter content reference before returning any bytes.

`evidence_hash` hashes the packet identity object. It is not the payload digest.
Because the payload read port is digest-based, the host retains or derives a
scope-bound digest-to-packet association and verifies the reconstructed bytes;
matching a stored identity hash is insufficient. Raw model responses need
host-owned exact-byte artifacts keyed by payload digest. Missing, withheld,
foreign or changed bytes cannot become successful empty evidence.

The reusable [payload contract checks](../tests/payload_contract.py) run against
files and a [synthetic PostgreSQL host adapter](../tests/integration/host_payload_fixture.py).
That fixture demonstrates separate packet identity, canonical reconstruction,
raw response durability and explicit availability. It is test code, not the
StateCivics adapter, authorization implementation or a second evidence system.

## Recovery and compatibility

PostgreSQL backup/restore belongs to the host's permanent recovery arrangement.
There is no `backup_to` file API on this backend. Include the Matter schema,
host evidence/response artifacts, necessary sweep/review receipts and compatible
host records in one declared recovery set. Use an actual consistent database
dump/restore; schema checksums or matching row counts alone are insufficient.

After restoring into a separate target, open with `initialize=False` and call
`store.verify()`. This performs a consistent scoped ledger scan over canonical
versions, journal/result/receipt bindings, heads and watches and returns counts.
It checks each version against its owning command's committed write pins,
including operation-receipt ownership; foreign-key existence alone is insufficient.
It does **not** attest host payload availability, authorization, external artifact
recovery or physical power-loss safety. Verify those host dependencies and
pending/unknown review state before accepting the recovery set. The synthetic
[restore test](../tests/integration/test_postgresql_recovery.py) uses real
`pg_dump`/`pg_restore`, exact ledger bytes, host payloads, pending pressure and an
unknown wake; restoring it must not permit another assistant call.

The PostgreSQL migration registry is separate from SQLite's registry. This
backend does not import a SQLite database or silently upgrade stored meanings.
The SDK/image, schema/semantic versions, ledger and host payload recovery pins
must remain compatible. An older image is not a supported rollback merely
because custody moved to PostgreSQL. Preserve the original SQLite rehearsal;
any later import requires its own explicit evidence and authorization.

| SDK / persisted state | Support and recovery boundary |
|---|---|
| dev22 + SQLite schema 1 | Existing SQLite migrations and online-copy restore remain supported; the rehearsal stays intact. |
| dev22 + PostgreSQL schema 1 | PostgreSQL 15–17, synchronous psycopg 3 factory/lease; actual tested versions are in the validation receipt. |
| dev20/dev21 + PostgreSQL ledger | No PostgreSQL backend in those SDKs; selecting an older image is not a rollback procedure. |
| dev19 + dev20-or-later historical-context state | Not a supported downgrade. Recover compatible prior ledger, host records and payloads with the appropriate SDK/image pin. |
| Future PostgreSQL manifest version | Refused with `E_VERSION_UNSUPPORTED`; no implicit schema downgrade or speculative interpretation. |

Schema version 1 in these two backends does not denote interchangeable physical
formats. MAT-074 envelopes continue to enforce required features and semantic
fingerprints independently of the storage backend. Tests exercise those portable
vectors and dev20-era history behavior; they do not qualify arbitrary historical
SDK/image combinations. Python/driver/server combinations not recorded in the
validation receipt remain untested.

KS-1158 owns StateCivics storage integration, payload persistence, coordination
and associated receiving/recovery acceptance. Encryption remains KS-637/KS-1152
work; the production dispatcher and activation retain their separate host/owner
scope. Passing Matter software tests does not authorize activation or qualify a
provider, and the host SDK pin has not been changed by this implementation.

## Run the isolated conformance suite

Use an explicitly selected disposable synthetic database, never a rehearsal or
production DSN. The tests create and remove random `mat_test_*` schemas. The recovery and schema-name
cases also create and drops a separate random `mat_test_restore_*` database
inside the explicitly named test container (the schema-name case creates
short/quoted schema names only inside that disposable database); its synthetic test role needs
create/drop-database privileges. The full fault suite also disables internal
constraint triggers and changes replication-role settings, so it uses a
**disposable superuser test role** in these isolated synthetic databases.
Those privileges are not a production runtime-role requirement or recommendation.

```bash
python -m pip install -r requirements-postgres-test.txt
# Set MATTER_TEST_POSTGRES_DSN through the test environment.
python -m unittest discover -s tests -p 'test_postgresql*.py' -v
python -m unittest discover -s tests -p test_host_payload_conformance.py -v
```

The real dump/restore case additionally requires
`MATTER_TEST_POSTGRES_CONTAINER` naming an isolated `matter-mat092-*` test
container with PostgreSQL tools. An unset DSN or container produces an explicit
skip, not PostgreSQL acceptance. SQLite-specific file, PRAGMA and online-copy
tests remain on SQLite; shared transaction/guard/hook/history/review scenarios
run through the actual PostgreSQL constructor, with a canary that refuses to
count a scenario that never opened PostgreSQL.
