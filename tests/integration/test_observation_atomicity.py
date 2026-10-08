"""Exercise the blob/transaction boundary, restart, and damaged source indexes."""

from copy import deepcopy
import multiprocessing
import os
from unittest.mock import patch

from matter.observations import ObservationIngestor, source_index_ref
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from observation_helpers import PAYLOAD, SCOPE, ObservationTestCase, observation_command


CRASH_EXIT = 74


def crash_ingest(database, payload_directory, command, stage):
    """Leave real rollback recovery to SQLite, bypassing Python cleanup."""
    def fault(point):
        if point == stage:
            os._exit(CRASH_EXIT)

    with SQLiteStore(database, scope_id=SCOPE, fault_hook=fault) as store:
        payloads = FilePayloadStore(payload_directory, scope_id=SCOPE)
        ObservationIngestor(store, payloads).ingest(command, payload=PAYLOAD)


class ObservationAtomicityTests(ObservationTestCase):
    def test_process_death_after_blob_publication_before_sql_commit_leaves_no_evidence(self):
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                command = observation_command(stage, stage, event_id=stage)
                prepared = self.ingestor.prepare(command)
                self._crash(prepared, stage)
                observation = command["body"]["observation"]
                self.assert_missing(entity_ref(observation))
                self.assert_missing(source_index_ref(SCOPE, observation["body"]["source_identity"]))
                with self.assertRaises(StorageError) as error:
                    self.storage.command_receipt(command["idempotency_key"])
                self.assertEqual(error.exception.code, "E_NOT_FOUND")
                # The immutable blob can safely survive as an orphan; no SQL
                # observation, index, command, or receipt claims it was accepted.
                self.assertEqual(self.payloads.read(observation["body"]["content"]).data, PAYLOAD)
                result = self.ingestor.ingest(prepared)
                self.assertEqual(result["outcome"], "committed", result)
                self.assertEqual(self.ingestor.read_payload(result["body"]["observation"]).data, PAYLOAD)

    def test_process_death_after_sql_commit_replays_complete_original_result(self):
        command = observation_command("committed-crash", "committed-crash")
        prepared = self.ingestor.prepare(command)
        self._crash(prepared, "after_commit")
        journal = self.storage.command_receipt(command["idempotency_key"])
        original = journal["result"]
        self.assertEqual(original["outcome"], "committed")
        self.assertEqual(journal["command"], prepared)
        # A saved command is an outcome lookup. Its handler, including supplied
        # payload checks, must not run again after a lost acknowledgement.
        self.assertEqual(self.ingestor.ingest(prepared, payload=b"not a new submission"), original)
        self.assertEqual(self.ingestor.read_payload(original["body"]["observation"]).data, PAYLOAD)
        self.assertEqual(self.record_counts(), {"observation": 1, "matter:projection": 1, "receipt": 1})

    def test_payload_storage_failure_does_not_publish_sql_references_or_receipts(self):
        command = observation_command("unavailable", "unavailable")
        prepared = self.ingestor.prepare(command)
        with patch.object(FilePayloadStore, "put", side_effect=StorageError("E_STORAGE_UNAVAILABLE", retriable=True)):
            failed = self.ingestor.ingest(prepared, payload=PAYLOAD)
        self.assert_failure(failed, "E_STORAGE_UNAVAILABLE")
        self.assertEqual(self.record_counts(), {})
        with self.assertRaises(StorageError) as error:
            self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")
        result = self.ingestor.ingest(prepared, payload=PAYLOAD)
        self.assertEqual(result["outcome"], "committed", result)

    def test_postcommit_exception_is_unavailable_until_exact_retry_recovers_receipt(self):
        command = observation_command("lost-ack", "lost-ack")
        prepared = self.ingestor.prepare(command)

        def fault(stage):
            if stage == "after_commit":
                raise OSError("Synthetic lost commit acknowledgement.")

        with SQLiteStore(self.database, scope_id=SCOPE, fault_hook=fault) as store:
            failed = ObservationIngestor(store, self.payloads).ingest(prepared, payload=PAYLOAD)
        self.assert_failure(failed, "E_STORAGE_UNAVAILABLE")
        journal = self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(journal["result"]["outcome"], "committed")
        self.assertEqual(self.ingestor.ingest(prepared), journal["result"])
        self.assertEqual(self.record_counts(), {"observation": 1, "matter:projection": 1, "receipt": 1})

    def test_restored_metadata_keeps_history_when_payloads_are_temporarily_missing(self):
        command = observation_command("original", "original")
        prepared, result = self.submit(command)
        original = self.storage.get(result["body"]["observation"])
        source = command["body"]["observation"]["body"]["source_identity"]
        backup = self.storage.backup_to(self.directory / "backup.sqlite")
        with SQLiteStore.restore_from(backup, self.directory / "restored.sqlite", scope_id=SCOPE) as restored:
            missing_payloads = FilePayloadStore(self.directory / "empty-payloads", scope_id=SCOPE)
            intake = ObservationIngestor(restored, missing_payloads)
            self.assertEqual(intake.revisions(source), [original])
            missing = intake.read_payload(result["body"]["observation"])
            self.assertEqual(missing.status, "unavailable")
            self.assertIsNone(missing.data)
            self.assertTrue(missing.reason)
            self.assertEqual(intake.ingest(prepared), result)
            # Retaining or restoring the scoped blob store supplies original
            # bytes without changing the restored observation or command.
            available = ObservationIngestor(restored, self.payloads)
            self.assertEqual(available.read_payload(result["body"]["observation"]).data, PAYLOAD)
            self.assertEqual(restored.get(result["body"]["observation"]), original)

    def test_tampered_index_value_is_refused_instead_of_accepting_false_duplicate(self):
        command = observation_command("original", "original")
        _, result = self.submit(command)
        source = command["body"]["observation"]["body"]["source_identity"]
        reference = source_index_ref(SCOPE, source)
        index = self.storage.get(reference)
        altered = deepcopy(index["value"])
        altered["value"]["entries"][0]["evidence_digest"] = "f" * 64
        # The generic port is deliberately host-programmable. Simulate a bad
        # host projection writer with an otherwise fully receipted transaction.
        mutation = observation_command("bad-index-writer", "unused")
        mutation["expected_revisions"] = [pin(index)]

        def corrupt(tx):
            tx.put_projection(reference, altered)
            return tx.success("duplicate", result["body"])

        self.assertEqual(self.storage.execute(mutation, corrupt)["status"], "success")
        with self.assertRaises(StorageError) as error:
            self.ingestor.revisions(source)
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")
        fresh = observation_command("redelivery", "redelivery")
        with self.assertRaises(StorageError) as error:
            self.ingestor.prepare(fresh)
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")
        self.assertEqual(self.ingestor.read_payload(result["body"]["observation"]).data, PAYLOAD)

    def _crash(self, command, stage):
        process = multiprocessing.get_context("spawn").Process(
            target=crash_ingest,
            args=(str(self.database), str(self.payload_directory), command, stage),
        )
        process.start()
        try:
            process.join(timeout=30)
            self.assertFalse(process.is_alive(), "Crash worker did not reach the injected boundary.")
            self.assertEqual(process.exitcode, CRASH_EXIT)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)


if __name__ == "__main__":
    import unittest
    unittest.main()
