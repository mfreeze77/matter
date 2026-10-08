"""Immutable scoped source assertions and explicit correction histories.

A claim preserves a proposition, its attribution, qualifiers and applicability.
It does not establish truth, change a matter, or infer a relationship between
subjects. Corrections append distinct immutable claims and retain all branches;
the host's later assessment decides what those assertions mean.

Prepare each command once and retain the exact result for durable retries.
Dependency-change notices identify affected model records, not independent new
source observations. Assessment invalidation is a separate operation.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
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
from .storage import PROJECTION_TYPE, Snapshot, Storage, StorageError, Transaction, entity_ref, pin
from .storage.base import STORAGE_NAMESPACE, _validate_fragment, _validate_projection
from .time import validate_interval


INDEX_NAMESPACE = "matter.claims"
_RESERVED_NAMESPACES = frozenset({
    STORAGE_NAMESPACE, INDEX_NAMESPACE, "matter.identity_keys", "matter.observations",
    "matter.occurrences", "matter.provenance_groups", "matter.evidence_relations", "matter.citations",
})
_MAX_LINEAGE_NODES = 4096

__all__ = [
    "ClaimService", "INDEX_NAMESPACE", "new_claim_id", "claim_index_ref",
    "claim_index_schema_ref", "read_claim", "validate_applicability",
]


def _identity(value: dict[str, Any]) -> tuple[str, str, str]:
    return value["scope_id"], value["namespace"], value["id"]


def _sorted(values: Any) -> list[dict[str, Any]]:
    return sorted(deepcopy(list(values)), key=canonical_bytes)


def _invalid(detail: str = "The scoped claim or its correction history could not be verified.") -> StorageError:
    return StorageError("E_EVIDENCE_INVALID", detail)


def _conflict(record: dict[str, Any]) -> StorageError:
    return StorageError(
        "E_SOURCE_IDENTITY_CONFLICT", "The claim identity already names a different immutable input.",
        affected_references=(entity_ref(record),),
    )


def _command(value: dict[str, Any]) -> dict[str, Any]:
    command = validate_command(value)
    if command["operation"] != "append_claim":
        raise ContractError("E_SCHEMA_INVALID", "Claim intake requires an append_claim command.")
    return command


def new_claim_id() -> str:
    """Allocate an opaque assertion ID before preparation and retain it on retry."""
    return str(uuid4())


def validate_applicability(interval: dict[str, Any]) -> dict[str, Any]:
    """Preserve known/unknown bounds; refuse reversed known times exactly.

    The contract validates UTC calendar values and precision. Comparing all
    nine fractional digits avoids converting nanosecond boundaries to a lower
    precision datetime. Unknown endpoints never receive inferred dates.
    """
    return validate_interval(interval)


def _reference(scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    _validate_fragment(scope_id, "identifier")
    if type(reference) is not dict:
        raise StorageError("E_SCHEMA_INVALID")
    fragment = "claim_dependency" if "digest" in reference or "revision" in reference else "claim_ref"
    value = _validate_fragment(reference, fragment)
    if value["scope_id"] != scope_id:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return value


def read_claim(view: Snapshot | Transaction, scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    """Read an exact immutable assertion without interpreting or refreshing it."""
    ref = _reference(scope_id, reference)
    # Keep port exceptions outside structural catches: an unavailable backend,
    # missing read guard or stale dependency is not malformed source evidence.
    stored = view.get(ref)
    try:
        record = validate_record(stored)
        if (
            record["record_type"] != "claim" or entity_ref(record) != entity_ref(ref)
            or record["creation_receipt"]["scope_id"] != scope_id
            or ("digest" in ref and canonical_bytes(pin(record)) != canonical_bytes(ref))
        ):
            raise _invalid()
        validate_applicability(record["body"]["applicability"])
        return record
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def claim_index_ref(scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    ref = _reference(scope_id, entity_ref(reference))
    return {
        "scope_id": scope_id, "namespace": INDEX_NAMESPACE, "record_type": PROJECTION_TYPE,
        "id": "claim-" + canonical_digest(ref, "matter.claim-index.v1"),
    }


def _subject(scope_id: str, value: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        raise StorageError("E_SCHEMA_INVALID")
    if "schema" in value:
        return _validate_fragment(value, "domain_value")
    reference = _validate_fragment(value, "entity_ref")
    if reference["scope_id"] != scope_id:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return reference


def _subject_watch(scope_id: str, subject: dict[str, Any]) -> str:
    return "claim-subject-" + canonical_digest(
        {"scope_id": scope_id, "subject": _subject(scope_id, subject)}, "matter.claim-subject-watch.v1",
    )


def _predecessor_watch(scope_id: str, reference: dict[str, Any]) -> str:
    return "claim-correction-" + canonical_digest(
        _reference(scope_id, reference), "matter.claim-correction-watch.v1",
    )


@lru_cache(maxsize=1)
def _index_contract() -> tuple[dict[str, str], Draft202012Validator]:
    try:
        content = files("matter._schemas").joinpath("claim-index.schema.json").read_bytes()
        schema = json.loads(content)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        return {
            "namespace": "matter", "id": "claim-index", "version": "1.0", "digest": source_digest(content),
        }, Draft202012Validator(schema, registry=registry)
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The installed claim index schema is unavailable.") from None


def claim_index_schema_ref() -> dict[str, str]:
    """Return a detached descriptor hashing the exact packaged schema bytes."""
    return deepcopy(_index_contract()[0])


def _index_value(record: dict[str, Any]) -> dict[str, Any]:
    body = {
        "scope_id": record["scope_id"], "claim": pin(record),
        "subject": deepcopy(record["body"]["subject"]), "predicate": record["body"]["predicate"],
        "predecessors": _sorted(record.get("supersedes", [])),
    }
    descriptor, validator = _index_contract()
    if not validator.is_valid(body):
        raise _invalid()
    return {"schema": deepcopy(descriptor), "value": body}


def _watches(record: dict[str, Any]) -> tuple[str, ...]:
    scope = record["scope_id"]
    keys = {_subject_watch(scope, record["body"]["subject"])}
    keys.update(_predecessor_watch(scope, ref) for ref in record.get("supersedes", []))
    return tuple(sorted(keys))


def _lookup(view: Snapshot | Transaction, reference: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return view.lookup_identity(reference)
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise


def _read_index(view: Snapshot | Transaction, record: dict[str, Any]) -> dict[str, Any]:
    reference = claim_index_ref(record["scope_id"], record)
    stored = _lookup(view, reference)
    if stored is None:
        raise _invalid()
    # Loading the installed contract can fail operationally; do that outside
    # the integrity catch so callers may retry an unavailable installation.
    expected = _index_value(record)
    try:
        projection = _validate_projection(stored)
        if (
            entity_ref(projection) != reference or projection["revision"] != 1
            or projection["creation_receipt"] != record["creation_receipt"]
            or canonical_bytes(projection["value"]) != canonical_bytes(expected)
            or projection["watch_keys"] != list(_watches(record))
        ):
            raise _invalid()
        return projection
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def _from_projection(view: Snapshot | Transaction, scope_id: str, stored: dict[str, Any]) -> dict[str, Any]:
    try:
        projection = _validate_projection(stored)
        reference = _reference(scope_id, projection["value"]["value"]["claim"])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    record = read_claim(view, scope_id, reference)
    verified = _read_index(view, record)
    if canonical_bytes(verified) != canonical_bytes(projection):
        raise _invalid()
    return record


class ClaimService:
    """Scope-bound assertion intake for a trusted host and persistence port.

    Attribution and host authority remain explicit declarations. Storing a
    proposition or a correction does not execute source instructions, accept
    semantic identity, transition a matter, or manufacture opposing claims.
    """

    def __init__(self, storage: Storage) -> None:
        _validate_fragment(storage.scope_id, "identifier")
        self._storage = storage

    @property
    def scope_id(self) -> str:
        return self._storage.scope_id

    def _check_scope(self, command: dict[str, Any]) -> None:
        claim = command["body"]["claim"]
        refs = [claim, command["actor"], command["authority"], *command["expected_revisions"]]
        refs.extend(claim["body"]["attribution"])
        refs.extend(claim["provenance"]["parents"])
        refs.extend(claim.get("supersedes", []))
        _subject(self.scope_id, claim["body"]["subject"])
        if command["scope_id"] != self.scope_id or any(ref["scope_id"] != self.scope_id for ref in refs):
            raise StorageError("E_SCOPE_FORBIDDEN")

    def prepare(self, command: dict[str, Any]) -> dict[str, Any]:
        """Capture dependencies in one snapshot, retaining supplied read pins.

        This read-only step may refuse missing references or malformed scope.
        Append journals ordinary semantic refusals. Immutable corrections do
        not update predecessor indexes, so concurrent distinct branches may
        both survive. No branch is selected as established or current truth.
        """
        command = _command(command)
        self._check_scope(command)
        expected = command["expected_revisions"]
        identities = {_identity(ref) for ref in expected}
        if len(identities) != len(expected):
            raise StorageError("E_SCHEMA_INVALID", "Expected revisions contain a duplicate identity.")

        def include(ref: dict[str, Any]) -> None:
            if ref["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
            if _identity(ref) not in identities:
                expected.append(deepcopy(ref))
                identities.add(_identity(ref))

        with self._storage.snapshot() as view:
            try:
                journal = view.command_receipt(command["idempotency_key"])
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
            else:
                if command_digest(command) != journal["command_digest"]:
                    raise StorageError("E_IDEMPOTENCY_CONFLICT")
                return command
            proposed = command["body"]["claim"]
            occupied = _lookup(view, entity_ref(proposed))
            if occupied is not None:
                include(pin(occupied))
            index = _lookup(view, claim_index_ref(self.scope_id, proposed))
            if index is not None:
                include(pin(index))
            # An exact duplicate refers to its original immutable assertion;
            # current external evidence or mutable subject state cannot alter it.
            if occupied is None:
                subject = proposed["body"]["subject"]
                if "schema" not in subject:
                    include(pin(view.get(subject)))
                for ref in proposed["body"]["attribution"] + proposed["provenance"]["parents"]:
                    include(ref)
                for ref in proposed.get("supersedes", []):
                    include(ref)
                    if ref["record_type"] == "claim":
                        prior_index = _lookup(view, claim_index_ref(self.scope_id, ref))
                        if prior_index is not None:
                            include(pin(prior_index))
        return validate_command(command)

    def append(self, command: dict[str, Any]) -> dict[str, Any]:
        """Atomically append an assertion and its exact subject/correction index."""
        return self._storage.execute(_command(command), self._append)

    def _append(self, tx: Transaction) -> dict[str, Any]:
        command = tx.command
        self._check_scope(command)
        proposed = command["body"]["claim"]
        if proposed["namespace"] in _RESERVED_NAMESPACES:
            raise StorageError("E_SCOPE_FORBIDDEN", "The persistence namespace is reserved.")
        occupied = _lookup(tx, entity_ref(proposed))
        if occupied is not None:
            if occupied["record_type"] != "claim":
                raise _conflict(occupied)
            original = deepcopy(occupied)
            original.pop("creation_receipt")
            if canonical_bytes(original) != canonical_bytes(proposed):
                raise _conflict(occupied)
            _read_index(tx, occupied)
            return tx.success("duplicate", {"claim": pin(occupied), "changes": []})
        if _lookup(tx, claim_index_ref(self.scope_id, proposed)) is not None:
            raise _invalid("A claim index exists without its immutable claim.")

        validate_applicability(proposed["body"]["applicability"])
        subject = proposed["body"]["subject"]
        if "schema" not in subject:
            if _identity(subject) == _identity(proposed):
                raise _invalid("A new claim cannot be its own subject.")
            tx.get(subject)
        for ref in proposed["body"]["attribution"] + proposed["provenance"]["parents"]:
            if _identity(ref) == _identity(proposed):
                raise _invalid("A claim cannot attribute or derive itself from itself.")
            tx.get(ref)

        predecessors = proposed.get("supersedes", [])
        seen: set[tuple[str, str, str]] = set()
        for ref in predecessors:
            if ref["record_type"] != "claim" or _identity(ref) in seen or _identity(ref) == _identity(proposed):
                raise _invalid("Claim corrections require distinct earlier claim snapshots.")
            seen.add(_identity(ref))
            prior = read_claim(tx, self.scope_id, ref)
            _read_index(tx, prior)
            if (
                canonical_bytes(prior["body"]["subject"]) != canonical_bytes(subject)
                or prior["body"]["predicate"] != proposed["body"]["predicate"]
                or prior["body"]["proposition_version"] == proposed["body"]["proposition_version"]
            ):
                raise _invalid("A correction must retain its subject and predicate and declare a different proposition version.")

        stored = tx.insert(proposed)
        tx.put_projection(claim_index_ref(self.scope_id, stored), _index_value(stored), watch_keys=_watches(stored))
        change = {
            "cause": "evidence_correction" if predecessors else "new_evidence",
            "before": _sorted(predecessors), "after": [pin(stored)],
        }
        return tx.success("appended", {"claim": pin(stored), "changes": [change]})

    def for_subject(self, subject: dict[str, Any], *, predicate: str | None = None) -> list[dict[str, Any]]:
        """Return all assertions for the exact declared subject, including history."""
        subject = _subject(self.scope_id, subject)
        if predicate is not None:
            predicate = _validate_fragment(predicate, "namespaced_name")
        found: dict[bytes, dict[str, Any]] = {}
        with self._storage.snapshot() as view:
            for index in view.watchers(_subject_watch(self.scope_id, subject)):
                record = _from_projection(view, self.scope_id, index)
                if canonical_bytes(record["body"]["subject"]) != canonical_bytes(subject):
                    raise _invalid()
                if predicate is None or record["body"]["predicate"] == predicate:
                    found[canonical_bytes(pin(record))] = record
        return [found[key] for key in sorted(found)]

    def _lineage(self, view: Snapshot, reference: dict[str, Any]) -> list[dict[str, Any]]:
        start = read_claim(view, self.scope_id, reference)
        queue = deque([start])
        records: dict[bytes, dict[str, Any]] = {}
        while queue:
            record = queue.popleft()
            key = canonical_bytes(pin(record))
            if key in records:
                continue
            if len(records) >= _MAX_LINEAGE_NODES:
                raise StorageError("E_BUDGET_EXHAUSTED", "The claim correction graph exceeds its node budget.")
            _read_index(view, record)
            if (
                canonical_bytes(record["body"]["subject"]) != canonical_bytes(start["body"]["subject"])
                or record["body"]["predicate"] != start["body"]["predicate"]
            ):
                raise _invalid()
            records[key] = record
            predecessors = record.get("supersedes", [])
            if len({_identity(ref) for ref in predecessors}) != len(predecessors):
                raise _invalid()
            for ref in predecessors:
                prior = read_claim(view, self.scope_id, ref)
                if prior["body"]["proposition_version"] == record["body"]["proposition_version"]:
                    raise _invalid()
                queue.append(prior)
            for index in view.watchers(_predecessor_watch(self.scope_id, pin(record))):
                child = _from_projection(view, self.scope_id, index)
                if pin(record) not in child.get("supersedes", []):
                    raise _invalid()
                queue.append(child)

        # Deterministic parent-before-child order does not interpret version
        # strings, arrival timestamps or IDs as authority between branches.
        remaining = {
            key: {canonical_bytes(ref) for ref in value.get("supersedes", [])}
            for key, value in records.items()
        }
        ordered: list[dict[str, Any]] = []
        while remaining:
            ready = sorted(key for key, parents in remaining.items() if not parents)
            if not ready:
                raise _invalid("The claim correction history contains a cycle or a missing predecessor.")
            for key in ready:
                ordered.append(records[key])
                del remaining[key]
            for parents in remaining.values():
                parents.difference_update(ready)
        return ordered

    def revisions(self, reference: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the connected correction history, retaining competing branches."""
        ref = _reference(self.scope_id, reference)
        with self._storage.snapshot() as view:
            return self._lineage(view, ref)

    def heads(self, reference: dict[str, Any]) -> list[dict[str, Any]]:
        """Return all unsuperseded branch tips; none is established as true."""
        records = self.revisions(reference)
        predecessors = {canonical_bytes(ref) for record in records for ref in record.get("supersedes", [])}
        return [record for record in records if canonical_bytes(pin(record)) not in predecessors]
