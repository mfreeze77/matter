"""Real concurrent writers and process interruption protect absence decisions."""

from matter.source_catalogs import source_catalog_ref, source_key
from matter.storage import StorageError, entity_ref, pin

from association_helpers import SCOPE
from coverage_helpers import (
    T3, CoverageTestCase, member, publish_command, register_command, specification,
)


class CoverageAtomicityTests(CoverageTestCase):
    def test_arrival_after_watch_preparation_cannot_commit_current_absence(self):
        covered, _, _ = self.publish_coverage()
        target = self.host_projection("dependent")
        command = register_command("prepared-watch", self.authority, self.coverage_policy, target, covered)
        prepared = self.coverage.prepare(command)
        observed, _, _ = self.arrival("arrived-before-registration", available_at=T3)
        result = self.coverage.register(prepared)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(self.coverage.register(prepared), result)
        watch, _, _ = self.register_watch(covered, identity="fresh-watch", target=target)
        self.assertNotEqual(self.value(watch)["status"], "current")
        self.assertIn(pin(observed), self.value(watch)["matches"])

    def test_first_watch_after_intake_preparation_cannot_be_missed_by_arrival(self):
        covered, _, _ = self.publish_coverage()
        command, payload = self.arrival_command("prepared-before-first-watch", available_at=T3)
        prepared = self.ingestor.prepare(command)
        watch, _, _ = self.register_watch(covered)
        result = self.ingestor.ingest(prepared, payload=payload)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(self.current(watch), watch)
        with self.assertRaises(StorageError) as error:
            self.storage.get(entity_ref(command["body"]["observation"]))
        self.assertEqual(error.exception.code, "E_NOT_FOUND")
        fresh, fresh_payload = self.arrival_command("fresh-after-first-watch", available_at=T3)
        result = self.ingestor.ingest(self.ingestor.prepare(fresh), payload=fresh_payload)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.value(self.current(watch))["status"], "invalidated")
        self.assertEqual(self.value(self.current(watch))["matches"], [result["body"]["observation"]])

    def test_new_catalog_arrival_invalidates_prepared_empty_replacement(self):
        covered, _, _ = self.publish_coverage()
        command = publish_command("prepared-replacement", self.authority, self.coverage_policy,
                                  specification(), previous=covered)
        prepared = self.coverage.prepare(command)
        self.arrival("catalog-phantom")
        result = self.coverage.publish(prepared)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(self.current(covered), covered)

    def test_two_processes_replacing_same_coverage_have_one_revision_winner(self):
        first, second = self.host_projection("first"), self.host_projection("second")
        covered, _, _ = self.publish_coverage(members=[member(first), member(second)])
        commands = [self.coverage.prepare(publish_command(label, self.authority, self.coverage_policy,
                        specification(), previous=covered, members=[member(record)]))
                    for label, record in (("keep-first", first), ("keep-second", second))]
        results = self.competing(commands)
        successes = [result for result in results.values() if result["status"] == "success"]
        failures = [result for result in results.values() if result["status"] == "failure"]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(failures), 1, results)
        self.assert_failure(failures[0], "E_REVISION_CONFLICT")
        current = self.current(covered)
        self.assertEqual(current["revision"], covered["revision"] + 1)
        self.assertEqual(sorted(item["status"] for item in self.member_states(current).values()), ["active", "retired"])
        for command in commands:
            self.assertEqual(self.coverage.publish(command), results[command["command_id"]])
        for record in (first, second):
            self.assertEqual(self.current(record), record)

    def test_replacement_process_exit_preserves_atomic_membership_and_exact_receipt(self):
        for stage in ("before_commit", "after_commit"):
            with self.subTest(stage=stage):
                derived = self.host_projection(f"derived-{stage}")
                spec = specification(sources=[f"example:replacement-{stage}"])
                covered, _, _ = self.publish_coverage(command_id=f"initial-{stage}", spec=spec,
                                                       members=[member(derived)])
                command = self.coverage.prepare(publish_command(f"replace-{stage}", self.authority,
                    self.coverage_policy, spec, previous=covered))
                self.crash(command, stage)
                if stage == "before_commit":
                    self.assert_no_journal(command)
                    self.assertEqual(self.current(covered), covered)
                    result = self.coverage.publish(command)
                else:
                    result = self.storage.command_receipt(command["idempotency_key"])["result"]
                self.assertEqual(result["status"], "success", result)
                replaced = self.current(covered)
                self.assertEqual(self.member_states(replaced)[derived["id"]]["status"], "retired")
                self.assertEqual(self.storage.receipt_for(pin(replaced))["id"], result["receipt"]["id"])
                self.assertEqual(self.storage.get(pin(covered)), covered)
                self.assertEqual(self.current(derived), derived)
                self.assertEqual(self.coverage.publish(command), result)

    def test_intake_process_exit_preserves_observation_catalog_and_all_watch_changes(self):
        for stage in ("before_commit", "after_commit"):
            with self.subTest(stage=stage):
                source = f"example:intake-{stage}"
                covered, _, _ = self.publish_coverage(command_id=f"coverage-{stage}",
                                                       spec=specification(sources=[source]))
                first, _, _ = self.register_watch(covered, identity=f"first-{stage}")
                second, _, _ = self.register_watch(covered, identity=f"second-{stage}")
                catalog_ref = source_catalog_ref(SCOPE, source_key(source))
                before_catalog = self.storage.get(catalog_ref)
                command, payload = self.arrival_command(stage, source=source, available_at=T3)
                prepared = self.ingestor.prepare(command)
                self.crash(prepared, stage, payload=payload)
                if stage == "before_commit":
                    self.assert_no_journal(prepared)
                    self.assertEqual(self.storage.get(catalog_ref), before_catalog)
                    self.assertEqual([self.current(item) for item in (first, second)], [first, second])
                    with self.assertRaises(StorageError) as error:
                        self.storage.get(entity_ref(command["body"]["observation"]))
                    self.assertEqual(error.exception.code, "E_NOT_FOUND")
                    result = self.ingestor.ingest(prepared, payload=payload)
                else:
                    result = self.storage.command_receipt(prepared["idempotency_key"])["result"]
                self.assertEqual(result["status"], "success", result)
                observation = self.storage.get(result["body"]["observation"])
                catalog = self.storage.get(catalog_ref)
                self.assertEqual(self.storage.receipt_for(pin(observation))["id"], result["receipt"]["id"])
                self.assertEqual(self.storage.receipt_for(pin(catalog))["id"], result["receipt"]["id"])
                for old in (first, second):
                    updated = self.current(old)
                    self.assertEqual(updated["revision"], old["revision"] + 1)
                    self.assertEqual(self.value(updated)["status"], "invalidated")
                    self.assertEqual(self.value(updated)["matches"], [pin(observation)])
                    self.assertEqual(self.storage.receipt_for(pin(updated))["id"], result["receipt"]["id"])
                self.assertEqual(self.ingestor.ingest(prepared), result)
