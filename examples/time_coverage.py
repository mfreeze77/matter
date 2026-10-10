"""Installed MAT-010 example using synthetic host declarations and exact bytes.

The host explicitly attests the legacy source baseline and supplies typed
metadata. No crawler, semantic classifier, assessment engine or source-truth
qualification is implied. Coverage retires only its own machine membership;
the original host projections and immutable source observations remain intact.
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from matter.canonical import source_digest
from matter.coverage import CoveragePolicy, CoverageService, observation_predicate
from matter.negative_dependencies import negative_status, require_current_negative_dependency
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.source_catalogs import source_key
from matter.storage import SQLiteStore, StorageError, entity_ref, pin
from matter.time import select_effective, select_knowledge


SCOPE = "synthetic:time-coverage-example"
SOURCE_NAMESPACE = "example:declared-event-source"
ACTOR = {"scope_id": SCOPE, "namespace": "example", "id": "coverage-host"}
AUTHORITY = {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "coverage-grant"}
HOST = {"namespace": "example", "id": "time-coverage-host", "version": "1.0",
        "digest": source_digest(b"Synthetic MAT-010 coverage host v1")}
ADAPTER = {"namespace": "example", "id": "declared-source-metadata", "version": "1.0",
           "digest": source_digest(b"Synthetic subject and event-kind adapter v1")}
CATALOG = {"namespace": "example", "id": "declared-source-collection", "version": "1.0",
           "digest": source_digest(b"Synthetic bounded source collection v1")}
T0, T1, T2, T3, T4 = [
    {"state": "known", "value": f"2026-10-08T{hour}:00:00Z", "precision": "second"}
    for hour in ("12", "13", "14", "15", "16")
]


def domain(value, schema=HOST):
    return {"schema": deepcopy(schema), "value": deepcopy(value)}


def envelope(label, operation, body):
    return {"schema_version": "1.0", "scope_id": SCOPE, "operation": operation,
            "command_id": label, "idempotency_key": "request-" + label,
            "actor": deepcopy(ACTOR), "authority": deepcopy(AUTHORITY),
            "expected_revisions": [], "body": deepcopy(body)}


def record(kind, label, body, *, origin="host"):
    return {"schema_version": "1.0", "scope_id": SCOPE, "namespace": "example",
            "record_type": kind, "id": label,
            "provenance": {"origin": origin, "producer": deepcopy(HOST), "recorded_at": deepcopy(T2), "parents": []},
            "body": deepcopy(body)}


def specification(subject):
    # The watch knows the continuing subject and expected event kind. It does
    # not know the ID of any future observation or future source event.
    return {
        "query": observation_predicate([{"field": "extension", "key": "example:notice",
            "schema": ADAPTER, "value": {"subject_key": subject, "event_kind": "cancellation"}}]),
        "eligible_sources": [source_key(SOURCE_NAMESPACE)],
        "observed_interval": {"start": deepcopy(T0), "end": deepcopy(T2), "bounds": "closed_open"},
    }


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payloads = FilePayloadStore(root / "payloads", scope_id=SCOPE)
        with SQLiteStore(root / "matter.sqlite", scope_id=SCOPE) as store:
            bootstrap = envelope("bootstrap", "create_matter", {"identity_policy": HOST,
                "matter": record("matter", "host-setup", {"domain_kind": "example:host-setup",
                    "identity_keys": [{"namespace": "example:bootstrap", "value": "host-setup"}]})})
            projections = {}

            def trusted_setup(tx):
                tx.insert(record("receipt", "coverage-grant", {
                    "stage": "authority", "operation_id": "bootstrap", "recorded_at": T2,
                    "outcome": "example:coverage_grant", "evidence": [],
                    "details": domain("Synthetic trusted host admission; no external authentication claim."),
                }))
                for label in ("absence-dependent", "machine", "operator", "reviewed", "rejected"):
                    reference = {"scope_id": SCOPE, "namespace": "example:derivatives",
                                 "record_type": "matter:projection", "id": label}
                    projections[label] = tx.put_projection(reference, domain({"synthetic_derivative": label}))
                setup = tx.insert(tx.command["body"]["matter"])
                return tx.success("created", {"matter": pin(setup)})

            assert store.execute(bootstrap, trusted_setup)["outcome"] == "created"
            policy = CoveragePolicy(SCOPE, actors=[ACTOR], authorities=[pin(store.get(AUTHORITY))],
                                    adapters=[ADAPTER], allow_retirement=True)
            coverage = CoverageService(store, policy=policy)
            intake = ObservationIngestor(store, payloads)

            def publish(label, spec, *, previous=None, status="complete", mode="replacement",
                        members=(), initialize=False, as_of=T2):
                declared = {"status": status, "snapshot": CATALOG}
                if status != "complete":
                    declared["reason"] = "Synthetic collection remains incomplete."
                command = envelope(label, "publish_coverage", {
                    "specification": spec, "catalog": CATALOG, "coverage": declared,
                    "as_of": as_of, "mode": mode, "members": list(members),
                    "source_baselines": [{"source": source_key(SOURCE_NAMESPACE), "observations": [],
                                          "history_complete": True}] if initialize else [],
                    "previous": pin(previous) if previous else None,
                    "adapter": ADAPTER, "coverage_policy": policy.reference,
                })
                result = coverage.publish(coverage.prepare(command))
                assert result.get("outcome") == "published", result
                return store.get(result["body"]["coverage"])

            narrow = specification("permit-A")
            empty = publish("explicit-empty-baseline", narrow, initialize=True)
            assert empty["value"]["value"]["history_complete"] is True
            assert empty["value"]["value"]["result"] == "adequate_empty"
            watch_command = envelope("watch-permit-A", "register_negative_watch", {
                "id": "permit-A-cancellation", "reference": pin(projections["absence-dependent"]),
                "coverage": pin(empty), "as_of": T2, "previous": None,
                "expires_at": T4, "next_check_at": T3, "coverage_policy": policy.reference,
            })
            watch_result = coverage.register(coverage.prepare(watch_command))
            assert watch_result.get("outcome") == "registered", watch_result
            watch = store.get(watch_result["body"]["registration"])
            assert watch["value"]["value"]["status"] == "current"

            # Clock checks are read-only. They create neither source events nor
            # new projection revisions, and elapsed time does not fill silence.
            with store.snapshot() as view:
                assert require_current_negative_dependency(view, SCOPE, pin(watch), as_of=T2) == watch
                assert negative_status(view, SCOPE, entity_ref(watch), as_of=T3) == "review_due"
                assert negative_status(view, SCOPE, entity_ref(watch), as_of=T4) == "expired"
                try:
                    require_current_negative_dependency(view, SCOPE, entity_ref(watch), as_of=T4)
                except StorageError as error:
                    assert error.code == "E_DEPENDENCY_STALE", error
                else:
                    raise AssertionError("Expired absence remained usable.")
            assert store.history(entity_ref(watch)) == [watch]
            assert store.history(entity_ref(empty)) == [empty]

            # Replacement membership is scoped to this exact predicate/source/
            # interval. Protected owners and original projections survive.
            members_spec = specification("separate-membership-subject")
            membership = publish("membership-baseline", members_spec, members=[
                {"reference": pin(projections[label]), "ownership": label}
                for label in ("machine", "operator", "reviewed", "rejected")
            ])
            for label, status, mode in (("partial", "partial", "replacement"),
                                        ("incremental", "complete", "incremental")):
                membership = publish("empty-" + label, members_spec, previous=membership, status=status, mode=mode)
                states = {item["reference"]["id"]: item for item in membership["value"]["value"]["members"]}
                assert states["machine"]["status"] == "active"
                assert states["operator"]["status"] == "active"
                assert states["rejected"]["status"] == "rejected"
            membership = publish("complete-replacement", members_spec, previous=membership)
            states = {item["reference"]["id"]: item for item in membership["value"]["value"]["members"]}
            assert states["machine"]["status"] == "retired"
            assert states["operator"]["status"] == "active"
            assert states["reviewed"]["status"] == "active" and states["reviewed"]["review_required"]
            assert states["rejected"]["status"] == "rejected"
            assert all(store.get(entity_ref(item)) == item for item in projections.values())

            def arrival(label, subject):
                payload = f"Synthetic cancellation metadata for {subject}.\n".encode("utf-8")
                observation = record("observation", label, {
                    "source_identity": {"namespace": SOURCE_NAMESPACE, "event_id": "previously-unknown-event-" + label},
                    "content": {"digest": source_digest(payload), "byte_length": len(payload), "media_type": "text/plain",
                        "locator": {"kind": "whole_artifact", "uri": "urn:example:notice:" + label},
                        "availability": {"status": "available", "checked_at": T3}},
                    "occurred_at": T1, "source_published_at": T1, "available_at": T3,
                    "ingested_at": T3, "extraction": ADAPTER,
                }, origin="source")
                observation["extensions"] = {"example:notice": domain({"subject_key": subject,
                                                                          "event_kind": "cancellation"}, ADAPTER)}
                command = intake.prepare(envelope("ingest-" + label, "ingest_observation", {"observation": observation}))
                result = intake.ingest(command, payload=payload)
                assert result.get("outcome") == "committed", result
                return store.get(result["body"]["observation"]), command, result

            arrival("unrelated-new-id", "permit-B")
            assert store.get(entity_ref(watch)) == watch
            cancellation, prepared, result = arrival("unpredicted-new-id", "permit-A")
            invalidated = store.get(entity_ref(watch))
            assert invalidated["value"]["value"]["status"] == "invalidated"
            assert invalidated["value"]["value"]["matches"] == [pin(cancellation)]
            assert any(change["cause"] == "negative_scope_arrival" and pin(invalidated) in change["after"]
                       for change in result["body"]["changes"])
            assert intake.ingest(prepared) == result
            redelivery = deepcopy(prepared)
            redelivery.update(command_id="new-delivery", idempotency_key="request-new-delivery", expected_revisions=[])
            redelivery["body"]["observation"]["id"] = "unused-new-proposed-id"
            duplicate = intake.ingest(intake.prepare(redelivery))
            assert duplicate.get("outcome") == "duplicate", duplicate
            assert not duplicate["body"].get("changes")
            assert store.get(entity_ref(watch)) == invalidated
            assert len(store.history(entity_ref(watch))) == 2

            # Explicit host temporal packets make no field-name inference. This
            # demonstration declares cancellation applicability separately from
            # the immutable observation's occurred/available timestamps.
            packets = [{"reference": pin(cancellation), "available_at": T3,
                        "effective": {"start": T1, "end": T4, "bounds": "closed_open"}}]
            yesterday = select_knowledge(packets, as_of=T2)
            assert yesterday["included"] == [] and yesterday["excluded"][0]["reason"] == "not_yet_available"
            assert select_knowledge(packets, as_of=T3)["included"] == [pin(cancellation)]
            assert select_effective(packets, effective_at=T1, as_of=T2)["included"] == []
            assert select_effective(packets, effective_at=T1, as_of=T3)["included"] == [pin(cancellation)]
            assert select_knowledge(packets, as_of=T2) == yesterday
            today = publish("today-after-late-discovery", narrow, previous=empty, as_of=T3)
            assert today["value"]["value"]["result"] == "evidence_present"
            assert today["value"]["value"]["matches"] == [pin(cancellation)]
            assert store.get(pin(empty)) == empty
            assert empty["value"]["value"]["matches"] == []
            assert intake.read_payload(pin(cancellation)).status == "available"
    print("Time, coverage, scoped replacement and negative watches passed.")


if __name__ == "__main__":
    main()
