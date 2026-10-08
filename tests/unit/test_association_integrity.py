"""Association proof and historical integrity against inconsistent stored data."""

from copy import deepcopy

from association_helpers import (
    AssociationTestCase, SCOPE, acceptance_command, entry,
)
from integration.helpers import create_command
from matter.associations import _domain, _record_ref
from matter.storage import StorageError, entity_ref, pin


class AssociationIntegrityTests(AssociationTestCase):
    def seed_inconsistent_proposal(self, proposal, mutate, *, seed_id):
        """Persist typed but inconsistent proof using the trusted generic test port.

        Production callers use AssociationService. This deliberately simulates
        malformed service-owned records imported through another host handler;
        storage integrity alone cannot validate the proposal's semantic binding.
        """
        old_receipt = self.storage.get(proposal["body"]["evaluation"])
        details = deepcopy(old_receipt["body"]["details"]["value"])
        mutate(details)
        command = create_command(seed_id, seed_id + "-host-record", scope_id=SCOPE)
        captured = {}

        def seed(tx):
            receipt_input = deepcopy(old_receipt)
            receipt_input.pop("creation_receipt")
            receipt_input.update(_record_ref(SCOPE, seed_id, "evaluation"))
            parents = self.service._evaluation_parents(details)
            receipt_input["provenance"]["parents"] = parents
            receipt_input["body"].update(
                operation_id=seed_id, outcome="matter:" + details["outcome"], evidence=parents,
                details=_domain("association-evaluation", details),
            )
            receipt = tx.insert(receipt_input)
            proposed_input = deepcopy(proposal)
            proposed_input.pop("creation_receipt")
            proposed_input.update(_record_ref(SCOPE, seed_id, "proposal"))
            proposed_input["provenance"]["parents"] = [pin(receipt)]
            proposed_input["body"] = {key: deepcopy(details[key]) for key in (
                "subject", "candidate_set", "outcome", "candidates", "selected", "matching_rule",
                "evidence", "coverage", "assessed_as_of",
            )}
            proposed_input["body"].update(
                evaluator_receipt=entity_ref(receipt), evaluation=pin(receipt),
                uncertainty=details["evaluation"]["uncertainty"],
                qualification=details["evaluation"]["qualification"],
            )
            captured["proposal"] = tx.insert(proposed_input)
            created = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(created)})

        self.assertEqual(self.storage.execute(command, seed)["status"], "success")
        return captured["proposal"]

    def assert_invalid_proposal_acceptance(self, proposal, catalog, candidates, *, command_id):
        command = acceptance_command(command_id, self.authority, proposal, catalog, candidates, self.policy)
        try:
            prepared = self.service.prepare(command)
        except StorageError as error:
            self.assertEqual(error.code, "E_EVIDENCE_INVALID")
        else:
            self.assert_failure(self.service.accept(prepared), "E_EVIDENCE_INVALID")
        self.assertEqual(self.service.for_subject(self.subject), [])

    def test_effective_match_cannot_contradict_frozen_evaluation(self):
        target = self.matter("first")
        catalog, entries, _, _ = self.publish([target])
        original, _, _ = self.propose(catalog, entries)

        def contradict(details):
            details["evaluation"].update(outcome="no_match", selected=[])

        forged = self.seed_inconsistent_proposal(original, contradict, seed_id="false-effective-match")
        self.assert_invalid_proposal_acceptance(forged, catalog, [target], command_id="accept-false-effective")

    def test_self_consistent_proof_cannot_select_member_outside_catalog(self):
        target, outsider = self.matter("first"), self.matter("outside")
        catalog, entries, _, _ = self.publish([target])
        original, _, _ = self.propose(catalog, entries)

        def replace_candidate(details):
            candidate = {"candidate": pin(outsider), "basis": [pin(self.subject)]}
            details["candidates"] = [candidate]
            details["selected"] = [pin(outsider)]
            details["evaluation"]["selected"] = [pin(outsider)]

        forged = self.seed_inconsistent_proposal(original, replace_candidate, seed_id="catalog-outsider")
        self.assert_invalid_proposal_acceptance(forged, catalog, [outsider], command_id="accept-catalog-outsider")

    def test_history_validates_each_past_association_receipt_binding(self):
        from matter.associations import _membership, _membership_ref, _watches

        target = self.matter("history-target")
        catalog, entries, _, _ = self.publish([target])
        proposal, _, _ = self.propose(catalog, entries)
        accepted = self.service.accept(self.accept_command(proposal, catalog, [target]))
        self.assertEqual(accepted["status"], "success")
        current = self.storage.get(accepted["body"]["association"])
        original = deepcopy(current)

        # Introduce a structurally legal unsupported intermediate revision,
        # then restore a valid head through the trusted generic host port.
        for label, status in (("invalid-middle", "superseded"), ("valid-head", "active")):
            index = self.storage.get(_membership_ref(current))
            command = create_command(label, label + "-host-record", scope_id=SCOPE,
                                     expected_revisions=[pin(current), pin(index)])
            replacement = deepcopy(current)
            replacement["revision"] += 1
            replacement["body"]["status"] = status
            captured = {}

            def seed(tx):
                changed = tx.replace(replacement)
                captured["record"] = changed
                tx.put_projection(_membership_ref(changed), _membership(changed),
                                  watch_keys=_watches(*changed["body"]["members"]))
                created = tx.insert(tx.command["body"]["matter"])
                return tx.success("created", {"matter": pin(created)})

            self.assertEqual(self.storage.execute(command, seed)["status"], "success")
            current = captured["record"]

        self.assertEqual(self.storage.history(entity_ref(original))[1]["body"]["status"], "superseded")
        with self.assertRaises(StorageError) as error:
            self.service.history(entity_ref(original))
        self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")

    def test_retirement_preserves_frozen_proof_after_mutable_catalog_inputs_advance(self):
        from association_helpers import policy_for
        from matter.associations import AssociationService
        from matter_helpers import metadata_command

        target = self.matter("retirement-target")
        catalog, entries, _, _ = self.publish([target])
        proposal, _, _ = self.propose(catalog, entries)
        accepted = self.service.accept(self.accept_command(proposal, catalog, [target]))
        self.assertEqual(accepted["status"], "success")
        original = self.storage.get(accepted["body"]["association"])
        edit = metadata_command("advance-associated-target", target, {"title": "Revised catalog target"})
        revised = self.matters.update_metadata(self.matters.prepare(edit))
        self.assertEqual(revised["outcome"], "updated")
        current_target = self.storage.get(revised["body"]["matter"])
        self.assertEqual(self.service.history(entity_ref(original)), [original])

        _, rejection = self.decide(current_target, command_id="retire-stale-proof")
        revoked = self.storage.get(rejection["body"]["associations"][0])
        self.assertEqual(revoked["body"]["status"], "revoked")
        self.assertEqual(revoked["body"]["members"], original["body"]["members"])
        self.assertEqual(revoked["body"]["candidate_set"], pin(catalog))
        self.assertEqual(self.service.history(entity_ref(original)), [original, revoked])

        policy = policy_for(self.authority, allow_correction=True)
        service = AssociationService(self.storage, policy=policy)
        self.decide(current_target, command_id="release-stale-proof", decision="release",
                    previous=rejection["body"]["disposition"], service=service, policy=policy)
        self.assertEqual(service.for_subject(self.subject, status="active"), [])
        self.assertEqual(service.history(entity_ref(original)), [original, revoked])
