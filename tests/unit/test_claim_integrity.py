"""Exact snapshot references and historical citation proof during acceptance edits."""

from copy import deepcopy

from matter.canonical import canonical_bytes, canonical_digest
from matter.evidence_relations import EvidenceRelationService
from matter.storage import entity_ref, pin
from matter.storage.base import snapshot_digest

from claim_helpers import ClaimTestCase, acceptance_command, relation_command
from matter_helpers import metadata_command


class MutableContextAdapter:
    """Synthetic host adapter declaring a checked mutable context snapshot.

    The included adapter validates the actual source bytes; this test adapter
    adds one explicit host-owned dependency to exercise the general port seam.
    """

    def __init__(self, adapter, dependency):
        self.adapter = adapter
        self.dependency = deepcopy(dependency)
        self.scope_id = adapter.scope_id

    @property
    def reference(self):
        return {
            "namespace": "example", "id": "mutable-context-citation", "version": "1.0",
            "digest": canonical_digest({"underlying": self.adapter.reference}, "example.citation-adapter.v1"),
        }

    def validate(self, evidence, locator, *, quotation=None, checked_at=None):
        value = self.adapter.validate(evidence, locator, quotation=quotation, checked_at=checked_at)
        value["value"]["adapter"] = self.reference
        value["value"]["dependencies"] = sorted(
            [pin(evidence), deepcopy(self.dependency)], key=canonical_bytes,
        )
        return value


class ClaimIntegrityTests(ClaimTestCase):
    def _digest_pin(self, record):
        return {**entity_ref(record), "digest": snapshot_digest(record)}

    def _advance_subject(self):
        command = metadata_command("advance-context", self.subject, {"title": "Revised host context"})
        result = self.matters.update_metadata(self.matters.prepare(command))
        self.assertEqual(result["outcome"], "updated", result)
        return self.storage.get(result["body"]["matter"])

    def _context_service(self):
        dependency = self._digest_pin(self.subject)
        adapter = MutableContextAdapter(self.adapter, dependency)
        return EvidenceRelationService(self.storage, locator_adapter=adapter), dependency

    def test_acceptance_can_use_the_exact_current_snapshot_digest(self):
        claim, _, _ = self.append()
        original, _, _ = self.relate(claim)
        command = acceptance_command("acceptance-by-digest", original, "rejected")
        reference = self._digest_pin(original)
        command["body"]["relation"] = reference
        command["expected_revisions"] = [deepcopy(reference)]
        prepared = self.relations.prepare(command)
        self.assertEqual(prepared["body"]["relation"], reference)
        self.assertIn(reference, prepared["expected_revisions"])
        result = self.relations.revise_acceptance(prepared)
        self.assertEqual(result["outcome"], "updated", result)
        current = self.storage.get(result["body"]["relation"])
        self.assertEqual(current["revision"], original["revision"] + 1)
        self.assertEqual(current["body"]["acceptance"]["status"], "rejected")
        self.assertEqual(result["body"]["previous"], pin(original))
        self.assertEqual(self.relations.history(entity_ref(original)), [original, current])

    def test_prepared_digest_pin_still_refuses_an_actual_stale_relation(self):
        claim, _, _ = self.append()
        original, _, _ = self.relate(claim)
        command = acceptance_command("stale-digest", original, "superseded")
        command["body"]["relation"] = self._digest_pin(original)
        prepared = self.relations.prepare(command)
        winner = acceptance_command("winning-revision", original, "rejected")
        accepted = self.relations.revise_acceptance(self.relations.prepare(winner))
        self.assertEqual(accepted["outcome"], "updated")
        result = self.relations.revise_acceptance(prepared)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], result)
        self.assertEqual(self.relations.revise_acceptance(prepared), result)
        self.assertEqual(self.storage.get(entity_ref(original))["body"]["acceptance"]["status"], "rejected")

    def test_mutable_digest_dependency_and_parent_are_historical_proof_after_advancement(self):
        claim, _, _ = self.append()
        service, dependency = self._context_service()
        command = relation_command("context-bound-relation", "context-bound-relation", claim, self.source)
        command["body"]["relation"]["provenance"]["parents"] = [deepcopy(dependency)]
        command["expected_revisions"] = [deepcopy(dependency)]
        prepared = service.prepare(command)
        self.assertIn(dependency, prepared["body"]["validation"]["value"]["dependencies"])
        self.assertIn(dependency, prepared["expected_revisions"])
        result = service.relate(prepared)
        self.assertEqual(result["outcome"], "appended", result)
        original = self.storage.get(result["body"]["relation"])
        receipt_before = self.storage.get(result["body"]["locator_validation"])
        advanced = self._advance_subject()

        # An immutable receipt preserves exactly what the adapter checked at
        # creation. Editing disposition does not rerun its historical inputs.
        self.assertEqual(service.history(entity_ref(original)), [original])
        self.assertEqual(service.for_claim(pin(claim)), [original])
        for label, status in (("withdraw-context", "rejected"), ("retire-context", "superseded")):
            current = self.storage.get(entity_ref(original))
            edit = service.prepare(acceptance_command(label, current, status))
            self.assertNotIn(dependency, edit["expected_revisions"])
            update = service.revise_acceptance(edit)
            self.assertEqual(update["outcome"], "updated", update)

        duplicate = deepcopy(command)
        duplicate.update(command_id="duplicate-after-context-change",
                         idempotency_key="key:duplicate-after-context-change", expected_revisions=[])
        duplicate_result = service.relate(service.prepare(duplicate))
        self.assertEqual(duplicate_result["outcome"], "duplicate", duplicate_result)
        current = self.storage.get(entity_ref(original))
        self.assertEqual(current["body"]["acceptance"]["status"], "superseded")
        self.assertEqual(current["provenance"], original["provenance"])
        self.assertEqual(current["body"]["locator_validation"], original["body"]["locator_validation"])
        self.assertEqual(self.storage.get(result["body"]["locator_validation"]), receipt_before)
        self.assertEqual(self.storage.get(entity_ref(self.subject)), advanced)
        self.assertEqual(len(service.history(entity_ref(original))), 3)

    def test_new_relation_cannot_commit_a_frozen_mutable_dependency_after_it_changes(self):
        claim, _, _ = self.append()
        service, dependency = self._context_service()
        command = relation_command("stale-new-citation", "stale-new-citation", claim, self.source)
        prepared = service.prepare(command)
        self.assertIn(dependency, prepared["body"]["validation"]["value"]["dependencies"])
        self._advance_subject()
        result = service.relate(prepared)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(service.for_claim(pin(claim)), [])
        self.assertNotIn("evidence_relation", self.record_counts())
        self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], result)
