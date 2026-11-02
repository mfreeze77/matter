"""SQLite reference backend: exact retries, checked reads, atomic receipts.

Connections are private to one operation and never shared across threads or
processes. Explicit transactions work on both Python 3.11 and 3.12. Durable
rollback journaling avoids depending on a particular distribution's WAL fixes.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable

from .. import __version__
from ..canonical import canonical_digest, source_digest
from .base import StorageError, _validate_fragment
from ._relational import RelationalStore, _Snapshot, _Transaction  # retain internal instrumentation imports
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


@lru_cache(maxsize=1)
def _components() -> tuple[dict[str, Any], dict[str, Any]]:
    root = files("matter.storage")
    implementation = {
        name: source_digest(root.joinpath(name).read_bytes())
        for name in ("base.py", "_relational.py", "sqlite.py", "migrations/__init__.py", "migrations/001_initial.sql")
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


class SQLiteStore(RelationalStore):
    """A durable database handle restricted to one host-authorized scope.

    timeout is a bounded lock wait in seconds (0 through 60). fault_hook is an
    explicit fault-test seam receiving transaction/migration stage names; normal
    applications leave it unset. No open connection survives a method call,
    except while a snapshot context or command handler is executing.
    """

    _database_errors = (sqlite3.Error, OSError)
    _components = staticmethod(_components)
    _rollback = staticmethod(_rollback)

    @staticmethod
    def _begin(db, *, write):
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")

    def __init__(
        self, path: str | Path, *, scope_id: str, timeout: float = 5.0,
        fault_hook: Callable[[str], None] | None = None,
        transaction_hook: Callable[[Any, list[dict[str, Any]]], None] | None = None,
    ) -> None:
        self._scope_id = _validate_fragment(scope_id, "identifier")
        if type(timeout) not in (int, float) or not 0 <= timeout <= 60:
            raise StorageError("E_SCHEMA_INVALID", "Lock timeout must be between zero and sixty seconds.")
        if not isinstance(path, (str, Path)) or str(path) in ("", ":memory:"):
            raise StorageError("E_SCHEMA_INVALID", "A durable filesystem database path is required.")
        if fault_hook is not None and not callable(fault_hook):
            raise StorageError("E_SCHEMA_INVALID")
        if transaction_hook is not None and not callable(transaction_hook):
            raise StorageError("E_SCHEMA_INVALID")
        self._path = Path(path).absolute()
        self._timeout = float(timeout)
        self._fault_hook = fault_hook
        self._transaction_hook = transaction_hook
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
