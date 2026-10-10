"""Temporal admission failures remain atomic at the real service boundaries."""

from copy import deepcopy

from matter.claims import claim_index_ref
from matter.observations import source_index_ref
from matter.occurrences import occurrence_index_ref, occurrence_key_ref
from matter.source_catalogs import source_catalog_ref, source_key
from matter.storage import StorageError, entity_ref, pin

from claim_helpers import ClaimTestCase, claim_command
from observation_helpers import ObservationTestCase, SCOPE, known_time, observation_command
from occurrence_helpers import OccurrenceTestCase, grouping_command, occurrence_input


EARLY = known_time("2026-10-08T12:00:00.000000001Z")
LATE = known_time("2026-10-08T12:00:00.000000002Z")
UNKNOWN = {"state": "unknown", "reason": "not_reported", "detail": "Synthetic source did not report this boundary."}


def interval(start, end):
    return {"start": deepcopy(start), "end": deepcopy(end), "bounds": "closed_open"}


def occurred_interval(record, value):
    record["body"].pop("occurred_at", None)
    record["body"]["occurred_interval"] = deepcopy(value)


class ObservationTemporalAdmissionTests(ObservationTestCase):
    def test_reversed_nanosecond_interval_journals_refusal_without_observation_or_indexes(self):
        command = observation_command("reversed-observation", "reversed-observation")
        observation = command["body"]["observation"]
        occurred_interval(observation, interval(LATE, EARLY))
        prepared = self.ingestor.prepare(command)
        before = self.record_counts()
        result = self.ingestor.ingest(prepared)
        self.assert_failure(result, "E_EVIDENCE_INVALID")
        self.assertEqual(result, self.storage.command_receipt(prepared["idempotency_key"])["result"])
        self.assertEqual(result, self.ingestor.ingest(prepared))
        source = observation["body"]["source_identity"]
        for reference in (entity_ref(observation), source_index_ref(SCOPE, source),
                          source_catalog_ref(SCOPE, source_key(source["namespace"]))):
            self.assert_missing(reference)
        self.assertEqual({**before, "receipt": before.get("receipt", 0) + 1}, self.record_counts())

    def test_unknown_interval_boundaries_preserve_source_uncertainty_and_availability(self):
        command = observation_command("unknown-observation", "unknown-observation", available_at=UNKNOWN)
        observation = command["body"]["observation"]
        declared = interval(UNKNOWN, EARLY)
        occurred_interval(observation, declared)
        _, result = self.submit(command)
        stored = self.storage.get(result["body"]["observation"])
        self.assertEqual(declared, stored["body"]["occurred_interval"])
        self.assertEqual(UNKNOWN, stored["body"]["available_at"])
        self.assertNotIn("occurred_at", stored["body"])
        self.assertNotEqual(stored["body"]["ingested_at"], stored["body"]["occurred_interval"]["start"])
        self.assertEqual([], self.ingestor.revisions(stored["body"]["source_identity"], as_of=LATE))


class ClaimTemporalAdmissionTests(ClaimTestCase):
    def test_reversed_nanosecond_claim_correction_retains_original_and_writes_no_new_claim_index(self):
        original, _, _ = self.append("original")
        command = claim_command("reversed-correction", "reversed-correction", self.subject, self.source,
                                version="2.0", supersedes=[original])
        proposed = command["body"]["claim"]
        proposed["body"]["applicability"] = interval(LATE, EARLY)
        prepared = self.claims.prepare(command)
        before = self.record_counts()
        result = self.claims.append(prepared)
        self.assert_failure(result, "E_EVIDENCE_INVALID")
        self.assertEqual(result, self.claims.append(prepared))
        self.assert_missing(entity_ref(proposed))
        self.assert_missing(claim_index_ref(proposed["scope_id"], proposed))
        self.assertEqual(original, self.storage.get(pin(original)))
        self.assertEqual([original], self.claims.for_subject(entity_ref(self.subject)))
        self.assertEqual({**before, "receipt": before["receipt"] + 1}, self.record_counts())

    def test_unknown_applicability_is_not_replaced_with_source_or_recorded_time(self):
        command = claim_command("unknown-claim", "unknown-claim", self.subject, self.source)
        declared = interval(UNKNOWN, UNKNOWN)
        command["body"]["claim"]["body"]["applicability"] = declared
        result = self.claims.append(self.claims.prepare(command))
        self.assertEqual("appended", result.get("outcome"), result)
        stored = self.storage.get(result["body"]["claim"])
        self.assertEqual(declared, stored["body"]["applicability"])
        self.assertEqual(self.source, self.storage.get(pin(self.source)))


class OccurrenceTemporalAdmissionTests(OccurrenceTestCase):
    def test_reversed_nanosecond_creation_refuses_entire_multi_occurrence_transaction(self):
        first = occurrence_input("would-have-been-valid")
        second = occurrence_input("reversed-occurrence")
        occurred_interval(first, interval(EARLY, LATE))
        occurred_interval(second, interval(LATE, EARLY))
        command = grouping_command("reversed-grouping", creates=[first, second])
        with self.assertRaises(StorageError) as caught:
            self.service.prepare(command)
        self.assertEqual("E_EVIDENCE_INVALID", caught.exception.code)
        before = self.record_counts()
        # Direct execution remains safe even when a host omits prepare.
        result = self.service.commit(command)
        self.assert_failure(result, "E_EVIDENCE_INVALID")
        self.assertEqual(result, self.service.commit(command))
        for proposed in (first, second):
            self.assert_missing(entity_ref(proposed))
            self.assert_missing(occurrence_index_ref(proposed["scope_id"], proposed))
            for key in proposed["body"]["identity_keys"]:
                self.assert_missing(occurrence_key_ref(proposed["scope_id"], key))
        self.assertEqual({**before, "receipt": before.get("receipt", 0) + 1}, self.record_counts())

    def test_unknown_occurrence_boundaries_survive_grouping_and_resolution(self):
        observation = self.observe("report-without-known-occurrence-end")
        proposed = occurrence_input("unknown-occurrence", [observation])
        declared = interval(EARLY, UNKNOWN)
        occurred_interval(proposed, declared)
        _, result = self.submit(grouping_command("unknown-grouping", creates=[proposed]))
        self.assertEqual("committed", result.get("outcome"), result)
        stored = self.storage.get(entity_ref(proposed))
        self.assertEqual(declared, stored["body"]["occurred_interval"])
        self.assertNotIn("occurred_at", stored["body"])
        self.assertEqual(observation, self.storage.get(pin(observation)))
        self.assertEqual(stored, self.service.resolve(proposed["body"]["identity_keys"]))


if __name__ == "__main__":
    import unittest
    unittest.main()
