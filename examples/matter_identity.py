"""Run the installed MAT-005 API with synthetic, host-authorized inputs only."""

from copy import deepcopy
from pathlib import Path
import tempfile

from matter.canonical import source_digest
from matter.identity_keys import ExactIdentityPolicy, identity_key_ref, new_matter_id
from matter.matters import MatterService
from matter.storage import SQLiteStore, entity_ref


SCOPE = "synthetic:matter-identity-example"
KEYS = [{"namespace": "example:subject", "value": "opportunity-17"}]
POLICY = ExactIdentityPolicy(key_namespaces=["example:subject"])
PRODUCER = {
    "namespace": "example", "id": "synthetic-host", "version": "1.0",
    "digest": source_digest(b"Synthetic MAT-005 identity example producer v1"),
}


def envelope(label, operation, body):
    return {
        "schema_version": "1.0", "operation": operation,
        "command_id": f"command-{label}", "idempotency_key": f"request-{label}",
        "scope_id": SCOPE,
        "actor": {"scope_id": SCOPE, "namespace": "example", "id": "host"},
        "authority": {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "synthetic-authority"},
        "expected_revisions": [], "body": body,
    }


def creation(label, run_id, title):
    return envelope(label, "create_matter", {
        "matter": {
            "schema_version": "1.0", "record_type": "matter", "scope_id": SCOPE,
            "namespace": "example", "id": new_matter_id(),
            "provenance": {
                "origin": "host", "producer": deepcopy(PRODUCER), "run_id": run_id,
                "recorded_at": {"state": "known", "value": "2026-10-08T18:00:00Z", "precision": "second"},
                "parents": [],
            },
            "body": {"domain_kind": "example:opportunity", "identity_keys": deepcopy(KEYS), "title": title},
        },
        "identity_policy": POLICY.reference,
    })


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "matter.sqlite"
        with SQLiteStore(database, scope_id=SCOPE) as store:
            service = MatterService(store, identity_policy=POLICY)
            prepared = service.prepare(creation("first", "run-1", "A continuing opportunity"))
            created = service.create(prepared)
            assert created["outcome"] == "created", created
            original = store.get(created["body"]["matter"])

        with SQLiteStore(database, scope_id=SCOPE) as store:
            service = MatterService(store, identity_policy=POLICY)
            later = service.prepare(creation("later", "run-2", "A new proposed title"))
            existing = service.create(later)
            assert existing["outcome"] == "existing", existing
            assert existing["body"]["matter"] == created["body"]["matter"]
            assert service.resolve(KEYS) == original
            assert existing["receipt"] != created["receipt"]

            edit = service.prepare(envelope("edit", "update_matter_metadata", {
                "matter": created["body"]["matter"],
                "metadata": {"title": "The opportunity, clarified", "description": "New wording for the same continuing subject."},
            }))
            updated = service.update_metadata(edit)
            assert updated["outcome"] == "updated", updated
            current = service.resolve(KEYS, domain_kind="example:opportunity")
            assert current["id"] == original["id"]
            assert current["revision"] == 2
            assert current["provenance"] == original["provenance"]
            assert current["creation_receipt"] == original["creation_receipt"]
            assert store.history(entity_ref(current)) == [original, current]
            assert store.get(identity_key_ref(SCOPE, KEYS[0]))["revision"] == 1
            assert service.create(prepared) == created
            assert service.update_metadata(edit) == updated
            backup = store.backup_to(root / "backup.sqlite")

        with SQLiteStore(database, scope_id="synthetic:another-scope") as store:
            assert MatterService(store, identity_policy=POLICY).resolve(KEYS) is None

        with SQLiteStore.restore_from(backup, root / "restored.sqlite", scope_id=SCOPE) as store:
            restored = MatterService(store, identity_policy=POLICY)
            assert restored.resolve(KEYS) == current
            assert restored.create(prepared) == created
            assert restored.update_metadata(edit) == updated
        print("Persistent matter identity example passed: restart, exact keys, metadata history, scope, retry, and restore.")


if __name__ == "__main__":
    main()
