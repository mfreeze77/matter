"""Current candidate sets, bounded authority and persistent replay protection."""

from copy import deepcopy
import multiprocessing

from matter.associations import AssociationService
from matter.storage import SQLiteStore, entity_ref, pin, snapshot_digest

from association_helpers import (AssociationTestCase, SCOPE, RELATION, acceptance_command,
    decision_command, entry, policy_for, proposal_command)
from matter_helpers import identity_key, metadata_command


def digest_pin(record):
    return {**entity_ref(record), "digest": snapshot_digest(record)}


def acceptance_worker(database, command, barrier, output):
    try:
        with SQLiteStore(database, scope_id=SCOPE) as storage:
            authority = storage.get(command["authority"])
            service = AssociationService(storage, policy=policy_for(authority))
            barrier.wait(timeout=20)
            result = service.accept(command)
            output.put({"command_id": command["command_id"], "result": result})
    except Exception as error:
        output.put({"worker_error": type(error).__name__, "detail": str(error)})


class AssociationAcceptanceTests(AssociationTestCase):
    def matched(self, *, candidate=None):
        candidate = candidate or self.matter("candidate")
        candidate_set, entries, _, _ = self.publish([candidate])
        proposal, _, _ = self.propose(candidate_set, entries)
        return candidate, candidate_set, entries, proposal

    def test_attachment_commits_without_merging_or_rewriting_members(self):
        candidate, candidate_set, _, proposal = self.matched()
        other = self.matter("separate-matter")
        prepared = self.accept_command(proposal, candidate_set, [candidate])
        result = self.service.accept(prepared)
        self.assertEqual(result.get("outcome"), "accepted", result)
        association = self.storage.get(result["body"]["association"])
        self.assertEqual({ref["id"] for ref in association["body"]["members"]}, {self.subject["id"], candidate["id"]})
        self.assertEqual(association["body"]["status"], "active")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [association])
        self.assertEqual(self.storage.get(entity_ref(candidate)), candidate)
        self.assertEqual(self.storage.get(entity_ref(other)), other)
        self.assertEqual(self.matters.resolve([identity_key("candidate")]), candidate)
        self.assertEqual(self.matters.resolve([identity_key("separate-matter")]), other)
        merge = acceptance_command("merge-denied", self.authority, proposal, candidate_set,
                                   [candidate], self.policy, capability="merge")
        self.assert_refused(self.service.prepare, self.service.accept, merge, "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [association])
        self.assertNotIn("matter_relation", self.record_counts())
        self.assertNotIn("assessment", self.record_counts())

    def test_new_matching_candidate_invalidates_frozen_unique_proposal(self):
        candidate, candidate_set, _, proposal = self.matched()
        acceptance = self.accept_command(proposal, candidate_set, [candidate])
        second = self.matter("new-matching-candidate")
        revised, entries, _, _ = self.publish([candidate, second], command_id="publish-expanded", previous=candidate_set)
        self.assertEqual(revised["revision"], candidate_set["revision"] + 1)
        refusal = self.service.accept(acceptance)
        self.assert_failure(refusal, "E_REVISION_CONFLICT")
        self.assertEqual(self.service.accept(acceptance), refusal)
        self.assertEqual(self.storage.command_receipt(acceptance["idempotency_key"])["result"], refusal)
        new_proposal, _, result = self.propose(revised, entries, command_id="propose-expanded")
        self.assertEqual(result["outcome"], "ambiguous")
        self.assertEqual(new_proposal["body"]["selected"], [])
        self.assertEqual(self.storage.get(pin(proposal)), proposal)
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])

    def test_candidate_revision_update_refuses_prepared_acceptance(self):
        candidate, candidate_set, _, proposal = self.matched()
        prepared = self.accept_command(proposal, candidate_set, [candidate])
        update = metadata_command("candidate-new-context", candidate, {"title": "Revised candidate context"})
        changed = self.matters.update_metadata(self.matters.prepare(update))
        refusal = self.service.accept(prepared)
        self.assert_failure(refusal, "E_REVISION_CONFLICT")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])
        self.assertEqual(self.storage.get(pin(candidate)), candidate)
        self.assertEqual(self.storage.get(entity_ref(candidate))["revision"], changed["body"]["matter"]["revision"])

    def test_nonmatching_catalog_member_changes_still_invalidate_catalog_snapshot(self):
        candidate, other = self.matter("candidate"), self.matter("other")
        entries = [entry(candidate, self.subject), entry(other, self.subject,
            keys=[{"namespace": "example:catalog-key", "value": "unmatched"}])]
        candidate_set, _, _, _ = self.publish([candidate, other], entries=entries)
        proposal, _, _ = self.propose(candidate_set, entries[:1])
        prepared = self.accept_command(proposal, candidate_set, [candidate])
        update = metadata_command("other-revised", other, {"description": "Changed catalog candidate"})
        self.matters.update_metadata(self.matters.prepare(update))
        self.assert_failure(self.service.accept(prepared), "E_REVISION_CONFLICT")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])

    def test_digest_form_current_candidate_and_set_pins_remain_valid(self):
        candidate, candidate_set, _, proposal = self.matched()
        command = acceptance_command("digest-accept", self.authority, proposal, digest_pin(candidate_set),
                                     [digest_pin(candidate)], self.policy)
        command["expected_revisions"] = [digest_pin(candidate_set), digest_pin(candidate)]
        prepared = self.service.prepare(command)
        self.assertIn(digest_pin(candidate), prepared["expected_revisions"])
        self.assertIn(digest_pin(candidate_set), prepared["expected_revisions"])
        result = self.service.accept(prepared)
        self.assertEqual(result.get("outcome"), "accepted", result)
        self.assertEqual(len(self.service.for_subject(entity_ref(self.subject), status="active")), 1)

    def test_publication_noop_and_exact_retry_preserve_catalog_history(self):
        candidate = self.matter("candidate")
        candidate_set, entries, prepared, result = self.publish([candidate])
        same, _, _, same_result = self.publish([candidate], command_id="publish-same", previous=candidate_set)
        self.assertEqual(same_result["outcome"], "unchanged")
        self.assertEqual(same, candidate_set)
        second = self.matter("second")
        revised, _, _, _ = self.publish([candidate, second], command_id="publish-new", previous=candidate_set)
        self.assertEqual(self.service.publish_candidates(prepared), result)
        self.assertEqual(self.storage.get(entity_ref(candidate_set)), revised)
        self.assertEqual(self.storage.history(entity_ref(candidate_set)), [candidate_set, revised])

    def test_rejection_revokes_attachment_and_old_success_retry_cannot_reactivate(self):
        candidate, candidate_set, _, proposal = self.matched()
        acceptance = self.accept_command(proposal, candidate_set, [candidate])
        accepted = self.service.accept(acceptance)
        original = self.storage.get(accepted["body"]["association"])
        decision, result = self.decide(candidate)
        disposition = self.storage.get(result["body"]["disposition"])
        self.assertEqual(disposition["value"]["value"]["status"], "blocked")
        self.assertEqual(disposition["value"]["value"]["kind"], "reject")
        current = self.storage.get(entity_ref(original))
        self.assertEqual(current["body"]["status"], "revoked")
        self.assertEqual(self.service.history(entity_ref(original)), [original, current])
        self.assertEqual(self.service.accept(acceptance), accepted)
        self.assertEqual(self.service.decide(decision), result)
        self.assertEqual(self.service.for_subject(entity_ref(self.subject), status="active"), [])
        self.assertEqual(self.service.for_subject(entity_ref(self.subject), status="revoked"), [current])

    def test_rejected_pair_blocks_new_proposal_id_and_new_command(self):
        candidate, candidate_set, entries, proposal = self.matched()
        self.decide(candidate)
        copied, _, _ = self.propose(candidate_set, entries, command_id="new-run-new-proposal")
        self.assertNotEqual(pin(copied), pin(proposal))
        fresh = acceptance_command("fresh-accept-rejected", self.authority, copied, candidate_set,
                                   [candidate], self.policy)
        self.assert_refused(self.service.prepare, self.service.accept, fresh, "E_ASSOCIATION_CONFLICT")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject), status="active"), [])

    def test_protected_attachment_survives_reopen_and_replayed_proposals(self):
        candidate, candidate_set, entries, _ = self.matched()
        _, decision = self.decide(candidate, decision="protect")
        expected_disposition = self.storage.get(decision["body"]["disposition"])
        with SQLiteStore(self.database, scope_id=SCOPE) as reopened:
            service = AssociationService(reopened, policy=self.policy)
            self.assertEqual(service.disposition(entity_ref(self.subject), entity_ref(candidate), RELATION, "attach"),
                             expected_disposition)
            command = proposal_command("restart-proposal", self.authority, candidate_set, self.query,
                                       entries, self.subject)
            proposal_result = service.propose(service.prepare(command))
            proposal = reopened.get(proposal_result["body"]["proposal"])
            accept = acceptance_command("restart-accept", self.authority, proposal, candidate_set,
                                        [candidate], self.policy)
            self.assert_refused(service.prepare, service.accept, accept, "E_ASSOCIATION_CONFLICT")
            self.assertEqual(service.for_subject(entity_ref(self.subject), status="active"), [])

    def test_nonmerge_protection_does_not_forbid_authorized_attachment(self):
        candidate, candidate_set, _, proposal = self.matched()
        self.decide(candidate, decision="protect", capability="merge")
        prepared = self.accept_command(proposal, candidate_set, [candidate])
        result = self.service.accept(prepared)
        self.assertEqual(result.get("outcome"), "accepted", result)
        self.assertEqual(self.storage.get(entity_ref(candidate)), candidate)
        disposition = self.service.disposition(entity_ref(self.subject), entity_ref(candidate), RELATION, "merge")
        self.assertEqual(disposition["value"]["value"]["status"], "blocked")
        merge = acceptance_command("protected-merge", self.authority, proposal, candidate_set,
                                   [candidate], self.policy, capability="merge")
        self.assert_refused(self.service.prepare, self.service.accept, merge, "E_AUTHORITY_REQUIRED")

    def test_authorized_release_retains_decision_history_and_requires_new_acceptance(self):
        self.policy = policy_for(self.authority, allow_correction=True)
        self.service = AssociationService(self.storage, policy=self.policy)
        candidate, candidate_set, entries, _ = self.matched()
        _, rejected = self.decide(candidate)
        blocked = self.storage.get(rejected["body"]["disposition"])
        release, result = self.decide(candidate, command_id="release", decision="release", previous=blocked)
        released = self.storage.get(result["body"]["disposition"])
        self.assertEqual(released["value"]["value"]["status"], "released")
        self.assertEqual(self.storage.history(entity_ref(blocked)), [blocked, released])
        self.assertEqual(self.service.for_subject(entity_ref(self.subject), status="active"), [])
        proposal, _, _ = self.propose(candidate_set, entries, command_id="after-release")
        acceptance = self.accept_command(proposal, candidate_set, [candidate], command_id="accept-after-release")
        self.assertEqual(self.service.accept(acceptance)["outcome"], "accepted")
        self.assertEqual(self.service.decide(release), result)
        self.assertEqual(len(self.service.for_subject(entity_ref(self.subject), status="active")), 1)

    def test_release_without_explicit_correction_permission_is_refused(self):
        candidate, _, _, _ = self.matched()
        _, result = self.decide(candidate)
        blocked = self.storage.get(result["body"]["disposition"])
        command = decision_command("unauthorized-release", self.authority, self.subject, candidate,
                                   self.policy, decision="release", previous=blocked)
        self.assert_refused(self.service.prepare, self.service.decide, command, "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.storage.get(entity_ref(blocked)), blocked)

    def test_stale_release_cannot_override_newer_protection(self):
        self.policy = policy_for(self.authority, allow_correction=True)
        self.service = AssociationService(self.storage, policy=self.policy)
        candidate, _, _, _ = self.matched()
        _, result = self.decide(candidate)
        blocked = self.storage.get(result["body"]["disposition"])
        release = decision_command("stale-release", self.authority, self.subject, candidate,
                                   self.policy, decision="release", previous=blocked)
        prepared = self.service.prepare(release)
        _, protection = self.decide(candidate, command_id="new-protection", decision="protect", previous=blocked)
        current = self.storage.get(protection["body"]["disposition"])
        refusal = self.service.decide(prepared)
        self.assert_failure(refusal, "E_REVISION_CONFLICT")
        self.assertEqual(self.storage.get(entity_ref(blocked)), current)
        self.assertEqual(current["value"]["value"]["kind"], "protect")

    def test_two_process_acceptances_do_not_duplicate_membership_or_lose_receipts(self):
        candidate, candidate_set, _, proposal = self.matched()
        commands = [self.accept_command(proposal, candidate_set, [candidate], command_id=identity)
                    for identity in ("writer-a", "writer-b")]
        context = multiprocessing.get_context("spawn")
        barrier, output = context.Barrier(2), context.Queue()
        processes = [context.Process(target=acceptance_worker, args=(str(self.database), command, barrier, output))
                     for command in commands]
        started = []
        try:
            for process in processes:
                process.start()
                started.append(process)
            messages = [output.get(timeout=30) for _ in started]
            for process in started:
                process.join(timeout=30)
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
        self.assertTrue(all("result" in message for message in messages), messages)
        results = [message["result"] for message in messages]
        self.assertEqual(sum(result.get("outcome") == "accepted" for result in results), 1, results)
        failures = [result for result in results if result["status"] == "failure"]
        self.assertEqual(len(failures), 1, results)
        self.assert_failure(failures[0], "E_REVISION_CONFLICT")
        current = self.service.for_subject(entity_ref(self.subject), status="active")
        self.assertEqual(len(current), 1)
        self.assertEqual(len(self.service.history(entity_ref(current[0]))), 1)
        for command in commands:
            self.assertEqual(self.service.accept(command), self.storage.command_receipt(command["idempotency_key"])["result"])

    def test_high_confidence_semantic_proposal_cannot_override_protected_pair(self):
        from association_helpers import query_for, semantic_evaluation
        self.policy = policy_for(self.authority, allow_semantic=True)
        self.service = AssociationService(self.storage, policy=self.policy)
        candidate = self.matter("semantic-candidate")
        query = query_for(self.subject, mode="semantic")
        candidate_set, entries, _, _ = self.publish([candidate], query=query)
        self.decide(candidate, decision="protect")
        proposal, _, result = self.propose(candidate_set, entries, query=query,
            evaluation=semantic_evaluation([candidate], score="1.0"))
        self.assertEqual(result["outcome"], "proposal")
        command = acceptance_command("high-confidence-blocked", self.authority, proposal,
                                     candidate_set, [candidate], self.policy)
        self.assert_refused(self.service.prepare, self.service.accept, command, "E_ASSOCIATION_CONFLICT")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject), status="active"), [])

    def test_relation_version_change_cannot_bypass_stable_protected_pair(self):
        from matter.canonical import source_digest
        revised_relation = deepcopy(RELATION)
        revised_relation.update(version="2.0", digest=source_digest(b"Synthetic attachment relation version2"))
        self.policy = policy_for(self.authority, relations=[RELATION, revised_relation])
        self.service = AssociationService(self.storage, policy=self.policy)
        candidate, candidate_set, _, proposal = self.matched()
        self.decide(candidate, decision="protect")
        command = acceptance_command("new-relation-version", self.authority, proposal, candidate_set,
                                     [candidate], self.policy, relation=revised_relation)
        self.assert_refused(self.service.prepare, self.service.accept, command, "E_ASSOCIATION_CONFLICT")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject), status="active"), [])

    def test_semantic_acceptance_must_retain_every_considered_alternative(self):
        from association_helpers import query_for, semantic_evaluation
        self.policy = policy_for(self.authority, allow_semantic=True)
        self.service = AssociationService(self.storage, policy=self.policy)
        selected, alternative = self.matter("selected"), self.matter("alternative")
        query = query_for(self.subject, mode="semantic")
        candidate_set, entries, _, _ = self.publish([selected, alternative], query=query)
        proposal, _, _ = self.propose(candidate_set, entries, query=query,
                                     evaluation=semantic_evaluation([selected]))
        incomplete = acceptance_command("omit-alternative", self.authority, proposal, candidate_set,
                                        [selected], self.policy)
        self.assert_refused(self.service.prepare, self.service.accept, incomplete, "E_EVIDENCE_INVALID")
        complete = self.accept_command(proposal, candidate_set, [selected, alternative], command_id="all-alternatives")
        result = self.service.accept(complete)
        self.assertEqual(result.get("outcome"), "accepted", result)
        association = self.storage.get(result["body"]["association"])
        self.assertEqual({ref["id"] for ref in association["body"]["members"]}, {self.subject["id"], selected["id"]})
        self.assertEqual(self.storage.get(pin(proposal)), proposal)
        self.assertEqual(len(proposal["body"]["candidates"]), 2)

    def test_first_protection_after_prepare_invalidates_absent_disposition_read(self):
        import sqlite3
        candidate, candidate_set, _, proposal = self.matched()
        self.assertIsNone(self.service.disposition(
            entity_ref(self.subject), entity_ref(candidate), RELATION, "attach"))
        prepared = self.accept_command(proposal, candidate_set, [candidate], command_id="before-first-protection")
        _, decision = self.decide(candidate, command_id="first-protection", decision="protect")
        protection = self.storage.get(decision["body"]["disposition"])

        refused = self.service.accept(prepared)
        self.assert_failure(refused, "E_REVISION_CONFLICT")
        self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], refused)
        self.assertEqual(self.service.accept(prepared), refused)
        fresh = acceptance_command("after-first-protection", self.authority, proposal,
                                   candidate_set, [candidate], self.policy)
        self.assert_refused(self.service.prepare, self.service.accept, fresh, "E_ASSOCIATION_CONFLICT")
        self.assertEqual(self.service.for_subject(entity_ref(self.subject)), [])
        self.assertEqual(self.service.disposition(
            entity_ref(self.subject), entity_ref(candidate), RELATION, "attach"), protection)
        # A failed phantom read must leave neither the edge nor its query index.
        with sqlite3.connect(self.database) as connection:
            count = connection.execute(
                "SELECT count(*) FROM heads WHERE scope_id=? AND "
                "(record_type='accepted_association' OR namespace='matter.association_memberships')",
                (SCOPE,),
            ).fetchone()[0]
        self.assertEqual(count, 0)
