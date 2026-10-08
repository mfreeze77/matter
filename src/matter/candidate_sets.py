"""Explicit host-published candidate catalogs and exact snapshot guards.

This module does not discover records or interpret matter identity keys. The
host declares and republishes the covered candidate universe when new matching
members arrive. Any publication revision, including a nonmatching new entry,
conservatively invalidates proposals pinned to the old catalog. Acceptance also
rechecks the subject, every considered candidate, and every evidence/basis pin.
It must not silently refresh an old proposal with newer members or revisions.

Exact keys nominate entries by any identical namespace/value pair. They never
expand, rebind, normalize, or merge a continuing matter's identity. Semantic
catalog entries are an explicit eligibility packet, not proof of global search
completeness. Coverage and source descriptors remain host declarations.
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

from .canonical import canonical_bytes, canonical_digest, source_digest
from .contracts import _FORMAT_CHECKER, schema_for, validate_record
from .storage import PROJECTION_TYPE, Snapshot, StorageError, Transaction, entity_ref, pin, snapshot_digest
from .storage.base import _validate_fragment, _validate_projection


CANDIDATE_NAMESPACE = "matter.association_candidates"
INDEX_NAMESPACE = CANDIDATE_NAMESPACE
_MEMBERS = {"observation", "occurrence", "matter"}
_SNAPSHOT_FIELDS = {"scope_id", "query", "subject", "entries", "coverage", "evidence", "as_of", "policy", "authority"}
_PUBLISH_FIELDS = {"query", "entries", "coverage", "evidence", "as_of", "previous"}

__all__ = [
    "CANDIDATE_NAMESPACE", "INDEX_NAMESPACE", "candidate_set_ref", "candidate_set_schema_ref",
    "candidate_set_value", "build_candidate_snapshot", "read_candidate_set", "require_current_candidates",
    "exact_candidates", "unavailable_evidence", "read_member", "read_dependency", "matches",
]


def _invalid() -> StorageError:
    return StorageError("E_EVIDENCE_INVALID", "The candidate catalog or its declared references are invalid.")


def _identity(value):
    return value["scope_id"], value["namespace"], value["id"]


def _scoped(scope_id, reference, fragment="pinned_ref"):
    ref = _validate_fragment(reference, fragment)
    if ref["scope_id"] != scope_id:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return ref


def matches(record: dict[str, Any], reference: dict[str, Any]) -> bool:
    """Match an already validated exact reference without changing its form."""
    if entity_ref(record) != entity_ref(reference):
        return False
    if "revision" in reference:
        return record.get("revision") == reference["revision"]
    if "digest" in reference:
        return snapshot_digest(record) == reference["digest"]
    return True


_matches = matches


def _read_current(view, scope_id, reference):
    # Keep real port exceptions outside every structural ValueError catch.
    stored = view.lookup_identity(entity_ref(reference))
    try:
        record = (_validate_projection(stored) if stored.get("record_type") == PROJECTION_TYPE
                  else validate_record(stored))
        if (entity_ref(record) != entity_ref(reference)
                or record["creation_receipt"]["scope_id"] != scope_id):
            raise _invalid()
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise _invalid() from None
    if not matches(record, reference):
        raise StorageError("E_REVISION_CONFLICT", "A candidate catalog dependency is no longer current.")
    return record


def read_dependency(view: Snapshot | Transaction, scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    """Read a pinned core record or projection at its current revision only."""
    scope = _validate_fragment(scope_id, "identifier")
    return _read_current(view, scope, _scoped(scope, reference))


def read_member(view: Snapshot | Transaction, scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    """Resolve a bare subject or exact member pin through the current identity."""
    scope = _validate_fragment(scope_id, "identifier")
    fragment = "pinned_ref" if type(reference) is dict and ("revision" in reference or "digest" in reference) else "entity_ref"
    ref = _scoped(scope, reference, fragment)
    if ref["record_type"] not in _MEMBERS:
        raise StorageError("E_SCHEMA_INVALID")
    return _read_current(view, scope, ref)


def _keys(values):
    if type(values) is not list:
        raise StorageError("E_SCHEMA_INVALID")
    keys = [_validate_fragment(key, "identity_key") for key in values]
    if len({canonical_bytes(key) for key in keys}) != len(keys):
        raise StorageError("E_SCHEMA_INVALID", "A candidate key must appear only once.")
    return sorted(keys, key=canonical_bytes)


def _refs(scope, values):
    if type(values) is not list:
        raise StorageError("E_SCHEMA_INVALID")
    refs = [_scoped(scope, reference) for reference in values]
    if len({_identity(reference) for reference in refs}) != len(refs):
        raise StorageError("E_SCHEMA_INVALID", "A dependency identity must appear only once in each set.")
    return sorted(refs, key=canonical_bytes)


def _query(scope, query):
    value = _validate_fragment(query, "association_query")
    subject = _scoped(scope, value["subject"], "entity_ref")
    if subject["record_type"] not in _MEMBERS:
        raise StorageError("E_SCHEMA_INVALID")
    if "keys" in value:
        value["keys"] = _keys(value["keys"])
    if value["mode"] == "exact_keys" and not value.get("keys"):
        raise StorageError("E_SCHEMA_INVALID", "An exact query needs a declared key.")
    return value


def candidate_set_ref(scope_id: str, query: dict[str, Any]) -> dict[str, str]:
    scope = _validate_fragment(scope_id, "identifier")
    value = _query(scope, query)
    return {
        "scope_id": scope, "namespace": CANDIDATE_NAMESPACE, "record_type": PROJECTION_TYPE,
        "id": "candidates-" + canonical_digest({"scope_id": scope, "query": value}, "matter.candidate-set.v1"),
    }


@lru_cache(maxsize=1)
def _contract():
    try:
        data = files("matter._schemas").joinpath("candidate-set.schema.json").read_bytes()
        schema = json.loads(data)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        return {
            "namespace": "matter", "id": "candidate-set", "version": "1.0", "digest": source_digest(data),
        }, Draft202012Validator(schema, registry=registry, format_checker=_FORMAT_CHECKER)
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The installed candidate-set schema is unavailable.") from None


def candidate_set_schema_ref() -> dict[str, str]:
    return deepcopy(_contract()[0])


def _snapshot(body):
    if type(body) is not dict or set(body) != _SNAPSHOT_FIELDS:
        raise StorageError("E_SCHEMA_INVALID")
    scope = _validate_fragment(body["scope_id"], "identifier")
    query = _query(scope, body["query"])
    subject = _scoped(scope, body["subject"], "association_member_dependency")
    if entity_ref(subject) != query["subject"]:
        raise _invalid()
    if type(body["entries"]) is not list:
        raise StorageError("E_SCHEMA_INVALID")
    entries, identities = [], set()
    for raw in body["entries"]:
        entry = _validate_fragment(raw, "association_candidate_entry")
        candidate = _scoped(scope, entry["candidate"], "association_member_dependency")
        if candidate["record_type"] != query["candidate_type"]:
            raise _invalid()
        identity = _identity(candidate)
        if identity == _identity(subject):
            raise StorageError("E_EVIDENCE_INVALID", "A subject cannot be its own association candidate.")
        if identity in identities:
            raise StorageError("E_SCHEMA_INVALID", "A candidate identity must appear only once.")
        identities.add(identity)
        entry["keys"] = _keys(entry["keys"])
        entry["basis"] = _refs(scope, entry["basis"])
        entries.append(entry)
    return {
        "scope_id": scope, "query": query, "subject": subject,
        "entries": sorted(entries, key=canonical_bytes),
        "coverage": _validate_fragment(body["coverage"], "coverage"),
        "evidence": _refs(scope, body["evidence"]),
        "as_of": _validate_fragment(body["as_of"], "known_time"),
        "policy": _validate_fragment(body["policy"], "component_ref"),
        "authority": _scoped(scope, body["authority"], "receipt_ref"),
    }


def candidate_set_value(body: dict[str, Any]) -> dict[str, Any]:
    """Build the closed schema-bound snapshot; all set fields are canonical."""
    descriptor, validator = _contract()
    value = _snapshot(body)
    if not validator.is_valid(value):
        raise StorageError("E_SCHEMA_INVALID")
    return {"schema": deepcopy(descriptor), "value": value}


def _snapshot_references(body):
    return [body["subject"], *body["evidence"],
            *(reference for entry in body["entries"] for reference in [entry["candidate"], *entry["basis"]])]


def build_candidate_snapshot(
    view: Snapshot | Transaction, scope_id: str, body: dict[str, Any],
    policy: dict[str, Any], authority: dict[str, Any],
) -> dict[str, Any]:
    """Validate a publication and read every declared member/dependency now.

    The caller owns the publication's previous-pin CAS and host authorization.
    Previous must nevertheless name this exact catalog, never another query.
    Keys are catalog metadata supplied by that host, not inferred identifiers.
    """
    scope = _validate_fragment(scope_id, "identifier")
    if type(body) is not dict or set(body) != _PUBLISH_FIELDS:
        raise StorageError("E_SCHEMA_INVALID")
    query = _query(scope, body["query"])
    if body["previous"] is not None:
        previous = _scoped(scope, body["previous"])
        if entity_ref(previous) != candidate_set_ref(scope, query):
            raise _invalid()
    subject = read_member(view, scope, query["subject"])
    snapshot = candidate_set_value({
        "scope_id": scope, "query": query, "subject": pin(subject),
        "entries": body["entries"], "coverage": body["coverage"], "evidence": body["evidence"],
        "as_of": body["as_of"], "policy": policy, "authority": authority,
    })["value"]
    for reference in _snapshot_references(snapshot):
        read_dependency(view, scope, reference)
    return snapshot


def _stored_set(stored, scope):
    # A missing packaged schema remains a storage error, not corrupt evidence.
    _contract()
    try:
        record = _validate_projection(stored)
        if (record["scope_id"] != scope or record["creation_receipt"]["scope_id"] != scope
                or record["namespace"] != CANDIDATE_NAMESPACE or record["watch_keys"]):
            raise _invalid()
        expected = candidate_set_value(record["value"]["value"])
        if (canonical_bytes(record["value"]) != canonical_bytes(expected)
                or entity_ref(record) != candidate_set_ref(scope, expected["value"]["query"])):
            raise _invalid()
        return record
    except StorageError as error:
        if error.code == "E_STORAGE_UNAVAILABLE":
            raise
        raise _invalid() from None
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def read_candidate_set(view: Snapshot | Transaction, scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    """Verify the current catalog; a pinned request never reads old history."""
    scope = _validate_fragment(scope_id, "identifier")
    fragment = "pinned_ref" if type(reference) is dict and ("revision" in reference or "digest" in reference) else "entity_ref"
    ref = _scoped(scope, reference, fragment)
    if ref["namespace"] != CANDIDATE_NAMESPACE or ref["record_type"] != PROJECTION_TYPE:
        raise StorageError("E_SCHEMA_INVALID")
    stored = view.lookup_identity(entity_ref(ref))
    record = _stored_set(stored, scope)
    if entity_ref(record) != entity_ref(ref):
        raise _invalid()
    if not matches(record, ref):
        raise StorageError("E_REVISION_CONFLICT", "The candidate-set revision is no longer current.")
    return record


def require_current_candidates(view: Snapshot | Transaction, scope_id: str, set_pin: dict[str, Any]) -> dict[str, Any]:
    """Require exact current catalog and all considered dependency snapshots."""
    reference = _scoped(scope_id, set_pin)
    record = read_candidate_set(view, scope_id, reference)
    for dependency in _snapshot_references(record["value"]["value"]):
        read_dependency(view, scope_id, dependency)
    return record


def exact_candidates(setrecord: dict[str, Any]) -> list[dict[str, Any]]:
    """Nominate entries by any exact key; semantic packets retain all entries."""
    scope = _validate_fragment(setrecord["scope_id"], "identifier")
    body = _stored_set(setrecord, scope)["value"]["value"]
    keys = {canonical_bytes(key) for key in body["query"].get("keys", [])}
    return sorted([
        {"candidate": deepcopy(entry["candidate"]), "basis": deepcopy(entry["basis"])}
        for entry in body["entries"]
        if body["query"]["mode"] == "semantic" or any(canonical_bytes(key) in keys for key in entry["keys"])
    ], key=canonical_bytes)


def unavailable_evidence(view: Snapshot | Transaction, scope_id: str, setrecord: dict[str, Any]) -> list[str]:
    """Report declared unavailable observation evidence; do not access bytes.

    Only explicit evidence and candidate basis refs are evidence for this gate.
    Being a subject/candidate does not itself make a member evidence. Other
    record kinds have no source availability inferred from arbitrary fields.
    """
    scope = _validate_fragment(scope_id, "identifier")
    body = _stored_set(setrecord, scope)["value"]["value"]
    references = [*body["evidence"], *(ref for entry in body["entries"] for ref in entry["basis"])]
    reasons = set()
    for reference in references:
        record = read_dependency(view, scope, reference)
        if record["record_type"] == "observation":
            status = record["body"]["content"]["availability"]["status"]
            if status != "available":
                reasons.add("observation_evidence_" + status)
    return sorted(reasons)
