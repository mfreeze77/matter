"""Explicit candidate outcomes and proposal/permission separation for MAT-008."""

from matter.associations import AssociationService
from matter.storage import entity_ref, pin

from association_helpers import (AssociationTestCase, entry, policy_for,
    acceptance_command, proposal_command, publish_command, query_for, semantic_evaluation)
from occurrence_helpers import coverage


class AssociationOutcomeTests(AssociationTestCase):
    def test_complete_zero_candidates_is_no_match_with_persisted_proposal(self):
        candidate_set, entries, _, _ = self.publish([])
        proposal, prepared, result = self.propose(candidate_set, entries)
        self.assertEqual(result["outcome"], "no_match")
        self.assertEqual(proposal["body"]["outcome"], "no_match")
        self.assertEqual(proposal["body"]["candidates"], [])
        self.assertEqual(proposal["body"]["selected"], [])
        self.assertEqual(self.service.propose(prepared), result)
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])
        self.assertNotIn("accepted_association", self.record_counts())

    def test_two_exact_matching_candidates_are_ambiguous_not_ranked(self):
        a, b = self.matter("a"), self.matter("b")
        candidate_set, entries, _, _ = self.publish([a, b])
        proposal, _, result = self.propose(candidate_set, entries)
        self.assertEqual(result["outcome"], "ambiguous")
        self.assertEqual(proposal["body"]["outcome"], "ambiguous")
        self.assertEqual({item["candidate"]["id"] for item in proposal["body"]["candidates"]}, {"a", "b"})
        self.assertEqual(proposal["body"]["selected"], [])
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])

    def test_unique_exact_match_creates_proposal_without_accepted_attachment(self):
        candidate = self.matter("candidate")
        candidate_set, entries, _, _ = self.publish([candidate])
        proposal, _, result = self.propose(candidate_set, entries)
        self.assertEqual(result["outcome"], "proposal")
        self.assertEqual(proposal["body"]["outcome"], "matched")
        self.assertEqual(proposal["body"]["selected"], [pin(candidate)])
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])
        self.assertEqual(self.storage.get(entity_ref(candidate)), candidate)
        self.assertNotIn("accepted_association", self.record_counts())

    def test_nonmatching_catalog_entry_is_retained_but_does_not_create_match(self):
        candidate = self.matter("different-key")
        candidate_set, _, _, _ = self.publish([candidate], entries=[entry(candidate, self.subject,
            keys=[{"namespace": "example:catalog-key", "value": "another-subject"}])])
        proposal, _, result = self.propose(candidate_set, [])
        self.assertEqual(result["outcome"], "no_match")
        self.assertEqual(proposal["body"]["selected"], [])
        self.assertEqual(candidate_set["value"]["value"]["entries"][0]["candidate"], pin(candidate))

    def test_partial_empty_catalog_is_insufficient_not_no_match(self):
        candidate_set, entries, _, _ = self.publish([], source_coverage=coverage("partial"))
        proposal, _, result = self.propose(candidate_set, entries)
        self.assertEqual(result["outcome"], "insufficient_evidence")
        self.assertEqual(proposal["body"]["outcome"], "insufficient_evidence")
        self.assertEqual(proposal["body"]["selected"], [])
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])

    def test_unavailable_key_evidence_does_not_establish_uniqueness(self):
        source = self.observe("unavailable", availability="unavailable")
        candidate = self.matter("candidate")
        query = query_for(source)
        candidate_set, entries, _, _ = self.publish([candidate], query=query, source=source)
        proposal, _, result = self.propose(candidate_set, entries, query=query, source=source)
        self.assertEqual(result["outcome"], "insufficient_evidence")
        self.assertEqual(proposal["body"]["selected"], [])
        self.assertEqual(len(proposal["body"]["candidates"]), 1)

    def test_unknown_candidate_id_is_refused_before_publication(self):
        candidate = self.matter("existing")
        unknown = pin(candidate)
        unknown["id"] = "not-present"
        command = publish_command("unknown", self.authority, self.query,
                                  [entry(unknown, self.subject)], self.subject)
        self.assert_refused(self.service.prepare, self.service.publish_candidates, command, "E_NOT_FOUND")
        self.assertNotIn("association_proposal", self.record_counts())
        self.assertNotIn("accepted_association", self.record_counts())

    def test_foreign_candidate_scope_is_refused(self):
        candidate = self.matter("existing")
        foreign = pin(candidate)
        foreign["scope_id"] = "synthetic:foreign"
        command = publish_command("foreign", self.authority, self.query,
                                  [entry(foreign, self.subject)], self.subject)
        self.assert_refused(self.service.prepare, self.service.publish_candidates, command, "E_SCOPE_FORBIDDEN")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])

    def test_high_confidence_external_proposal_is_data_not_acceptance_authority(self):
        candidate = self.matter("candidate")
        query = query_for(self.subject, mode="semantic")
        candidate_set, entries, _, _ = self.publish([candidate], query=query)
        proposal, _, result = self.propose(candidate_set, entries, query=query,
                                         evaluation=semantic_evaluation([candidate]))
        self.assertEqual(result["outcome"], "proposal")
        self.assertEqual(proposal["body"]["uncertainty"]["value"]["confidence"], "0.999999")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])
        command = acceptance_command("semantic-denied", self.authority, proposal, candidate_set,
                                     [candidate], self.policy)
        self.assert_refused(self.service.prepare, self.service.accept, command, "E_AUTHORITY_REQUIRED")
        # The same authority gate also protects direct execution by a host
        # supplying the exact proposal and evaluation-receipt read guards.
        command["expected_revisions"] = [pin(self.authority), pin(proposal), proposal["body"]["evaluation"]]
        refused = self.service.accept(command)
        self.assert_failure(refused, "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], refused)
        self.assertNotIn("accepted_association", self.record_counts())

    def test_semantic_selection_cannot_name_candidate_outside_frozen_set(self):
        allowed, outsider = self.matter("allowed"), self.matter("outsider")
        query = query_for(self.subject, mode="semantic")
        candidate_set, entries, _, _ = self.publish([allowed], query=query)
        command = proposal_command("outside", self.authority, candidate_set, query, entries,
                                   self.subject, evaluation=semantic_evaluation([outsider]))
        self.assert_refused(self.service.prepare, self.service.propose, command, "E_EVIDENCE_INVALID")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])

    def test_changed_actor_cannot_use_an_allowed_authority_receipt(self):
        candidate = self.matter("candidate")
        candidate_set, entries, _, _ = self.publish([candidate])
        proposal, _, _ = self.propose(candidate_set, entries)
        command = self.accept_command(proposal, candidate_set, [candidate])
        command["actor"]["id"] = "untrusted-evaluator"
        self.assert_failure(self.service.accept(command), "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])

    def test_operation_receipt_cannot_masquerade_as_host_authority(self):
        ordinary = self.storage.get(self.subject["creation_receipt"])
        service = AssociationService(self.storage, policy=policy_for(ordinary))
        command = publish_command("false-authority", ordinary, self.query, [], self.subject)
        self.assert_refused(service.prepare, service.publish_candidates, command, "E_AUTHORITY_REQUIRED")
        self.assertNotIn("association_proposal", self.record_counts())

    def test_external_evaluation_failure_is_not_no_match_or_absence_evidence(self):
        candidate = self.matter("candidate")
        query = query_for(self.subject, mode="semantic")
        candidate_set, entries, _, _ = self.publish([candidate], query=query)
        proposal, _, result = self.propose(candidate_set, entries, query=query,
                                         evaluation=semantic_evaluation([], outcome="evaluation_failed"))
        self.assertEqual(result["outcome"], "evaluation_failed")
        self.assertEqual(proposal["body"]["outcome"], "evaluation_failed")
        self.assertEqual(proposal["body"]["selected"], [])
        self.assertEqual(proposal["body"]["candidates"], [
            {"candidate": pin(candidate), "basis": [pin(self.subject)]}])
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])
