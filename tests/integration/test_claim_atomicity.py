"""Process death, journal recovery, and restore across claim/citation writes."""

import multiprocessing
import os

from matter.citations import Utf8LineLocatorAdapter
from matter.claims import ClaimService, claim_index_ref
from matter.evidence_relations import EvidenceRelationService, relation_index_ref
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from claim_helpers import (SCOPE, ClaimTestCase, acceptance_command, claim_command,
                           relation_command)


CRASH_EXIT_CODE = 77


def execute_claim_operation(database, payload_directory, command, stage):
    def fault(point):
        if point == stage:
            os._exit(CRASH_EXIT_CODE)

    with SQLiteStore(database, scope_id=SCOPE, fault_hook=fault) as store:
        if command["operation"] == "append_claim":
            ClaimService(store).append(command)
        else:
            adapter = Utf8LineLocatorAdapter(FilePayloadStore(payload_directory, scope_id=SCOPE))
            service = EvidenceRelationService(store, locator_adapter=adapter)
            if command["operation"] == "relate_evidence":
                service.relate(command)
            else:
                service.revise_acceptance(command)
    raise AssertionError("The requested interruption did not occur.")


def must_not_execute(tx):
    raise AssertionError("An exact committed retry re-executed its handler.")


class ClaimCitationAtomicityTests(ClaimTestCase):
    def crash(self, command, stage):
        context = multiprocessing.get_context("spawn")
        process = context.Process(target=execute_claim_operation, args=(
            str(self.database), str(self.payload_directory), command, stage,
        ))
        process.start()
        try:
            process.join(timeout=30)
            self.assertFalse(process.is_alive(), "The interrupted citation process did not terminate.")
            self.assertEqual(process.exitcode, CRASH_EXIT_CODE)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)

    def assert_no_journal(self, command):
        with self.assertRaises(StorageError) as error:
            self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def test_claim_and_index_roll_back_together_before_receipt_and_commit(self):
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                command = self.claims.prepare(claim_command(
                    f"crash-claim-{stage}", f"claim-{stage}", self.subject, self.source,
                ))
                before = self.record_counts()
                self.crash(command, stage)
                self.assertEqual(self.record_counts(), before)
                proposed = command["body"]["claim"]
                self.assert_missing(entity_ref(proposed))
                self.assert_missing(claim_index_ref(SCOPE, proposed))
                self.assert_no_journal(command)
                result = self.claims.append(command)
                self.assertEqual(result["outcome"], "appended", result)
                stored = self.storage.get(result["body"]["claim"])
                index = self.storage.get(claim_index_ref(SCOPE, stored))
                self.assertEqual(stored["creation_receipt"], index["creation_receipt"])
                self.assertEqual(self.storage.execute(command, must_not_execute), result)

    def test_committed_claim_correction_and_notice_survive_lost_acknowledgement(self):
        original, _, _ = self.append()
        command = self.claims.prepare(claim_command(
            "crash-correction", "corrected-claim", self.subject, self.source,
            value="The forecast was withdrawn.", version="withdrawn-2", supersedes=[original],
        ))
        self.crash(command, "after_commit")
        result = self.storage.command_receipt(command["idempotency_key"])["result"]
        current = self.storage.get(result["body"]["claim"])
        self.assertEqual(self.claims.revisions(pin(original)), [original, current])
        self.assertEqual(self.claims.heads(pin(original)), [current])
        self.assertEqual(result["body"]["changes"], [{
            "cause": "evidence_correction", "before": [pin(original)], "after": [pin(current)],
        }])
        self.assertEqual(self.storage.get(pin(original)), original)
        self.assertEqual(self.storage.get(entity_ref(self.subject)), self.subject)
        self.assertEqual(self.storage.execute(command, must_not_execute), result)

    def test_relation_validation_receipt_and_index_roll_back_before_receipt_and_commit(self):
        claim, _, _ = self.append()
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                command = self.relations.prepare(relation_command(
                    f"crash-relation-{stage}", f"relation-{stage}", claim, self.source,
                ))
                before = self.record_counts()
                self.crash(command, stage)
                self.assertEqual(self.record_counts(), before)
                proposed = command["body"]["relation"]
                self.assert_missing(entity_ref(proposed))
                self.assert_missing(relation_index_ref(SCOPE, proposed))
                self.assert_no_journal(command)
                result = self.relations.relate(command)
                self.assertEqual(result["outcome"], "appended", result)
                self.assert_complete_relation(result)

    def assert_complete_relation(self, result):
        relation = self.storage.get(result["body"]["relation"])
        validation = self.storage.get(result["body"]["locator_validation"])
        index = self.storage.get(relation_index_ref(SCOPE, relation))
        self.assertEqual(validation["body"]["stage"], "evaluation")
        self.assertEqual(validation["body"]["details"]["value"]["result"]["kind"], "exact_passage")
        self.assertEqual(relation["body"]["locator_validation"], pin(validation))
        for record in (relation, validation, index):
            self.assertEqual(self.storage.receipt_for(pin(record))["id"], result["receipt"]["id"])
        self.assertIn(relation, self.relations.for_claim(relation["body"]["claim"]))
        return relation

    def test_relation_death_after_commit_retains_frozen_validation_and_exact_result(self):
        claim, _, _ = self.append()
        command = self.relations.prepare(relation_command("lost-relation", "lost-relation", claim, self.source))
        self.crash(command, "after_commit")
        result = self.storage.command_receipt(command["idempotency_key"])["result"]
        relation = self.assert_complete_relation(result)
        self.assertEqual(self.relations.history(entity_ref(relation)), [relation])
        self.assertEqual(self.storage.execute(command, must_not_execute), result)
        self.assertEqual(self.relations.relate(command), result)

    def test_acceptance_revision_and_index_roll_back_together(self):
        claim, _, _ = self.append()
        relation, _, _ = self.relate(claim)
        command = self.relations.prepare(acceptance_command("withdraw-citation", relation, "rejected"))
        before = self.record_counts()
        index = self.storage.get(relation_index_ref(SCOPE, relation))
        self.crash(command, "before_commit")
        self.assertEqual(self.record_counts(), before)
        self.assertEqual(self.storage.get(entity_ref(relation)), relation)
        self.assertEqual(self.storage.get(relation_index_ref(SCOPE, relation)), index)
        self.assert_no_journal(command)
        result = self.relations.revise_acceptance(command)
        self.assertEqual(result["outcome"], "updated", result)
        current = self.storage.get(result["body"]["relation"])
        self.assertEqual(self.relations.history(entity_ref(relation)), [relation, current])
        self.assertEqual(current["body"]["locator_validation"], relation["body"]["locator_validation"])
        for record in (current, self.storage.get(relation_index_ref(SCOPE, current))):
            self.assertEqual(self.storage.receipt_for(pin(record))["id"], result["receipt"]["id"])

    def test_restart_restore_preserve_claim_branches_citation_history_and_replay(self):
        claim, claim_command_saved, claim_result = self.append()
        correction, _, _ = self.append("claim-corrected", value="Withdrawal", version="2", supersedes=[claim])
        branch, _, _ = self.append("claim-branch", value="Competing correction", version="branch-2", supersedes=[claim])
        relation, relation_command_saved, relation_result = self.relate(claim)
        command = self.relations.prepare(acceptance_command("retire-relation", relation, "superseded"))
        updated = self.relations.revise_acceptance(command)
        self.assertEqual(updated["outcome"], "updated", updated)
        lineage = self.claims.revisions(pin(claim))
        tips = self.claims.heads(pin(claim))
        self.assertEqual({item["id"] for item in tips}, {correction["id"], branch["id"]})
        history = self.relations.history(entity_ref(relation))
        backup = self.storage.backup_to(self.directory / "backup.sqlite")
        for mode in ("restart", "restore"):
            with self.subTest(mode=mode):
                store = (SQLiteStore(self.database, scope_id=SCOPE) if mode == "restart" else
                         SQLiteStore.restore_from(backup, self.directory / "restored.sqlite", scope_id=SCOPE))
                with store:
                    claims = ClaimService(store)
                    relations = EvidenceRelationService(store, locator_adapter=self.adapter)
                    self.assertEqual(claims.revisions(pin(claim)), lineage)
                    self.assertEqual(claims.heads(pin(claim)), tips)
                    self.assertEqual(claims.for_subject(entity_ref(self.subject)), self.claims.for_subject(entity_ref(self.subject)))
                    self.assertEqual(relations.history(entity_ref(relation)), history)
                    self.assertEqual(claims.append(claim_command_saved), claim_result)
                    self.assertEqual(relations.relate(relation_command_saved), relation_result)
                    self.assertEqual(relations.revise_acceptance(command), updated)
                    self.assertEqual(store.get(entity_ref(self.subject)), self.subject)
