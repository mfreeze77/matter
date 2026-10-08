"""Synthetic identity corrections over real matters, claims and attachments."""

from copy import deepcopy
import multiprocessing
import os

from matter.claims import ClaimService
from matter.evidence_relations import EvidenceRelationService
from matter.citations import Utf8LineLocatorAdapter
from matter.identity_corrections import IdentityCorrectionService, MergePolicy
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from association_helpers import (
    ACTOR, RELATION, SCOPE, AssociationTestCase, as_pin, decision_command, envelope,
)
from claim_helpers import claim_command, relation_command
from observation_helpers import known_time


CRASH_EXIT_CODE = 79


def merge_policy(authority, *, allow_correction=True):
    return MergePolicy(SCOPE, actors=[ACTOR], authorities=[pin(authority)],
                       allow_correction=allow_correction)


def merge_command(command_id, authority, policy, survivor, merged, basis):
    return envelope(command_id, "merge_matters", {
        "survivor": as_pin(survivor), "merged": [as_pin(item) for item in merged],
        "equivalence_basis": [as_pin(item) for item in basis],
        "merge_policy": policy.reference, "as_of": known_time(),
    }, authority)


def correction_command(command_id, authority, merge_receipt, partitions, basis, *, kind="undo"):
    return envelope(command_id, "correct_merge", {
        "merge_receipt": as_pin(merge_receipt), "correction_kind": kind,
        "partitions": deepcopy(partitions), "basis": [as_pin(item) for item in basis],
        "as_of": known_time(),
    }, authority)


def release_command(command_id, authority, policy, separations, basis):
    return envelope(command_id, "release_identity_separations", {
        "separations": [as_pin(item) for item in separations],
        "basis": [as_pin(item) for item in basis],
        "reason": "Explicit correction of an earlier mistaken separation.",
        "merge_policy": policy.reference, "as_of": known_time(),
    }, authority)


def identity_handler(service, operation):
    method = {"merge_matters": "merge", "correct_merge": "correct",
              "release_identity_separations": "release_separations"}[operation]
    return getattr(service, method)


def identity_worker(database, authority, command, barrier, output):
    try:
        with SQLiteStore(database, scope_id=SCOPE) as storage:
            service = IdentityCorrectionService(storage, policy=merge_policy(authority))
            barrier.wait(timeout=25)
            handler = identity_handler(service, command["operation"])
            result = handler(command)
        output.put({"command_id": command["command_id"], "result": result})
    except Exception as error:
        output.put({"worker_error": type(error).__name__, "detail": str(error)})


def interrupted_identity(database, authority, command, stage):
    def fault(point):
        if point == stage:
            os._exit(CRASH_EXIT_CODE)
    with SQLiteStore(database, scope_id=SCOPE, fault_hook=fault) as storage:
        service = IdentityCorrectionService(storage, policy=merge_policy(authority))
        handler = identity_handler(service, command["operation"])
        result = handler(command)
    raise AssertionError(f"The requested interruption did not occur: {result!r}")


def competing_identity_results(test, database, authority, commands):
    context = multiprocessing.get_context("spawn")
    barrier, output = context.Barrier(len(commands)), context.Queue()
    processes = [context.Process(target=identity_worker,
        args=(str(database), authority, command, barrier, output)) for command in commands]
    started = []
    try:
        for process in processes:
            process.start()
            started.append(process)
        messages = [output.get(timeout=35) for _ in started]
        for process in started:
            process.join(timeout=35)
            test.assertFalse(process.is_alive(), "Identity worker did not terminate.")
            test.assertEqual(process.exitcode, 0)
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
    test.assertTrue(all("result" in item for item in messages), messages)
    return {item["command_id"]: item["result"] for item in messages}


class IdentityTestCase(AssociationTestCase):
    def setUp(self):
        super().setUp()
        self.merge_policy = merge_policy(self.authority)
        self.identities = IdentityCorrectionService(self.storage, policy=self.merge_policy)
        self.claims = ClaimService(self.storage)
        self.evidence = EvidenceRelationService(self.storage,
            locator_adapter=Utf8LineLocatorAdapter(self.payloads))

    def current(self, matter):
        return self.storage.get(entity_ref(matter))

    def prepare_merge(self, survivor, merged, *, command_id="merge"):
        return self.identities.prepare(merge_command(command_id, self.authority, self.merge_policy,
                                                    survivor, merged, [self.subject]))

    def merge(self, survivor, merged, *, command_id="merge"):
        command = self.prepare_merge(survivor, merged, command_id=command_id)
        result = self.identities.merge(command)
        self.assertEqual(result.get("outcome"), "committed", result)
        return command, result

    def prepare_correction(self, receipt, *, command_id="correct", partitions=None, kind="undo"):
        planned = self.identities.plan_correction(receipt, partitions=partitions, correction_kind=kind)
        command = correction_command(command_id, self.authority, receipt, planned, [self.subject], kind=kind)
        return self.identities.prepare(command)

    def correct(self, receipt, *, command_id="correct", partitions=None, kind="undo"):
        command = self.prepare_correction(receipt, command_id=command_id, partitions=partitions, kind=kind)
        result = self.identities.correct(command)
        self.assertEqual(result.get("outcome"), "committed", result)
        return command, result

    def prepare_release(self, separations, *, command_id="release"):
        return self.identities.prepare(release_command(command_id, self.authority, self.merge_policy,
                                                      separations, [self.subject]))

    def release(self, separations, *, command_id="release"):
        command = self.prepare_release(separations, command_id=command_id)
        result = self.identities.release_separations(command)
        self.assertEqual(result.get("outcome"), "released", result)
        return command, result

    def attach(self, target, *, label):
        query = deepcopy(self.query)
        query["selector"]["value"]["identity_test_target"] = label
        catalog, entries, _, _ = self.publish([target], query=query, command_id=f"catalog-{label}")
        proposal, _, _ = self.propose(catalog, entries, query=query, command_id=f"proposal-{label}")
        command = self.accept_command(proposal, catalog, [target], command_id=f"attach-{label}")
        result = self.service.accept(command)
        self.assertEqual(result.get("outcome"), "accepted", result)
        return self.storage.get(result["body"]["association"])

    def assertion(self, target, label, value):
        command = claim_command(f"claim-{label}", label, target, self.subject, value=value)
        result = self.claims.append(self.claims.prepare(command))
        self.assertEqual(result.get("outcome"), "appended", result)
        claim = self.storage.get(result["body"]["claim"])
        citation = relation_command(f"citation-{label}", f"citation-{label}", claim, self.subject,
                                   relation="reports_assertion", component=None,
                                   quotation="Synthetic report concerning an unassigned continuing subject.")
        related = self.evidence.relate(self.evidence.prepare(citation))
        self.assertEqual(related.get("outcome"), "appended", related)
        return claim, self.storage.get(related["body"]["relation"])

    def protect(self, first, second, *, command_id="protect", relation=None):
        command = decision_command(command_id, self.authority, first, second, self.policy,
                                   decision="protect", relation=relation or RELATION, capability="merge")
        prepared = self.service.prepare(command)
        result = self.service.decide(prepared)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["disposition"])

    def member_ids(self, reference):
        return {item["id"] for item in self.identities.view(reference)["members"]}

    def assert_no_journal(self, command):
        with self.assertRaises(StorageError) as error:
            self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def crash(self, command, stage):
        context = multiprocessing.get_context("spawn")
        process = context.Process(target=interrupted_identity,
            args=(str(self.database), self.authority, command, stage))
        process.start()
        try:
            process.join(timeout=35)
            self.assertFalse(process.is_alive(), "Interrupted identity process did not terminate.")
            self.assertEqual(process.exitcode, CRASH_EXIT_CODE)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)

    def registered_assessment(self, matter, *, label="historical-assessment", merge_receipt=None):
        """Persist an incomplete fixture plus validity hook, not an evaluator run."""
        from matter.identity_dependencies import dependency_ref, register_identity_dependency
        from integration.helpers import domain_value
        from matter_helpers import assessment_fixture_command
        view = self.identities.view(matter)
        current = self.storage.get(view["survivor"])
        command = assessment_fixture_command(label, current, purpose="synthetic-review", audience="synthetic-host")
        dependencies = deepcopy(view["members"] + view["indexes"])
        if merge_receipt is not None:
            dependencies.append(as_pin(merge_receipt))
        command["expected_revisions"] = deepcopy(view["read_set"])
        for reference in dependencies:
            if reference not in command["expected_revisions"]:
                command["expected_revisions"].append(deepcopy(reference))
        proposed = command["body"]["assessment"]
        proposed["body"]["dependency_manifest"]["positive"] = deepcopy(dependencies)
        proposed["extensions"] = {"example:identity-view": domain_value(view)}
        def handler(tx):
            for reference in dependencies:
                tx.get(reference)
            stored = tx.insert(tx.command["body"]["assessment"])
            register_identity_dependency(tx, pin(stored), matters=view["members"])
            return tx.success("committed", {"assessment": pin(stored)})
        result = self.storage.execute(command, handler)
        self.assertEqual(result.get("outcome"), "committed", result)
        assessment = self.storage.get(result["body"]["assessment"])
        registration = self.storage.get(dependency_ref(assessment))
        self.assertEqual(registration["value"]["value"]["status"], "current")
        return assessment, registration
