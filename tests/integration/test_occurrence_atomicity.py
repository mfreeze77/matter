"""Real process interruption and restore for one multi-effect grouping split."""

import multiprocessing
import os

from matter.occurrences import OccurrenceService, occurrence_index_ref, occurrence_key_ref
from matter.provenance_groups import assignment_ref
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from occurrence_helpers import (
    SCOPE, OccurrenceTestCase, coverage, declared, event_key, group_key,
    grouping_command, grouping_policy, occurrence_input, replacement,
)


CRASH_EXIT_CODE = 76


def split_in_child(database, command, stage):
    def fault(point):
        if point == stage:
            os._exit(CRASH_EXIT_CODE)

    with SQLiteStore(database, scope_id=SCOPE, fault_hook=fault) as store:
        OccurrenceService(store, grouping_policy=grouping_policy()).commit(command)
    raise AssertionError("The requested interruption did not occur.")


class NoExecutionService(OccurrenceService):
    def _commit(self, tx):
        raise AssertionError("An exact committed retry re-executed grouping.")


class OccurrenceAtomicityTests(OccurrenceTestCase):
    def _split(self):
        log_a = self.observe("log-a")
        log_b = self.observe("log-b")
        original = self.group("execution-a", [log_a, log_b], assignments=[declared(log_a), declared(log_b)])
        proposed = occurrence_input("execution-b", [log_b])
        command = self.service.prepare(grouping_command(
            "split-and-correct", creates=[proposed], replacements=[replacement(original, [log_a])],
            assignments=[declared(log_b, group_key("corrected-root-b"))],
        ))
        return log_a, log_b, original, proposed, command

    def _crash(self, command, stage):
        context = multiprocessing.get_context("spawn")
        process = context.Process(target=split_in_child, args=(str(self.database), command, stage))
        process.start()
        try:
            process.join(timeout=30)
            self.assertFalse(process.is_alive(), "The interrupted grouping process did not terminate.")
            self.assertEqual(process.exitcode, CRASH_EXIT_CODE)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)

    def _assert_completed(self, log_a, log_b, original, proposed, command):
        result = self.storage.command_receipt(command["idempotency_key"])["result"]
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(result["body"]["previous"], [pin(original)])
        current_a = self.storage.get(entity_ref(original))
        current_b = self.storage.get(entity_ref(proposed))
        self.assertEqual(current_a["body"]["observations"], [pin(log_a)])
        self.assertEqual(current_b["body"]["observations"], [pin(log_b)])
        self.assertEqual(current_a["body"]["provenance_groups"], [group_key()])
        self.assertEqual(current_b["body"]["provenance_groups"], [group_key("corrected-root-b")])
        self.assertEqual(current_a["revision"], 2)
        self.assertEqual(current_b["revision"], 1)
        self.assertEqual(current_a["creation_receipt"], original["creation_receipt"])
        self.assertEqual(self.storage.get(pin(log_a)), log_a)
        self.assertEqual(self.storage.get(pin(log_b)), log_b)
        self.assertEqual(self.storage.history(entity_ref(original)), [original, current_a])
        assignment = self.storage.get(assignment_ref(SCOPE, pin(log_b)))
        self.assertEqual(assignment["revision"], 2)
        self.assertEqual(result["body"]["provenance_assignments"], [pin(assignment)])
        for record in (current_a, current_b, assignment,
                       self.storage.get(occurrence_index_ref(SCOPE, current_a)),
                       self.storage.get(occurrence_index_ref(SCOPE, current_b)),
                       self.storage.get(occurrence_key_ref(SCOPE, event_key("execution-b")))):
            self.assertEqual(self.storage.receipt_for(pin(record))["id"], result["receipt"]["id"])
        self.assert_counts(self.count([log_a, log_b]), 2, 2, 2)
        replay = NoExecutionService(self.storage, grouping_policy=self.policy)
        self.assertEqual(replay.commit(command), result)
        return result

    def _rollback_after_crash(self, stage):
        log_a, log_b, original, proposed, command = self._split()
        assignment_before = self.storage.get(assignment_ref(SCOPE, pin(log_b)))
        index_before = self.storage.get(occurrence_index_ref(SCOPE, original))
        self._crash(command, stage)
        self.assertEqual(self.storage.get(entity_ref(original)), original)
        self.assertEqual(self.storage.get(assignment_ref(SCOPE, pin(log_b))), assignment_before)
        self.assertEqual(self.storage.get(occurrence_index_ref(SCOPE, original)), index_before)
        self.assert_missing(entity_ref(proposed))
        self.assert_missing(occurrence_index_ref(SCOPE, proposed))
        self.assert_missing(occurrence_key_ref(SCOPE, event_key("execution-b")))
        with self.assertRaises(StorageError) as error:
            self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")
        self.assert_counts(self.count([log_a, log_b]), 2, 1, 1)
        self.assertEqual(self.service.commit(command)["outcome"], "committed")
        self._assert_completed(log_a, log_b, original, proposed, command)

    def test_death_before_receipt_rolls_back_split_assignment_indexes_and_memberships(self):
        self._rollback_after_crash("before_receipt")

    def test_death_before_commit_rolls_back_split_assignment_indexes_and_memberships(self):
        self._rollback_after_crash("before_commit")

    def test_death_after_commit_recovers_entire_split_without_reexecuting(self):
        log_a, log_b, original, proposed, command = self._split()
        self._crash(command, "after_commit")
        self._assert_completed(log_a, log_b, original, proposed, command)

    def test_lost_acknowledgement_retains_committed_result_for_exact_retry(self):
        log_a, log_b, original, proposed, command = self._split()

        def fault(stage):
            if stage == "after_commit":
                raise OSError("Synthetic acknowledgement loss after the atomic grouping commit.")

        with SQLiteStore(self.database, scope_id=SCOPE, fault_hook=fault) as store:
            failed = OccurrenceService(store, grouping_policy=self.policy).commit(command)
        self.assert_failure(failed, "E_STORAGE_UNAVAILABLE")
        self._assert_completed(log_a, log_b, original, proposed, command)

    def test_restart_and_backup_restore_preserve_full_grouping_history_watches_and_retry(self):
        log_a, log_b, original, proposed, command = self._split()
        self.assertEqual(self.service.commit(command)["outcome"], "committed")
        result = self._assert_completed(log_a, log_b, original, proposed, command)
        before = self.count([log_a, log_b])
        current_a = self.storage.get(entity_ref(original))
        current_b = self.storage.get(entity_ref(proposed))
        assignment_history = self.storage.history(assignment_ref(SCOPE, pin(log_b)))
        with SQLiteStore(self.database, scope_id=SCOPE) as store:
            service = NoExecutionService(store, grouping_policy=self.policy)
            self.assertEqual(service.commit(command), result)
            self.assertEqual(service.counts([pin(log_a), pin(log_b)], coverage=coverage()), before)
        backup = self.storage.backup_to(self.directory / "backup.sqlite")
        with SQLiteStore.restore_from(backup, self.directory / "restored.sqlite", scope_id=SCOPE) as store:
            service = NoExecutionService(store, grouping_policy=self.policy)
            self.assertEqual(service.commit(command), result)
            self.assertEqual(service.counts([pin(log_a), pin(log_b)], coverage=coverage()), before)
            self.assertEqual(service.occurrences_for(pin(log_a)), [current_a])
            self.assertEqual(service.occurrences_for(pin(log_b)), [current_b])
            self.assertEqual(store.history(entity_ref(original)), [original, current_a])
            self.assertEqual(store.history(assignment_ref(SCOPE, pin(log_b))), assignment_history)
            self.assertEqual(service.resolve([event_key("execution-a")]), current_a)
            self.assertEqual(service.resolve([event_key("execution-b")]), current_b)
