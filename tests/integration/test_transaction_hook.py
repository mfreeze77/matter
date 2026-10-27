"""Trusted observers share commit/rollback while ordinary reads stay strict."""

from pathlib import Path
import tempfile
import unittest

from matter.storage import SQLiteStore, StorageError, entity_ref, pin
from integration.helpers import (
    SCOPE, WATCH_KEY, create_command, create_matter, domain_value,
    mutation_command, projection_ref, rewrite_with_children,
)


class TransactionHookTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "matter.sqlite"
        self.store = SQLiteStore(self.path, scope_id=SCOPE)
        self.addCleanup(self.store.close)
        result = self.store.execute(create_command("seed", "subject"), create_matter)
        self.original = self.store.get(result["body"]["matter"])

    def reopen(self, hook):
        self.store.close()
        self.store = SQLiteStore(self.path, scope_id=SCOPE, transaction_hook=hook)
        self.addCleanup(self.store.close)

    def test_hook_writes_atomically_audits_reads_and_is_not_replayed(self):
        held, notices = [], []
        target = projection_ref("derived")

        def hook(tx, changes):
            held.append(tx)
            notices.extend(changes)
            current = tx.get(entity_ref(self.original))
            self.assertEqual(current["revision"], 2)
            watched = tx.watchers(WATCH_KEY)
            self.assertEqual(len(watched), 1)
            tx.put_projection(target, domain_value({"dependency": pin(current)}))

        self.reopen(hook)
        command = mutation_command("edit", self.original, label="changed", child_id="child", projection_id="index")
        result = self.store.execute(command, rewrite_with_children)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(notices[0]["before"], [pin(self.original)])
        self.assertEqual(notices[0]["after"], [result["body"]["matter"]])
        derived = self.store.get(target)
        receipt = self.store.receipt_for(pin(derived))
        self.assertIn(pin(derived), receipt["body"]["evidence"])
        self.assertEqual(receipt["body"]["details"]["value"]["read_set"], command["expected_revisions"])
        self.assertIn(WATCH_KEY, receipt["body"]["details"]["value"]["watch_queries"])
        self.assertEqual(self.store.execute(command, rewrite_with_children), result)
        self.assertEqual(len(held), 1)
        with self.assertRaises(StorageError):
            held[0].get(entity_ref(self.original))

    def test_system_preexisting_reads_are_evidence_without_mutating_command(self):
        target = projection_ref("derived")
        def hook(tx, changes):
            self.assertEqual(tx.lookup_identity(entity_ref(self.original)), self.original)
            tx.put_projection(target, domain_value({"source": pin(tx.get(pin(self.original)))}))
        self.reopen(hook)
        command = create_command("other", "other")
        result = self.store.execute(command, create_matter)
        self.assertEqual(result["status"], "success", result)
        journal = self.store.command_receipt(command["idempotency_key"])
        self.assertEqual(journal["command"], command)
        receipt = self.store.receipt_for(pin(self.store.get(target)))
        self.assertIn(pin(self.original), receipt["body"]["evidence"])
        self.assertEqual(receipt["body"]["details"]["value"]["read_set"], [])

    def test_refused_hook_rolls_back_all_children_and_keeps_failure_journal(self):
        target = projection_ref("refused")
        def hook(tx, changes):
            created = tx.put_projection(target, domain_value({"partial": True}))
            tx.get(pin(created))
            raise StorageError("E_DEPENDENCY_STALE")
        self.reopen(hook)
        command = create_command("refusal", "other")
        result = self.store.execute(command, create_matter)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        for reference in (target, entity_ref(command["body"]["matter"])):
            with self.assertRaises(StorageError):
                self.store.get(reference)
        self.assertEqual(self.store.command_receipt(command["idempotency_key"])["result"], result)
        failure_receipt = self.store.command_receipt(command["idempotency_key"])["receipt"]
        self.assertNotIn(target["id"], [ref["id"] for ref in failure_receipt["body"]["evidence"]])
        self.assertEqual(self.store.get(entity_ref(self.original)), self.original)

    def test_unexpected_failure_rolls_back_without_failure_journal(self):
        def hook(tx, changes):
            raise RuntimeError("injected")
        self.reopen(hook)
        command = create_command("crash", "other")
        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.store.execute(command, create_matter)
        with self.assertRaises(StorageError):
            self.store.command_receipt(command["idempotency_key"])
        with self.assertRaises(StorageError):
            self.store.get(entity_ref(command["body"]["matter"]))

    def test_handler_cannot_borrow_system_reads_and_hook_never_runs_on_failure(self):
        calls = []
        self.reopen(lambda tx, changes: calls.append(True))
        def handler(tx):
            tx.get(entity_ref(self.original))
        result = self.store.execute(create_command("missing-declaration", "other"), handler)
        self.assertEqual(result["error"]["code"], "E_REVISION_CONFLICT")
        self.assertEqual(calls, [])

    def test_system_watch_limit_refuses_oversized_cohort_without_partial_effects(self):
        def seed(tx):
            result = create_matter(tx)
            for index in range(3):
                tx.put_projection(projection_ref("watch-" + str(index)), domain_value({"index": index}), watch_keys=(WATCH_KEY,))
            return result
        seeded = self.store.execute(create_command("watch-seed", "watch-seed"), seed)
        self.assertEqual(seeded["status"], "success", seeded)
        self.reopen(lambda tx, changes: tx.watchers(WATCH_KEY, limit=2))
        refused = self.store.execute(create_command("too-many", "must-not-exist"), create_matter)
        self.assertEqual(refused["error"]["code"], "E_BUDGET_EXHAUSTED")
        with self.assertRaises(StorageError):
            self.store.get(entity_ref(create_command("unused", "must-not-exist")["body"]["matter"]))
        observed = []
        def bounded(tx, changes):
            observed.extend(tx.watchers(WATCH_KEY, limit=3))
        self.reopen(bounded)
        accepted = self.store.execute(create_command("exact-limit", "accepted"), create_matter)
        self.assertEqual(accepted["status"], "success", accepted)
        self.assertEqual([row["value"]["value"]["index"] for row in observed], [0, 1, 2])

    def test_system_watch_limit_must_be_a_bounded_integer(self):
        for index, limit in enumerate((0, -1, True, "2", None, 4097)):
            with self.subTest(limit=limit):
                self.reopen(lambda tx, changes: tx.watchers(WATCH_KEY, limit=limit))
                result = self.store.execute(create_command("bad-limit-" + str(index), "new-" + str(index)), create_matter)
                self.assertEqual(result["error"]["code"], "E_SCHEMA_INVALID")

    def test_hook_cannot_cross_scope_or_escape_phase_or_return_decisions(self):
        def cross_scope(tx, changes):
            tx.get({**entity_ref(self.original), "scope_id": "other"})
        self.reopen(cross_scope)
        result = self.store.execute(create_command("cross", "other"), create_matter)
        self.assertEqual(result["error"]["code"], "E_SCOPE_FORBIDDEN")
        self.reopen(lambda tx, changes: False)
        result = self.store.execute(create_command("decision", "another"), create_matter)
        self.assertEqual(result["error"]["code"], "E_POLICY_INVALID")

    def test_preexisting_watch_reads_are_audited_and_watch_replacement_is_atomic(self):
        target = projection_ref("preexisting-watcher")
        replacement_key = "watch:replacement"
        refused_key = "watch:refused"
        def seed(tx):
            stored = tx.insert(tx.command["body"]["matter"])
            tx.put_projection(target, domain_value({"state": "original"}), watch_keys=(WATCH_KEY,))
            return tx.success("created", {"matter": pin(stored)})
        self.store.execute(create_command("watch-seed", "watch-seed-subject"), seed)
        original = self.store.get(target)
        def hook(tx, changes):
            self.assertEqual(tx.watchers(WATCH_KEY), [original])
            tx.put_projection(target, domain_value({"state": "updated"}), watch_keys=(replacement_key,))
        self.reopen(hook)
        command = create_command("watch-hook", "watch-hook-subject")
        result = self.store.execute(command, create_matter)
        self.assertEqual(result["status"], "success", result)
        current = self.store.get(target)
        self.assertEqual(current["revision"], original["revision"] + 1)
        self.assertEqual(self.store.watchers(WATCH_KEY), [])
        self.assertEqual(self.store.watchers(replacement_key), [current])
        journal = self.store.command_receipt(command["idempotency_key"])
        self.assertEqual(journal["command"], command)
        self.assertEqual(journal["receipt"]["body"]["details"]["value"]["read_set"], [])
        self.assertIn(pin(original), journal["receipt"]["body"]["evidence"])
        self.assertIn(pin(current), journal["receipt"]["body"]["evidence"])
        def refuse(tx, changes):
            tx.put_projection(target, domain_value({"state": "refused"}), watch_keys=(refused_key,))
            raise StorageError("E_DEPENDENCY_STALE")
        self.reopen(refuse)
        refused = self.store.execute(create_command("watch-refusal", "watch-refusal-subject"), create_matter)
        self.assertEqual(refused["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.store.get(target), current)
        self.assertEqual(self.store.watchers(replacement_key), [current])
        self.assertEqual(self.store.watchers(refused_key), [])

    def test_every_public_held_system_port_operation_is_closed_after_hook_phase(self):
        held = []
        self.reopen(lambda tx, changes: held.append(tx))
        result = self.store.execute(create_command("held-port", "held-subject"), create_matter)
        self.assertEqual(result["status"], "success", result)
        target = projection_ref("held-target")
        operations = {
            "command": lambda: held[0].command,
            "receipt_ref": lambda: held[0].receipt_ref,
            "get": lambda: held[0].get(entity_ref(self.original)),
            "lookup_identity": lambda: held[0].lookup_identity(entity_ref(self.original)),
            "watchers": lambda: held[0].watchers(WATCH_KEY),
            "put_projection": lambda: held[0].put_projection(target, domain_value({"bad": True})),
        }
        for name, operation in operations.items():
            with self.subTest(operation=name):
                with self.assertRaises(StorageError) as error:
                    operation()
                self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
