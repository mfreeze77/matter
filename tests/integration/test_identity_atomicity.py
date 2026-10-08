"""Process-interruption boundaries for complete identity decisions, not power loss."""

from matter.identity_dependencies import require_current_identity_dependency
from matter.storage import StorageError, entity_ref, pin

from association_helpers import SCOPE
from identity_helpers import IdentityTestCase, merge_command


def must_not_execute(tx):
    raise AssertionError("A committed identity retry re-executed its handler.")


class IdentityAtomicityTests(IdentityTestCase):
    def assert_committed_view(self, result, originals):
        self.assertEqual(result.get("outcome"), "committed", result)
        receipt = result["body"].get("merge_receipt", result["body"].get("correction_receipt"))
        self.assertIsNotNone(receipt)
        decision = self.storage.get(receipt)
        self.assertEqual(decision["creation_receipt"], result["receipt"])
        for original in originals:
            current = self.current(original)
            self.assertEqual(self.storage.receipt_for(pin(current))["id"], result["receipt"]["id"])
            for index in self.identities.view(current)["indexes"]:
                self.assertEqual(self.storage.receipt_for(index)["id"], result["receipt"]["id"])
        return decision

    def test_merge_process_death_rolls_back_complete_children_redirects_and_receipts(self):
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                a, b = self.matter(f"a-{stage}"), self.matter(f"b-{stage}")
                attachment = self.attach(b, label=stage)
                prepared = self.prepare_merge(a, [b], command_id=f"interrupted-merge-{stage}")
                before = [self.identities.view(item) for item in (a, b)]
                counts = self.record_counts()
                self.crash(prepared, stage)
                self.assertEqual(self.record_counts(), counts)
                self.assertEqual([self.identities.view(item) for item in (a, b)], before)
                self.assertEqual([self.current(item) for item in (a, b)], [a, b])
                self.assertEqual(self.storage.get(pin(attachment)), attachment)
                self.assert_no_journal(prepared)
                result = self.identities.merge(prepared)
                self.assert_committed_view(result, [a, b])
                self.assertEqual(self.identities.resolve(b)["id"], a["id"])

    def test_merge_after_commit_process_death_recovers_complete_view_and_exact_result(self):
        a, b = self.matter("a"), self.matter("b")
        attachment = self.attach(b, label="after-commit")
        prepared = self.prepare_merge(a, [b])
        self.crash(prepared, "after_commit")
        journal = self.storage.command_receipt(prepared["idempotency_key"])
        self.assert_committed_view(journal["result"], [a, b])
        self.assertEqual(self.identities.resolve(a), self.identities.resolve(b))
        self.assertEqual(self.member_ids(a), {"a", "b"})
        self.assertEqual(self.storage.get(pin(attachment)), attachment)
        self.assertEqual(self.storage.execute(prepared, must_not_execute), journal["result"])
        self.assertEqual(self.identities.merge(prepared), journal["result"])

    def test_correction_process_death_keeps_merged_view_and_registered_dependency_current(self):
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                a, b = self.matter(f"a-{stage}"), self.matter(f"b-{stage}")
                _, merged = self.merge(a, [b], command_id=f"merge-{stage}")
                assessment, registration = self.registered_assessment(
                    a, label=f"assessment-{stage}", merge_receipt=merged["body"]["merge_receipt"])
                prepared = self.prepare_correction(merged["body"]["merge_receipt"], command_id=f"correct-{stage}")
                before = [self.identities.view(item) for item in (a, b)]
                counts = self.record_counts()
                self.crash(prepared, stage)
                self.assertEqual(self.record_counts(), counts)
                self.assertEqual([self.identities.view(item) for item in (a, b)], before)
                self.assertEqual(self.storage.get(entity_ref(registration)), registration)
                self.assertEqual(self.storage.get(pin(assessment)), assessment)
                self.assert_no_journal(prepared)
                with self.storage.snapshot() as snapshot:
                    self.assertEqual(require_current_identity_dependency(snapshot, SCOPE, pin(registration)), registration)
                corrected = self.identities.correct(prepared)
                self.assert_committed_view(corrected, [a, b])
                self.assertEqual(self.storage.get(entity_ref(registration))["value"]["value"]["status"], "invalidated")

    def test_correction_after_commit_recovers_partitions_protection_and_invalidation_together(self):
        a, b = self.matter("a"), self.matter("b")
        _, merged = self.merge(a, [b])
        assessment, registration = self.registered_assessment(a, merge_receipt=merged["body"]["merge_receipt"])
        prepared = self.prepare_correction(merged["body"]["merge_receipt"])
        self.crash(prepared, "after_commit")
        journal = self.storage.command_receipt(prepared["idempotency_key"])
        self.assert_committed_view(journal["result"], [a, b])
        self.assertEqual(self.identities.resolve(a)["id"], "a")
        self.assertEqual(self.identities.resolve(b)["id"], "b")
        invalidated = self.storage.get(entity_ref(registration))
        self.assertEqual(invalidated["value"]["value"]["status"], "invalidated")
        self.assertEqual(self.storage.receipt_for(pin(invalidated))["id"], journal["result"]["receipt"]["id"])
        self.assertEqual(self.storage.get(pin(assessment)), assessment)
        with self.storage.snapshot() as snapshot:
            with self.assertRaises(StorageError) as error:
                require_current_identity_dependency(snapshot, SCOPE, entity_ref(registration))
            self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        fresh = merge_command("forbidden-after-recovery", self.authority, self.merge_policy,
                              self.current(a), [self.current(b)], [self.subject])
        self.assert_refused(self.identities.prepare, self.identities.merge, fresh, "E_MERGE_CONFLICT")
        self.assertEqual(self.storage.execute(prepared, must_not_execute), journal["result"])
        self.assertEqual(self.identities.correct(prepared), journal["result"])
