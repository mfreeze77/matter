"""Real process death, exact replay, and restoration of protected associations."""

from copy import deepcopy
import multiprocessing
import os

from matter.associations import AssociationService, MEMBERSHIP_NAMESPACE, association_ref
from matter.candidate_sets import read_candidate_set
from matter.storage import PROJECTION_TYPE, SQLiteStore, StorageError, entity_ref, pin

from association_helpers import (
    SCOPE, RELATION, AssociationTestCase, acceptance_command, decision_command,
    policy_for, proposal_command,
)


CRASH_EXIT_CODE = 78


def execute_association_operation(database, authority, command, stage):
    def fault(point):
        if point == stage:
            os._exit(CRASH_EXIT_CODE)

    with SQLiteStore(database, scope_id=SCOPE, fault_hook=fault) as storage:
        service = AssociationService(storage, policy=policy_for(authority))
        handlers = {
            "propose_association": service.propose,
            "accept_association": service.accept,
            "decide_association": service.decide,
        }
        result = handlers[command["operation"]](command)
    raise AssertionError(f"The requested interruption did not occur: {result!r}")


def must_not_execute(tx):
    raise AssertionError("A committed exact retry re-executed the association handler.")


def membership_reference(association):
    return {**entity_ref(association), "namespace": MEMBERSHIP_NAMESPACE, "record_type": PROJECTION_TYPE}


class AssociationAtomicityTests(AssociationTestCase):
    def crash(self, command, stage):
        context = multiprocessing.get_context("spawn")
        process = context.Process(target=execute_association_operation,
                                  args=(str(self.database), self.authority, command, stage))
        process.start()
        try:
            process.join(timeout=30)
            self.assertFalse(process.is_alive(), "The interrupted association process did not terminate.")
            self.assertEqual(process.exitcode, CRASH_EXIT_CODE)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)

    def assert_no_journal(self, command):
        with self.assertRaises(StorageError) as caught:
            self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(caught.exception.code, "E_NOT_FOUND")

    def catalog(self, suffix):
        target = self.matter(f"target:{suffix}")
        query = deepcopy(self.query)
        query["selector"]["value"]["atomicity_case"] = suffix
        catalog, entries, _, _ = self.publish([target], query=query, command_id=f"catalog:{suffix}")
        return target, query, catalog, entries

    def matched(self, suffix):
        target, query, catalog, entries = self.catalog(suffix)
        proposal, _, _ = self.propose(catalog, entries, query=query, command_id=f"proposal:{suffix}")
        return target, catalog, proposal

    def active(self, suffix):
        target, catalog, proposal = self.matched(suffix)
        command = self.accept_command(proposal, catalog, [target], command_id=f"accept:{suffix}")
        result = self.service.accept(command)
        self.assertEqual(result["outcome"], "accepted", result)
        association = self.storage.get(result["body"]["association"])
        return target, catalog, proposal, association

    def complete_proposal(self, result, *, storage=None):
        store = storage or self.storage
        self.assertEqual(result["outcome"], "proposal")
        proposal = store.get(result["body"]["proposal"])
        evaluation = store.get(proposal["body"]["evaluation"])
        self.assertEqual(evaluation["body"]["stage"], "evaluation")
        self.assertEqual(evaluation["body"]["details"]["value"]["outcome"], "matched")
        self.assertEqual(proposal["body"]["candidate_set"], result["body"]["candidate_set"])
        for record in (proposal, evaluation):
            self.assertEqual(store.receipt_for(pin(record))["id"], result["receipt"]["id"])
        return proposal

    def complete_association(self, result, *, storage=None, service=None):
        store, handler = storage or self.storage, service or self.service
        association = store.get(result["body"]["association"])
        decision = store.get(association["body"]["decision"])
        membership = store.get(membership_reference(association))
        self.assertEqual(decision["body"]["stage"], "authority")
        self.assertEqual(decision["body"]["details"]["value"]["decision"], "accept")
        self.assertEqual(association["body"]["status"], "active")
        self.assertEqual(membership["revision"], association["revision"])
        for record in (association, decision, membership):
            self.assertEqual(store.receipt_for(pin(record))["id"], result["receipt"]["id"])
        self.assertIn(association, handler.for_subject(self.subject, status="active"))
        return association

    def complete_block(self, result, prior, target, *, storage=None, service=None):
        store, handler = storage or self.storage, service or self.service
        disposition = store.get(result["body"]["disposition"])
        decision = store.get(result["body"]["decision"])
        association = store.get(entity_ref(prior))
        membership = store.get(membership_reference(association))
        self.assertEqual(disposition["value"]["value"]["status"], "blocked")
        self.assertEqual(disposition["value"]["value"]["decision"], pin(decision))
        self.assertEqual(association["body"]["decision"], pin(decision))
        self.assertEqual(association["body"]["status"], "revoked")
        self.assertEqual(association["revision"], prior["revision"] + 1)
        self.assertEqual(result["body"]["associations"], [pin(association)])
        self.assertEqual(membership["revision"], association["revision"])
        for record in (disposition, decision, association, membership):
            self.assertEqual(store.receipt_for(pin(record))["id"], result["receipt"]["id"])
        self.assertEqual(handler.history(entity_ref(prior)), [prior, association])
        self.assertEqual(handler.disposition(self.subject, target, RELATION), disposition)
        self.assertIn(association, handler.for_subject(self.subject, status="revoked"))
        self.assertNotIn(association, handler.for_subject(self.subject, status="active"))
        return disposition, association

    def test_proposal_and_evaluation_receipt_rollback_together_before_receipt_and_commit(self):
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                _, query, catalog, entries = self.catalog("proposal:" + stage)
                command = self.service.prepare(proposal_command(
                    f"interrupted-proposal:{stage}", self.authority, catalog, query, entries, self.subject))
                before = self.record_counts()
                self.crash(command, stage)
                self.assertEqual(self.record_counts(), before)
                self.assert_no_journal(command)
                result = self.service.propose(command)
                self.complete_proposal(result)
                self.assertEqual(self.storage.execute(command, must_not_execute), result)

    def test_acceptance_receipt_association_and_membership_rollback_together(self):
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                target, catalog, proposal = self.matched("acceptance:" + stage)
                command = self.accept_command(proposal, catalog, [target], command_id=f"interrupted-accept:{stage}")
                before = self.record_counts()
                previous_edges = self.service.for_subject(self.subject)
                reference = association_ref(SCOPE, self.subject, target, RELATION)
                self.crash(command, stage)
                self.assertEqual(self.record_counts(), before)
                self.assert_no_journal(command)
                with self.assertRaises(StorageError) as caught:
                    self.storage.get(reference)
                self.assertEqual(caught.exception.code, "E_NOT_FOUND")
                self.assertEqual(self.service.for_subject(self.subject), previous_edges)
                result = self.service.accept(command)
                self.complete_association(result)
                self.assertEqual(self.storage.execute(command, must_not_execute), result)

    def test_protection_and_revocation_rollback_with_decision_and_membership(self):
        for stage in ("before_receipt", "before_commit"):
            with self.subTest(stage=stage):
                target, _, _, prior = self.active("protection:" + stage)
                command = self.service.prepare(decision_command(
                    f"interrupted-protect:{stage}", self.authority, self.subject, target, self.policy,
                    decision="protect"))
                before = self.record_counts()
                membership = self.storage.get(membership_reference(prior))
                self.crash(command, stage)
                self.assertEqual(self.record_counts(), before)
                self.assertEqual(self.storage.get(entity_ref(prior)), prior)
                self.assertEqual(self.storage.get(membership_reference(prior)), membership)
                self.assertIsNone(self.service.disposition(self.subject, target, RELATION))
                self.assert_no_journal(command)
                result = self.service.decide(command)
                self.complete_block(result, prior, target)
                self.assertEqual(self.storage.execute(command, must_not_execute), result)

    def test_lost_acknowledgements_restart_and_restore_preserve_exact_results_and_block(self):
        target, query, catalog, entries = self.catalog("lost-ack")
        proposal_command_value = self.service.prepare(proposal_command(
            "lost-proposal", self.authority, catalog, query, entries, self.subject))
        self.crash(proposal_command_value, "after_commit")
        proposal_result = self.storage.command_receipt(proposal_command_value["idempotency_key"])["result"]
        proposal = self.complete_proposal(proposal_result)
        accept_command_value = self.accept_command(proposal, catalog, [target], command_id="lost-accept")
        self.crash(accept_command_value, "after_commit")
        accept_result = self.storage.command_receipt(accept_command_value["idempotency_key"])["result"]
        prior = self.complete_association(accept_result)
        protect_command = self.service.prepare(decision_command(
            "lost-protect", self.authority, self.subject, target, self.policy, decision="protect"))
        self.crash(protect_command, "after_commit")
        protect_result = self.storage.command_receipt(protect_command["idempotency_key"])["result"]
        disposition, revoked = self.complete_block(protect_result, prior, target)
        commands = ((proposal_command_value, proposal_result), (accept_command_value, accept_result),
                    (protect_command, protect_result))
        for command, result in commands:
            self.assertEqual(self.storage.execute(command, must_not_execute), result)
        backup = self.storage.backup_to(self.directory / "association-backup.sqlite")
        restored_path = self.directory / "association-restored.sqlite"
        for label, opener in (
            ("restart", lambda: SQLiteStore(self.database, scope_id=SCOPE)),
            ("restore", lambda: SQLiteStore.restore_from(backup, restored_path, scope_id=SCOPE)),
        ):
            with self.subTest(mode=label), opener() as store:
                service = AssociationService(store, policy=policy_for(self.authority))
                for command, result in commands:
                    self.assertEqual(store.execute(command, must_not_execute), result)
                self.complete_block(protect_result, prior, target, storage=store, service=service)
                with store.snapshot() as snapshot:
                    self.assertEqual(read_candidate_set(snapshot, SCOPE, pin(catalog)), catalog)
                self.assertEqual(service.disposition(self.subject, target, RELATION), disposition)
                self.assertEqual(service.for_subject(self.subject), [revoked])
                fresh = acceptance_command(f"replay-after-{label}", self.authority, proposal, catalog,
                                           [target], self.policy)
                with self.assertRaises(StorageError) as caught:
                    service.prepare(fresh)
                self.assertEqual(caught.exception.code, "E_ASSOCIATION_CONFLICT")
