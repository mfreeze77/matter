"""Real SQLite transactions, checked reads, history, and unavailable outcomes.

All data and trusted handlers are synthetic. These tests qualify the embedded
storage port, not domain operations, external delivery, or physical power loss.
"""

from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from matter.contracts import ContractError, validate_record, validate_result
from matter.storage import SQLiteStore, StorageError, entity_ref, pin, snapshot_digest

from integration.helpers import (
    SCOPE,
    WATCH_KEY,
    create_command,
    create_matter,
    domain_value,
    ingest_command,
    ingest_observation,
    mutation_command,
    projection_ref,
    record_input,
    rewrite_with_children,
)


class StorageTransactionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "matter.sqlite"
        self.store = SQLiteStore(self.path, scope_id=SCOPE)
        self.addCleanup(self.store.close)

    def seed(self, identity="subject", command_id="seed-command"):
        command = create_command(command_id, identity, title="Initial subject")
        result = self.store.execute(command, create_matter)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["outcome"], "created")
        return self.store.get(result["body"]["matter"]), command, result

    def assert_failure(self, result, code):
        self.assertEqual(validate_result(result), result)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error"]["code"], code)
        self.assertNotIn("outcome", result)

    def assert_missing(self, reference, store=None):
        with self.assertRaises(StorageError) as error:
            (store or self.store).get(reference)
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def assert_journal(self, command, result):
        journal = self.store.command_receipt(command["idempotency_key"])
        self.assertEqual(journal["command"], command)
        self.assertEqual(journal["result"], result)
        self.assertEqual(validate_record(journal["receipt"]), journal["receipt"])
        self.assertEqual(journal["receipt"]["record_type"], "receipt")
        self.assertEqual(journal["receipt"]["body"]["operation_id"], command["command_id"])
        self.assertEqual(self.store.get(entity_ref(journal["receipt"])), journal["receipt"])
        if result["status"] == "success":
            self.assertEqual(result["receipt"], entity_ref(journal["receipt"]))
        return journal

    def test_committed_command_and_receipt_survive_restart_and_exact_retry(self):
        stored, command, result = self.seed()
        self.assertEqual(stored["revision"], 1)
        self.assertEqual(stored["creation_receipt"], result["receipt"])
        journal = self.assert_journal(command, result)
        self.store.close()
        self.store = SQLiteStore(self.path, scope_id=SCOPE)
        self.addCleanup(self.store.close)
        calls = []

        def forbidden_handler(tx):
            calls.append(True)
            raise AssertionError("A committed retry must not run its handler.")

        retry = self.store.execute(deepcopy(command), forbidden_handler)
        self.assertEqual(retry, result)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(entity_ref(stored)), stored)
        self.assertEqual(self.store.command_receipt(command["idempotency_key"]), journal)
        self.assertEqual(self.store.history(entity_ref(stored)), [stored])

    def test_map_order_does_not_change_idempotency_but_changed_content_conflicts(self):
        stored, command, original = self.seed()

        def reversed_maps(value):
            if isinstance(value, dict):
                return {key: reversed_maps(item) for key, item in reversed(list(value.items()))}
            if isinstance(value, list):
                return [reversed_maps(item) for item in value]
            return value

        calls = []
        retry = self.store.execute(reversed_maps(command), lambda tx: calls.append(True))
        self.assertEqual(retry, original)
        self.assertEqual(calls, [])
        changed = deepcopy(command)
        changed["body"]["matter"]["body"]["title"] = "Different intended content"
        conflict = self.store.execute(changed, lambda tx: calls.append(True))
        self.assert_failure(conflict, "E_IDEMPOTENCY_CONFLICT")
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(entity_ref(stored)), stored)
        self.assertEqual(self.store.command_receipt(command["idempotency_key"])["result"], original)

    def test_one_command_identity_cannot_be_reused_under_a_different_key(self):
        stored, command, original = self.seed()
        changed = deepcopy(command)
        changed["idempotency_key"] = "another-idempotency-key"
        calls = []
        result = self.store.execute(changed, lambda tx: calls.append(True))
        self.assert_failure(result, "E_IDEMPOTENCY_CONFLICT")
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(entity_ref(stored)), stored)
        self.assertEqual(self.store.command_receipt(command["idempotency_key"])["result"], original)

    def test_revision_history_preserves_creation_receipt_and_each_commit_receipt(self):
        initial, seed_command, seed_result = self.seed()
        command = mutation_command("update-command", initial, label="Changed subject",
                                   child_id="child-one", projection_id="alias-one")
        result = self.store.execute(command, rewrite_with_children)
        self.assertEqual(result["status"], "success")
        current = self.store.get(entity_ref(initial))
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["body"]["title"], "Changed subject")
        self.assertEqual(current["creation_receipt"], initial["creation_receipt"])
        self.assertEqual(self.store.history(entity_ref(initial)), [initial, current])
        self.assertEqual(self.store.get(pin(initial)), initial)
        self.assertEqual(self.store.get({**entity_ref(current), "digest": snapshot_digest(initial)}), initial)
        first_receipt = self.assert_journal(seed_command, seed_result)["receipt"]
        second_receipt = self.assert_journal(command, result)["receipt"]
        self.assertNotEqual(first_receipt["id"], second_receipt["id"])
        self.assertEqual(self.store.receipt_for(pin(initial)), first_receipt)
        self.assertEqual(self.store.receipt_for(pin(current)), second_receipt)
        child = self.store.get(entity_ref(record_input("observation", "child-one")))
        projection = self.store.get(projection_ref("alias-one"))
        self.assertEqual(child["creation_receipt"], entity_ref(second_receipt))
        self.assertEqual(projection["creation_receipt"], entity_ref(second_receipt))
        self.assertEqual(self.store.receipt_for(entity_ref(child)), second_receipt)
        self.assertEqual(self.store.receipt_for(entity_ref(projection)), second_receipt)
        self.assertEqual(self.store.watchers(WATCH_KEY), [projection])

    def test_retry_is_checked_before_stale_read_revisions(self):
        initial, _, _ = self.seed()
        first = mutation_command("first-update", initial, label="First update",
                                 child_id="first-child", projection_id="first-alias")
        first_result = self.store.execute(first, rewrite_with_children)
        second_state = self.store.get(entity_ref(initial))
        second = mutation_command("second-update", second_state, label="Second update",
                                  child_id="second-child", projection_id="second-alias")
        second_result = self.store.execute(second, rewrite_with_children)
        self.assertEqual(second_result["status"], "success")
        calls = []
        retried = self.store.execute(first, lambda tx: calls.append(True))
        self.assertEqual(retried, first_result)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(entity_ref(initial))["revision"], 3)
        self.assertEqual(self.store.get(retried["body"]["matter"])["body"]["title"], "First update")

    def test_stale_expected_revision_refuses_handler_and_records_failure(self):
        initial, _, _ = self.seed()
        first = mutation_command("winner", initial, label="Winning change",
                                 child_id="winning-child", projection_id="winning-alias")
        self.assertEqual(self.store.execute(first, rewrite_with_children)["status"], "success")
        stale = mutation_command("stale", initial, label="Stale change",
                                 child_id="stale-child", projection_id="stale-alias")
        calls = []
        result = self.store.execute(stale, lambda tx: calls.append(True))
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(entity_ref(initial))["body"]["title"], "Winning change")
        self.assert_missing(entity_ref(record_input("observation", "stale-child")))
        self.assert_missing(projection_ref("stale-alias"))
        self.assert_journal(stale, result)

    def test_missing_read_pin_rolls_back_earlier_children_and_replays_failure(self):
        initial, _, _ = self.seed()
        command = create_command("missing-readset", initial["id"])
        child = record_input("observation", "unreceipted-child")

        def missing_readset(tx):
            tx.insert(child)
            tx.put_projection(projection_ref("unreceipted-alias"), domain_value({"synthetic": True}),
                              watch_keys=(WATCH_KEY,))
            tx.get(entity_ref(initial))
            raise AssertionError("An undeclared read must have been refused.")

        result = self.store.execute(command, missing_readset)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(self.store.get(entity_ref(initial)), initial)
        self.assert_missing(entity_ref(child))
        self.assert_missing(projection_ref("unreceipted-alias"))
        self.assertEqual(self.store.watchers(WATCH_KEY), [])
        journal = self.assert_journal(command, result)
        calls = []
        self.assertEqual(self.store.execute(command, lambda tx: calls.append(True)), result)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.command_receipt(command["idempotency_key"]), journal)

    def test_handler_refusal_rolls_back_every_child_but_retains_a_durable_receipt(self):
        initial, _, _ = self.seed()
        command = mutation_command("refused", initial, label="Must not persist",
                                   child_id="refused-child", projection_id="refused-alias")

        def refuse_after_writes(tx):
            rewrite_with_children(tx)
            raise StorageError("E_POLICY_INVALID", "Synthetic host refusal.")

        result = self.store.execute(command, refuse_after_writes)
        self.assert_failure(result, "E_POLICY_INVALID")
        self.assertEqual(self.store.get(entity_ref(initial)), initial)
        self.assertEqual(self.store.history(entity_ref(initial)), [initial])
        self.assert_missing(entity_ref(record_input("observation", "refused-child")))
        self.assert_missing(projection_ref("refused-alias"))
        self.assertEqual(self.store.watchers(WATCH_KEY), [])
        journal = self.assert_journal(command, result)
        self.store.close()
        with SQLiteStore(self.path, scope_id=SCOPE) as restarted:
            self.assertEqual(restarted.command_receipt(command["idempotency_key"]), journal)
            self.assertEqual(restarted.history(entity_ref(initial)), [initial])

    def test_new_writes_are_readable_without_a_preexisting_pin(self):
        command = create_command("read-own-write", "new-subject")
        observed = []

        def handler(tx):
            inserted = tx.insert(tx.command["body"]["matter"])
            observed.append(tx.get(entity_ref(inserted)))
            return tx.success("created", {"matter": pin(inserted)})

        result = self.store.execute(command, handler)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0], self.store.get(result["body"]["matter"]))

    def test_duplicate_writes_inside_one_command_do_not_leave_partial_state(self):
        command = create_command("duplicate-insert", "duplicate-subject")

        def duplicate_insert(tx):
            tx.insert(tx.command["body"]["matter"])
            stored = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(stored)})

        result = self.store.execute(command, duplicate_insert)
        self.assertEqual(result["status"], "failure")
        self.assert_missing(entity_ref(command["body"]["matter"]))
        self.assert_journal(command, result)
        initial, _, _ = self.seed()
        command = create_command("duplicate-replace", initial["id"], expected_revisions=[pin(initial)])

        def duplicate_replace(tx):
            current = tx.get(entity_ref(initial))
            current["revision"] = 2
            second = tx.replace(current)
            second["revision"] = 3
            third = tx.replace(second)
            return tx.success("existing", {"matter": pin(third)})

        result = self.store.execute(command, duplicate_replace)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(self.store.history(entity_ref(initial)), [initial])

    def test_immutable_records_cannot_be_replaced_or_retyped(self):
        command = ingest_command("observe", "observation")
        result = self.store.execute(command, ingest_observation)
        self.assertEqual(result["status"], "success")
        original = self.store.get(result["body"]["observation"])
        attempted = ingest_command("replace-observation", "observation", expected_revisions=[pin(original)])

        def replace_evidence(tx):
            current = tx.get(entity_ref(original))
            current["body"]["source_identity"]["event_id"] = "changed-source-event"
            replacement = tx.replace(current)
            return tx.success("committed", {"observation": pin(replacement)})

        failure = self.store.execute(attempted, replace_evidence)
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        self.assertEqual(self.store.history(entity_ref(original)), [original])
        retype = create_command("retype-evidence", "observation")
        failure = self.store.execute(retype, create_matter)
        self.assert_failure(failure, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(self.store.get(entity_ref(original)), original)

    def test_scopes_are_isolated_even_when_opaque_ids_match(self):
        initial, _, _ = self.seed()
        other_scope = "synthetic:other-scope"
        with SQLiteStore(self.path, scope_id=other_scope) as other:
            command = create_command("other-seed", initial["id"], scope_id=other_scope,
                                     title="Other scope subject")
            result = other.execute(command, create_matter)
            self.assertEqual(result["status"], "success")
            foreign = other.get(result["body"]["matter"])
            for query in (self.store.get, self.store.history, self.store.receipt_for):
                with self.subTest(query=query.__name__), self.assertRaises(StorageError) as error:
                    query(entity_ref(foreign))
                self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
            calls = []
            rejected = self.store.execute(command, lambda tx: calls.append(True))
            self.assert_failure(rejected, "E_SCOPE_FORBIDDEN")
            self.assertEqual(calls, [])
            self.assertEqual(self.store.get(entity_ref(initial)), initial)
            self.assertEqual(other.get(entity_ref(foreign)), foreign)

    def test_cross_scope_write_rolls_back_earlier_same_scope_mutation(self):
        command = create_command("cross-scope-write", "local-subject")
        foreign = record_input("observation", "foreign-child", scope_id="synthetic:other-scope")

        def handler(tx):
            local = tx.insert(tx.command["body"]["matter"])
            tx.insert(foreign)
            return tx.success("created", {"matter": pin(local)})

        result = self.store.execute(command, handler)
        self.assert_failure(result, "E_SCOPE_FORBIDDEN")
        self.assert_missing(entity_ref(command["body"]["matter"]))
        self.assert_journal(command, result)

    def test_projection_identity_cannot_retype_an_existing_core_record(self):
        initial, _, _ = self.seed()
        command = create_command("projection-collision", initial["id"], expected_revisions=[pin(initial)])
        collision = {**entity_ref(initial), "record_type": "matter:projection"}

        def handler(tx):
            tx.put_projection(collision, domain_value({"synthetic": True}))
            return tx.success("existing", {"matter": pin(initial)})

        result = self.store.execute(command, handler)
        self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(self.store.history(entity_ref(initial)), [initial])

    def test_consistent_snapshot_blocks_writer_commit_until_read_boundary_closes(self):
        initial, _, _ = self.seed()
        command = mutation_command("concurrent-view-update", initial, label="New boundary",
                                   child_id="snapshot-child", projection_id="snapshot-alias")
        writer = SQLiteStore(self.path, scope_id=SCOPE, timeout=0.05)
        self.addCleanup(writer.close)
        calls = []

        def write_during_snapshot(tx):
            calls.append(True)
            return rewrite_with_children(tx)

        with self.store.snapshot() as view:
            self.assertEqual(view.get(entity_ref(initial)), initial)
            self.assertEqual(view.watchers(WATCH_KEY), [])
            result = writer.execute(command, write_during_snapshot)
            self.assert_failure(result, "E_STORAGE_UNAVAILABLE")
            self.assertEqual(calls, [True], "The reader should block commit, not the initial write lock.")
            self.assertEqual(view.get(entity_ref(initial)), initial)
            self.assertEqual(view.history(entity_ref(initial)), [initial])
            self.assertEqual(view.watchers(WATCH_KEY), [])
            with self.assertRaises(StorageError) as error:
                view.command_receipt(command["idempotency_key"])
            self.assertEqual(error.exception.code, "E_NOT_FOUND")
        self.assertEqual(self.store.get(entity_ref(initial)), initial)
        self.assert_missing(entity_ref(record_input("observation", "snapshot-child")))
        self.assert_missing(projection_ref("snapshot-alias"))
        with self.assertRaises(StorageError) as error:
            self.store.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")
        result = writer.execute(command, write_during_snapshot)
        self.assertEqual(result["status"], "success")
        self.assertEqual(calls, [True, True])
        self.assertEqual(self.store.get(entity_ref(initial))["revision"], 2)
        self.assertEqual(len(self.store.watchers(WATCH_KEY)), 1)
        self.assert_journal(command, result)

    def test_projection_revisions_keep_history_and_replace_watch_registrations_atomically(self):
        initial, _, _ = self.seed()
        alias_ref = projection_ref("stable-alias")
        command = create_command("first-projection", initial["id"], expected_revisions=[pin(initial)])

        def create_projection(tx):
            matter = tx.get(entity_ref(initial))
            tx.put_projection(alias_ref, domain_value({"target": entity_ref(matter), "label": "first"}),
                              watch_keys=(WATCH_KEY,))
            return tx.success("existing", {"matter": pin(matter)})

        first_result = self.store.execute(command, create_projection)
        self.assertEqual(first_result["status"], "success")
        first = self.store.get(alias_ref)
        changed_watch = "watch:changed"
        update = create_command("update-projection", initial["id"],
                                expected_revisions=[pin(initial), pin(first)])

        def update_projection(tx):
            matter = tx.get(entity_ref(initial))
            tx.get(alias_ref)
            tx.put_projection(alias_ref, domain_value({"target": entity_ref(matter), "label": "second"}),
                              watch_keys=(changed_watch,))
            return tx.success("existing", {"matter": pin(matter)})

        result = self.store.execute(update, update_projection)
        self.assertEqual(result["status"], "success")
        current = self.store.get(alias_ref)
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["creation_receipt"], first["creation_receipt"])
        self.assertEqual(current["value"]["value"]["label"], "second")
        self.assertEqual(self.store.history(alias_ref), [first, current])
        self.assertEqual(self.store.get(pin(first)), first)
        self.assertEqual(self.store.watchers(WATCH_KEY), [])
        self.assertEqual(self.store.watchers(changed_watch), [current])
        self.assertEqual(self.store.receipt_for(pin(first)), self.assert_journal(command, first_result)["receipt"])
        self.assertEqual(self.store.receipt_for(pin(current)), self.assert_journal(update, result)["receipt"])
        stale = create_command("stale-projection", initial["id"],
                               expected_revisions=[pin(initial), pin(first)])
        calls = []
        failure = self.store.execute(stale, lambda tx: calls.append(True))
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(alias_ref), current)
        self.assertEqual(self.store.watchers(changed_watch), [current])

    def test_transaction_watch_reads_require_pins_for_existing_projection_rows(self):
        initial, _, _ = self.seed()
        command = mutation_command("with-watch", initial, label="Watch target",
                                   child_id="watch-child", projection_id="watch-alias")
        self.assertEqual(self.store.execute(command, rewrite_with_children)["status"], "success")
        current = self.store.get(entity_ref(initial))
        projection = self.store.get(projection_ref("watch-alias"))
        missing = create_command("missing-watch-pin", initial["id"], expected_revisions=[pin(current)])

        def read_watch(tx):
            matter = tx.get(entity_ref(current))
            tx.watchers(WATCH_KEY)
            return tx.success("existing", {"matter": pin(matter)})

        failure = self.store.execute(missing, read_watch)
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        declared = create_command("declared-watch-pin", initial["id"],
                                  expected_revisions=[pin(current), pin(projection)])
        success = self.store.execute(declared, read_watch)
        self.assertEqual(success["status"], "success")

    def test_invalid_commands_and_invalid_handler_results_do_not_commit(self):
        command = create_command("invalid-wire", "invalid-subject")
        del command["authority"]
        calls = []
        with self.assertRaises(ContractError):
            self.store.execute(command, lambda tx: calls.append(True))
        self.assertEqual(calls, [])
        command = create_command("invalid-result", "invalid-result-subject")

        def invalid_result(tx):
            tx.insert(tx.command["body"]["matter"])
            return {"status": "success", "outcome": "created"}

        result = self.store.execute(command, invalid_result)
        self.assert_failure(result, "E_SCHEMA_INVALID")
        self.assert_missing(entity_ref(command["body"]["matter"]))
        self.assert_journal(command, result)

    def test_records_results_history_and_transaction_command_are_defensive_copies(self):
        initial, command, result = self.seed()
        read = self.store.get(entity_ref(initial))
        read["body"]["title"] = "Uncommitted external mutation"
        history = self.store.history(entity_ref(initial))
        history[0]["body"].clear()
        journal = self.store.command_receipt(command["idempotency_key"])
        journal["result"]["body"].clear()
        self.assertEqual(self.store.get(entity_ref(initial)), initial)
        self.assertEqual(self.store.history(entity_ref(initial)), [initial])
        self.assertEqual(self.store.command_receipt(command["idempotency_key"])["result"], result)
        next_command = create_command("defensive-command", "new-subject", title="Intended title")

        def handler(tx):
            external = tx.command
            external["body"]["matter"]["body"]["title"] = "Forged handler copy"
            return create_matter(tx)

        result = self.store.execute(next_command, handler)
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.store.get(result["body"]["matter"])["body"]["title"], "Intended title")

    def test_unavailable_database_queries_raise_errors_instead_of_empty_results(self):
        initial, command, _ = self.seed()
        # No live snapshot or raw connection is held; each port read opens its
        # own connection. Corrupting this temporary file simulates a real I/O
        # admission failure, not an absent application record.
        self.path.write_bytes(b"This is not a SQLite database.\n")
        queries = (
            lambda: self.store.get(entity_ref(initial)),
            lambda: self.store.history(entity_ref(initial)),
            lambda: self.store.watchers(WATCH_KEY),
            lambda: self.store.command_receipt(command["idempotency_key"]),
        )
        for query in queries:
            with self.subTest(query=query), self.assertRaises(StorageError) as error:
                query()
            self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")

    def test_busy_writer_returns_unavailable_and_exact_retry_can_commit(self):
        constrained = SQLiteStore(self.path, scope_id=SCOPE, timeout=0.02)
        self.addCleanup(constrained.close)
        command = create_command("busy-command", "busy-subject")
        calls = []
        with sqlite3.connect(self.path, isolation_level=None) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            try:
                result = constrained.execute(command, lambda tx: calls.append(True))
                self.assert_failure(result, "E_STORAGE_UNAVAILABLE")
                self.assertEqual(calls, [])
            finally:
                blocker.rollback()
        self.assert_missing(entity_ref(command["body"]["matter"]))
        with self.assertRaises(StorageError) as error:
            self.store.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")
        result = constrained.execute(command, create_matter)
        self.assertEqual(result["status"], "success")
        self.assert_journal(command, result)


if __name__ == "__main__":
    unittest.main()
