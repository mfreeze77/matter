"""SQLite reference backend: exact retries, checked reads, atomic receipts.

Connections are private to one operation and never shared across threads or
processes. Explicit transactions work on both Python 3.11 and 3.12. Durable
rollback journaling avoids depending on a particular distribution's WAL fixes.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable, Iterator

from .. import __version__
from ..canonical import canonical_bytes, canonical_digest, loads, source_digest
from ..contracts import (
    ContractError, command_digest, decode_command, decode_record, decode_result,
    error_result, validate_command, validate_record, validate_result,
)
from .base import (
    MUTABLE_RECORD_TYPES, PROJECTION_TYPE, STORAGE_NAMESPACE, CommandHandler,
    StorageError, _identity, _reference, _validate_fragment,
    _validate_projection, entity_ref, pin, snapshot_digest,
)
from .migrations import APPLICATION_ID, SCHEMA_VERSION, check_database, migrate


def _unavailable() -> StorageError:
    return StorageError("E_STORAGE_UNAVAILABLE", retriable=True)


def _rollback(db: sqlite3.Connection) -> None:
    # Closing below is the second cleanup boundary if the connection is broken.
    try:
        if db.in_transaction:
            db.rollback()
    except sqlite3.Error:
        pass


def _now() -> dict[str, str]:
    return {
        "state": "known",
        "value": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "precision": "microsecond",
    }


@lru_cache(maxsize=1)
def _components() -> tuple[dict[str, Any], dict[str, Any]]:
    root = files("matter.storage")
    implementation = {
        name: source_digest(root.joinpath(name).read_bytes())
        for name in ("base.py", "sqlite.py", "migrations/__init__.py", "migrations/001_initial.sql")
    }
    producer = {
        "namespace": "matter", "id": "sqlite-reference-store", "version": __version__,
        "digest": canonical_digest(implementation, "component.storage.v1"),
    }
    details_schema = {
        "namespace": "matter", "id": "storage-receipt-details", "version": "1.0",
        "digest": source_digest(files("matter._schemas").joinpath("storage-receipt-details.schema.json").read_bytes()),
    }
    return producer, details_schema


class _Snapshot:
    def __init__(self, store: SQLiteStore, db: sqlite3.Connection) -> None:
        self._store, self._db = store, db
        self._active = True

    def _ensure_active(self) -> None:
        if not self._active:
            raise StorageError("E_STORAGE_UNAVAILABLE", "This storage view is closed.")

    def _checked_ref(self, reference: dict[str, Any]) -> dict[str, Any]:
        self._ensure_active()
        pinned = type(reference) is dict and ("revision" in reference or "digest" in reference)
        result = _reference(reference, pinned=pinned)
        if result["scope_id"] != self._store.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        return result

    def _row(self, reference: dict[str, Any], *, current: bool = False) -> sqlite3.Row:
        ref = self._checked_ref(reference)
        args: tuple[Any, ...] = _identity(ref)
        if not current and "revision" in ref:
            row = self._db.execute(
                "SELECT * FROM versions WHERE scope_id=? AND namespace=? AND id=? AND version=?",
                (*args, ref["revision"]),
            ).fetchone()
        elif not current and "digest" in ref:
            row = self._db.execute(
                "SELECT * FROM versions WHERE scope_id=? AND namespace=? AND id=? AND digest=?",
                (*args, ref["digest"]),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT v.* FROM heads h JOIN versions v USING(scope_id,namespace,id,version) "
                "WHERE h.scope_id=? AND h.namespace=? AND h.id=?",
                args,
            ).fetchone()
        if row is None or row["record_type"] != ref["record_type"]:
            raise StorageError("E_NOT_FOUND")
        return row

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        try:
            value = (
                _validate_projection(loads(row["content"]))
                if row["record_type"] == PROJECTION_TYPE else decode_record(row["content"])
            )
            if (
                _identity(value) != (row["scope_id"], row["namespace"], row["id"])
                or value["record_type"] != row["record_type"]
                or value.get("revision", 1) != row["version"]
                or snapshot_digest(value) != row["digest"]
                or canonical_bytes(value) != row["content"]
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError, RecursionError):
            raise StorageError("E_STORAGE_UNAVAILABLE", "Stored snapshot integrity could not be established.") from None
        return value

    def get(self, reference: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._decode(self._row(reference))
        except sqlite3.Error:
            raise _unavailable() from None

    def history(self, reference: dict[str, Any]) -> list[dict[str, Any]]:
        ref = self._checked_ref(reference)
        try:
            # Fail explicitly on an unknown or mistyped identity, including empty DBs.
            self._row(entity_ref(ref), current=True)
            rows = self._db.execute(
                "SELECT * FROM versions WHERE scope_id=? AND namespace=? AND id=? ORDER BY version",
                _identity(ref),
            ).fetchall()
            return [self._decode(row) for row in rows]
        except sqlite3.Error:
            raise _unavailable() from None

    def watchers(self, watch_key: str) -> list[dict[str, Any]]:
        self._ensure_active()
        _validate_fragment(watch_key, "identifier")
        try:
            rows = self._db.execute(
                "SELECT namespace,id FROM watches WHERE scope_id=? AND watch_key=? ORDER BY namespace,id",
                (self._store.scope_id, watch_key),
            ).fetchall()
            return [self.get({
                "scope_id": self._store.scope_id, "namespace": row["namespace"],
                "id": row["id"], "record_type": PROJECTION_TYPE,
            }) for row in rows]
        except sqlite3.Error:
            raise _unavailable() from None

    def _journal(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            command = decode_command(row["command_json"])
            result = decode_result(row["result_json"])
            receipt_ref = {
                "scope_id": row["scope_id"], "namespace": row["receipt_namespace"],
                "record_type": "receipt", "id": row["receipt_id"],
            }
            # Bypass a transaction's declared-read wrapper for this internal read.
            receipt = self._decode(self._row(receipt_ref))
            if (
                command["scope_id"] != row["scope_id"]
                or command["command_id"] != row["command_id"]
                or command["idempotency_key"] != row["idempotency_key"]
                or command_digest(command) != row["digest"]
                or canonical_bytes(command) != row["command_json"]
                or canonical_bytes(result) != row["result_json"]
                or result["operation"] != command["operation"]
                or result["operation_id"] != command["command_id"]
                or receipt["body"]["operation_id"] != command["command_id"]
                or receipt["body"]["stage"] != "operation"
                or receipt["creation_receipt"] != receipt_ref
                or receipt["body"]["details"]["value"]["command_digest"] != row["digest"]
                or receipt["body"]["details"]["value"]["result_digest"]
                != canonical_digest(result, f"result.{command['operation']}.v1")
                or (result["status"] == "success" and result["receipt"] != receipt_ref)
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError, RecursionError):
            raise StorageError("E_STORAGE_UNAVAILABLE", "Stored command integrity could not be established.") from None
        return {"command": command, "command_digest": row["digest"], "result": result, "receipt": receipt}

    def command_receipt(self, idempotency_key: str) -> dict[str, Any]:
        self._ensure_active()
        _validate_fragment(idempotency_key, "identifier")
        try:
            row = self._db.execute(
                "SELECT * FROM commands WHERE scope_id=? AND idempotency_key=?",
                (self._store.scope_id, idempotency_key),
            ).fetchone()
            if row is None:
                raise StorageError("E_NOT_FOUND")
            return self._journal(row)
        except sqlite3.Error:
            raise _unavailable() from None

    def receipt_for(self, reference: dict[str, Any]) -> dict[str, Any]:
        try:
            row = self._row(reference)
            self._decode(row)
            journal = self._db.execute(
                "SELECT * FROM commands WHERE scope_id=? AND command_id=?",
                (self._store.scope_id, row["command_id"]),
            ).fetchone()
            if journal is None:
                raise _unavailable()
            return self._journal(journal)["receipt"]
        except sqlite3.Error:
            raise _unavailable() from None


class _Transaction(_Snapshot):
    def __init__(self, store: SQLiteStore, db: sqlite3.Connection, command: dict[str, Any], digest: str) -> None:
        super().__init__(store, db)
        self._command = command
        self._digest = digest
        self._receipt_ref = {
            "scope_id": store.scope_id, "namespace": STORAGE_NAMESPACE,
            "record_type": "receipt", "id": "command-" + digest,
        }
        self._expected: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._writes: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._verified_reads: list[dict[str, Any]] = []
        self._absent_reads: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._watch_queries: list[str] = []

    @property
    def command(self) -> dict[str, Any]:
        self._ensure_active()
        return deepcopy(self._command)

    @property
    def receipt_ref(self) -> dict[str, Any]:
        self._ensure_active()
        return deepcopy(self._receipt_ref)

    @staticmethod
    def _matches(reference: dict[str, Any], record: dict[str, Any]) -> bool:
        if entity_ref(reference) != entity_ref(record):
            return False
        if "revision" in reference:
            return reference["revision"] == record.get("revision")
        return reference.get("digest") == snapshot_digest(record)

    def _check_reads(self) -> None:
        for reference in self._command["expected_revisions"]:
            self._checked_ref(reference)
            identity = _identity(reference)
            if identity in self._expected:
                raise StorageError("E_SCHEMA_INVALID", "Expected revisions contain a duplicate identity.")
            self._expected[identity] = reference
        for reference in self._expected.values():
            try:
                record = self._decode(self._row(reference, current=True))
            except StorageError as exc:
                if exc.code != "E_NOT_FOUND":
                    raise
                raise StorageError("E_REVISION_CONFLICT") from None
            if not self._matches(reference, record):
                raise StorageError("E_REVISION_CONFLICT")
            self._verified_reads.append(reference)

    def get(self, reference: dict[str, Any]) -> dict[str, Any]:
        ref = self._checked_ref(reference)
        identity = _identity(ref)
        try:
            record = self._decode(self._row(ref, current=True))
        except StorageError as exc:
            if exc.code == "E_NOT_FOUND":
                self._absent_reads[identity] = entity_ref(ref)
            raise
        except sqlite3.Error:
            raise _unavailable() from None
        if identity not in self._writes:
            expected = self._expected.get(identity)
            if expected is None or not self._matches(expected, record):
                raise StorageError("E_REVISION_CONFLICT", "A current dependency pin is required for this read.")
        if ("revision" in ref or "digest" in ref) and not self._matches(ref, record):
            raise StorageError("E_REVISION_CONFLICT")
        return record

    def watchers(self, watch_key: str) -> list[dict[str, Any]]:
        _validate_fragment(watch_key, "identifier")
        self._watch_queries.append(watch_key)
        return super().watchers(watch_key)

    # The shared internal reader must not accidentally expose an untracked
    # read route through its public Snapshot-only methods.
    def history(self, reference: dict[str, Any]) -> list[dict[str, Any]]:
        raise StorageError("E_SCHEMA_INVALID", "Historical queries require a snapshot context.")

    def command_receipt(self, idempotency_key: str) -> dict[str, Any]:
        raise StorageError("E_SCHEMA_INVALID", "Journal queries require a snapshot context.")

    def receipt_for(self, reference: dict[str, Any]) -> dict[str, Any]:
        raise StorageError("E_SCHEMA_INVALID", "Historical receipt queries require a snapshot context.")

    def _writable_ref(self, reference: dict[str, Any]) -> None:
        self._checked_ref(reference)
        if reference["namespace"] == STORAGE_NAMESPACE:
            raise StorageError("E_SCOPE_FORBIDDEN", "The operation-receipt namespace is reserved.")
        if _identity(reference) in self._writes:
            raise StorageError("E_SCHEMA_INVALID", "A command may write an identity only once.")

    def _write(self, record: dict[str, Any], previous_version: int | None) -> None:
        identity = _identity(record)
        version = record.get("revision", 1)
        self._db.execute(
            "INSERT INTO versions(scope_id,namespace,id,record_type,version,digest,content,command_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (*identity, record["record_type"], version, snapshot_digest(record),
             canonical_bytes(record), self._command["command_id"]),
        )
        if previous_version is None:
            self._db.execute(
                "INSERT INTO heads(scope_id,namespace,id,record_type,version) VALUES(?,?,?,?,?)",
                (*identity, record["record_type"], version),
            )
        else:
            updated = self._db.execute(
                "UPDATE heads SET version=? WHERE scope_id=? AND namespace=? AND id=? AND version=? AND record_type=?",
                (version, *identity, previous_version, record["record_type"]),
            )
            if updated.rowcount != 1:
                raise StorageError("E_REVISION_CONFLICT")
        self._writes[identity] = deepcopy(record)

    def insert(self, record_input: dict[str, Any]) -> dict[str, Any]:
        self._ensure_active()
        if type(record_input) is not dict or {"creation_receipt", "revision"} & record_input.keys():
            raise StorageError("E_SCHEMA_INVALID", "Creation receipt and initial revision are assigned by storage.")
        record = {**deepcopy(record_input), "creation_receipt": self.receipt_ref}
        if record.get("record_type") in MUTABLE_RECORD_TYPES:
            record["revision"] = 1
        record = validate_record(record)
        reference = entity_ref(record)
        self._writable_ref(reference)
        if self._db.execute("SELECT 1 FROM heads WHERE scope_id=? AND namespace=? AND id=?", _identity(record)).fetchone():
            raise StorageError("E_SOURCE_IDENTITY_CONFLICT")
        self._write(record, None)
        return deepcopy(record)

    def replace(self, record: dict[str, Any]) -> dict[str, Any]:
        self._ensure_active()
        record = validate_record(record)
        if record["record_type"] not in MUTABLE_RECORD_TYPES:
            raise StorageError("E_REVISION_CONFLICT", "Immutable records cannot be replaced.")
        reference = entity_ref(record)
        self._writable_ref(reference)
        previous = self.get(reference)
        if record["revision"] != previous["revision"] + 1:
            raise StorageError("E_REVISION_CONFLICT", "Replacement must use the next revision.")
        if record["creation_receipt"] != previous["creation_receipt"]:
            raise StorageError("E_SCHEMA_INVALID", "Replacement must preserve the original creation receipt.")
        self._write(record, previous["revision"])
        return deepcopy(record)

    def put_projection(
        self, reference: dict[str, Any], value: dict[str, Any],
        *, watch_keys: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if type(watch_keys) not in (list, tuple):
            raise StorageError("E_SCHEMA_INVALID")
        ref = _reference(reference)
        self._writable_ref(ref)
        if ref["record_type"] != PROJECTION_TYPE:
            raise StorageError("E_SCHEMA_INVALID")
        old_head = self._db.execute(
            "SELECT record_type FROM heads WHERE scope_id=? AND namespace=? AND id=?", _identity(ref),
        ).fetchone()
        if old_head is not None and old_head["record_type"] != PROJECTION_TYPE:
            raise StorageError("E_SOURCE_IDENTITY_CONFLICT")
        previous = self.get(ref) if old_head is not None else None
        record = _validate_projection({
            "schema_version": "1.0", **ref,
            "revision": previous["revision"] + 1 if previous else 1,
            "creation_receipt": previous["creation_receipt"] if previous else self.receipt_ref,
            "value": value, "watch_keys": list(watch_keys),
        })
        self._write(record, previous["revision"] if previous else None)
        self._db.execute("DELETE FROM watches WHERE scope_id=? AND namespace=? AND id=?", _identity(ref))
        self._db.executemany(
            "INSERT INTO watches(scope_id,watch_key,namespace,id) VALUES(?,?,?,?)",
            [(ref["scope_id"], key, ref["namespace"], ref["id"]) for key in record["watch_keys"]],
        )
        return deepcopy(record)

    def success(self, outcome: str, body: dict[str, Any]) -> dict[str, Any]:
        self._ensure_active()
        return validate_result({
            "schema_version": "1.0", "operation": self._command["operation"],
            "operation_id": self._command["command_id"], "status": "success",
            "outcome": outcome, "receipt": self.receipt_ref, "body": body,
        })

    def _receipt(self, result: dict[str, Any]) -> dict[str, Any]:
        producer, details_schema = _components()
        recorded_at = _now()
        written = [pin(record) for record in self._writes.values()]
        evidence = {canonical_bytes(ref): ref for ref in [*self._verified_reads, *written]}
        return validate_record({
            "schema_version": "1.0", **self.receipt_ref,
            "creation_receipt": self.receipt_ref,
            "provenance": {"origin": "system", "producer": producer, "recorded_at": recorded_at, "parents": []},
            "body": {
                "stage": "operation", "operation_id": self._command["command_id"],
                "recorded_at": recorded_at,
                "outcome": "matter:" + (result["outcome"] if result["status"] == "success" else result["error"]["code"]),
                "evidence": list(evidence.values()),
                "details": {"schema": details_schema, "value": {
                    "command_digest": self._digest,
                    "result_digest": canonical_digest(result, f"result.{self._command['operation']}.v1"),
                    "read_set": self._command["expected_revisions"],
                    "absent_reads": list(self._absent_reads.values()),
                    "watch_queries": self._watch_queries,
                    "writes": written,
                }},
            },
        })


class SQLiteStore:
    """A durable database handle restricted to one host-authorized scope.

    timeout is a bounded lock wait in seconds (0 through 60). fault_hook is an
    explicit fault-test seam receiving transaction/migration stage names; normal
    applications leave it unset. No open connection survives a method call,
    except while a snapshot context or command handler is executing.
    """

    def __init__(
        self, path: str | Path, *, scope_id: str, timeout: float = 5.0,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._scope_id = _validate_fragment(scope_id, "identifier")
        if type(timeout) not in (int, float) or not 0 <= timeout <= 60:
            raise StorageError("E_SCHEMA_INVALID", "Lock timeout must be between zero and sixty seconds.")
        if not isinstance(path, (str, Path)) or str(path) in ("", ":memory:"):
            raise StorageError("E_SCHEMA_INVALID", "A durable filesystem database path is required.")
        if fault_hook is not None and not callable(fault_hook):
            raise StorageError("E_SCHEMA_INVALID")
        self._path = Path(path).absolute()
        self._timeout = float(timeout)
        self._fault_hook = fault_hook
        self._closed = False
        self._local = threading.local()
        try:
            # Only a new database receives new permissions. Never chmod or
            # truncate a caller's existing file, including an unsupported one.
            try:
                descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            db = self._open(initialize=True)
            db.close()
        except (sqlite3.Error, OSError):
            raise _unavailable() from None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def scope_id(self) -> str:
        return self._scope_id

    def __enter__(self) -> SQLiteStore:
        if self._closed:
            raise StorageError("E_STORAGE_UNAVAILABLE", "This storage handle is closed.")
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True

    def _fault(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    @contextmanager
    def _operation(self) -> Iterator[None]:
        if self._closed:
            raise StorageError("E_STORAGE_UNAVAILABLE", "This storage handle is closed.")
        if getattr(self._local, "active", False):
            raise StorageError("E_STORAGE_UNAVAILABLE", "Nested operations on one storage handle are not supported.")
        self._local.active = True
        try:
            yield
        finally:
            self._local.active = False

    def _open(self, *, initialize: bool = False) -> sqlite3.Connection:
        # mode=rw is deliberate: a removed or mis-mounted store must not become
        # a newly created empty database that reports no matching records.
        db = sqlite3.connect(
            self._path.as_uri() + "?mode=rw", uri=True,
            isolation_level=None, timeout=self._timeout,
        )
        db.row_factory = sqlite3.Row
        try:
            if initialize:
                application_id = db.execute("PRAGMA application_id").fetchone()[0]
                version = db.execute("PRAGMA user_version").fetchone()[0]
                existing = db.execute("SELECT 1 FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone()
                if application_id not in (0, APPLICATION_ID) or (application_id == 0 and (existing or version)):
                    raise StorageError("E_SCHEMA_INVALID", "This database is not an owned Matter storage format.")
                if application_id == APPLICATION_ID and version > SCHEMA_VERSION:
                    raise StorageError("E_VERSION_UNSUPPORTED")
            else:
                check_database(db)
            mode = db.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            db.execute("PRAGMA synchronous=EXTRA")
            db.execute("PRAGMA foreign_keys=ON")
            if (
                mode.lower() != "delete"
                or db.execute("PRAGMA synchronous").fetchone()[0] != 3
                or db.execute("PRAGMA foreign_keys").fetchone()[0] != 1
            ):
                raise StorageError("E_STORAGE_UNAVAILABLE", "Required durability settings are unavailable.")
            if initialize:
                migrate(db, fault_hook=self._fault_hook)
                check_database(db)
            return db
        except BaseException:
            _rollback(db)
            db.close()
            raise

    @contextmanager
    def snapshot(self) -> Iterator[_Snapshot]:
        """Hold one read snapshot; a long reader may delay a writer's commit."""
        try:
            with self._operation():
                db = self._open()
                view = _Snapshot(self, db)
                try:
                    db.execute("BEGIN")
                    # Establish the snapshot on entry, including an empty scope.
                    db.execute("SELECT version FROM heads WHERE scope_id=? LIMIT 1", (self.scope_id,)).fetchone()
                    yield view
                finally:
                    view._active = False
                    _rollback(db)
                    db.close()
        except (sqlite3.Error, OSError):
            raise _unavailable() from None

    def get(self, reference: dict[str, Any]) -> dict[str, Any]:
        with self.snapshot() as view:
            return view.get(reference)

    def history(self, reference: dict[str, Any]) -> list[dict[str, Any]]:
        with self.snapshot() as view:
            return view.history(reference)

    def watchers(self, watch_key: str) -> list[dict[str, Any]]:
        with self.snapshot() as view:
            return view.watchers(watch_key)

    def command_receipt(self, idempotency_key: str) -> dict[str, Any]:
        with self.snapshot() as view:
            return view.command_receipt(idempotency_key)

    def receipt_for(self, reference: dict[str, Any]) -> dict[str, Any]:
        with self.snapshot() as view:
            return view.receipt_for(reference)

    @staticmethod
    def _failure(command: dict[str, Any], exc: ContractError) -> dict[str, Any]:
        # A trusted handler may supply affected refs, but a scoped handle never
        # publishes refs to other scopes through the public failure envelope.
        references = tuple(
            reference for reference in getattr(exc, "affected_references", ())
            if type(reference) is dict and reference.get("scope_id") == command["scope_id"]
        )
        return error_result(
            command["operation"], command["command_id"], exc.code,
            retriable=getattr(exc, "retriable", False),
            affected_references=references, detail=exc.detail,
        )

    def execute(self, command: dict[str, Any], handler: CommandHandler) -> dict[str, Any]:
        """Atomically execute or replay a command; never retry the handler here.

        A handled semantic refusal is durable with no child writes. Unexpected
        Python exceptions propagate after rollback. Any persistence failure
        returns E_STORAGE_UNAVAILABLE; after a lost commit acknowledgement the
        caller must retry the original command to discover its durable outcome.
        """
        command = validate_command(command)
        digest = command_digest(command)
        if not callable(handler):
            raise TypeError("A synchronous command handler is required.")
        if (
            command["scope_id"] != self.scope_id
            or command["actor"]["scope_id"] != self.scope_id
            or command["authority"]["scope_id"] != self.scope_id
        ):
            return self._failure(command, StorageError("E_SCOPE_FORBIDDEN"))
        try:
            with self._operation():
                db = self._open()
                transaction = _Transaction(self, db, command, digest)
                try:
                    db.execute("BEGIN IMMEDIATE")
                    prior = db.execute(
                        "SELECT * FROM commands WHERE scope_id=? AND (idempotency_key=? OR command_id=?)",
                        (self.scope_id, command["idempotency_key"], command["command_id"]),
                    ).fetchall()
                    if prior:
                        if len(prior) != 1:
                            return self._failure(command, StorageError("E_IDEMPOTENCY_CONFLICT"))
                        journal = transaction._journal(prior[0])
                        if journal["command_digest"] != digest or canonical_bytes(journal["command"]) != canonical_bytes(command):
                            return self._failure(command, StorageError("E_IDEMPOTENCY_CONFLICT"))
                        return journal["result"]

                    db.execute("SAVEPOINT command_mutation")
                    try:
                        transaction._check_reads()
                        result = validate_result(handler(transaction))
                        if (
                            result["operation"] != command["operation"]
                            or result["operation_id"] != command["command_id"]
                            or (result["status"] == "success" and result["receipt"] != transaction.receipt_ref)
                        ):
                            raise StorageError("E_SCHEMA_INVALID", "Handler result identities must match the command.")
                    except ContractError as exc:
                        if exc.code == "E_STORAGE_UNAVAILABLE":
                            raise
                        result = self._failure(command, exc)
                    if result["status"] == "failure":
                        if result["error"]["code"] == "E_STORAGE_UNAVAILABLE":
                            raise _unavailable()
                        failure = result["error"]
                        result["error"] = self._failure(command, StorageError(
                            failure["code"], failure["detail"],
                            retriable=failure["retriable"],
                            affected_references=tuple(failure["affected_references"]),
                        ))["error"]
                        db.execute("ROLLBACK TO command_mutation")
                        transaction._writes.clear()
                    db.execute("RELEASE command_mutation")

                    self._fault("before_receipt")
                    receipt = transaction._receipt(result)
                    transaction._write(receipt, None)
                    db.execute(
                        "INSERT INTO commands(scope_id,idempotency_key,command_id,digest,command_json,result_json,"
                        "receipt_namespace,receipt_id,receipt_version) VALUES(?,?,?,?,?,?,?,?,1)",
                        (self.scope_id, command["idempotency_key"], command["command_id"], digest,
                         canonical_bytes(command), canonical_bytes(result), receipt["namespace"], receipt["id"]),
                    )
                    self._fault("before_commit")
                    db.commit()
                    self._fault("after_commit")
                    return deepcopy(result)
                finally:
                    transaction._active = False
                    _rollback(db)
                    db.close()
        except ContractError as exc:
            return self._failure(command, exc)
        except (sqlite3.Error, OSError):
            return self._failure(command, _unavailable())

    def backup_to(self, destination: str | Path, *, copy_timeout: float = 5.0) -> Path:
        """Take a verified SQLite snapshot into a new destination file."""
        from ._backup import copy_database

        try:
            with self._operation():
                # Check the owned source without silently creating/reinitializing it.
                db = self._open()
                db.close()
                return copy_database(self.path, Path(destination).absolute(), timeout=copy_timeout)
        except (sqlite3.Error, OSError):
            raise _unavailable() from None

    @classmethod
    def restore_from(
        cls, backup: str | Path, destination: str | Path,
        *, scope_id: str, timeout: float = 5.0, copy_timeout: float = 5.0,
    ) -> SQLiteStore:
        """Restore into a NEW database, then open it under an authorized scope."""
        from ._backup import copy_database

        _validate_fragment(scope_id, "identifier")
        if type(timeout) not in (int, float) or not 0 <= timeout <= 60:
            raise StorageError("E_SCHEMA_INVALID")
        path = copy_database(Path(backup).absolute(), Path(destination).absolute(), timeout=copy_timeout)
        return cls(path, scope_id=scope_id, timeout=timeout)
