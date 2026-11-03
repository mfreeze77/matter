"""Optional synchronous PostgreSQL backend using host-owned connections (MAT-092).

The factory must supply an idle, exclusively leased psycopg Connection. Once
accepted, Matter owns its transaction until cleanup. `release` returns the idle
connection to a host pool; omitted, it closes the owned connection. An already
active connection is rejected without committing, rolling back or closing it:
its factory retains ownership. Connection acquisition deadlines belong to the
host factory/pool; `timeout` bounds database lock waits, not arbitrary callbacks.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import math
import re
import threading
from typing import Any, Callable

from .. import __version__
from ..canonical import canonical_bytes, canonical_digest, source_digest
from .base import StorageError, _validate_fragment, entity_ref, pin
from ._relational import RelationalStore, _unavailable
from . import postgresql_migrations as migrations


def _driver():
    try:
        import psycopg
    except ImportError:
        raise StorageError("E_STORAGE_UNAVAILABLE", "Install matter-foundation[postgres] to use PostgreSQL.") from None
    return psycopg


@lru_cache(maxsize=1)
def _components():
    root = files("matter.storage")
    names = ("base.py", "_relational.py", "postgresql.py", "postgresql_migrations/__init__.py",
             "postgresql_migrations/001_initial.sql", "postgresql_migrations/001_objects.json")
    producer = {"namespace": "matter", "id": "postgresql-reference-store", "version": __version__,
                "digest": canonical_digest({n: source_digest(root.joinpath(n).read_bytes()) for n in names},
                                           "component.storage.v1")}
    details = {"namespace": "matter", "id": "storage-receipt-details", "version": "1.0",
               "digest": source_digest(files("matter._schemas").joinpath("storage-receipt-details.schema.json").read_bytes())}
    return producer, details


class _Result:
    def __init__(self, rows, rowcount):
        self._rows, self.rowcount = rows, rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


@lru_cache(maxsize=128)
def _statement(statement):
    """Adapt only the private, fixed qmark statements; never accept host SQL.

    Digest predicates use bounded indexes; exact text predicates remain the
    authority for identity. Named parameters let both predicates share a value.
    """
    parts = statement.split("?")
    statement = "".join(part + (f"%(p{i})s" if i < len(parts) - 1 else "")
                        for i, part in enumerate(parts))
    keys = {"scope_id": "scope_key", "namespace": "namespace_key", "id": "id_key",
            "command_id": "command_key", "idempotency_key": "idempotency_hash", "watch_key": "watch_hash"}
    def predicate(match):
        prefix, field, parameter = match.groups()
        return (f"({prefix}{keys[field]}=identity_key({parameter}::text) "
                f"AND {prefix}{field}={parameter})")
    statement = re.sub(r"(?<![\w.])([a-z_]+\.|)(scope_id|namespace|id|command_id|idempotency_key|watch_key)"
                       r"=(%\(p[0-9]+\)s)", predicate, statement)
    statement = statement.replace("USING(scope_id,namespace,id", "USING(scope_key,namespace_key,id_key,scope_id,namespace,id")
    return statement


def _parameters(parameters):
    return {f"p{i}": value for i, value in enumerate(parameters)}


class _Connection:
    """Private qmark adapter for the fixed statements in _relational only."""
    def __init__(self, connection, release):
        self.raw, self._release = connection, release
        self._autocommit = connection.autocommit
        connection.autocommit = True

    def execute(self, statement, parameters=()):
        from psycopg.rows import dict_row
        with self.raw.cursor(row_factory=dict_row) as cursor:
            cursor.execute(_statement(statement), _parameters(parameters))
            return _Result(cursor.fetchall() if cursor.description else [], cursor.rowcount)

    def executemany(self, statement, parameters):
        with self.raw.cursor() as cursor:
            cursor.executemany(_statement(statement), (_parameters(row) for row in parameters))

    def commit(self):
        self.raw.commit()

    def close(self):
        if self._release is not None:
            release, self._release = self._release, None
            if not self.raw.closed:
                self.raw.autocommit = self._autocommit
            release(self.raw)


class PostgreSQLStore(RelationalStore):
    """Scope-bound ledger in an explicitly selected private host schema.

    Example factory: ``lambda: psycopg.connect(dsn, connect_timeout=5)``.
    Pool lease: ``PostgreSQLStore(pool.getconn, release=pool.putconn, ...)``.
    The pool and its lifecycle remain host-owned; closing this handle never
    closes the pool. No filesystem, DSN discovery or host schema is implicit.
    """
    _components = staticmethod(_components)

    def __init__(self, connection_factory: Callable, *, schema: str, scope_id: str,
                 release: Callable | None = None, timeout: float = 5.0,
                 initialize: bool = True, fault_hook=None, transaction_hook=None):
        self._scope_id = _validate_fragment(scope_id, "identifier")
        if (type(schema) is not str or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema)
                or schema in ("public", "information_schema") or schema.startswith("pg_")):
            raise StorageError("E_SCHEMA_INVALID", "Select a private lowercase PostgreSQL schema identifier.")
        if type(timeout) not in (int, float) or not 0 <= timeout <= 60:
            raise StorageError("E_SCHEMA_INVALID", "Lock timeout must be between zero and sixty seconds.")
        if type(initialize) is not bool:
            raise StorageError("E_SCHEMA_INVALID", "initialize must be a boolean.")
        if not callable(connection_factory) or any(x is not None and not callable(x)
                for x in (release, fault_hook, transaction_hook)):
            raise StorageError("E_SCHEMA_INVALID")
        psycopg = _driver()
        self._database_errors = (psycopg.Error, OSError)
        self._factory, self._release = connection_factory, release
        self._schema, self._timeout = schema, float(timeout)
        self._fault_hook, self._transaction_hook = fault_hook, transaction_hook
        self._local, self._closed = threading.local(), False
        try:
            db = self._open()
            try:
                if initialize:
                    self._start(db, write=True)
                    self._lock(db, "schema", schema)
                    migrations.migrate(db.raw, schema, self._fault)
                    self._fault("migration:before_commit")
                    db.commit()
                else:
                    self._begin(db, write=False)
            finally:
                self._rollback(db)
                db.close()
        except self._database_errors:
            raise _unavailable() from None

    @property
    def schema(self):
        return self._schema

    def _open(self):
        psycopg = _driver()
        connection = self._factory()
        if not isinstance(connection, psycopg.Connection):
            raise StorageError("E_SCHEMA_INVALID", "The host factory must return a synchronous psycopg connection.")
        if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            # Ownership did not transfer. Never touch the host's active work.
            raise StorageError("E_STORAGE_UNAVAILABLE", "The host connection must be idle and exclusively leased.")
        db = _Connection(connection, self._release or (lambda conn: conn.close()))
        if not 15 <= connection.info.server_version // 10000 <= 17:
            db.close()
            raise StorageError("E_VERSION_UNSUPPORTED", "This backend supports PostgreSQL 15 through 17.")
        return db

    def _start(self, db, *, write):
        from psycopg import sql
        db.raw.execute("BEGIN ISOLATION LEVEL READ COMMITTED READ WRITE" if write
                       else "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        db.raw.execute("SET LOCAL client_encoding = 'UTF8'")
        # Explicit pg_temp LAST prevents temporary relations shadowing our tables.
        db.raw.execute(sql.SQL("SET LOCAL search_path = pg_catalog, {}, pg_temp").format(sql.Identifier(self.schema)))
        db.raw.execute("SELECT set_config('lock_timeout', %s, true)",
                       (str(max(1, math.ceil(self._timeout * 1000))) + "ms",))
        db.raw.execute("SET LOCAL synchronous_commit = on")
        from psycopg.rows import tuple_row
        with db.raw.cursor(row_factory=tuple_row) as cursor:
            cursor.execute("SELECT current_setting('fsync'), current_setting('full_page_writes'), "
                           "current_setting('session_replication_role'), current_setting('server_encoding')")
            if cursor.fetchone() != ("on", "on", "origin", "UTF8"):
                raise StorageError("E_STORAGE_UNAVAILABLE", "Required PostgreSQL durability and integrity settings are unavailable.")

    def _lock(self, db, kind, value):
        # Collisions only serialize extra work; locks never grant authority.
        key = int.from_bytes(bytes.fromhex(source_digest(canonical_bytes(
            ["matter.postgresql.lock.v1", self.schema, kind, value])))[:8], "big", signed=True)
        if self._timeout == 0:
            from psycopg.rows import tuple_row
            with db.raw.cursor(row_factory=tuple_row) as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", (key,))
                if not cursor.fetchone()[0]:
                    raise _unavailable()
        else:
            db.raw.execute("SELECT pg_advisory_xact_lock(%s)", (key,))

    def _begin(self, db, *, write):
        self._start(db, write=write)
        if write:
            # Lock BEFORE any scoped reads; READ COMMITTED sees the prior
            # writer's commit after waiting, including previously absent rows.
            self._lock(db, "scope", self.scope_id)
        migrations.check_database(db.raw, self.schema)

    def _rollback(self, db):
        psycopg = _driver()
        try:
            if db.raw.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                db.raw.rollback()
        except psycopg.Error:
            db.raw.close()

    def verify(self) -> dict[str, Any]:
        """Verify scoped canonical bytes AND all ledger relationships in a snapshot.

        Host payload/artifact availability needs its own receiving check. Counts
        are informational; a valid count is not proof of a complete recovery set.
        """
        from psycopg.rows import dict_row
        counts = {}
        try:
            with self.snapshot() as view:
                db = view._db
                # Do not use the digest-prefiltered adapter for this first scan:
                # a stale generated scope key could otherwise hide whole rows.
                # Recompute independently of the database's generating function.
                keys = {"scope_id": "scope_key", "namespace": "namespace_key", "id": "id_key",
                        "command_id": "command_key", "idempotency_key": "idempotency_hash",
                        "watch_key": "watch_hash", "receipt_namespace": "receipt_namespace_key",
                        "receipt_id": "receipt_id_key"}
                for table in ("versions", "commands", "heads", "watches"):
                    with db.raw.cursor(name="matter_verify_keys", row_factory=dict_row) as cursor:
                        cursor.execute("SELECT * FROM " + table + " WHERE scope_id=%s", (self.scope_id,))
                        for row in cursor:
                            for field, key in keys.items():
                                if field in row and row[key] != bytes.fromhex(source_digest(row[field].encode("utf-8"))):
                                    raise _unavailable()
                invalid_head = db.execute(
                    "SELECT 1 FROM versions v LEFT JOIN heads h USING(scope_id,namespace,id) "
                    "WHERE v.scope_id=? AND (h.id IS NULL OR h.record_type<>v.record_type OR v.version>h.version) LIMIT 1",
                    (self.scope_id,)).fetchone()
                orphan_watch = db.execute(
                    "SELECT 1 FROM watches w LEFT JOIN heads h USING(scope_id,namespace,id) "
                    "WHERE w.scope_id=? AND h.id IS NULL LIMIT 1", (self.scope_id,)).fetchone()
                orphan_version = db.execute(
                    "SELECT 1 FROM versions v LEFT JOIN commands c ON v.scope_key=c.scope_key "
                    "AND v.command_key=c.command_key AND v.scope_id=c.scope_id AND v.command_id=c.command_id "
                    "WHERE v.scope_id=? AND c.command_id IS NULL LIMIT 1", (self.scope_id,)).fetchone()
                if invalid_head or orphan_watch or orphan_version:
                    raise _unavailable()
                # Bound memory to one command's write set. Checking just foreign
                # keys misses a version reassigned to a different valid command.
                commands = versions = 0
                with db.raw.cursor(name="matter_verify_commands", row_factory=dict_row) as cursor:
                    cursor.execute(_statement("SELECT * FROM commands WHERE scope_id=?"), _parameters((self.scope_id,)))
                    for row in cursor:
                        journal = view._journal(row)
                        receipt = journal["receipt"]
                        expected = [*receipt["body"]["details"]["value"]["writes"], pin(receipt)]
                        owned = db.execute("SELECT * FROM versions WHERE scope_id=? AND command_id=?",
                                           (self.scope_id, row["command_id"])).fetchall()
                        actual = [pin(view._decode(version)) for version in owned]
                        if sorted(map(canonical_bytes, expected)) != sorted(map(canonical_bytes, actual)):
                            raise _unavailable()
                        commands += 1
                        versions += len(owned)
                counts.update(commands=commands, versions=versions)
                heads = db.execute("SELECT * FROM heads WHERE scope_id=?", (self.scope_id,)).fetchall()
                for head in heads:
                    record = view.get({k: head[k] for k in ("scope_id", "namespace", "id", "record_type")})
                    history = view.history(entity_ref(record))
                    if [x.get("revision", 1) for x in history] != list(range(1, head["version"] + 1)):
                        raise _unavailable()
                    watch_rows = db.execute("SELECT watch_key FROM watches WHERE scope_id=? AND namespace=? AND id=?",
                                            (self.scope_id, head["namespace"], head["id"])).fetchall()
                    if sorted(x["watch_key"] for x in watch_rows) != sorted(record.get("watch_keys", [])):
                        raise _unavailable()
                counts["heads"] = len(heads)
                counts["watches"] = db.execute("SELECT count(*) AS n FROM watches WHERE scope_id=?",
                                               (self.scope_id,)).fetchone()["n"]
        except StorageError as error:
            if error.code == "E_NOT_FOUND":
                raise _unavailable() from None
            raise
        return {"scope_id": self.scope_id, "schema_version": migrations.SCHEMA_VERSION, **counts}
