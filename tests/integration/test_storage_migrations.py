"""Migration atomicity and schema enforcement using synthetic local databases.

Forced child termination covers process crashes, not physical power-loss or
filesystem qualification. Raw rows in constraint tests deliberately isolate
relational guarantees from the separate core JSON contract tests.
"""

from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from importlib.resources import files
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.synchronize import Event
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from matter.storage.base import StorageError
from matter.storage import migrations
from matter.storage.migrations import (
    APPLICATION_ID, SCHEMA_VERSION, check_database, migrate,
)


class _Interrupted(BaseException):
    """Exercise rollback even when the test seam bypasses Exception handlers."""


def _connect(path: Path, *, timeout: float = 0.05) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None, timeout=timeout)
    db.execute("PRAGMA journal_mode = DELETE")
    db.execute("PRAGMA synchronous = EXTRA")
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _state(db: sqlite3.Connection) -> tuple[object, ...]:
    return (
        db.execute("PRAGMA application_id").fetchone()[0],
        db.execute("PRAGMA user_version").fetchone()[0],
        tuple(db.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        )),
    )


def _crash_initialization(path: str, stage: str) -> None:
    db = _connect(Path(path))

    def terminate(current: str) -> None:
        if current == stage:
            os._exit(71)

    migrate(db, terminate)
    os._exit(72)  # The requested fault stage must have been reached.


def _concurrent_initializer(path: str, first: bool, release: Event, messages: Connection) -> None:
    """A trace barrier proves the second process reaches writer acquisition."""
    try:
        with closing(_connect(Path(path), timeout=5)) as db:
            stages: list[str] = []
            if not first:
                def trace(statement: str) -> None:
                    if statement == "BEGIN IMMEDIATE":
                        messages.send("waiting_for_writer")

                db.set_trace_callback(trace)

            def paused(current: str) -> None:
                stages.append(current)
                if first and current == "migration:1:1":
                    messages.send("holding_writer")
                    if not release.wait(10):
                        raise TimeoutError("Initialization barrier timed out.")

            migrate(db, paused)
            messages.send(("complete", stages))
    except BaseException as error:
        messages.send(("error", type(error).__name__))
        raise
    finally:
        messages.close()


def _seed_receipted_rows(db: sqlite3.Connection, *, scope: str = "scope:a") -> None:
    """Insert a minimal relational cycle; payload semantics are tested elsewhere."""
    db.execute("BEGIN IMMEDIATE")
    for identity, kind in (("receipt:1", "receipt"), ("entity:1", "matter")):
        db.execute(
            "INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (scope, "synthetic", identity, kind, 1,
             sha256(identity.encode()).hexdigest(), b"{}", "command:1"),
        )
        db.execute("INSERT INTO heads VALUES (?, ?, ?, ?, ?)",
                   (scope, "synthetic", identity, kind, 1))
    db.execute(
        "INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (scope, "key:1", "command:1", "a" * 64, b"{}", b"{}",
         "synthetic", "receipt:1", 1),
    )
    db.execute("INSERT INTO watches VALUES (?, ?, ?, ?)",
               (scope, "watch:1", "synthetic", "entity:1"))
    db.execute("COMMIT")


class StorageMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def database(self, name: str = "matter.sqlite") -> sqlite3.Connection:
        db = _connect(self.root / name)
        self.addCleanup(db.close)
        return db

    def assert_empty(self, db: sqlite3.Connection) -> None:
        self.assertEqual((0, 0, ()), _state(db))
        self.assertFalse(db.in_transaction)

    def test_initialization_records_exact_packaged_checksum_and_is_idempotent(self) -> None:
        db = self.database()
        stages: list[str] = []
        migrate(db, stages.append)
        source = files("matter.storage.migrations").joinpath("001_initial.sql").read_bytes()
        self.assertEqual(APPLICATION_ID, 0x4D415454)
        self.assertEqual(SCHEMA_VERSION, 1)
        self.assertEqual(
            (1, "001_initial.sql", sha256(source).hexdigest()),
            db.execute("SELECT version, name, checksum FROM schema_migrations").fetchone(),
        )
        self.assertEqual([f"migration:1:{index}" for index in range(1, 19)]
                         + ["migration:before_commit"], stages)
        before = (_state(db), tuple(db.execute("SELECT * FROM schema_migrations")))
        repeated: list[str] = []
        migrate(db, repeated.append)
        check_database(db)
        self.assertEqual([], repeated)
        self.assertEqual(before, (_state(db), tuple(db.execute("SELECT * FROM schema_migrations"))))
        self.assertFalse(db.in_transaction)

    def test_every_initial_migration_write_rolls_back_on_interruption(self) -> None:
        stages: list[str] = []
        with closing(_connect(self.root / "reference.sqlite")) as reference:
            migrate(reference, stages.append)
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                path = self.root / f"interrupted-{index}.sqlite"
                with closing(_connect(path)) as db:
                    def interrupt(current: str) -> None:
                        if current == stage:
                            self.assertTrue(db.in_transaction)
                            raise _Interrupted()

                    with self.assertRaises(_Interrupted):
                        migrate(db, interrupt)
                    self.assert_empty(db)
                with closing(_connect(path)) as restarted:
                    self.assert_empty(restarted)
                    migrate(restarted)
                    check_database(restarted)

    def test_process_crash_during_ddl_or_before_commit_recovers_empty_schema(self) -> None:
        context = multiprocessing.get_context("spawn")
        for index, stage in enumerate(("migration:1:1", "migration:before_commit")):
            with self.subTest(stage=stage):
                path = self.root / f"crashed-{index}.sqlite"
                child = context.Process(target=_crash_initialization, args=(str(path), stage))
                child.start()
                try:
                    child.join(15)
                    self.assertFalse(child.is_alive(), "Migration crash child did not finish.")
                    self.assertEqual(71, child.exitcode)
                finally:
                    if child.is_alive():
                        child.kill()
                        child.join(5)
                    child.close()
                with closing(_connect(path)) as restarted:
                    self.assert_empty(restarted)
                    migrate(restarted)
                    check_database(restarted)

    def test_simultaneous_initializers_recheck_schema_under_the_writer_lock(self) -> None:
        context = multiprocessing.get_context("spawn")
        path = self.root / "concurrent-init.sqlite"
        release = context.Event()
        first_read, first_write = context.Pipe(duplex=False)
        second_read, second_write = context.Pipe(duplex=False)
        first = context.Process(target=_concurrent_initializer,
                                args=(str(path), True, release, first_write))
        second = context.Process(target=_concurrent_initializer,
                                 args=(str(path), False, release, second_write))
        children = []
        try:
            first.start()
            children.append(first)
            first_write.close()
            self.assertTrue(first_read.poll(10), "First initializer did not acquire the writer lock.")
            self.assertEqual("holding_writer", first_read.recv())
            second.start()
            children.append(second)
            second_write.close()
            self.assertTrue(second_read.poll(10), "Second initializer did not attempt writer acquisition.")
            self.assertEqual("waiting_for_writer", second_read.recv())
            release.set()
            for child in children:
                child.join(10)
                self.assertFalse(child.is_alive())
                self.assertEqual(0, child.exitcode)
            self.assertTrue(first_read.poll(1))
            self.assertEqual("complete", first_read.recv()[0])
            self.assertTrue(second_read.poll(1))
            self.assertEqual(("complete", []), second_read.recv())
        finally:
            release.set()
            for child in children:
                if child.is_alive():
                    child.kill()
                    child.join(5)
                child.close()
            for endpoint in (first_read, first_write, second_read, second_write):
                endpoint.close()
        with closing(_connect(path)) as db:
            check_database(db)
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0])

    def test_future_upgrade_commits_only_missing_migration_and_preserves_records(self) -> None:
        db = self.database()
        migrate(db)
        _seed_receipted_rows(db)
        prior_ledger = db.execute("SELECT * FROM schema_migrations").fetchone()
        prior_versions = tuple(db.execute("SELECT * FROM versions ORDER BY id"))
        initial = migrations._migrations()
        sql = (
            "ALTER TABLE heads ADD COLUMN migration_note TEXT;",
            "CREATE INDEX heads_by_type ON heads (scope_id, record_type);",
        )
        future = migrations._Migration(
            2, "002_test_only.sql", sha256("\n".join(sql).encode()).hexdigest(), sql,
        )
        with patch.object(migrations, "SCHEMA_VERSION", 2), \
                patch.object(migrations, "_migrations", return_value=initial + (future,)):
            with self.assertRaises(StorageError) as requires_migration:
                check_database(db)
            self.assertEqual("E_VERSION_UNSUPPORTED", requires_migration.exception.code)
            stages: list[str] = []
            migrate(db, stages.append)
            check_database(db)
            self.assertEqual([f"migration:2:{index}" for index in range(1, 6)]
                             + ["migration:before_commit"], stages)
            self.assertEqual(prior_ledger, db.execute(
                "SELECT * FROM schema_migrations WHERE version = 1"
            ).fetchone())
            self.assertEqual(prior_versions, tuple(db.execute("SELECT * FROM versions ORDER BY id")))
            self.assertEqual((2, future.name, future.checksum), db.execute(
                "SELECT version, name, checksum FROM schema_migrations WHERE version = 2"
            ).fetchone())
            migrate(db)  # A completed upgrade is also idempotent.

    def test_failed_future_upgrade_restores_existing_schema_ledger_and_records(self) -> None:
        initial = migrations._migrations()
        sql = (
            "ALTER TABLE heads ADD COLUMN migration_note TEXT;",
            "CREATE INDEX heads_by_type ON heads (scope_id, record_type);",
        )
        future = migrations._Migration(
            2, "002_test_only.sql", sha256("\n".join(sql).encode()).hexdigest(), sql,
        )
        stages = [f"migration:2:{index}" for index in range(1, 6)] + ["migration:before_commit"]
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                db = self.database(f"upgrade-{index}.sqlite")
                migrate(db)
                _seed_receipted_rows(db)
                before = (_state(db), tuple(db.iterdump()))
                with patch.object(migrations, "SCHEMA_VERSION", 2), \
                        patch.object(migrations, "_migrations", return_value=initial + (future,)):
                    def interrupt(current: str) -> None:
                        if current == stage:
                            raise _Interrupted()

                    with self.assertRaises(_Interrupted):
                        migrate(db, interrupt)
                self.assertEqual(before, (_state(db), tuple(db.iterdump())))
                self.assertFalse(db.in_transaction)
                check_database(db)

    def test_foreign_and_newer_databases_are_refused_without_file_changes(self) -> None:
        cases = (
            ("foreign-table", 'CREATE TABLE "private-source-marker" (value TEXT)', "E_SCHEMA_INVALID"),
            ("foreign-id", "PRAGMA application_id = 27", "E_SCHEMA_INVALID"),
            ("unbranded-version", "PRAGMA user_version = 1", "E_SCHEMA_INVALID"),
            ("incomplete-owned", f"PRAGMA application_id = {APPLICATION_ID}", "E_STORAGE_UNAVAILABLE"),
            ("future", "PRAGMA user_version = 2", "E_VERSION_UNSUPPORTED"),
        )
        for name, change, expected in cases:
            with self.subTest(case=name):
                path = self.root / f"{name}.sqlite"
                with closing(_connect(path)) as db:
                    if name == "future":
                        migrate(db)
                    db.execute(change)
                original = path.read_bytes()
                with closing(_connect(path)) as db:
                    for operation in (check_database, migrate):
                        with self.assertRaises(StorageError) as refused:
                            operation(db)
                        self.assertEqual(expected, refused.exception.code)
                        self.assertNotIn("private-source-marker", str(refused.exception))
                        self.assertFalse(db.in_transaction)
                self.assertEqual(original, path.read_bytes())

    def test_damaged_migration_ledger_is_not_silently_repaired(self) -> None:
        changes = (
            "DELETE FROM schema_migrations",
            "UPDATE schema_migrations SET version = 2",
            "UPDATE schema_migrations SET name = 'different.sql'",
            "UPDATE schema_migrations SET checksum = '" + "0" * 64 + "'",
            "UPDATE schema_migrations SET applied_at = 'not-a-time'",
            "INSERT INTO schema_migrations VALUES (2, 'unknown.sql', '" + "b" * 64
            + "', '2024-01-01T00:00:00Z')",
            "PRAGMA user_version = 0",
        )
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                db = self.database(f"ledger-{index}.sqlite")
                migrate(db)
                db.execute(change)
                before = (_state(db), tuple(db.execute("SELECT * FROM schema_migrations")))
                for operation in (check_database, migrate):
                    with self.assertRaises(StorageError) as refused:
                        operation(db)
                    self.assertEqual("E_STORAGE_UNAVAILABLE", refused.exception.code)
                self.assertEqual(before, (_state(db), tuple(db.execute("SELECT * FROM schema_migrations"))))

    def test_exact_schema_objects_are_verified_but_sqlite_internal_objects_are_allowed(self) -> None:
        changes = (
            ("DROP TRIGGER commands_no_update",),
            ("DROP INDEX watches_by_identity",),
            ("ALTER TABLE commands ADD COLUMN unexpected TEXT",),
            ("CREATE TABLE unexpected (value TEXT)",),
            ("DROP TRIGGER versions_no_delete",
             "CREATE TRIGGER versions_no_delete BEFORE DELETE ON versions BEGIN SELECT 1; END"),
        )
        for index, statements in enumerate(changes):
            with self.subTest(change=index):
                db = self.database(f"structure-{index}.sqlite")
                migrate(db)
                for statement in statements:
                    db.execute(statement)
                with self.assertRaises(StorageError) as refused:
                    check_database(db)
                self.assertEqual("E_STORAGE_UNAVAILABLE", refused.exception.code)
        db = self.database("analyzed.sqlite")
        migrate(db)
        db.execute("ANALYZE")
        self.assertIsNotNone(db.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'sqlite_stat1'"
        ).fetchone())
        check_database(db)

    def test_readonly_check_and_repeated_migrate_do_not_require_a_writer(self) -> None:
        path = self.root / "readonly.sqlite"
        with closing(_connect(path)) as db:
            migrate(db)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                     isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            check_database(db)
            migrate(db)
            self.assertFalse(db.in_transaction)

    def test_check_preserves_caller_transaction_and_migrate_refuses_to_own_it(self) -> None:
        db = self.database()
        migrate(db)
        before = db.execute("SELECT applied_at FROM schema_migrations").fetchone()[0]
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE schema_migrations SET applied_at = '2000-01-01T00:00:00Z'")
        check_database(db)
        self.assertTrue(db.in_transaction)
        with self.assertRaises(StorageError):
            migrate(db)
        self.assertTrue(db.in_transaction)
        self.assertEqual("2000-01-01T00:00:00Z",
                         db.execute("SELECT applied_at FROM schema_migrations").fetchone()[0])
        db.execute("ROLLBACK")
        self.assertEqual(before, db.execute("SELECT applied_at FROM schema_migrations").fetchone()[0])

    def test_writer_contention_is_retriable_without_partial_initialization(self) -> None:
        path = self.root / "busy.sqlite"
        with closing(_connect(path)) as holder, closing(_connect(path)) as contender:
            holder.execute("BEGIN IMMEDIATE")
            with self.assertRaises(StorageError) as refused:
                migrate(contender)
            self.assertEqual("E_STORAGE_UNAVAILABLE", refused.exception.code)
            self.assertTrue(refused.exception.retriable)
            self.assertFalse(contender.in_transaction)
            holder.execute("ROLLBACK")
            self.assert_empty(contender)
            migrate(contender)

    def test_busy_commit_rolls_back_ddl_ledger_and_database_identity(self) -> None:
        path = self.root / "busy-commit.sqlite"
        with closing(_connect(path)) as reader, closing(_connect(path)) as writer:
            reader.execute("BEGIN")
            reader.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            stages: list[str] = []
            with self.assertRaises(StorageError) as refused:
                migrate(writer, stages.append)
            self.assertIn("migration:before_commit", stages)
            self.assertEqual("E_STORAGE_UNAVAILABLE", refused.exception.code)
            self.assertTrue(refused.exception.retriable)
            self.assertFalse(writer.in_transaction)
            reader.execute("ROLLBACK")
            self.assert_empty(writer)
            migrate(writer)

    def test_journal_and_versions_are_append_only_and_identity_cannot_change_type(self) -> None:
        db = self.database()
        migrate(db)
        _seed_receipted_rows(db)
        forbidden = (
            "UPDATE commands SET command_json = X'7b7d'",
            "DELETE FROM commands",
            "UPDATE versions SET content = X'7b7d'",
            "DELETE FROM versions",
            "UPDATE heads SET record_type = 'claim' WHERE id = 'entity:1'",
        )
        before = tuple(db.iterdump())
        for statement in forbidden:
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)
                self.assertEqual(before, tuple(db.iterdump()))
        for record_type, version in (("claim", 2), ("matter", 3), ("matter", 0),
                                     ("matter", 9007199254740992), ("matter", 1.5)):
            with self.subTest(record_type=record_type, version=version):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               ("scope:a", "synthetic", "entity:1", record_type,
                                version, "b" * 64, b"{}", "command:1"))
        db.execute("DELETE FROM watches")
        db.execute("DELETE FROM heads WHERE id = 'entity:1'")
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO heads VALUES (?, ?, ?, ?, ?)",
                       ("scope:a", "synthetic", "entity:1", "claim", 1))

    def test_receipt_foreign_keys_are_deferred_and_scoped_identities_are_unique(self) -> None:
        db = self.database()
        migrate(db)
        _seed_receipted_rows(db)
        _seed_receipted_rows(db, scope="scope:b")
        self.assertEqual(2, db.execute("SELECT COUNT(*) FROM commands").fetchone()[0])
        for missing in ("receipt", "journal"):
            with self.subTest(missing=missing):
                db.execute("BEGIN IMMEDIATE")
                if missing == "receipt":
                    db.execute("INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               ("scope:a", "new-key", "new-command", "b" * 64,
                                b"{}", b"{}", "synthetic", "missing-receipt", 1))
                else:
                    db.execute("INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               ("scope:a", "synthetic", "new-entity", "matter", 1,
                                "b" * 64, b"{}", "missing-command"))
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("COMMIT")
                self.assertTrue(db.in_transaction)
                db.execute("ROLLBACK")
        self.assertEqual([], db.execute("PRAGMA foreign_key_check").fetchall())
        self.assertEqual(2, db.execute("SELECT COUNT(*) FROM commands").fetchone()[0])
        self.assertEqual(4, db.execute("SELECT COUNT(*) FROM versions").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
