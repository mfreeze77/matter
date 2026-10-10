"""Admission limits preserve usable source buckets under refresh and races."""

from copy import deepcopy
from unittest.mock import patch

from matter.negative_dependencies import negative_dependency_ref
from matter.source_catalogs import source_key, source_watch_key
from matter.storage import StorageError, pin

from association_helpers import SCOPE
from coverage_helpers import (
    OTHER_SOURCE, SOURCE_NAMESPACE, T3, CoverageTestCase, register_command, specification,
)


class NegativeRegistrationCapacityTests(CoverageTestCase):
    def bucket(self, source=SOURCE_NAMESPACE):
        return self.storage.watchers(source_watch_key(SCOPE, source_key(source)))

    def test_overflow_refuses_prepare_and_commit_without_blocking_source_intake(self):
        # A small process-local limit exercises the production admission path
        # without constructing thousands of otherwise identical registrations.
        with patch("matter.negative_dependencies.MAX_NEGATIVE_REGISTRATIONS", 1):
            covered, _, _ = self.publish_coverage()
            target = self.host_projection("capacity-target")
            first, prepared, _ = self.register_watch(covered, identity="first", target=target)
            overflow = register_command("overflow", self.authority, self.coverage_policy,
                                        target, covered)
            with self.assertRaises(StorageError) as error:
                self.coverage.prepare(overflow)
            self.assertEqual(error.exception.code, "E_BUDGET_EXHAUSTED")
            self.assert_no_journal(overflow)

            # A caller can supply complete dependency pins directly. Commit
            # must enforce the same limit, journal refusal, and write no watch.
            overflow["expected_revisions"] = deepcopy(prepared["expected_revisions"]) + [pin(first)]
            refused = self.coverage.register(overflow)
            self.assert_failure(refused, "E_BUDGET_EXHAUSTED")
            self.assertEqual(self.coverage.register(overflow), refused)
            with self.assertRaises(StorageError) as error:
                self.storage.get(negative_dependency_ref(SCOPE, "overflow"))
            self.assertEqual(error.exception.code, "E_NOT_FOUND")
            self.assertEqual(self.bucket(), [first])

            self.arrival("unrelated-after-capacity-refusal", event="different-event")
            self.assertEqual(self.current(first), first)
            observed, _, result = self.arrival("matching-after-capacity-refusal", available_at=T3)
            updated = self.current(first)
            self.assertEqual(self.value(updated)["status"], "invalidated")
            self.assertEqual(self.value(updated)["matches"], [pin(observed)])
            self.assertEqual(result["body"]["changes"][0]["after"], [pin(updated)])
            self.assertEqual(len(self.bucket()), 1)

    def test_same_id_refresh_and_old_success_replay_keep_one_slot_at_capacity(self):
        with patch("matter.negative_dependencies.MAX_NEGATIVE_REGISTRATIONS", 1):
            covered, _, _ = self.publish_coverage()
            target = self.host_projection("refresh-target")
            first, initial_command, initial_result = self.register_watch(
                covered, identity="stable", target=target)
            refreshed, command, result = self.register_watch(
                covered, identity="stable", target=target, command_id="refresh-stable", previous=first)
            self.assertEqual(refreshed["revision"], first["revision"] + 1)
            self.assertEqual(refreshed["creation_receipt"], first["creation_receipt"])
            self.assertEqual(self.bucket(), [refreshed])
            self.assertEqual(self.coverage.register(command), result)
            self.assertEqual(self.coverage.register(initial_command), initial_result)
            self.assertEqual(self.current(first), refreshed)
            self.assertEqual(self.bucket(), [refreshed])

    def test_two_prepared_registrations_cannot_both_take_the_last_slot(self):
        with patch("matter.negative_dependencies.MAX_NEGATIVE_REGISTRATIONS", 2):
            covered, _, _ = self.publish_coverage()
            target = self.host_projection("race-target")
            first, _, _ = self.register_watch(covered, identity="existing", target=target)
            commands = [self.coverage.prepare(register_command(
                identity, self.authority, self.coverage_policy, target, covered))
                for identity in ("last-slot-winner", "last-slot-loser")]
            winner = self.coverage.register(commands[0])
            self.assertEqual(winner["status"], "success", winner)
            loser = self.coverage.register(commands[1])
            self.assert_failure(loser, "E_REVISION_CONFLICT")
            self.assertEqual(self.coverage.register(commands[1]), loser)
            self.assertEqual(len(self.bucket()), 2)
            self.assertEqual(self.current(first), first)
            with self.assertRaises(StorageError) as error:
                self.storage.get(negative_dependency_ref(SCOPE, "last-slot-loser"))
            self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def test_joining_a_full_source_bucket_preserves_original_subscription(self):
        with patch("matter.negative_dependencies.MAX_NEGATIVE_REGISTRATIONS", 1):
            original_coverage, _, _ = self.publish_coverage()
            other_coverage, _, _ = self.publish_coverage(
                command_id="other-coverage", spec=specification(sources=[OTHER_SOURCE]))
            target = self.host_projection("moving-target")
            original, _, _ = self.register_watch(original_coverage, identity="moving", target=target)
            occupant, _, _ = self.register_watch(other_coverage, identity="occupant")
            both_coverage, _, _ = self.publish_coverage(command_id="both-coverage",
                spec=specification(sources=[SOURCE_NAMESPACE, OTHER_SOURCE]), baselines=[])
            command = register_command("join-full-source", self.authority, self.coverage_policy,
                target, both_coverage, identity="moving", previous=original)
            with self.assertRaises(StorageError) as error:
                self.coverage.prepare(command)
            self.assertEqual(error.exception.code, "E_BUDGET_EXHAUSTED")
            self.assert_no_journal(command)
            self.assertEqual(self.bucket(), [original])
            self.assertEqual(self.bucket(OTHER_SOURCE), [occupant])
            self.arrival("original-subscription-retained", available_at=T3)
            self.assertEqual(self.value(self.current(original))["status"], "invalidated")
            self.assertEqual(self.current(occupant), occupant)

