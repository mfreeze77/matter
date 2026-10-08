"""Synthetic observation commands shared by MAT-004 behavioral tests."""

from copy import deepcopy
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from matter.canonical import source_digest
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore, PayloadRead
from matter.storage import SQLiteStore, StorageError

from integration.helpers import ingest_command


SCOPE = "synthetic:observations"
SOURCE_NAMESPACE = "example:publisher"
SOURCE_EVENT = "source-event-one"
PAYLOAD = b"Synthetic original source bytes.\n"


def known_time(value="2026-10-08T15:00:00Z"):
    digits = len(value.partition(".")[2][:-1]) if "." in value else 0
    precision = {0: "second", 3: "millisecond", 6: "microsecond", 9: "nanosecond"}[digits]
    return {"state": "known", "value": value, "precision": precision}


def observation_command(command_id, observation_id, *, payload=PAYLOAD, scope_id=SCOPE,
                        source_namespace=SOURCE_NAMESPACE, event_id=SOURCE_EVENT,
                        revision_id=None, available_at=None):
    command = ingest_command(command_id, observation_id, scope_id=scope_id)
    observation = command["body"]["observation"]
    observation["provenance"]["origin"] = "source"
    source = {"namespace": source_namespace, "event_id": event_id}
    if revision_id is not None:
        source["revision_id"] = revision_id
    observation["body"]["source_identity"] = source
    content = observation["body"]["content"]
    content["digest"] = source_digest(payload)
    content["byte_length"] = len(payload)
    content["locator"]["uri"] = f"urn:synthetic:source:{source_namespace}:{event_id}"
    observation["body"]["available_at"] = deepcopy(available_at or known_time())
    return command


def redelivery(original, command_id, observation_id):
    command = deepcopy(original)
    command["command_id"] = command_id
    command["idempotency_key"] = f"key:{command_id}"
    command["expected_revisions"] = []
    command["body"]["observation"]["id"] = observation_id
    return command


class UnavailablePayloads:
    """A port whose local bytes have become unavailable after a valid commit."""

    def __init__(self, scope_id=SCOPE):
        self.scope_id = scope_id
        self.read_calls = 0
        self.put_calls = 0

    def read(self, content):
        self.read_calls += 1
        return PayloadRead("unavailable", content["digest"], None, "Synthetic unavailable bytes.")

    def put(self, data):
        self.put_calls += 1
        raise StorageError("E_STORAGE_UNAVAILABLE")


class ObservationTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.database = self.directory / "observations.sqlite"
        self.payload_directory = self.directory / "payloads"
        self.storage = SQLiteStore(self.database, scope_id=SCOPE)
        self.addCleanup(self.storage.close)
        self.payloads = FilePayloadStore(self.payload_directory, scope_id=SCOPE)
        self.ingestor = ObservationIngestor(self.storage, self.payloads)

    def submit(self, command, payload=PAYLOAD):
        prepared = self.ingestor.prepare(command)
        result = self.ingestor.ingest(prepared, payload=payload)
        return prepared, result

    def assert_failure(self, result, code):
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error"]["code"], code)
        self.assertNotIn("outcome", result)

    def assert_missing(self, reference):
        with self.assertRaises(StorageError) as error:
            self.storage.get(reference)
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def record_counts(self):
        # The port has no global search API. Inspect the documented SQLite
        # identity table read-only to detect unintended domain-object creation.
        with sqlite3.connect(self.database) as connection:
            return dict(connection.execute(
                "SELECT record_type, count(*) FROM heads WHERE scope_id=? GROUP BY record_type",
                (SCOPE,),
            ).fetchall())


def concurrent_ingest(database, payload_directory, command, payload, barrier, output):
    """Spawn-safe worker; never refresh the already prepared command."""
    with SQLiteStore(database, scope_id=SCOPE) as storage:
        payloads = FilePayloadStore(payload_directory, scope_id=SCOPE)
        ingestor = ObservationIngestor(storage, payloads)
        barrier.wait(timeout=30)
        result = ingestor.ingest(command, payload=payload)
    output.put({"command_id": command["command_id"], "result": result})


def competing_results(test, database, payload_directory, commands, payload):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    output = context.Queue()
    processes = [context.Process(
        target=concurrent_ingest,
        args=(str(database), str(payload_directory), command, payload, barrier, output),
    ) for command in commands]
    for process in processes:
        process.start()
    try:
        barrier.wait(timeout=30)
        messages = [output.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            test.assertFalse(process.is_alive(), "Concurrent ingestion did not terminate.")
            test.assertEqual(process.exitcode, 0)
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        output.close()
        output.join_thread()
    return {message["command_id"]: message["result"] for message in messages}
