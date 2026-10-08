"""Declared evidence dependence, kept separate from occurrence identity.

Only a parentless observation whose origin is neither derived nor evaluator can
receive a root assignment. A declared group is supplied by the host; source
text, payload hashes, publishers, timestamps and execution IDs never mint one.
An assignment can instead preserve an explicit unknown reason. These groups
describe declared dependence, not independence qualification or proof of cause.

Every parented observation inherits the union of its observation parents'
groups. A summary over two groups retains both groups without connecting them
into one group or creating a third. Non-observation parent semantics are outside
this bounded algorithm and remain explicit unresolved references.

Resolution uses only the persistence port. Its read pins and identity watches
let the occurrence service revise affected projections when assignments change.
Coverage describes the declared provenance closure of the selected observation
packet; callers must separately retain their source/selection coverage.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from .canonical import canonical_bytes, canonical_digest, source_digest
from .contracts import ContractError, schema_for, validate_record
from .storage import PROJECTION_TYPE, Snapshot, StorageError, Transaction, entity_ref, pin
from .storage.base import _validate_fragment, _validate_projection


ASSIGNMENT_NAMESPACE = "matter.provenance_groups"
ASSIGNMENT_SCHEMA = "https://github.com/mfreeze77/matter/schemas/provenance-root-assignment.schema.json"
_ASSIGNMENT_FILE = "provenance-root-assignment.schema.json"

__all__ = [
    "ASSIGNMENT_NAMESPACE", "ASSIGNMENT_SCHEMA", "assignment_schema_ref",
    "assignment_ref", "assignment_value", "read_assignment", "root_watch_key",
    "resolve_groups",
]


def _invalid() -> StorageError:
    return StorageError("E_EVIDENCE_INVALID", "The provenance assignment or observation lineage is invalid.")


def _identity(reference: dict[str, Any]) -> tuple[str, str, str]:
    return reference["scope_id"], reference["namespace"], reference["id"]


def _sorted_unique(values: Any) -> list[Any]:
    unique = {canonical_bytes(value): deepcopy(value) for value in values}
    return [unique[key] for key in sorted(unique)]


def _observation_ref(scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    reference = _validate_fragment(reference, "observation_dependency")
    if reference["scope_id"] != scope_id:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return reference


def _observation(
    scope_id: str, observation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        value = validate_record(observation)
    except ContractError as error:
        raise StorageError(error.code) from None
    if value["record_type"] != "observation":
        raise StorageError("E_SCHEMA_INVALID")
    if value["scope_id"] != scope_id:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return value, pin(value)


def _eligible(observation: dict[str, Any]) -> bool:
    provenance = observation["provenance"]
    return not provenance["parents"] and provenance["origin"] not in {"derived", "evaluator"}


def assignment_ref(scope_id: str, observation_ref: dict[str, Any]) -> dict[str, str]:
    """Address a root assignment by bare identity after validating its exact pin.

    The pin is verified in the stored value. Excluding its digest from the
    address prevents an incorrect pin from hiding an existing assignment.
    """
    scope = _validate_fragment(scope_id, "identifier")
    reference = _observation_ref(scope, observation_ref)
    return {
        "scope_id": scope, "namespace": ASSIGNMENT_NAMESPACE, "record_type": PROJECTION_TYPE,
        "id": "root-" + canonical_digest(
            {"scope_id": scope, "observation": entity_ref(reference)},
            "matter.provenance-assignment.v1",
        ),
    }


def root_watch_key(scope_id: str, observation_ref: dict[str, Any]) -> str:
    """Watch the assignment identity even while it is absent or unresolved."""
    return "provenance-root-" + canonical_digest(
        assignment_ref(scope_id, observation_ref), "matter.provenance-watch.v1",
    )


@lru_cache(maxsize=1)
def _assignment_contract() -> tuple[dict[str, str], Draft202012Validator]:
    try:
        content = files("matter._schemas").joinpath(_ASSIGNMENT_FILE).read_bytes()
        schema = json.loads(content)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        descriptor = {
            "namespace": "matter", "id": "provenance-root-assignment", "version": "1.0",
            "digest": source_digest(content),
        }
        return descriptor, Draft202012Validator(schema, registry=registry)
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise StorageError(
            "E_STORAGE_UNAVAILABLE", "The installed provenance assignment schema is unavailable."
        ) from None


def assignment_schema_ref() -> dict[str, str]:
    """Return a detached descriptor hashing the exact packaged schema bytes."""
    return deepcopy(_assignment_contract()[0])


def _assignment_value(
    scope_id: str, observation: dict[str, Any], observation_pin: dict[str, Any],
    assignment: dict[str, Any],
) -> dict[str, Any]:
    if not _eligible(observation):
        raise _invalid()
    if type(assignment) is not dict or "observation" in assignment:
        raise StorageError("E_SCHEMA_INVALID")
    declaration = _validate_fragment(
        {**assignment, "observation": observation_pin}, "occurrence_grouping_assignment",
    )
    declaration.pop("observation")
    body = {"scope_id": scope_id, "observation": deepcopy(observation_pin), "assignment": declaration}
    descriptor, validator = _assignment_contract()
    if not validator.is_valid(body):
        raise StorageError("E_SCHEMA_INVALID")
    return {"schema": deepcopy(descriptor), "value": body}


def assignment_value(
    scope_id: str, observation_record: dict[str, Any], assignment: dict[str, Any],
) -> dict[str, Any]:
    """Build a declaration for an eligible root without changing its evidence."""
    scope = _validate_fragment(scope_id, "identifier")
    observation, observation_pin = _observation(scope, observation_record)
    return _assignment_value(scope, observation, observation_pin, assignment)


def _read_assignment(
    view: Snapshot | Transaction, scope_id: str, observation: dict[str, Any],
    observation_pin: dict[str, Any],
) -> dict[str, Any] | None:
    reference = assignment_ref(scope_id, observation_pin)
    try:
        stored = view.lookup_identity(deepcopy(reference))
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise
    try:
        projection = _validate_projection(stored)
        if (
            entity_ref(projection) != reference
            or projection["creation_receipt"]["scope_id"] != scope_id
            or projection["watch_keys"]
        ):
            raise _invalid()
        contents = projection["value"]
        expected = _assignment_value(
            scope_id, observation, observation_pin, contents["value"]["assignment"],
        )
        if contents != expected:
            raise _invalid()
        return projection
    except StorageError as error:
        if error.code == "E_STORAGE_UNAVAILABLE":
            raise
        raise _invalid() from None
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def read_assignment(
    view: Snapshot | Transaction, scope_id: str, observation_record: dict[str, Any],
) -> dict[str, Any] | None:
    """Read an exact assignment; an assignment on a parented source is invalid.

    Querying an unassigned parented observation returns None. This negative
    read is intentional: it cannot silently ignore a later forged assignment.
    """
    scope = _validate_fragment(scope_id, "identifier")
    observation, observation_pin = _observation(scope, observation_record)
    return _read_assignment(view, scope, observation, observation_pin)


def resolve_groups(
    view: Snapshot | Transaction, scope_id: str, observation_refs: list[dict[str, Any]],
    *, max_nodes: int = 4096,
) -> dict[str, Any]:
    """Resolve a bounded observation-parent graph into declared group unions.

    All returned lists are canonical sets, detached from port records. Missing
    requested observations are errors; missing ancestors and non-observation
    ancestry remain unresolved. Read/authority/revision failures propagate.
    Cycles or incompatible pins are invalid evidence. max_nodes limits distinct
    referenced lineage snapshots, including unsupported and missing parents;
    assignment projections are extra reads bounded by the observation count.
    """
    scope = _validate_fragment(scope_id, "identifier")
    _validate_fragment(max_nodes, "revision")
    if type(observation_refs) is not list:
        raise StorageError("E_SCHEMA_INVALID")
    selected = _sorted_unique(_observation_ref(scope, reference) for reference in observation_refs)
    selected_ids = {_identity(reference) for reference in selected}
    requests: dict[tuple[str, str, str], dict[str, Any]] = {}
    queue: deque[tuple[str, str, str]] = deque()
    budget_nodes: set[bytes] = set()

    def budget(reference: dict[str, Any]) -> None:
        budget_nodes.add(canonical_bytes(reference))
        if len(budget_nodes) > max_nodes:
            raise StorageError("E_BUDGET_EXHAUSTED", "The provenance lineage exceeds its node budget.")

    def enqueue(reference: dict[str, Any]) -> tuple[str, str, str]:
        identity = _identity(reference)
        if identity in requests:
            if requests[identity] != reference:
                raise _invalid()
        else:
            budget(reference)
            requests[identity] = deepcopy(reference)
            queue.append(identity)
        return identity

    for reference in selected:
        enqueue(reference)
    dependencies: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []
    watches: set[str] = set()
    unresolved: list[dict[str, Any]] = []
    children: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {}
    group_sets: dict[tuple[str, str, str], dict[bytes, dict[str, str]]] = {}
    missing: set[tuple[str, str, str]] = set()

    while queue:
        identity = queue.popleft()
        reference = requests[identity]
        watches.add(root_watch_key(scope, reference))
        children[identity] = set()
        group_sets[identity] = {}
        try:
            stored = view.get(deepcopy(reference))
        except StorageError as error:
            if error.code != "E_NOT_FOUND" or identity in selected_ids:
                raise
            missing.add(identity)
            continue
        observation, actual_pin = _observation(scope, stored)
        if actual_pin != reference:
            raise _invalid()
        dependencies.append(actual_pin)
        assigned = _read_assignment(view, scope, observation, actual_pin)
        if assigned is not None:
            dependencies.append(pin(assigned))
        parents = _sorted_unique(observation["provenance"]["parents"])
        if not parents:
            if not _eligible(observation):
                unresolved.append({"observation": actual_pin, "reason": "non_source_root"})
                continue
            roots.append(actual_pin)
            if assigned is None:
                unresolved.append({"observation": actual_pin, "reason": "unassigned_root"})
            else:
                declaration = assigned["value"]["value"]["assignment"]
                if declaration["status"] == "unknown":
                    unresolved.append({
                        "observation": actual_pin, "reason": "unknown_root", "detail": declaration["reason"],
                    })
                else:
                    group = declaration["group"]
                    group_sets[identity][canonical_bytes(group)] = deepcopy(group)
            continue
        for parent in parents:
            if parent["scope_id"] != scope:
                raise StorageError("E_SCOPE_FORBIDDEN")
            if parent["record_type"] != "observation":
                budget(parent)
                unresolved.append({
                    "observation": actual_pin, "reason": "non_observation_parent", "parent": parent,
                })
                continue
            children[identity].add(enqueue(parent))

    # Missing ancestors remain visible for every direct edge that cites them.
    for identity, descendants in children.items():
        for absent in descendants & missing:
            unresolved.append({
                "observation": requests[identity], "reason": "missing_parent", "parent": requests[absent],
            })

    # Process leaves toward their consumers without recursion. Unioning group
    # sets preserves distinct roots; it is not a union-find merge of sources.
    remaining = {identity: len(descendants) for identity, descendants in children.items()}
    consumers: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {identity: set() for identity in children}
    for identity, descendants in children.items():
        for descendant in descendants:
            consumers[descendant].add(identity)
    ready = deque(identity for identity in children if remaining[identity] == 0)
    processed = 0
    while ready:
        identity = ready.popleft()
        processed += 1
        for consumer in consumers[identity]:
            group_sets[consumer].update(group_sets[identity])
            remaining[consumer] -= 1
            if remaining[consumer] == 0:
                ready.append(consumer)
    if processed != len(children):
        raise _invalid()

    result = {
        "groups": _sorted_unique(group for identity in selected_ids for group in group_sets[identity].values()),
        "dependencies": _sorted_unique(dependencies),
        "roots": _sorted_unique(roots),
        "watch_keys": _sorted_unique(watches),
        "unresolved": _sorted_unique(unresolved),
    }
    coverage = {
        "status": "partial" if result["unresolved"] else "complete",
        "snapshot": {
            "namespace": "matter", "id": "provenance-resolution", "version": "1.0",
            "digest": canonical_digest(
                {"scope_id": scope, "observations": selected, **result},
                "matter.provenance-resolution.v1",
            ),
        },
    }
    if result["unresolved"]:
        coverage["reason"] = "Some selected observation lineage has no declared provenance group."
    result["provenance_coverage"] = coverage
    return result
