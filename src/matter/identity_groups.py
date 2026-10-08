"""Verified flat identity groups with original matter records kept intact.

Every member has a mirror of the complete current partition and its direct
survivor. Missing mirrors mean untouched singletons; redirects never chain.
Keys and child endpoints remain anchored to their original matter identities.
Only an authorized identity-correction handler should call ``write_groups``;
this module checks partition integrity, not equivalence or host permission.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from .canonical import CanonicalError, canonical_bytes, canonical_digest, source_digest
from .contracts import schema_for, validate_record
from .storage import PROJECTION_TYPE, Snapshot, StorageError, Transaction, entity_ref, pin, snapshot_digest
from .storage.base import _validate_fragment, _validate_projection


GROUP_NAMESPACE = "matter.identity_groups"
MAX_GROUP_MEMBERS = 4096

__all__ = [
    "GROUP_NAMESPACE", "MAX_GROUP_MEMBERS", "group_ref", "group_schema_ref",
    "group_value", "read_group", "write_groups", "resolve_matter",
]


def _invalid() -> StorageError:
    return StorageError("E_EVIDENCE_INVALID", "The persistent matter identity group could not be verified.")


def _identity(value):
    return value["scope_id"], value["namespace"], value["id"]


def _sort(records):
    return sorted(records, key=lambda value: canonical_bytes(entity_ref(value)))


def _matter_reference(value):
    fragment = "matter_dependency" if type(value) is dict and ("revision" in value or "digest" in value) else "matter_ref"
    return _validate_fragment(value, fragment)


def group_ref(matter: dict[str, Any]) -> dict[str, str]:
    """Address the mirror by original bare matter identity, never a pin."""
    reference = _validate_fragment(entity_ref(matter), "matter_ref")
    return {
        "scope_id": reference["scope_id"], "namespace": GROUP_NAMESPACE,
        "record_type": PROJECTION_TYPE,
        "id": "group-" + canonical_digest(reference, "matter.identity-group.v1"),
    }


@lru_cache(maxsize=1)
def _contract():
    try:
        data = files("matter._schemas").joinpath("identity-group.schema.json").read_bytes()
        schema = json.loads(data)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        return {
            "namespace": "matter", "id": "identity-group", "version": "1.0", "digest": source_digest(data),
        }, Draft202012Validator(schema, registry=registry)
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The installed identity-group schema is unavailable.") from None


def group_schema_ref() -> dict[str, str]:
    return deepcopy(_contract()[0])


def group_value(body: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete closed mirror, canonicalizing its membership set."""
    descriptor, validator = _contract()
    try:
        canonical_bytes(body)
    except (CanonicalError, RecursionError):
        raise StorageError("E_SCHEMA_INVALID") from None
    if not validator.is_valid(body):
        raise StorageError("E_SCHEMA_INVALID")
    value = deepcopy(body)
    references = [value["member"], value["survivor"], *value["members"], value["decision"]]
    if any(reference["scope_id"] != value["scope_id"] for reference in references):
        raise StorageError("E_SCOPE_FORBIDDEN")
    identities = {_identity(reference) for reference in value["members"]}
    if (len(identities) != len(value["members"]) or _identity(value["member"]) not in identities
            or _identity(value["survivor"]) not in identities):
        raise _invalid()
    value["members"] = sorted(value["members"], key=canonical_bytes)
    return {"schema": deepcopy(descriptor), "value": value}


def _current_matter(view, scope, reference):
    ref = _matter_reference(reference)
    if ref["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    stored = view.lookup_identity(entity_ref(ref))
    try:
        record = validate_record(stored)
        if entity_ref(record) != entity_ref(ref) or record["creation_receipt"]["scope_id"] != scope:
            raise _invalid()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    if (("revision" in ref and ref["revision"] != record["revision"])
            or ("digest" in ref and ref["digest"] != snapshot_digest(record))):
        raise StorageError("E_REVISION_CONFLICT", "The original matter revision is no longer current.")
    return record


def _mirror(view, scope, reference):
    _contract()
    target = group_ref(reference)
    try:
        stored = view.lookup_identity(target)
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise
    try:
        record = _validate_projection(stored)
        expected = group_value(record["value"]["value"])
        if (entity_ref(record) != target or record["creation_receipt"]["scope_id"] != scope
                or record["watch_keys"] or expected["value"]["scope_id"] != scope
                or expected["value"]["member"] != entity_ref(reference)
                or canonical_bytes(record["value"]) != canonical_bytes(expected)):
            raise _invalid()
        return record
    except StorageError as error:
        if error.code == "E_STORAGE_UNAVAILABLE":
            raise
        raise _invalid() from None
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def _decision(view, scope, reference):
    # The decision reader validates an immutable receipt independently of
    # current groups. Local import keeps the correction service dependency acyclic.
    from .identity_corrections import read_decision
    return read_decision(view, scope, reference)


def _bind_decision(receipt, body, indexes, members=None, *, exact=False):
    try:
        groups = receipt["body"]["details"]["value"]["after"]
        expected_members = body["members"]
        matching = [group for group in groups
                    if entity_ref(group["survivor"]) == body["survivor"]
                    and sorted((entity_ref(member) for member in group["members"]), key=canonical_bytes) == expected_members]
        if len(matching) != 1:
            raise _invalid()
        if sorted(matching[0]["indexes"], key=canonical_bytes) != sorted((pin(index) for index in indexes), key=canonical_bytes):
            raise _invalid()
        if members is not None:
            current = {_identity(member): member for member in members}
            if any(current[_identity(member)]["revision"] < member["revision"] for member in matching[0]["members"]):
                raise _invalid()
            if exact:
                expected = sorted((pin(member) for member in members), key=canonical_bytes)
                survivor = next(pin(member) for member in members if entity_ref(member) == body["survivor"])
                if sorted(matching[0]["members"], key=canonical_bytes) != expected or matching[0]["survivor"] != survivor:
                    raise _invalid()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def read_group(
    view: Snapshot | Transaction, scope_id: str, matter: dict[str, Any],
) -> dict[str, Any]:
    """Read the complete current group and every exact transactional guard.

    Supplied pins must still be current even on a historical-capable snapshot.
    Existing groups require all mirrors and their immutable decision proof.
    Missing, conflicting, or chained mirrors cannot degrade into a singleton.
    """
    scope = _validate_fragment(scope_id, "identifier")
    original = _current_matter(view, scope, matter)
    first = _mirror(view, scope, entity_ref(original))
    if first is None:
        return {"survivor": original, "members": [deepcopy(original)], "indexes": []}
    body = first["value"]["value"]
    members, indexes = [], []
    for reference in body["members"]:
        member = original if entity_ref(original) == reference else _current_matter(view, scope, reference)
        index = first if entity_ref(original) == reference else _mirror(view, scope, reference)
        if index is None:
            raise _invalid()
        expected = {**body, "member": reference}
        if canonical_bytes(index["value"]["value"]) != canonical_bytes(expected):
            raise _invalid()
        members.append(member)
        indexes.append(index)
    receipt = _decision(view, scope, body["decision"])
    _bind_decision(receipt, body, indexes, members)
    survivor = next(member for member in members if entity_ref(member) == body["survivor"])
    return deepcopy({"survivor": survivor, "members": _sort(members), "indexes": _sort(indexes)})


def resolve_matter(view: Snapshot | Transaction, scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    """Resolve a current original matter to its direct current survivor."""
    return read_group(view, scope_id, reference)["survivor"]


def write_groups(
    tx: Transaction, partitions: list[dict[str, Any]], decision: dict[str, Any],
) -> list[dict[str, Any]]:
    """Revision complete partitions atomically after host authorization.

    Each partition contains a bare survivor and complete current matter records.
    The union must include every member of every affected old group. Originals
    keep their bodies, keys, provenance, and creation receipt. Every member
    revision advances, invalidating old mutable matter dependencies. Return the
    same group structures as ``read_group``; the enclosing handler owns typed
    change notices and the immutable before/after movement manifest.
    """
    scope = tx.command["scope_id"]
    reference = _validate_fragment(decision, "receipt_dependency")
    if reference["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    if type(partitions) is not list or not partitions:
        raise StorageError("E_SCHEMA_INVALID")
    declared, all_members = [], {}
    for partition in partitions:
        if type(partition) is not dict or set(partition) != {"survivor", "members"}:
            raise StorageError("E_SCHEMA_INVALID")
        survivor = _validate_fragment(partition["survivor"], "matter_ref")
        if type(partition["members"]) is not list or not partition["members"]:
            raise StorageError("E_SCHEMA_INVALID")
        members = []
        for supplied in partition["members"]:
            record = validate_record(supplied)
            _validate_fragment(entity_ref(record), "matter_ref")
            if record["scope_id"] != scope or survivor["scope_id"] != scope:
                raise StorageError("E_SCOPE_FORBIDDEN")
            identity = _identity(record)
            if identity in all_members:
                raise StorageError("E_MERGE_CONFLICT", "Correction partitions overlap.")
            all_members[identity] = record
            members.append(record)
        if survivor not in [entity_ref(record) for record in members]:
            raise StorageError("E_MERGE_CONFLICT", "A partition survivor must belong to that partition.")
        declared.append({"survivor": survivor, "members": _sort(members)})
    if len(all_members) > MAX_GROUP_MEMBERS:
        raise StorageError("E_MERGE_CONFLICT", "The identity operation exceeds the supported member bound.")

    # Validate complete closure and exact current bodies before the first write.
    checked = set()
    for supplied in all_members.values():
        if _identity(supplied) in checked:
            continue
        group = read_group(tx, scope, pin(supplied))
        for current in group["members"]:
            identity = _identity(current)
            if identity not in all_members:
                raise StorageError("E_MERGE_CONFLICT", "Correction partitions omit current group members.")
            if canonical_bytes(current) != canonical_bytes(all_members[identity]):
                raise StorageError("E_REVISION_CONFLICT")
            checked.add(identity)
    receipt = _decision(tx, scope, reference)
    written = []
    for partition in sorted(declared, key=lambda value: canonical_bytes(value["survivor"])):
        members = []
        for original in partition["members"]:
            changed = deepcopy(original)
            changed["revision"] += 1
            members.append(tx.replace(changed))
        references = [entity_ref(member) for member in members]
        indexes = [tx.put_projection(group_ref(member), group_value({
            "scope_id": scope, "member": entity_ref(member), "survivor": partition["survivor"],
            "members": references, "decision": reference,
        })) for member in members]
        _bind_decision(receipt, indexes[0]["value"]["value"], indexes, members, exact=True)
        written.append({"survivor": next(member for member in members if entity_ref(member) == partition["survivor"]),
                        "members": members, "indexes": _sort(indexes)})
    return deepcopy(written)
