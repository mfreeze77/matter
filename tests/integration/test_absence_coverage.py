"""Covered absence remains distinct from silence and immutable source evidence."""

from copy import deepcopy

from matter.coverage import CoverageService
from matter.negative_dependencies import negative_status, require_current_negative_dependency
from matter.observations import ObservationIngestor
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from association_helpers import SCOPE
from coverage_helpers import (
    ADAPTER, OTHER_SOURCE, T1, T2, T3, T4, UNKNOWN,
    CoverageTestCase, member, policy_for, publish_command, register_command, specification,
)
from observation_helpers import known_time, redelivery


class AbsenceCoverageTests(CoverageTestCase):
    def test_empty_complete_partial_failed_and_not_expected_are_distinct(self):
        previous = None
        for status in ("complete", "partial", "failed", "not_expected_yet", "expected_not_published", "manual_review"):
            with self.subTest(status=status):
                covered, _, _ = self.publish_coverage(command_id=f"coverage-{status}", previous=previous, status=status)
                value = self.value(covered)
                self.assertEqual(value["result"], "adequate_empty" if status == "complete" else "unusable_coverage")
                self.assertEqual(value["matches"], [])
                watch, _, _ = self.register_watch(covered, identity=f"absence-{status}")
                self.assertEqual(self.value(watch)["status"], "current" if status == "complete" else "unusable_coverage")
                with self.storage.snapshot() as snapshot:
                    if status == "complete":
                        self.assertEqual(require_current_negative_dependency(snapshot, SCOPE, pin(watch), as_of=T2), watch)
                    else:
                        with self.assertRaises(StorageError) as error:
                            require_current_negative_dependency(snapshot, SCOPE, pin(watch), as_of=T2)
                        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
                previous = covered
        with SQLiteStore(self.database, scope_id=SCOPE) as restarted:
            self.assertEqual(restarted.get(pin(previous)), previous)
            self.assertEqual(self.value(restarted.get(pin(previous)))["coverage"]["reason"],
                             "Synthetic source collection reports manual_review.")

    def test_uninitialized_empty_or_populated_catalog_cannot_establish_absence(self):
        uninitialized, _, _ = self.publish_coverage(baselines=[])
        self.assertFalse(self.value(uninitialized)["history_complete"])
        self.assertEqual(self.value(uninitialized)["result"], "unusable_coverage")
        self.arrival("unrelated-unattested-history", source=OTHER_SOURCE, event="other-event")
        other, _, _ = self.publish_coverage(command_id="incomplete-history",
            spec=specification(sources=[OTHER_SOURCE]), baselines=[])
        self.assertFalse(self.value(other)["history_complete"])
        self.assertEqual(self.value(other)["result"], "unusable_coverage")

    def test_only_complete_replacement_retires_omitted_machine_members(self):
        machine, operator, reviewed, rejected = [self.host_projection(label)
                                                for label in ("machine", "operator", "reviewed", "rejected")]
        subject = self.matter("unresolved-subject")
        covered, _, _ = self.publish_coverage(members=[member(machine), member(operator, "operator"),
            member(reviewed, "reviewed"), member(rejected, "rejected")])
        for label, status, mode in (("partial", "partial", "replacement"), ("failed", "failed", "replacement"),
                                    ("incremental", "complete", "incremental")):
            covered, _, _ = self.publish_coverage(command_id=f"silent-{label}", previous=covered,
                                                  status=status, mode=mode)
            states = self.member_states(covered)
            self.assertEqual(states["machine"]["status"], "active")
            self.assertEqual(states["rejected"]["status"], "rejected")
            self.assertEqual(self.current(subject), subject)
        retired, command, result = self.publish_coverage(command_id="complete-replacement", previous=covered)
        states = self.member_states(retired)
        self.assertEqual(states["machine"]["status"], "retired")
        self.assertEqual(states["operator"]["status"], "active")
        self.assertEqual(states["reviewed"]["status"], "active")
        self.assertTrue(states["reviewed"]["review_required"])
        self.assertEqual(states["rejected"]["status"], "rejected")
        for record in (machine, operator, reviewed, rejected, subject):
            self.assertEqual(self.current(record), record)
            self.assertEqual(self.storage.history(entity_ref(record)), [record])
        self.assertEqual(self.coverage.publish(command), result)
        self.assertEqual(self.current(retired), retired)

    def test_disabled_retirement_and_neighboring_scopes_preserve_membership(self):
        first, second = self.host_projection("first"), self.host_projection("second")
        narrow, _, _ = self.publish_coverage(members=[member(first)])
        neighbor, _, _ = self.publish_coverage(command_id="neighbor", spec=specification(event="other-event"),
                                               members=[member(second)], baselines=[])
        policy = policy_for(self.authority, allow_retirement=False)
        service = CoverageService(self.storage, policy=policy)
        retained, _, _ = self.publish_coverage(command_id="forbidden-retirement", previous=narrow,
                                                service=service, policy=policy)
        self.assertEqual(self.member_states(retained)["first"]["status"], "active")
        self.assertEqual(self.current(neighbor), neighbor)
        retired, _, _ = self.publish_coverage(command_id="retire-own-scope", previous=retained)
        self.assertEqual(self.member_states(retired)["first"]["status"], "retired")
        self.assertEqual(self.member_states(self.current(neighbor))["second"]["status"], "active")

    def test_operator_and_rejected_ownership_cannot_be_demoted_or_resurrected(self):
        operator, rejected = self.host_projection("operator"), self.host_projection("rejected")
        covered, _, _ = self.publish_coverage(members=[member(operator, "operator"), member(rejected, "rejected")])
        for target in (operator, rejected):
            command = publish_command(f"demote-{target['id']}", self.authority, self.coverage_policy,
                specification(), previous=covered, members=[member(target)])
            self.assert_refused(self.coverage.prepare, self.coverage.publish, command, "E_AUTHORITY_REQUIRED")
            self.assertEqual(self.current(covered), covered)
        retained, _, _ = self.publish_coverage(command_id="retain-rejection", previous=covered,
                                                members=[member(rejected, "rejected")])
        self.assertEqual(self.member_states(retained)["rejected"]["status"], "rejected")

    def test_late_cancellation_changes_current_watch_without_rewriting_yesterday(self):
        covered, coverage_command, coverage_result = self.publish_coverage()
        watch, watch_command, watch_result = self.register_watch(covered)
        cancellation, _, result = self.arrival("late-cancellation", available_at=T3, occurred_at=T1)
        invalidated = self.current(watch)
        self.assertEqual(self.value(invalidated)["status"], "invalidated")
        self.assertEqual(self.value(invalidated)["matches"], [pin(cancellation)])
        self.assertEqual(invalidated["revision"], watch["revision"] + 1)
        self.assertTrue(any(change["cause"] == "negative_scope_arrival" and pin(invalidated) in change["after"]
                            for change in result["body"]["changes"]))
        today, _, _ = self.publish_coverage(command_id="today", previous=covered, as_of=T3)
        self.assertEqual(self.value(today)["result"], "evidence_present")
        self.assertEqual(self.value(today)["matches"], [pin(cancellation)])
        self.assertEqual(self.storage.get(pin(covered)), covered)
        self.assertEqual(self.value(covered)["matches"], [])
        self.assertEqual(cancellation["body"]["occurred_at"], T1)
        self.assertEqual(cancellation["body"]["available_at"], T3)
        self.assertEqual(self.coverage.publish(coverage_command), coverage_result)
        self.assertEqual(self.coverage.register(watch_command), watch_result)
        self.assertEqual(self.current(watch), invalidated)
        self.assertEqual(self.current(covered), today)

    def test_known_availability_boundary_is_exact_and_unknown_time_is_not_ingestion(self):
        one_ns_early = known_time("2026-10-08T14:00:00.000000001Z")
        one_ns_later = known_time("2026-10-08T14:00:00.000000002Z")
        late, _, _ = self.arrival("nanosecond", available_at=one_ns_later)
        unknown, _, _ = self.arrival("unknown-event-time", occurred_at=UNKNOWN)
        covered, _, _ = self.publish_coverage(as_of=one_ns_early, observations=[late, unknown])
        self.assertEqual(self.value(covered)["matches"], [])
        self.assertEqual(self.value(covered)["indeterminate"], [pin(unknown)])
        self.assertIn(pin(late), self.value(covered)["excluded"])
        self.assertEqual(self.value(covered)["result"], "indeterminate")
        later, _, _ = self.publish_coverage(command_id="later-nanosecond", previous=covered, as_of=one_ns_later)
        self.assertIn(pin(late), self.value(later)["matches"])
        self.assertEqual(self.storage.get(pin(unknown))["body"]["occurred_at"], UNKNOWN)

    def test_interval_not_yet_observed_and_unknown_bounds_cannot_prove_absence(self):
        future, _, _ = self.publish_coverage(spec=specification(end=T3), as_of=T2)
        self.assertEqual(self.value(future)["result"], "unusable_coverage")
        unknown, _, _ = self.publish_coverage(command_id="unknown-window", spec=specification(start=UNKNOWN), baselines=[])
        self.assertEqual(self.value(unknown)["result"], "unusable_coverage")

    def test_narrow_watch_ignores_unrelated_arrivals_and_invalidates_all_matching_dependents(self):
        covered, _, _ = self.publish_coverage()
        first, _, _ = self.register_watch(covered, identity="first")
        second, _, _ = self.register_watch(covered, identity="second")
        for identity, arguments in (("wrong-event", {"event": "unrelated-event"}),
                                    ("wrong-source", {"source": OTHER_SOURCE}),
                                    ("outside-interval", {"occurred_at": T3})):
            with self.subTest(identity=identity):
                self.arrival(identity, **arguments)
                self.assertEqual(self.current(first), first)
                self.assertEqual(self.current(second), second)
                with self.storage.snapshot() as snapshot:
                    self.assertEqual(negative_status(snapshot, SCOPE, entity_ref(first), as_of=T2), "current")
                    self.assertEqual(negative_status(snapshot, SCOPE, entity_ref(second), as_of=T2), "current")
        match, command, result = self.arrival("never-known-observation-id", available_at=T3)
        after = [self.current(item) for item in (first, second)]
        for record in after:
            self.assertEqual(self.value(record)["status"], "invalidated")
            self.assertEqual(self.value(record)["matches"], [pin(match)])
        self.assertEqual(self.ingestor.ingest(command), result)
        original = deepcopy(command)
        retry = redelivery(original, "new-delivery", "new-proposed-id")
        retried = self.ingestor.ingest(self.ingestor.prepare(retry))
        self.assertEqual(retried["outcome"], "duplicate")
        self.assertEqual([self.current(item) for item in (first, second)], after)

    def test_unknown_relevant_arrival_stales_absence_without_claiming_positive_match(self):
        covered, _, _ = self.publish_coverage()
        watch, _, _ = self.register_watch(covered)
        unknown, _, _ = self.arrival("unknown-effective-time", occurred_at=UNKNOWN)
        updated = self.current(watch)
        self.assertNotEqual(self.value(updated)["status"], "current")
        self.assertEqual(self.value(updated)["matches"], [])
        self.assertEqual(self.value(updated)["indeterminate"], [pin(unknown)])
        with self.storage.snapshot() as snapshot:
            with self.assertRaises(StorageError) as error:
                require_current_negative_dependency(snapshot, SCOPE, entity_ref(watch), as_of=T3)
            self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")

    def test_predicate_extension_uses_exact_typed_value_and_missing_is_indeterminate(self):
        clause = {"field": "extension", "key": "example:flag", "schema": ADAPTER, "value": {"approved": 1}}
        covered, _, _ = self.publish_coverage(spec=specification(clauses=[clause]))
        watch, _, _ = self.register_watch(covered)
        self.arrival("boolean", extensions={"example:flag": {"schema": ADAPTER, "value": {"approved": True}}})
        self.assertEqual(self.current(watch), watch)
        exact, _, _ = self.arrival("integer", extensions={"example:flag": {"schema": ADAPTER, "value": {"approved": 1}}})
        self.assertEqual(self.value(self.current(watch))["matches"], [pin(exact)])
        missing, _, _ = self.arrival("missing-extension")
        current, _, _ = self.publish_coverage(command_id="inspect-missing", previous=covered,
                                               spec=specification(clauses=[clause]))
        self.assertIn(pin(missing), self.value(current)["indeterminate"])

    def test_clock_progression_only_changes_read_status_not_events_or_persisted_coverage(self):
        covered, _, _ = self.publish_coverage()
        watch, _, _ = self.register_watch(covered, next_check_at=T3, expires_at=T4)
        before = self.record_counts()
        with self.storage.snapshot() as snapshot:
            self.assertEqual(negative_status(snapshot, SCOPE, entity_ref(watch), as_of=T2), "current")
            self.assertEqual(negative_status(snapshot, SCOPE, entity_ref(watch), as_of=T3), "review_due")
            self.assertEqual(negative_status(snapshot, SCOPE, entity_ref(watch), as_of=T4), "expired")
            with self.assertRaises(StorageError) as error:
                require_current_negative_dependency(snapshot, SCOPE, entity_ref(watch), as_of=T4)
            self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.current(watch), watch)
        self.assertEqual(self.current(covered), covered)
        self.assertEqual(self.record_counts(), before)

    def test_older_knowledge_publication_and_foreign_watch_refuse_without_mutation(self):
        covered, _, _ = self.publish_coverage(as_of=T3)
        older = publish_command("older", self.authority, self.coverage_policy, specification(), previous=covered, as_of=T2)
        self.assert_refused(self.coverage.prepare, self.coverage.publish, older, "E_EVIDENCE_INVALID")
        target = self.host_projection("foreign-target")
        foreign = pin(target)
        foreign["scope_id"] = "synthetic:foreign"
        command = register_command("foreign-watch", self.authority, self.coverage_policy,
                                   foreign, covered, as_of=T3)
        self.assert_refused(self.coverage.prepare, self.coverage.register, command, "E_SCOPE_FORBIDDEN")
        self.assertEqual(self.current(covered), covered)
        self.assertEqual(self.current(target), target)

    def test_restart_backup_and_old_retry_preserve_invalidated_absence(self):
        covered, coverage_command, coverage_result = self.publish_coverage()
        watch, watch_command, watch_result = self.register_watch(covered)
        observed, arrival_command, arrival_result = self.arrival("after-registration", available_at=T3)
        invalidated = self.current(watch)
        backup = self.storage.backup_to(self.directory / "coverage-backup.sqlite")
        for database in (self.database, backup):
            with SQLiteStore(database, scope_id=SCOPE) as store:
                service = CoverageService(store, policy=self.coverage_policy)
                self.assertEqual(service.publish(coverage_command), coverage_result)
                self.assertEqual(service.register(watch_command), watch_result)
                self.assertEqual(ObservationIngestor(store, self.payloads).ingest(arrival_command), arrival_result)
                self.assertEqual(store.get(entity_ref(watch)), invalidated)
                self.assertEqual(store.get(pin(covered)), covered)
                self.assertEqual(store.get(pin(observed)), observed)
                with store.snapshot() as snapshot:
                    with self.assertRaises(StorageError) as error:
                        require_current_negative_dependency(snapshot, SCOPE, entity_ref(watch), as_of=T3)
                    self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
