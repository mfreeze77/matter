"""Small host handlers and synthetic inputs shared by storage integration tests.

The handlers exercise generic atomic persistence. They do not implement the
future domain operations, merge semantics, evidence interpretation, or policy
authorization represented by the portable command names.
"""

from copy import deepcopy
import json
import os
from pathlib import Path

from matter.canonical import source_digest
from matter.storage import SQLiteStore, entity_ref, pin


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "contracts"
SCOPE = "synthetic:storage"
WATCH_KEY = "watch:synthetic"
CRASH_EXIT_CODE = 73


def fixture(relative):
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def _in_scope(value, scope_id):
    if isinstance(value, dict):
        return {
            key: scope_id if key == "scope_id" else _in_scope(item, scope_id)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_in_scope(item, scope_id) for item in value]
    return value


def record_input(kind, identity, *, scope_id=SCOPE):
    value = _in_scope(fixture(f"records/{kind}.json"), scope_id)
    value.pop("creation_receipt", None)
    value.pop("revision", None)
    value["id"] = identity
    if kind == "matter":
        value["body"]["identity_keys"][0]["value"] = identity
        value["body"]["title"] = f"Synthetic subject {identity}"
    elif kind == "observation":
        payload = f"Synthetic evidence for {scope_id}/{identity}".encode("utf-8")
        value["body"]["source_identity"]["event_id"] = f"event:{identity}"
        value["body"]["content"]["digest"] = source_digest(payload)
        value["body"]["content"]["byte_length"] = len(payload)
        value["body"]["content"]["locator"]["uri"] = f"urn:synthetic:evidence:{identity}"
    return value


def create_command(command_id, matter_id, *, scope_id=SCOPE,
                   expected_revisions=(), title=None, key=None):
    value = _in_scope(fixture("commands/create_matter.json"), scope_id)
    value["command_id"] = command_id
    value["idempotency_key"] = key if key is not None else f"key:{command_id}"
    value["expected_revisions"] = deepcopy(list(expected_revisions))
    value["body"]["matter"] = record_input("matter", matter_id, scope_id=scope_id)
    if title is not None:
        value["body"]["matter"]["body"]["title"] = title
    return value


def ingest_command(command_id, observation_id, *, scope_id=SCOPE,
                   expected_revisions=(), key=None):
    value = _in_scope(fixture("commands/ingest_observation.json"), scope_id)
    value["command_id"] = command_id
    value["idempotency_key"] = key if key is not None else f"key:{command_id}"
    value["expected_revisions"] = deepcopy(list(expected_revisions))
    value["body"]["observation"] = record_input("observation", observation_id, scope_id=scope_id)
    return value


def projection_ref(identity, scope_id=SCOPE):
    return {
        "scope_id": scope_id,
        "namespace": "example:projection",
        "record_type": "matter:projection",
        "id": identity,
    }


def domain_value(value):
    return {
        "schema": {
            "namespace": "example:storage", "id": "synthetic-value", "version": "1.0",
            "digest": "a" * 64,
        },
        "value": deepcopy(value),
    }


def create_matter(tx):
    stored = tx.insert(tx.command["body"]["matter"])
    return tx.success("created", {"matter": pin(stored)})


def ingest_observation(tx):
    stored = tx.insert(tx.command["body"]["observation"])
    return tx.success("committed", {"observation": pin(stored)})


def mutation_command(command_id, stored_matter, *, label, child_id, projection_id,
                     expected_revisions=None):
    expected = [pin(stored_matter)] if expected_revisions is None else expected_revisions
    value = create_command(
        command_id, stored_matter["id"], scope_id=stored_matter["scope_id"],
        expected_revisions=expected, title=label,
    )
    value["extensions"] = {
        "example:effects": domain_value({"child_id": child_id, "projection_id": projection_id}),
    }
    return value


def rewrite_with_children(tx):
    command = tx.command
    effects = command["extensions"]["example:effects"]["value"]
    current = tx.get(entity_ref(command["body"]["matter"]))
    current["revision"] += 1
    current["body"]["title"] = command["body"]["matter"]["body"]["title"]
    updated = tx.replace(current)
    tx.insert(record_input("observation", effects["child_id"], scope_id=command["scope_id"]))
    tx.put_projection(
        projection_ref(effects["projection_id"], command["scope_id"]),
        domain_value({"target": entity_ref(updated), "label": current["body"]["title"]}),
        watch_keys=(WATCH_KEY,),
    )
    return tx.success("existing", {"matter": pin(updated)})


def execute_in_child(database, command, *, crash_at=None, barrier=None, output=None):
    """Spawn-safe worker; a requested crash bypasses all Python cleanup."""
    def fault(stage):
        if stage == crash_at:
            os._exit(CRASH_EXIT_CODE)

    with SQLiteStore(database, scope_id=command["scope_id"], fault_hook=fault) as store:
        if barrier is not None:
            barrier.wait(timeout=30)
        result = store.execute(command, rewrite_with_children)
    if output is not None:
        output.put({"command_id": command["command_id"], "result": result})
