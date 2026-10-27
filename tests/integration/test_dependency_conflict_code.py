"""Generic stale-read classification preserves checked writes and exact journals."""

from pathlib import Path
import tempfile
import unittest

from matter.contracts import ContractError
from matter.storage import SQLiteStore, StorageError, entity_ref, pin
from integration.helpers import SCOPE, create_command, create_matter, mutation_command, rewrite_with_children


class DependencyConflictCodeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "matter.sqlite"
        self.store = SQLiteStore(self.path, scope_id=SCOPE)
        self.addCleanup(self.store.close)
        result = self.store.execute(create_command("seed", "subject"), create_matter)
        self.original = self.store.get(result["body"]["matter"])

    def change_subject(self):
        result = self.store.execute(mutation_command("edit", self.original, label="Changed",
            child_id="child", projection_id="projection"), rewrite_with_children)
        self.assertEqual(result["status"], "success", result)

    def test_stale_dependency_is_journaled_without_running_handler_and_replays_after_restart(self):
        self.change_subject()
        command = create_command("stale-candidate", "must-not-exist", expected_revisions=[pin(self.original)])
        calls = []
        result = self.store.execute(command, lambda tx: calls.append(True), dependency_error_code="E_DEPENDENCY_STALE")
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(calls, [])
        self.assertEqual(self.store.command_receipt(command["idempotency_key"])["command"], command)
        with self.assertRaises(StorageError) as caught:
            self.store.lookup_identity(entity_ref(command["body"]["matter"]))
        self.assertEqual(caught.exception.code, "E_NOT_FOUND")
        self.store.close()
        self.store = SQLiteStore(self.path, scope_id=SCOPE)
        self.addCleanup(self.store.close)
        # A different classification option cannot relabel a historical retry.
        self.assertEqual(self.store.execute(command, lambda tx: calls.append(True)), result)
        self.assertEqual(calls, [])

    def test_default_revision_conflict_is_preserved(self):
        self.change_subject()
        command = create_command("default-stale", "new", expected_revisions=[pin(self.original)])
        result = self.store.execute(command, create_matter)
        self.assertEqual(result["error"]["code"], "E_REVISION_CONFLICT")

    def test_opt_in_does_not_weaken_fresh_read_or_write_validation(self):
        command = create_command("fresh", "new", expected_revisions=[pin(self.original)])
        result = self.store.execute(command, create_matter, dependency_error_code="E_DEPENDENCY_STALE")
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.store.get(result["body"]["matter"])["body"], command["body"]["matter"]["body"])
        duplicate = create_command("duplicate-reads", "other", expected_revisions=[pin(self.original)] * 2)
        rejected = self.store.execute(duplicate, create_matter, dependency_error_code="E_DEPENDENCY_STALE")
        self.assertEqual(rejected["error"]["code"], "E_SCHEMA_INVALID")

    def test_missing_declared_read_is_stale_without_side_effects(self):
        missing = {**entity_ref(self.original), "id": "absent", "revision": 1}
        command = create_command("missing-dependency", "new", expected_revisions=[missing])
        result = self.store.execute(command, create_matter, dependency_error_code="E_DEPENDENCY_STALE")
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(len(self.store.history(entity_ref(self.original))), 1)

    def test_arbitrary_error_classification_is_refused_before_execution(self):
        marker = "PRIVATE-CLASSIFICATION-MARKER"
        for value in (marker, True, None, {marker: "value"}):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ContractError) as caught:
                    self.store.execute(create_command("invalid-option", "new"), create_matter,
                        dependency_error_code=value)
                self.assertEqual(caught.exception.code, "E_POLICY_INVALID")
                self.assertNotIn(marker, caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
