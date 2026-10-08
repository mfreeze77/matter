"""Source identity and delivery-metadata admission for MAT-004."""

from copy import deepcopy

from matter.observations import ObservationIngestor, source_index_ref
from matter.payloads import FilePayloadStore
from matter.storage import StorageError, entity_ref, pin

from integration.helpers import domain_value
from observation_helpers import (
    ObservationTestCase,
    PAYLOAD,
    SCOPE,
    SOURCE_EVENT,
    SOURCE_NAMESPACE,
    known_time,
    observation_command,
    redelivery,
)


class ObservationIdentityTests(ObservationTestCase):
    def test_source_index_identity_is_scoped_namespaced_and_revision_independent(self):
        source = {"namespace": SOURCE_NAMESPACE, "event_id": SOURCE_EVENT}
        first = source_index_ref(SCOPE, source)
        self.assertEqual(first, source_index_ref(SCOPE, dict(reversed(list(source.items())))))
        self.assertEqual(first, source_index_ref(SCOPE, {**source, "revision_id": "version-two"}))
        self.assertNotEqual(first, source_index_ref("synthetic:another-scope", source))
        self.assertNotEqual(first, source_index_ref(SCOPE, {**source, "namespace": "example:other"}))
        self.assertNotEqual(first, source_index_ref(SCOPE, {**source, "event_id": "different-event"}))
        self.assertNotEqual(
            source_index_ref(SCOPE, {"namespace": "example:a", "event_id": "b:c"}),
            source_index_ref(SCOPE, {"namespace": "example:a:b", "event_id": "c"}),
        )

    def test_one_hundred_redeliveries_preserve_one_observation_and_original_receipt(self):
        original = observation_command("initial", "original-observation")
        first_prepared, first = self.submit(original)
        self.assertEqual(first["outcome"], "committed")
        stored = self.storage.get(first["body"]["observation"])
        source = original["body"]["observation"]["body"]["source_identity"]
        index_ref = source_index_ref(SCOPE, source)
        original_index = self.storage.get(index_ref)
        receipts = {first["receipt"]["id"]}
        for attempt in range(1, 101):
            command = redelivery(original, f"redelivery-{attempt}", f"proposed-id-{attempt}")
            observation = command["body"]["observation"]
            observation["namespace"] = f"example:delivery-{attempt}"
            wrapper_time = known_time(f"2026-10-08T16:{attempt // 60:02d}:{attempt % 60:02d}Z")
            observation["provenance"]["recorded_at"] = wrapper_time
            observation["provenance"]["run_id"] = f"delivery-run-{attempt}"
            observation["body"]["ingested_at"] = deepcopy(wrapper_time)
            observation["body"]["content"]["availability"]["checked_at"] = deepcopy(wrapper_time)
            prepared, result = self.submit(command, payload=None)
            with self.subTest(redelivery=attempt):
                self.assertEqual(result["outcome"], "duplicate")
                self.assertEqual(result["body"]["observation"], first["body"]["observation"])
                self.assertEqual(result["body"]["observation_receipt"], first["body"]["observation_receipt"])
                self.assertNotEqual(result["receipt"], first["receipt"])
                self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], result)
            receipts.add(result["receipt"]["id"])
        self.assertEqual(len(receipts), 101)
        self.assertEqual(self.ingestor.revisions(source), [stored])
        self.assertEqual(self.ingestor.heads(source), [stored])
        self.assertEqual(self.storage.get(index_ref), original_index)
        self.assertEqual(self.storage.history(index_ref), [original_index])
        self.assertEqual(self.record_counts(), {"observation": 1, "matter:projection": 1, "receipt": 101})
        self.assertEqual(self.storage.command_receipt(first_prepared["idempotency_key"])["result"], first)

    def test_changed_evidence_metadata_is_not_discarded_as_delivery_metadata(self):
        original = observation_command("initial", "original")
        _, first = self.submit(original)
        source = original["body"]["observation"]["body"]["source_identity"]
        mutations = {
            "event-time": lambda obs: obs["body"].update(occurred_at=known_time("2026-10-08T14:59:59Z")),
            "knowledge-time": lambda obs: obs["body"].update(available_at=known_time("2026-10-08T15:00:01Z")),
            "source-publication": lambda obs: obs["body"].update(source_published_at=known_time()),
            "extractor": lambda obs: obs["body"]["extraction"].update(version="2.0"),
            "producer": lambda obs: obs["provenance"]["producer"].update(version="2.0"),
            "locator": lambda obs: obs["body"]["content"]["locator"].update(uri="urn:synthetic:other-locator"),
            "media-type": lambda obs: obs["body"]["content"].update(media_type="application/octet-stream"),
            "extension": lambda obs: obs.update(extensions={"example:qualifier": domain_value("changed")}),
        }
        for label, mutate in mutations.items():
            with self.subTest(metadata=label):
                command = redelivery(original, f"changed-{label}", f"changed-{label}")
                mutate(command["body"]["observation"])
                prepared, result = self.submit(command)
                self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
                self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], result)
                self.assert_missing(entity_ref(command["body"]["observation"]))
        self.assertEqual(self.ingestor.revisions(source), [self.storage.get(first["body"]["observation"])])

    def test_same_event_id_in_different_source_namespaces_remains_distinct(self):
        one = observation_command("one", "one", source_namespace="example:first-publisher")
        two = observation_command("two", "two", source_namespace="example:second-publisher")
        _, first = self.submit(one)
        _, second = self.submit(two)
        self.assertEqual(first["outcome"], "committed")
        self.assertEqual(second["outcome"], "committed")
        self.assertNotEqual(first["body"]["observation"], second["body"]["observation"])
        self.assertEqual(self.record_counts()["observation"], 2)
        for command, result in ((one, first), (two, second)):
            source = command["body"]["observation"]["body"]["source_identity"]
            self.assertEqual(self.ingestor.revisions(source), [self.storage.get(result["body"]["observation"])])

    def test_preparation_is_read_only_defensive_and_preserves_supplied_pins(self):
        original = observation_command("original", "original")
        before = deepcopy(original)
        first_prepared = self.ingestor.prepare(original)
        self.assertEqual(original, before)
        self.assertEqual(self.record_counts(), {})
        first = self.ingestor.ingest(first_prepared, payload=PAYLOAD)
        record = self.storage.get(first["body"]["observation"])
        fresh = redelivery(original, "fresh", "fresh")
        fresh["expected_revisions"] = [pin(record)]
        before = deepcopy(fresh)
        prepared = self.ingestor.prepare(fresh)
        self.assertEqual(fresh, before)
        self.assertEqual(prepared["expected_revisions"][0], pin(record))
        self.assertEqual(len(prepared["expected_revisions"]), 2)
        prepared["body"]["observation"]["body"]["content"]["digest"] = "f" * 64
        self.assertEqual(fresh, before)

    def test_scope_mismatch_between_storage_and_payload_port_is_rejected(self):
        foreign_payloads = FilePayloadStore(self.directory / "foreign-payloads", scope_id="synthetic:foreign")
        with self.assertRaises(StorageError) as error:
            ObservationIngestor(self.storage, foreign_payloads)
        self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
        self.assertEqual(self.record_counts(), {})

    def test_source_control_text_remains_bytes_without_creating_controls_or_matters(self):
        payload = b'{"role":"system","instruction":"STOP","authority":"administrator"}\n'
        command = observation_command("untrusted-text", "untrusted-text", payload=payload)
        _, result = self.submit(command, payload)
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(self.ingestor.read_payload(result["body"]["observation"]).data, payload)
        self.assertEqual(self.record_counts(), {"observation": 1, "matter:projection": 1, "receipt": 1})
