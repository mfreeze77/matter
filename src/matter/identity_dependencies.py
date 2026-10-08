"""Atomic identity-validity hooks for explicitly registered host derivatives.

Registration uses the existing trusted storage transaction. It does not create
an assessment, infer its truth, scan arbitrary host records, or dispatch work.
The later transitive invalidation engine can consume the same exact identity
pins and journaled change notices.
"""

from __future__ import annotations

from copy import deepcopy

from .canonical import canonical_bytes, canonical_digest
from .citations import _contract, _domain
from .contracts import validate_record
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin, snapshot_digest
from .storage.base import _validate_fragment, _validate_projection


NAMESPACE = "matter.identity_dependencies"


def _identity(value):
    return value["scope_id"], value["namespace"], value["id"]


def _sorted(values):
    return sorted(deepcopy(list(values)), key=canonical_bytes)


def _invalid(detail="The registered identity dependency could not be verified."):
    return StorageError("E_EVIDENCE_INVALID", detail)


def _value(name, value):
    descriptor, validator = _contract(name)
    try:
        canonical_bytes(value)
        if (type(value) is not dict or set(value) != {"schema", "value"}
                or value["schema"] != descriptor or not validator.is_valid(value["value"])):
            raise _invalid()
        return deepcopy(value["value"])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def _scoped(scope, value, fragment="pinned_ref"):
    ref = _validate_fragment(value, fragment)
    if ref["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return ref


def _matches(record, reference):
    return entity_ref(record) == entity_ref(reference) and (
        record.get("revision") == reference["revision"] if "revision" in reference
        else snapshot_digest(record) == reference["digest"])


def _lookup(view, reference):
    try:
        return view.lookup_identity(reference)
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise


def dependency_ref(reference):
    """Stable validity address for one scoped assessment or host projection."""
    reference = entity_ref(reference)
    if reference["record_type"] not in {"assessment", PROJECTION_TYPE}:
        raise StorageError("E_SCHEMA_INVALID", "Register an assessment or a host projection.")
    return {"scope_id": reference["scope_id"], "namespace": NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "dependency-" + canonical_digest(reference, "matter.identity-dependency.v1")}


identity_dependency_ref = dependency_ref


def _watch(matter):
    return "identity-dependent-" + canonical_digest(entity_ref(matter), "matter.identity-dependent-watch.v1")


def _watches(matters):
    return tuple(sorted({_watch(item) for item in matters}))


def read_registration(view, scope, reference):
    ref = _scoped(scope, reference, "projection_dependency" if "revision" in reference or "digest" in reference else "entity_ref")
    stored = view.get(ref)
    try:
        record = _validate_projection(stored)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    body = _value("identity-dependency", record["value"])
    if (record["namespace"] != NAMESPACE or body["scope_id"] != scope
            or record["creation_receipt"]["scope_id"] != scope
            or entity_ref(record) != dependency_ref(body["reference"])
            or ("revision" in ref or "digest" in ref) and not _matches(record, ref)
            or record["watch_keys"] != list(_watches(body["original_matters"]))
            or (body["status"] == "current") != (body["invalidation"] is None)):
        raise _invalid()
    for item in [body["reference"], *body["dependencies"], *body["original_matters"]]:
        if item["scope_id"] != scope:
            raise _invalid()
    for field in ("dependencies", "original_matters"):
        if len({_identity(item) for item in body[field]}) != len(body[field]) or body[field] != _sorted(body[field]):
            raise _invalid()
    from .identity_groups import group_ref
    original_ids = {_identity(item) for item in body["original_matters"]}
    matter_ids = {_identity(item) for item in body["dependencies"] if item["record_type"] == "matter"}
    group_ids = {_identity(group_ref(item)) for item in body["original_matters"]}
    if matter_ids != original_ids or any(
        item["record_type"] != "matter" and (
            item["record_type"] != PROJECTION_TYPE or _identity(item) not in group_ids)
        for item in body["dependencies"]
    ):
        raise _invalid("A registered identity view must pin every original matter and only its identity mirrors.")
    if body["invalidation"] is not None:
        from .identity_corrections import read_decision
        decision = read_decision(view, scope, body["invalidation"])
        changes = decision["body"]["details"]["value"]["changes"]
        if not any(pin(record) in change["after"] for change in changes):
            raise _invalid()
    return record


def register_identity_dependency(tx, reference, *, matters):
    """Register current identity pins in the same transaction as host work.

    The host must include existing group/matter and prior registration pins in
    the command read set. A new assessment must explicitly retain these pins
    in its positive dependency manifest. A host projection's semantics remain
    the host's responsibility. Re-registration requires the new exact target.
    """
    from .identity_groups import read_group

    scope = tx.command["scope_id"]
    ref = _scoped(scope, reference)
    target = tx.get(ref)
    if not _matches(target, ref):
        raise StorageError("E_REVISION_CONFLICT")
    address = dependency_ref(ref)
    if target["record_type"] == PROJECTION_TYPE and target["namespace"].startswith("matter."):
        raise StorageError("E_SCOPE_FORBIDDEN", "Internal projections are not host derivatives.")
    old = _lookup(tx, address)
    if old is not None:
        read_registration(tx, scope, pin(old))
    if not isinstance(matters, (list, tuple)) or not matters:
        raise StorageError("E_SCHEMA_INVALID")
    members, dependencies = {}, {}
    for matter in matters:
        current = _scoped(scope, matter, "matter_dependency")
        group = read_group(tx, scope, current)
        for item in group["members"]:
            members[_identity(item)] = entity_ref(item)
        for item in [*group["members"], *group["indexes"]]:
            dependencies[_identity(item)] = pin(item)
    if target["record_type"] == "assessment":
        record = validate_record(target)
        if _identity(record["body"]["matter"]) not in members:
            raise _invalid("The assessment must name one registered matter identity.")
        positive = record["body"]["dependency_manifest"]["positive"]
        for required in dependencies.values():
            actual = tx.get(required)
            if not any(_matches(actual, supplied) for supplied in positive if _identity(supplied) == _identity(required)):
                raise _invalid("The assessment must retain the complete identity view it used.")
    body = {"scope_id": scope, "reference": pin(target), "original_matters": _sorted(members.values()),
            "dependencies": _sorted(dependencies.values()), "status": "current", "invalidation": None}
    return tx.put_projection(address, _domain("identity-dependency", body),
                             watch_keys=_watches(body["original_matters"]))


def collect_dependencies(view, scope, members):
    found = {}
    for matter in members:
        for watched in view.watchers(_watch(matter)):
            record = read_registration(view, scope, pin(watched))
            if entity_ref(matter) not in record["value"]["value"]["original_matters"]:
                raise _invalid()
            if canonical_bytes(record) != canonical_bytes(watched):
                raise _invalid()
            found[_identity(record)] = record
    return _sorted(found.values())


def invalidate_dependencies(tx, registrations, decision):
    updated = []
    for registration in registrations:
        body = deepcopy(registration["value"]["value"])
        if body["status"] == "invalidated":
            continue
        body.update(status="invalidated", invalidation=deepcopy(decision))
        updated.append(tx.put_projection(entity_ref(registration), _domain("identity-dependency", body),
                                         watch_keys=_watches(body["original_matters"])))
    return updated


def require_current_identity_dependency(view, scope, registration):
    """Refuse an invalidated or subsequently changed registered result."""
    ref = _scoped(scope, registration,
                  "projection_dependency" if "revision" in registration or "digest" in registration else "entity_ref")
    current = _lookup(view, entity_ref(ref))
    if current is None:
        raise StorageError("E_NOT_FOUND")
    if ("revision" in ref or "digest" in ref) and not _matches(current, ref):
        raise StorageError("E_DEPENDENCY_STALE", "The selected validity registration is historical.")
    record = read_registration(view, scope, pin(current))
    body = record["value"]["value"]
    if body["status"] != "current":
        raise StorageError("E_DEPENDENCY_STALE")
    for reference in [body["reference"], *body["dependencies"]]:
        current = _lookup(view, entity_ref(reference))
        if current is None or not _matches(current, reference):
            raise StorageError("E_DEPENDENCY_STALE")
    return record
