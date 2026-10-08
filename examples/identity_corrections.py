"""Installed MAT-009 example with synthetic host decisions and source evidence.

The incomplete assessment is a host fixture proving historical identity and
validity storage. It does not run an evaluator or establish real equivalence.
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from matter.canonical import source_digest
from matter.claims import ClaimService
from matter.identity_corrections import IdentityCorrectionService, MergePolicy
from matter.identity_dependencies import (
    dependency_ref, register_identity_dependency, require_current_identity_dependency,
)
from matter.identity_keys import ExactIdentityPolicy
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.relations import RelationPolicy, RelationRule, RelationService
from matter.storage import SQLiteStore, StorageError, entity_ref, pin


SCOPE = "synthetic:identity-corrections-example"
TIME = {"state": "known", "value": "2026-10-08T21:00:00Z", "precision": "second"}
UNKNOWN = {"state": "unknown", "reason": "not_reported"}
HOST = {"namespace": "example", "id": "identity-host", "version": "1.0",
        "digest": source_digest(b"Synthetic MAT-009 identity correction host v1")}
ACTOR = {"scope_id": SCOPE, "namespace": "example", "id": "reviewer"}
AUTHORITY = {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "host-grant"}
PAYLOAD = b"Synthetic report: two catalog descriptions concern a subject under review.\n"


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


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        payloads = FilePayloadStore(root / "payloads", scope_id=SCOPE)
        with SQLiteStore(root / "matter.sqlite", scope_id=SCOPE) as store:
            bootstrap = envelope("bootstrap", "create_matter", {"identity_policy": HOST, "matter": record("matter", "host-setup", {
                "domain_kind": "example:host-setup", "identity_keys": [{"namespace": "example:bootstrap", "value": "host-setup"}],
            })})

            def trusted_setup(tx):
                tx.insert(record("receipt", "host-grant", {
                    "stage": "authority", "operation_id": "bootstrap", "recorded_at": TIME,
                    "outcome": "example:host_grant", "evidence": [],
                    "details": domain("Synthetic host admission; no authentication-provider claim."),
                }))
                matter = tx.insert(tx.command["body"]["matter"])
                return tx.success("created", {"matter": pin(matter)})

            assert store.execute(bootstrap, trusted_setup)["outcome"] == "created"
            authority = store.get(AUTHORITY)
            key_policy = ExactIdentityPolicy(key_namespaces=["example:subject"])
            matters = MatterService(store, identity_policy=key_policy)
            policy = MergePolicy(SCOPE, actors=[ACTOR], authorities=[pin(authority)], allow_correction=True)
            identities = IdentityCorrectionService(store, policy=policy)
            originals = []
            for label in ("a", "b", "c"):
                command = envelope("create-" + label, "create_matter", {
                    "matter": record("matter", label, {"domain_kind": "example:question", "title": "Description " + label,
                        "identity_keys": [{"namespace": "example:subject", "value": label}]}),
                    "identity_policy": key_policy.reference,
                })
                result = matters.create(matters.prepare(command))
                assert result["outcome"] == "created", result
                originals.append(store.get(result["body"]["matter"]))
            a, b, c = originals
            intake = ObservationIngestor(store, payloads)
            observation = record("observation", "report", {
                "source_identity": {"namespace": "example:reports", "event_id": "report-1"},
                "content": {"digest": source_digest(PAYLOAD), "byte_length": len(PAYLOAD), "media_type": "text/plain",
                    "locator": {"kind": "whole_artifact", "uri": "urn:example:identity-report"},
                    "availability": {"status": "available", "checked_at": TIME}},
                "occurred_at": UNKNOWN, "source_published_at": TIME, "available_at": TIME,
                "ingested_at": TIME, "extraction": HOST,
            }, origin="source")
            result = intake.ingest(intake.prepare(envelope("report", "ingest_observation", {"observation": observation})), payload=PAYLOAD)
            assert result["status"] == "success", result
            source = result["body"]["observation"]

            # This host rule deliberately permits a related-to self projection;
            # a depends-on rule would normally prohibit self links and cycles.
            related = RelationRule("example:related_to", namespace="example", id="related-to",
                                   directed=False, allow_self=True, acyclic=False)
            links = RelationService(store, policy=RelationPolicy(SCOPE, actors=[ACTOR],
                authorities=[pin(authority)], rules=[related]))
            for label, first, second in (("a-b", a, b), ("b-c", b, c)):
                result = links.link(links.prepare(envelope("link-" + label, "link_matters", {
                    "from_matter": pin(first), "to_matter": pin(second), "relation_kind": related.definition["kind"],
                    "relationship_schema": related.reference, "basis": [source],
                })))
                assert result["outcome"] == "linked", result
            assert [identities.resolve(item)["id"] for item in originals] == ["a", "b", "c"]
            claims = ClaimService(store)
            assertions = []
            for target, value in ((a, "reported active"), (b, "reported inactive")):
                claim = record("claim", "claim-" + target["id"], {
                    "subject": entity_ref(target), "predicate": "example:reported_state", "value": domain(value),
                    "qualifiers": [], "applicability": {"start": UNKNOWN, "end": UNKNOWN, "bounds": "closed_open"},
                    "attribution": [source], "proposition_version": "1.0",
                }, origin="source")
                result = claims.append(claims.prepare(envelope("append-" + target["id"], "append_claim", {"claim": claim})))
                assert result["outcome"] == "appended", result
                assertions.append(store.get(result["body"]["claim"]))

            def merge_command(label, survivor, losing):
                return envelope(label, "merge_matters", {"survivor": pin(store.get(entity_ref(survivor))),
                    "merged": [pin(store.get(entity_ref(item))) for item in losing],
                    "equivalence_basis": [source], "merge_policy": policy.reference, "as_of": TIME})

            prepared = identities.prepare(merge_command("merge-a-b", a, [b]))
            merged = identities.merge(prepared)
            assert merged["outcome"] == "committed", merged
            assert identities.resolve(b)["id"] == "a"
            assert matters.resolve(b["body"]["identity_keys"])["id"] == "a"
            history = identities.historical_view(merged["body"]["merge_receipt"])
            assert any(item["kind"] == "overlapping_claims" for item in history["conflicts"])
            assert all(store.get(pin(claim)) == claim for claim in assertions)
            view = identities.view(a)
            dependencies = view["members"] + view["indexes"] + [merged["body"]["merge_receipt"]]
            manifest = {"positive": dependencies, "negative": [], "time_conditions": [], "context": [], "control_epoch": 0}
            assessment = record("assessment", "historical-understanding", {
                "matter": view["survivor"], "profile": HOST, "purpose": HOST, "assessed_as_of": TIME,
                "dependency_manifest": manifest, "judgments": [], "propositions": [],
                "causes": ["association_correction"], "evaluation_state": "incomplete", "proposals": [],
                "limitations": ["Synthetic incomplete host fixture; no assessment engine was run."],
                "input_artifact": {"state": "unavailable", "reason": "not_recorded"},
                "evidence_selection": {"references": [source], "omitted": [], "coverage": {"status": "complete", "snapshot": HOST}},
                "resource_use": domain({"calls": 0}), "stop_reason": "incomplete", "consequences": [],
                "material_changes": [], "evidence_gaps": [],
            })
            host_command = envelope("record-incomplete-assessment", "commit_assessment", {
                "assessment": assessment})
            host_command["expected_revisions"] = view["read_set"]

            def trusted_assessment_fixture(tx):
                stored = tx.insert(tx.command["body"]["assessment"])
                register_identity_dependency(tx, pin(stored), matters=view["members"])
                return tx.success("committed", {"assessment": pin(stored)})

            assessed = store.execute(host_command, trusted_assessment_fixture)
            assert assessed["outcome"] == "committed", assessed
            validity = dependency_ref(assessed["body"]["assessment"])
            correction = envelope("undo-a-b", "correct_merge", {
                "merge_receipt": merged["body"]["merge_receipt"], "correction_kind": "undo",
                "partitions": identities.plan_correction(merged["body"]["merge_receipt"]), "basis": [source], "as_of": TIME})
            corrected = identities.correct(identities.prepare(correction))
            assert corrected["outcome"] == "committed", corrected
            assert identities.resolve(a)["id"] == "a" and identities.resolve(b)["id"] == "b"
            assert store.get(validity)["value"]["value"]["status"] == "invalidated"
            with store.snapshot() as snapshot:
                try:
                    require_current_identity_dependency(snapshot, SCOPE, validity)
                except StorageError as error:
                    assert error.code == "E_DEPENDENCY_STALE", error
                else:
                    raise AssertionError("An identity correction left old derived work current.")
            assert identities.historical_view(merged["body"]["merge_receipt"]) == history
            assert identities.merge(prepared) == merged
            assert identities.resolve(b)["id"] == "b"
            assert identities.merge(identities.prepare(merge_command("merge-a-c", c, [a])))["outcome"] == "committed"
            try:
                identities.prepare(merge_command("forbidden-indirect-remerge", c, [b]))
            except StorageError as error:
                assert error.code == "E_MERGE_CONFLICT", error
            else:
                raise AssertionError("A new survivor bypassed the protected original pair.")
            barrier = identities.view(a)["protections"][0]
            release_command = identities.prepare(envelope("release-reviewed-separation", "release_identity_separations", {
                "separations": [barrier], "basis": [source], "reason": "Synthetic host review corrects the earlier separation decision.",
                "merge_policy": policy.reference, "as_of": TIME,
            }))
            released = identities.release_separations(release_command)
            assert released["outcome"] == "released", released
            assert identities.resolve(a)["id"] == "c" and identities.resolve(b)["id"] == "b"
            approved_merge = identities.merge(identities.prepare(merge_command("fresh-merge-after-release", c, [b])))
            assert approved_merge["outcome"] == "committed", approved_merge
            recheck = envelope("correct-reviewed-merge", "correct_merge", {
                "merge_receipt": approved_merge["body"]["merge_receipt"], "correction_kind": "undo",
                "partitions": identities.plan_correction(approved_merge["body"]["merge_receipt"]), "basis": [source], "as_of": TIME,
            })
            assert identities.correct(identities.prepare(recheck))["outcome"] == "committed"
            assert [item["value"]["value"]["status"] for item in identities.separation_history(barrier)] == [
                "protected", "released", "protected"]
            assert identities.release_separations(release_command) == released
            assert store.get(entity_ref(barrier))["value"]["value"]["status"] == "protected"
            assert all(store.get(pin(claim)) == claim for claim in assertions)
            assert intake.read_payload(source).data == PAYLOAD
            backup = store.backup_to(root / "corrected-backup.sqlite")
        with SQLiteStore.restore_from(backup, root / "restored.sqlite", scope_id=SCOPE) as restored:
            identities = IdentityCorrectionService(restored, policy=policy)
            assert identities.merge(prepared) == merged
            assert identities.resolve(a)["id"] == "c" and identities.resolve(b)["id"] == "b"
            assert identities.historical_view(merged["body"]["merge_receipt"]) == history
    print("Identity correction example passed: typed links, complete merges, retained conflicts and evidence, historical assessment, atomic invalidation, protected undo, indirect remerge refusal, explicit release and re-protection, exact replay, and restore.")


if __name__ == "__main__":
    main()
