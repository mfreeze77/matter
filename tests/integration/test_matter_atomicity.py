"""Matter/key atomicity, recovery, and verified persistent identity failures."""

import multiprocessing
import os
from unittest.mock import patch

from matter.identity_keys import binding_value, identity_key_ref
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from integration.helpers import record_input
from matter_helpers import MatterTestCase, SCOPE, identity_key, identity_policy, matter_command, metadata_command
from observation_helpers import PAYLOAD, observation_command


CRASH_EXIT = 75


def crash_matter_operation(database, command, stage):
    """Force SQLite rollback recovery without Python context cleanup."""
    def fault(point):
        if point == stage:
            os._exit(CRASH_EXIT)

    with SQLiteStore(database, scope_id=SCOPE, fault_hook=fault) as storage:
        service = MatterService(storage, identity_policy=identity_policy())
        execute = service.create if command["operation"] == "create_matter" else service.update_metadata
        execute(command)


class MatterAtomicityTests(MatterTestCase):
    def _keys(self, label):
        return [identity_key(f"{label}-a"), identity_key(f"{label}-b"),
                identity_key(f"{label}-registry", "example:registry")]

    def _new(self, label="original"):
        prepared, result = self.submit_create(matter_command(label, keys=self._keys(label)))
        self.assertEqual(result["outcome"], "created", result)
        return prepared, result, self.storage.get(result["body"]["matter"])

    def _assert_no_journal(self, command):
        with self.assertRaises(StorageError) as error:
            self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def _crash(self, command, stage):
        process = multiprocessing.get_context("spawn").Process(
            target=crash_matter_operation, args=(str(self.database), command, stage),
        )
        process.start()
        try:
            process.join(timeout=30)
            self.assertFalse(process.is_alive(), "Matter worker did not reach the injected commit boundary.")
            self.assertEqual(process.exitcode, CRASH_EXIT)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)

    def test_creation_process_death_before_commit_leaves_every_key_and_matter_unpublished(self):
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                keys = self._keys(stage)
                prepared = self.service.prepare(matter_command(stage, keys=keys))
                before = self.record_counts()
                self._crash(prepared, stage)
                self.assertIsNone(self.service.resolve(keys))
                self.assert_missing(entity_ref(prepared["body"]["matter"]))
                for key in keys:
                    self.assert_missing(identity_key_ref(SCOPE, key))
                self._assert_no_journal(prepared)
                self.assertEqual(self.record_counts(), before)
                committed = self.service.create(prepared)
                self.assertEqual(committed["outcome"], "created", committed)
                current = self.service.resolve(keys)
                for key in keys:
                    binding = self.storage.get(identity_key_ref(SCOPE, key))
                    self.assertEqual(binding["creation_receipt"], current["creation_receipt"])
                    self.assertEqual(binding["value"], binding_value(SCOPE, key, [entity_ref(current)]))

    def test_creation_process_death_after_commit_recovers_all_keys_and_original_receipt(self):
        keys = self._keys("committed")
        prepared = self.service.prepare(matter_command("committed", keys=keys))
        self._crash(prepared, "after_commit")
        journal = self.storage.command_receipt(prepared["idempotency_key"])
        result = journal["result"]
        self.assertEqual(result["outcome"], "created")
        self.assertEqual(journal["command"], prepared)
        current = self.service.resolve(keys)
        self.assertEqual(result["body"]["matter"], pin(current))
        with patch.object(MatterService, "_create", side_effect=AssertionError("Committed handler reran.")):
            self.assertEqual(self.service.create(prepared), result)
        self.assertEqual(self.record_counts(), {"matter": 1, "matter:projection": 3, "receipt": 1})
        for key in keys:
            self.assertEqual(self.service.resolve([key]), current)
            self.assertEqual(self.storage.get(identity_key_ref(SCOPE, key))["creation_receipt"], result["receipt"])

    def test_metadata_process_death_before_commit_retains_old_snapshot_and_key_bindings(self):
        _, _, original = self._new()
        bindings = [self.storage.get(identity_key_ref(SCOPE, key)) for key in original["body"]["identity_keys"]]
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                prepared = self.service.prepare(metadata_command(stage, original, {"title": stage}))
                self._crash(prepared, stage)
                self.assertEqual(self.service.resolve(original["body"]["identity_keys"]), original)
                self.assertEqual(self.storage.history(entity_ref(original)), [original])
                self.assertEqual([self.storage.get(entity_ref(value)) for value in bindings], bindings)
                self._assert_no_journal(prepared)
        self.assertEqual(self.record_counts(), {"matter": 1, "matter:projection": 3, "receipt": 1})

    def test_metadata_process_death_after_commit_recovers_revision_without_repeating_edit(self):
        _, _, original = self._new()
        prepared = self.service.prepare(metadata_command("committed-edit", original, {"description": "New wording"}))
        self._crash(prepared, "after_commit")
        result = self.storage.command_receipt(prepared["idempotency_key"])["result"]
        self.assertEqual(result["outcome"], "updated")
        current = self.service.resolve(original["body"]["identity_keys"])
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["body"]["description"], "New wording")
        self.assertNotIn("title", current["body"])
        with patch.object(MatterService, "_update_metadata", side_effect=AssertionError("Committed edit reran.")):
            self.assertEqual(self.service.update_metadata(prepared), result)
        self.assertEqual(self.storage.history(entity_ref(original)), [original, current])
        self.assertEqual(self.record_counts(), {"matter": 1, "matter:projection": 3, "receipt": 2})

    def test_postcommit_acknowledgement_loss_recovers_exact_creation_and_edit_results(self):
        def fault(stage):
            if stage == "after_commit":
                raise OSError("Synthetic lost acknowledgement.")

        command = self.service.prepare(matter_command("lost-create", keys=self._keys("lost-create")))
        with SQLiteStore(self.database, scope_id=SCOPE, fault_hook=fault) as storage:
            failure = MatterService(storage, identity_policy=self.policy).create(command)
        self.assert_failure(failure, "E_STORAGE_UNAVAILABLE")
        created = self.storage.command_receipt(command["idempotency_key"])["result"]
        self.assertEqual(self.service.create(command), created)
        original = self.storage.get(created["body"]["matter"])
        edit = self.service.prepare(metadata_command("lost-edit", original, {"title": "Committed despite lost response"}))
        with SQLiteStore(self.database, scope_id=SCOPE, fault_hook=fault) as storage:
            failure = MatterService(storage, identity_policy=self.policy).update_metadata(edit)
        self.assert_failure(failure, "E_STORAGE_UNAVAILABLE")
        updated = self.storage.command_receipt(edit["idempotency_key"])["result"]
        self.assertEqual(self.service.update_metadata(edit), updated)
        self.assertEqual(updated["outcome"], "updated")
        self.assertEqual(self.service.resolve(original["body"]["identity_keys"])["revision"], 2)

    def test_backup_and_restore_preserve_every_key_metadata_revision_and_command_result(self):
        creation, created, original = self._new()
        edit, updated = self.submit_metadata(metadata_command("edit", original, {"description": "Saved new wording"}))
        current = self.storage.get(updated["body"]["matter"])
        keys = original["body"]["identity_keys"]
        proposal, existing = self.submit_create(matter_command("existing", keys=keys[:1]))
        bindings = [self.storage.get(identity_key_ref(SCOPE, key)) for key in keys]
        backup = self.storage.backup_to(self.directory / "backup.sqlite")
        with SQLiteStore.restore_from(backup, self.directory / "restored.sqlite", scope_id=SCOPE) as storage:
            restored = MatterService(storage, identity_policy=self.policy)
            self.assertEqual(restored.resolve(keys), current)
            self.assertEqual(storage.history(entity_ref(original)), [original, current])
            self.assertEqual([storage.get(entity_ref(value)) for value in bindings], bindings)
            for command, result in ((creation, created), (edit, updated), (proposal, existing)):
                self.assertEqual(storage.command_receipt(command["idempotency_key"])["result"], result)
                execute = restored.create if command["operation"] == "create_matter" else restored.update_metadata
                self.assertEqual(execute(command), result)

    def test_existing_subject_cannot_silently_discard_a_proposed_observation_id_collision(self):
        _, _, original = self._new()
        intake = ObservationIngestor(self.storage, FilePayloadStore(self.payload_directory, scope_id=SCOPE))
        observation = observation_command("occupied", "occupied", scope_id=SCOPE)
        ingested = intake.ingest(intake.prepare(observation), payload=PAYLOAD)
        evidence = self.storage.get(ingested["body"]["observation"])
        for label, keys in (("existing-key", original["body"]["identity_keys"]), ("new-key", self._keys("new"))):
            with self.subTest(label=label):
                proposal = matter_command(label, matter_id=evidence["id"], keys=keys)
                proposal["body"]["matter"]["namespace"] = evidence["namespace"]
                prepared = self.service.prepare(proposal)
                self.assertIn(pin(evidence), prepared["expected_revisions"])
                result = self.service.create(prepared)
                self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
                self.assertEqual(result["error"]["affected_references"], [entity_ref(evidence)])
                self.assertEqual(self.storage.get(pin(evidence)), evidence)
        self.assertEqual(self.service.resolve(original["body"]["identity_keys"]), original)
        self.assertIsNone(self.service.resolve(self._keys("new")))

    def test_index_target_corruption_is_explicit_and_never_becomes_absence_or_false_identity(self):
        for mode in ("missing", "wrong-kind", "wrong-key"):
            with self.subTest(mode=mode):
                key = identity_key(f"corrupt-{mode}")
                command = matter_command(f"seed-{mode}", keys=[key])
                target = record_input("observation" if mode == "wrong-kind" else "matter", f"target-{mode}", scope_id=SCOPE)
                if target["record_type"] == "matter":
                    target["body"]["identity_keys"] = [identity_key("different-declared-key")]
                reference = {**entity_ref(target), "record_type": "matter"}

                def seed(tx):
                    # A bad trusted projection writer can bypass operation
                    # policy. The service must still detect its inconsistency.
                    stored = tx.insert(tx.command["body"]["matter"])
                    if mode != "missing":
                        tx.insert(target)
                    tx.put_projection(identity_key_ref(SCOPE, key), binding_value(SCOPE, key, [reference]))
                    return tx.success("created", {"matter": pin(stored)})

                self.assertEqual(self.storage.execute(command, seed)["status"], "success")
                before = self.record_counts()
                for read in (
                    lambda: self.service.resolve([key]),
                    lambda: self.service.prepare(matter_command(f"lookup-{mode}", keys=[key])),
                ):
                    with self.assertRaises(StorageError) as error:
                        read()
                    self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")
                self.assertEqual(self.record_counts(), before)


if __name__ == "__main__":
    import unittest
    unittest.main()
