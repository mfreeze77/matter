"""Synthetic source coverage and absence guards over real scoped storage."""

from copy import deepcopy
import multiprocessing
import os

from matter.canonical import source_digest
from matter.coverage import CoveragePolicy, CoverageService, observation_predicate
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.source_catalogs import source_key
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from association_helpers import ACTOR, SCOPE, AssociationTestCase, as_pin, envelope
from integration.helpers import create_command, domain_value, projection_ref
from observation_helpers import known_time, observation_command


SOURCE_NAMESPACE = "example:coverage-source"
OTHER_SOURCE = "example:other-coverage-source"
ADAPTER = {"namespace": "example:coverage", "id": "synthetic-source-adapter", "version": "1.0",
           "digest": source_digest(b"Synthetic bounded coverage adapter v1")}
CATALOG = {"namespace": "example:coverage", "id": "synthetic-catalog", "version": "1.0",
           "digest": source_digest(b"Synthetic declared catalog v1")}
T0, T1, T2, T3, T4 = [known_time(f"2026-10-08T{hour}:00:00Z") for hour in ("12", "13", "14", "15", "16")]
UNKNOWN = {"state": "unknown", "reason": "not_reported"}
CRASH_EXIT_CODE = 81


def policy_for(authority, *, allow_retirement=True):
    return CoveragePolicy(SCOPE, actors=[ACTOR], authorities=[pin(authority)],
                          adapters=[ADAPTER], allow_retirement=allow_retirement)


def specification(*, event="expected-event", sources=None, start=None, end=None, clauses=None):
    return {"query": observation_predicate(clauses=clauses if clauses is not None else [
                {"field": "source_event_id", "equals": event}]),
            "eligible_sources": [source_key(value) for value in (sources or [SOURCE_NAMESPACE])],
            "observed_interval": {"start": deepcopy(start or T0), "end": deepcopy(end or T2),
                                  "bounds": "closed_open"}}


def publish_command(command_id, authority, policy, spec, *, previous=None, status="complete",
                    mode="replacement", members=(), baselines=(), as_of=None):
    coverage = {"status": status, "snapshot": deepcopy(CATALOG)}
    if status != "complete":
        coverage["reason"] = f"Synthetic source collection reports {status}."
    return envelope(command_id, "publish_coverage", {
        "specification": spec, "catalog": CATALOG, "coverage": coverage,
        "as_of": deepcopy(as_of or T2), "mode": mode, "members": list(members),
        "source_baselines": list(baselines), "previous": as_pin(previous) if previous else None,
        "adapter": ADAPTER, "coverage_policy": policy.reference,
    }, authority)


def register_command(command_id, authority, policy, target, coverage, *, identity=None,
                     previous=None, as_of=None, expires_at=None, next_check_at=None):
    body = {"id": identity or command_id, "reference": as_pin(target), "coverage": as_pin(coverage),
            "as_of": deepcopy(as_of or T2), "previous": as_pin(previous) if previous else None,
            "coverage_policy": policy.reference,
            "expires_at": deepcopy(expires_at or T4)}
    if next_check_at is not None:
        body["next_check_at"] = deepcopy(next_check_at)
    return envelope(command_id, "register_negative_watch", body, authority)


def member(record, ownership="machine"):
    return {"reference": as_pin(record), "ownership": ownership}


def coverage_worker(database, payload_directory, authority, command, *, payload=None,
                    barrier=None, output=None, crash_at=None):
    def fault(stage):
        if stage == crash_at:
            os._exit(CRASH_EXIT_CODE)
    try:
        with SQLiteStore(database, scope_id=SCOPE, fault_hook=fault) as storage:
            if barrier is not None:
                barrier.wait(timeout=30)
            if command["operation"] == "ingest_observation":
                ingestor = ObservationIngestor(storage, FilePayloadStore(payload_directory, scope_id=SCOPE))
                result = ingestor.ingest(command, payload=payload)
            else:
                service = CoverageService(storage, policy=policy_for(authority))
                operation = service.publish if command["operation"] == "publish_coverage" else service.register
                result = operation(command)
        if output is not None:
            output.put({"command_id": command["command_id"], "result": result})
        elif crash_at is not None:
            raise AssertionError(f"Requested interruption was not reached: {result!r}")
    except Exception as error:
        if output is None:
            raise
        output.put({"worker_error": type(error).__name__, "detail": str(error)})


class CoverageTestCase(AssociationTestCase):
    def setUp(self):
        super().setUp()
        self.coverage_policy = policy_for(self.authority)
        self.coverage = CoverageService(self.storage, policy=self.coverage_policy)

    def host_projection(self, identity):
        """Trusted fixture owner; coverage revisions membership, never this object."""
        command = create_command(f"host-{identity}", f"host-{identity}", scope_id=SCOPE)
        def handler(tx):
            matter = tx.insert(tx.command["body"]["matter"])
            tx.put_projection(projection_ref(identity, SCOPE), domain_value({"synthetic_fact": identity}))
            return tx.success("created", {"matter": pin(matter)})
        result = self.storage.execute(command, handler)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(projection_ref(identity, SCOPE))

    def publish_coverage(self, *, command_id="coverage", spec=None, previous=None, status="complete",
                         mode="replacement", members=(), baselines=None, observations=(),
                         as_of=None, service=None, policy=None):
        spec = spec or specification()
        if baselines is None:
            baselines = [] if previous else [{"source": key, "observations": [pin(item) for item in observations
                if source_key(item["body"]["source_identity"]["namespace"]) == key],
                "history_complete": True} for key in spec["eligible_sources"]]
        service, policy = service or self.coverage, policy or self.coverage_policy
        command = publish_command(command_id, self.authority, policy, spec, previous=previous,
            status=status, mode=mode, members=members, baselines=baselines, as_of=as_of)
        prepared = service.prepare(command)
        result = service.publish(prepared)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["coverage"]), prepared, result

    def register_watch(self, coverage, *, identity="absence", target=None, command_id=None,
                       previous=None, as_of=None, next_check_at=None, expires_at=None):
        target = target or self.host_projection(identity)
        command = register_command(command_id or f"register-{identity}", self.authority,
            self.coverage_policy, target, coverage, identity=identity, previous=previous,
            as_of=as_of, next_check_at=next_check_at, expires_at=expires_at)
        prepared = self.coverage.prepare(command)
        result = self.coverage.register(prepared)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["registration"]), prepared, result

    def arrival_command(self, identity, *, event="expected-event", source=SOURCE_NAMESPACE,
                        available_at=None, occurred_at=None, extensions=None):
        payload = f"Synthetic source report {identity}.\n".encode()
        command = observation_command(f"arrival-{identity}", identity, payload=payload, scope_id=SCOPE,
            source_namespace=source, event_id=event, revision_id=identity, available_at=available_at or T1)
        record = command["body"]["observation"]
        record["body"].update(occurred_at=deepcopy(occurred_at or T1), source_published_at=deepcopy(T1),
                               ingested_at=deepcopy(T3))
        if extensions is not None:
            record["extensions"] = deepcopy(extensions)
        return command, payload

    def arrival(self, identity, **kwargs):
        command, payload = self.arrival_command(identity, **kwargs)
        prepared = self.ingestor.prepare(command)
        result = self.ingestor.ingest(prepared, payload=payload)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["observation"]), prepared, result

    def current(self, record):
        return self.storage.get(entity_ref(record))

    @staticmethod
    def value(record):
        return record["value"]["value"]

    @staticmethod
    def member_states(coverage):
        return {item["reference"]["id"]: item for item in coverage["value"]["value"]["members"]}

    def assert_no_journal(self, command):
        with self.assertRaises(StorageError) as error:
            self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def crash(self, command, stage, *, payload=None):
        context = multiprocessing.get_context("spawn")
        process = context.Process(target=coverage_worker,
            args=(str(self.database), str(self.directory / "payloads"), self.authority, command),
            kwargs={"payload": payload, "crash_at": stage})
        process.start()
        try:
            process.join(timeout=35)
            self.assertFalse(process.is_alive(), "Coverage worker did not terminate.")
            self.assertEqual(process.exitcode, CRASH_EXIT_CODE)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=5)

    def competing(self, commands):
        context = multiprocessing.get_context("spawn")
        barrier, output = context.Barrier(len(commands)), context.Queue()
        processes = [context.Process(target=coverage_worker,
            args=(str(self.database), str(self.directory / "payloads"), self.authority, command),
            kwargs={"barrier": barrier, "output": output}) for command in commands]
        started = []
        try:
            for process in processes:
                process.start()
                started.append(process)
            messages = [output.get(timeout=40) for _ in started]
            for process in started:
                process.join(timeout=35)
                self.assertFalse(process.is_alive(), "Competing coverage worker did not terminate.")
                self.assertEqual(process.exitcode, 0)
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
        self.assertTrue(all("result" in message for message in messages), messages)
        return {message["command_id"]: message["result"] for message in messages}
