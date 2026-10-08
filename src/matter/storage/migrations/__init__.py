"""Transactional, checksummed SQLite schema migrations.

The caller configures connection durability and foreign-key enforcement before
calling this module. Migration 1 accepts only an empty, unbranded database. Its
DDL, complete migration ledger, ``user_version`` and ``application_id`` commit in
one explicit ``BEGIN IMMEDIATE`` transaction. ``executescript`` is never used:
it can implicitly commit a pending transaction on supported Python runtimes.

Schema checks compare the installed migration's exact SQL object definitions,
not just the table names. They inspect metadata and the small migration ledger;
they do not replace an integrity check or validate every stored record's JSON.

A fault hook is a trusted test seam. It receives ``migration:1:N`` after each
write statement (DDL, ledger insertion, user version, application ID), then
``migration:before_commit``. Exceptions from the hook roll back and propagate.
Process termination deliberately bypasses cleanup to exercise SQLite recovery.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
import sqlite3
from typing import Callable, Iterator, NamedTuple

from ..base import StorageError


APPLICATION_ID = 0x4D415454  # ASCII "MATT", within SQLite's signed 32-bit field.
SCHEMA_VERSION = 1
_MIGRATION_FILES = ((1, "001_initial.sql"),)

__all__ = ["APPLICATION_ID", "SCHEMA_VERSION", "migrate", "check_database"]


class _Migration(NamedTuple):
    version: int
    name: str
    checksum: str
    statements: tuple[str, ...]


def _unavailable() -> StorageError:
    return StorageError(
        "E_STORAGE_UNAVAILABLE",
        "The database schema or migration ledger does not match this installation.",
    )


def _sqlite_error(error: sqlite3.Error) -> StorageError:
    # Extended result codes retain the primary code in their low eight bits.
    primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
    return StorageError(
        "E_STORAGE_UNAVAILABLE",
        "The database schema could not be accessed safely.",
        retriable=primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED},
    )


@lru_cache(maxsize=1)
def _migrations() -> tuple[_Migration, ...]:
    """Read trusted package resources; preserve exact bytes for the ledger."""
    migrations: list[_Migration] = []
    for version, name in _MIGRATION_FILES:
        try:
            source = files(__package__).joinpath(name).read_bytes()
            text = source.decode("utf-8")
        except (OSError, UnicodeError):
            raise StorageError(
                "E_STORAGE_UNAVAILABLE", "The installed storage migrations are unavailable."
            ) from None
        statements: list[str] = []
        pending: list[str] = []
        for line in text.splitlines(keepends=True):
            pending.append(line)
            candidate = "".join(pending)
            # complete_statement respects quoted strings and trigger bodies. A
            # semicolon split would incorrectly split the append-only triggers.
            if sqlite3.complete_statement(candidate):
                statements.append(candidate.strip())
                pending.clear()
        if "".join(pending).strip() or not statements:
            raise StorageError(
                "E_STORAGE_UNAVAILABLE", "The installed storage migration is incomplete."
            )
        migrations.append(_Migration(version, name, sha256(source).hexdigest(), tuple(statements)))
    return tuple(migrations)


def _registry() -> tuple[_Migration, ...]:
    migrations = _migrations()
    if tuple(item.version for item in migrations) != tuple(range(1, SCHEMA_VERSION + 1)):
        raise StorageError(
            "E_STORAGE_UNAVAILABLE", "The installed storage migration sequence is incomplete."
        )
    return migrations


def _schema_objects(db: sqlite3.Connection) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(row)
        for row in db.execute(
            "SELECT type, name, tbl_name, sql FROM main.sqlite_master ORDER BY type, name"
        )
        if not row[1].lower().startswith("sqlite_")
    )


@lru_cache(maxsize=8)
def _expected_objects(migrations: tuple[_Migration, ...]) -> tuple[tuple[str, ...], ...]:
    """Let this SQLite runtime normalize the trusted DDL once, away from data."""
    reference = sqlite3.connect(":memory:", isolation_level=None)
    try:
        for migration in migrations:
            for statement in migration.statements:
                reference.execute(statement)
        return _schema_objects(reference)
    finally:
        reference.close()


def _valid_applied_at(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return "T" in value and parsed.utcoffset() == timezone.utc.utcoffset(None)


def _check(
    db: sqlite3.Connection, *, allow_empty: bool, require_current: bool = True,
) -> int:
    """Inspect one transaction's view. Return zero only for a pristine schema."""
    application_id = db.execute("PRAGMA main.application_id").fetchone()[0]
    version = db.execute("PRAGMA main.user_version").fetchone()[0]
    objects = _schema_objects(db)
    if application_id != APPLICATION_ID:
        if allow_empty and application_id == 0 and version == 0 and not objects:
            return 0
        raise StorageError("E_SCHEMA_INVALID", "Database is not a Matter storage database.")
    if version > SCHEMA_VERSION:
        raise StorageError(
            "E_VERSION_UNSUPPORTED", "Database schema version is newer than this installation."
        )
    if version < 1:
        raise _unavailable()
    migrations = _registry()[:version]
    if objects != _expected_objects(migrations):
        raise _unavailable()
    # An extra row is enough to detect an unknown migration, without loading a
    # potentially enormous damaged ledger. Every expected row is still checked.
    rows = db.execute(
        "SELECT version, name, checksum, applied_at FROM main.schema_migrations "
        "ORDER BY version LIMIT ?", (len(migrations) + 1,),
    ).fetchall()
    if len(rows) != len(migrations):
        raise _unavailable()
    for row, migration in zip(rows, migrations):
        if tuple(row[:3]) != migration[:3] or not _valid_applied_at(row[3]):
            raise _unavailable()
    if require_current and version != SCHEMA_VERSION:
        raise StorageError(
            "E_VERSION_UNSUPPORTED", "Database schema requires migration before use."
        )
    return version


def _rollback_quietly(db: sqlite3.Connection) -> None:
    # Preserve the primary exception, including an injected BaseException. The
    # caller must discard a connection if I/O failure also prevents rollback.
    try:
        if db.in_transaction:
            db.execute("ROLLBACK")
    except sqlite3.Error:
        pass


@contextmanager
def _read_transaction(db: sqlite3.Connection) -> Iterator[None]:
    owns_transaction = not db.in_transaction
    if owns_transaction:
        db.execute("BEGIN")
    try:
        yield
        if owns_transaction:
            db.execute("ROLLBACK")  # Read only: release without committing caller work.
    except BaseException:
        if owns_transaction:
            _rollback_quietly(db)
        raise


def check_database(db: sqlite3.Connection) -> None:
    """Require an intact current Matter schema, with no database modifications.

    A read-only connection is sufficient. A caller's existing transaction is
    preserved; otherwise all metadata is inspected in one short read snapshot.
    Foreign databases, future versions and damaged schemas are explicit semantic
    errors. Full ``integrity_check`` and ``foreign_key_check`` belong to restore.
    """
    try:
        with _read_transaction(db):
            _check(db, allow_empty=False)
    except sqlite3.Error as error:
        raise _sqlite_error(error) from None


def migrate(
    db: sqlite3.Connection, fault_hook: Callable[[str], None] | None = None,
) -> None:
    """Initialize or upgrade a verified schema prefix atomically.

    The connection must have no active transaction. A second initializer waits
    for the first writer, then rechecks identity and schema under the write lock;
    it does not repeat DDL or invent another migration ledger entry.
    """
    owns_transaction = False
    try:
        if db.in_transaction:
            raise StorageError(
                "E_STORAGE_UNAVAILABLE", "A migration requires an idle database connection."
            )
        with _read_transaction(db):
            if _check(db, allow_empty=True, require_current=False) == SCHEMA_VERSION:
                return
        migrations = _registry()
        _expected_objects(migrations)  # Validate packaged DDL before acquiring the writer lock.
        db.execute("BEGIN IMMEDIATE")
        owns_transaction = True
        version = _check(db, allow_empty=True, require_current=False)
        if version == SCHEMA_VERSION:
            db.execute("ROLLBACK")  # Another initializer finished while we waited.
            owns_transaction = False
            return
        for migration in migrations[version:]:
            index = 0

            def execute(statement: str, parameters: tuple[object, ...] = ()) -> None:
                nonlocal index
                db.execute(statement, parameters)
                index += 1
                if fault_hook is not None:
                    fault_hook(f"migration:{migration.version}:{index}")

            for statement in migration.statements:
                execute(statement)
            applied_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, migration.checksum,
                 applied_at.replace("+00:00", "Z")),
            )
            execute(f"PRAGMA main.user_version = {migration.version}")
            execute(f"PRAGMA main.application_id = {APPLICATION_ID}")
        _check(db, allow_empty=False)
        if fault_hook is not None:
            fault_hook("migration:before_commit")
        db.execute("COMMIT")
        owns_transaction = False
    except BaseException as error:
        if owns_transaction:
            _rollback_quietly(db)
        if isinstance(error, sqlite3.Error):
            raise _sqlite_error(error) from None
        raise
