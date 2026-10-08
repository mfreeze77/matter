"""Forced process interruption and genuinely competing SQLite writers.

os._exit bypasses normal Python cleanup. The evidence here concerns process
death at defined transaction boundaries, not physical disk or power failure.
"""

from copy import deepcopy
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from matter.storage import SQLiteStore, StorageError, entity_ref

from integration.helpers import (
    CRASH_EXIT_CODE,
    SCOPE,
    WATCH_KEY,
    create_command,
    create_matter,
    execute_in_child,
    mutation_command,
    projection_ref,
    record_input,
    rewrite_with_children,
)


class StorageInterruptionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.context = multiprocessing.get_context("spawn")

    def seed(self, path):
        with SQLiteStore(path, scope_id=SCOPE) as store:
            result = store.execute(create_command("seed", "subject", title="Initial subject"), create_matter)
            self.assertEqual(result["status"], "success")
            return store.get(result["body"]["matter"])

    def assert_missing(self, store, reference):
        with self.assertRaises(StorageError) as error:
            store.get(reference)
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def assert_no_command_effects(self, store, command, initial):
        effects = command["extensions"]["example:effects"]["value"]
        self.assertEqual(store.get(entity_ref(initial)), initial)
        self.assertEqual(store.history(entity_ref(initial)), [initial])
        self.assert_missing(store, entity_ref(record_input("observation", effects["child_id"])))
        self.assert_missing(store, projection_ref(effects["projection_id"]))
        self.assertEqual(store.watchers(WATCH_KEY), [])
        with self.assertRaises(StorageError) as error:
            store.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def assert_committed_effects(self, store, command, initial, result):
        effects = command["extensions"]["example:effects"]["value"]
        current = store.get(entity_ref(initial))
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["body"]["title"], command["body"]["matter"]["body"]["title"])
        self.assertEqual(current["creation_receipt"], initial["creation_receipt"])
        self.assertEqual(store.history(entity_ref(initial)), [initial, current])
        child = store.get(entity_ref(record_input("observation", effects["child_id"])))
        projection = store.get(projection_ref(effects["projection_id"]))
        journal = store.command_receipt(command["idempotency_key"])
        self.assertEqual(journal["command"], command)
        self.assertEqual(journal["result"], result)
        receipt = journal["receipt"]
        self.assertEqual(entity_ref(receipt), result["receipt"])
        self.assertEqual(store.get(entity_ref(receipt)), receipt)
        for snapshot in (current, child, projection):
            self.assertEqual(store.receipt_for(entity_ref(snapshot)), receipt)
        self.assertEqual(child["creation_receipt"], entity_ref(receipt))
        self.assertEqual(projection["creation_receipt"], entity_ref(receipt))
        self.assertEqual(store.watchers(WATCH_KEY), [projection])

    def join_process(self, process, *, expected_exit=0):
        process.join(timeout=30)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
            self.fail("Storage subprocess did not terminate within 30 seconds.")
        self.assertEqual(process.exitcode, expected_exit)

    def test_forced_exit_around_receipt_and_commit_boundaries_preserves_atomicity(self):
        for stage in ("before_receipt", "before_commit", "after_commit"):
            with self.subTest(stage=stage):
                path = self.directory / f"{stage}.sqlite"
                initial = self.seed(path)
                command = mutation_command(
                    "interrupted-update", initial, label="Committed child set",
                    child_id="crash-child", projection_id="crash-alias",
                )
                process = self.context.Process(
                    target=execute_in_child, args=(str(path), command), kwargs={"crash_at": stage},
                )
                process.start()
                self.join_process(process, expected_exit=CRASH_EXIT_CODE)
                with SQLiteStore(path, scope_id=SCOPE) as recovered:
                    if stage == "after_commit":
                        original = recovered.command_receipt(command["idempotency_key"])["result"]
                        self.assertEqual(original["status"], "success")
                        self.assert_committed_effects(recovered, command, initial, original)
                    else:
                        self.assert_no_command_effects(recovered, command, initial)
                        original = None
                    calls = []

                    def retry_handler(tx):
                        calls.append(True)
                        return rewrite_with_children(tx)

                    retried = recovered.execute(deepcopy(command), retry_handler)
                    self.assertEqual(retried["status"], "success")
                    if original is not None:
                        self.assertEqual(retried, original)
                        self.assertEqual(calls, [])
                    else:
                        self.assertEqual(calls, [True])
                    self.assert_committed_effects(recovered, command, initial, retried)

    def test_precommit_fault_exceptions_leave_neither_children_nor_journaled_success(self):
        for target in ("before_receipt", "before_commit"):
            with self.subTest(stage=target):
                path = self.directory / f"exception-{target}.sqlite"
                initial = self.seed(path)
                command = mutation_command("faulted-update", initial, label="Uncommitted",
                                           child_id="fault-child", projection_id="fault-alias")

                def fault(stage):
                    if stage == target:
                        raise OSError("Synthetic transaction boundary failure.")

                with SQLiteStore(path, scope_id=SCOPE, fault_hook=fault) as faulty:
                    result = faulty.execute(command, rewrite_with_children)
                self.assertEqual(result["status"], "failure")
                self.assertEqual(result["error"]["code"], "E_STORAGE_UNAVAILABLE")
                self.assertNotIn("outcome", result)
                with SQLiteStore(path, scope_id=SCOPE) as recovered:
                    self.assert_no_command_effects(recovered, command, initial)
                    result = recovered.execute(command, rewrite_with_children)
                    self.assertEqual(result["status"], "success")
                    self.assert_committed_effects(recovered, command, initial, result)

    def test_postcommit_exception_reports_uncertainty_but_retry_returns_original_success(self):
        path = self.directory / "exception-after-commit.sqlite"
        initial = self.seed(path)
        command = mutation_command("postcommit-update", initial, label="Durably committed",
                                   child_id="postcommit-child", projection_id="postcommit-alias")

        def fault(stage):
            if stage == "after_commit":
                raise OSError("Synthetic failure after durable commit.")

        with SQLiteStore(path, scope_id=SCOPE, fault_hook=fault) as faulty:
            uncertain = faulty.execute(command, rewrite_with_children)
        self.assertEqual(uncertain["status"], "failure")
        self.assertEqual(uncertain["error"]["code"], "E_STORAGE_UNAVAILABLE")
        self.assertNotIn("outcome", uncertain)
        with SQLiteStore(path, scope_id=SCOPE) as recovered:
            original = recovered.command_receipt(command["idempotency_key"])["result"]
            self.assertEqual(original["status"], "success")
            self.assert_committed_effects(recovered, command, initial, original)
            calls = []
            retried = recovered.execute(command, lambda tx: calls.append(True))
            self.assertEqual(retried, original)
            self.assertEqual(calls, [])

    def test_two_processes_cannot_commit_incompatible_changes_from_one_revision(self):
        path = self.directory / "competing.sqlite"
        initial = self.seed(path)
        commands = [
            mutation_command(f"writer-{suffix}", initial, label=f"Writer {suffix}",
                             child_id=f"child-{suffix}", projection_id=f"alias-{suffix}")
            for suffix in ("a", "b")
        ]
        barrier = self.context.Barrier(3)
        output = self.context.Queue()
        processes = [
            self.context.Process(target=execute_in_child, args=(str(path), command),
                                 kwargs={"barrier": barrier, "output": output})
            for command in commands
        ]
        for process in processes:
            process.start()
        try:
            barrier.wait(timeout=30)
            messages = [output.get(timeout=30) for _ in processes]
            for process in processes:
                self.join_process(process)
        finally:
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
            output.close()
            output.join_thread()
        by_id = {item["command_id"]: item["result"] for item in messages}
        winners = [command for command in commands if by_id[command["command_id"]]["status"] == "success"]
        losers = [command for command in commands if by_id[command["command_id"]]["status"] == "failure"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        winner, loser = winners[0], losers[0]
        self.assertEqual(by_id[loser["command_id"]]["error"]["code"], "E_REVISION_CONFLICT")
        with SQLiteStore(path, scope_id=SCOPE) as recovered:
            self.assert_committed_effects(recovered, winner, initial, by_id[winner["command_id"]])
            effects = loser["extensions"]["example:effects"]["value"]
            self.assert_missing(recovered, entity_ref(record_input("observation", effects["child_id"])))
            self.assert_missing(recovered, projection_ref(effects["projection_id"]))
            failed_journal = recovered.command_receipt(loser["idempotency_key"])
            self.assertEqual(failed_journal["command"], loser)
            self.assertEqual(failed_journal["result"], by_id[loser["command_id"]])
            self.assertEqual(recovered.get(entity_ref(failed_journal["receipt"])), failed_journal["receipt"])
            self.assertNotEqual(failed_journal["receipt"]["id"], by_id[winner["command_id"]]["receipt"]["id"])


if __name__ == "__main__":
    unittest.main()
