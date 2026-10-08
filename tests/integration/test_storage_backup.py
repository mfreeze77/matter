"""Snapshot backup/restore preserves durable state without replacing files."""

from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from matter.storage import SQLiteStore, StorageError, entity_ref, pin
from matter.storage import _backup
from matter.storage.migrations import SCHEMA_VERSION

from .helpers import (
    SCOPE, WATCH_KEY, create_command, create_matter, mutation_command,
    projection_ref, rewrite_with_children,
)


class StorageBackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source.sqlite3"
        self.destination = self.root / "backup.sqlite3"

    def _initialize(self):
        with SQLiteStore(self.source, scope_id=SCOPE):
            pass

    def _populate(self):
        """Create real journal entries and two versions of an alias projection."""
        commands = []
        results = []
        with SQLiteStore(self.source, scope_id=SCOPE) as store:
            command = create_command("create-subject", "subject")
            result = store.execute(command, create_matter)
            self.assertEqual(result["status"], "success", result)
            commands.append(command)
            results.append(result)
            reference = entity_ref(result["body"]["matter"])
            alias = projection_ref("alias")
            for number in (1, 2):
                current = store.get(reference)
                expected = [pin(current)]
                if number == 2:
                    expected.append(pin(store.get(alias)))
                command = mutation_command(
                    f"change-{number}", current,
                    label=f"Synthetic update {number}",
                    child_id=f"evidence-{number}", projection_id="alias",
                    expected_revisions=expected,
                )
                result = store.execute(command, rewrite_with_children)
                self.assertEqual(result["status"], "success", result)
                commands.append(command)
                results.append(result)
            expected_state = self._logical_state(store, reference, alias, commands)
        return reference, alias, commands, results, expected_state

    def _logical_state(self, store, reference, alias, commands):
        with store.snapshot() as snapshot:
            record_history = snapshot.history(reference)
            projection_history = snapshot.history(alias)
            return {
                "record_current": snapshot.get(reference),
                "record_history": record_history,
                "projection_current": snapshot.get(alias),
                "projection_history": projection_history,
                "watchers": snapshot.watchers(WATCH_KEY),
                "commands": [
                    snapshot.command_receipt(command["idempotency_key"])
                    for command in commands
                ],
                "record_receipts": [
                    snapshot.receipt_for(pin(record)) for record in record_history
                ],
                "projection_receipts": [
                    snapshot.receipt_for(pin(value)) for value in projection_history
                ],
            }

    def _table_rows(self, path):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            names = db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT GLOB 'sqlite_*' ORDER BY name"
            ).fetchall()
            result = {}
            for (name,) in names:
                quoted = '"' + name.replace('"', '""') + '"'
                rows = db.execute("SELECT * FROM " + quoted).fetchall()
                result[name] = sorted(rows, key=repr)
            return result

    def _assert_no_staging(self):
        self.assertEqual(list(self.root.glob(".matter-backup-*")), [])

    def test_backup_and_restore_preserve_exact_history_watches_and_results(self):
        reference, alias, commands, results, expected = self._populate()
        rows = self._table_rows(self.source)
        with SQLiteStore(self.source, scope_id=SCOPE) as source_store:
            published = source_store.backup_to(self.destination)
            self.assertEqual(published, self.destination)
            self.assertFalse(os.path.samefile(self.source, self.destination))
            later = create_command("after-backup", "later-subject")
            self.assertEqual(
                source_store.execute(later, create_matter)["status"], "success"
            )

        self.assertEqual(self._table_rows(self.destination), rows)
        self.assertNotEqual(self._table_rows(self.source), rows)
        restored_path = self.root / "restored.sqlite3"
        with SQLiteStore.restore_from(
            self.destination, restored_path, scope_id=SCOPE,
        ) as restored:
            self.assertEqual(self._logical_state(restored, reference, alias, commands), expected)
            self.assertEqual(len(restored.history(reference)), 3)
            self.assertEqual(len(restored.history(alias)), 2)

            def must_not_run(transaction):
                self.fail("A restored journal retry must not call the handler.")

            for command, result in zip(commands, results):
                self.assertEqual(restored.execute(deepcopy(command), must_not_run), result)

        self.assertEqual(self._table_rows(restored_path), rows)
        with closing(sqlite3.connect(restored_path)) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self._assert_no_staging()

    def test_existing_destination_is_never_modified(self):
        self._initialize()
        original = b"An existing file must remain untouched."
        self.destination.write_bytes(original)
        with self.assertRaises(StorageError) as caught:
            _backup.copy_database(self.source, self.destination)
        self.assertEqual(caught.exception.code, "E_STORAGE_UNAVAILABLE")
        self.assertEqual(self.destination.read_bytes(), original)
        self._assert_no_staging()

    def test_existing_broken_symlink_is_not_replaced(self):
        self._initialize()
        missing_target = self.root / "missing-target"
        try:
            self.destination.symlink_to(missing_target)
        except (OSError, NotImplementedError):
            self.skipTest("This platform cannot create a test symlink.")
        with self.assertRaises(StorageError):
            _backup.copy_database(self.source, self.destination)
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(self.destination.readlink(), missing_target)
        self.assertFalse(missing_target.exists())
        self._assert_no_staging()

    def test_destination_created_during_publication_is_not_overwritten(self):
        self._initialize()
        real_link = os.link
        original = b"Created by another process during backup."

        def concurrent_creation(source, destination):
            Path(destination).write_bytes(original)
            return real_link(source, destination)

        with patch.object(_backup.os, "link", side_effect=concurrent_creation):
            with self.assertRaises(StorageError):
                _backup.copy_database(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), original)
        self._assert_no_staging()

    def test_failed_target_verification_publishes_nothing(self):
        self._initialize()
        real_verify = _backup._verify_database
        calls = []

        def fail_target(db, deadline):
            real_verify(db, deadline)
            calls.append(True)
            if len(calls) == 2:
                raise StorageError("E_STORAGE_UNAVAILABLE", "Synthetic target refusal.")

        with patch.object(_backup, "_verify_database", side_effect=fail_target):
            with self.assertRaises(StorageError):
                _backup.copy_database(self.source, self.destination)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.destination.exists())
        self._assert_no_staging()

    def test_backup_progress_deadline_stops_repeated_busy_restarts(self):
        self._initialize()
        real_connect = sqlite3.connect
        clock = [0.0]
        progress_calls = []

        class BusySource:
            def __init__(self, db):
                self.db = db

            def __getattr__(self, name):
                return getattr(self.db, name)

            def backup(self, target, *, pages, progress, sleep):
                while True:
                    clock[0] += 0.25
                    progress_calls.append(clock[0])
                    progress(sqlite3.SQLITE_BUSY, 1, 1)

        def connect(database, *args, **kwargs):
            db = real_connect(database, *args, **kwargs)
            if kwargs.get("uri") and "mode=ro" in str(database):
                return BusySource(db)
            return db

        with patch.object(_backup, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(_backup.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(StorageError) as caught:
                _backup.copy_database(self.source, self.destination, timeout=1.0)
        self.assertEqual(caught.exception.code, "E_STORAGE_UNAVAILABLE")
        self.assertTrue(caught.exception.retriable)
        self.assertEqual(progress_calls, [0.25, 0.5, 0.75, 1.0])
        self.assertFalse(self.destination.exists())
        self._assert_no_staging()

    def test_foreign_and_newer_databases_are_explicitly_refused(self):
        self._initialize()
        future = self.root / "future.sqlite3"
        _backup.copy_database(self.source, future)
        with closing(sqlite3.connect(future)) as db:
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
        foreign = self.root / "foreign.sqlite3"
        with closing(sqlite3.connect(foreign)) as db:
            db.execute("CREATE TABLE unrelated (value TEXT)")
            db.commit()
        for source, code in (
            (future, "E_VERSION_UNSUPPORTED"),
            (foreign, "E_SCHEMA_INVALID"),
        ):
            with self.subTest(code=code), self.assertRaises(StorageError) as caught:
                _backup.copy_database(source, self.destination)
            self.assertEqual(caught.exception.code, code)
            self.assertFalse(self.destination.exists())
        self._assert_no_staging()

    def test_corrupt_sqlite_source_is_refused_without_path_disclosure(self):
        self.source.write_bytes(b"This is not an SQLite database.")
        with self.assertRaises(StorageError) as caught:
            _backup.copy_database(self.source, self.destination)
        self.assertEqual(caught.exception.code, "E_STORAGE_UNAVAILABLE")
        self.assertNotIn(str(self.source), str(caught.exception))
        self.assertNotIn(str(self.destination), str(caught.exception))
        self.assertFalse(self.destination.exists())
        self._assert_no_staging()

    def test_missing_durable_foreign_reference_prevents_backup(self):
        self._populate()
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute(
                "DELETE FROM heads WHERE scope_id=? AND namespace=? AND id=?",
                (SCOPE, "example:projection", "alias"),
            )
            self.assertNotEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            db.commit()
        with self.assertRaises(StorageError) as caught:
            _backup.copy_database(self.source, self.destination)
        self.assertEqual(caught.exception.code, "E_STORAGE_UNAVAILABLE")
        self.assertFalse(self.destination.exists())
        self._assert_no_staging()

    def test_invalid_timeouts_are_structural_refusals(self):
        self._initialize()
        for timeout in (True, 0, -1, float("inf"), float("nan"), 10 ** 400):
            with self.subTest(timeout=timeout), self.assertRaises(StorageError) as caught:
                _backup.copy_database(self.source, self.destination, timeout=timeout)
            self.assertEqual(caught.exception.code, "E_SCHEMA_INVALID")
        self.assertFalse(self.destination.exists())
        self._assert_no_staging()

    def test_missing_source_does_not_create_a_database(self):
        with self.assertRaises(StorageError) as caught:
            _backup.copy_database(self.source, self.destination)
        self.assertEqual(caught.exception.code, "E_STORAGE_UNAVAILABLE")
        self.assertFalse(self.source.exists())
        self.assertFalse(self.destination.exists())
        self._assert_no_staging()

    def test_failure_after_publication_retains_complete_new_file(self):
        self._initialize()
        expected_rows = self._table_rows(self.source)
        with patch.object(_backup, "_fsync_directory", side_effect=OSError("synthetic")):
            with self.assertRaises(StorageError) as caught:
                _backup.copy_database(self.source, self.destination)
        self.assertEqual(caught.exception.code, "E_STORAGE_UNAVAILABLE")
        self.assertEqual(self._table_rows(self.destination), expected_rows)
        self._assert_no_staging()


if __name__ == "__main__":
    unittest.main()
