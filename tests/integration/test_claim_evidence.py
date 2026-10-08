"""Durable scoped propositions/citations, without a truth or transition engine."""

from copy import deepcopy
import multiprocessing

from matter.citations import Utf8LineLocatorAdapter
from matter.evidence_relations import EvidenceRelationService
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from claim_helpers import (ClaimTestCase, SCOPE, PASSAGE, acceptance_command,
                           claim_command, relation_command)
from matter_helpers import identity_key, metadata_command
from observation_helpers import UnavailablePayloads


def acceptance_writer(database, payload_directory, command, barrier, output):
    """Start independent processes with already frozen revision expectations."""
    try:
        with SQLiteStore(database, scope_id=SCOPE) as storage:
            service = EvidenceRelationService(storage, locator_adapter=Utf8LineLocatorAdapter(
                FilePayloadStore(payload_directory, scope_id=SCOPE)))
            barrier.wait(timeout=15)
            output.put(service.revise_acceptance(command))
    except Exception as error:
        output.put({"worker_error": type(error).__name__, "detail": str(error)})


class ClaimEvidenceIntegrationTests(ClaimTestCase):
    def test_forecast_asserted_approval_and_equivalence_leave_matter_identity_untouched(self):
        other = self.make_matter("subject-b")
        before = [self.storage.get(entity_ref(item)) for item in (self.subject, other)]
        for identity, value, predicate in (
            ("forecast", "funding expected next year", "example:forecast"),
            ("asserted-approval", "the speaker asserts approval", "example:approval"),
            ("equivalence", {"asserted_same_as": entity_ref(other)}, "example:equivalence"),
        ):
            claim, _, _ = self.append(identity, value=value, predicate=predicate)
            self.relate(claim, f"reported-{identity}", relation="reports_assertion", component=None)
        self.assertEqual([self.storage.get(entity_ref(item)) for item in before], before)
        self.assertEqual(self.matters.resolve([identity_key("subject-a")]), before[0])
        self.assertEqual(self.matters.resolve([identity_key("subject-b")]), before[1])
        self.assertNotEqual(before[0]["id"], before[1]["id"])
        for kind in ("assessment", "matter_relation", "accepted_association", "occurrence"):
            self.assertNotIn(kind, self.record_counts())
        self.assertEqual(self.record_counts()["matter"], 2)

    def test_branching_corrections_preserve_every_claim_and_source(self):
        original, _, original_result = self.append("original")
        left, _, left_result = self.append("left", version="2-left", value="left correction", supersedes=[original])
        right, _, _ = self.append("right", version="2-right", value="right correction", supersedes=[original])
        joined, _, joined_result = self.append("joined", version="3", value="explicit later correction",
                                               supersedes=[left, right])
        self.assertEqual({row["id"] for row in self.claims.revisions(pin(original))},
                         {"original", "left", "right", "joined"})
        self.assertEqual(self.claims.heads(pin(original)), [joined])
        self.assertEqual(self.storage.get(pin(original)), original)
        self.assertEqual(self.storage.get(pin(left)), left)
        self.assertEqual(self.storage.get(pin(right)), right)
        self.assertEqual(self.ingestor.read_payload(pin(self.source)).data, PASSAGE)
        self.assertEqual(original_result["body"]["changes"], [
            {"cause": "new_evidence", "before": [], "after": [pin(original)]}])
        self.assertEqual(left_result["body"]["changes"], [
            {"cause": "evidence_correction", "before": [pin(original)], "after": [pin(left)]}])
        self.assertEqual(joined_result["body"]["changes"][0]["cause"], "evidence_correction")
        self.assertEqual({ref["id"] for ref in joined_result["body"]["changes"][0]["before"]}, {"left", "right"})

    def test_unmerged_claim_branches_have_multiple_heads_not_a_latest_truth(self):
        original, _, _ = self.append("original")
        left, _, _ = self.append("left", version="2-left", supersedes=[original])
        right, _, _ = self.append("right", version="2-right", supersedes=[original])
        self.assertEqual({row["id"] for row in self.claims.heads(pin(original))}, {left["id"], right["id"]})
        unrelated, _, _ = self.append("separate-same-proposition")
        self.assertEqual(self.claims.heads(pin(unrelated)), [unrelated])
        self.assertEqual(len(self.claims.for_subject(entity_ref(self.subject))), 4)

    def test_contradictory_sources_and_withdrawn_relation_history_survive_restart(self):
        claim, _, _ = self.append()
        support, _, _ = self.relate(claim, "support")
        contradictory = self.observe("contradictory", b"There is no funding discussion.\n")
        against, _, _ = self.relate(claim, "against", source=contradictory, relation="contradicts",
                                   quotation="There is no funding discussion.")
        command = acceptance_command("withdraw-support", support, "superseded")
        result = self.relations.revise_acceptance(self.relations.prepare(command))
        revised = self.storage.get(result["body"]["relation"])
        self.assertEqual(result["body"]["previous"], pin(support))
        self.assertEqual(result["body"]["changes"], [{"cause": "disposition_change",
                         "before": [pin(support)], "after": [pin(revised)]}])
        with SQLiteStore(self.database, scope_id=SCOPE) as reopened:
            service = EvidenceRelationService(reopened, locator_adapter=Utf8LineLocatorAdapter(self.payloads))
            self.assertEqual(service.history(entity_ref(support)), [support, revised])
            self.assertEqual({row["id"] for row in service.for_claim(pin(claim))}, {"support", "against"})
            self.assertEqual(reopened.get(pin(against)), against)
            self.assertEqual(reopened.get(pin(support)), support)
            self.assertEqual(reopened.get(pin(self.source)), self.source)
        self.assertEqual(self.record_counts()["claim"], 1)

    def test_exact_claim_retry_and_same_id_duplicate_keep_original_pin(self):
        claim, prepared, original = self.append()
        correction, _, _ = self.append("later", version="2", supersedes=[claim])
        self.assertEqual(self.claims.append(prepared), original)
        duplicate = deepcopy(prepared)
        duplicate.update(command_id="duplicate-claim", idempotency_key="key:duplicate-claim", expected_revisions=[])
        result = self.claims.append(self.claims.prepare(duplicate))
        self.assertEqual(result["outcome"], "duplicate")
        self.assertEqual(result["body"], {"claim": pin(claim), "changes": []})
        self.assertEqual(self.claims.heads(pin(claim)), [correction])
        self.assertEqual(len(self.storage.history(entity_ref(claim))), 1)

    def test_equal_propositions_with_different_ids_are_retained(self):
        first, _, _ = self.append("first")
        second, _, _ = self.append("second")
        self.assertEqual(first["body"], second["body"])
        self.assertNotEqual(pin(first), pin(second))
        self.assertEqual({row["id"] for row in self.claims.for_subject(entity_ref(self.subject))}, {"first", "second"})

    def test_duplicate_and_retry_preserve_validation_after_payload_disappears(self):
        claim, _, _ = self.append()
        relation, prepared, original = self.relate(claim)
        unavailable = UnavailablePayloads(scope_id=SCOPE)
        offline = EvidenceRelationService(self.storage, locator_adapter=Utf8LineLocatorAdapter(unavailable))
        self.assertEqual(offline.relate(prepared), original)
        self.assertEqual(unavailable.read_calls, 0)
        duplicate = deepcopy(prepared)
        duplicate.update(command_id="duplicate-relation", idempotency_key="key:duplicate-relation", expected_revisions=[])
        duplicate["body"].pop("validation", None)
        result = offline.relate(offline.prepare(duplicate))
        self.assertEqual(result["outcome"], "duplicate")
        self.assertEqual(result["body"]["relation"], pin(relation))
        self.assertEqual(result["body"]["locator_validation"], relation["body"]["locator_validation"])
        self.assertEqual(result["body"]["changes"], [])
        self.assertEqual(unavailable.read_calls, 0)
        fresh = relation_command("fresh-offline", "fresh-offline", claim, self.source)
        failure = offline.relate(offline.prepare(fresh))
        self.assert_failure(failure, "E_EVIDENCE_UNAVAILABLE")
        self.assertEqual(unavailable.read_calls, 1)
        self.assertEqual(self.relations.for_claim(pin(claim)), [relation])

    def test_relation_acceptance_update_preserves_citation_fields_and_exact_retry(self):
        claim, _, _ = self.append()
        relation, _, _ = self.relate(claim)
        command = acceptance_command("reject", relation, "rejected")
        prepared = self.relations.prepare(command)
        result = self.relations.revise_acceptance(prepared)
        rejected = self.storage.get(result["body"]["relation"])
        expected_body = deepcopy(relation["body"])
        expected_body["acceptance"] = deepcopy(command["body"]["acceptance"])
        self.assertEqual(rejected["body"], expected_body)
        self.assertEqual(rejected["revision"], 2)
        self.assertEqual(rejected["creation_receipt"], relation["creation_receipt"])
        self.assertEqual(rejected["provenance"], relation["provenance"])
        restore = acceptance_command("restore", rejected, "accepted")
        self.relations.revise_acceptance(self.relations.prepare(restore))
        self.assertEqual(self.relations.revise_acceptance(prepared), result)
        self.assertEqual(self.storage.get(entity_ref(relation))["revision"], 3)
        self.assertEqual(self.storage.get(pin(relation)), relation)

    def test_acceptance_noop_does_not_create_revision_or_dependency_change(self):
        claim, _, _ = self.append()
        relation, _, _ = self.relate(claim)
        command = acceptance_command("same-acceptance", relation, "accepted")
        command["body"]["acceptance"] = deepcopy(relation["body"]["acceptance"])
        command["authority"] = deepcopy(relation["body"]["acceptance"]["authority"])
        result = self.relations.revise_acceptance(self.relations.prepare(command))
        self.assertEqual(result["outcome"], "unchanged")
        self.assertEqual(result["body"], {"relation": pin(relation), "changes": []})
        self.assertEqual(self.relations.history(entity_ref(relation)), [relation])

    def test_frozen_stale_acceptance_is_durable_and_cannot_overwrite_winner(self):
        claim, _, _ = self.append()
        relation, _, _ = self.relate(claim)
        stale = self.relations.prepare(acceptance_command("stale", relation, "rejected"))
        winner = self.relations.prepare(acceptance_command("winner", relation, "superseded"))
        winner_result = self.relations.revise_acceptance(winner)
        refusal = self.relations.revise_acceptance(stale)
        self.assert_failure(refusal, "E_REVISION_CONFLICT")
        self.assertEqual(self.relations.revise_acceptance(stale), refusal)
        self.assertEqual(self.storage.command_receipt(stale["idempotency_key"])["result"], refusal)
        self.assertEqual(pin(self.storage.get(entity_ref(relation))), winner_result["body"]["relation"])
        self.assertEqual(len(self.relations.history(entity_ref(relation))), 2)

    def test_two_process_acceptance_writers_cannot_lose_revision(self):
        claim, _, _ = self.append()
        relation, _, _ = self.relate(claim)
        commands = [self.relations.prepare(acceptance_command(identity, relation, status))
                    for identity, status in (("writer-a", "rejected"), ("writer-b", "superseded"))]
        context = multiprocessing.get_context("spawn")
        barrier, output = context.Barrier(2), context.Queue()
        processes = [context.Process(target=acceptance_writer, args=(
            str(self.database), str(self.payload_directory), command, barrier, output)) for command in commands]
        started = []
        try:
            for process in processes:
                process.start()
                started.append(process)
            results = [output.get(timeout=25) for _ in started]
            for process in started:
                process.join(timeout=25)
                self.assertFalse(process.is_alive(), "Competing acceptance writer did not terminate.")
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in started:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
            output.close()
            output.join_thread()
        self.assertEqual(sum(result.get("outcome") == "updated" for result in results), 1, results)
        failures = [result for result in results if result.get("status") == "failure"]
        self.assertEqual(len(failures), 1, results)
        self.assert_failure(failures[0], "E_REVISION_CONFLICT")
        self.assertEqual(len(self.relations.history(entity_ref(relation))), 2)
        for command in commands:
            self.assertEqual(self.relations.revise_acceptance(command),
                             self.storage.command_receipt(command["idempotency_key"])["result"])

    def test_prepared_claim_stale_subject_guard_refuses_without_claim_child(self):
        command = claim_command("stale-subject", "stale-subject", self.subject, self.source)
        prepared = self.claims.prepare(command)
        update = metadata_command("new-title", self.subject, {"title": "New context"})
        self.matters.update_metadata(self.matters.prepare(update))
        result = self.claims.append(prepared)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(self.claims.for_subject(entity_ref(self.subject)), [])
        self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)

    def test_frozen_validation_cannot_be_rebound_to_other_evidence_or_locator(self):
        claim, _, _ = self.append()
        original_command = relation_command("binding", "binding", claim, self.source)
        original = self.relations.prepare(original_command)
        for identity, mutation in (
            ("wrong-evidence", lambda declaration: declaration["evidence"].update(digest="f" * 64)),
            ("wrong-locator", lambda declaration: declaration["locator"]["selector"]["value"].update(end_line=2)),
            ("wrong-quote", lambda declaration: declaration.update(quotation="No allocation")),
            ("wrong-content", lambda declaration: declaration["content"].update(digest="f" * 64)),
        ):
            with self.subTest(identity=identity):
                command = deepcopy(original)
                command.update(command_id=identity, idempotency_key=f"key:{identity}")
                command["body"]["relation"]["id"] = identity
                mutation(command["body"]["validation"]["value"])
                result = self.relations.relate(command)
                self.assert_failure(result, "E_EVIDENCE_INVALID")
                self.assertEqual(self.relations.for_claim(pin(claim)), [])

    def test_foreign_scope_reference_is_refused_before_query(self):
        claim, _, _ = self.append()
        for target in ("claim", "evidence"):
            with self.subTest(target=target):
                command = relation_command(f"foreign-{target}", f"foreign-{target}", claim, self.source)
                command["body"]["relation"]["body"][target]["scope_id"] = "synthetic:foreign"
                with self.assertRaises(StorageError) as error:
                    self.relations.prepare(command)
                self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
        self.assertEqual(self.relations.for_claim(pin(claim)), [])

    def test_changed_input_cannot_overwrite_existing_claim_identity(self):
        claim, prepared, _ = self.append()
        command = deepcopy(prepared)
        command.update(command_id="changed-id", idempotency_key="key:changed-id", expected_revisions=[])
        command["body"]["claim"]["body"]["value"]["value"] = "different assertion"
        result = self.claims.append(self.claims.prepare(command))
        self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(self.storage.get(pin(claim)), claim)
        self.assertEqual(len(self.storage.history(entity_ref(claim))), 1)
        self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)

    def test_correction_requires_changed_version_and_same_subject_predicate(self):
        original, _, _ = self.append("original")
        other = self.make_matter("other")
        cases = (
            ("same-version", self.subject, "example:funding", "1.0"),
            ("wrong-subject", other, "example:funding", "2.0"),
            ("wrong-predicate", self.subject, "example:unrelated", "2.0"),
        )
        for identity, subject, predicate, version in cases:
            with self.subTest(identity=identity):
                command = claim_command(identity, identity, subject, self.source, supersedes=[original],
                                        predicate=predicate, version=version)
                result = self.claims.append(self.claims.prepare(command))
                self.assert_failure(result, "E_EVIDENCE_INVALID")
        self.assertEqual(self.claims.revisions(pin(original)), [original])
        self.assertEqual(self.claims.heads(pin(original)), [original])
        self.assertEqual(self.record_counts()["claim"], 1)

    def test_missing_or_changed_immutable_attribution_pin_cannot_be_silently_refreshed(self):
        for identity, mutation in (
            ("missing-attribution", {"id": "absent-source"}),
            ("wrong-attribution-digest", {"digest": "f" * 64}),
        ):
            with self.subTest(identity=identity):
                command = claim_command(identity, identity, self.subject, self.source)
                command["body"]["claim"]["body"]["attribution"][0].update(mutation)
                prepared = self.claims.prepare(command)
                result = self.claims.append(prepared)
                self.assert_failure(result, "E_REVISION_CONFLICT")
                self.assertEqual(self.claims.for_subject(entity_ref(self.subject)), [])

    def test_foreign_claim_attribution_and_correction_are_refused(self):
        original, _, _ = self.append("original")
        for field in ("attribution", "supersedes"):
            with self.subTest(field=field):
                command = claim_command(f"foreign-{field}", f"foreign-{field}", self.subject,
                                        self.source, version="2", supersedes=[original])
                refs = (command["body"]["claim"]["body"][field] if field == "attribution"
                        else command["body"]["claim"][field])
                refs[0]["scope_id"] = "synthetic:foreign"
                with self.assertRaises(StorageError) as error:
                    self.claims.prepare(command)
                self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
        self.assertEqual(self.claims.revisions(pin(original)), [original])

    def test_dependency_changes_are_defensive_and_retry_receipt_stays_original(self):
        claim, prepared, result = self.append()
        expected = deepcopy(result)
        result["body"]["changes"][0]["after"][0]["id"] = "caller-mutated"
        self.assertEqual(self.claims.append(prepared), expected)
        records = self.claims.for_subject(entity_ref(self.subject))
        records[0]["body"]["value"]["value"] = "caller-mutated"
        self.assertEqual(self.storage.get(pin(claim)), claim)

    def test_creation_duplicate_after_acceptance_change_keeps_current_disposition(self):
        claim, _, _ = self.append()
        relation, original_command, _ = self.relate(claim)
        revise = acceptance_command("withdraw-before-duplicate", relation, "rejected")
        update = self.relations.revise_acceptance(self.relations.prepare(revise))
        current = self.storage.get(update["body"]["relation"])
        duplicate = deepcopy(original_command)
        duplicate.update(command_id="duplicate-after-withdrawal",
                         idempotency_key="key:duplicate-after-withdrawal", expected_revisions=[])
        duplicate["body"].pop("validation")
        result = self.relations.relate(self.relations.prepare(duplicate))
        self.assertEqual(result["outcome"], "duplicate")
        self.assertEqual(result["body"]["relation"], pin(current))
        self.assertEqual(result["body"]["locator_validation"], relation["body"]["locator_validation"])
        self.assertEqual(self.storage.get(entity_ref(relation))["body"]["acceptance"]["status"], "rejected")
        self.assertEqual(len(self.relations.history(entity_ref(relation))), 2)

    def test_changed_relation_input_cannot_reuse_original_identity(self):
        claim, _, _ = self.append()
        relation, original_command, _ = self.relate(claim)
        # Preparation may reject occupied identity before adapter work. A
        # frozen valid read set exercises the same refusal durably in commit.
        original_command = deepcopy(original_command)
        original_command.update(command_id="change-existing-relation",
                                idempotency_key="key:change-existing-relation", expected_revisions=[])
        prepared = self.relations.prepare(original_command)
        prepared["body"]["relation"]["body"]["relation"] = "contradicts"
        result = self.relations.relate(prepared)
        self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(self.storage.get(entity_ref(relation)), relation)
        self.assertEqual(self.relations.history(entity_ref(relation)), [relation])
