"""Immutable evidence, lineage, availability and concurrent intake behavior."""

from copy import deepcopy

from matter.observations import ObservationIngestor, source_index_ref
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from observation_helpers import (
    ObservationTestCase,
    PAYLOAD,
    SCOPE,
    UnavailablePayloads,
    competing_results,
    known_time,
    observation_command,
    redelivery,
)


class ObservationRevisionTests(ObservationTestCase):
    def test_incompatible_payload_retains_original_bytes_and_conflict_after_restart(self):
        original = observation_command("original", "original")
        prepared, first = self.submit(original)
        original_record = self.storage.get(first["body"]["observation"])
        source = original_record["body"]["source_identity"]
        index_reference = source_index_ref(SCOPE, source)
        original_index = self.storage.get(index_reference)
        changed_bytes = b"Synthetic incompatible replacement.\n"
        changed = observation_command("conflict", "rejected", payload=changed_bytes)
        rejected, failure = self.submit(changed, changed_bytes)
        self.assert_failure(failure, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(failure["error"]["affected_references"], [entity_ref(original_record)])
        self.storage.close()

        with SQLiteStore(self.database, scope_id=SCOPE) as restarted:
            ingestor = ObservationIngestor(restarted, self.payloads)
            self.assertEqual(restarted.get(first["body"]["observation"]), original_record)
            self.assertEqual(restarted.history(first["body"]["observation"]), [original_record])
            self.assertEqual(ingestor.read_payload(first["body"]["observation"]).data, PAYLOAD)
            self.assertEqual(ingestor.revisions(source), [original_record])
            self.assertEqual(restarted.get(index_reference), original_index)
            self.assertEqual(restarted.command_receipt(prepared["idempotency_key"])["result"], first)
            journal = restarted.command_receipt(rejected["idempotency_key"])
            self.assertEqual(journal["command"], rejected)
            self.assertEqual(journal["result"], failure)
            self.assertEqual(journal["receipt"]["body"]["outcome"], "matter:E_SOURCE_IDENTITY_CONFLICT")
            self.assertEqual(journal["receipt"]["body"]["details"]["value"]["writes"], [])
            with self.assertRaises(StorageError) as error:
                restarted.get(entity_ref(changed["body"]["observation"]))
            self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def test_correction_preserves_prior_content_and_adjacent_nanosecond_boundaries(self):
        original_time = known_time("2026-10-08T15:00:00.123456788Z")
        correction_time = known_time("2026-10-08T15:00:00.123456789Z")
        original = observation_command("original", "original", available_at=original_time)
        original["body"]["observation"]["body"]["source_published_at"] = known_time("2026-10-08T14:00:00Z")
        _, first = self.submit(original)
        old = self.storage.get(first["body"]["observation"])
        corrected_bytes = b"Synthetic explicitly corrected evidence.\n"
        correction = observation_command("correction", "correction", payload=corrected_bytes,
                                         available_at=correction_time)
        correction["body"]["observation"]["body"]["source_published_at"] = known_time("2026-10-08T14:00:00Z")
        correction["body"]["observation"]["body"]["ingested_at"] = known_time("2026-10-08T16:00:00Z")
        correction["body"]["observation"]["supersedes"] = [pin(old)]
        _, second = self.submit(correction, corrected_bytes)
        self.assertEqual(second["outcome"], "committed")
        new = self.storage.get(second["body"]["observation"])
        source = old["body"]["source_identity"]

        self.assertEqual(self.ingestor.revisions(source, as_of=known_time("2026-10-08T15:00:00.123456Z")), [])
        self.assertEqual(self.ingestor.revisions(source, as_of=original_time), [old])
        self.assertEqual(self.ingestor.heads(source, as_of=original_time), [old])
        self.assertEqual(self.ingestor.revisions(source, as_of=correction_time), [old, new])
        self.assertEqual(self.ingestor.heads(source, as_of=correction_time), [new])
        self.assertEqual(self.ingestor.revisions(source), [old, new])
        self.assertEqual(self.storage.history(pin(old)), [old])
        self.assertEqual(self.storage.get(pin(old))["body"]["available_at"], original_time)
        self.assertEqual(new["body"]["available_at"], correction_time)
        self.assertEqual(new["supersedes"], [pin(old)])
        self.assertEqual(self.ingestor.read_payload(pin(old)).data, PAYLOAD)
        self.assertEqual(self.ingestor.read_payload(pin(new)).data, corrected_bytes)
        self.assertNotEqual(new["creation_receipt"], old["creation_receipt"])
        self.assertEqual(self.storage.receipt_for(pin(old))["id"], old["creation_receipt"]["id"])
        self.assertEqual(self.storage.get(source_index_ref(SCOPE, source))["revision"], 2)

    def test_explicit_revision_labels_do_not_implicitly_supersede_older_evidence(self):
        first_command = observation_command("version-one", "version-one", revision_id="r1")
        second_command = observation_command("version-two", "version-two", revision_id="r2")
        _, first = self.submit(first_command)
        _, second = self.submit(second_command)
        self.assertEqual(first["outcome"], "committed")
        self.assertEqual(second["outcome"], "committed")
        records = [self.storage.get(result["body"]["observation"]) for result in (first, second)]
        source = first_command["body"]["observation"]["body"]["source_identity"]
        self.assertEqual(self.ingestor.revisions(source), records)
        self.assertEqual(self.ingestor.heads(source), records)
        self.assertEqual([record["body"]["source_identity"]["revision_id"] for record in records], ["r1", "r2"])
        self.assertTrue(all("supersedes" not in record for record in records))
        _, duplicate = self.submit(redelivery(first_command, "retry-r1", "proposed-r1"), payload=None)
        self.assertEqual(duplicate["outcome"], "duplicate")
        self.assertEqual(duplicate["body"], first["body"])
        self.assertEqual(self.storage.get(source_index_ref(SCOPE, source))["revision"], 2)

    def test_changed_revision_identity_must_supersede_its_own_bound_predecessor(self):
        _, first = self.submit(observation_command("r1", "r1", revision_id="r1"))
        _, second = self.submit(observation_command("r2", "r2", revision_id="r2"))
        old_one = self.storage.get(first["body"]["observation"])
        old_two = self.storage.get(second["body"]["observation"])
        changed_bytes = b"Synthetic correction assigned to revision one.\n"
        wrong = observation_command("wrong-predecessor", "wrong-predecessor", payload=changed_bytes, revision_id="r1")
        wrong["body"]["observation"]["supersedes"] = [pin(old_two)]
        _, failure = self.submit(wrong, changed_bytes)
        self.assert_failure(failure, "E_SOURCE_IDENTITY_CONFLICT")
        source = old_one["body"]["source_identity"]
        self.assertEqual(self.ingestor.heads(source), [old_one, old_two])
        self.assert_missing(entity_ref(wrong["body"]["observation"]))
        self.assertEqual(self.storage.get(source_index_ref(SCOPE, source))["revision"], 2)

        corrected = redelivery(wrong, "right-predecessor", "right-predecessor")
        corrected["body"]["observation"]["supersedes"] = [pin(old_one)]
        _, committed = self.submit(corrected, changed_bytes)
        self.assertEqual(committed["outcome"], "committed")
        new = self.storage.get(committed["body"]["observation"])
        self.assertEqual(self.ingestor.revisions(source), [old_one, old_two, new])
        self.assertEqual(self.ingestor.heads(source), [old_two, new])

    def test_derived_summary_retains_exact_parent_and_producer_provenance(self):
        _, first = self.submit(observation_command("publisher", "publisher"))
        parent = self.storage.get(first["body"]["observation"])
        summary_bytes = b"Synthetic generated summary of the source evidence.\n"
        summary = observation_command("summary", "summary", payload=summary_bytes,
                                      source_namespace="example:summarizer", event_id="summary-event")
        proposed = summary["body"]["observation"]
        proposed["provenance"].update(origin="derived", parents=[pin(parent)])
        proposed["provenance"]["producer"].update(id="summary-generator", version="2.0")
        proposed["body"]["extraction"].update(id="summary-extractor", version="2.0")
        prepared, result = self.submit(summary, summary_bytes)
        self.assertEqual(result["outcome"], "committed")
        stored = self.storage.get(result["body"]["observation"])
        self.assertIn(pin(parent), prepared["expected_revisions"])
        self.assertEqual(stored["provenance"], proposed["provenance"])
        self.assertEqual(stored["body"]["extraction"], proposed["body"]["extraction"])
        self.assertEqual(stored["body"]["source_identity"], proposed["body"]["source_identity"])
        self.assertEqual(self.ingestor.read_payload(pin(stored)).data, summary_bytes)
        self.assertEqual(self.ingestor.read_payload(pin(parent)).data, PAYLOAD)
        self.assertEqual(self.ingestor.revisions(parent["body"]["source_identity"]), [parent])
        self.assertEqual(self.record_counts(), {"observation": 2, "matter:projection": 2, "receipt": 2})

    def test_missing_and_wrong_digest_parent_pins_are_durable_revision_refusals(self):
        _, first = self.submit(observation_command("parent", "parent"))
        parent = self.storage.get(first["body"]["observation"])
        for variant in ("missing", "wrong-digest"):
            with self.subTest(parent=variant):
                parent_pin = pin(parent)
                if variant == "missing":
                    parent_pin["id"] = "nonexistent-parent"
                else:
                    parent_pin["digest"] = "0" * 64
                command = observation_command(variant, variant, event_id=f"summary-{variant}")
                command["body"]["observation"]["provenance"].update(origin="derived", parents=[parent_pin])
                prepared, result = self.submit(command)
                self.assertIn(parent_pin, prepared["expected_revisions"])
                self.assert_failure(result, "E_REVISION_CONFLICT")
                self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], result)
                self.assert_missing(entity_ref(command["body"]["observation"]))
                self.assert_missing(source_index_ref(SCOPE, command["body"]["observation"]["body"]["source_identity"]))
        self.assertEqual(self.storage.get(pin(parent)), parent)

    def test_invalid_supersession_never_changes_the_existing_source_index(self):
        prepared, first = self.submit(observation_command("original", "original"))
        _, other = self.submit(observation_command("other-family", "other-family", event_id="other-family"))
        original = self.storage.get(first["body"]["observation"])
        foreign_family = self.storage.get(other["body"]["observation"])
        original_receipt = self.storage.command_receipt(prepared["idempotency_key"])["receipt"]
        source = original["body"]["source_identity"]
        index_reference = source_index_ref(SCOPE, source)
        before = self.storage.get(index_reference)
        missing = {**pin(original), "id": "nonexistent-predecessor"}
        cases = (
            ("wrong-family", [pin(foreign_family)], "E_EVIDENCE_INVALID"),
            ("wrong-kind", [pin(original_receipt)], "E_EVIDENCE_INVALID"),
            ("duplicate", [pin(original), pin(original)], "E_EVIDENCE_INVALID"),
            ("wrong-digest", [{**pin(original), "digest": "0" * 64}], "E_EVIDENCE_INVALID"),
            ("missing", [missing], "E_REVISION_CONFLICT"),
        )
        for label, references, code in cases:
            with self.subTest(supersedes=label):
                command = observation_command(label, label, payload=b"Synthetic correction.\n")
                command["body"]["observation"]["supersedes"] = references
                prepared, result = self.submit(command, b"Synthetic correction.\n")
                self.assert_failure(result, code)
                self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], result)
                self.assertEqual(self.storage.get(index_reference), before)
                self.assert_missing(entity_ref(command["body"]["observation"]))
        self.assertEqual(self.ingestor.heads(source), [original])
        self.assertEqual(self.ingestor.read_payload(pin(original)).data, PAYLOAD)

    def test_self_lineage_and_foreign_scope_references_are_rejected_before_writes(self):
        for relation in ("parents", "supersedes"):
            for target in ("self", "foreign"):
                with self.subTest(relation=relation, target=target):
                    label = f"{relation}-{target}"
                    command = observation_command(label, label, event_id=label)
                    proposed = command["body"]["observation"]
                    reference = {**entity_ref(proposed), "digest": "0" * 64}
                    if target == "foreign":
                        reference["scope_id"] = "synthetic:foreign"
                    if relation == "parents":
                        proposed["provenance"].update(origin="derived", parents=[reference])
                    else:
                        proposed["supersedes"] = [reference]
                    if target == "foreign":
                        with self.assertRaises(StorageError) as error:
                            self.ingestor.prepare(command)
                        self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
                    # A fresh family needs no existing index pins. Direct
                    # execution exercises the handler's lineage admission.
                    result = self.ingestor.ingest(command, payload=PAYLOAD)
                    expected = "E_SCOPE_FORBIDDEN" if target == "foreign" else "E_EVIDENCE_INVALID"
                    self.assert_failure(result, expected)
                    self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)
                    self.assert_missing(entity_ref(proposed))
                    self.assert_missing(source_index_ref(SCOPE, proposed["body"]["source_identity"]))
        self.assertEqual(self.record_counts(), {"receipt": 4})

    def test_missing_available_payload_is_a_durable_failure_then_a_new_command_can_commit(self):
        original = observation_command("missing-payload", "missing-payload")
        prepared, failure = self.submit(original, payload=None)
        self.assert_failure(failure, "E_EVIDENCE_UNAVAILABLE")
        self.assert_missing(entity_ref(original["body"]["observation"]))
        self.assertEqual(self.record_counts(), {"receipt": 1})
        self.payloads.put(PAYLOAD)
        self.assertEqual(self.ingestor.ingest(prepared), failure)
        self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], failure)
        fresh = redelivery(original, "now-available", "now-available")
        _, success = self.submit(fresh, payload=None)
        self.assertEqual(success["outcome"], "committed")
        self.assertEqual(self.ingestor.read_payload(success["body"]["observation"]).data, PAYLOAD)
        self.assertEqual(self.record_counts(), {"observation": 1, "matter:projection": 1, "receipt": 2})

    def test_explicit_unavailable_and_withheld_metadata_need_no_payload_bytes(self):
        for status in ("unavailable", "withheld"):
            with self.subTest(availability=status):
                command = observation_command(status, status, event_id=f"event-{status}")
                content = command["body"]["observation"]["body"]["content"]
                content["availability"].update(status=status, reason=f"Synthetic {status} evidence.")
                _, result = self.submit(command, payload=None)
                self.assertEqual(result["outcome"], "committed")
                stored = self.storage.get(result["body"]["observation"])
                self.assertEqual(stored["body"]["content"], content)
                reading = self.ingestor.read_payload(pin(stored))
                self.assertEqual(reading.status, status)
                self.assertEqual(reading.digest, content["digest"])
                self.assertIsNone(reading.data)
                self.assertTrue(reading.reason)

    def test_raw_payload_mismatch_and_wrong_length_do_not_publish_evidence(self):
        for label in ("digest", "length"):
            with self.subTest(mismatch=label):
                command = observation_command(label, label, event_id=label)
                if label == "length":
                    command["body"]["observation"]["body"]["content"]["byte_length"] += 1
                payload = b"Other synthetic bytes.\n" if label == "digest" else PAYLOAD
                prepared, failure = self.submit(command, payload)
                self.assert_failure(failure, "E_EVIDENCE_INVALID")
                self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], failure)
                self.assert_missing(entity_ref(command["body"]["observation"]))
                self.assert_missing(source_index_ref(SCOPE, command["body"]["observation"]["body"]["source_identity"]))
        self.assertEqual(self.record_counts(), {"receipt": 2})

    def test_a_new_duplicate_command_still_rejects_mismatched_supplied_bytes(self):
        original = observation_command("original", "original")
        _, first = self.submit(original)
        duplicate = redelivery(original, "bad-delivery", "bad-delivery")
        _, failure = self.submit(duplicate, b"Wrong replacement bytes.\n")
        self.assert_failure(failure, "E_EVIDENCE_INVALID")
        self.assertEqual(self.ingestor.read_payload(first["body"]["observation"]).data, PAYLOAD)
        self.assertEqual(self.record_counts(), {"observation": 1, "matter:projection": 1, "receipt": 2})

    def test_unknown_availability_does_not_acquire_the_ingestion_timestamp(self):
        unknown = {"state": "unknown", "reason": "not_reported"}
        original = observation_command("unknown", "unknown", available_at=unknown)
        _, first = self.submit(original)
        known = observation_command("known", "known", revision_id="known-revision")
        _, second = self.submit(known)
        old = self.storage.get(first["body"]["observation"])
        new = self.storage.get(second["body"]["observation"])
        source = old["body"]["source_identity"]
        self.assertEqual(old["body"]["available_at"], unknown)
        self.assertEqual(old["body"]["ingested_at"]["state"], "known")
        self.assertEqual(self.ingestor.revisions(source), [old, new])
        self.assertEqual(self.ingestor.heads(source), [old, new])
        self.assertEqual(self.ingestor.revisions(source, as_of=known_time("2026-10-09T00:00:00Z")), [new])
        self.assertEqual(self.ingestor.heads(source, as_of=known_time("2026-10-09T00:00:00Z")), [new])

    def test_retry_and_redelivery_keep_original_result_after_supersession_without_payload_recheck(self):
        original = observation_command("original", "original")
        prepared, first = self.submit(original)
        old = self.storage.get(first["body"]["observation"])
        correction = observation_command("correction", "correction", payload=b"Corrected synthetic bytes.\n")
        correction["body"]["observation"]["supersedes"] = [pin(old)]
        _, second = self.submit(correction, b"Corrected synthetic bytes.\n")
        new = self.storage.get(second["body"]["observation"])
        source = old["body"]["source_identity"]
        before = self.storage.get(source_index_ref(SCOPE, source))
        unavailable = UnavailablePayloads()
        ingestor = ObservationIngestor(self.storage, unavailable)

        self.assertEqual(ingestor.prepare(prepared), prepared)
        self.assertEqual(ingestor.ingest(prepared), first)
        delivery = ingestor.prepare(redelivery(original, "late-redelivery", "unused-proposal"))
        result = ingestor.ingest(delivery)
        self.assertEqual(result["outcome"], "duplicate")
        self.assertEqual(result["body"], first["body"])
        self.assertNotEqual(result["receipt"], first["receipt"])
        self.assertEqual((unavailable.read_calls, unavailable.put_calls), (0, 0))
        self.assertEqual(ingestor.revisions(source), [old, new])
        self.assertEqual(ingestor.heads(source), [new])
        self.assertEqual(self.storage.get(source_index_ref(SCOPE, source)), before)
        self.assertEqual(ingestor.read_payload(pin(old)).status, "unavailable")
        self.assertEqual(unavailable.read_calls, 1)
        self.assertEqual(self.storage.get(pin(old))["body"]["content"]["availability"]["status"], "available")

    def test_preparation_never_replaces_a_callers_stale_index_pin(self):
        original = observation_command("original", "original", revision_id="r1")
        _, first = self.submit(original)
        source = original["body"]["observation"]["body"]["source_identity"]
        index_reference = source_index_ref(SCOPE, source)
        old_index_pin = pin(self.storage.get(index_reference))
        self.submit(observation_command("r2", "r2", revision_id="r2"))
        command = redelivery(original, "stale-reader", "stale-reader")
        command["expected_revisions"] = [old_index_pin]
        before = deepcopy(command)
        prepared = self.ingestor.prepare(command)
        self.assertEqual(command, before)
        self.assertEqual(prepared["expected_revisions"][0], old_index_pin)
        failure = self.ingestor.ingest(prepared)
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        self.assertEqual(self.ingestor.ingest(prepared), failure)
        _, duplicate = self.submit(redelivery(original, "fresh-reader", "fresh-reader"), payload=None)
        self.assertEqual(duplicate["outcome"], "duplicate")
        self.assertEqual(duplicate["body"], first["body"])
        self.assertEqual(self.storage.get(index_reference)["revision"], 2)

    def test_same_source_and_observation_ids_are_isolated_by_real_storage_scope(self):
        local = observation_command("same-command", "same-observation")
        _, first = self.submit(local)
        foreign_scope = "synthetic:another-scope"
        foreign = observation_command("same-command", "same-observation", scope_id=foreign_scope)
        with SQLiteStore(self.database, scope_id=foreign_scope) as other_storage:
            other_payloads = FilePayloadStore(self.payload_directory, scope_id=foreign_scope)
            other_ingestor = ObservationIngestor(other_storage, other_payloads)
            second = other_ingestor.ingest(other_ingestor.prepare(foreign), payload=PAYLOAD)
            self.assertEqual(second["outcome"], "committed")
            self.assertNotEqual(first["body"]["observation"], second["body"]["observation"])
            source = local["body"]["observation"]["body"]["source_identity"]
            self.assertEqual([record["scope_id"] for record in self.ingestor.revisions(source)], [SCOPE])
            self.assertEqual([record["scope_id"] for record in other_ingestor.revisions(source)], [foreign_scope])
            self.assertEqual(other_ingestor.read_payload(second["body"]["observation"]).data, PAYLOAD)
            for ingestor, reference in ((self.ingestor, second["body"]["observation"]),
                                        (other_ingestor, first["body"]["observation"])):
                with self.assertRaises(StorageError) as error:
                    ingestor.read_payload(reference)
                self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")

    def _assert_prepared_competition(self, *, existing):
        source_event = "race-append" if existing else "race-create"
        initial = []
        if existing:
            _, result = self.submit(observation_command("baseline", "baseline", event_id=source_event,
                                                        revision_id="r0"))
            initial.append(self.storage.get(result["body"]["observation"]))
        payload = b"Concurrent synthetic revision.\n"
        commands = [self.ingestor.prepare(observation_command(
            f"{source_event}-{label}", f"{source_event}-{label}", payload=payload,
            event_id=source_event, revision_id="r1",
        )) for label in ("one", "two")]
        results = competing_results(self, self.database, self.payload_directory, commands, payload)
        successes = [command for command in commands if results[command["command_id"]]["status"] == "success"]
        failures = [command for command in commands if results[command["command_id"]]["status"] == "failure"]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(failures), 1, results)
        winner_command, loser_command = successes[0], failures[0]
        winner = results[winner_command["command_id"]]
        loser = results[loser_command["command_id"]]
        self.assertEqual(winner["outcome"], "committed")
        self.assert_failure(loser, "E_REVISION_CONFLICT")
        source = winner_command["body"]["observation"]["body"]["source_identity"]
        winner_record = self.storage.get(winner["body"]["observation"])
        self.assertEqual(self.ingestor.revisions(source), initial + [winner_record])
        self.assert_missing(entity_ref(loser_command["body"]["observation"]))
        self.assertEqual(self.storage.command_receipt(loser_command["idempotency_key"])["result"], loser)
        self.assertEqual(self.ingestor.ingest(loser_command, payload=payload), loser)
        index_reference = source_index_ref(SCOPE, source)
        before = self.storage.get(index_reference)
        self.assertEqual(before["revision"], 2 if existing else 1)
        fresh = redelivery(loser_command, f"{source_event}-converged", f"{source_event}-converged")
        _, duplicate = self.submit(fresh, payload=payload)
        self.assertEqual(duplicate["outcome"], "duplicate")
        self.assertEqual(duplicate["body"], winner["body"])
        self.assertEqual(self.storage.get(index_reference), before)
        self.assertEqual(self.ingestor.revisions(source), initial + [winner_record])

    def test_competing_processes_cannot_both_create_the_same_source_family(self):
        self._assert_prepared_competition(existing=False)

    def test_competing_processes_cannot_append_against_the_same_index_revision(self):
        self._assert_prepared_competition(existing=True)
