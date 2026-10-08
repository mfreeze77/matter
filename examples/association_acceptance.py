"""Synthetic MAT-008 proposal, currentness and protected-decision walkthrough.

The explicit catalog is supplied by a trusted host, not a search provider.
Bootstrap authority below is a local host transaction, not authentication or
authority inferred from the observation. Run with the installed Matter wheel.
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from matter.associations import AssociationPolicy, AssociationService
from matter.candidate_sets import exact_candidates
from matter.canonical import source_digest
from matter.identity_keys import ExactIdentityPolicy
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin


SCOPE = "synthetic:association-example"
TIME = {"state": "known", "value": "2026-10-08T20:00:00Z", "precision": "second"}
UNKNOWN = {"state": "unknown", "reason": "not_reported"}
HOST = {"namespace": "example", "id": "association-host", "version": "1.0",
        "digest": source_digest(b"Synthetic MAT-008 host catalog and review v1")}
RULE = {**HOST, "id": "any-exact-declared-key"}
RELATION = {**HOST, "id": "attachment"}
ACTOR = {"scope_id": SCOPE, "namespace": "example", "id": "reviewer"}
AUTHORITY = {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "host-grant"}
KEY = {"namespace": "example:catalog", "value": "reported-subject"}
PAYLOAD = b"Synthetic report about an initially unassigned continuing matter.\n"


def domain(value):
    return {"schema": deepcopy(HOST), "value": deepcopy(value)}


def envelope(label, operation, body):
    return {"schema_version": "1.0", "scope_id": SCOPE, "operation": operation,
            "command_id": label, "idempotency_key": "request-" + label,
            "actor": deepcopy(ACTOR), "authority": deepcopy(AUTHORITY),
            "expected_revisions": [], "body": deepcopy(body)}


def record(kind, label, body, *, origin="host"):
    return {"schema_version": "1.0", "scope_id": SCOPE, "namespace": "example",
            "record_type": kind, "id": label,
            "provenance": {"origin": origin, "producer": deepcopy(HOST), "recorded_at": deepcopy(TIME), "parents": []},
            "body": deepcopy(body)}


def expect_failure(result, code):
    assert result["status"] == "failure" and result["error"]["code"] == code, result


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payloads = FilePayloadStore(root / "payloads", scope_id=SCOPE)
        with SQLiteStore(root / "matter.sqlite", scope_id=SCOPE) as store:
            bootstrap = envelope("bootstrap", "create_matter", {"identity_policy": HOST, "matter": record("matter", "host-setup", {
                "domain_kind": "example:host-setup", "title": "Synthetic setup",
                "identity_keys": [{"namespace": "example:bootstrap", "value": "host-setup"}],
            })})

            def trusted_setup(tx):
                tx.insert(record("receipt", "host-grant", {
                    "stage": "authority", "operation_id": "bootstrap", "recorded_at": TIME,
                    "outcome": "example:host_grant", "evidence": [],
                    "details": domain("Synthetic host configuration; no identity-provider claim."),
                }))
                created = tx.insert(tx.command["body"]["matter"])
                return tx.success("created", {"matter": pin(created)})

            result = store.execute(bootstrap, trusted_setup)
            assert result["outcome"] == "created", result
            authority = store.get(AUTHORITY)
            policy = AssociationPolicy(SCOPE, actors=[ACTOR], authorities=[pin(authority)],
                matching_rules=[RULE], relations=[RELATION], allow_correction=True)
            service = AssociationService(store, policy=policy)
            identities = ExactIdentityPolicy(key_namespaces=["example:subject"])
            matters = MatterService(store, identity_policy=identities)
            originals = []
            for label in ("candidate-a", "candidate-b"):
                created = matters.create(matters.prepare(envelope(label, "create_matter", {
                    "matter": record("matter", label, {"domain_kind": "example:subject", "title": label,
                        "identity_keys": [{"namespace": "example:subject", "value": label}]}),
                    "identity_policy": identities.reference,
                })))
                assert created["outcome"] == "created", created
                originals.append(store.get(created["body"]["matter"]))
            intake = ObservationIngestor(store, payloads)
            observation = record("observation", "report", {
                "source_identity": {"namespace": "example:reports", "event_id": "report-1"},
                "content": {"digest": source_digest(PAYLOAD), "byte_length": len(PAYLOAD), "media_type": "text/plain",
                    "locator": {"kind": "whole_artifact", "uri": "urn:example:association-report"},
                    "availability": {"status": "available", "checked_at": TIME}},
                "occurred_at": UNKNOWN, "source_published_at": TIME, "available_at": TIME,
                "ingested_at": TIME, "extraction": HOST,
            }, origin="source")
            ingested = intake.ingest(intake.prepare(envelope("report", "ingest_observation", {"observation": observation})), payload=PAYLOAD)
            assert ingested["status"] == "success", ingested
            subject = ingested["body"]["observation"]
            query = {"source": HOST, "subject": entity_ref(subject), "candidate_type": "matter", "mode": "exact_keys",
                     "matching_rule": RULE, "selector": domain("This explicit host catalog only."), "keys": [KEY]}

            def publish(label, candidates, previous=None):
                entries = [{"candidate": pin(item), "keys": [KEY], "basis": [subject]} for item in candidates]
                result = service.publish_candidates(service.prepare(envelope(label, "publish_association_candidates", {
                    "query": query, "entries": entries, "coverage": {"status": "complete", "snapshot": HOST},
                    "evidence": [subject], "as_of": TIME, "previous": previous,
                })))
                assert result["outcome"] == "published", result
                return result["body"]["candidate_set"]

            def propose(label, candidate_set):
                result = service.propose(service.prepare(envelope(label, "propose_association", {
                    "subject": subject, "candidate_set": candidate_set,
                    "candidates": exact_candidates(store.get(candidate_set)), "matching_rule": RULE,
                    "evidence": [subject], "assessed_as_of": TIME,
                })))
                assert result["status"] == "success", result
                return result

            def acceptance(label, proposal, candidate_set):
                stored = store.get(proposal)
                return envelope(label, "accept_association", {
                    "proposal": proposal, "candidate_set": candidate_set,
                    "candidates": [item["candidate"] for item in stored["body"]["candidates"]],
                    "acceptance_policy": policy.reference, "relation": RELATION, "capability": "attach", "as_of": TIME,
                })

            def decide(label, kind, previous=None, capability="attach"):
                result = service.decide(service.prepare(envelope(label, "decide_association", {
                    "subject": subject, "target": pin(originals[0]), "relation": RELATION, "capability": capability,
                    "decision": kind, "previous": previous, "reason": "Explicit synthetic host review.",
                    "as_of": TIME, "acceptance_policy": policy.reference,
                })))
                assert result["outcome"] == "applied", result
                return result["body"]["disposition"]

            empty = publish("empty-catalog", [])
            assert propose("no-match", empty)["outcome"] == "no_match"
            unique = publish("unique-catalog", originals[:1], empty)
            first = propose("first-proposal", unique)
            assert first["outcome"] == "proposal" and service.for_subject(subject) == []
            stale = service.prepare(acceptance("stale-accept", first["body"]["proposal"], unique))
            expanded = publish("expanded-catalog", originals, unique)
            expect_failure(service.accept(stale), "E_REVISION_CONFLICT")
            assert propose("two-alternatives", expanded)["outcome"] == "ambiguous"

            # The host explicitly corrects its bounded packet. No model result
            # edits this registry, matter identifiers or source evidence.
            corrected = publish("corrected-catalog", originals[:1], expanded)
            proposal = propose("reviewed-proposal", corrected)["body"]["proposal"]
            decide("nonmerge-protection", "protect", capability="merge")
            accepted_command = service.prepare(acceptance("host-accept", proposal, corrected))
            accepted = service.accept(accepted_command)
            assert accepted["outcome"] == "accepted", accepted
            edge = accepted["body"]["association"]
            assert len(service.for_subject(subject, status="active")) == 1
            denied_merge = acceptance("forbidden-merge", proposal, corrected)
            denied_merge["body"]["capability"] = "merge"
            denied_merge["expected_revisions"] = deepcopy(accepted_command["expected_revisions"])
            expect_failure(service.accept(denied_merge), "E_AUTHORITY_REQUIRED")

            rejection = decide("reject-attachment", "reject")
            assert service.accept(accepted_command) == accepted  # Historical receipt only.
            assert service.for_subject(subject, status="active") == []
            assert [item["body"]["status"] for item in service.history(edge)] == ["active", "revoked"]
            fresh = propose("replayed-new-proposal-id", corrected)["body"]["proposal"]
            try:
                service.prepare(acceptance("still-rejected", fresh, corrected))
            except StorageError as error:
                assert error.code == "E_ASSOCIATION_CONFLICT", error
            else:
                raise AssertionError("A fresh proposal bypassed a prior rejection.")
            backup = store.backup_to(root / "rejected-backup.sqlite")
            decide("explicit-correction", "release", rejection)
            reaccepted = service.accept(service.prepare(acceptance("accept-after-correction", fresh, corrected)))
            assert reaccepted["outcome"] == "accepted", reaccepted
            assert [item["body"]["status"] for item in service.history(edge)] == ["active", "revoked", "active"]
            assert all(store.get(entity_ref(item)) == item for item in originals)
            assert intake.read_payload(subject).data == PAYLOAD

        with SQLiteStore.restore_from(backup, root / "restored.sqlite", scope_id=SCOPE) as restored:
            service = AssociationService(restored, policy=policy)
            assert service.for_subject(subject, status="active") == []
            assert service.disposition(subject, originals[0], RELATION)["value"]["value"]["status"] == "blocked"
            assert service.accept(accepted_command) == accepted
            assert all(restored.get(entity_ref(item)) == item for item in originals)
    print("Association example passed: durable proposals, distinct outcomes, stale-catalog refusal, scoped host acceptance, nonmerge protection, rejection, replay barrier, explicit correction, unchanged identities, and restore.")


if __name__ == "__main__":
    main()
