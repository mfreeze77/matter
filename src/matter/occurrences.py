"""Exact happenings, accepted report membership, and explicit evidence counts.

An adapter's execution/event keys identify an occurrence. They do not establish
cause or evidence independence. Observation membership is many-to-many and may
be empty. The host accepts a grouping through one revision-checked command;
that same atomic operation can split a mistaken grouping and correct root
provenance declarations without rewriting the original reports.

Prepare once, retain the exact command, then commit it. A conflict requires a
new decision and command, not an automatic refresh of stale dependencies.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from .canonical import canonical_bytes, canonical_digest, source_digest
from .contracts import ContractError, command_digest, schema_for, validate_command, validate_record
from .provenance_groups import (
    ASSIGNMENT_NAMESPACE, assignment_ref, assignment_value, read_assignment,
    resolve_groups, root_watch_key,
)
from .storage import PROJECTION_TYPE, Snapshot, Storage, StorageError, Transaction, entity_ref, pin, snapshot_digest
from .storage.base import STORAGE_NAMESPACE, _validate_fragment, _validate_projection
from .time import validate_interval


INDEX_NAMESPACE = "matter.occurrences"
_RESERVED_NAMESPACES = frozenset({
    STORAGE_NAMESPACE, INDEX_NAMESPACE, ASSIGNMENT_NAMESPACE,
    "matter.identity_keys", "matter.observations",
})
_OPERATION = "commit_occurrence_grouping"

__all__ = [
    "INDEX_NAMESPACE", "ExactGroupingPolicy", "OccurrenceService",
    "new_occurrence_id", "occurrence_key_ref", "occurrence_index_ref",
    "membership_watch_key",
]


def _identity(value: dict[str, Any]) -> tuple[str, str, str]:
    return value["scope_id"], value["namespace"], value["id"]


def _sorted(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(deepcopy(list(values)), key=canonical_bytes)


def _unique_refs(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: dict[tuple[str, str, str], dict[str, Any]] = {}
    for ref in values:
        identity = _identity(ref)
        if identity in refs and canonical_bytes(refs[identity]) != canonical_bytes(ref):
            raise StorageError("E_REVISION_CONFLICT", "A dependency has inconsistent pins.")
        refs[identity] = ref
    return _sorted(refs.values())


def _integrity_error() -> StorageError:
    return StorageError("E_EVIDENCE_INVALID", "The accepted occurrence grouping could not be verified.")


def _conflict(records: Iterable[dict[str, Any]] = ()) -> StorageError:
    return StorageError(
        "E_SOURCE_IDENTITY_CONFLICT", "The declared event identity conflicts with existing state.",
        affected_references=tuple(entity_ref(record) for record in records),
    )


def _command(value: dict[str, Any]) -> dict[str, Any]:
    command = validate_command(value)
    if command["operation"] != _OPERATION:
        raise ContractError("E_SCHEMA_INVALID", "An occurrence grouping command is required.")
    return command


def new_occurrence_id() -> str:
    """Allocate an opaque ID before preparation; retain it for exact retries."""
    return str(uuid4())


def _namespaces(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise StorageError("E_SCHEMA_INVALID", "A namespace collection is required.")
    try:
        supplied = tuple(values)
    except TypeError:
        raise StorageError("E_SCHEMA_INVALID", "A namespace collection is required.") from None
    validated = tuple(_validate_fragment(value, "namespace") for value in supplied)
    if not validated or len(set(validated)) != len(validated):
        raise StorageError("E_SCHEMA_INVALID", "Namespaces must be nonempty and distinct.")
    return tuple(sorted(validated))


@dataclass(frozen=True, slots=True, init=False)
class ExactGroupingPolicy:
    """A digest-bound host declaration of event-key and provenance namespaces.

    Arrays representing keys, memberships and groups have set semantics, with
    duplicate command members refused and stored order defined by ascending
    Matter canonical JSON bytes. Identifiers themselves are never normalized.
    """

    key_namespaces: tuple[str, ...]
    group_namespaces: tuple[str, ...]

    def __init__(self, *, key_namespaces: Iterable[str], group_namespaces: Iterable[str]) -> None:
        object.__setattr__(self, "key_namespaces", _namespaces(key_namespaces))
        object.__setattr__(self, "group_namespaces", _namespaces(group_namespaces))

    @property
    def definition(self) -> dict[str, Any]:
        return {
            "algorithm": "matter.exact-occurrence-grouping.v1",
            "identity": "adapter_declared_happening",
            "normalization": "none",
            "key_namespaces": list(self.key_namespaces),
            "group_namespaces": list(self.group_namespaces),
            "key_expansion": "forbidden", "key_rebinding": "forbidden",
            "membership": "many_to_many_explicit_host_acceptance",
            "sets": "unique_sorted_canonical_json_bytes",
            "provenance": "explicit_root_assignments_and_observation_parent_union",
            "unresolved_lineage": "explicit_partial_coverage",
            "max_lineage_nodes": 4096,
        }

    @property
    def reference(self) -> dict[str, str]:
        return {
            "namespace": "matter", "id": "exact-occurrence-grouping", "version": "1.0",
            "digest": canonical_digest(self.definition, "matter.occurrence-policy.v1"),
        }

    @property
    def ref(self) -> dict[str, str]:
        return self.reference

    def validate_keys(self, keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if type(keys) is not list or not keys:
            raise StorageError("E_SCHEMA_INVALID", "At least one declared event key is required.")
        values = [_validate_fragment(key, "identity_key") for key in keys]
        pairs = [(value["namespace"], value["value"]) for value in values]
        if len(set(pairs)) != len(pairs):
            raise StorageError("E_SCHEMA_INVALID", "An event key must appear only once.")
        if any(namespace not in self.key_namespaces for namespace, _ in pairs):
            raise StorageError("E_POLICY_INVALID", "An event-key namespace is not allowed by this policy.")
        return _sorted(values)

    def validate_group(self, group: dict[str, Any]) -> dict[str, Any]:
        value = _validate_fragment(group, "identity_key")
        if value["namespace"] not in self.group_namespaces:
            raise StorageError("E_POLICY_INVALID", "A provenance-group namespace is not allowed by this policy.")
        return value


def _scoped_ref(scope_id: str, reference: dict[str, Any], fragment: str) -> dict[str, Any]:
    _validate_fragment(scope_id, "identifier")
    ref = _validate_fragment(reference, fragment)
    if ref["scope_id"] != scope_id:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return ref


def occurrence_key_ref(scope_id: str, key: dict[str, Any]) -> dict[str, Any]:
    scope = _validate_fragment(scope_id, "identifier")
    key = _validate_fragment(key, "identity_key")
    return {
        "scope_id": scope, "namespace": INDEX_NAMESPACE, "record_type": PROJECTION_TYPE,
        "id": "key-" + canonical_digest({"scope_id": scope, "key": key}, "matter.occurrence-key.v1"),
    }


def occurrence_index_ref(scope_id: str, occurrence: dict[str, Any]) -> dict[str, Any]:
    ref = _scoped_ref(scope_id, entity_ref(occurrence), "occurrence_ref")
    return {
        "scope_id": scope_id, "namespace": INDEX_NAMESPACE, "record_type": PROJECTION_TYPE,
        "id": "members-" + canonical_digest(ref, "matter.occurrence-membership.v1"),
    }


def membership_watch_key(scope_id: str, observation: dict[str, Any]) -> str:
    ref = _scoped_ref(scope_id, entity_ref(observation), "observation_ref")
    return "occurrence-member-" + canonical_digest(ref, "matter.occurrence-member-watch.v1")


def _lookup(view: Snapshot | Transaction, reference: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return view.lookup_identity(reference)
    except StorageError as exc:
        if exc.code == "E_NOT_FOUND":
            return None
        raise


@lru_cache(maxsize=2)
def _projection_contract(name: str) -> tuple[dict[str, str], Draft202012Validator]:
    try:
        content = files("matter._schemas").joinpath(name + ".schema.json").read_bytes()
        schema = json.loads(content)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        return {
            "namespace": "matter", "id": name, "version": "1.0", "digest": source_digest(content),
        }, Draft202012Validator(schema, registry=registry)
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The installed occurrence projection schema is unavailable.") from None


def _value(name: str, body: dict[str, Any]) -> dict[str, Any]:
    descriptor, validator = _projection_contract(name)
    canonical_bytes(body)
    if not validator.is_valid(body):
        raise _integrity_error()
    return {"schema": deepcopy(descriptor), "value": deepcopy(body)}


def _projection(value: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    try:
        record = _validate_projection(value)
        if entity_ref(record) != reference or record["creation_receipt"]["scope_id"] != reference["scope_id"]:
            raise _integrity_error()
        return record
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _integrity_error() from None


def _key_value(scope_id: str, key: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    refs = _sorted(entity_ref(record) for record in records)
    if any(ref["scope_id"] != scope_id for ref in refs):
        raise StorageError("E_SCOPE_FORBIDDEN")
    return _value("occurrence-key", {"scope_id": scope_id, "key": key, "occurrences": refs})


def _read_key(view: Snapshot | Transaction, scope_id: str, key: dict[str, Any]) -> dict[str, Any] | None:
    reference = occurrence_key_ref(scope_id, key)
    current = _lookup(view, reference)
    if current is None:
        return None
    index = _projection(current, reference)
    try:
        value = index["value"]
        expected = _key_value(scope_id, key, value["value"]["occurrences"])
        if canonical_bytes(value) != canonical_bytes(expected) or index["watch_keys"]:
            raise _integrity_error()
    except StorageError as exc:
        if exc.code == "E_STORAGE_UNAVAILABLE":
            raise
        raise _integrity_error() from None
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _integrity_error() from None
    return index


def _members(scope_id: str, observations: list[dict[str, Any]], *, deduplicate: bool = False) -> list[dict[str, Any]]:
    if type(observations) is not list:
        raise StorageError("E_SCHEMA_INVALID", "Observation membership must be an array.")
    refs = [_scoped_ref(scope_id, ref, "observation_dependency") for ref in observations]
    unique = _unique_refs(refs)
    if not deduplicate and len(refs) != len(unique):
        raise StorageError("E_SCHEMA_INVALID", "An observation must appear only once in a membership.")
    return unique


def _stored_occurrence(value: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    try:
        record = validate_record(value)
        if record["record_type"] != "occurrence" or entity_ref(record) != entity_ref(reference):
            raise _integrity_error()
        body = record["body"]
        if "occurred_interval" in body:
            validate_interval(body["occurred_interval"])
        members = _members(record["scope_id"], body["observations"])
        keys = _sorted(body["identity_keys"])
        groups = _sorted(body["provenance_groups"])
        if (
            len({canonical_bytes(key) for key in keys}) != len(keys)
            or len({canonical_bytes(group) for group in groups}) != len(groups)
            or body["observations"] != members or body["identity_keys"] != keys
            or body["provenance_groups"] != groups
        ):
            raise _integrity_error()
        return record
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _integrity_error() from None


def _bindings(
    view: Snapshot | Transaction, scope_id: str, keys: list[dict[str, Any]],
) -> tuple[list[dict[str, Any] | None], list[dict[str, Any]]]:
    indexes = []
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key in keys:
        index = _read_key(view, scope_id, key)
        indexes.append(index)
        if index is None:
            continue
        for ref in index["value"]["value"]["occurrences"]:
            identity = _identity(ref)
            if identity not in records:
                value = _lookup(view, ref)
                if value is None:
                    raise _integrity_error()
                records[identity] = _stored_occurrence(value, ref)
            if key not in records[identity]["body"]["identity_keys"]:
                raise _integrity_error()
    return indexes, list(records.values())


def _resolved(
    indexes: list[dict[str, Any] | None], records: list[dict[str, Any]], kind: str | None = None,
) -> dict[str, Any] | None:
    if not records:
        return None
    if len(records) != 1 or any(index is None for index in indexes):
        raise _conflict(records)
    current = records[0]
    if kind is not None and current["body"]["kind"] != kind:
        raise _conflict(records)
    return current


def _membership_value(record: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    return _value("occurrence-membership", {
        "scope_id": record["scope_id"], "occurrence": pin(record),
        "dependencies": resolution["dependencies"],
        "lineage_digest": canonical_digest(resolution, "matter.occurrence-lineage.v1"),
    })


def _watches(record: dict[str, Any], resolution: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(set(resolution["watch_keys"]) | {
        membership_watch_key(record["scope_id"], observation) for observation in record["body"]["observations"]
    }))


def _read_membership(
    view: Snapshot | Transaction, record: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    scope_id = record["scope_id"]
    reference = occurrence_index_ref(scope_id, record)
    current = _lookup(view, reference)
    if current is None:
        raise _integrity_error()
    index = _projection(current, reference)
    resolution = resolve_groups(view, scope_id, record["body"]["observations"])
    if (
        canonical_bytes(index["value"]) != canonical_bytes(_membership_value(record, resolution))
        or index["watch_keys"] != list(_watches(record, resolution))
        or record["body"]["provenance_groups"] != resolution["groups"]
    ):
        raise _integrity_error()
    return index, resolution


def _watched_occurrence(view: Snapshot | Transaction, index: dict[str, Any], scope_id: str) -> dict[str, Any]:
    try:
        ref = index["value"]["value"]["occurrence"]
        _scoped_ref(scope_id, ref, "occurrence_dependency")
        if entity_ref(index) != occurrence_index_ref(scope_id, ref):
            raise _integrity_error()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _integrity_error() from None
    # Port failures must retain their code. StorageError is a ValueError, so
    # placing this read in the structural catch above would journal outages
    # as terminal evidence refusals and conceal a transaction revision race.
    record = _lookup(view, entity_ref(ref))
    if record is None:
        raise _integrity_error()
    record = _stored_occurrence(record, ref)
    if pin(record) != ref:
        raise _integrity_error()
    return record


class _ReadCollector:
    """Record actual port reads while retaining the caller's existing pins."""

    def __init__(self, view: Snapshot, include: Callable[[dict[str, Any]], None]) -> None:
        self._view, self._include = view, include

    def get(self, reference: dict[str, Any]) -> dict[str, Any]:
        record = self._view.get(reference)
        self._include(pin(record))
        return record

    def lookup_identity(self, reference: dict[str, Any]) -> dict[str, Any]:
        record = self._view.lookup_identity(reference)
        self._include(pin(record))
        return record

    def watchers(self, watch_key: str) -> list[dict[str, Any]]:
        records = self._view.watchers(watch_key)
        for record in records:
            self._include(pin(record))
        return records


class OccurrenceService:
    """Scope-bound explicit grouping for a trusted host and local storage port.

    The command's actor, authority, and typed basis are retained in its receipt.
    The host owns business authorization and adapter identifiers. Group labels
    are declarations about evidence dependence, not proof of independence.
    """

    def __init__(self, storage: Storage, *, grouping_policy: ExactGroupingPolicy) -> None:
        _validate_fragment(storage.scope_id, "identifier")
        if not isinstance(grouping_policy, ExactGroupingPolicy):
            raise StorageError("E_POLICY_INVALID", "An exact occurrence grouping policy is required.")
        self._storage, self._policy = storage, grouping_policy

    @property
    def scope_id(self) -> str:
        return self._storage.scope_id

    @property
    def grouping_policy(self) -> dict[str, Any]:
        return self._policy.reference

    def _check_scope(self, command: dict[str, Any]) -> None:
        refs = [command["actor"], command["authority"], *command["expected_revisions"]]
        body = command["body"]
        for proposed in body["creates"]:
            refs.extend([proposed, *proposed["body"]["observations"], *proposed["provenance"]["parents"]])
            refs.extend(proposed.get("supersedes", []))
        for replacement in body["replacements"]:
            refs.extend([replacement["occurrence"], *replacement["observations"]])
        refs.extend(assignment["observation"] for assignment in body["provenance_assignments"])
        if command["scope_id"] != self.scope_id or any(ref["scope_id"] != self.scope_id for ref in refs):
            raise StorageError("E_SCOPE_FORBIDDEN")

    def prepare(self, command: dict[str, Any]) -> dict[str, Any]:
        """Read one snapshot and capture every dependency used by the decision.

        Explicit pins are preserved. Execution re-enumerates ancestry watches
        under the write transaction so a new dependent cannot escape a frozen
        correction. Semantic read errors may be raised here, before journaling.
        """
        command = _command(command)
        self._check_scope(command)
        expected = command["expected_revisions"]
        identities = {_identity(ref) for ref in expected}
        if len(identities) != len(expected):
            raise StorageError("E_SCHEMA_INVALID", "Expected revisions contain a duplicate identity.")

        def include(reference: dict[str, Any]) -> None:
            if reference["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
            identity = _identity(reference)
            if identity not in identities:
                expected.append(deepcopy(reference))
                identities.add(identity)

        with self._storage.snapshot() as snapshot:
            try:
                journal = snapshot.command_receipt(command["idempotency_key"])
            except StorageError as exc:
                if exc.code != "E_NOT_FOUND":
                    raise
            else:
                if command_digest(command) != journal["command_digest"]:
                    raise StorageError("E_IDEMPOTENCY_CONFLICT")
                return command
            for proposed in command["body"]["creates"]:
                for ref in proposed["body"]["observations"] + proposed["provenance"]["parents"]:
                    include(ref)
            for replacement in command["body"]["replacements"]:
                include(replacement["occurrence"])
                for ref in replacement["observations"]:
                    include(ref)
            for assignment in command["body"]["provenance_assignments"]:
                include(assignment["observation"])
            self._inspect(_ReadCollector(snapshot, include), command)
        return validate_command(command)

    def commit(self, command: dict[str, Any]) -> dict[str, Any]:
        """Atomically accept memberships, assignments, and affected projections."""
        return self._storage.execute(_command(command), self._commit)

    def _inspect(self, view: Snapshot | Transaction, command: dict[str, Any]) -> dict[str, Any]:
        self._check_scope(command)
        body = command["body"]
        if body["grouping_policy"] != self._policy.reference:
            raise StorageError("E_POLICY_INVALID", "The command's grouping policy is not configured.")
        current: dict[tuple[str, str, str], dict[str, Any]] = {}
        new: dict[tuple[str, str, str], dict[str, Any]] = {}
        members: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        old_resolutions: dict[tuple[str, str, str], dict[str, Any]] = {}
        assignments = []
        explicit_targets: set[tuple[str, str, str]] = set()
        proposed_ids: set[tuple[str, str, str]] = set()
        proposed_keys: set[bytes] = set()

        for proposed in body["creates"]:
            proposed = deepcopy(proposed)
            if "occurred_interval" in proposed["body"]:
                validate_interval(proposed["body"]["occurred_interval"])
            if proposed["namespace"] in _RESERVED_NAMESPACES:
                raise StorageError("E_SCOPE_FORBIDDEN", "The persistence namespace is reserved.")
            if "supersedes" in proposed:
                raise StorageError("E_POLICY_INVALID", "Grouping corrections use explicit membership replacements.")
            identity = _identity(proposed)
            if identity in proposed_ids:
                raise StorageError("E_SCHEMA_INVALID", "An occurrence creation target must appear only once.")
            proposed_ids.add(identity)
            keys = self._policy.validate_keys(proposed["body"]["identity_keys"])
            for key in keys:
                encoded = canonical_bytes(key)
                if encoded in proposed_keys:
                    raise _conflict()
                proposed_keys.add(encoded)
            proposed["body"]["identity_keys"] = keys
            proposed["body"]["observations"] = _members(self.scope_id, proposed["body"]["observations"])
            indexes, candidates = _bindings(view, self.scope_id, keys)
            candidate = _resolved(indexes, candidates, proposed["body"]["kind"])
            occupied = _lookup(view, entity_ref(proposed))
            if occupied is not None and (candidate is None or entity_ref(occupied) != entity_ref(candidate)):
                raise _conflict([occupied])
            for parent in proposed["provenance"]["parents"]:
                if entity_ref(parent) == entity_ref(proposed):
                    raise StorageError("E_EVIDENCE_INVALID", "An occurrence cannot be its own provenance parent.")
                view.get(parent)
            if candidate is not None:
                # New reports or changed event details are an explicit grouping
                # correction, not an implicit consequence of an exact key hit.
                actual_body = deepcopy(candidate["body"])
                actual_body["provenance_groups"] = []
                if (
                    canonical_bytes(actual_body) != canonical_bytes(proposed["body"])
                    or canonical_bytes(candidate.get("extensions", {})) != canonical_bytes(proposed.get("extensions", {}))
                ):
                    raise StorageError("E_ASSOCIATION_CONFLICT", "Existing occurrence membership or event details differ.")
                identity = _identity(candidate)
                current[identity] = candidate
            else:
                if _lookup(view, occurrence_index_ref(self.scope_id, proposed)) is not None:
                    raise _integrity_error()
                new[identity] = proposed
            if identity in explicit_targets:
                raise StorageError("E_SCHEMA_INVALID", "An occurrence must be targeted only once per command.")
            explicit_targets.add(identity)
            members[identity] = proposed["body"]["observations"]

        for replacement in body["replacements"]:
            reference = replacement["occurrence"]
            identity = _identity(reference)
            if identity in explicit_targets or identity in proposed_ids:
                raise StorageError("E_SCHEMA_INVALID", "An occurrence must be targeted only once per command.")
            explicit_targets.add(identity)
            record = view.lookup_identity(entity_ref(reference))
            if record["record_type"] != "occurrence":
                raise StorageError("E_NOT_FOUND")
            if (
                ("revision" in reference and reference["revision"] != record["revision"])
                or ("digest" in reference and reference["digest"] != snapshot_digest(record))
            ):
                raise StorageError("E_REVISION_CONFLICT", "The replacement occurrence pin is stale.")
            current[identity] = _stored_occurrence(record, reference)
            members[identity] = _members(self.scope_id, replacement["observations"])

        assigned: set[tuple[str, str, str]] = set()
        for declaration in body["provenance_assignments"]:
            reference = declaration["observation"]
            identity = _identity(reference)
            if identity in assigned:
                raise StorageError("E_SCHEMA_INVALID", "A root provenance assignment must appear only once.")
            assigned.add(identity)
            observation = view.get(reference)
            assignment = {key: deepcopy(value) for key, value in declaration.items() if key != "observation"}
            if assignment["status"] == "declared":
                self._policy.validate_group(assignment["group"])
            value = assignment_value(self.scope_id, observation, assignment)
            old = read_assignment(view, self.scope_id, observation)
            assignments.append({"observation": observation, "old": old, "value": value})
            # Re-enumerating these under Transaction detects newly registered
            # dependents as undeclared reads, including an initially empty set.
            for index in view.watchers(root_watch_key(self.scope_id, reference)):
                if index["namespace"] == INDEX_NAMESPACE:
                    record = _watched_occurrence(view, index, self.scope_id)
                    current[_identity(record)] = record

        for identity, record in current.items():
            keys = self._policy.validate_keys(record["body"]["identity_keys"])
            indexes, candidates = _bindings(view, self.scope_id, keys)
            resolved = _resolved(indexes, candidates, record["body"]["kind"])
            if resolved is None or pin(resolved) != pin(record):
                raise _integrity_error()
            _, resolution = _read_membership(view, record)
            old_resolutions[identity] = resolution
            members.setdefault(identity, record["body"]["observations"])
        for observations in members.values():
            resolve_groups(view, self.scope_id, observations)
        return {
            "current": current, "new": new, "members": members,
            "old_resolutions": old_resolutions,
            "assignments": assignments,
        }

    def _commit(self, tx: Transaction) -> dict[str, Any]:
        plan = self._inspect(tx, tx.command)
        assignment_pins = []
        changed = False
        for assignment in plan["assignments"]:
            old, value = assignment["old"], assignment["value"]
            if old is not None and canonical_bytes(old["value"]) == canonical_bytes(value):
                stored = old
            else:
                stored = tx.put_projection(
                    assignment_ref(self.scope_id, pin(assignment["observation"])), value,
                )
                changed = True
            assignment_pins.append(pin(stored))

        affected, previous = [], []
        for identity in sorted(plan["members"]):
            observations = plan["members"][identity]
            resolution = resolve_groups(tx, self.scope_id, observations)
            if identity in plan["new"]:
                proposed = deepcopy(plan["new"][identity])
                proposed["body"]["provenance_groups"] = resolution["groups"]
                stored = tx.insert(proposed)
                for key in stored["body"]["identity_keys"]:
                    tx.put_projection(
                        occurrence_key_ref(self.scope_id, key), _key_value(self.scope_id, key, [stored]),
                    )
                write_index = True
            else:
                old = plan["current"][identity]
                stored = deepcopy(old)
                stored["body"]["observations"] = observations
                stored["body"]["provenance_groups"] = resolution["groups"]
                write_index = (
                    canonical_bytes(stored) != canonical_bytes(old)
                    or canonical_bytes(resolution) != canonical_bytes(plan["old_resolutions"][identity])
                )
                if write_index:
                    previous.append(pin(old))
                    stored["revision"] += 1
                    stored = tx.replace(stored)
            if write_index:
                tx.put_projection(
                    occurrence_index_ref(self.scope_id, stored), _membership_value(stored, resolution),
                    watch_keys=_watches(stored, resolution),
                )
                changed = True
            affected.append(pin(stored))
        return tx.success("committed" if changed else "unchanged", {
            "occurrences": _sorted(affected), "previous": _sorted(previous),
            "provenance_assignments": _sorted(assignment_pins),
        })

    def resolve(self, keys: list[dict[str, Any]], *, kind: str | None = None) -> dict[str, Any] | None:
        """Resolve exact declared event keys, refusing partial or ambiguous hits."""
        keys = self._policy.validate_keys(keys)
        if kind is not None:
            _validate_fragment(kind, "namespaced_name")
        with self._storage.snapshot() as view:
            indexes, records = _bindings(view, self.scope_id, keys)
            current = _resolved(indexes, records, kind)
            if current is not None:
                _read_membership(view, current)
            return deepcopy(current)

    def _for_observations(
        self, view: Snapshot | Transaction, observations: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        records: dict[tuple[str, str, str], dict[str, Any]] = {}
        unassociated = []
        for observation in observations:
            view.get(observation)
            found = False
            for index in view.watchers(membership_watch_key(self.scope_id, observation)):
                if index["namespace"] != INDEX_NAMESPACE:
                    continue
                record = _watched_occurrence(view, index, self.scope_id)
                identity = _identity(record)
                if identity not in records:
                    _read_membership(view, record)
                    records[identity] = record
                if observation not in record["body"]["observations"]:
                    raise _integrity_error()
                found = True
            if not found:
                unassociated.append(observation)
        return _sorted(records.values()), _sorted(unassociated)

    def occurrences_for(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        """Return current accepted memberships for one immutable observation."""
        observations = _members(self.scope_id, [observation])
        with self._storage.snapshot() as view:
            records, _ = self._for_observations(view, observations)
            return records

    def counts(self, observations: list[dict[str, Any]], *, coverage: dict[str, Any]) -> dict[str, Any]:
        """Count an explicit observation cohort in one consistent snapshot.

        Source coverage is required and retained exactly. Provenance resolution
        has separate coverage. These counts establish neither external absence,
        causation, independent corroboration nor a judgment about any claim.
        """
        coverage = _validate_fragment(coverage, "coverage")
        selected = _members(self.scope_id, observations, deduplicate=True)
        dependencies: list[dict[str, Any]] = []
        with self._storage.snapshot() as snapshot:
            view = _ReadCollector(snapshot, dependencies.append)
            records, unassociated = self._for_observations(view, selected)
            resolution = resolve_groups(view, self.scope_id, selected)
            # Resolve the selected packet, not every other report that happens
            # to share one of its occurrences. Peers do not inflate its groups.
            return {
                "scope_id": self.scope_id,
                "counts": {
                    "observations": len(selected), "occurrences": len(records),
                    "provenance_groups": len(resolution["groups"]),
                },
                "observations": deepcopy(selected), "occurrences": _sorted(pin(record) for record in records),
                "provenance_groups": resolution["groups"],
                "unassociated_observations": unassociated,
                "unresolved_provenance": resolution["unresolved"],
                "coverage": coverage, "provenance_coverage": resolution["provenance_coverage"],
                "dependencies": _unique_refs(dependencies),
            }
