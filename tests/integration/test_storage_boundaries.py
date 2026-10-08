"""Receipt provenance and transaction API boundaries independent of SQL layout."""

from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from matter.canonical import canonical_digest, source_digest
from matter.contracts import command_digest, error_result, schema_for
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from integration.helpers import SCOPE, create_command, create_matter, record_input


class StorageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = SQLiteStore(Path(self.directory.name) / "matter.sqlite", scope_id=SCOPE)
        self.addCleanup(self.store.close)
        self.seed_command = create_command("seed", "subject")
        self.seed_result = self.store.execute(self.seed_command, create_matter)
        self.assertEqual(self.seed_result["status"], "success")
        self.initial = self.store.get(self.seed_result["body"]["matter"])

    def test_receipt_details_conform_to_their_content_bound_schema(self):
        receipt = self.store.command_receipt(self.seed_command["idempotency_key"])["receipt"]
        details = receipt["body"]["details"]
        schema_bytes = files("matter._schemas").joinpath("storage-receipt-details.schema.json").read_bytes()
        descriptor = details["schema"]
        self.assertEqual(descriptor["digest"], source_digest(schema_bytes))
        self.assertEqual(descriptor["version"], "1.0")
        schema = json.loads(schema_bytes)
        core = schema_for("record")
        registry = Registry().with_resources([
            (core["$id"], Resource.from_contents(core)),
            (schema["$id"], Resource.from_contents(schema)),
        ])
        Draft202012Validator(schema, registry=registry).validate(details["value"])
        self.assertEqual(details["value"]["command_digest"], command_digest(self.seed_command))
        self.assertEqual(details["value"]["result_digest"], canonical_digest(self.seed_result, "result.create_matter.v1"))
        self.assertEqual(details["value"]["writes"], [pin(self.initial)])
        self.assertEqual(receipt["creation_receipt"], entity_ref(receipt))
        self.assertNotEqual(receipt["provenance"]["producer"]["digest"], "0" * 64)

    def test_snapshot_only_methods_cannot_bypass_transaction_read_checks(self):
        calls = (
            lambda tx: tx.history(entity_ref(self.initial)),
            lambda tx: tx.command_receipt(self.seed_command["idempotency_key"]),
            lambda tx: tx.receipt_for(entity_ref(self.initial)),
        )
        for index, read in enumerate(calls):
            with self.subTest(read=index):
                child = record_input("observation", f"bypass-child-{index}")
                command = create_command(f"bypass-{index}", "subject")

                def attempt(tx):
                    tx.insert(child)
                    read(tx)
                    return tx.success("existing", {"matter": pin(self.initial)})

                result = self.store.execute(command, attempt)
                self.assertEqual(result["status"], "failure")
                self.assertEqual(result["error"]["code"], "E_SCHEMA_INVALID")
                with self.assertRaises(StorageError) as missing:
                    self.store.get(entity_ref(child))
                self.assertEqual(missing.exception.code, "E_NOT_FOUND")
                receipt = self.store.command_receipt(command["idempotency_key"])["receipt"]
                self.assertEqual(receipt["body"]["details"]["value"]["writes"], [])
                self.assertNotIn(entity_ref(child), [entity_ref(ref) for ref in receipt["body"]["evidence"]])

    def test_duplicate_expected_identity_is_refused_before_handler_execution(self):
        command = create_command("duplicate-reads", "subject", expected_revisions=[pin(self.initial), pin(self.initial)])
        calls = []
        result = self.store.execute(command, lambda tx: calls.append(True))
        self.assertEqual(result["error"]["code"], "E_SCHEMA_INVALID")
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(entity_ref(self.initial)), self.initial)

    def test_unexpected_handler_exception_rolls_back_and_does_not_mint_a_result(self):
        command = create_command("handler-bug", "another-subject")

        def broken_handler(tx):
            tx.insert(tx.command["body"]["matter"])
            raise RuntimeError("Synthetic programming error.")

        with self.assertRaisesRegex(RuntimeError, "Synthetic programming error"):
            self.store.execute(command, broken_handler)
        for read in (
            lambda: self.store.get(entity_ref(command["body"]["matter"])),
            lambda: self.store.command_receipt(command["idempotency_key"]),
        ):
            with self.assertRaises(StorageError) as missing:
                read()
            self.assertEqual(missing.exception.code, "E_NOT_FOUND")
        self.assertEqual(self.store.execute(command, create_matter)["status"], "success")

    def test_retained_transaction_and_snapshot_handles_cannot_be_reused(self):
        retained = []
        command = create_command("retain-view", "subject", expected_revisions=[pin(self.initial)])

        def handler(tx):
            retained.append(tx)
            return tx.success("existing", {"matter": pin(tx.get(entity_ref(self.initial)))})

        self.assertEqual(self.store.execute(command, handler)["status"], "success")
        with self.store.snapshot() as snapshot:
            retained.append(snapshot)
        for view in retained:
            with self.assertRaises(StorageError) as closed:
                view.get(entity_ref(self.initial))
            self.assertEqual(closed.exception.code, "E_STORAGE_UNAVAILABLE")

    def test_reserved_receipt_namespace_and_creation_receipt_are_not_handler_assigned(self):
        for label in ("reserved-namespace", "supplied-creation-receipt"):
            with self.subTest(label=label):
                command = create_command(label, label)

                def invalid_insert(tx):
                    value = deepcopy(tx.command["body"]["matter"])
                    if label == "reserved-namespace":
                        value["namespace"] = "matter.storage"
                    else:
                        value["creation_receipt"] = tx.receipt_ref
                    return tx.success("created", {"matter": pin(tx.insert(value))})

                result = self.store.execute(command, invalid_insert)
                self.assertEqual(result["status"], "failure")
                self.assertEqual(result["error"]["code"], "E_SCOPE_FORBIDDEN" if label == "reserved-namespace" else "E_SCHEMA_INVALID")

    def test_removed_source_cannot_be_backed_up_as_an_empty_database(self):
        self.store.path.unlink()
        with self.assertRaises(StorageError) as failed:
            self.store.backup_to(Path(self.directory.name) / "backup.sqlite")
        self.assertEqual(failed.exception.code, "E_STORAGE_UNAVAILABLE")
        self.assertFalse(self.store.path.exists())

    def test_returned_and_raised_failures_both_filter_cross_scope_affected_references(self):
        readable = entity_ref(self.initial)
        foreign = {**readable, "scope_id": "another:scope"}
        for mode in ("returned", "raised"):
            with self.subTest(mode=mode):
                command = create_command(f"scope-failure-{mode}", "subject")

                def handler(tx):
                    if mode == "raised":
                        raise StorageError("E_SCOPE_FORBIDDEN", affected_references=(readable, foreign))
                    return error_result(tx.command["operation"], tx.command["command_id"],
                                        "E_SCOPE_FORBIDDEN", affected_references=[readable, foreign])

                result = self.store.execute(command, handler)
                self.assertEqual(result["error"]["affected_references"], [readable])
                self.assertEqual(self.store.command_receipt(command["idempotency_key"])["result"], result)

    def test_invalid_timeouts_are_semantic_errors_and_zero_lock_wait_can_back_up(self):
        directory = Path(self.directory.name)
        for invalid in (True, -1, 61, float("nan"), float("inf"), 10**400):
            with self.subTest(timeout_type=type(invalid).__name__):
                with self.assertRaises(StorageError) as error:
                    SQLiteStore(directory / "invalid.sqlite", scope_id=SCOPE, timeout=invalid)
                self.assertEqual(error.exception.code, "E_SCHEMA_INVALID")
        with SQLiteStore(self.store.path, scope_id=SCOPE, timeout=0) as no_wait:
            backup = no_wait.backup_to(directory / "no-wait-backup.sqlite")
            with SQLiteStore.restore_from(backup, directory / "restored.sqlite", scope_id=SCOPE, timeout=0) as restored:
                self.assertEqual(restored.get(entity_ref(self.initial)), self.initial)

    def test_foreign_table_resembling_internal_prefix_is_refused_before_journal_changes(self):
        path = Path(self.directory.name) / "foreign.sqlite"
        db = sqlite3.connect(path)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE sqliteXforeign(value TEXT)")
            db.execute("INSERT INTO sqliteXforeign VALUES('foreign content')")
            db.commit()
        finally:
            db.close()
        original = path.read_bytes()
        with self.assertRaises(StorageError) as refused:
            SQLiteStore(path, scope_id=SCOPE)
        self.assertEqual(refused.exception.code, "E_SCHEMA_INVALID")
        self.assertEqual(path.read_bytes(), original)
        db = sqlite3.connect(path)
        try:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(db.execute("SELECT value FROM sqliteXforeign").fetchone()[0], "foreign content")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
