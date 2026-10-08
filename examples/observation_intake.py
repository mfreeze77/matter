"""Synthetic installed-API example: commit, redeliver, correct, and query history.

Run ``python examples/observation_intake.py`` from an installed checkout. This
example also runs outside the checkout with the installed wheel alone.
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from matter.canonical import canonical_digest, source_digest
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore


SCOPE = "example:observation-intake"


def known(value):
    return {"state": "known", "value": value, "precision": "second"}


def command(identity, payload, available):
    producer = {
        "namespace": "example", "id": "synthetic-source-adapter", "version": "1.0",
        "digest": canonical_digest({"purpose": "synthetic intake example"}, "example.adapter.v1"),
    }
    return {
        "schema_version": "1.0", "operation": "ingest_observation", "command_id": identity,
        "idempotency_key": "key:" + identity, "scope_id": SCOPE,
        "actor": {"scope_id": SCOPE, "namespace": "example", "id": "authorized-host"},
        "authority": {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "host-grant"},
        "expected_revisions": [],
        "body": {"observation": {
            "schema_version": "1.0", "record_type": "observation", "scope_id": SCOPE,
            "namespace": "example", "id": "observation:" + identity,
            "provenance": {"origin": "source", "producer": producer, "recorded_at": available, "parents": []},
            "body": {
                "source_identity": {"namespace": "example:publisher", "event_id": "notice-1"},
                "content": {
                    "digest": source_digest(payload), "byte_length": len(payload), "media_type": "text/plain",
                    "locator": {"kind": "whole_artifact", "uri": "urn:example:notice:1"},
                    "availability": {"status": "available", "checked_at": available},
                },
                "occurred_at": {"state": "unknown", "reason": "not_reported"},
                "source_published_at": {"state": "unknown", "reason": "not_reported"},
                "available_at": available, "ingested_at": available, "extraction": producer,
            },
        }},
    }


def main():
    first_time = known("2026-10-08T10:00:00Z")
    correction_time = known("2026-10-08T11:00:00Z")
    original_bytes = b"Synthetic notice: meeting at 14:00.\n"
    corrected_bytes = b"Synthetic correction: meeting at 15:00.\n"
    source = {"namespace": "example:publisher", "event_id": "notice-1"}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payloads = FilePayloadStore(root / "payloads", scope_id=SCOPE)
        with SQLiteStore(root / "matter.sqlite", scope_id=SCOPE) as store:
            intake = ObservationIngestor(store, payloads)
            prepared = intake.prepare(command("first", original_bytes, first_time))
            first = intake.ingest(prepared, payload=original_bytes)
            assert first["outcome"] == "committed", first
            assert intake.ingest(prepared) == first

            redelivery = deepcopy(prepared)
            redelivery.update(command_id="delivery-2", idempotency_key="key:delivery-2", expected_revisions=[])
            redelivery["body"]["observation"]["id"] = "proposed-new-id"
            redelivery["body"]["observation"]["body"]["ingested_at"] = correction_time
            duplicate = intake.ingest(intake.prepare(redelivery))
            assert duplicate["outcome"] == "duplicate", duplicate
            assert duplicate["body"] == first["body"]
            assert duplicate["receipt"] != first["receipt"]

            correction = command("correction", corrected_bytes, correction_time)
            correction["body"]["observation"]["supersedes"] = [first["body"]["observation"]]
            corrected = intake.ingest(intake.prepare(correction), payload=corrected_bytes)
            assert corrected["outcome"] == "committed", corrected
            assert intake.heads(source, as_of=first_time)[0]["id"] == "observation:first"
            assert intake.heads(source, as_of=correction_time)[0]["id"] == "observation:correction"
            assert intake.read_payload(first["body"]["observation"]).data == original_bytes
            assert len(intake.revisions(source)) == 2
        with SQLiteStore(root / "matter.sqlite", scope_id=SCOPE) as store:
            intake = ObservationIngestor(store, payloads)
            assert intake.ingest(prepared) == first
            assert len(intake.revisions(source)) == 2
    print("Observation intake passed: committed, duplicate, correction, historical views, exact bytes, restart.")


if __name__ == "__main__":
    main()
