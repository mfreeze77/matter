"""Synthetic commands and process workers for MAT-005 continuity checks."""

from copy import deepcopy
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from matter.identity_keys import ExactIdentityPolicy, new_matter_id
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, pin

from integration.helpers import _in_scope, create_command, fixture
from observation_helpers import observation_command


SCOPE = "synthetic:continuity"
KEY_NAMESPACES = ("example:subject", "example:registry")


def identity_policy():
    return ExactIdentityPolicy(key_namespaces=KEY_NAMESPACES)


def identity_key(value="continuing-subject", namespace="example:subject"):
    return {"namespace": namespace, "value": value}


def matter_command(command_id, *, matter_id=None, keys=None, scope_id=SCOPE,
                   policy=None, domain_kind="example:opportunity"):
    value = create_command(command_id, matter_id or new_matter_id(), scope_id=scope_id)
    value["body"]["identity_policy"] = deepcopy((policy or identity_policy()).reference)
    matter = value["body"]["matter"]
    matter["body"]["identity_keys"] = deepcopy(keys if keys is not None else [identity_key()])
    matter["body"]["domain_kind"] = domain_kind
    matter["body"]["title"] = "Synthetic continuing opportunity"
    matter["provenance"]["run_id"] = f"run:{command_id}"
    return value


def metadata_command(command_id, matter, metadata, *, expected_revisions=()):
    value = create_command(command_id, matter["id"], scope_id=matter["scope_id"],
                           expected_revisions=expected_revisions)
    value["operation"] = "update_matter_metadata"
    value["body"] = {
        "matter": pin(matter) if "body" in matter else deepcopy(matter),
        "metadata": deepcopy(metadata),
    }
    return value


def assessment_fixture_command(command_id, matter, *, purpose, audience, version="1.0"):
    """Bind contexts structurally; this fixture performs no assessment evaluation."""
    value = _in_scope(fixture("commands/commit_assessment.json"), matter["scope_id"])
    value["command_id"] = command_id
    value["idempotency_key"] = f"key:{command_id}"
    value["expected_revisions"] = [pin(matter)]
    assessment = value["body"]["assessment"]
    assessment["id"] = command_id
    body = assessment["body"]
    body["matter"] = pin(matter)
    body["purpose"].update(id=purpose, version=version)
    body["audience"] = {**body["purpose"], "id": audience}
    body["dependency_manifest"]["positive"] = [pin(matter)]
    body["judgments"] = []
    body["propositions"] = []
    body["evaluation_state"] = "incomplete"
    body["stop_reason"] = "incomplete"
    body["limitations"] = ["Synthetic context binding only; no assessment engine was executed."]
    body["input_artifact"] = {"state": "unavailable", "reason": "not_recorded"}
    body["evidence_selection"]["references"] = []
    body["evidence_selection"]["coverage"]["status"] = "partial"
    body["evidence_selection"]["coverage"]["reason"] = "Synthetic context binding does not establish evidence coverage."
    return value


def store_assessment_fixture(tx):
    """Generic storage proves coexistence, not MAT-015 assessment semantics."""
    proposed = tx.command["body"]["assessment"]
    tx.get(proposed["body"]["matter"])
    stored = tx.insert(proposed)
    return tx.success("committed", {"assessment": pin(stored)})


class MatterTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.database = self.directory / "matters.sqlite"
        self.payload_directory = self.directory / "payloads"
        self.storage = SQLiteStore(self.database, scope_id=SCOPE)
        self.addCleanup(self.storage.close)
        self.policy = identity_policy()
        self.service = MatterService(self.storage, identity_policy=self.policy)

    def submit_create(self, command):
        prepared = self.service.prepare(command)
        return prepared, self.service.create(prepared)

    def submit_metadata(self, command):
        prepared = self.service.prepare(command)
        return prepared, self.service.update_metadata(prepared)

    def assert_failure(self, result, code):
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], code)
        self.assertNotIn("outcome", result)

    def assert_missing(self, reference):
        with self.assertRaises(StorageError) as error:
            self.storage.get(reference)
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def record_counts(self):
        # Read-only inspection detects accidental matter/evidence/context creation.
        with sqlite3.connect(self.database) as connection:
            return dict(connection.execute(
                "SELECT record_type, count(*) FROM heads WHERE scope_id=? GROUP BY record_type",
                (SCOPE,),
            ).fetchall())


def continuing_subject_in_child(database, payload_directory, command, output):
    """Start fresh services, reuse identity, and ingest unassociated later evidence."""
    with SQLiteStore(database, scope_id=SCOPE) as storage:
        service = MatterService(storage, identity_policy=identity_policy())
        result = service.create(service.prepare(command))
        payloads = FilePayloadStore(payload_directory, scope_id=SCOPE)
        observations = ObservationIngestor(storage, payloads)
        payload = b"Synthetic later evidence from a new processing run.\n"
        observation = observation_command(
            "later-unassociated-event", "later-unassociated-event", payload=payload,
            scope_id=SCOPE, event_id="later-event",
        )
        observation["body"]["observation"]["provenance"]["run_id"] = "run:new-process"
        evidence = observations.ingest(observations.prepare(observation), payload=payload)
        resolved = service.resolve(command["body"]["matter"]["body"]["identity_keys"])
    output.put({"result": result, "evidence": evidence, "resolved": resolved})


def restarted_subject(test, database, payload_directory, command):
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=continuing_subject_in_child,
                              args=(str(database), str(payload_directory), command, output))
    process.start()
    try:
        message = output.get(timeout=30)
        process.join(timeout=30)
        test.assertFalse(process.is_alive(), "Restarted service process did not terminate.")
        test.assertEqual(process.exitcode, 0)
        return message
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        output.close()
        output.join_thread()


def concurrent_matter_operation(database, command, barrier, output):
    """Execute exactly the prepared command; never refresh pins in the worker."""
    with SQLiteStore(database, scope_id=SCOPE) as storage:
        service = MatterService(storage, identity_policy=identity_policy())
        operation = service.create if command["operation"] == "create_matter" else service.update_metadata
        barrier.wait(timeout=30)
        result = operation(command)
    output.put({"command_id": command["command_id"], "result": result})


def competing_matter_results(test, database, commands):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    output = context.Queue()
    processes = [context.Process(target=concurrent_matter_operation,
                                 args=(str(database), command, barrier, output)) for command in commands]
    for process in processes:
        process.start()
    try:
        barrier.wait(timeout=30)
        messages = [output.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            test.assertFalse(process.is_alive(), "Competing matter operation did not terminate.")
            test.assertEqual(process.exitcode, 0)
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        output.close()
        output.join_thread()
    return {message["command_id"]: message["result"] for message in messages}
