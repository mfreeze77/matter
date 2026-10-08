"""Synthetic reports, grouping commands, and process workers for MAT-006."""

from copy import deepcopy
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from matter.occurrences import ExactGroupingPolicy, OccurrenceService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from integration.helpers import _in_scope, domain_value, fixture, record_input
from observation_helpers import observation_command


SCOPE = "synthetic:occurrence-grouping"
DIAGNOSTIC = b"Synthetic diagnostic: the same visible condition.\n"


def grouping_policy():
    return ExactGroupingPolicy(
        key_namespaces=["example:execution"],
        group_namespaces=["example:lineage", "example:alternate-lineage"],
    )


def event_key(value):
    return {"namespace": "example:execution", "value": value}


def group_key(value="root-group", namespace="example:lineage"):
    return {"namespace": namespace, "value": value}


def as_pin(value):
    return pin(value) if "body" in value else deepcopy(value)


def occurrence_input(identity, observations=(), *, execution=None, keys=None, scope_id=SCOPE):
    value = record_input("occurrence", identity, scope_id=scope_id)
    value["provenance"]["origin"] = "host"
    value["body"]["identity_keys"] = deepcopy(keys if keys is not None else [event_key(execution or identity)])
    value["body"]["observations"] = [as_pin(observation) for observation in observations]
    value["body"]["provenance_groups"] = []
    return value


def replacement(occurrence, observations):
    return {"occurrence": as_pin(occurrence), "observations": [as_pin(observation) for observation in observations]}


def declared(observation, group=None):
    return {"observation": as_pin(observation), "status": "declared", "group": deepcopy(group or group_key())}


def unknown(observation, reason="Synthetic dependence has not been established."):
    return {"observation": as_pin(observation), "status": "unknown", "reason": reason}


def grouping_command(command_id, *, creates=(), replacements=(), assignments=(),
                     expected_revisions=(), scope_id=SCOPE, policy=None):
    value = _in_scope(fixture("commands/commit_occurrence_grouping.json"), scope_id)
    value["command_id"] = command_id
    value["idempotency_key"] = f"key:{command_id}"
    value["expected_revisions"] = deepcopy(list(expected_revisions))
    value["body"] = {
        "creates": deepcopy(list(creates)),
        "replacements": deepcopy(list(replacements)),
        "provenance_assignments": deepcopy(list(assignments)),
        "grouping_policy": deepcopy((policy or grouping_policy()).ref),
        "basis": domain_value({"reason": "Explicit synthetic host grouping; no claim or independence inference."}),
    }
    return value


def coverage(status="complete"):
    value = {
        "status": status,
        "snapshot": {"namespace": "example", "id": "selected-synthetic-corpus", "version": "1.0", "digest": "0" * 64},
    }
    if status != "complete":
        value["reason"] = f"Synthetic collection coverage is {status}."
    return value


class OccurrenceTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.database = self.directory / "occurrences.sqlite"
        self.storage = SQLiteStore(self.database, scope_id=SCOPE)
        self.addCleanup(self.storage.close)
        self.payloads = FilePayloadStore(self.directory / "payloads", scope_id=SCOPE)
        self.observations = ObservationIngestor(self.storage, self.payloads)
        self.policy = grouping_policy()
        self.service = OccurrenceService(self.storage, grouping_policy=self.policy)
        self.observation_commands = {}

    def observe(self, identity, *, parents=(), origin=None, payload=DIAGNOSTIC):
        command = observation_command(f"ingest:{identity}", identity, payload=payload,
                                      scope_id=SCOPE, event_id=f"source:{identity}")
        provenance = command["body"]["observation"]["provenance"]
        provenance["origin"] = origin or ("derived" if parents else "source")
        provenance["parents"] = [as_pin(parent) for parent in parents]
        provenance["run_id"] = f"run:{identity}"
        prepared = self.observations.prepare(command)
        result = self.observations.ingest(prepared, payload=payload)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["outcome"], "committed")
        self.observation_commands[identity] = prepared
        return self.storage.get(result["body"]["observation"])

    def submit(self, command):
        prepared = self.service.prepare(command)
        return prepared, self.service.commit(prepared)

    def group(self, identity, observations=(), *, assignments=(), execution=None, keys=None):
        proposed = occurrence_input(identity, observations, execution=execution, keys=keys)
        command = grouping_command(f"group:{identity}", creates=[proposed], assignments=assignments)
        _, result = self.submit(command)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["outcome"], "committed")
        return self.storage.get(entity_ref(proposed))

    def count(self, observations, *, source_coverage=None):
        return self.service.counts([as_pin(observation) for observation in observations],
                                   coverage=source_coverage if source_coverage is not None else coverage())

    def assert_counts(self, result, observations, occurrences, provenance_groups):
        self.assertEqual(result["counts"], {
            "observations": observations, "occurrences": occurrences, "provenance_groups": provenance_groups,
        })

    def assert_failure(self, result, code):
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], code)
        self.assertNotIn("outcome", result)

    def assert_missing(self, reference):
        with self.assertRaises(StorageError) as error:
            self.storage.get(reference)
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def record_counts(self):
        with sqlite3.connect(self.database) as connection:
            return dict(connection.execute(
                "SELECT record_type, count(*) FROM heads WHERE scope_id=? GROUP BY record_type", (SCOPE,),
            ).fetchall())


def grouping_in_child(database, command, barrier, output):
    """Commit the frozen prepared command without refreshing its read set."""
    with SQLiteStore(database, scope_id=SCOPE) as storage:
        service = OccurrenceService(storage, grouping_policy=grouping_policy())
        barrier.wait(timeout=30)
        result = service.commit(command)
    output.put({"command_id": command["command_id"], "result": result})


def competing_groupings(test, database, commands):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    output = context.Queue()
    processes = [context.Process(target=grouping_in_child,
                                 args=(str(database), command, barrier, output)) for command in commands]
    for process in processes:
        process.start()
    try:
        barrier.wait(timeout=30)
        messages = [output.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            test.assertFalse(process.is_alive(), "Competing grouping did not terminate.")
            test.assertEqual(process.exitcode, 0)
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        output.close()
        output.join_thread()
    return {message["command_id"]: message["result"] for message in messages}
