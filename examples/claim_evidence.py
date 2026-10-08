"""Run scoped claims and exact citations through the installed MAT-007 API.

All inputs are synthetic host declarations. The example preserves a forecast,
its qualification, a later correction and citation acceptance history without
establishing an outcome or changing the continuing matter.
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from matter.canonical import source_digest
from matter.citations import Utf8LineLocatorAdapter, line_selector
from matter.claims import ClaimService
from matter.evidence_relations import EvidenceRelationService
from matter.identity_keys import ExactIdentityPolicy
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, entity_ref, pin


SCOPE = "synthetic:claim-example"
TIME = {"state": "known", "value": "2026-10-08T19:00:00Z", "precision": "second"}
UNKNOWN = {"state": "unknown", "reason": "not_reported"}
INTERVAL = {"start": deepcopy(UNKNOWN), "end": deepcopy(UNKNOWN), "bounds": "closed"}
PRODUCER = {
    "namespace": "example", "id": "synthetic-claim-host", "version": "1.0",
    "digest": source_digest(b"Synthetic MAT-007 claim and citation example v1"),
}
SOURCE = (b"Funding is expected next year, subject to approval.\n"
          b"No allocation has been approved.\n")
KEYS = [{"namespace": "example:subject", "value": "funding-opportunity"}]


def envelope(label, operation, body):
    return {
        "schema_version": "1.0", "operation": operation, "scope_id": SCOPE,
        "command_id": f"command-{label}", "idempotency_key": f"request-{label}",
        "actor": {"scope_id": SCOPE, "namespace": "example", "id": "host"},
        "authority": {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "synthetic-host-grant"},
        "expected_revisions": [], "body": body,
    }


def provenance(origin="host", parents=()):
    return {"origin": origin, "producer": deepcopy(PRODUCER), "recorded_at": deepcopy(TIME), "parents": deepcopy(list(parents))}


def record(kind, label, body, *, origin="host", parents=()):
    return {
        "schema_version": "1.0", "record_type": kind, "scope_id": SCOPE,
        "namespace": "example", "id": f"{kind}-{label}",
        "provenance": provenance(origin, parents), "body": body,
    }


def domain(value):
    return {"schema": deepcopy(PRODUCER), "value": deepcopy(value)}


def observe(intake):
    observation = record("observation", "forecast", {
        "source_identity": {"namespace": "example:reports", "event_id": "forecast-1"},
        "content": {
            "digest": source_digest(SOURCE), "byte_length": len(SOURCE), "media_type": "text/plain",
            "locator": {"kind": "whole_artifact", "uri": "urn:example:forecast-source"},
            "availability": {"status": "available", "checked_at": deepcopy(TIME)},
        },
        "occurred_at": deepcopy(UNKNOWN), "source_published_at": deepcopy(TIME),
        "available_at": deepcopy(TIME), "ingested_at": deepcopy(TIME), "extraction": deepcopy(PRODUCER),
    }, origin="source")
    command = intake.prepare(envelope("source", "ingest_observation", {"observation": observation}))
    result = intake.ingest(command, payload=SOURCE)
    assert result["status"] == "success", result
    return result["body"]["observation"]


def claim_input(label, subject, evidence, *, version="1", wording="Funding is forecast, conditional on approval."):
    return record("claim", label, {
        "subject": entity_ref(subject), "predicate": "example:funding-forecast",
        "value": domain(wording), "qualifiers": [domain("Approval remains a condition.")],
        "applicability": deepcopy(INTERVAL), "attribution": [deepcopy(evidence)],
        "proposition_version": version,
        "components": {
            "example:funding": domain("Funding is under discussion."),
            "example:timing": domain("Next year, conditional on approval."),
        },
    }, parents=[evidence])


def relation_input(label, claim, evidence, kind, component, *, whole=False, quote="Funding is expected next year"):
    locator = {"kind": "whole_artifact", "uri": "urn:example:forecast-source"}
    if not whole:
        locator.update(kind="selected_span", selector=line_selector(1, 1))
    body = {
        "claim": deepcopy(claim), "evidence": deepcopy(evidence), "relation": kind,
        "target": {"kind": "component", "component": component},
        "locator": locator, "applicability": deepcopy(INTERVAL),
        "acceptance": {"status": "proposed", "rationale": "Synthetic scoped relation awaiting host acceptance."},
    }
    if not whole:
        body["quotation"] = quote
    return record("evidence_relation", label, body, parents=[evidence, claim])


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payloads = FilePayloadStore(root / "payloads", scope_id=SCOPE)
        adapter = Utf8LineLocatorAdapter(payloads)
        policy = ExactIdentityPolicy(key_namespaces=["example:subject"])
        with SQLiteStore(root / "matter.sqlite", scope_id=SCOPE) as store:
            matters = MatterService(store, identity_policy=policy)
            proposed_matter = record("matter", "opportunity", {
                "domain_kind": "example:opportunity", "identity_keys": deepcopy(KEYS),
                "title": "A synthetic funding opportunity",
            })
            created = matters.create(matters.prepare(envelope("subject", "create_matter", {
                "matter": proposed_matter, "identity_policy": policy.reference,
            })))
            assert created["outcome"] == "created", created
            subject = store.get(created["body"]["matter"])
            intake = ObservationIngestor(store, payloads)
            evidence = observe(intake)
            claims = ClaimService(store)
            relations = EvidenceRelationService(store, locator_adapter=adapter)
            initial_command = claims.prepare(envelope("forecast", "append_claim", {
                "claim": claim_input("forecast", subject, evidence),
            }))
            initial_result = claims.append(initial_command)
            assert initial_result["outcome"] == "appended", initial_result
            claim = initial_result["body"]["claim"]

            saved_relations = []
            for label, kind, component in (
                ("support", "supports", "example:funding"),
                ("qualification", "qualifies", "example:timing"),
            ):
                command = relations.prepare(envelope(label, "relate_evidence", {
                    "relation": relation_input(label, claim, evidence, kind, component),
                }))
                result = relations.relate(command)
                assert result["outcome"] == "appended", result
                receipt = store.get(result["body"]["locator_validation"])
                assert receipt["body"]["details"]["value"]["result"]["kind"] == "exact_passage"
                saved_relations.append(store.get(result["body"]["relation"]))
            assert {item["body"]["relation"] for item in relations.for_claim(claim)} == {"supports", "qualifies"}

            whole = relations.relate(relations.prepare(envelope("whole", "relate_evidence", {
                "relation": relation_input("whole", claim, evidence, "context_only", "example:funding", whole=True),
            })))
            assert whole["outcome"] == "appended", whole
            whole_receipt = store.get(whole["body"]["locator_validation"])
            assert whole_receipt["body"]["details"]["value"]["result"]["kind"] == "whole_artifact"

            bad = relations.prepare(envelope("bad-quote", "relate_evidence", {
                "relation": relation_input("bad-quote", claim, evidence, "supports", "example:funding", quote="No allocation has been approved."),
            }))
            refused = relations.relate(bad)
            assert refused["status"] == "failure" and refused["error"]["code"] == "E_EVIDENCE_INVALID", refused
            assert store.command_receipt(bad["idempotency_key"])["command"]["body"]["validation"]["value"]["result"]["reason"] == "quotation_absent_from_selected_lines"

            support = saved_relations[0]
            acceptance = envelope("accept", "revise_evidence_acceptance", {
                "relation": pin(support),
                "acceptance": {"status": "accepted", "rationale": "Host accepts this citation's narrow support relation."},
            })
            acceptance["body"]["acceptance"]["authority"] = deepcopy(acceptance["authority"])
            accepted = relations.revise_acceptance(relations.prepare(acceptance))
            assert accepted["outcome"] == "updated", accepted
            current = store.get(accepted["body"]["relation"])
            assert current["body"]["locator_validation"] == support["body"]["locator_validation"]
            assert relations.history(entity_ref(support)) == [support, current]

            corrected = claim_input("correction", subject, evidence, version="2", wording="The earlier forecast is withdrawn; no outcome is established.")
            corrected["supersedes"] = [deepcopy(claim)]
            correction = claims.append(claims.prepare(envelope("correct", "append_claim", {"claim": corrected})))
            assert correction["outcome"] == "appended", correction
            assert correction["body"]["changes"][0]["cause"] == "evidence_correction"
            assert len(claims.revisions(claim)) == 2
            assert claims.heads(claim)[0]["id"] == corrected["id"]
            assert len(relations.for_claim(claim)) == 3  # Original citation scopes remain intact.
            assert relations.for_claim(correction["body"]["claim"]) == []  # Support does not migrate to another proposition.
            assert matters.resolve(KEYS) == subject
            assert intake.read_payload(evidence).data == SOURCE
            assert claims.append(initial_command) == initial_result
            backup = store.backup_to(root / "backup.sqlite")

        with SQLiteStore.restore_from(backup, root / "restored.sqlite", scope_id=SCOPE) as restored:
            assert len(ClaimService(restored).revisions(claim)) == 2
            service = EvidenceRelationService(restored, locator_adapter=adapter)
            assert service.history(entity_ref(support)) == [support, current]
            assert restored.get(entity_ref(subject)) == subject
            assert ClaimService(restored).append(initial_command) == initial_result
    print("Claim/evidence example passed: scoped support and qualification, exact and whole citations, explicit refusal, immutable correction, acceptance history, unchanged matter, retry, and restore.")


if __name__ == "__main__":
    main()
