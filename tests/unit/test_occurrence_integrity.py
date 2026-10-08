"""Grouping index inconsistencies and port failures never become zero evidence."""

from copy import deepcopy
from unittest.mock import patch

from matter import occurrences
from matter.occurrences import occurrence_index_ref, occurrence_key_ref
from matter.storage import StorageError, entity_ref, pin
from matter.storage.sqlite import _Snapshot, _Transaction

from integration.helpers import record_input
from occurrence_helpers import (
    SCOPE, OccurrenceTestCase, declared, event_key, group_key,
    grouping_command, occurrence_input, unknown,
)


class OccurrenceIntegrityTests(OccurrenceTestCase):
    def _seed(self, identity="report"):
        report = self.observe(identity)
        occurrence = self.group(f"event:{identity}", [report], assignments=[declared(report)])
        return report, occurrence

    def _assert_invalid(self, read):
        with self.assertRaises(StorageError) as error:
            read()
        self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")

    def _write_projection(self, command_id, report, occurrence, reference, value, watches, *, extra=None):
        try:
            current = self.storage.get(reference)
        except StorageError as error:
            self.assertEqual(error.code, "E_NOT_FOUND")
            expected = []
        else:
            expected = [pin(current)]
        command = grouping_command(command_id, assignments=[unknown(report)], expected_revisions=expected)

        def corrupt(tx):
            # The generic port intentionally permits trusted host handlers.
            # A bad handler must not make an inconsistent index authoritative.
            if extra is not None:
                tx.insert(extra)
            tx.put_projection(reference, value, watch_keys=watches)
            return tx.success("committed", {
                "occurrences": [pin(occurrence)], "previous": [], "provenance_assignments": [],
            })

        self.assertEqual(self.storage.execute(command, corrupt)["status"], "success")

    def test_watched_occurrence_outage_is_not_journaled_as_a_terminal_evidence_refusal(self):
        report, occurrence = self._seed()
        command = self.service.prepare(grouping_command(
            "correct-root", assignments=[declared(report, group_key("corrected"))],
        ))
        before = self.record_counts()
        original = _Transaction.lookup_identity

        def unavailable(view, reference):
            if reference == entity_ref(occurrence):
                raise StorageError("E_STORAGE_UNAVAILABLE", "Synthetic read outage.")
            return original(view, reference)

        with patch.object(_Transaction, "lookup_identity", unavailable):
            result = self.service.commit(command)
        self.assert_failure(result, "E_STORAGE_UNAVAILABLE")
        self.assertEqual(self.record_counts(), before)
        self.assertEqual(self.storage.get(pin(occurrence)), occurrence)
        with self.assertRaises(StorageError) as error:
            self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")
        # The exact command remains retryable after the transient outage.
        accepted = self.service.commit(command)
        self.assertEqual(accepted["outcome"], "committed")
        self.assertEqual(self.count([report])["provenance_groups"], [group_key("corrected")])

    def test_undeclared_watched_target_retains_revision_conflict_and_durable_refusal(self):
        report, occurrence = self._seed()
        command = self.service.prepare(grouping_command(
            "missing-target-pin", assignments=[declared(report, group_key("corrected"))],
        ))
        command["expected_revisions"] = [
            reference for reference in command["expected_revisions"]
            if entity_ref(reference) != entity_ref(occurrence)
        ]
        result = self.service.commit(command)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)
        self.assertEqual(self.service.commit(command), result)
        self.assertEqual(self.storage.get(entity_ref(occurrence)), occurrence)
        self.assertEqual(self.count([report])["provenance_groups"], [group_key()])

    def test_current_count_read_propagates_a_watched_target_storage_outage(self):
        report, occurrence = self._seed()
        original = _Snapshot.lookup_identity

        def unavailable(view, reference):
            if reference == entity_ref(occurrence):
                raise StorageError("E_STORAGE_UNAVAILABLE")
            return original(view, reference)

        with patch.object(_Snapshot, "lookup_identity", unavailable):
            with self.assertRaises(StorageError) as error:
                self.count([report])
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")

    def test_membership_payload_schema_digest_and_watch_mismatch_are_explicit(self):
        for mode in ("malformed", "descriptor", "lineage-digest", "watches"):
            with self.subTest(mode=mode):
                report, occurrence = self._seed(mode)
                index = self.storage.get(occurrence_index_ref(SCOPE, occurrence))
                value, watches = deepcopy(index["value"]), list(index["watch_keys"])
                if mode == "malformed":
                    value["value"]["occurrence"] = {"id": "not-a-typed-pin"}
                elif mode == "descriptor":
                    value["schema"]["digest"] = "f" * 64
                elif mode == "lineage-digest":
                    value["value"]["lineage_digest"] = "f" * 64
                else:
                    # Keep direct discovery working while dropping ancestry.
                    watches = [key for key in watches if not key.startswith("provenance-root-")]
                self._write_projection(
                    f"corrupt:{mode}", report, occurrence, entity_ref(index), value, watches,
                )
                self._assert_invalid(lambda: self.count([report]))
                self._assert_invalid(lambda: self.service.resolve(occurrence["body"]["identity_keys"]))
                self.assertEqual(self.storage.get(pin(report)), report)

    def test_missing_and_wrong_kind_watched_targets_never_become_absence(self):
        for mode in ("missing", "wrong-kind"):
            with self.subTest(mode=mode):
                report, occurrence = self._seed(mode)
                index = self.storage.get(occurrence_index_ref(SCOPE, occurrence))
                forged = {**pin(occurrence), "id": f"untrusted-target:{mode}"}
                value = deepcopy(index["value"])
                value["value"]["occurrence"] = forged
                extra = None
                if mode == "wrong-kind":
                    extra = record_input("observation", forged["id"], scope_id=SCOPE)
                    extra["namespace"] = forged["namespace"]
                self._write_projection(
                    f"bad-target:{mode}", report, occurrence,
                    occurrence_index_ref(SCOPE, forged), value, index["watch_keys"], extra=extra,
                )
                self._assert_invalid(lambda: self.count([report]))
                self._assert_invalid(lambda: self.service.occurrences_for(pin(report)))
                self.assertEqual(self.storage.get(pin(report)), report)

    def test_missing_or_wrong_kind_membership_index_is_not_a_resolved_occurrence(self):
        for mode in ("missing", "wrong-kind"):
            with self.subTest(mode=mode):
                proposed = occurrence_input(f"index-{mode}")
                key = event_key(f"index-{mode}")
                command = grouping_command(f"seed-index:{mode}", creates=[proposed])

                def corrupt(tx):
                    stored = tx.insert(proposed)
                    tx.put_projection(
                        occurrence_key_ref(SCOPE, key), occurrences._key_value(SCOPE, key, [stored]),
                    )
                    if mode == "wrong-kind":
                        address = occurrence_index_ref(SCOPE, stored)
                        impostor = record_input("observation", address["id"], scope_id=SCOPE)
                        impostor["namespace"] = address["namespace"]
                        tx.insert(impostor)
                    return tx.success("committed", {
                        "occurrences": [pin(stored)], "previous": [], "provenance_assignments": [],
                    })

                self.assertEqual(self.storage.execute(command, corrupt)["status"], "success")
                self._assert_invalid(lambda: self.service.resolve([key]))

    def test_unavailable_packaged_projection_schema_remains_a_storage_failure(self):
        _, occurrence = self._seed()
        occurrences._projection_contract.cache_clear()
        self.addCleanup(occurrences._projection_contract.cache_clear)
        with patch.object(occurrences, "files", side_effect=OSError("Synthetic missing schema.")):
            with self.assertRaises(StorageError) as error:
                self.service.resolve(occurrence["body"]["identity_keys"])
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")
