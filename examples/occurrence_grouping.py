"""Synthetic installed-API example of reports, happenings, and provenance.

Run ``python examples/occurrence_grouping.py`` after installing Matter. This
example uses explicit host declarations; it does not infer cause or evaluate
whether any diagnostic is true.
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from matter.canonical import source_digest
from matter.observations import ObservationIngestor
from matter.occurrences import ExactGroupingPolicy, OccurrenceService
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, entity_ref, pin


SCOPE = "synthetic:occurrence-example"
TIME = {"state": "known", "value": "2026-10-08T18:00:00Z", "precision": "second"}
PRODUCER = {
    "namespace": "example", "id": "synthetic-host", "version": "1.0",
    "digest": source_digest(b"Synthetic MAT-006 occurrence example v1"),
}
POLICY = ExactGroupingPolicy(key_namespaces=["example:execution"], group_namespaces=["example:lineage"])
COVERAGE = {"status": "complete", "snapshot": deepcopy(PRODUCER)}
GROUP_A = {"namespace": "example:lineage", "value": "source-family-a"}
GROUP_B = {"namespace": "example:lineage", "value": "source-family-b"}


def envelope(label, operation, body):
    return {
        "schema_version": "1.0", "operation": operation,
        "command_id": f"command-{label}", "idempotency_key": f"request-{label}",
        "scope_id": SCOPE,
        "actor": {"scope_id": SCOPE, "namespace": "example", "id": "authorized-host"},
        "authority": {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "host-grant"},
        "expected_revisions": [], "body": body,
    }


def observe(intake, label, payload, parents=()):
    observation = {
        "schema_version": "1.0", "record_type": "observation", "scope_id": SCOPE,
        "namespace": "example", "id": f"observation-{label}",
        "provenance": {
            "origin": "derived" if parents else "source", "producer": deepcopy(PRODUCER),
            "recorded_at": deepcopy(TIME), "parents": deepcopy(list(parents)),
        },
        "body": {
            "source_identity": {"namespace": "example:reports", "event_id": label},
            "content": {
                "digest": source_digest(payload), "byte_length": len(payload), "media_type": "text/plain",
                "locator": {"kind": "whole_artifact", "uri": f"urn:example:report:{label}"},
                "availability": {"status": "available", "checked_at": deepcopy(TIME)},
            },
            "occurred_at": {"state": "unknown", "reason": "not_reported"},
            "source_published_at": deepcopy(TIME), "available_at": deepcopy(TIME),
            "ingested_at": deepcopy(TIME), "extraction": deepcopy(PRODUCER),
        },
    }
    command = intake.prepare(envelope(f"observe-{label}", "ingest_observation", {"observation": observation}))
    result = intake.ingest(command, payload=payload)
    assert result["status"] == "success", result
    return result["body"]["observation"]


def occurrence(label, observations):
    return {
        "schema_version": "1.0", "record_type": "occurrence", "scope_id": SCOPE,
        "namespace": "example", "id": f"occurrence-{label}",
        "provenance": {"origin": "host", "producer": deepcopy(PRODUCER), "recorded_at": deepcopy(TIME), "parents": []},
        "body": {
            "kind": "example:execution", "identity_keys": [{"namespace": "example:execution", "value": label}],
            "observations": deepcopy(observations), "provenance_groups": [],
            "occurred_at": {"state": "unknown", "reason": "not_reported"},
        },
    }


def grouping(label, *, creates=(), replacements=(), assignments=()):
    return envelope(label, "commit_occurrence_grouping", {
        "creates": deepcopy(list(creates)), "replacements": deepcopy(list(replacements)),
        "provenance_assignments": deepcopy(list(assignments)), "grouping_policy": POLICY.reference,
        "basis": {"schema": deepcopy(PRODUCER), "value": {"reason": label, "authority": "synthetic_host_declaration"}},
    })


def main():
    diagnostic = b"Synthetic diagnostic: operation failed.\n"
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payloads = FilePayloadStore(root / "payloads", scope_id=SCOPE)
        database = root / "matter.sqlite"
        with SQLiteStore(database, scope_id=SCOPE) as store:
            intake = ObservationIngestor(store, payloads)
            service = OccurrenceService(store, grouping_policy=POLICY)
            log_a = observe(intake, "log-a", diagnostic)
            report_a = observe(intake, "report-a", b"Synthetic report of execution A.\n", [log_a])
            log_b = observe(intake, "log-b", diagnostic)
            first = service.prepare(grouping("initial-grouping", creates=[occurrence("execution-a", [log_a, report_a, log_b])], assignments=[
                {"observation": log_a, "status": "declared", "group": GROUP_A},
                {"observation": log_b, "status": "declared", "group": GROUP_A},
            ]))
            accepted = service.commit(first)
            assert accepted["outcome"] == "committed", accepted
            original = store.get(accepted["body"]["occurrences"][0])
            assert service.counts([log_a, report_a], coverage=COVERAGE)["counts"] == {
                "observations": 2, "occurrences": 1, "provenance_groups": 1,
            }

            split = service.prepare(grouping("split-new-execution", creates=[occurrence("execution-b", [log_b])], replacements=[
                {"occurrence": pin(original), "observations": [log_a, report_a]},
            ]))
            corrected = service.commit(split)
            assert corrected["outcome"] == "committed", corrected
            cohort = [log_a, report_a, log_b]
            assert service.counts(cohort, coverage=COVERAGE)["counts"] == {
                "observations": 3, "occurrences": 2, "provenance_groups": 1,
            }
            assert store.history(entity_ref(original))[0] == original
            assert intake.read_payload(log_a).data == intake.read_payload(log_b).data == diagnostic

            summary = observe(intake, "summary", b"Synthetic summary of two executions.\n", [log_a, log_b])
            current_a = service.resolve([{"namespace": "example:execution", "value": "execution-a"}])
            current_b = service.resolve([{"namespace": "example:execution", "value": "execution-b"}])
            summarized = service.commit(service.prepare(grouping("accept-summary", replacements=[
                {"occurrence": pin(current_a), "observations": [log_a, report_a, summary]},
                {"occurrence": pin(current_b), "observations": [log_b, summary]},
            ])))
            assert summarized["status"] == "success", summarized
            cohort.append(summary)
            assert service.counts(cohort, coverage=COVERAGE)["counts"] == {
                "observations": 4, "occurrences": 2, "provenance_groups": 1,
            }
            declaration = service.commit(service.prepare(grouping("correct-source-family", assignments=[
                {"observation": log_b, "status": "declared", "group": GROUP_B},
            ])))
            assert declaration["outcome"] == "committed", declaration
            assert len(declaration["body"]["previous"]) == 2
            final = service.counts(cohort, coverage=COVERAGE)
            assert final["counts"] == {"observations": 4, "occurrences": 2, "provenance_groups": 2}
            assert service.counts([log_a], coverage=COVERAGE)["counts"]["provenance_groups"] == 1
            assert service.commit(first) == accepted
            backup = store.backup_to(root / "backup.sqlite")

        with SQLiteStore.restore_from(backup, root / "restored.sqlite", scope_id=SCOPE) as store:
            service = OccurrenceService(store, grouping_policy=POLICY)
            assert service.counts(cohort, coverage=COVERAGE) == final
            assert service.commit(split) == corrected
            assert service.commit(first) == accepted
    print("Occurrence grouping example passed: 2 reports/1 execution, atomic split, identical diagnostics, inherited groups, correction, retry, and restore.")


if __name__ == "__main__":
    main()
