"""Independent immutable identity-decision and historical-view proof checks."""

from copy import deepcopy

from association_helpers import SCOPE
from identity_helpers import IdentityTestCase
from integration.helpers import create_command
from matter.citations import _domain
from matter.identity_corrections import (
    IdentityCorrectionService, _decision_ref, _release_parents, _unique, read_decision, read_release,
)
from matter.storage import PROJECTION_TYPE, StorageError, entity_ref, pin


class IdentityDecisionTests(IdentityTestCase):
    def copied_decision(self, original_ref, identity, mutate=None):
        """Use the trusted generic port to model imported inconsistent proof.

        This deliberately bypasses the identity service's writer. A valid
        storage envelope alone must not turn unrelated historical snapshots
        into the writes made by this new identity decision.
        """
        original = self.storage.get(original_ref)
        proposed = deepcopy(original)
        proposed.pop("creation_receipt")
        detail = deepcopy(original["body"]["details"]["value"])
        if mutate is not None:
            mutate(detail)
        proposed.update(_decision_ref(SCOPE, identity, detail["kind"]))
        parents = _unique([*detail["basis"], *([detail["previous"]] if detail["previous"] is not None else [])])
        proposed["provenance"]["parents"] = parents
        proposed["body"].update(operation_id=identity, outcome="matter:identity_" + detail["kind"],
                                evidence=parents, details=_domain("identity-decision", detail))
        captured = {}
        command = create_command(identity, identity + "-host-record", scope_id=SCOPE)

        def seed(tx):
            captured["receipt"] = tx.insert(proposed)
            created = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(created)})

        result = self.storage.execute(command, seed)
        self.assertEqual(result["status"], "success", result)
        return captured["receipt"]

    def assert_invalid_decision(self, receipt):
        with self.storage.snapshot() as snapshot:
            with self.assertRaises(StorageError) as error:
                read_decision(snapshot, SCOPE, pin(receipt))
            self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")

    def copied_release(self, original_ref, identity, mutate=None):
        original = self.storage.get(original_ref)
        proposed = deepcopy(original)
        proposed.pop("creation_receipt")
        detail = deepcopy(original["body"]["details"]["value"])
        if mutate is not None:
            mutate(detail)
        proposed.update(_decision_ref(SCOPE, identity, "release"))
        parents = _release_parents(detail)
        proposed["provenance"]["parents"] = parents
        proposed["body"].update(operation_id=identity, evidence=parents,
                                details=_domain("identity-release", detail))
        captured = {}

        def seed(tx):
            captured["receipt"] = tx.insert(proposed)
            created = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(created)})

        result = self.storage.execute(create_command(identity, identity + "-host-record", scope_id=SCOPE), seed)
        self.assertEqual(result["status"], "success", result)
        return captured["receipt"]

    def protected_pair(self):
        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        _, corrected = self.correct(merged["body"]["merge_receipt"])
        correction = self.storage.get(corrected["body"]["correction_receipt"])
        separation = self.storage.get(correction["body"]["details"]["value"]["protections"][0])
        return a, b, merged, corrected, separation

    def test_historical_view_cannot_claim_another_receipts_group_writes(self):
        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        actual = self.identities.historical_view(merged["body"]["merge_receipt"])
        copied = self.copied_decision(merged["body"]["merge_receipt"], "copied-historical-merge")
        with self.assertRaises(StorageError) as error:
            self.identities.historical_view(pin(copied))
        self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")
        self.assertEqual(self.identities.historical_view(merged["body"]["merge_receipt"]), actual)

    def test_correction_proof_requires_all_cross_partition_protections(self):
        a, b, c = self.matter("a"), self.matter("b"), self.matter("c")
        _, merged = self.merge(a, [b, c])
        _, corrected = self.correct(merged["body"]["merge_receipt"], kind="split",
                                    partitions=[[a, b], [c]])
        receipt = self.storage.get(corrected["body"]["correction_receipt"])
        self.assertEqual(len(receipt["body"]["details"]["value"]["protections"]), 2)
        for label, keep in (("missing-all-protections", 0), ("missing-one-protection", 1)):
            copied = self.copied_decision(pin(receipt), label,
                                         lambda detail: detail.update(protections=detail["protections"][:keep]))
            self.assert_invalid_decision(copied)

    def test_correction_previous_must_be_its_governing_merge_proof(self):
        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        _, corrected = self.correct(merged["body"]["merge_receipt"])
        copied = self.copied_decision(corrected["body"]["correction_receipt"], "unrelated-previous-authority",
                                     lambda detail: detail.update(previous=pin(self.authority)))
        self.assert_invalid_decision(copied)

    def test_correction_allows_later_metadata_without_rewriting_earlier_view(self):
        from matter_helpers import metadata_command
        from matter.storage import entity_ref

        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        original = self.identities.historical_view(merged["body"]["merge_receipt"])
        current = self.current(a)
        update = metadata_command("edit-survivor-after-merge", current, {"title": "Later survivor metadata"})
        changed = self.matters.update_metadata(self.matters.prepare(update))
        self.assertEqual(changed["outcome"], "updated")
        edited = self.storage.get(changed["body"]["matter"])
        _, corrected = self.correct(merged["body"]["merge_receipt"])
        self.assertEqual(self.current(a)["body"], edited["body"])
        self.assertEqual(self.identities.resolve(entity_ref(b))["id"], b["id"])
        correction = self.identities.historical_view(corrected["body"]["correction_receipt"])
        self.assertIn(pin(edited), correction["before"][0]["members"])
        self.assertEqual(self.identities.historical_view(merged["body"]["merge_receipt"]), original)

    def test_correction_receipt_chain_is_refused_before_recursive_ancestry_reads(self):
        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        _, corrected = self.correct(merged["body"]["merge_receipt"])
        first = self.copied_decision(corrected["body"]["correction_receipt"], "correction-chain-first",
                                     lambda detail: detail.update(previous=corrected["body"]["correction_receipt"]))
        second = self.copied_decision(corrected["body"]["correction_receipt"], "correction-chain-second",
                                      lambda detail: detail.update(previous=pin(first)))
        with self.storage.snapshot() as snapshot:
            class BoundedPreviousView:
                def get(self, reference):
                    if reference == corrected["body"]["correction_receipt"]:
                        raise AssertionError("A correction cannot recursively follow a correction predecessor.")
                    return snapshot.get(reference)

            with self.assertRaises(StorageError) as error:
                read_decision(BoundedPreviousView(), SCOPE, pin(second))
            self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")

    def test_release_requires_its_exact_protection_to_be_written_by_the_cited_correction(self):
        _, _, merged, corrected, separation = self.protected_pair()
        _, released = self.release([separation])
        unrelated = self.copied_release(released["body"]["release_receipt"], "release-wrong-producer",
            lambda detail: detail["separations"][0].update(protected_by=merged["body"]["merge_receipt"]))
        with self.storage.snapshot() as snapshot:
            with self.assertRaises(StorageError) as error:
                read_release(snapshot, SCOPE, pin(unrelated))
            self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")

        # Merely listing a protection revision does not prove this correction
        # wrote it. The real local change still records protection revision 1.
        alleged = self.copied_decision(corrected["body"]["correction_receipt"], "unwritten-protection",
            lambda detail: detail["protections"][0].update(revision=3))

        def change_to_unwritten(detail):
            entry = detail["separations"][0]
            entry["before"]["revision"] = 3
            entry["after"]["revision"] = 4
            entry["protected_by"] = pin(alleged)
            detail["changes"] = [{"cause": "disposition_change", "before": [entry["before"]],
                                  "after": [entry["after"]]}]

        forged = self.copied_release(released["body"]["release_receipt"], "release-unwritten-protection",
                                     change_to_unwritten)
        with self.storage.snapshot() as snapshot:
            with self.assertRaises(StorageError) as error:
                read_release(snapshot, SCOPE, pin(forged))
            self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")

    def test_separation_history_checks_actual_commit_ownership_of_each_release(self):
        from contextlib import contextmanager

        _, _, _, _, separation = self.protected_pair()
        _, released = self.release([separation])
        copied = self.copied_release(released["body"]["release_receipt"], "release-other-commit")
        actual = self.storage.get(released["body"]["separations"][0])
        substituted = deepcopy(actual)
        substituted["value"]["value"]["decision"] = pin(copied)
        storage = self.storage

        class SubstitutedHistoryStorage:
            scope_id = SCOPE

            @contextmanager
            def snapshot(self):
                with storage.snapshot() as snapshot:
                    class SubstitutedView:
                        def __getattr__(self, name):
                            return getattr(snapshot, name)

                        def lookup_identity(self, reference):
                            current = snapshot.lookup_identity(reference)
                            return substituted if current is not None and entity_ref(current) == entity_ref(actual) else current

                        def history(self, reference):
                            return [substituted if pin(item) == pin(actual) else item for item in snapshot.history(reference)]

                    yield SubstitutedView()

        service = IdentityCorrectionService(SubstitutedHistoryStorage(), policy=self.merge_policy)
        with self.assertRaises(StorageError) as error:
            service.separation_history(entity_ref(separation))
        self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")
        self.assertEqual([item["revision"] for item in self.identities.separation_history(entity_ref(separation))], [1, 2])

    def test_repeated_reprotection_proof_does_not_read_old_mutable_separation_ancestry(self):
        a, b, _, _, separation = self.protected_pair()
        _, first_release = self.release([separation])
        _, second_merge = self.merge(self.current(a), [self.current(b)], command_id="second-merge")
        _, second_correction = self.correct(second_merge["body"]["merge_receipt"], command_id="second-correction")
        correction = self.storage.get(second_correction["body"]["correction_receipt"])
        protected = self.storage.get(correction["body"]["details"]["value"]["protections"][0])
        self.assertEqual(protected["revision"], 3)
        _, second_release = self.release([protected], command_id="second-release")
        with self.storage.snapshot() as snapshot:
            class ImmutableProofView:
                def get(self, reference):
                    if reference["record_type"] == PROJECTION_TYPE or reference == first_release["body"]["release_receipt"]:
                        raise AssertionError("Current release proof must not recurse through old mutable separation history.")
                    return snapshot.get(reference)

            verified = read_release(ImmutableProofView(), SCOPE, second_release["body"]["release_receipt"])
            self.assertEqual(pin(verified), second_release["body"]["release_receipt"])
        history = self.identities.separation_history(entity_ref(separation))
        self.assertEqual([item["revision"] for item in history], [1, 2, 3, 4])
        self.assertEqual([item["value"]["value"]["status"] for item in history],
                         ["protected", "released", "protected", "released"])
