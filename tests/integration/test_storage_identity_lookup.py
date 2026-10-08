"""Current identity occupancy without weakening typed or revision-checked reads."""

from pathlib import Path
import tempfile
import unittest

from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from integration.helpers import (
    SCOPE, create_command, create_matter, domain_value, ingest_command,
    ingest_observation, projection_ref, record_input,
)


class StorageIdentityLookupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = SQLiteStore(Path(self.directory.name) / "matter.sqlite", scope_id=SCOPE)
        self.addCleanup(self.store.close)
        result = self.store.execute(create_command("seed", "subject"), create_matter)
        self.assertEqual(result["status"], "success")
        self.matter = self.store.get(result["body"]["matter"])
        self.wrong_kind = {**entity_ref(self.matter), "record_type": "observation"}

    def assert_error(self, callback, code):
        with self.assertRaises(StorageError) as error:
            callback()
        self.assertEqual(error.exception.code, code)

    def test_lookup_returns_actual_current_kind_and_does_not_change_typed_get(self):
        self.assertEqual(self.store.lookup_identity(self.wrong_kind), self.matter)
        self.assert_error(lambda: self.store.get(self.wrong_kind), "E_NOT_FOUND")
        with self.store.snapshot() as view:
            found = view.lookup_identity(self.wrong_kind)
            found["body"]["title"] = "Caller-owned copy"
            self.assertEqual(view.lookup_identity(self.wrong_kind), self.matter)
        command = create_command("advance", "subject", expected_revisions=[pin(self.matter)])

        def advance(tx):
            current = tx.lookup_identity(self.wrong_kind)
            current["revision"] += 1
            current["body"]["title"] = "Revision two"
            return tx.success("existing", {"matter": pin(tx.replace(current))})

        self.assertEqual(self.store.execute(command, advance)["status"], "success")
        current = self.store.lookup_identity(self.wrong_kind)
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["body"]["title"], "Revision two")
        self.assertEqual(self.store.get(pin(self.matter)), self.matter)

    def test_transaction_checks_the_actual_immutable_occupant_pin(self):
        result = self.store.execute(ingest_command("seed-observation", "occupied"), ingest_observation)
        original = self.store.get(result["body"]["observation"])
        proposed = {**entity_ref(original), "record_type": "matter"}
        command = create_command("refuse-occupied", "occupied", expected_revisions=[pin(original)])
        seen = []

        def refuse(tx):
            occupant = tx.lookup_identity(proposed)
            seen.append(occupant)
            raise StorageError("E_SOURCE_IDENTITY_CONFLICT", affected_references=(entity_ref(occupant),))

        refused = self.store.execute(command, refuse)
        self.assertEqual(refused["error"]["code"], "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(seen, [original])
        self.assertEqual(refused["error"]["affected_references"], [entity_ref(original)])
        receipt = self.store.command_receipt(command["idempotency_key"])["receipt"]
        self.assertEqual(receipt["body"]["details"]["value"]["read_set"], [pin(original)])
        self.assertIn(pin(original), receipt["body"]["evidence"])
        self.assertEqual(receipt["body"]["details"]["value"]["writes"], [])

    def test_undeclared_occupant_read_refuses_and_rolls_back_child_writes(self):
        command = create_command("undeclared", "unused")
        child = record_input("observation", "rolled-back-child")

        def bypass(tx):
            tx.insert(child)
            tx.lookup_identity(self.wrong_kind)
            self.fail("The undeclared occupant must not reach the handler.")

        result = self.store.execute(command, bypass)
        self.assertEqual(result["error"]["code"], "E_REVISION_CONFLICT")
        self.assert_error(lambda: self.store.get(entity_ref(child)), "E_NOT_FOUND")
        details = self.store.command_receipt(command["idempotency_key"])["receipt"]["body"]["details"]["value"]
        self.assertEqual(details["writes"], [])
        self.assertEqual(details["absent_reads"], [])

    def test_occupant_appearing_after_absent_preparation_is_a_revision_conflict(self):
        pending = create_command("prepared-before-occupant", "raced")
        reference = entity_ref(pending["body"]["matter"])
        with self.store.snapshot() as view:
            self.assert_error(lambda: view.lookup_identity(reference), "E_NOT_FOUND")
        with SQLiteStore(self.store.path, scope_id=SCOPE) as competing:
            self.assertEqual(
                competing.execute(ingest_command("race-winner", "raced"), ingest_observation)["status"],
                "success",
            )
        result = self.store.execute(pending, lambda tx: tx.lookup_identity(reference))
        self.assertEqual(result["error"]["code"], "E_REVISION_CONFLICT")
        self.assertEqual(self.store.lookup_identity(reference)["record_type"], "observation")
        self.assertEqual(self.store.execute(pending, lambda tx: self.fail("Exact replay ran its handler.")), result)

    def test_transaction_can_lookup_its_own_new_records_and_projections(self):
        command = create_command("own-writes", "fresh")
        projection = projection_ref("fresh-projection")

        def write_and_read(tx):
            matter = tx.insert(tx.command["body"]["matter"])
            projected = tx.put_projection(projection, domain_value({"target": entity_ref(matter)}))
            wrong_matter = {**entity_ref(matter), "record_type": "receipt"}
            wrong_projection = {**projection, "record_type": "observation"}
            self.assertEqual(tx.lookup_identity(wrong_matter), matter)
            self.assertEqual(tx.lookup_identity(wrong_projection), projected)
            changed = tx.lookup_identity(wrong_matter)
            changed["body"].clear()
            self.assertEqual(tx.lookup_identity(wrong_matter), matter)
            return tx.success("created", {"matter": pin(matter)})

        result = self.store.execute(command, write_and_read)
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.store.lookup_identity(projection)["record_type"], "matter:projection")

    def test_foreign_scope_is_refused_without_an_absence_receipt(self):
        foreign = {**self.wrong_kind, "scope_id": "another:scope"}
        with SQLiteStore(self.store.path, scope_id=foreign["scope_id"]) as other:
            self.assertEqual(other.execute(create_command("foreign-seed", "subject", scope_id=foreign["scope_id"]), create_matter)["status"], "success")
        self.assert_error(lambda: self.store.lookup_identity(foreign), "E_SCOPE_FORBIDDEN")
        command = create_command("foreign-read", "unused")
        result = self.store.execute(command, lambda tx: tx.lookup_identity(foreign))
        self.assertEqual(result["error"]["code"], "E_SCOPE_FORBIDDEN")
        self.assertEqual(result["error"]["affected_references"], [])
        details = self.store.command_receipt(command["idempotency_key"])["receipt"]["body"]["details"]["value"]
        self.assertEqual(details["absent_reads"], [])

    def test_lookup_accepts_bare_references_only(self):
        invalid = [pin(self.matter), {**entity_ref(self.matter), "digest": "a" * 64}]
        for index, reference in enumerate(invalid):
            with self.subTest(reference=reference):
                self.assert_error(lambda: self.store.lookup_identity(reference), "E_SCHEMA_INVALID")
                command = create_command(f"pinned-lookup-{index}", "subject", expected_revisions=[pin(self.matter)])
                result = self.store.execute(command, lambda tx: tx.lookup_identity(reference))
                self.assertEqual(result["error"]["code"], "E_SCHEMA_INVALID")

    def test_closed_snapshot_and_transaction_cannot_be_used_for_identity_lookup(self):
        retained = []
        command = create_command("retained-view", "subject", expected_revisions=[pin(self.matter)])

        def read(tx):
            retained.append(tx)
            return tx.success("existing", {"matter": pin(tx.lookup_identity(self.wrong_kind))})

        self.assertEqual(self.store.execute(command, read)["status"], "success")
        with self.store.snapshot() as view:
            retained.append(view)
        for view in retained:
            self.assert_error(lambda: view.lookup_identity(self.wrong_kind), "E_STORAGE_UNAVAILABLE")

    def test_absence_is_audited_with_the_supplied_bare_identity_on_success_and_failure(self):
        command = create_command("absent-then-create", "new-identity")
        reference = {**entity_ref(command["body"]["matter"]), "record_type": "observation"}

        def create_after_absence(tx):
            self.assert_error(lambda: tx.lookup_identity(reference), "E_NOT_FOUND")
            return tx.success("created", {"matter": pin(tx.insert(tx.command["body"]["matter"]))})

        result = self.store.execute(command, create_after_absence)
        self.assertEqual(result["status"], "success")
        details = self.store.command_receipt(command["idempotency_key"])["receipt"]["body"]["details"]["value"]
        self.assertEqual(details["absent_reads"], [reference])
        self.assertEqual(details["read_set"], [])
        self.assertEqual(self.store.lookup_identity(reference)["record_type"], "matter")
        missing = {**reference, "id": "still-missing"}
        command = create_command("durable-absence", "unused")
        failure = self.store.execute(command, lambda tx: tx.lookup_identity(missing))
        self.assertEqual(failure["error"]["code"], "E_NOT_FOUND")
        details = self.store.command_receipt(command["idempotency_key"])["receipt"]["body"]["details"]["value"]
        self.assertEqual(details["absent_reads"], [missing])
        self.assertEqual(details["writes"], [])


if __name__ == "__main__":
    unittest.main()
